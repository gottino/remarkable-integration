"""
Page-Level Granular Sync System

This module implements true page-level synchronization to avoid the performance
issues of syncing entire large notebooks when only individual pages change.

Key features:
- Page-level sync tracking
- Batch processing within API limits
- Incremental page updates
- Notion API 50-block limit compliance
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import asyncio

from .sync_engine import SyncItem, SyncItemType, SyncStatus, SyncResult, ContentFingerprint, SyncRecord

logger = logging.getLogger(__name__)


class PageLevelSyncManager:
    """
    Manages page-level synchronization for large notebooks.
    
    This handles the complexity of syncing individual pages while maintaining
    notebook structure and respecting API limits.
    """
    
    def __init__(self, db_manager, dedup_service):
        self.db_manager = db_manager
        self.dedup_service = dedup_service
        self.logger = logging.getLogger(f"{__name__}.PageLevelSyncManager")
        self.max_blocks_per_request = 50  # Notion API limit
        
    async def convert_page_change_to_sync_items(self, change: Dict[str, Any]) -> List[SyncItem]:
        """
        Convert a page-level change to appropriate sync items.
        
        For new notebooks: Create notebook + page sync items
        For existing notebooks: Create only page sync items for changed pages
        
        Args:
            change: Page change from sync_changelog
            
        Returns:
            List of sync items to process
        """
        try:
            # Parse page record_id: "notebook_uuid|page_number"
            record_id = change['record_id']
            if '|' not in record_id:
                self.logger.warning(f"Invalid page record_id format: {record_id}")
                return []
            
            notebook_uuid, page_number = record_id.split('|', 1)
            page_number = int(page_number)
            
            # Check if notebook is already synced
            is_new_notebook = not await self._is_notebook_synced(notebook_uuid)
            
            if is_new_notebook:
                # For new notebooks, create notebook-level sync item but handle pages separately
                return await self._create_new_notebook_sync_items(notebook_uuid, page_number)
            else:
                # For existing notebooks, create page-level sync items only
                return await self._create_page_sync_items(notebook_uuid, [page_number])
                
        except Exception as e:
            self.logger.error(f"Error converting page change to sync items: {e}")
            return []
    
    async def _is_notebook_synced(self, notebook_uuid: str) -> bool:
        """Check if a notebook is already synced to any target."""
        try:
            # Direct database check - look for any sync record for this notebook
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Check if this notebook exists in sync_records via notion_notebook_sync
                cursor.execute('''
                    SELECT sr.id FROM sync_records sr
                    JOIN notion_notebook_sync nns ON sr.external_id = nns.notion_page_id
                    WHERE nns.notebook_uuid = ? 
                    AND sr.item_type = 'notebook'
                    AND sr.status = 'success'
                    LIMIT 1
                ''', (notebook_uuid,))
                
                result = cursor.fetchone()
                return result is not None
                
        except Exception as e:
            self.logger.error(f"Error checking if notebook {notebook_uuid} is synced: {e}")
            return False
    
    async def _create_new_notebook_sync_items(self, notebook_uuid: str, trigger_page: int) -> List[SyncItem]:
        """
        Create sync items for a new notebook, handling large notebooks efficiently.
        
        Args:
            notebook_uuid: UUID of the notebook
            trigger_page: Page number that triggered this sync
            
        Returns:
            List of sync items (notebook metadata + page batches)
        """
        try:
            sync_items = []
            
            # Get notebook metadata
            notebook_metadata = await self._get_notebook_metadata(notebook_uuid)
            if not notebook_metadata:
                return []
            
            # Create notebook metadata sync item (without full content)
            metadata_hash = ContentFingerprint.for_notebook({
                'notebook_uuid': notebook_uuid,
                'title': notebook_metadata['title'],
                'page_count': notebook_metadata['page_count'],
                'type': 'notebook_metadata'
            })
            
            notebook_item = SyncItem(
                item_type=SyncItemType.NOTEBOOK,
                item_id=notebook_uuid,
                content_hash=metadata_hash,
                data={
                    'notebook_uuid': notebook_uuid,
                    'title': notebook_metadata['title'],
                    'page_count': notebook_metadata['page_count'],
                    'sync_type': 'metadata_only',
                    'type': 'notebook'
                },
                source_table='notebooks',
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            sync_items.append(notebook_item)
            
            # Create page-level sync items in batches
            page_batches = await self._create_page_batches(notebook_uuid, notebook_metadata['page_count'])
            sync_items.extend(page_batches)
            
            return sync_items
            
        except Exception as e:
            self.logger.error(f"Error creating new notebook sync items: {e}")
            return []
    
    async def _create_page_sync_items(self, notebook_uuid: str, page_numbers: List[int]) -> List[SyncItem]:
        """
        Create sync items for specific pages of an existing notebook.
        
        Args:
            notebook_uuid: UUID of the notebook
            page_numbers: List of page numbers to sync
            
        Returns:
            List of page sync items
        """
        try:
            sync_items = []
            
            for page_number in page_numbers:
                page_data = await self._get_page_data(notebook_uuid, page_number)
                if not page_data:
                    continue
                
                # Generate page-specific content hash
                page_hash = ContentFingerprint.for_page_text({
                    'notebook_uuid': notebook_uuid,
                    'page_number': page_number,
                    'text': page_data.get('text', ''),
                    'confidence': page_data.get('confidence', 0.0),
                    'type': 'page'
                })
                
                page_item = SyncItem(
                    item_type=SyncItemType.PAGE_TEXT,
                    item_id=f"{notebook_uuid}|{page_number}",
                    content_hash=page_hash,
                    data={
                        'notebook_uuid': notebook_uuid,
                        'page_number': page_number,
                        'text': page_data.get('text', ''),
                        'confidence': page_data.get('confidence', 0.0),
                        'notebook_title': page_data.get('notebook_title', ''),
                        'sync_type': 'page_only',
                        'type': 'page'
                    },
                    source_table='pages',
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                sync_items.append(page_item)
            
            return sync_items
            
        except Exception as e:
            self.logger.error(f"Error creating page sync items: {e}")
            return []
    
    async def _create_page_batches(self, notebook_uuid: str, total_pages: int) -> List[SyncItem]:
        """
        Create page sync items in batches that respect API limits.
        
        Args:
            notebook_uuid: UUID of the notebook
            total_pages: Total number of pages in the notebook
            
        Returns:
            List of batched page sync items
        """
        try:
            sync_items = []
            batch_size = min(self.max_blocks_per_request // 2, 25)  # Conservative batch size
            
            for batch_start in range(1, total_pages + 1, batch_size):
                batch_end = min(batch_start + batch_size - 1, total_pages)
                
                # Get pages in this batch
                batch_pages = await self._get_pages_batch(notebook_uuid, batch_start, batch_end)
                if not batch_pages:
                    continue
                
                # Create batch sync item
                batch_hash = ContentFingerprint._generate_hash({
                    'notebook_uuid': notebook_uuid,
                    'batch_start': batch_start,
                    'batch_end': batch_end,
                    'pages': [p['page_number'] for p in batch_pages],
                    'type': 'page_batch'
                })
                
                batch_item = SyncItem(
                    item_type=SyncItemType.PAGE_TEXT,
                    item_id=f"{notebook_uuid}|batch_{batch_start}_{batch_end}",
                    content_hash=batch_hash,
                    data={
                        'notebook_uuid': notebook_uuid,
                        'batch_start': batch_start,
                        'batch_end': batch_end,
                        'pages': batch_pages,
                        'page_count': len(batch_pages),
                        'sync_type': 'page_batch',
                        'type': 'page_batch'
                    },
                    source_table='pages',
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                sync_items.append(batch_item)
            
            return sync_items
            
        except Exception as e:
            self.logger.error(f"Error creating page batches: {e}")
            return []
    
    async def _get_notebook_metadata(self, notebook_uuid: str) -> Optional[Dict[str, Any]]:
        """Get notebook metadata without full content."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT notebook_name, COUNT(*) as page_count,
                           AVG(confidence) as avg_confidence,
                           MIN(created_at) as first_created,
                           MAX(updated_at) as last_updated
                    FROM notebook_text_extractions
                    WHERE notebook_uuid = ?
                    GROUP BY notebook_uuid, notebook_name
                ''', (notebook_uuid,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'notebook_uuid': notebook_uuid,
                        'title': row[0] or 'Untitled Notebook',
                        'page_count': row[1],
                        'avg_confidence': row[2],
                        'first_created': row[3],
                        'last_updated': row[4]
                    }
                
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting notebook metadata for {notebook_uuid}: {e}")
            return None
    
    async def _get_page_data(self, notebook_uuid: str, page_number: int) -> Optional[Dict[str, Any]]:
        """Get data for a specific page."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT notebook_name, text, confidence, created_at, updated_at
                    FROM notebook_text_extractions
                    WHERE notebook_uuid = ? AND page_number = ?
                ''', (notebook_uuid, page_number))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'notebook_title': row[0],
                        'text': row[1],
                        'confidence': row[2],
                        'created_at': row[3],
                        'updated_at': row[4]
                    }
                
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting page data for {notebook_uuid}|{page_number}: {e}")
            return None
    
    async def _get_pages_batch(self, notebook_uuid: str, start_page: int, end_page: int) -> List[Dict[str, Any]]:
        """Get a batch of pages."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT page_number, text, confidence, created_at, updated_at
                    FROM notebook_text_extractions
                    WHERE notebook_uuid = ? 
                    AND page_number BETWEEN ? AND ?
                    ORDER BY page_number
                ''', (notebook_uuid, start_page, end_page))
                
                pages = []
                for row in cursor.fetchall():
                    pages.append({
                        'page_number': row[0],
                        'text': row[1],
                        'confidence': row[2],
                        'created_at': row[3],
                        'updated_at': row[4]
                    })
                
                return pages
                
        except Exception as e:
            self.logger.error(f"Error getting pages batch {start_page}-{end_page} for {notebook_uuid}: {e}")
            return []


class PageAwareSyncProcessor:
    """
    Sync processor that understands page-level granularity and API limits.
    
    This extends the basic sync queue processor to handle page-level sync items
    efficiently while respecting Notion API constraints.
    """
    
    def __init__(self, sync_queue_processor, page_sync_manager):
        self.sync_processor = sync_queue_processor
        self.page_manager = page_sync_manager
        self.logger = logging.getLogger(f"{__name__}.PageAwareSyncProcessor")
    
    async def process_page_change(self, change: Dict[str, Any]) -> bool:
        """
        Process a page-level change with proper granularity.
        
        Args:
            change: Page change from sync_changelog
            
        Returns:
            True if processing succeeded, False otherwise
        """
        try:
            self.logger.info(f"Processing page change {change['id']}: {change['record_id']}")
            
            # Convert to appropriate sync items
            sync_items = await self.page_manager.convert_page_change_to_sync_items(change)
            
            if not sync_items:
                self.logger.warning(f"No sync items created for page change {change['id']}")
                return False
            
            self.logger.info(f"Created {len(sync_items)} sync items for page change {change['id']}")
            
            # Process each sync item
            success_count = 0
            for i, sync_item in enumerate(sync_items):
                self.logger.debug(f"Processing sync item {i+1}/{len(sync_items)}: {sync_item.item_type} - {sync_item.item_id}")
                # Use existing sync processor logic for each item
                success = await self._process_single_sync_item(sync_item)
                if success:
                    success_count += 1
                    self.logger.debug(f"Sync item {i+1} succeeded")
                else:
                    self.logger.warning(f"Sync item {i+1} failed")
            
            self.logger.info(f"Page change {change['id']}: {success_count}/{len(sync_items)} sync items succeeded")
            
            # Mark original change as processed if at least one item succeeded
            if success_count > 0:
                await self._mark_page_change_processed(change['id'], f"Processed {success_count}/{len(sync_items)} sync items")
                return True
            else:
                self.logger.error(f"All sync items failed for page change {change['id']}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error processing page change {change.get('id')}: {e}")
            return False
    
    async def _process_single_sync_item(self, sync_item: SyncItem) -> bool:
        """Process a single sync item using available targets."""
        try:
            # Get available targets from the sync processor
            for target_name, target in self.sync_processor.targets.items():
                # Check if target supports this item type
                target_info = target.get_target_info()
                capabilities = target_info.get('capabilities', {})
                
                should_sync = False
                if sync_item.item_type == SyncItemType.NOTEBOOK and capabilities.get('notebooks', False):
                    should_sync = True
                elif sync_item.item_type == SyncItemType.PAGE_TEXT and capabilities.get('page_text', False):
                    should_sync = True
                
                if not should_sync:
                    continue
                
                # Check for duplicates
                existing_id = await self.sync_processor.dedup_service.is_duplicate(
                    sync_item.content_hash, target_name
                )
                
                if existing_id:
                    # Update existing item
                    result = await target.update_item(existing_id, sync_item)
                    action = "update"
                else:
                    # Create new item
                    result = await target.sync_item(sync_item)
                    action = "create"
                
                # Handle result
                if result.success:
                    await self.sync_processor.dedup_service.register_sync(
                        sync_item.content_hash,
                        target_name,
                        result.target_id,
                        sync_item.item_type,
                        SyncStatus.SUCCESS
                    )
                    
                    self.logger.info(
                        f"Successfully {action}d {sync_item.item_type.value} "
                        f"{sync_item.item_id} in {target_name}"
                    )
                    return True
                else:
                    self.logger.error(
                        f"Failed to {action} {sync_item.item_type.value} "
                        f"{sync_item.item_id} in {target_name}: {result.error_message}"
                    )
            
            return False
            
        except Exception as e:
            self.logger.error(f"Error processing sync item {sync_item.item_id}: {e}")
            return False
    
    async def _mark_page_change_processed(self, change_id: int, note: str) -> None:
        """Mark a page change as processed."""
        try:
            with self.sync_processor.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE sync_changelog 
                    SET processed_at = CURRENT_TIMESTAMP,
                        process_status = ?
                    WHERE id = ?
                ''', (note, change_id))
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"Error marking page change {change_id} as processed: {e}")


if __name__ == "__main__":
    # Example usage for testing
    import asyncio
    from src.core.database import DatabaseManager
    from src.core.sync_engine import DeduplicationService
    
    async def test_page_level_sync():
        db_manager = DatabaseManager("remarkable_pipeline.db")
        dedup_service = DeduplicationService(db_manager)
        page_manager = PageLevelSyncManager(db_manager, dedup_service)
        
        # Test with a sample page change
        test_change = {
            'id': 1,
            'table_name': 'pages',
            'record_id': '79281395-00c4-4a11-9b32-7205f2e682a9|13',
            'change_type': 'INSERT',
            'change_data': {},
            'created_at': '2025-09-10 18:29:50'
        }
        
        print("Testing page-level sync conversion...")
        sync_items = await page_manager.convert_page_change_to_sync_items(test_change)
        
        print(f"Created {len(sync_items)} sync items:")
        for item in sync_items:
            print(f"  {item.item_type.value}: {item.item_id}")
            print(f"    Hash: {item.content_hash[:16]}...")
            print(f"    Type: {item.data.get('sync_type', 'unknown')}")
    
    # Run the test
    asyncio.run(test_page_level_sync())