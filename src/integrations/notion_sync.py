"""
Notion integration for reMarkable notebook text export.

This module syncs extracted handwritten text from reMarkable notebooks to Notion,
creating a page for each notebook with content organized by pages in reverse order
(latest page first) using toggle blocks.
"""

import os
import re
import logging
import sqlite3
import time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from .notion_markdown import MarkdownToNotionConverter
from .notion_incremental import NotionSyncTracker, should_sync_notebook, log_sync_decision
from ..core.notebook_paths import update_notebook_metadata

try:
    from notion_client import Client
    from notion_client.errors import APIResponseError
    NOTION_AVAILABLE = True
except ImportError:
    NOTION_AVAILABLE = False
    Client = None
    APIResponseError = Exception

logger = logging.getLogger(__name__)

def parse_remarkable_timestamp(timestamp_str: Optional[str]) -> Optional[datetime]:
    """Parse reMarkable timestamp (milliseconds since Unix epoch)."""
    if not timestamp_str or not timestamp_str.isdigit():
        return None
    
    try:
        # reMarkable uses millisecond timestamps
        timestamp_seconds = int(timestamp_str) / 1000
        return datetime.fromtimestamp(timestamp_seconds)
    except (ValueError, OSError):
        return None

def parse_path_tags(full_path: Optional[str]) -> List[str]:
    """Parse reMarkable path into tags by splitting on '/'."""
    if not full_path:
        return []
    
    # Split path and filter out empty parts
    path_parts = [part.strip() for part in full_path.split('/') if part.strip()]
    
    # Remove the notebook name itself (usually the last part)
    # Keep only folder structure as tags
    if len(path_parts) > 1:
        return path_parts[:-1]  # All parts except the last (which is the notebook name)
    elif len(path_parts) == 1:
        return []  # Root level notebook, no folder tags
    else:
        return []

@dataclass
class NotebookPage:
    """Represents a single page from a notebook."""
    page_number: int
    text: str
    confidence: float
    page_uuid: str

@dataclass
class NotebookMetadata:
    """Represents metadata for a notebook from reMarkable."""
    uuid: str
    name: str
    full_path: str
    last_modified: Optional[datetime]
    last_opened: Optional[datetime]
    path_tags: List[str]

@dataclass
class Notebook:
    """Represents a complete notebook with all its pages."""
    uuid: str
    name: str
    pages: List[NotebookPage]
    total_pages: int
    metadata: Optional[NotebookMetadata] = None

