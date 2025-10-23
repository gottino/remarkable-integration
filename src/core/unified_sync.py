"""
Unified Sync Manager for reMarkable Integration.

This module provides a unified interface for managing sync operations across
multiple targets (Notion, Readwise, etc.) using a target-agnostic approach.

Key Features:
- Target-agnostic sync management using target_name
- Content-hash based change detection and deduplication
- Unified sync_records table for all targets
- Integration with existing SyncTarget interface
- Support for incremental and real-time sync
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union

from .database import DatabaseManager
from .sync_engine import SyncItem, SyncResult, SyncStatus, SyncItemType, ContentFingerprint

logger = logging.getLogger(__name__)


class UnifiedSyncManager:
    """
    Unified sync manager that coordinates sync operations across all targets.
    
    This replaces target-specific sync managers with a single unified interface
    that can handle multiple sync targets using the target_name approach.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(f"{__name__}.UnifiedSyncManager")
        self.targets: Dict[str, 'SyncTarget'] = {}
        self._ensure_sync_records_table()
    
    def _ensure_sync_records_table(self):
        """Ensure the unified sync_records table exists with all required columns."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sync_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content_hash TEXT NOT NULL,
                        target_name TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        item_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        item_id TEXT,
                        metadata TEXT,
                        error_message TEXT,
                        retry_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        synced_at TIMESTAMP,
                        UNIQUE(content_hash, target_name)
                    )
                ''')
                
                # Create indexes for efficient lookups
                indexes = [
                    'CREATE INDEX IF NOT EXISTS idx_sync_records_hash ON sync_records(content_hash)',
                    'CREATE INDEX IF NOT EXISTS idx_sync_records_target ON sync_records(target_name)',
                    'CREATE INDEX IF NOT EXISTS idx_sync_records_status ON sync_records(status)',
                    'CREATE INDEX IF NOT EXISTS idx_sync_records_item_id ON sync_records(item_id)',
                    'CREATE INDEX IF NOT EXISTS idx_sync_records_content_target_item ON sync_records(content_hash, target_name, item_id)',
                ]
                
                for index_sql in indexes:
                    cursor.execute(index_sql)

                # Create page_sync_records table for per-page tracking
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS page_sync_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        notebook_uuid TEXT NOT NULL,
                        page_number INTEGER NOT NULL,
                        content_hash TEXT NOT NULL,
                        target_name TEXT NOT NULL,
                        notion_page_id TEXT,
                        notion_block_id TEXT,
                        status TEXT NOT NULL,
                        error_message TEXT,
                        retry_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        synced_at TIMESTAMP,
                        UNIQUE(notebook_uuid, page_number, target_name)
                    )
                ''')

                # Create indexes for page_sync_records
                page_indexes = [
                    'CREATE INDEX IF NOT EXISTS idx_page_sync_notebook ON page_sync_records(notebook_uuid)',
                    'CREATE INDEX IF NOT EXISTS idx_page_sync_hash ON page_sync_records(content_hash)',
                    'CREATE INDEX IF NOT EXISTS idx_page_sync_target ON page_sync_records(target_name)',
                    'CREATE INDEX IF NOT EXISTS idx_page_sync_status ON page_sync_records(status)',
                    'CREATE INDEX IF NOT EXISTS idx_page_sync_notion_page ON page_sync_records(notion_page_id)',
                    'CREATE INDEX IF NOT EXISTS idx_page_sync_notion_block ON page_sync_records(notion_block_id)',
                ]

                for index_sql in page_indexes:
                    cursor.execute(index_sql)

                conn.commit()
                self.logger.debug("Unified sync_records and page_sync_records tables with indexes ensured")
        except Exception as e:
            self.logger.error(f"Error ensuring sync records table: {e}")
            raise
    
    def register_target(self, target: 'SyncTarget'):
        """
        Register a sync target with the unified manager.
        
        Args:
            target: SyncTarget implementation
        """
        target_name = target.target_name
        self.targets[target_name] = target
        self.logger.info(f"Registered sync target: {target_name}")
    
    def unregister_target(self, target_name: str):
        """
        Unregister a sync target.

        Args:
            target_name: Name of target to unregister
        """
        if target_name in self.targets:
            del self.targets[target_name]
            self.logger.info(f"Unregistered sync target: {target_name}")

    def get_target(self, target_name: str):
        """
        Get a registered sync target by name.

        Args:
            target_name: Name of target to retrieve

        Returns:
            SyncTarget instance if found, None otherwise
        """
        return self.targets.get(target_name)

    async def sync_item_to_target(self, item: SyncItem, target_name: str) -> SyncResult:
        """
        Sync a single item to a specific target.
        
        Args:
            item: The item to sync
            target_name: Name of the target to sync to
            
        Returns:
            SyncResult indicating success/failure
        """
        if target_name not in self.targets:
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=f"Target '{target_name}' not registered"
            )
        
        target = self.targets[target_name]
        
        try:
            # Calculate content hash if not provided
            if not item.content_hash:
                if hasattr(target, 'calculate_content_hash'):
                    item.content_hash = target.calculate_content_hash(item)
                else:
                    # Fallback: basic hash of the item data
                    import hashlib
                    item.content_hash = hashlib.md5(str(item.data).encode('utf-8')).hexdigest()

            # Check for existing sync record
            # For PAGE_TEXT items, use page_sync_records table; for others use sync_records
            if item.item_type == SyncItemType.PAGE_TEXT:
                existing_sync = await self.get_page_sync_record(item.item_id, target_name)
            else:
                existing_sync = await self.get_sync_record(item.content_hash, target_name)

            if existing_sync and existing_sync['status'] == 'success':
                # Check if content has changed (for page syncs)
                if item.item_type == SyncItemType.PAGE_TEXT:
                    if existing_sync.get('content_hash') == item.content_hash:
                        self.logger.debug(f"Page already synced with same content: {item.item_id}")
                        return SyncResult(
                            status=SyncStatus.SKIPPED,
                            target_id=existing_sync.get('notion_page_id', ''),
                            metadata={'reason': 'already_synced', 'content_unchanged': True}
                        )
                    else:
                        self.logger.info(f"Page content changed, will re-sync: {item.item_id}")
                else:
                    # Already synced successfully (non-page items)
                    self.logger.debug(f"Item already synced to {target_name}: {item.content_hash[:8]}...")
                    return SyncResult(
                        status=SyncStatus.SKIPPED,
                        target_id=existing_sync['external_id'],
                        metadata={'reason': 'already_synced'}
                    )

            # Log details for debugging
            self.logger.info(f"🔄 Syncing item {item.item_id} to {target_name}")
            self.logger.info(f"   Content hash: {item.content_hash[:8]}...")
            self.logger.info(f"   Item type: {item.item_type}")
            if existing_sync:
                self.logger.info(f"   Previous sync status: {existing_sync['status']}")
                self.logger.info(f"   Previous hash: {existing_sync.get('content_hash', 'N/A')[:8]}...")
            else:
                self.logger.info(f"   No previous sync record found")

            # Attempt to sync the item
            self.logger.info(f"   Calling target.sync_item for {target_name}...")
            result = await target.sync_item(item)
            self.logger.info(f"   Target returned: status={result.status}, error={result.error_message}")

            # Record the sync result
            await self.record_sync_result(
                content_hash=item.content_hash,
                target_name=target_name,
                item_id=item.item_id,
                item_type=item.item_type,
                result=result,
                metadata={
                    'source_table': item.source_table,
                    'created_at': item.created_at.isoformat(),
                    'updated_at': item.updated_at.isoformat()
                }
            )
            
            return result
            
        except Exception as e:
            error_msg = f"Error syncing to {target_name}: {e}"
            self.logger.error(error_msg)
            self.logger.error(f"Item details - Type: {item.item_type}, ID: {item.item_id}, Hash: {item.content_hash[:8]}...")

            # Create detailed error result
            error_result = SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e),
                metadata={
                    'item_type': item.item_type.value,
                    'item_id': item.item_id,
                    'target_name': target_name,
                    'error_type': type(e).__name__
                }
            )

            # Record the failure
            await self.record_sync_result(
                content_hash=item.content_hash,
                target_name=target_name,
                item_id=item.item_id,
                item_type=item.item_type,
                result=error_result
            )

            return error_result
    
    async def sync_item_to_all_targets(self, item: SyncItem, 
                                     exclude_targets: Optional[Set[str]] = None) -> Dict[str, SyncResult]:
        """
        Sync a single item to all registered targets.
        
        Args:
            item: The item to sync
            exclude_targets: Set of target names to exclude
            
        Returns:
            Dictionary mapping target names to sync results
        """
        if exclude_targets is None:
            exclude_targets = set()
        
        results = {}
        
        for target_name in self.targets:
            if target_name in exclude_targets:
                continue
                
            result = await self.sync_item_to_target(item, target_name)
            results[target_name] = result
        
        return results
    
    async def get_page_sync_record(self, item_id: str, target_name: str) -> Optional[Dict[str, Any]]:
        """
        Get sync record for a specific page from page_sync_records table.

        Args:
            item_id: Item ID in format "notebook_uuid:page:page_number"
            target_name: Name of the target

        Returns:
            Sync record dict or None if not found
        """
        try:
            # Parse item_id to extract notebook_uuid and page_number
            parts = item_id.split(':page:')
            if len(parts) != 2:
                self.logger.error(f"Invalid page item_id format: {item_id}")
                return None

            notebook_uuid = parts[0]
            page_number = int(parts[1])

            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, notebook_uuid, page_number, content_hash, target_name,
                           notion_page_id, notion_block_id, status, error_message,
                           retry_count, created_at, updated_at, synced_at
                    FROM page_sync_records
                    WHERE notebook_uuid = ? AND page_number = ? AND target_name = ?
                ''', (notebook_uuid, page_number, target_name))

                row = cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'notebook_uuid': row[1],
                        'page_number': row[2],
                        'content_hash': row[3],
                        'target_name': row[4],
                        'notion_page_id': row[5],
                        'notion_block_id': row[6],
                        'status': row[7],
                        'error_message': row[8],
                        'retry_count': row[9],
                        'created_at': row[10],
                        'updated_at': row[11],
                        'synced_at': row[12]
                    }
                return None

        except Exception as e:
            self.logger.error(f"Error getting page sync record: {e}")
            return None

    async def get_sync_record(self, content_hash: str, target_name: str) -> Optional[Dict[str, Any]]:
        """
        Get sync record for a specific content hash and target.

        Args:
            content_hash: Hash of the content
            target_name: Name of the target

        Returns:
            Sync record dict or None if not found
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, content_hash, target_name, external_id, item_type, status,
                           item_id, metadata, error_message, retry_count,
                           created_at, updated_at, synced_at
                    FROM sync_records
                    WHERE content_hash = ? AND target_name = ?
                ''', (content_hash, target_name))

                row = cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'content_hash': row[1],
                        'target_name': row[2],
                        'external_id': row[3],
                        'item_type': row[4],
                        'status': row[5],
                        'item_id': row[6],
                        'metadata': json.loads(row[7]) if row[7] else {},
                        'error_message': row[8],
                        'retry_count': row[9],
                        'created_at': row[10],
                        'updated_at': row[11],
                        'synced_at': row[12]
                    }
                return None

        except Exception as e:
            self.logger.error(f"Error getting sync record: {e}")
            return None
    
    async def record_sync_result(self, content_hash: str, target_name: str,
                               item_id: str, item_type: SyncItemType,
                               result: SyncResult, metadata: Optional[Dict] = None):
        """
        Record a sync result in the appropriate table (page_sync_records for PAGE_TEXT, sync_records for others).

        Args:
            content_hash: Hash of the synced content
            target_name: Name of the target system
            item_id: Local ID of the item
            item_type: Type of item synced
            result: Sync result
            metadata: Additional metadata to store
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.utcnow().isoformat()
                synced_at = now if result.success else None

                # For PAGE_TEXT items, use page_sync_records table
                if item_type == SyncItemType.PAGE_TEXT:
                    # Parse item_id to extract notebook_uuid and page_number
                    parts = item_id.split(':page:')
                    if len(parts) != 2:
                        self.logger.error(f"Invalid page item_id format: {item_id}")
                        return

                    notebook_uuid = parts[0]
                    page_number = int(parts[1])

                    # Extract Notion IDs from result metadata
                    notion_page_id = result.target_id or result.metadata.get('notebook_page_id') if result.metadata else None
                    notion_block_id = result.metadata.get('page_block_id') if result.metadata else None

                    cursor.execute('''
                        INSERT OR REPLACE INTO page_sync_records
                        (notebook_uuid, page_number, content_hash, target_name,
                         notion_page_id, notion_block_id, status, error_message,
                         retry_count, created_at, updated_at, synced_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        notebook_uuid,
                        page_number,
                        content_hash,
                        target_name,
                        notion_page_id,
                        notion_block_id,
                        result.status.value,
                        result.error_message,
                        0,  # retry_count - reset on new attempt
                        now,
                        now,
                        synced_at
                    ))

                    self.logger.debug(f"Recorded page sync result: {notebook_uuid} page {page_number} -> {target_name} = {result.status.value}")

                else:
                    # For non-page items, use sync_records table
                    # Merge metadata
                    final_metadata = metadata or {}
                    if result.metadata:
                        final_metadata.update(result.metadata)

                    cursor.execute('''
                        INSERT OR REPLACE INTO sync_records
                        (content_hash, target_name, external_id, item_type, status,
                         item_id, metadata, error_message, retry_count,
                         created_at, updated_at, synced_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        content_hash,
                        target_name,
                        result.target_id or '',
                        item_type.value,
                        result.status.value,
                        item_id,
                        json.dumps(final_metadata),
                        result.error_message,
                        0,  # retry_count - reset on new attempt
                        now,
                        now,
                        synced_at
                    ))

                    self.logger.debug(f"Recorded sync result: {content_hash[:8]}... -> {target_name} = {result.status.value}")

                conn.commit()

        except Exception as e:
            self.logger.error(f"Error recording sync result: {e}")
            raise
    
    async def get_sync_stats(self, target_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get sync statistics for all targets or a specific target.
        
        Args:
            target_name: Optional target name to filter by
            
        Returns:
            Dictionary with sync statistics
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Base query conditions
                where_clause = ""
                params = []
                if target_name:
                    where_clause = "WHERE target_name = ?"
                    params.append(target_name)
                
                # Overall stats
                cursor.execute(f'SELECT COUNT(*) FROM sync_records {where_clause}', params)
                total_records = cursor.fetchone()[0]
                
                # Stats by status
                cursor.execute(f'''
                    SELECT status, COUNT(*) 
                    FROM sync_records {where_clause}
                    GROUP BY status
                ''', params)
                status_counts = dict(cursor.fetchall())
                
                # Stats by target (if not filtering by target)
                if not target_name:
                    cursor.execute('''
                        SELECT target_name, COUNT(*) 
                        FROM sync_records 
                        GROUP BY target_name
                    ''')
                    target_counts = dict(cursor.fetchall())
                else:
                    target_counts = {target_name: total_records}
                
                # Stats by item type
                cursor.execute(f'''
                    SELECT item_type, COUNT(*) 
                    FROM sync_records {where_clause}
                    GROUP BY item_type
                ''', params)
                type_counts = dict(cursor.fetchall())
                
                # Recent activity (last 24 hours)
                cursor.execute(f'''
                    SELECT COUNT(*) 
                    FROM sync_records {where_clause}
                    {"AND" if where_clause else "WHERE"} updated_at > datetime('now', '-1 day')
                ''', params)
                recent_activity = cursor.fetchone()[0]
                
                return {
                    'target_name': target_name or 'all',
                    'total_records': total_records,
                    'status_counts': status_counts,
                    'target_counts': target_counts,
                    'type_counts': type_counts,
                    'recent_activity_24h': recent_activity
                }
                
        except Exception as e:
            self.logger.error(f"Error getting sync stats: {e}")
            return {}
    
    async def get_items_needing_sync(self, target_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get items that need to be synced to a specific target.
        
        This identifies content in the database that hasn't been successfully
        synced to the target yet.
        
        Args:
            target_name: Name of the target to check
            limit: Maximum number of items to return
            
        Returns:
            List of items that need syncing
        """
        try:
            items_to_sync = []
            
            # Get notebooks that need syncing
            notebooks = await self._get_notebooks_needing_sync(target_name, limit // 4)
            items_to_sync.extend(notebooks)
            
            # Get todos that need syncing
            todos = await self._get_todos_needing_sync(target_name, limit // 4)
            items_to_sync.extend(todos)
            
            # Get highlights that need syncing
            highlights = await self._get_highlights_needing_sync(target_name, limit // 4)
            items_to_sync.extend(highlights)
            
            # Sort by priority (most recent first)
            items_to_sync.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
            
            return items_to_sync[:limit]
            
        except Exception as e:
            self.logger.error(f"Error getting items needing sync: {e}")
            return []
    
    async def _get_notebooks_needing_sync(self, target_name: str, limit: int) -> List[Dict[str, Any]]:
        """Get notebooks that need syncing to target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Find notebooks that need syncing (either never synced or content has changed)
                cursor.execute('''
                    SELECT nm.notebook_uuid, nm.visible_name, nm.full_path,
                           MAX(nte.updated_at) as last_updated,
                           sr.content_hash as last_synced_hash
                    FROM notebook_metadata nm
                    LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = nm.notebook_uuid
                        AND sr.target_name = ?
                        AND sr.status = 'success'
                        AND sr.item_type = 'notebook'
                    )
                    WHERE nm.deleted = FALSE
                    AND nte.text IS NOT NULL
                    GROUP BY nm.notebook_uuid, nm.visible_name, nm.full_path
                    ORDER BY last_updated DESC
                ''', (target_name,))
                
                notebooks = []
                for row in cursor.fetchall():
                    notebook_uuid, visible_name, full_path, last_updated, last_synced_hash = row

                    # Fetch individual pages for this notebook
                    cursor.execute('''
                        SELECT nte.page_number, nte.text, nte.confidence, nte.page_uuid,
                               nte.updated_at
                        FROM notebook_text_extractions nte
                        WHERE nte.notebook_uuid = ?
                            AND nte.text IS NOT NULL AND length(nte.text) > 0
                        ORDER BY nte.page_number
                    ''', (notebook_uuid,))

                    pages_data = []
                    for page_row in cursor.fetchall():
                        page_number, text, confidence, page_uuid, page_updated = page_row
                        pages_data.append({
                            'page_number': page_number,
                            'text': text,
                            'confidence': confidence or 0.0,
                            'page_uuid': page_uuid,
                            'updated_at': page_updated
                        })

                    if not pages_data:
                        continue  # Skip notebooks with no text content

                    # Convert pages to text_content for ContentFingerprint compatibility
                    text_content = '\n'.join([
                        f"Page {page['page_number']}: {page['text']}"
                        for page in pages_data
                        if page.get('text', '').strip()
                    ])

                    # Create data structure compatible with ContentFingerprint.for_notebook()
                    fingerprint_data = {
                        'title': visible_name or 'Untitled Notebook',
                        'author': '',  # reMarkable doesn't have author concept
                        'text_content': text_content,
                        'page_count': len(pages_data),
                        'type': 'notebook'
                    }
                    content_hash = ContentFingerprint.for_notebook(fingerprint_data)

                    # Create the actual data structure for sync (includes both formats)
                    notebook_data = {
                        'notebook_uuid': notebook_uuid,
                        'notebook_name': visible_name or 'Untitled Notebook',
                        'title': visible_name or 'Untitled Notebook',  # For compatibility
                        'pages': pages_data,
                        'text_content': text_content,  # For hash consistency
                        'page_count': len(pages_data),
                        'type': 'notebook'
                    }

                    # Only include if content has changed or never synced
                    if last_synced_hash is None or last_synced_hash != content_hash:
                        notebooks.append({
                            'item_type': 'notebook',
                            'item_id': notebook_uuid,
                            'content_hash': content_hash,
                            'data': {
                                **notebook_data,
                                'full_path': full_path,
                                'created_at': last_updated,
                                'updated_at': last_updated
                            },
                            'source_table': 'notebook_text_extractions',
                            'updated_at': last_updated or datetime.now().isoformat()
                        })

                # Apply limit after filtering
                return notebooks[:limit]
                
        except Exception as e:
            self.logger.error(f"Error getting notebooks needing sync: {e}")
            return []
    
    async def _get_todos_needing_sync(self, target_name: str, limit: int) -> List[Dict[str, Any]]:
        """Get todos that need syncing to target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT t.id, t.notebook_uuid, t.text, t.page_number, t.updated_at,
                           sr.content_hash as last_synced_hash,
                           nm.visible_name as notebook_name,
                           nns.notion_page_id,
                           npb.notion_block_id,
                           t.actual_date, t.confidence, t.created_at
                    FROM todos t
                    LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
                    LEFT JOIN notion_notebook_sync nns ON t.notebook_uuid = nns.notebook_uuid
                    LEFT JOIN notion_page_blocks npb ON t.notebook_uuid = npb.notebook_uuid
                        AND t.page_number = npb.page_number
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = CAST(t.id AS TEXT)
                        AND sr.target_name = ?
                        AND sr.status = 'success'
                        AND sr.item_type = 'todo'
                    )
                    WHERE t.completed = FALSE
                    ORDER BY t.updated_at DESC
                ''', (target_name,))
                
                todos = []
                for row in cursor.fetchall():
                    (todo_id, notebook_uuid, text, page_number, updated_at, last_synced_hash,
                     notebook_name, notion_page_id, notion_block_id, actual_date, confidence, created_at) = row

                    # Generate content hash
                    todo_data = {
                        'text': text,
                        'notebook_uuid': notebook_uuid,
                        'page_number': page_number,
                        'type': 'todo'
                    }
                    content_hash = ContentFingerprint.for_todo(todo_data)

                    # Only include if content has changed or never synced
                    if last_synced_hash is None or last_synced_hash != content_hash:
                        todos.append({
                            'item_type': 'todo',
                            'item_id': str(todo_id),
                            'content_hash': content_hash,
                            'data': {
                                **todo_data,
                                'todo_id': todo_id,
                                'notebook_name': notebook_name,
                                'notion_page_id': notion_page_id,
                                'notion_block_id': notion_block_id,
                                'actual_date': actual_date,
                                'confidence': confidence or 0.0,
                                'created_at': created_at,
                                'completed': False  # Since we filter for completed = FALSE
                            },
                            'source_table': 'todos',
                            'updated_at': updated_at or datetime.now().isoformat()
                        })

                # Apply limit after filtering
                return todos[:limit]
                
        except Exception as e:
            self.logger.error(f"Error getting todos needing sync: {e}")
            return []
    
    async def _get_highlights_needing_sync(self, target_name: str, limit: int) -> List[Dict[str, Any]]:
        """Get highlights that need syncing to target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT eh.id, eh.source_file, eh.title, eh.original_text,
                           eh.corrected_text, eh.page_number, eh.updated_at,
                           sr.content_hash as last_synced_hash
                    FROM enhanced_highlights eh
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = CAST(eh.id AS TEXT)
                        AND sr.target_name = ?
                        AND sr.status = 'success'
                        AND sr.item_type = 'highlight'
                    )
                    ORDER BY eh.updated_at DESC
                ''', (target_name,))
                
                highlights = []
                for row in cursor.fetchall():
                    highlight_id, source_file, title, original_text, corrected_text, page_number, updated_at, last_synced_hash = row
                    
                    # Generate content hash
                    highlight_data = {
                        'text': original_text,
                        'corrected_text': corrected_text,
                        'source_file': source_file,
                        'page_number': page_number,
                        'type': 'highlight'
                    }
                    content_hash = ContentFingerprint.for_highlight(highlight_data)

                    # Only include if content has changed or never synced
                    if last_synced_hash is None or last_synced_hash != content_hash:
                        highlights.append({
                            'item_type': 'highlight',
                            'item_id': str(highlight_id),
                            'content_hash': content_hash,
                            'data': {
                                **highlight_data,
                                'highlight_id': highlight_id,
                                'title': title
                            },
                            'source_table': 'enhanced_highlights',
                            'updated_at': updated_at or datetime.now().isoformat()
                        })

                # Apply limit after filtering
                return highlights[:limit]
                
        except Exception as e:
            self.logger.error(f"Error getting highlights needing sync: {e}")
            return []
    
    async def cleanup_failed_syncs(self, max_retries: int = 3, older_than_hours: int = 24):
        """
        Clean up failed sync records that have exceeded retry limits.
        
        Args:
            max_retries: Maximum number of retries before giving up
            older_than_hours: Only clean up failures older than this many hours
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    DELETE FROM sync_records 
                    WHERE status = 'failed' 
                    AND retry_count >= ?
                    AND updated_at < datetime('now', '-{} hours')
                '''.format(older_than_hours), (max_retries,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    self.logger.info(f"Cleaned up {deleted_count} failed sync records")
                    
        except Exception as e:
            self.logger.error(f"Error cleaning up failed syncs: {e}")


if __name__ == "__main__":
    # Example usage
    import asyncio
    from .database import DatabaseManager
    
    async def test_unified_sync():
        # Initialize components
        db_manager = DatabaseManager("test_unified_sync.db")
        sync_manager = UnifiedSyncManager(db_manager)
        
        # Get sync stats
        stats = await sync_manager.get_sync_stats()
        print(f"Sync stats: {stats}")
        
        # Check items needing sync
        items = await sync_manager.get_items_needing_sync("notion", limit=5)
        print(f"Items needing sync: {len(items)}")
    
    # Run test
    asyncio.run(test_unified_sync())