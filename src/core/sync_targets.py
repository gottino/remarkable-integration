"""
Concrete implementations of sync targets for the unified sync engine.

This module provides specific implementations for each downstream target
(Notion, Readwise, etc.) that implement the SyncTarget interface and integrate
with the unified sync_records table architecture.

Key Features:
- Integration with unified sync_records table
- Target-agnostic sync interface
- Content-hash based deduplication
- Consistent error handling and retry logic
"""

import logging
from typing import Any, Dict, Optional
import asyncio

from .sync_engine import SyncTarget, SyncItem, SyncResult, SyncStatus, SyncItemType, ContentFingerprint

logger = logging.getLogger(__name__)


class NotionSyncTarget(SyncTarget):
    """
    Notion implementation of the sync target interface.
    
    This wraps our existing NotionNotebookSync to provide the standardized
    sync target interface for the event-driven sync engine.
    """
    
    def __init__(self, notion_client, verify_ssl: bool = True):
        super().__init__("notion")
        self.notion_client = notion_client
        self.verify_ssl = verify_ssl
        
        # Import here to avoid circular dependencies
        try:
            from ..integrations.notion_sync import NotionNotebookSync
            self.sync_client = NotionNotebookSync(
                notion_client.auth.token if hasattr(notion_client, 'auth') else notion_client._token,
                notion_client.database_id if hasattr(notion_client, 'database_id') else None,
                verify_ssl=verify_ssl
            )
        except ImportError as e:
            self.logger.error(f"Failed to import NotionNotebookSync: {e}")
            self.sync_client = None
    
    async def sync_item(self, item: SyncItem) -> SyncResult:
        """Sync a single item to Notion."""
        if not self.sync_client:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message="Notion sync client not available"
            )
        
        try:
            if item.item_type == SyncItemType.NOTEBOOK:
                return await self._sync_notebook(item)
            elif item.item_type == SyncItemType.PAGE_TEXT:
                return await self._sync_page_text(item)
            elif item.item_type == SyncItemType.TODO:
                return await self._sync_todo(item)
            elif item.item_type == SyncItemType.HIGHLIGHT:
                return await self._sync_highlight(item)
            else:
                return SyncResult(
                    status=SyncStatus.FAILED,
                    error_message=f"Unsupported item type: {item.item_type}"
                )
        except Exception as e:
            self.logger.error(f"Error syncing {item.item_type} to Notion: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_notebook(self, item: SyncItem) -> SyncResult:
        """Sync a notebook to Notion."""
        try:
            # Use existing notebook sync logic
            notebook_data = item.data
            
            # Check if this is an update to existing page
            existing_id = await self.check_duplicate(item.content_hash)
            if existing_id:
                # Update existing page
                result = await self._update_notion_page(existing_id, notebook_data)
                if result:
                    return SyncResult(
                        status=SyncStatus.SUCCESS,
                        target_id=existing_id,
                        metadata={'action': 'updated'}
                    )
                else:
                    return SyncResult(
                        status=SyncStatus.RETRY,
                        error_message="Failed to update existing Notion page"
                    )
            else:
                # Create new page
                page_id = await self._create_notion_page(notebook_data)
                if page_id:
                    return SyncResult(
                        status=SyncStatus.SUCCESS,
                        target_id=page_id,
                        metadata={'action': 'created'}
                    )
                else:
                    return SyncResult(
                        status=SyncStatus.RETRY,
                        error_message="Failed to create Notion page"
                    )
        except Exception as e:
            self.logger.error(f"Error syncing notebook to Notion: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_page_text(self, item: SyncItem) -> SyncResult:
        """Sync individual page text as a block to existing Notion page."""
        try:
            # Extract page information
            notebook_uuid = item.data.get('notebook_uuid')
            page_number = item.data.get('page_number')
            page_text = item.data.get('text', '')
            
            if not notebook_uuid or page_number is None:
                return SyncResult(
                    status=SyncStatus.FAILED,
                    error_message="Missing notebook UUID or page number in page sync item"
                )
            
            self.logger.info(f"Syncing page {page_number} for notebook {notebook_uuid} as individual block")
            
            # Find the existing Notion page for this notebook
            existing_page_id = self.sync_client.find_existing_page(notebook_uuid)
            if not existing_page_id:
                self.logger.warning(f"No existing Notion page found for notebook {notebook_uuid}")
                return SyncResult(
                    status=SyncStatus.FAILED,
                    error_message=f"Notebook {notebook_uuid} not found in Notion - cannot add page block"
                )
            
            # Add or update the page block in the existing Notion page
            success = await self._add_page_block_to_notion(existing_page_id, page_number, page_text)
            
            if success:
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id=existing_page_id,
                    metadata={
                        'action': 'page_block_updated',
                        'page_number': page_number,
                        'notebook_uuid': notebook_uuid
                    }
                )
            else:
                return SyncResult(
                    status=SyncStatus.RETRY,
                    error_message="Failed to add page block to Notion"
                )
                
        except Exception as e:
            self.logger.error(f"Error syncing page text to Notion: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_todo(self, item: SyncItem) -> SyncResult:
        """Sync a todo item to Notion."""
        try:
            # Use existing todo sync logic
            from ..integrations.notion_todo_sync import NotionTodoSync
            
            # This would need the tasks database ID from config
            # For now, return success but log that it needs implementation
            self.logger.info(f"Todo sync not yet implemented for item {item.item_id}")
            return SyncResult(
                status=SyncStatus.SKIPPED,
                metadata={'reason': 'Todo sync integration pending'}
            )
        except Exception as e:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_highlight(self, item: SyncItem) -> SyncResult:
        """Sync a highlight to Notion."""
        # Highlights are typically part of notebook content
        # Could be implemented as separate database or embedded in notebooks
        return SyncResult(
            status=SyncStatus.SKIPPED,
            metadata={'reason': 'Highlights handled via notebook sync'}
        )
    
    async def check_duplicate(self, content_hash: str) -> Optional[str]:
        """Check if content with this hash already exists in Notion."""
        if not self.sync_client:
            return None
        
        try:
            # For notebook sync, we check by UUID instead of content hash
            # The content_hash contains the notebook UUID for our use case
            # This is a simplified approach - in production might want more sophisticated checking
            existing_page_id = self.sync_client.find_existing_page(content_hash)
            return existing_page_id
        except Exception as e:
            self.logger.error(f"Error checking Notion duplicates: {e}")
            return None
    
    async def update_item(self, external_id: str, item: SyncItem) -> SyncResult:
        """Update an existing item in Notion."""
        try:
            if item.item_type == SyncItemType.NOTEBOOK:
                success = await self._update_notion_page(external_id, item.data)
                if success:
                    return SyncResult(
                        status=SyncStatus.SUCCESS,
                        target_id=external_id,
                        metadata={'action': 'updated'}
                    )
                else:
                    return SyncResult(
                        status=SyncStatus.RETRY,
                        error_message="Failed to update Notion page"
                    )
            elif item.item_type == SyncItemType.PAGE_TEXT:
                success = await self._update_page_block_in_notion(external_id, item)
                if success:
                    return SyncResult(
                        status=SyncStatus.SUCCESS,
                        target_id=external_id,
                        metadata={'action': 'page_block_updated'}
                    )
                else:
                    return SyncResult(
                        status=SyncStatus.RETRY,
                        error_message="Failed to update page block in Notion"
                    )
            else:
                return SyncResult(
                    status=SyncStatus.FAILED,
                    error_message=f"Update not supported for {item.item_type}"
                )
        except Exception as e:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def delete_item(self, external_id: str) -> SyncResult:
        """Delete an item from Notion."""
        try:
            # Notion doesn't really support deletion, but we could archive
            # For now, return success but don't actually delete
            return SyncResult(
                status=SyncStatus.SUCCESS,
                metadata={'action': 'archived', 'note': 'Notion pages archived, not deleted'}
            )
        except Exception as e:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    def get_target_info(self) -> Dict[str, Any]:
        """Get information about this Notion target."""
        try:
            connected = self.sync_client is not None
            return {
                'target_name': self.target_name,
                'connected': connected,
                'verify_ssl': self.verify_ssl,
                'client_available': self.sync_client is not None,
                'capabilities': {
                    'notebooks': True,
                    'todos': False,  # Not yet implemented
                    'highlights': False,  # Embedded in notebooks
                    'page_text': True  # Now supported for granular updates
                }
            }
        except Exception as e:
            return {
                'target_name': self.target_name,
                'connected': False,
                'error': str(e)
            }
    
    async def _create_notion_page(self, notebook_data: Dict[str, Any]) -> Optional[str]:
        """Create a new page in Notion and return its ID."""
        try:
            # Convert notebook data to Notebook object
            notebook = self._convert_to_notebook(notebook_data)
            
            self.logger.info(f"Creating Notion page for notebook: {notebook.name}")
            
            # Use existing NotionNotebookSync logic
            page_id = self.sync_client.create_notebook_page(notebook)
            
            return page_id
        except Exception as e:
            self.logger.error(f"Error creating Notion page: {e}")
            return None
    
    async def _update_notion_page(self, page_id: str, notebook_data: Dict[str, Any]) -> bool:
        """Update an existing Notion page."""
        try:
            # Convert notebook data to Notebook object
            notebook = self._convert_to_notebook(notebook_data)
            
            self.logger.info(f"Updating Notion page {page_id} for notebook: {notebook.name}")
            
            # Use existing NotionNotebookSync logic
            self.sync_client.update_existing_page(page_id, notebook)
            
            return True
        except Exception as e:
            self.logger.error(f"Error updating Notion page: {e}")
            return False
    
    async def _add_page_block_to_notion(self, page_id: str, page_number: int, page_text: str) -> bool:
        """Add or update a single page toggle block within an existing Notion page."""
        try:
            self.logger.info(f"Adding page {page_number} toggle block to Notion page {page_id}")
            
            if not page_text.strip():
                self.logger.debug(f"Page {page_number} has no text content, skipping")
                return True
            
            # Create proper toggle block structure like the existing sync
            page_toggle = self._create_page_toggle_block(page_number, page_text, confidence=0.8)
            
            # Find the correct insertion position (pages in reverse order)
            insertion_position = await self._find_insertion_position_for_page(page_id, page_number)
            
            try:
                if insertion_position:
                    # Insert after the specified block to maintain reverse order
                    response = self.sync_client.client.blocks.children.append(
                        block_id=page_id,
                        children=[page_toggle],
                        after=insertion_position
                    )
                else:
                    # Insert at the beginning (after header blocks)
                    response = self.sync_client.client.blocks.children.append(
                        block_id=page_id,
                        children=[page_toggle]
                    )
                
                # 🔗 STORE BLOCK ID for todo linking
                if response.get('results') and len(response['results']) > 0:
                    new_block_id = response['results'][0]['id']
                    await self._store_notion_page_block_mapping(
                        notebook_uuid=item.data.get('notebook_uuid'),
                        page_number=page_number,
                        notion_page_id=page_id,
                        notion_block_id=new_block_id
                    )
                    self.logger.debug(f"Stored block mapping: page {page_number} -> {new_block_id[:20]}...")
                
                self.logger.info(f"Successfully added page {page_number} toggle block to Notion page")
                return True
                
            except Exception as api_error:
                self.logger.error(f"Notion API error adding page toggle block: {api_error}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error adding page toggle block to Notion: {e}")
            return False
    
    async def _update_page_block_in_notion(self, page_id: str, item: SyncItem) -> bool:
        """Update an existing page block within a Notion page."""
        try:
            notebook_uuid = item.data.get('notebook_uuid')
            page_number = item.data.get('page_number')
            page_text = item.data.get('text', '')
            
            self.logger.info(f"Updating page {page_number} block in Notion page {page_id}")
            
            # First, try to find the existing page block
            existing_block_id = await self._find_page_block_in_notion(page_id, page_number)
            
            if existing_block_id:
                # Update the existing block
                success = await self._replace_notion_block_content(existing_block_id, page_number, page_text)
                if success:
                    # 🔗 STORE BLOCK ID for todo linking (update case)
                    await self._store_notion_page_block_mapping(
                        notebook_uuid=item.data.get('notebook_uuid'),
                        page_number=page_number,
                        notion_page_id=page_id,
                        notion_block_id=existing_block_id
                    )
                    self.logger.info(f"Successfully updated existing page {page_number} block")
                    return True
                else:
                    self.logger.warning(f"Failed to update existing page {page_number} block, falling back to append")
            
            # If no existing block found or update failed, append new block
            self.logger.info(f"Adding new page {page_number} block (no existing block found)")
            return await self._add_page_block_to_notion(page_id, page_number, page_text)
            
        except Exception as e:
            self.logger.error(f"Error updating page block in Notion: {e}")
            return False
    
    async def _find_page_block_in_notion(self, page_id: str, page_number: int) -> Optional[str]:
        """Find the toggle block ID for a specific page number within a Notion page."""
        try:
            # Get all blocks in the page
            response = self.sync_client.client.blocks.children.list(block_id=page_id)
            
            # Look for toggle block with the proper page format
            page_identifier = f"📄 Page {page_number}"
            
            for block in response.get('results', []):
                if block.get('type') == 'toggle':
                    # Check toggle heading for the proper page format
                    rich_text = block.get('toggle', {}).get('rich_text', [])
                    if rich_text:
                        title = rich_text[0].get('text', {}).get('content', '')
                        if title.startswith(page_identifier):
                            return block['id']
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding page toggle block in Notion: {e}")
            return None
    
    def _extract_rich_text_from_block(self, block: Dict[str, Any]) -> Optional[str]:
        """Extract plain text content from a Notion block."""
        try:
            block_type = block.get('type')
            if not block_type:
                return None
            
            block_content = block.get(block_type, {})
            rich_text_array = block_content.get('rich_text', [])
            
            # Combine all text content
            text_parts = []
            for text_obj in rich_text_array:
                if text_obj.get('type') == 'text':
                    text_parts.append(text_obj.get('text', {}).get('content', ''))
            
            return ''.join(text_parts)
            
        except Exception:
            return None
    
    async def _replace_notion_block_content(self, block_id: str, page_number: int, page_text: str) -> bool:
        """Replace the children of an existing toggle block with new content."""
        try:
            # Convert the new page text to Notion blocks
            from ..integrations.notion_markdown import MarkdownToNotionConverter
            converter = MarkdownToNotionConverter()
            
            new_children = converter.text_to_notion_blocks(page_text, max_blocks=20)
            
            if not new_children:
                new_children = [{
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": "(No readable text extracted)"}
                        }]
                    }
                }]
            
            # First, delete all existing children of the toggle block
            try:
                # Get current children
                children_response = self.sync_client.client.blocks.children.list(block_id=block_id)
                
                # Delete all existing children
                for child_block in children_response.get('results', []):
                    self.sync_client.client.blocks.delete(block_id=child_block['id'])
                
                # Add new children
                self.sync_client.client.blocks.children.append(
                    block_id=block_id,
                    children=new_children
                )
                
                self.logger.info(f"Successfully replaced content for page {page_number} toggle block")
                return True
                
            except Exception as api_error:
                self.logger.error(f"Notion API error replacing toggle content: {api_error}")
                return False
            
        except Exception as e:
            self.logger.error(f"Error replacing toggle block content: {e}")
            return False
    
    def _create_page_toggle_block(self, page_number: int, page_text: str, confidence: float = 0.8) -> Dict[str, Any]:
        """Create a proper toggle block for a single notebook page."""
        # Create confidence indicator
        confidence_emoji = "🟢" if confidence > 0.8 else "🟡" if confidence > 0.5 else "🔴"
        confidence_text = f" ({confidence_emoji} {confidence:.1f})" if confidence > 0 else ""
        
        # Use markdown converter to create properly formatted blocks
        from ..integrations.notion_markdown import MarkdownToNotionConverter
        converter = MarkdownToNotionConverter()
        children = converter.text_to_notion_blocks(page_text, max_blocks=20)
        
        # Create the toggle block
        return {
            "object": "block",
            "type": "toggle",
            "toggle": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"📄 Page {page_number}{confidence_text}"
                        },
                        "annotations": {
                            "bold": True
                        }
                    }
                ],
                "children": children
            }
        }
    
    async def _find_insertion_position_for_page(self, page_id: str, page_number: int) -> Optional[str]:
        """Find the correct position to insert a page to maintain reverse order."""
        try:
            # Get all blocks in the page
            response = self.sync_client.client.blocks.children.list(block_id=page_id)
            
            # Find existing page toggle blocks and determine insertion position
            page_blocks = []
            header_blocks = []
            
            for block in response.get('results', []):
                if block.get('type') == 'toggle':
                    # Check if this is a page toggle block
                    rich_text = block.get('toggle', {}).get('rich_text', [])
                    if rich_text:
                        title = rich_text[0].get('text', {}).get('content', '')
                        if '📄 Page ' in title:
                            # Extract page number
                            try:
                                existing_page_num = int(title.split('📄 Page ')[1].split()[0])
                                page_blocks.append((existing_page_num, block['id']))
                            except (ValueError, IndexError):
                                continue
                else:
                    # This is a header/summary block
                    header_blocks.append(block['id'])
            
            # Sort page blocks by page number (descending for reverse order)
            page_blocks.sort(key=lambda x: x[0], reverse=True)
            
            # Find where to insert this page number
            for existing_page_num, block_id in page_blocks:
                if page_number > existing_page_num:
                    # Insert before this block (which means after the previous block)
                    # For the first position, insert after header blocks
                    if page_blocks.index((existing_page_num, block_id)) == 0:
                        return header_blocks[-1] if header_blocks else None
                    else:
                        # Find the previous block in the list
                        prev_index = page_blocks.index((existing_page_num, block_id)) - 1
                        return page_blocks[prev_index][1]
            
            # If we get here, this page should be inserted at the end
            # Return the last page block ID, or last header block
            if page_blocks:
                return page_blocks[-1][1]
            elif header_blocks:
                return header_blocks[-1]
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"Error finding insertion position: {e}")
            return None
    
    def _convert_to_notebook(self, notebook_data: Dict[str, Any]) -> 'Notebook':
        """Convert sync item data to Notebook object."""
        from ..integrations.notion_sync import Notebook, NotebookPage, NotebookMetadata
        
        # Extract notebook info
        notebook_uuid = notebook_data.get('uuid')
        notebook_name = notebook_data.get('name', 'Unknown Notebook')
        
        # Convert pages data
        pages = []
        pages_data = notebook_data.get('pages', [])
        
        for page_data in pages_data:
            page = NotebookPage(
                page_number=page_data.get('page_number', 0),
                text=page_data.get('text', ''),
                confidence=page_data.get('confidence', 0.0),
                page_uuid=page_data.get('page_uuid', '')
            )
            pages.append(page)
        
        # Create metadata if available
        metadata = None
        metadata_data = notebook_data.get('metadata')
        if metadata_data:
            metadata = NotebookMetadata(
                uuid=metadata_data.get('uuid', notebook_uuid),
                name=metadata_data.get('name', notebook_name),
                full_path=metadata_data.get('full_path', ''),
                last_modified=metadata_data.get('last_modified'),
                last_opened=metadata_data.get('last_opened'),
                path_tags=metadata_data.get('path_tags', [])
            )
        
        return Notebook(
            uuid=notebook_uuid,
            name=notebook_name,
            pages=pages,
            total_pages=len(pages),
            metadata=metadata
        )
    
    async def _get_notebook_data_for_sync(self, notebook_uuid: str) -> Optional[Dict[str, Any]]:
        """Get complete notebook data for sync operations."""
        try:
            # Import here to avoid circular dependencies
            from datetime import datetime
            import sqlite3
            
            # This is a simplified approach - in a full implementation, 
            # we'd want to access the database manager properly
            db_path = "./data/remarkable_pipeline.db"
            
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                
                # Get notebook metadata first
                cursor.execute('''
                    SELECT DISTINCT notebook_uuid, notebook_name
                    FROM notebook_text_extractions 
                    WHERE notebook_uuid = ?
                    LIMIT 1
                ''', (notebook_uuid,))
                
                notebook_row = cursor.fetchone()
                if not notebook_row:
                    return None
                
                notebook_name = notebook_row[1]
                
                # Get all pages for this notebook
                cursor.execute('''
                    SELECT page_uuid, page_number, text, confidence
                    FROM notebook_text_extractions
                    WHERE notebook_uuid = ?
                    ORDER BY page_number ASC
                ''', (notebook_uuid,))
                
                pages = []
                for page_row in cursor.fetchall():
                    pages.append({
                        'page_uuid': page_row[0],
                        'page_number': page_row[1], 
                        'text': page_row[2],
                        'confidence': page_row[3]
                    })
                
                return {
                    'uuid': notebook_uuid,
                    'name': notebook_name,
                    'pages': pages,
                    'total_pages': len(pages),
                    'metadata': {
                        'uuid': notebook_uuid,
                        'name': notebook_name,
                        'full_path': '',
                        'last_modified': datetime.now(),
                        'last_opened': datetime.now(),
                        'path_tags': []
                    }
                }
                
        except Exception as e:
            self.logger.error(f"Error loading notebook data for {notebook_uuid}: {e}")
            return None
    
    async def _store_notion_page_block_mapping(self, 
                                             notebook_uuid: str, 
                                             page_number: int,
                                             notion_page_id: str, 
                                             notion_block_id: str) -> None:
        """Store the mapping between a reMarkable page and its Notion block ID."""
        try:
            # Get database connection
            db_manager = await self._get_db_manager()
            
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Insert or update the block mapping
                cursor.execute('''
                    INSERT OR REPLACE INTO notion_page_blocks 
                    (notebook_uuid, page_number, notion_page_id, notion_block_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (notebook_uuid, page_number, notion_page_id, notion_block_id))
                
                conn.commit()
                self.logger.debug(f"Stored block mapping: {notebook_uuid}|p{page_number} -> {notion_block_id[:20]}...")
                
        except Exception as e:
            self.logger.error(f"Failed to store notion block mapping: {e}")
    
    async def _get_db_manager(self):
        """Get database manager instance."""
        from .database import DatabaseManager
        return DatabaseManager('./data/remarkable_pipeline.db')


# Import the full Readwise implementation
try:
    from ..integrations.readwise_sync import ReadwiseSyncTarget
except ImportError as e:
    logger.warning(f"Readwise integration not available: {e}")
    
    # Fallback stub implementation
    class ReadwiseSyncTarget(SyncTarget):
        """Fallback Readwise target when integration is not available."""
        
        def __init__(self, access_token: str, **kwargs):
            super().__init__("readwise")
            self.access_token = access_token
        
        async def sync_item(self, item: SyncItem) -> SyncResult:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message="Readwise integration not available - missing dependencies"
            )
        
        async def check_duplicate(self, content_hash: str) -> Optional[str]:
            return None
        
        async def update_item(self, external_id: str, item: SyncItem) -> SyncResult:
            return SyncResult(status=SyncStatus.FAILED, error_message="Not available")
        
        async def delete_item(self, external_id: str) -> SyncResult:
            return SyncResult(status=SyncStatus.FAILED, error_message="Not available")
        
        def get_target_info(self) -> Dict[str, Any]:
            return {
                'target_name': self.target_name,
                'connected': False,
                'error': 'Integration not available'
            }


class MockSyncTarget(SyncTarget):
    """
    Mock sync target for testing purposes.
    
    This simulates a sync target without actually sending data anywhere.
    Useful for testing the sync engine logic.
    """
    
    def __init__(self, target_name: str = "mock", fail_rate: float = 0.0):
        super().__init__(target_name)
        self.fail_rate = fail_rate  # Probability of failure (0.0 to 1.0)
        self.synced_items = {}  # Mock storage
        self.sync_count = 0
    
    async def sync_item(self, item: SyncItem) -> SyncResult:
        """Mock sync operation."""
        self.sync_count += 1
        
        # Simulate random failures based on fail_rate
        import random
        if random.random() < self.fail_rate:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=f"Mock failure (rate: {self.fail_rate})"
            )
        
        # Store in mock storage
        mock_id = f"mock_{self.sync_count}"
        self.synced_items[mock_id] = item.to_dict()
        
        self.logger.debug(f"Mock synced {item.item_type} with ID {mock_id}")
        
        return SyncResult(
            status=SyncStatus.SUCCESS,
            target_id=mock_id,
            metadata={'sync_count': self.sync_count}
        )
    
    async def check_duplicate(self, content_hash: str) -> Optional[str]:
        """Check for duplicates in mock storage."""
        for mock_id, item_data in self.synced_items.items():
            if item_data.get('content_hash') == content_hash:
                return mock_id
        return None
    
    async def update_item(self, external_id: str, item: SyncItem) -> SyncResult:
        """Mock update operation."""
        if external_id in self.synced_items:
            self.synced_items[external_id] = item.to_dict()
            return SyncResult(
                status=SyncStatus.SUCCESS,
                target_id=external_id,
                metadata={'action': 'updated'}
            )
        else:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=f"Mock item {external_id} not found"
            )
    
    async def delete_item(self, external_id: str) -> SyncResult:
        """Mock delete operation."""
        if external_id in self.synced_items:
            del self.synced_items[external_id]
            return SyncResult(
                status=SyncStatus.SUCCESS,
                metadata={'action': 'deleted'}
            )
        else:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=f"Mock item {external_id} not found"
            )
    
    def get_target_info(self) -> Dict[str, Any]:
        """Get mock target information."""
        return {
            'target_name': self.target_name,
            'connected': True,
            'synced_items_count': len(self.synced_items),
            'total_syncs': self.sync_count,
            'fail_rate': self.fail_rate,
            'capabilities': {
                'notebooks': True,
                'todos': True,
                'highlights': True,
                'page_text': True
            }
        }


# Factory function for creating sync targets
def create_sync_target(target_type: str, **kwargs) -> SyncTarget:
    """
    Factory function to create sync targets.
    
    Args:
        target_type: Type of target ('notion', 'readwise', 'mock')
        **kwargs: Target-specific configuration
        
    Returns:
        Configured sync target
    """
    if target_type == "notion":
        return NotionSyncTarget(
            notion_client=kwargs.get('notion_client'),
            verify_ssl=kwargs.get('verify_ssl', True)
        )
    elif target_type == "readwise":
        return ReadwiseSyncTarget(
            access_token=kwargs.get('access_token') or kwargs.get('api_token'),
            author_name=kwargs.get('author_name', 'reMarkable'),
            default_category=kwargs.get('default_category', 'books')
        )
    elif target_type == "mock":
        return MockSyncTarget(
            target_name=kwargs.get('target_name', 'mock'),
            fail_rate=kwargs.get('fail_rate', 0.0)
        )
    else:
        raise ValueError(f"Unknown sync target type: {target_type}")


if __name__ == "__main__":
    # Example usage
    import asyncio
    from datetime import datetime
    
    async def test_mock_target():
        # Test the mock sync target
        mock_target = create_sync_target("mock", fail_rate=0.1)
        
        # Create a test item
        test_item = SyncItem(
            item_type=SyncItemType.NOTEBOOK,
            item_id="test-notebook-123",
            content_hash="abc123def456",
            data={'title': 'Test Notebook', 'content': 'Test content'},
            source_table="notebook_text_extractions",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Test sync
        result = await mock_target.sync_item(test_item)
        print(f"Sync result: {result}")
        
        # Test duplicate check
        duplicate_id = await mock_target.check_duplicate("abc123def456")
        print(f"Duplicate ID: {duplicate_id}")
        
        # Get target info
        info = mock_target.get_target_info()
        print(f"Target info: {info}")
    
    # Run the test
    asyncio.run(test_mock_target())