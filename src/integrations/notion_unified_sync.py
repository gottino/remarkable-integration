"""
Unified Notion integration for reMarkable Pipeline.

This module provides a unified sync target implementation for Notion,
integrating handwritten text from reMarkable notebooks with the unified sync system.
"""

import asyncio
import hashlib
import logging
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..core.sync_engine import SyncTarget, SyncItem, SyncResult, SyncStatus, SyncItemType
# Import the data classes we still need from legacy sync
from .notion_sync import Notebook, NotebookPage, NotebookMetadata
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class NotionSyncTarget(SyncTarget):
    """
    Notion implementation of the unified sync target interface.
    
    Syncs handwritten text from reMarkable notebooks to Notion pages
    with proper organization and incremental updates.
    """
    
    def __init__(self, notion_token: str, database_id: str,
                 tasks_database_id: Optional[str] = None,
                 db_connection: Optional[sqlite3.Connection] = None,
                 verify_ssl: bool = True):
        super().__init__("notion")
        self.notion_token = notion_token
        self.database_id = database_id
        self.tasks_database_id = tasks_database_id
        self.db_connection = db_connection
        self.verify_ssl = verify_ssl
        
        # For now, keep using legacy sync but we'll override the update method
        from .notion_sync import NotionNotebookSync
        self.notion_client = NotionNotebookSync(
            notion_token=notion_token,
            database_id=database_id,
            verify_ssl=verify_ssl
        )
        
        # Store SSL setting for any additional API calls
        self.verify_ssl = verify_ssl
        
        # Content hash cache to avoid duplicate computation
        self._content_hash_cache: Dict[str, str] = {}

        # Initialize todo sync service if tasks database ID is provided
        self.todo_sync = None
        if self.tasks_database_id:
            try:
                from .notion_todo_sync import NotionTodoSync
                # Use db_path from database connection or default
                db_path = './data/remarkable_pipeline.db'  # TODO: Get this from config
                self.todo_sync = NotionTodoSync(
                    notion_token=notion_token,
                    tasks_database_id=tasks_database_id,
                    db_path=db_path
                )
                self.logger.info("✅ Todo sync service initialized")
            except Exception as e:
                self.logger.error(f"❌ Failed to initialize todo sync: {e}")
                self.todo_sync = None
    
    async def sync_item(self, item: SyncItem) -> SyncResult:
        """Sync a single item to Notion."""
        try:
            if item.item_type == SyncItemType.NOTEBOOK:
                return await self._sync_notebook(item)
            elif item.item_type == SyncItemType.PAGE_TEXT:
                return await self._sync_page_text(item)
            elif item.item_type == SyncItemType.TODO:
                return await self._sync_todo(item)
            else:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': f'Unsupported item type for Notion: {item.item_type}'}
                )
        except Exception as e:
            self.logger.error(f"Error syncing {item.item_type} to Notion: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_notebook(self, item: SyncItem) -> SyncResult:
        """Sync a complete notebook to Notion."""
        try:
            notebook_data = item.data
            notebook_uuid = item.item_id

            # Create Notebook object from sync item data
            notebook = self._create_notebook_from_sync_item(notebook_data, notebook_uuid)

            if not notebook.pages:
                logger.warning(f"Notebook {notebook.name} has no pages with text content")
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={
                        'reason': 'No pages to sync',
                        'notebook_name': notebook.name,
                        'notebook_uuid': notebook_uuid,
                        'total_pages_processed': len(notebook_data.get('pages', []))
                    }
                )

            # Extract changed pages information for incremental sync
            changed_pages = notebook_data.get('changed_pages')

            # Ensure we never pass None to avoid full refresh - use empty set as fallback
            if changed_pages is None:
                changed_pages = set()  # Empty set = no specific pages changed, but avoid full refresh
                logger.info(f"🔍 DEBUG: changed_pages was None, using empty set fallback")

            logger.info(f"🔍 DEBUG: changed_pages = {changed_pages} (type: {type(changed_pages)})")

            # Check if notebook already exists in Notion
            existing_page_id = self.notion_client.find_existing_page(notebook_uuid)

            if existing_page_id:
                # Update existing page with incremental sync support
                logger.info(f"🔄 Calling update_existing_page with changed_pages: {changed_pages}")
                self.notion_client.update_existing_page(existing_page_id, notebook, changed_pages)
                logger.info(f"✅ Updated Notion page for notebook: {notebook.name}")
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id=existing_page_id,
                    metadata={
                        'notebook_name': notebook.name,
                        'total_pages': notebook.total_pages,
                        'action': 'updated'
                    }
                )
            else:
                # Create new page
                page_id = self.notion_client.create_notebook_page(notebook)
                logger.info(f"✅ Created Notion page for notebook: {notebook.name}")
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id=page_id,
                    metadata={
                        'notebook_name': notebook.name,
                        'total_pages': notebook.total_pages,
                        'action': 'created'
                    }
                )

        except Exception as e:
            self.logger.error(f"Failed to sync notebook {notebook_uuid} to Notion: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e),
                metadata={
                    'notebook_uuid': notebook_uuid,
                    'notebook_name': notebook_data.get('title', 'Unknown'),
                    'error_type': type(e).__name__,
                    'pages_count': len(notebook_data.get('pages', []))
                }
            )
    
    async def _sync_page_text(self, item: SyncItem) -> SyncResult:
        """Sync individual page text updates to Notion."""
        try:
            page_data = item.data
            notebook_uuid = page_data.get('notebook_uuid')
            page_number = page_data.get('page_number')
            
            if not notebook_uuid or page_number is None:
                return SyncResult(
                    status=SyncStatus.FAILED,
                    error_message="Missing notebook_uuid or page_number in page text data"
                )
            
            # Find the Notion page for this notebook
            existing_page_id = self.notion_client.find_existing_page(notebook_uuid)
            
            if not existing_page_id:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'Notebook not found in Notion - need full notebook sync first'}
                )
            
            # Get full notebook data for incremental update
            if self.db_connection:
                notebook = self._fetch_notebook_from_db(notebook_uuid)
                if notebook:
                    # Update just this page
                    changed_pages = {page_number}
                    self.notion_client.update_existing_page(existing_page_id, notebook, changed_pages)
                    
                    return SyncResult(
                        status=SyncStatus.SUCCESS,
                        target_id=existing_page_id,
                        metadata={
                            'notebook_name': notebook.name,
                            'updated_page': page_number,
                            'action': 'page_updated'
                        }
                    )
            
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message="Could not fetch notebook data for incremental update"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to sync page text to Notion: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e),
                metadata={
                    'error_type': type(e).__name__,
                    'item_type': 'page_text'
                }
            )

    async def _sync_todo(self, item: SyncItem) -> SyncResult:
        """Sync a todo to Notion Tasks database."""
        try:
            if not self.todo_sync:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'Todo sync not configured - missing tasks_database_id'}
                )

            todo_data = item.data
            todo_id = item.item_id

            # Extract todo information
            todo_text = todo_data.get('text', '')
            notebook_uuid = todo_data.get('notebook_uuid', '')
            page_number = todo_data.get('page_number', 0)
            completed = todo_data.get('completed', False)

            if not todo_text.strip():
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'Empty todo text'}
                )

            if completed:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'Todo already completed'}
                )

            # Get notebook name for context
            notebook_name = todo_data.get('notebook_name', 'Unknown Notebook')

            # Create todo tuple in format expected by legacy sync
            todo_tuple = (
                int(todo_id),  # todo_id
                todo_text,     # text
                todo_data.get('actual_date'),  # actual_date
                page_number,   # page_number
                todo_data.get('confidence', 0.0),  # confidence
                completed,     # completed
                notebook_name, # notebook_name
                todo_data.get('notion_page_id'),   # notion_page_id
                todo_data.get('notion_block_id'),  # notion_block_id
                todo_data.get('created_at', datetime.now().isoformat())  # created_at
            )

            # Export to Notion using legacy service
            self.logger.info(f"📝 Exporting todo to Notion Tasks: {todo_text[:50]}...")

            # Log block linking info for debugging
            notion_page_id = todo_data.get('notion_page_id')
            notion_block_id = todo_data.get('notion_block_id')
            if notion_page_id and notion_block_id:
                self.logger.info(f"   🔗 Block linking available: page {notion_page_id[:8]}... block {notion_block_id[:8]}...")
            else:
                self.logger.warning(f"   ⚠️ Block linking not available (page_id: {bool(notion_page_id)}, block_id: {bool(notion_block_id)})")

            notion_todo_id = self.todo_sync.export_todo_to_notion(todo_tuple, notebook_name)

            if notion_todo_id:
                self.logger.info(f"✅ Successfully exported todo to Notion Tasks")
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id=notion_todo_id,
                    metadata={
                        'todo_text': todo_text[:100],
                        'notebook_name': notebook_name,
                        'page_number': page_number,
                        'action': 'exported_to_tasks_db'
                    }
                )
            else:
                return SyncResult(
                    status=SyncStatus.FAILED,
                    error_message="Failed to export todo to Notion - no ID returned",
                    metadata={
                        'todo_text': todo_text[:100],
                        'notebook_name': notebook_name
                    }
                )

        except Exception as e:
            self.logger.error(f"Failed to sync todo {item.item_id}: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e),
                metadata={
                    'todo_id': item.item_id,
                    'error_type': type(e).__name__
                }
            )

    async def check_duplicate(self, content_hash: str) -> Optional[str]:
        """
        Check if content already exists in Notion.
        
        We use the content hash to check for duplicates by querying
        our sync tracking tables.
        """
        if not self.db_connection:
            return None
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute('''
                SELECT notion_page_id FROM notion_notebook_sync 
                WHERE content_hash = ?
            ''', (content_hash,))
            
            result = cursor.fetchone()
            return result[0] if result else None
            
        except Exception as e:
            self.logger.warning(f"Error checking duplicate in Notion: {e}")
            return None
    
    async def update_item(self, external_id: str, item: SyncItem) -> SyncResult:
        """Update an existing item in Notion."""
        # For Notion, update is the same as sync - we handle incrementally
        return await self.sync_item(item)
    
    async def delete_item(self, external_id: str) -> SyncResult:
        """
        Delete an item from Notion.
        
        Note: We don't automatically delete pages from Notion as they may contain
        user annotations. This would need manual confirmation.
        """
        return SyncResult(
            status=SyncStatus.SKIPPED,
            metadata={'reason': 'Notion page deletion requires manual confirmation'}
        )
    
    def _create_notebook_from_sync_item(self, notebook_data: Dict[str, Any], notebook_uuid: str) -> Notebook:
        """Create a Notebook object from sync item data."""
        notebook_name = notebook_data.get('title', notebook_data.get('notebook_name', 'Untitled'))
        pages_data = notebook_data.get('pages', [])

        self.logger.info(f"🔍 DEBUG: Creating notebook {notebook_name} (UUID: {notebook_uuid}) with {len(pages_data)} pages")
        for i, page in enumerate(pages_data[:3]):  # Log first 3 pages for debugging
            text_length = len(page.get('text', ''))
            text_preview = page.get('text', '')[:50].replace('\n', ' ')
            self.logger.info(f"   Page {page.get('page_number', i)}: '{text_preview}...' ({text_length} chars, confidence: {page.get('confidence', 0)})")
        if len(pages_data) > 3:
            self.logger.info(f"   ... and {len(pages_data) - 3} more pages")

        # CRITICAL DEBUG: Log last few pages including page 16
        if len(pages_data) > 10:
            self.logger.info(f"🔍 DEBUG: Last pages of {notebook_name}:")
            for page in pages_data[-3:]:  # Last 3 pages
                text_preview = page.get('text', '')[:50].replace('\n', ' ')
                self.logger.info(f"   Page {page.get('page_number')}: '{text_preview}...'")

        # SPECIFIC DEBUG: If this is Test for integration, log page 16 specifically
        if 'Test for integration' in notebook_name:
            page_16 = next((p for p in pages_data if p.get('page_number') == 16), None)
            if page_16:
                page_16_text = page_16.get('text', '')[:100].replace('\n', ' ')
                self.logger.info(f"🚨 CRITICAL: Test for integration page 16 content: '{page_16_text}...'")
            else:
                self.logger.info(f"🚨 CRITICAL: Test for integration page 16 NOT FOUND in pages_data")
        
        # Create NotebookPage objects, filtering out empty pages
        pages = []
        for page_data in pages_data:
            text = page_data.get('text', '').strip()
            if text:  # Only include pages with actual text content
                page = NotebookPage(
                    page_number=page_data.get('page_number', 0),
                    text=text,
                    confidence=page_data.get('confidence', 0.0),
                    page_uuid=page_data.get('page_uuid', f"{notebook_uuid}_page_{page_data.get('page_number', 0)}")
                )
                pages.append(page)
            else:
                self.logger.debug(f"Skipping empty page {page_data.get('page_number', 0)} in notebook {notebook_name}")

        self.logger.debug(f"Filtered to {len(pages)} pages with text content")
        
        # Sort pages in reverse order (latest first)
        pages = sorted(pages, key=lambda p: p.page_number, reverse=True)
        
        # Create metadata if available
        metadata = None
        if any(key in notebook_data for key in ['full_path', 'last_modified', 'last_opened']):
            metadata = NotebookMetadata(
                uuid=notebook_uuid,
                name=notebook_name,
                full_path=notebook_data.get('full_path', ''),
                last_modified=self._parse_timestamp(notebook_data.get('last_modified')),
                last_opened=self._parse_timestamp(notebook_data.get('last_opened')),
                path_tags=self._parse_path_tags(notebook_data.get('full_path'))
            )
        
        return Notebook(
            uuid=notebook_uuid,
            name=notebook_name,
            pages=pages,
            total_pages=len(pages),
            metadata=metadata
        )
    
    def _fetch_notebook_from_db(self, notebook_uuid: str) -> Optional[Notebook]:
        """Fetch a notebook from the database."""
        if not self.db_connection:
            return None
        
        try:
            # Use the existing fetch method from NotionNotebookSync
            notebooks = self.notion_client.fetch_notebooks_from_db(self.db_connection)
            for notebook in notebooks:
                if notebook.uuid == notebook_uuid:
                    return notebook
            return None
        except Exception as e:
            self.logger.error(f"Error fetching notebook {notebook_uuid} from DB: {e}")
            return None
    
    def _parse_timestamp(self, timestamp_str: Optional[str]) -> Optional[datetime]:
        """Parse reMarkable timestamp (milliseconds since Unix epoch)."""
        if not timestamp_str or not str(timestamp_str).isdigit():
            return None
        
        try:
            timestamp_seconds = int(timestamp_str) / 1000
            return datetime.fromtimestamp(timestamp_seconds)
        except (ValueError, OSError):
            return None
    
    def _parse_path_tags(self, full_path: Optional[str]) -> List[str]:
        """Parse reMarkable path into tags by splitting on '/'."""
        if not full_path:
            return []

        path_parts = [part.strip() for part in full_path.split('/') if part.strip()]

        # Remove the notebook name itself (usually the last part)
        if len(path_parts) > 1:
            return path_parts[:-1]
        else:
            return []

    def refresh_metadata_for_notebooks(self, notebook_uuids: set) -> int:
        """Refresh Notion metadata properties only for specific notebooks."""
        if not notebook_uuids:
            self.logger.debug("No notebooks specified for Notion metadata refresh")
            return 0

        if not self.db_connection:
            self.logger.warning("No database connection - skipping metadata refresh")
            return 0

        refreshed_count = 0
        self.logger.info(f"🔄 Refreshing Notion metadata for {len(notebook_uuids)} changed notebooks...")

        try:
            # Fetch notebooks that have changed metadata
            notebooks = self.notion_client.fetch_notebooks_from_db(self.db_connection, refresh_changed_metadata=False)
            changed_notebooks = [nb for nb in notebooks if nb.uuid in notebook_uuids]

            for notebook in changed_notebooks:
                try:
                    existing_page_id = self.notion_client.find_existing_page(notebook.uuid)

                    if existing_page_id:
                        self.logger.debug(f"📝 Updating Notion metadata for: {notebook.name}")

                        # Build metadata properties
                        properties = {
                            "Total Pages": {"number": notebook.total_pages},
                            "Last Updated": {"date": {"start": datetime.now().isoformat()}}
                        }

                        if notebook.metadata:
                            # Add path tags
                            if notebook.metadata.path_tags:
                                properties["Tags"] = {
                                    "multi_select": [{"name": tag} for tag in notebook.metadata.path_tags]
                                }

                            # Add last modified if available
                            if notebook.metadata.last_modified:
                                properties["Last Modified"] = {
                                    "date": {"start": notebook.metadata.last_modified.isoformat()}
                                }

                        # Update the Notion page properties
                        self.notion_client.client.pages.update(page_id=existing_page_id, properties=properties)
                        refreshed_count += 1
                        self.logger.debug(f"✅ Updated metadata for {notebook.name}")
                    else:
                        self.logger.debug(f"⏭️ No existing Notion page found for {notebook.name} - skipping metadata refresh")

                except Exception as e:
                    self.logger.error(f"❌ Failed to refresh metadata for {notebook.name}: {e}")

        except Exception as e:
            self.logger.error(f"❌ Error during metadata refresh: {e}")

        self.logger.info(f"✅ Refreshed metadata for {refreshed_count} notebooks")
        return refreshed_count
    
    def get_target_info(self) -> Dict[str, Any]:
        """Get information about this Notion target."""
        return {
            'target_name': self.target_name,
            'connected': bool(self.notion_token and self.database_id),
            'database_id': self.database_id,
            'tasks_database_id': self.tasks_database_id,
            'todo_sync_configured': bool(self.todo_sync),
            'capabilities': {
                'notebooks': True,
                'page_text': True,
                'todos': bool(self.todo_sync),  # Depends on tasks database configuration
                'highlights': False,  # Goes to Readwise
                'updates': True,
                'deletions': False  # Requires manual confirmation
            }
        }
    
    def calculate_content_hash(self, item: SyncItem) -> str:
        """Calculate a hash for the item content to detect changes."""
        if item.item_id in self._content_hash_cache:
            return self._content_hash_cache[item.item_id]
        
        # Create a stable hash based on notebook content
        if item.item_type == SyncItemType.NOTEBOOK:
            notebook_data = item.data
            pages_data = notebook_data.get('pages', [])
            
            # Sort pages by page number for consistent hashing
            sorted_pages = sorted(pages_data, key=lambda p: p.get('page_number', 0))
            
            content_parts = []
            for page in sorted_pages:
                page_content = f"page_{page.get('page_number', 0)}:{page.get('text', '')}:{page.get('confidence', 0)}"
                content_parts.append(page_content)
            
            combined_content = '|'.join(content_parts)
            content_hash = hashlib.md5(combined_content.encode('utf-8')).hexdigest()
            
        elif item.item_type == SyncItemType.PAGE_TEXT:
            page_data = item.data
            page_content = f"page_{page_data.get('page_number', 0)}:{page_data.get('text', '')}:{page_data.get('confidence', 0)}"
            content_hash = hashlib.md5(page_content.encode('utf-8')).hexdigest()

        elif item.item_type == SyncItemType.TODO:
            todo_data = item.data
            # Create hash based on todo content, notebook, and completion status
            todo_content = f"todo:{todo_data.get('text', '')}:notebook:{todo_data.get('notebook_uuid', '')}:page:{todo_data.get('page_number', 0)}:completed:{todo_data.get('completed', False)}"
            content_hash = hashlib.md5(todo_content.encode('utf-8')).hexdigest()

        else:
            # Fallback for other types
            content_hash = hashlib.md5(str(item.data).encode('utf-8')).hexdigest()
        
        self._content_hash_cache[item.item_id] = content_hash
        return content_hash