class NotionNotebookSync:
    """Syncs reMarkable notebook text to Notion database."""
    
    def __init__(self, notion_token: str, database_id: str, verify_ssl: bool = True):
        """
        Initialize Notion sync client.
        
        Args:
            notion_token: Notion integration token
            database_id: Notion database ID where notebooks will be created
            verify_ssl: Whether to verify SSL certificates (default: True)
        """
        if not NOTION_AVAILABLE:
            raise ImportError("notion-client package not installed. Run: pip install notion-client")
        
        # Configure SSL verification
        import httpx
        if verify_ssl:
            self.client = Client(auth=notion_token)
        else:
            # Create client with SSL verification disabled
            logger.warning("⚠️ SSL verification disabled for Notion API calls")
            http_client = httpx.Client(verify=False)
            self.client = Client(auth=notion_token, client=http_client)
            
        self.database_id = database_id
        self.markdown_converter = MarkdownToNotionConverter()
        self.sync_tracker = None  # Will be set when db_manager is available

        # Append-only audit trail of every Notion object this session creates/updates/
        # deletes, so duplicate blocks/pages can be found and cleaned up afterwards.
        self.run_id = f"{datetime.now():%Y%m%dT%H%M%S}-{os.getpid()}"
        self.audit_db_path = os.path.join('data', 'remarkable_pipeline.db')
        self._ensure_audit_table()
        logger.info(f"🧾 Notion sync audit enabled — run_id={self.run_id} "
                    f"(table notion_sync_audit in {self.audit_db_path})")

    def _ensure_audit_table(self) -> None:
        """Create the append-only notion_sync_audit table if it doesn't exist."""
        try:
            con = sqlite3.connect(self.audit_db_path)
            con.execute('''
                CREATE TABLE IF NOT EXISTS notion_sync_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    operation TEXT NOT NULL,
                    notebook_uuid TEXT,
                    notebook_name TEXT,
                    page_number INTEGER,
                    notion_page_id TEXT,
                    notion_block_id TEXT,
                    possible_duplicate INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            con.execute('CREATE INDEX IF NOT EXISTS idx_notion_audit_run ON notion_sync_audit(run_id)')
            con.execute('CREATE INDEX IF NOT EXISTS idx_notion_audit_nb ON notion_sync_audit(notebook_uuid)')
            con.commit()
            con.close()
        except Exception as e:
            logger.warning(f"⚠️ Could not ensure notion_sync_audit table: {e}")

    def _audit(self, operation: str, notebook_uuid: str = None, notebook_name: str = None,
               page_number: int = None, notion_page_id: str = None, notion_block_id: str = None,
               possible_duplicate: bool = False) -> None:
        """Record one Notion write to the audit trail. Never raises (must not break a sync)."""
        try:
            con = sqlite3.connect(self.audit_db_path)
            con.execute('''
                INSERT INTO notion_sync_audit
                (run_id, operation, notebook_uuid, notebook_name, page_number,
                 notion_page_id, notion_block_id, possible_duplicate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (self.run_id, operation, notebook_uuid, notebook_name, page_number,
                  notion_page_id, notion_block_id, 1 if possible_duplicate else 0))
            con.commit()
            con.close()
        except Exception as e:
            logger.warning(f"⚠️ notion audit write failed ({operation}): {e}")
        # Surface in the live log too (each block_append = one block created on Notion)
        dup = " ⚠️ POSSIBLE DUPLICATE" if possible_duplicate else ""
        logger.info(f"🧾 audit[{self.run_id}] {operation} nb='{notebook_name}' "
                    f"page={page_number} page_id={notion_page_id} block={notion_block_id}{dup}")

    def _audit_created_page_blocks(self, page_id: str, notebook) -> None:
        """After a fresh page create, list its children and record each toggle block's ID."""
        try:
            cursor = None
            results = []
            while True:
                resp = self.client.blocks.children.list(
                    block_id=page_id, start_cursor=cursor) if cursor \
                    else self.client.blocks.children.list(block_id=page_id)
                results.extend(resp.get("results", []))
                if resp.get("has_more") and resp.get("next_cursor"):
                    cursor = resp["next_cursor"]
                else:
                    break
            for block in results:
                if block.get("type") != "toggle":
                    continue
                rich = block.get("toggle", {}).get("rich_text", [])
                title = rich[0].get("text", {}).get("content", "") if rich else ""
                m = re.search(r"Page\s+(\d+)", title)
                page_num = int(m.group(1)) if m else None
                self._audit('block_append', notebook_uuid=getattr(notebook, 'uuid', None),
                            notebook_name=getattr(notebook, 'name', None), page_number=page_num,
                            notion_page_id=page_id, notion_block_id=block.get("id"))
        except Exception as e:
            logger.warning(f"⚠️ Could not audit created page blocks for {page_id}: {e}")

    def refresh_notion_metadata_for_specific_notebooks(self, db_connection, notebook_uuids: set) -> int:
        """Refresh Notion metadata properties only for specific notebooks."""
        if not notebook_uuids:
            logger.debug("No notebooks specified for Notion metadata refresh")
            return 0
            
        refreshed_count = 0
        logger.info(f"🔄 Refreshing Notion metadata for {len(notebook_uuids)} changed notebooks...")
        
        # Fetch notebooks that have changed metadata
        notebooks = self.fetch_notebooks_from_db(db_connection, refresh_changed_metadata=False)
        changed_notebooks = [nb for nb in notebooks if nb.uuid in notebook_uuids]
        
        for notebook in changed_notebooks:
            try:
                existing_page_id = self.find_existing_page(notebook.uuid)
                
                if existing_page_id:
                    logger.debug(f"📝 Updating Notion metadata for: {notebook.name}")
                    
                    # Build metadata properties
                    properties = {
                        "Total Pages": {"number": notebook.total_pages},
                        "Last Updated": {"date": {"start": datetime.now().isoformat()}}
                    }
                    
                    if notebook.metadata:
                        # Add path tags
                        if notebook.metadata.path_tags:
                            properties["Tags"] = {
                                "multi_select": [
                                    {"name": tag} for tag in notebook.metadata.path_tags
                                ]
                            }
                        
                        # Add last modified date
                        if notebook.metadata.last_modified:
                            properties["Last Modified"] = {
                                "date": {
                                    "start": notebook.metadata.last_modified.isoformat()
                                }
                            }
                        
                        # Add last viewed date
                        if notebook.metadata.last_opened:
                            properties["Last Viewed"] = {
                                "date": {
                                    "start": notebook.metadata.last_opened.isoformat()
                                }
                            }
                    
                    # Update only properties, not content
                    self.client.pages.update(page_id=existing_page_id, properties=properties)
                    refreshed_count += 1
                    
                else:
                    logger.debug(f"⚠️ No existing Notion page found for: {notebook.name}")
                    
            except Exception as e:
                logger.error(f"Failed to update Notion metadata for {notebook.name}: {e}")
        
        logger.info(f"✅ Refreshed Notion metadata for {refreshed_count} notebooks")
        return refreshed_count
        
    def fetch_notebooks_from_db(self, db_connection, refresh_changed_metadata: bool = False) -> List[Notebook]:
        """Fetch all notebooks with extracted text from database."""
        
        cursor = db_connection.cursor()
        
        # Get all notebooks with text and their metadata
        cursor.execute('''
            SELECT 
                nte.notebook_uuid, 
                nte.notebook_name, 
                nte.page_number, 
                nte.text, 
                nte.confidence, 
                nte.page_uuid,
                nm.full_path,
                nm.last_modified,
                nm.last_opened
            FROM notebook_text_extractions nte
            LEFT JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
            WHERE nte.text IS NOT NULL AND length(nte.text) > 0
            ORDER BY nte.notebook_name, nte.page_number
        ''')
        
        rows = cursor.fetchall()
        notebooks_dict = {}
        
        for uuid, name, page_num, text, confidence, page_uuid, full_path, last_modified, last_opened in rows:
            if uuid not in notebooks_dict:
                # Parse metadata
                metadata = NotebookMetadata(
                    uuid=uuid,
                    name=name,
                    full_path=full_path or "",
                    last_modified=parse_remarkable_timestamp(last_modified),
                    last_opened=parse_remarkable_timestamp(last_opened),
                    path_tags=parse_path_tags(full_path)
                )
                
                notebooks_dict[uuid] = {
                    'uuid': uuid,
                    'name': name,
                    'pages': [],
                    'metadata': metadata
                }
            
            notebooks_dict[uuid]['pages'].append(NotebookPage(
                page_number=page_num,
                text=text,
                confidence=confidence or 0.0,
                page_uuid=page_uuid
            ))
        
        # Convert to Notebook objects
        notebooks = []
        for nb_data in notebooks_dict.values():
            # Sort pages in reverse order (latest page first)
            pages = sorted(nb_data['pages'], key=lambda p: p.page_number, reverse=True)
            
            notebook = Notebook(
                uuid=nb_data['uuid'],
                name=nb_data['name'],
                pages=pages,
                total_pages=len(pages),
                metadata=nb_data['metadata']
            )
            notebooks.append(notebook)
        
        return notebooks
    
    def create_notebook_page(self, notebook: Notebook) -> str:
        """
        Create a Notion page for a notebook.
        
        Args:
            notebook: Notebook object with all page data
            
        Returns:
            Notion page ID of created page
        """
        try:
            # Prepare page properties
            properties = {
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": notebook.name
                            }
                        }
                    ]
                },
                "Notebook UUID": {
                    "rich_text": [
                        {
                            "text": {
                                "content": notebook.uuid
                            }
                        }
                    ]
                },
                "Total Pages": {
                    "number": notebook.total_pages
                },
                "Last Updated": {
                    "date": {
                        "start": datetime.now().isoformat()
                    }
                }
            }
            
            # Add metadata properties if available
            if notebook.metadata:
                # Add path information
                if notebook.metadata.full_path:
                    properties["reMarkable Path"] = {
                        "rich_text": [
                            {
                                "text": {
                                    "content": notebook.metadata.full_path
                                }
                            }
                        ]
                    }
                
                # Add path tags
                if notebook.metadata.path_tags:
                    properties["Tags"] = {
                        "multi_select": [
                            {"name": tag} for tag in notebook.metadata.path_tags
                        ]
                    }
                
                # Add last modified date
                if notebook.metadata.last_modified:
                    properties["Last Modified"] = {
                        "date": {
                            "start": notebook.metadata.last_modified.isoformat()
                        }
                    }
                
                # Add last opened date
                if notebook.metadata.last_opened:
                    properties["Last Viewed"] = {
                        "date": {
                            "start": notebook.metadata.last_opened.isoformat()
                        }
                    }
            
            
            # Create children blocks (page content)
            children = self._create_page_content_blocks(notebook)
            
            # Create the page
            response = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=children
            )
            
            page_id = response["id"]
            logger.info(f"✅ Created Notion page for notebook: {notebook.name} (page_id={page_id})")
            self._audit('page_create', notebook_uuid=getattr(notebook, 'uuid', None),
                        notebook_name=notebook.name, notion_page_id=page_id)
            self._audit_created_page_blocks(page_id, notebook)
            return page_id

        except APIResponseError as e:
            logger.error(f"❌ Failed to create Notion page for {notebook.name}: {e}")
            raise
    
    def _create_page_content_blocks(self, notebook: Notebook, max_pages: int = 50) -> List[Dict]:
        """Create Notion blocks for notebook page content."""
        blocks = []
        
        # Add header with notebook info
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"📓 {notebook.name}"
                        }
                    }
                ]
            }
        })
        
        # Add summary with metadata info
        total_pages = notebook.total_pages
        showing_pages = min(total_pages, max_pages)
        truncated = total_pages > max_pages
        
        summary_parts = [f"Total pages: {total_pages}", f"UUID: {notebook.uuid[:8]}..."]
        
        # Add metadata info to summary
        if notebook.metadata:
            if notebook.metadata.full_path:
                summary_parts.append(f"Path: {notebook.metadata.full_path}")
            if notebook.metadata.last_modified:
                summary_parts.append(f"Modified: {notebook.metadata.last_modified.strftime('%Y-%m-%d')}")
            if notebook.metadata.path_tags:
                summary_parts.append(f"Tags: {', '.join(notebook.metadata.path_tags)}")
        
        if truncated:
            summary_parts.append(f"Showing latest {showing_pages} pages (truncated)")
        
        summary_text = " | ".join(summary_parts)
        
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": summary_text
                        }
                    }
                ]
            }
        })
        
        # Add truncation warning if needed
        if truncated:
            blocks.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": f"⚠️ This notebook has {total_pages} pages, but only the latest {max_pages} are shown due to Notion API limits. Use smaller chunks or filter pages if you need to see more content."
                            }
                        }
                    ],
                    "icon": {
                        "emoji": "⚠️"
                    },
                    "color": "yellow"
                }
            })
        
        # Add divider
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })
        
        # Add pages (limited to max_pages, latest first)
        pages_to_show = sorted(notebook.pages, key=lambda p: p.page_number, reverse=True)[:max_pages]
        for page in pages_to_show:
            page_toggle = self._create_page_toggle_block(page)
            blocks.append(page_toggle)
        
        return blocks
    
    def _update_changed_pages_only(self, page_id: str, notebook: Notebook, changed_pages: set, sync_metadata: dict = None) -> None:
        """Update only the blocks for pages that have changed."""
        # Get all current blocks
        blocks_response = self.client.blocks.children.list(block_id=page_id)
        current_blocks = blocks_response["results"]
        
        # Find page toggle blocks to update/replace
        blocks_to_delete = []
        page_blocks_map = {}  # page_number -> block_id
        header_blocks = []  # Keep header, summary, divider blocks
        
        for block in current_blocks:
            if block["type"] == "toggle":
                # Extract page number from toggle title
                rich_text = block.get("toggle", {}).get("rich_text", [])
                if rich_text:
                    title = rich_text[0].get("text", {}).get("content", "")
                    # Parse "📄 Page X" format
                    if "📄 Page " in title:
                        try:
                            page_num = int(title.split("📄 Page ")[1].split(" ")[0].split("(")[0])
                            page_blocks_map[page_num] = block["id"]
                        except (ValueError, IndexError):
                            # If we can't parse page number, mark for deletion
                            blocks_to_delete.append(block["id"])
            else:
                # Keep header, summary, divider blocks
                header_blocks.append(block)
        
        # Audit existing toggle blocks whose page number could NOT be parsed. These are
        # never deleted below (they're not in page_blocks_map), so if one of their pages
        # is re-synced a duplicate block is created. Record them as cleanup candidates.
        if blocks_to_delete:
            logger.warning(f"⚠️ {notebook.name}: {len(blocks_to_delete)} existing toggle block(s) "
                           f"have an unrecognized title format — they will NOT be replaced and may "
                           f"already be (or become) duplicates. Recorded in notion_sync_audit.")
            for unmatched_id in blocks_to_delete:
                self._audit('unmatched_existing_block', notebook_uuid=notebook.uuid,
                            notebook_name=notebook.name, notion_page_id=page_id,
                            notion_block_id=unmatched_id, possible_duplicate=True)

        # Delete blocks for changed pages
        deleted_page_nums = set()
        for page_num in changed_pages:
            if page_num in page_blocks_map:
                self.client.blocks.delete(block_id=page_blocks_map[page_num])
                deleted_page_nums.add(page_num)
                self._audit('block_delete', notebook_uuid=notebook.uuid, notebook_name=notebook.name,
                            page_number=page_num, notion_page_id=page_id,
                            notion_block_id=page_blocks_map[page_num])
                logger.debug(f"🗑️ Deleted old content for page {page_num}")
        
        # Create new blocks for changed pages in reverse order (newest first)
        changed_pages_list = [page for page in notebook.pages if page.page_number in changed_pages]

        # Filter out blank/placeholder pages to prevent syncing empty content
        valid_pages = []
        skipped_pages = []
        for page in changed_pages_list:
            if not page.text or len(page.text.strip()) == 0:
                # Skip truly empty pages
                skipped_pages.append(page.page_number)
                logger.warning(f"⚠️ Skipping page {page.page_number} with no content")
            elif 'This appears to be a blank' in page.text or 'completely empty page' in page.text:
                # Skip Claude's blank page placeholders
                skipped_pages.append(page.page_number)
                logger.warning(f"⚠️ Skipping blank placeholder page {page.page_number} from sync")
            else:
                # Sync all pages with actual content, regardless of length
                valid_pages.append(page)

        if skipped_pages:
            logger.info(f"ℹ️ Skipped {len(skipped_pages)} blank/placeholder pages: {skipped_pages}")

        # Prioritize newly processed pages over backlog
        # Use passed sync_metadata instead of trying to get from notebook.metadata
        if sync_metadata is None:
            sync_metadata = {}
        newly_processed = set(sync_metadata.get('newly_processed', []))
        backlog = set(sync_metadata.get('backlog', []))

        # Split valid pages into priority groups
        new_pages = [p for p in valid_pages if p.page_number in newly_processed]
        backlog_pages = [p for p in valid_pages if p.page_number in backlog]

        # Sort each group by page number (newest first)
        new_pages_sorted = sorted(new_pages, key=lambda p: p.page_number, reverse=True)
        backlog_pages_sorted = sorted(backlog_pages, key=lambda p: p.page_number, reverse=True)

        # Apply rate limiting: max pages per sync to avoid Notion API limits
        MAX_PAGES_PER_SYNC = 50
        DELAY_BETWEEN_PAGES = 0.35  # ~3 requests/second to stay under Notion's rate limit

        # Prioritize: sync ALL new pages first, then fill remaining slots with backlog
        changed_pages_sorted = new_pages_sorted.copy()
        remaining_slots = MAX_PAGES_PER_SYNC - len(new_pages_sorted)

        if remaining_slots > 0 and backlog_pages_sorted:
            backlog_to_sync = backlog_pages_sorted[:remaining_slots]
            changed_pages_sorted.extend(backlog_to_sync)
            logger.info(f"📊 Syncing {len(new_pages_sorted)} new pages + {len(backlog_to_sync)} backlog pages")
        elif len(new_pages_sorted) > MAX_PAGES_PER_SYNC:
            logger.warning(f"⚠️ {len(new_pages_sorted)} new pages exceeds limit, syncing first {MAX_PAGES_PER_SYNC}")
            changed_pages_sorted = new_pages_sorted[:MAX_PAGES_PER_SYNC]
        else:
            logger.info(f"📊 Syncing {len(new_pages_sorted)} new pages")

        total_pending = len(new_pages_sorted) + len(backlog_pages_sorted)
        if total_pending > len(changed_pages_sorted):
            logger.warning(f"⚠️ {total_pending - len(changed_pages_sorted)} pages remaining for next sync")

        # Find insertion point (after header blocks, before existing page blocks)
        insertion_point = len(header_blocks)  # Insert after header/summary/divider

        # Track the last inserted block to maintain descending order
        last_inserted_block_id = header_blocks[-1]["id"] if header_blocks else None

        # Insert new pages one by one in descending order (highest page number first)
        for i, page in enumerate(changed_pages_sorted, 1):
            page_toggle = self._create_page_toggle_block(page)

            # Rate limiting: add delay between API calls
            if i > 1:  # Don't delay before first request
                time.sleep(DELAY_BETWEEN_PAGES)

            # Insert after the last inserted block to maintain descending order
            result = self.client.blocks.children.append(
                block_id=page_id,
                children=[page_toggle],
                after=last_inserted_block_id
            )

            # Capture the block ID for linking and update anchor for next insertion
            if result.get("results") and len(result["results"]) > 0:
                block_id = result["results"][0]["id"]
                last_inserted_block_id = block_id  # Update anchor for next page
                self._store_page_block_mapping(notebook.uuid, page.page_number, page_id, block_id, page.text)
                # A new block was created. If we did NOT delete a prior block for this page
                # but the page DID already have a (recognized) block, that's a duplicate.
                # We also flag it when unrecognized-format blocks were present for this page.
                is_possible_dup = (page.page_number not in deleted_page_nums
                                   and (page.page_number in page_blocks_map or len(blocks_to_delete) > 0))
                self._audit('block_append', notebook_uuid=notebook.uuid, notebook_name=notebook.name,
                            page_number=page.page_number, notion_page_id=page_id,
                            notion_block_id=block_id, possible_duplicate=is_possible_dup)
                logger.debug(f"📝 Inserted page {page.page_number} ({i}/{len(changed_pages_sorted)}) with block ID {block_id}")
            else:
                logger.debug(f"📝 Inserted page {page.page_number} ({i}/{len(changed_pages_sorted)}) at top of page list")

        if changed_pages_sorted:
            logger.info(f"✅ Updated {len(changed_pages_sorted)} changed pages in Notion (newest first)")
    
    def _store_page_block_mapping(self, notebook_uuid: str, page_number: int, notion_page_id: str, notion_block_id: str, page_content: str = None):
        """Store the mapping between notebook page and Notion block ID, and track synced content."""
        try:
            # We need database access - this should be passed in or made available
            from ..core.database import DatabaseManager
            import hashlib
            db = DatabaseManager('./data/remarkable_pipeline.db')

            with db.get_connection() as conn:
                cursor = conn.cursor()

                # Store in notion_page_blocks table (legacy)
                cursor.execute('''
                    INSERT OR REPLACE INTO notion_page_blocks
                    (notebook_uuid, page_number, notion_page_id, notion_block_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (notebook_uuid, page_number, notion_page_id, notion_block_id))

                # Also update notion_page_sync table with the block ID, sync timestamp, and synced content (legacy)
                cursor.execute('''
                    UPDATE notion_page_sync
                    SET notion_block_id = ?, last_synced = CURRENT_TIMESTAMP, last_synced_content = ?
                    WHERE notebook_uuid = ? AND page_number = ?
                ''', (notion_block_id, page_content, notebook_uuid, page_number))

                # NEW: Store in page_sync_records table for per-page tracking
                if page_content:
                    content_hash = hashlib.sha256(page_content.encode('utf-8')).hexdigest()
                    cursor.execute('''
                        INSERT OR REPLACE INTO page_sync_records
                        (notebook_uuid, page_number, content_hash, target_name, notion_page_id,
                         notion_block_id, status, synced_at, updated_at)
                        VALUES (?, ?, ?, 'notion', ?, ?, 'success', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    ''', (notebook_uuid, page_number, content_hash, notion_page_id, notion_block_id))
                    logger.debug(f"✅ Created page sync record: {notebook_uuid} page {page_number}")

                conn.commit()
                logger.debug(f"📎 Stored block mapping: {notebook_uuid} page {page_number} -> {notion_block_id}")

        except Exception as e:
            logger.warning(f"Failed to store block mapping for {notebook_uuid} page {page_number}: {e}")
    
    def _create_page_toggle_block(self, page: NotebookPage) -> Dict:
        """Create a toggle block for a single notebook page with markdown formatting."""
        # Create confidence indicator
        confidence_emoji = "🟢" if page.confidence > 0.8 else "🟡" if page.confidence > 0.5 else "🔴"
        confidence_text = f" ({confidence_emoji} {page.confidence:.1f})" if page.confidence > 0 else ""
        
        # Use markdown converter to create properly formatted blocks
        children = self.markdown_converter.text_to_notion_blocks(page.text, max_blocks=100)
        
        # Create the toggle block
        return {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"📄 Page {page.page_number}{confidence_text}"
                        },
                        "annotations": {
                            "bold": True
                        }
                    }
                ],
                "children": children
            }
        }
    
    def update_existing_page(self, page_id: str, notebook: Notebook, changed_pages: set = None, sync_metadata: dict = None) -> None:
        """Update an existing Notion page with incremental content changes."""
        try:
            # Update page properties
            properties = {
                "Total Pages": {
                    "number": notebook.total_pages
                },
                "Last Updated": {
                    "date": {
                        "start": datetime.now().isoformat()
                    }
                }
            }
            
            # Add metadata properties if available
            if notebook.metadata:
                # Add path information
                if notebook.metadata.full_path:
                    properties["reMarkable Path"] = {
                        "rich_text": [
                            {
                                "text": {
                                    "content": notebook.metadata.full_path
                                }
                            }
                        ]
                    }
                
                # Add path tags
                if notebook.metadata.path_tags:
                    properties["Tags"] = {
                        "multi_select": [
                            {"name": tag} for tag in notebook.metadata.path_tags
                        ]
                    }
                
                # Add last modified date
                if notebook.metadata.last_modified:
                    properties["Last Modified"] = {
                        "date": {
                            "start": notebook.metadata.last_modified.isoformat()
                        }
                    }
                
                # Add last opened date
                if notebook.metadata.last_opened:
                    properties["Last Viewed"] = {
                        "date": {
                            "start": notebook.metadata.last_opened.isoformat()
                        }
                    }
            
            # Update properties
            self.client.pages.update(page_id=page_id, properties=properties)
            self._audit('page_update', notebook_uuid=getattr(notebook, 'uuid', None),
                        notebook_name=notebook.name, notion_page_id=page_id)

            # Handle content updates incrementally
            if changed_pages is None:
                # Full refresh - delete all and recreate (fallback behavior)
                logger.info(f"🔄 Full content refresh for {notebook.name}")
                blocks_response = self.client.blocks.children.list(block_id=page_id)

                # Delete existing blocks
                for block in blocks_response["results"]:
                    self.client.blocks.delete(block_id=block["id"])
                    self._audit('block_delete', notebook_uuid=getattr(notebook, 'uuid', None),
                                notebook_name=notebook.name, notion_page_id=page_id,
                                notion_block_id=block["id"])

                # Add new content
                children = self._create_page_content_blocks(notebook)
                self.client.blocks.children.append(block_id=page_id, children=children)
                # Capture the freshly-created block IDs for the audit trail
                self._audit_created_page_blocks(page_id, notebook)
            else:
                # Incremental update - only update changed pages
                logger.info(f"📝 Incremental update for {notebook.name} - {len(changed_pages)} pages changed")
                self._update_changed_pages_only(page_id, notebook, changed_pages, sync_metadata)
            
            logger.info(f"✅ Updated Notion page for notebook: {notebook.name}")
            
        except APIResponseError as e:
            logger.error(f"❌ Failed to update Notion page for {notebook.name}: {e}")
            raise
    
    def find_existing_page(self, notebook_uuid: str) -> Optional[str]:
        """Find existing Notion page for a notebook by UUID."""
        try:
            # Search for pages with matching UUID
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Notebook UUID",
                    "rich_text": {
                        "equals": notebook_uuid
                    }
                }
            )
            
            if response["results"]:
                page = response["results"][0]
                return page["id"]
            return None
            
        except APIResponseError as e:
            logger.error(f"❌ Failed to search for existing page: {e}")
            return None
    
    def sync_notebook(self, notebook: Notebook, update_existing: bool = True) -> str:
        """
        Sync a single notebook to Notion.
        
        Args:
            notebook: Notebook to sync
            update_existing: Whether to update existing pages
            
        Returns:
            Notion page ID
        """
        existing_page_id = self.find_existing_page(notebook.uuid)
        
        if existing_page_id and update_existing:
            logger.info(f"📝 Updating existing page for: {notebook.name}")
            self.update_existing_page(existing_page_id, notebook)
            return existing_page_id
        elif existing_page_id:
            logger.info(f"⏭️ Skipping existing page for: {notebook.name}")
            return existing_page_id
        else:
            logger.info(f"📄 Creating new page for: {notebook.name}")
            return self.create_notebook_page(notebook)
    
    def sync_notebook_smart(self, notebook: Notebook, changes: Dict, update_existing: bool = True) -> str:
        """
        Smart sync that handles incremental updates based on detected changes.
        
        Args:
            notebook: Notebook to sync
            changes: Change analysis from sync tracker
            update_existing: Whether to update existing pages
            
        Returns:
            Notion page ID
        """
        if changes['is_new']:
            # New notebook - create full page and track sync state
            page_id = self.create_notebook_page(notebook)
            self._track_sync_completion(notebook, page_id, changes)
            return page_id
        
        elif changes['content_changed'] or changes['metadata_changed']:
            if update_existing:
                # Update existing page
                page_id = changes['notion_page_id']
                self.update_existing_page(page_id, notebook)
                self._track_sync_completion(notebook, page_id, changes)
                return page_id
            else:
                logger.info(f"⏭️ Skipping update for: {notebook.name} (update_existing=False)")
                return changes['notion_page_id']
        
        else:
            # No changes needed
            return changes['notion_page_id']
    
    def _track_sync_completion(self, notebook: Notebook, page_id: str, changes: Dict):
        """Track successful sync completion for incremental updates."""
        if self.sync_tracker:
            # Mark notebook as synced
            self.sync_tracker.mark_notebook_synced(
                notebook.uuid,
                page_id, 
                changes['current_content_hash'],
                changes['current_metadata_hash'],
                changes['current_total_pages']
            )
            
            # Mark individual pages as synced
            for page in notebook.pages:
                # Create tuple matching the expected format: (notebook_uuid, notebook_name, page_uuid, confidence, page_number, text, full_path, last_modified, last_opened)
                page_data = (notebook.uuid, notebook.name, page.page_uuid, page.confidence, page.page_number, page.text, None, None, None)
                page_content_hash = self.sync_tracker._calculate_page_content_hash(page_data)
                self.sync_tracker.mark_page_synced(
                    notebook.uuid,
                    page.page_number,
                    page.page_uuid,
                    page_content_hash,
                    page_content=page.text
                )
    
    def sync_all_notebooks(self, db_connection, update_existing: bool = True, 
                          exclude_patterns: Optional[List[str]] = None, 
                          force_update: bool = False) -> Dict[str, str]:
        """
        Sync all notebooks to Notion with intelligent incremental updates.
        
        Args:
            db_connection: Database connection
            update_existing: Whether to update existing pages
            exclude_patterns: List of patterns to exclude from sync
            force_update: If True, update all notebooks regardless of changes
            
        Returns:
            Dictionary mapping notebook UUIDs to Notion page IDs
        """
        # Initialize sync tracker - get the database file path
        from ..core.database import DatabaseManager
        try:
            # Try to get database path from connection
            db_list = db_connection.execute("PRAGMA database_list").fetchall()
            db_path = None
            for row in db_list:
                if row[1] == 'main':  # main database
                    db_path = row[2]
                    break
            
            if not db_path:
                # Fallback - use a default path
                db_path = './data/remarkable_pipeline.db'
                
            db_manager = DatabaseManager(db_path)
            self.sync_tracker = NotionSyncTracker(db_manager)
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize incremental sync tracker: {e}")
            logger.info("📄 Falling back to simple sync mode")
            self.sync_tracker = None
        
        if exclude_patterns is None:
            exclude_patterns = ['Luzerner Todesmelodie']  # Exclude the book that was incorrectly processed
        
        notebooks = self.fetch_notebooks_from_db(db_connection)
        
        # Filter out excluded notebooks
        filtered_notebooks = []
        for notebook in notebooks:
            exclude = False
            for pattern in exclude_patterns:
                if pattern.lower() in notebook.name.lower():
                    logger.info(f"⏭️ Excluding notebook: {notebook.name} (matches pattern: {pattern})")
                    exclude = True
                    break
            if not exclude:
                filtered_notebooks.append(notebook)
        
        logger.info(f"🚀 Intelligent sync: {len(filtered_notebooks)} notebooks to analyze...")
        
        if self.sync_tracker is None:
            # Fallback to simple sync mode
            logger.info(f"📄 Using simple sync mode for {len(filtered_notebooks)} notebooks...")
            
            synced_pages = {}
            for i, notebook in enumerate(filtered_notebooks, 1):
                logger.info(f"📖 Processing {i}/{len(filtered_notebooks)}: {notebook.name} ({notebook.total_pages} pages)")
                
                try:
                    page_id = self.sync_notebook(notebook, update_existing)
                    synced_pages[notebook.uuid] = page_id
                    logger.info(f"✅ Synced: {notebook.name}")
                except Exception as e:
                    logger.error(f"❌ Failed to sync {notebook.name}: {e}")
                    continue
            
            logger.info(f"🎉 Simple sync completed! {len(synced_pages)} notebooks synced to Notion")
            return synced_pages
        
        # Analyze which notebooks need syncing (smart mode)
        notebooks_to_sync = []
        skipped_count = 0
        
        for notebook in filtered_notebooks:
            should_sync, changes = should_sync_notebook(notebook.uuid, self.sync_tracker, force_update)
            log_sync_decision(notebook.name, notebook.uuid, should_sync, changes)
            
            if should_sync:
                notebooks_to_sync.append((notebook, changes))
            else:
                skipped_count += 1
        
        logger.info(f"📊 Analysis complete: {len(notebooks_to_sync)} to sync, {skipped_count} skipped (no changes)")
        
        synced_pages = {}
        for i, (notebook, changes) in enumerate(notebooks_to_sync, 1):
            logger.info(f"📖 Syncing {i}/{len(notebooks_to_sync)}: {notebook.name} ({notebook.total_pages} pages)")
            
            try:
                page_id = self.sync_notebook_smart(notebook, changes, update_existing)
                synced_pages[notebook.uuid] = page_id
                logger.info(f"✅ Synced: {notebook.name}")
            except Exception as e:
                logger.error(f"❌ Failed to sync {notebook.name}: {e}")
                continue
        
        logger.info(f"🎉 Smart sync completed! {len(synced_pages)} updated, {skipped_count} unchanged")
        return synced_pages


def sync_notebooks_to_notion(notion_token: str, database_id: str, db_connection, 
                            update_existing: bool = True, verify_ssl: bool = True) -> Dict[str, str]:
    """
    Convenience function to sync notebooks to Notion.
    
    Args:
        notion_token: Notion integration token
        database_id: Notion database ID
        db_connection: SQLite database connection
        update_existing: Whether to update existing pages
        verify_ssl: Whether to verify SSL certificates
        
    Returns:
        Dictionary mapping notebook UUIDs to Notion page IDs
    """
    sync_client = NotionNotebookSync(notion_token, database_id, verify_ssl=verify_ssl)
    return sync_client.sync_all_notebooks(db_connection, update_existing)