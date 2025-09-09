#!/usr/bin/env python3
"""
Generic change tracking system for event-driven sync.

This module provides infrastructure to track changes to any table/record
for reliable master-slave synchronization across multiple targets.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from contextlib import contextmanager

from .database import DatabaseManager

logger = logging.getLogger(__name__)


class ChangeTracker:
    """Generic change tracking system for sync operations."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def track_change(self, source_table: str, source_id: str, operation: str,
                    content_before: Optional[str] = None, 
                    content_after: Optional[str] = None,
                    changed_fields: Optional[List[str]] = None,
                    trigger_source: str = 'system') -> int:
        """
        Track a change in the sync changelog.
        
        Args:
            source_table: Table name (e.g., 'notebooks', 'pages', 'todos')
            source_id: Record identifier (UUID, composite key, etc.)
            operation: 'INSERT', 'UPDATE', 'DELETE'
            content_before: Content before change (for comparison)
            content_after: Content after change (for comparison)
            changed_fields: List of field names that changed
            trigger_source: What triggered the change (e.g., 'file_watcher', 'manual_sync')
        
        Returns:
            int: ID of the changelog entry created
        """
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Calculate content hashes if content provided
            hash_before = None
            hash_after = None
            
            if content_before is not None:
                hash_before = self._calculate_content_hash(content_before)
            
            if content_after is not None:
                hash_after = self._calculate_content_hash(content_after)
            
            # Convert changed_fields to JSON
            changed_fields_json = None
            if changed_fields:
                changed_fields_json = json.dumps(changed_fields)
            
            cursor.execute('''
                INSERT INTO sync_changelog (
                    source_table, source_id, operation, 
                    changed_fields, content_hash_before, content_hash_after,
                    trigger_source, process_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                source_table, source_id, operation,
                changed_fields_json, hash_before, hash_after,
                trigger_source, 'pending'
            ))
            
            changelog_id = cursor.lastrowid
            conn.commit()
            
            logger.debug(f"📝 Tracked {operation} for {source_table}:{source_id} (changelog #{changelog_id})")
            return changelog_id
    
    def track_notebook_change(self, notebook_uuid: str, operation: str, 
                            notebook_data: Optional[Dict] = None,
                            trigger_source: str = 'system') -> int:
        """Track changes to notebook records."""
        content_after = None
        changed_fields = None
        
        if notebook_data:
            # Create a content representation for change detection
            content_after = self._serialize_notebook_content(notebook_data)
            changed_fields = list(notebook_data.keys())
        
        return self.track_change(
            source_table='notebooks',
            source_id=notebook_uuid,
            operation=operation,
            content_after=content_after,
            changed_fields=changed_fields,
            trigger_source=trigger_source
        )
    
    def track_page_change(self, notebook_uuid: str, page_number: int, operation: str,
                         page_data: Optional[Dict] = None,
                         content_before: Optional[str] = None,
                         content_after: Optional[str] = None,
                         trigger_source: str = 'system') -> int:
        """Track changes to page records."""
        source_id = f"{notebook_uuid}|{page_number}"
        
        # Use provided content or extract from page_data
        if content_after is None and page_data and 'text' in page_data:
            content_after = page_data['text']
        
        changed_fields = None
        if page_data:
            changed_fields = list(page_data.keys())
        
        return self.track_change(
            source_table='pages',
            source_id=source_id,
            operation=operation,
            content_before=content_before,
            content_after=content_after,
            changed_fields=changed_fields,
            trigger_source=trigger_source
        )
    
    def track_todo_change(self, todo_id: int, operation: str,
                         todo_data: Optional[Dict] = None,
                         trigger_source: str = 'system') -> int:
        """Track changes to todo records."""
        content_after = None
        changed_fields = None
        
        if todo_data:
            # Create content representation from todo data
            content_after = self._serialize_todo_content(todo_data)
            changed_fields = list(todo_data.keys())
        
        return self.track_change(
            source_table='todos',
            source_id=str(todo_id),
            operation=operation,
            content_after=content_after,
            changed_fields=changed_fields,
            trigger_source=trigger_source
        )
    
    def get_pending_changes(self, source_table: Optional[str] = None, 
                          limit: Optional[int] = None) -> List[Dict]:
        """
        Get pending changes from the changelog.
        
        Args:
            source_table: Filter by table name (optional)
            limit: Maximum number of changes to return
            
        Returns:
            List of change records with full context
        """
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT 
                    cl.id, cl.source_table, cl.source_id, cl.operation,
                    cl.changed_at, cl.changed_fields, cl.content_hash_before, 
                    cl.content_hash_after, cl.trigger_source,
                    ss.sync_target, ss.remote_id, ss.last_synced_content,
                    ss.sync_status, ss.metadata
                FROM sync_changelog cl
                LEFT JOIN sync_state ss ON (
                    cl.source_table = ss.source_table AND 
                    cl.source_id = ss.source_id
                )
                WHERE cl.process_status = 'pending'
            '''
            
            params = []
            if source_table:
                query += ' AND cl.source_table = ?'
                params.append(source_table)
            
            query += ' ORDER BY cl.changed_at ASC'
            
            if limit:
                query += ' LIMIT ?'
                params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Convert to dictionaries for easier handling
            changes = []
            for row in rows:
                change = {
                    'changelog_id': row[0],
                    'source_table': row[1],
                    'source_id': row[2],
                    'operation': row[3],
                    'changed_at': row[4],
                    'changed_fields': json.loads(row[5]) if row[5] else None,
                    'content_hash_before': row[6],
                    'content_hash_after': row[7],
                    'trigger_source': row[8],
                    'sync_target': row[9],
                    'remote_id': row[10],
                    'last_synced_content': row[11],
                    'sync_status': row[12],
                    'metadata': json.loads(row[13]) if row[13] else None
                }
                changes.append(change)
            
            return changes
    
    def mark_changes_processed(self, changelog_ids: List[int], success: bool = True) -> None:
        """
        Mark changelog entries as processed.
        
        Args:
            changelog_ids: List of changelog IDs to mark
            success: Whether processing was successful
        """
        if not changelog_ids:
            return
        
        status = 'processed' if success else 'failed'
        placeholders = ','.join(['?'] * len(changelog_ids))
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE sync_changelog 
                SET process_status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
            ''', [status] + changelog_ids)
            
            conn.commit()
            
            logger.debug(f"📋 Marked {len(changelog_ids)} changes as {status}")
    
    def get_sync_health_metrics(self) -> Dict[str, Any]:
        """Get metrics about sync health and pending changes."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Pending changes by table
            cursor.execute('''
                SELECT source_table, COUNT(*) 
                FROM sync_changelog 
                WHERE process_status = 'pending'
                GROUP BY source_table
            ''')
            pending_by_table = dict(cursor.fetchall())
            
            # Oldest pending change
            cursor.execute('''
                SELECT MIN(changed_at) 
                FROM sync_changelog 
                WHERE process_status = 'pending'
            ''')
            oldest_pending = cursor.fetchone()[0]
            
            # Processing success rate (last 24 hours)
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN process_status = 'processed' THEN 1 ELSE 0 END) as successful
                FROM sync_changelog 
                WHERE processed_at >= datetime('now', '-1 day')
            ''')
            total, successful = cursor.fetchone()
            success_rate = (successful / total * 100) if total > 0 else 100
            
            # Sync state summary
            cursor.execute('''
                SELECT sync_target, sync_status, COUNT(*)
                FROM sync_state
                GROUP BY sync_target, sync_status
            ''')
            sync_state_summary = {}
            for target, status, count in cursor.fetchall():
                if target not in sync_state_summary:
                    sync_state_summary[target] = {}
                sync_state_summary[target][status] = count
            
            return {
                'pending_changes': pending_by_table,
                'total_pending': sum(pending_by_table.values()),
                'oldest_pending': oldest_pending,
                'success_rate_24h': round(success_rate, 1),
                'sync_state_summary': sync_state_summary
            }
    
    @contextmanager
    def batch_tracking(self, trigger_source: str = 'batch_operation'):
        """Context manager for efficient batch change tracking."""
        changes = []
        
        class BatchTracker:
            def __init__(self, tracker, source):
                self.tracker = tracker
                self.trigger_source = source
                self.changes = changes
            
            def track(self, source_table: str, source_id: str, operation: str, **kwargs):
                self.changes.append((source_table, source_id, operation, kwargs))
        
        batch_tracker = BatchTracker(self, trigger_source)
        
        try:
            yield batch_tracker
        finally:
            # Process all tracked changes in a single transaction
            if changes:
                self._process_batch_changes(changes, trigger_source)
    
    def _process_batch_changes(self, changes: List[Tuple], trigger_source: str):
        """Process a batch of changes efficiently."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            batch_data = []
            for source_table, source_id, operation, kwargs in changes:
                # Prepare data for batch insert
                content_before = kwargs.get('content_before')
                content_after = kwargs.get('content_after')
                changed_fields = kwargs.get('changed_fields')
                
                hash_before = self._calculate_content_hash(content_before) if content_before else None
                hash_after = self._calculate_content_hash(content_after) if content_after else None
                changed_fields_json = json.dumps(changed_fields) if changed_fields else None
                
                batch_data.append((
                    source_table, source_id, operation,
                    changed_fields_json, hash_before, hash_after,
                    trigger_source, 'pending'
                ))
            
            cursor.executemany('''
                INSERT INTO sync_changelog (
                    source_table, source_id, operation,
                    changed_fields, content_hash_before, content_hash_after,
                    trigger_source, process_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', batch_data)
            
            conn.commit()
            logger.info(f"📦 Batch tracked {len(changes)} changes from {trigger_source}")
    
    def _calculate_content_hash(self, content: str) -> str:
        """Calculate SHA-256 hash of content."""
        if content is None:
            return None
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def _serialize_notebook_content(self, notebook_data: Dict) -> str:
        """Create a serialized representation of notebook data for change detection."""
        # Extract key fields that matter for sync
        relevant_fields = ['name', 'visible_name', 'full_path', 'last_modified', 'total_pages']
        content_parts = []
        
        for field in relevant_fields:
            if field in notebook_data:
                content_parts.append(f"{field}:{notebook_data[field]}")
        
        return "|".join(content_parts)
    
    def _serialize_todo_content(self, todo_data: Dict) -> str:
        """Create a serialized representation of todo data for change detection."""
        # Extract key fields that matter for sync
        relevant_fields = ['text', 'actual_date', 'completed', 'confidence']
        content_parts = []
        
        for field in relevant_fields:
            if field in todo_data:
                content_parts.append(f"{field}:{todo_data[field]}")
        
        return "|".join(content_parts)