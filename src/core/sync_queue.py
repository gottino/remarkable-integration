"""
Sync Queue Processor for the Event-Driven Sync Engine

This module processes pending changes from our existing sync_changelog table
and coordinates syncing to multiple downstream targets with intelligent 
retry logic and error handling.
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
import json

from .sync_engine import (
    SyncTarget, SyncItem, SyncResult, SyncStatus, SyncItemType, 
    ContentFingerprint, DeduplicationService
)
from .page_level_sync import PageLevelSyncManager, PageAwareSyncProcessor

logger = logging.getLogger(__name__)


@dataclass
class SyncQueueConfig:
    """Configuration for the sync queue processor."""
    batch_size: int = 10  # Number of items to process in one batch
    retry_delay_base: int = 30  # Base delay in seconds for retries
    max_retry_delay: int = 3600  # Maximum delay in seconds (1 hour)
    max_retries: int = 5  # Maximum number of retry attempts
    concurrent_syncs: int = 3  # Number of concurrent sync operations
    health_check_interval: int = 300  # Health check interval in seconds (5 min)
    stale_threshold_hours: int = 24  # Consider syncs stale after this many hours


class SyncQueueProcessor:
    """
    Processes sync queue items from the existing sync_changelog table.
    
    This leverages our existing change tracking infrastructure to drive
    the event-driven sync engine. It reads from sync_changelog and
    pushes changes to configured sync targets.
    """
    
    def __init__(self, db_manager, config: Optional[SyncQueueConfig] = None):
        self.db_manager = db_manager
        self.config = config or SyncQueueConfig()
        self.targets: Dict[str, SyncTarget] = {}
        self.dedup_service = DeduplicationService(db_manager)
        self.page_sync_manager = PageLevelSyncManager(db_manager, self.dedup_service)
        self.page_processor = PageAwareSyncProcessor(self, self.page_sync_manager)
        self.logger = logging.getLogger(f"{__name__}.SyncQueueProcessor")
        self.is_running = False
        self._stop_event = asyncio.Event()
    
    def add_target(self, target: SyncTarget) -> None:
        """Add a sync target to the processor."""
        self.targets[target.target_name] = target
        self.logger.info(f"Added sync target: {target.target_name}")
    
    def remove_target(self, target_name: str) -> bool:
        """Remove a sync target from the processor."""
        if target_name in self.targets:
            del self.targets[target_name]
            self.logger.info(f"Removed sync target: {target_name}")
            return True
        return False
    
    async def start(self) -> None:
        """Start the sync queue processor."""
        if self.is_running:
            self.logger.warning("Sync queue processor already running")
            return
        
        self.is_running = True
        self._stop_event.clear()
        self.logger.info("Starting sync queue processor")
        
        # Start main processing loop
        await self._run_processor()
    
    async def stop(self) -> None:
        """Stop the sync queue processor."""
        if not self.is_running:
            return
        
        self.logger.info("Stopping sync queue processor")
        self.is_running = False
        self._stop_event.set()
    
    async def _run_processor(self) -> None:
        """Main processing loop."""
        try:
            while self.is_running:
                # Process pending changes
                await self._process_pending_changes()
                
                # Retry failed syncs
                await self._retry_failed_syncs()
                
                # Health check
                await self._health_check()
                
                # Wait before next iteration
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), 
                        timeout=30.0  # Check every 30 seconds
                    )
                    break  # Stop event was set
                except asyncio.TimeoutError:
                    continue  # Normal timeout, continue processing
                    
        except Exception as e:
            self.logger.error(f"Error in sync processor main loop: {e}")
        finally:
            self.is_running = False
            self.logger.info("Sync queue processor stopped")
    
    async def _process_pending_changes(self) -> None:
        """Process pending changes from the sync_changelog."""
        try:
            pending_changes = await self._get_pending_changes()
            
            if not pending_changes:
                return
            
            self.logger.info(f"Processing {len(pending_changes)} pending changes")
            
            # Group changes by target for efficient processing
            for target_name, target in self.targets.items():
                self.logger.info(f"Checking {len(pending_changes)} changes for target {target_name}")
                
                target_changes = []
                for change in pending_changes:
                    should_sync = await self._should_sync_to_target(change, target)
                    if should_sync:
                        target_changes.append(change)
                    else:
                        self.logger.debug(f"Skipping change {change['id']} for target {target_name}: not supported")
                
                self.logger.info(f"Target {target_name}: {len(target_changes)} eligible changes")
                
                if target_changes:
                    await self._process_target_changes(target, target_changes)
                else:
                    self.logger.warning(f"No changes eligible for target {target_name}")
                    
        except Exception as e:
            self.logger.error(f"Error processing pending changes: {e}")
    
    async def _get_pending_changes(self) -> List[Dict[str, Any]]:
        """Get pending changes from sync_changelog."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get unprocessed changes
                cursor.execute('''
                    SELECT sc.id, sc.source_table, sc.source_id, sc.operation, 
                           sc.changed_fields, sc.changed_at
                    FROM sync_changelog sc
                    WHERE sc.processed_at IS NULL
                    ORDER BY sc.changed_at ASC
                    LIMIT ?
                ''', (self.config.batch_size,))
                
                changes = []
                for row in cursor.fetchall():
                    changed_fields = json.loads(row[4]) if row[4] else {}
                    changes.append({
                        'id': row[0],
                        'table_name': row[1],  # source_table
                        'record_id': row[2],   # source_id
                        'change_type': row[3], # operation
                        'change_data': changed_fields,
                        'created_at': row[5]   # changed_at
                    })
                
                return changes
                
        except Exception as e:
            self.logger.error(f"Error getting pending changes: {e}")
            return []
    
    async def _should_sync_to_target(self, change: Dict[str, Any], target: SyncTarget) -> bool:
        """Determine if a change should be synced to a specific target."""
        table_name = change['table_name']
        change_type = change['change_type']
        
        # Get target capabilities
        target_info = target.get_target_info()
        capabilities = target_info.get('capabilities', {})
        
        self.logger.debug(f"Checking change {change['id']} ({table_name}) against target {target.target_name} capabilities: {capabilities}")
        
        # Check if target supports this type of content
        if table_name == 'notebook_text_extractions' and capabilities.get('notebooks', False):
            return True
        elif table_name == 'pages' and capabilities.get('page_text', False):
            return True
        elif table_name == 'todos' and capabilities.get('todos', False):
            return True
        elif table_name == 'highlights' and capabilities.get('highlights', False):
            return True
        elif table_name == 'enhanced_highlights' and capabilities.get('highlights', False):
            return True
        
        self.logger.debug(f"Change {change['id']} not eligible for target {target.target_name}: {table_name} not supported")
        return False
    
    async def _process_target_changes(self, target: SyncTarget, changes: List[Dict[str, Any]]) -> None:
        """Process changes for a specific target."""
        try:
            self.logger.debug(f"Processing {len(changes)} changes for target {target.target_name}")
            
            # Create semaphore to limit concurrent syncs
            semaphore = asyncio.Semaphore(self.config.concurrent_syncs)
            
            # Process changes concurrently
            tasks = []
            for change in changes:
                task = asyncio.create_task(
                    self._process_single_change(target, change, semaphore)
                )
                tasks.append(task)
            
            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log results
            success_count = sum(1 for r in results if isinstance(r, bool) and r)
            error_count = sum(1 for r in results if isinstance(r, Exception))
            
            self.logger.info(
                f"Target {target.target_name}: {success_count} successful, "
                f"{error_count} errors out of {len(changes)} changes"
            )
            
        except Exception as e:
            self.logger.error(f"Error processing changes for target {target.target_name}: {e}")
    
    async def _process_single_change(self, target: SyncTarget, change: Dict[str, Any], 
                                   semaphore: asyncio.Semaphore) -> bool:
        """Process a single change for a target."""
        async with semaphore:
            try:
                self.logger.info(f"Processing change {change['id']}: {change['table_name']} - {change['record_id']}")
                
                # Handle page-level changes with special logic
                if change['table_name'] == 'pages':
                    self.logger.info(f"Delegating page change {change['id']} to page processor")
                    return await self.page_processor.process_page_change(change)
                
                # Convert change to sync item (for non-page changes)
                self.logger.debug(f"Converting change {change['id']} to sync item")
                sync_item = await self._change_to_sync_item(change)
                if not sync_item:
                    self.logger.warning(f"Could not create sync item for change {change['id']}")
                    await self._mark_change_processed(change['id'], "No sync item created")
                    return False
                
                self.logger.info(f"Created sync item for {sync_item.item_type}: {sync_item.item_id}")
                
                # Check for duplicates
                self.logger.debug(f"Checking for duplicates of {sync_item.content_hash}")
                existing_id = await self.dedup_service.is_duplicate(
                    sync_item.content_hash, target.target_name
                )
                
                if existing_id:
                    # Update existing item
                    self.logger.info(f"Updating existing item {existing_id}")
                    result = await target.update_item(existing_id, sync_item)
                    action = "update"
                else:
                    # Create new item
                    self.logger.info(f"Creating new item for {sync_item.item_type}")
                    result = await target.sync_item(sync_item)
                    action = "create"
                
                # Handle result
                self.logger.info(f"Sync result for change {change['id']}: {result.status} - {action}")
                if result.error_message:
                    self.logger.warning(f"Sync error for change {change['id']}: {result.error_message}")
                
                await self._handle_sync_result(
                    target, sync_item, result, change['id'], action
                )
                
                return result.success
                
            except Exception as e:
                self.logger.error(f"Error processing change {change['id']} for {target.target_name}: {e}")
                await self._mark_change_processed(
                    change['id'], 
                    f"Processing error: {str(e)}"
                )
                return False
    
    async def _change_to_sync_item(self, change: Dict[str, Any]) -> Optional[SyncItem]:
        """Convert a changelog entry to a sync item."""
        try:
            table_name = change['table_name']
            record_id = change['record_id']
            
            # Handle page-level changes specially
            if table_name == 'pages':
                return await self._handle_page_level_change(change)
            
            # Get the actual record data
            record_data = await self._get_record_data(table_name, record_id)
            if not record_data:
                self.logger.warning(f"No record found for {table_name}.{record_id}")
                return None
            
            # Determine item type and generate content hash
            if table_name == 'notebook_text_extractions':
                item_type = SyncItemType.NOTEBOOK
                content_hash = ContentFingerprint.for_notebook(record_data)
            elif table_name == 'notebooks':
                item_type = SyncItemType.NOTEBOOK
                content_hash = ContentFingerprint.for_notebook(record_data)
            elif table_name == 'todos':
                item_type = SyncItemType.TODO
                content_hash = ContentFingerprint.for_todo(record_data)
            elif table_name in ['highlights', 'enhanced_highlights']:
                item_type = SyncItemType.HIGHLIGHT
                content_hash = ContentFingerprint.for_highlight(record_data)
            else:
                self.logger.warning(f"Unknown table for sync: {table_name}")
                return None
            
            return SyncItem(
                item_type=item_type,
                item_id=record_id,
                content_hash=content_hash,
                data=record_data,
                source_table=table_name,
                created_at=datetime.fromisoformat(change['created_at']),
                updated_at=datetime.now()
            )
            
        except Exception as e:
            self.logger.error(f"Error converting change to sync item: {e}")
            return None
    
    async def _handle_page_level_change(self, change: Dict[str, Any]) -> Optional[SyncItem]:
        """Handle page-level changes by converting them to notebook-level sync items."""
        try:
            # Parse the page record_id format: "notebook_uuid|page_number"
            record_id = change['record_id']
            if '|' not in record_id:
                self.logger.warning(f"Invalid page record_id format: {record_id}")
                return None
            
            notebook_uuid, page_number = record_id.split('|', 1)
            
            # Check if this notebook is already synced
            existing_syncs = await self.dedup_service.find_existing_syncs(f"notebook_{notebook_uuid}")
            notebook_already_synced = any(
                sync.target_name == 'notion' and sync.status == SyncStatus.SUCCESS 
                for sync in existing_syncs
            )
            
            if notebook_already_synced:
                # For already synced notebooks, we need to trigger a notebook update
                # to include the new page content
                self.logger.info(f"Page {record_id} added to already-synced notebook {notebook_uuid} - triggering notebook update")
                
                # Get the full notebook data
                notebook_data = await self._get_record_data('notebooks', notebook_uuid)
                if not notebook_data:
                    self.logger.warning(f"Could not get notebook data for {notebook_uuid}")
                    return None
                
                # Generate content hash for the updated notebook
                content_hash = ContentFingerprint.for_notebook(notebook_data)
                
                return SyncItem(
                    item_type=SyncItemType.NOTEBOOK,
                    item_id=notebook_uuid,
                    content_hash=content_hash,
                    data=notebook_data,
                    source_table='notebooks',
                    created_at=datetime.fromisoformat(change['created_at']),
                    updated_at=datetime.now()
                )
            else:
                # For new notebooks, create a regular notebook sync item
                notebook_data = await self._get_record_data('notebooks', notebook_uuid)
                if not notebook_data:
                    self.logger.warning(f"Could not get notebook data for {notebook_uuid}")
                    return None
                
                content_hash = ContentFingerprint.for_notebook(notebook_data)
                
                return SyncItem(
                    item_type=SyncItemType.NOTEBOOK,
                    item_id=notebook_uuid,
                    content_hash=content_hash,
                    data=notebook_data,
                    source_table='notebooks',
                    created_at=datetime.fromisoformat(change['created_at']),
                    updated_at=datetime.now()
                )
                
        except Exception as e:
            self.logger.error(f"Error handling page-level change: {e}")
            return None
    
    async def _get_record_data(self, table_name: str, record_id: str) -> Optional[Dict[str, Any]]:
        """Get the full record data for a table/record_id."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                if table_name in ['notebook_text_extractions', 'notebooks']:
                    # Get aggregated notebook data
                    cursor.execute('''
                        SELECT notebook_uuid, notebook_name, 
                               GROUP_CONCAT(text, '\n\n') as full_text,
                               COUNT(*) as page_count,
                               AVG(confidence) as avg_confidence
                        FROM notebook_text_extractions
                        WHERE notebook_uuid = ?
                        GROUP BY notebook_uuid, notebook_name
                    ''', (record_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        return {
                            'notebook_uuid': row[0],
                            'title': row[1] or 'Untitled Notebook',
                            'text_content': row[2] or '',
                            'page_count': row[3],
                            'avg_confidence': row[4],
                            'type': 'notebook'
                        }
                
                elif table_name == 'todos':
                    cursor.execute('''
                        SELECT notebook_uuid, page_number, text, 
                               confidence, created_at
                        FROM todos
                        WHERE id = ?
                    ''', (record_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        return {
                            'notebook_uuid': row[0],
                            'page_number': row[1],
                            'text': row[2],
                            'confidence': row[3],
                            'created_at': row[4],
                            'type': 'todo'
                        }
                
                elif table_name in ['highlights', 'enhanced_highlights']:
                    cursor.execute(f'''
                        SELECT source_file, page_number, text, 
                               corrected_text, created_at
                        FROM {table_name}
                        WHERE id = ?
                    ''', (record_id,))
                    
                    row = cursor.fetchone()
                    if row:
                        return {
                            'source_file': row[0],
                            'page_number': row[1],
                            'text': row[2],
                            'corrected_text': row[3],
                            'created_at': row[4],
                            'type': 'highlight'
                        }
                
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting record data for {table_name}.{record_id}: {e}")
            return None
    
    async def _handle_sync_result(self, target: SyncTarget, item: SyncItem, 
                                result: SyncResult, change_id: int, action: str) -> None:
        """Handle the result of a sync operation."""
        try:
            if result.success:
                # Register successful sync
                await self.dedup_service.register_sync(
                    item.content_hash,
                    target.target_name,
                    result.target_id,
                    item.item_type,
                    SyncStatus.SUCCESS
                )
                
                # Mark change as processed
                await self._mark_change_processed(
                    change_id,
                    f"Successfully {action}d in {target.target_name}: {result.target_id}"
                )
                
                self.logger.debug(
                    f"Successfully {action}d {item.item_type} {item.item_id} "
                    f"in {target.target_name} as {result.target_id}"
                )
                
            elif result.should_retry:
                # Update sync status for retry
                await self.dedup_service.update_sync_status(
                    item.content_hash,
                    target.target_name,
                    SyncStatus.RETRY,
                    result.error_message
                )
                
                self.logger.warning(
                    f"Sync failed, will retry: {item.item_type} {item.item_id} "
                    f"to {target.target_name}: {result.error_message}"
                )
                
            else:
                # Permanent failure
                await self.dedup_service.update_sync_status(
                    item.content_hash,
                    target.target_name,
                    SyncStatus.FAILED,
                    result.error_message
                )
                
                await self._mark_change_processed(
                    change_id,
                    f"Failed to sync to {target.target_name}: {result.error_message}"
                )
                
                self.logger.error(
                    f"Sync permanently failed: {item.item_type} {item.item_id} "
                    f"to {target.target_name}: {result.error_message}"
                )
                
        except Exception as e:
            self.logger.error(f"Error handling sync result: {e}")
    
    async def _mark_change_processed(self, change_id: int, note: str = None) -> None:
        """Mark a change as processed in the sync_changelog."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE sync_changelog 
                    SET processed_at = CURRENT_TIMESTAMP,
                        process_status = ?
                    WHERE id = ?
                ''', (note, change_id))
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"Error marking change {change_id} as processed: {e}")
    
    async def _retry_failed_syncs(self) -> None:
        """Retry failed sync operations with exponential backoff."""
        try:
            # Get sync records that need retry
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT content_hash, target_name, retry_count, updated_at
                    FROM sync_records
                    WHERE status = 'retry'
                    AND retry_count < ?
                    AND updated_at < datetime('now', '-' || (? * (1 << retry_count)) || ' seconds')
                    LIMIT ?
                ''', (self.config.max_retries, self.config.retry_delay_base, self.config.batch_size))
                
                retry_records = cursor.fetchall()
            
            if not retry_records:
                return
            
            self.logger.info(f"Retrying {len(retry_records)} failed syncs")
            
            # Process retries
            for content_hash, target_name, retry_count, updated_at in retry_records:
                if target_name in self.targets:
                    await self._retry_single_sync(content_hash, target_name, retry_count)
                    
        except Exception as e:
            self.logger.error(f"Error retrying failed syncs: {e}")
    
    async def _retry_single_sync(self, content_hash: str, target_name: str, retry_count: int) -> None:
        """Retry a single failed sync operation."""
        try:
            # This would need to reconstruct the sync item from the original data
            # For now, just update the retry count
            await self.dedup_service.update_sync_status(
                content_hash,
                target_name,
                SyncStatus.RETRY,
                f"Retry attempt {retry_count + 1}"
            )
            
            self.logger.debug(f"Scheduled retry {retry_count + 1} for {content_hash[:8]}... -> {target_name}")
            
        except Exception as e:
            self.logger.error(f"Error retrying sync {content_hash} -> {target_name}: {e}")
    
    async def _health_check(self) -> None:
        """Perform health checks on targets and detect stale syncs."""
        try:
            for target_name, target in self.targets.items():
                # Check target connectivity
                is_healthy = await target.validate_connection()
                if not is_healthy:
                    self.logger.warning(f"Target {target_name} failed health check")
                
            # Check for stale syncs
            stale_threshold = datetime.now() - timedelta(hours=self.config.stale_threshold_hours)
            
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM sync_records
                    WHERE status IN ('pending', 'in_progress')
                    AND updated_at < ?
                ''', (stale_threshold.isoformat(),))
                
                stale_count = cursor.fetchone()[0]
                if stale_count > 0:
                    self.logger.warning(f"Found {stale_count} stale sync records")
                    
        except Exception as e:
            self.logger.error(f"Error during health check: {e}")
    
    async def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status and statistics."""
        try:
            # Get deduplication service stats
            dedup_stats = await self.dedup_service.get_sync_stats()
            
            # Get pending changes count
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM sync_changelog WHERE processed_at IS NULL')
                pending_changes = cursor.fetchone()[0]
            
            # Get target info
            target_info = {}
            for name, target in self.targets.items():
                target_info[name] = target.get_target_info()
            
            return {
                'is_running': self.is_running,
                'targets': target_info,
                'pending_changes': pending_changes,
                'sync_records': dedup_stats,
                'config': {
                    'batch_size': self.config.batch_size,
                    'max_retries': self.config.max_retries,
                    'concurrent_syncs': self.config.concurrent_syncs
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting sync status: {e}")
            return {'error': str(e)}


if __name__ == "__main__":
    # Example usage
    import asyncio
    from src.core.database import DatabaseManager
    from .sync_targets import create_sync_target
    
    async def test_sync_processor():
        # Initialize components
        db_manager = DatabaseManager("test_sync.db")
        processor = SyncQueueProcessor(db_manager)
        
        # Add a mock target
        mock_target = create_sync_target("mock", fail_rate=0.1)
        processor.add_target(mock_target)
        
        # Get status
        status = await processor.get_sync_status()
        print(f"Sync processor status: {status}")
        
        # Process pending changes (would run for a short time in real usage)
        await processor._process_pending_changes()
    
    # Run the test
    asyncio.run(test_sync_processor())