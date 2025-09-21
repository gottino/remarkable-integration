"""
Unified Change Detection for reMarkable Integration.

This module provides intelligent change detection that works across all content types
and sync targets, replacing target-specific change tracking with a unified approach.

Key Features:
- Content-hash based change detection
- Last-opened timestamp analysis for notebooks
- Unified change tracking across all content types
- Smart sync decision making based on access patterns
- Integration with unified sync_records table
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .database import DatabaseManager
from .sync_engine import ContentFingerprint, SyncItemType

logger = logging.getLogger(__name__)


class UnifiedChangeDetector:
    """
    Unified change detection system that works across all content types and sync targets.
    
    This replaces target-specific change detection (like NotionSyncTracker) with a
    single system that can determine what needs syncing for any target.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(f"{__name__}.UnifiedChangeDetector")
    
    async def detect_notebook_changes(self, notebook_uuid: str, target_name: str) -> Dict[str, Any]:
        """
        Detect changes for a notebook since last sync to specific target.
        
        Args:
            notebook_uuid: UUID of the notebook to check
            target_name: Name of the sync target to check against
            
        Returns:
            Dictionary with change analysis results
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get current notebook state
                cursor.execute('''
                    SELECT 
                        nte.notebook_uuid, nte.notebook_name, nte.page_uuid, nte.confidence, 
                        nte.page_number, nte.text, nm.full_path, nm.last_modified, nm.last_opened,
                        nte.updated_at
                    FROM notebook_text_extractions nte
                    LEFT JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
                    WHERE nte.notebook_uuid = ?
                    AND nte.text IS NOT NULL AND length(nte.text) > 0
                    ORDER BY nte.page_number
                ''', (notebook_uuid,))
                
                current_pages = cursor.fetchall()
                if not current_pages:
                    return {
                        'notebook_exists': False,
                        'needs_sync': False,
                        'reason': 'notebook_not_found'
                    }
                
                # Get last sync record for this target
                cursor.execute('''
                    SELECT content_hash, metadata, synced_at, external_id
                    FROM sync_records 
                    WHERE item_id = ? AND target_name = ? AND status = 'success' AND item_type = 'notebook'
                    ORDER BY synced_at DESC
                    LIMIT 1
                ''', (notebook_uuid, target_name))
                
                last_sync = cursor.fetchone()
                
                # Calculate current state
                current_content_hash = self._calculate_content_hash(current_pages)
                current_metadata_hash = self._calculate_metadata_hash(current_pages[0])
                current_total_pages = len(current_pages)
                
                # Analyze changes
                changes = {
                    'notebook_exists': True,
                    'notebook_uuid': notebook_uuid,
                    'notebook_name': current_pages[0][1],
                    'current_total_pages': current_total_pages,
                    'current_content_hash': current_content_hash,
                    'current_metadata_hash': current_metadata_hash,
                    'target_name': target_name
                }
                
                if not last_sync:
                    # Never synced to this target
                    changes.update({
                        'is_new_to_target': True,
                        'needs_sync': True,
                        'reason': 'never_synced_to_target',
                        'content_changed': True,
                        'metadata_changed': True,
                        'new_pages': list(range(1, current_total_pages + 1)),
                        'changed_pages': []
                    })
                    return changes
                
                last_content_hash, last_metadata_json, last_synced, external_id = last_sync
                last_metadata = json.loads(last_metadata_json) if last_metadata_json else {}
                
                # Check if content or metadata changed
                content_changed = current_content_hash != last_content_hash
                metadata_changed = current_metadata_hash != last_metadata.get('metadata_hash', '')
                
                # Check if notebook was accessed since last sync
                was_accessed_since_sync = await self._was_notebook_accessed_since_sync(
                    current_pages[0], last_synced
                )
                
                # Determine if sync is needed
                needs_sync = content_changed or metadata_changed or was_accessed_since_sync
                
                # Find specific page changes if content changed
                new_pages = []
                changed_pages = []
                
                if content_changed:
                    page_changes = await self._analyze_page_changes(notebook_uuid, target_name, current_pages)
                    new_pages = page_changes['new_pages']
                    changed_pages = page_changes['changed_pages']
                
                changes.update({
                    'is_new_to_target': False,
                    'needs_sync': needs_sync,
                    'reason': self._determine_sync_reason(content_changed, metadata_changed, was_accessed_since_sync),
                    'content_changed': content_changed,
                    'metadata_changed': metadata_changed,
                    'was_accessed_since_sync': was_accessed_since_sync,
                    'new_pages': new_pages,
                    'changed_pages': changed_pages,
                    'last_synced': last_synced,
                    'external_id': external_id
                })
                
                return changes
                
        except Exception as e:
            self.logger.error(f"Error detecting notebook changes: {e}")
            return {
                'notebook_exists': False,
                'needs_sync': False,
                'error': str(e)
            }
    
    async def detect_todo_changes(self, todo_id: int, target_name: str) -> Dict[str, Any]:
        """
        Detect changes for a todo since last sync to specific target.
        
        Args:
            todo_id: ID of the todo to check
            target_name: Name of the sync target to check against
            
        Returns:
            Dictionary with change analysis results
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get current todo state
                cursor.execute('''
                    SELECT id, notebook_uuid, text, page_number, completed, 
                           confidence, created_at, updated_at
                    FROM todos 
                    WHERE id = ?
                ''', (todo_id,))
                
                todo_row = cursor.fetchone()
                if not todo_row:
                    return {
                        'todo_exists': False,
                        'needs_sync': False,
                        'reason': 'todo_not_found'
                    }
                
                # Generate content hash for current state
                todo_data = {
                    'text': todo_row[2],
                    'notebook_uuid': todo_row[1],
                    'page_number': todo_row[3],
                    'type': 'todo'
                }
                current_content_hash = ContentFingerprint.for_todo(todo_data)
                
                # Get last sync record
                cursor.execute('''
                    SELECT content_hash, synced_at, external_id
                    FROM sync_records 
                    WHERE item_id = ? AND target_name = ? AND status = 'success' AND item_type = 'todo'
                    ORDER BY synced_at DESC
                    LIMIT 1
                ''', (str(todo_id), target_name))
                
                last_sync = cursor.fetchone()
                
                changes = {
                    'todo_exists': True,
                    'todo_id': todo_id,
                    'text': todo_row[2],
                    'completed': bool(todo_row[4]),
                    'current_content_hash': current_content_hash,
                    'updated_at': todo_row[7],
                    'target_name': target_name
                }
                
                if not last_sync:
                    # Never synced to this target
                    changes.update({
                        'is_new_to_target': True,
                        'needs_sync': not bool(todo_row[4]),  # Don't sync completed todos
                        'reason': 'never_synced_to_target' if not bool(todo_row[4]) else 'completed_todo',
                        'content_changed': True
                    })
                    return changes
                
                last_content_hash, last_synced, external_id = last_sync
                
                # Check if content changed
                content_changed = current_content_hash != last_content_hash
                
                # Don't sync completed todos
                if bool(todo_row[4]):
                    changes.update({
                        'is_new_to_target': False,
                        'needs_sync': False,
                        'reason': 'completed_todo',
                        'content_changed': content_changed,
                        'last_synced': last_synced,
                        'external_id': external_id
                    })
                    return changes
                
                changes.update({
                    'is_new_to_target': False,
                    'needs_sync': content_changed,
                    'reason': 'content_changed' if content_changed else 'no_changes',
                    'content_changed': content_changed,
                    'last_synced': last_synced,
                    'external_id': external_id
                })
                
                return changes
                
        except Exception as e:
            self.logger.error(f"Error detecting todo changes: {e}")
            return {
                'todo_exists': False,
                'needs_sync': False,
                'error': str(e)
            }
    
    async def detect_highlight_changes(self, highlight_id: int, target_name: str) -> Dict[str, Any]:
        """
        Detect changes for a highlight since last sync to specific target.
        
        Args:
            highlight_id: ID of the highlight to check
            target_name: Name of the sync target to check against
            
        Returns:
            Dictionary with change analysis results
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get current highlight state
                cursor.execute('''
                    SELECT id, source_file, title, original_text, corrected_text, 
                           page_number, confidence, match_score, created_at, updated_at
                    FROM enhanced_highlights 
                    WHERE id = ?
                ''', (highlight_id,))
                
                highlight_row = cursor.fetchone()
                if not highlight_row:
                    return {
                        'highlight_exists': False,
                        'needs_sync': False,
                        'reason': 'highlight_not_found'
                    }
                
                # Generate content hash for current state
                highlight_data = {
                    'text': highlight_row[3],  # original_text
                    'corrected_text': highlight_row[4],  # corrected_text
                    'source_file': highlight_row[1],
                    'page_number': highlight_row[5],
                    'type': 'highlight'
                }
                current_content_hash = ContentFingerprint.for_highlight(highlight_data)
                
                # Get last sync record
                cursor.execute('''
                    SELECT content_hash, synced_at, external_id
                    FROM sync_records 
                    WHERE item_id = ? AND target_name = ? AND status = 'success' AND item_type = 'highlight'
                    ORDER BY synced_at DESC
                    LIMIT 1
                ''', (str(highlight_id), target_name))
                
                last_sync = cursor.fetchone()
                
                changes = {
                    'highlight_exists': True,
                    'highlight_id': highlight_id,
                    'title': highlight_row[2],
                    'text': highlight_row[4],  # Use corrected_text as primary text
                    'source_file': highlight_row[1],
                    'current_content_hash': current_content_hash,
                    'updated_at': highlight_row[9],
                    'target_name': target_name
                }
                
                if not last_sync:
                    # Never synced to this target
                    changes.update({
                        'is_new_to_target': True,
                        'needs_sync': True,
                        'reason': 'never_synced_to_target',
                        'content_changed': True
                    })
                    return changes
                
                last_content_hash, last_synced, external_id = last_sync
                
                # Check if content changed
                content_changed = current_content_hash != last_content_hash
                
                changes.update({
                    'is_new_to_target': False,
                    'needs_sync': content_changed,
                    'reason': 'content_changed' if content_changed else 'no_changes',
                    'content_changed': content_changed,
                    'last_synced': last_synced,
                    'external_id': external_id
                })
                
                return changes
                
        except Exception as e:
            self.logger.error(f"Error detecting highlight changes: {e}")
            return {
                'highlight_exists': False,
                'needs_sync': False,
                'error': str(e)
            }
    
    async def get_all_items_needing_sync(self, target_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all items across all content types that need syncing to a target.
        
        Args:
            target_name: Name of the sync target
            limit: Maximum number of items to return
            
        Returns:
            List of items that need syncing, sorted by priority
        """
        try:
            items_needing_sync = []
            
            # Check notebooks
            notebooks = await self._get_notebooks_needing_sync(target_name, limit // 3)
            items_needing_sync.extend(notebooks)
            
            # Check todos
            todos = await self._get_todos_needing_sync(target_name, limit // 3)
            items_needing_sync.extend(todos)
            
            # Check highlights
            highlights = await self._get_highlights_needing_sync(target_name, limit // 3)
            items_needing_sync.extend(highlights)
            
            # Sort by priority (updated_at desc, but prioritize notebooks)
            def sort_key(item):
                priority_order = {'notebook': 0, 'todo': 1, 'highlight': 2}
                return (priority_order.get(item['item_type'], 9), item.get('updated_at', ''))
            
            items_needing_sync.sort(key=sort_key, reverse=True)
            
            return items_needing_sync[:limit]
            
        except Exception as e:
            self.logger.error(f"Error getting items needing sync: {e}")
            return []
    
    async def _was_notebook_accessed_since_sync(self, page_data: Tuple, last_synced: Optional[str]) -> bool:
        """
        Check if notebook was accessed since last sync based on last_opened timestamp.
        
        Args:
            page_data: First page data tuple containing metadata
            last_synced: ISO timestamp of last sync
            
        Returns:
            True if notebook was accessed since last sync
        """
        try:
            if not last_synced:
                return True
            
            # Parse last_opened timestamp (index 8 in page_data)
            last_opened_str = page_data[8]  # last_opened timestamp
            if not last_opened_str:
                return False
            
            # reMarkable timestamps are in milliseconds, UTC
            last_opened_timestamp = datetime.fromtimestamp(int(last_opened_str) / 1000, tz=timezone.utc)
            # Convert to local time for comparison
            last_opened_local = last_opened_timestamp.replace(tzinfo=None)
            
            # Parse last_synced timestamp
            if isinstance(last_synced, str):
                last_synced_timestamp = datetime.fromisoformat(last_synced.replace('Z', '+00:00'))
                if last_synced_timestamp.tzinfo:
                    last_synced_timestamp = last_synced_timestamp.replace(tzinfo=None)
            else:
                last_synced_timestamp = last_synced
            
            return last_opened_local > last_synced_timestamp
            
        except (ValueError, TypeError, AttributeError) as e:
            self.logger.debug(f"Error parsing timestamps for access check: {e}")
            return False
    
    async def _analyze_page_changes(self, notebook_uuid: str, target_name: str, current_pages: List[Tuple]) -> Dict[str, List[int]]:
        """
        Analyze which specific pages are new or changed.
        
        Args:
            notebook_uuid: UUID of the notebook
            target_name: Name of the sync target
            current_pages: List of current page data tuples
            
        Returns:
            Dictionary with 'new_pages' and 'changed_pages' lists
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get last synced state for pages
                cursor.execute('''
                    SELECT JSON_EXTRACT(metadata, '$.page_sync_state') as page_state
                    FROM sync_records 
                    WHERE item_id = ? AND target_name = ? AND status = 'success' AND item_type = 'notebook'
                    ORDER BY synced_at DESC
                    LIMIT 1
                ''', (notebook_uuid, target_name))
                
                result = cursor.fetchone()
                last_page_state = json.loads(result[0]) if result and result[0] else {}
                
                new_pages = []
                changed_pages = []
                
                for page_data in current_pages:
                    page_number = page_data[4]  # page_number at index 4
                    page_uuid = page_data[2]    # page_uuid at index 2
                    current_text = page_data[5]  # text at index 5
                    
                    # Generate content hash for this page
                    page_content_hash = hashlib.md5(f"{current_text}:{page_data[3]}".encode('utf-8')).hexdigest()
                    
                    page_key = str(page_number)
                    last_page_hash = last_page_state.get(page_key, {}).get('content_hash', '')
                    
                    if not last_page_hash:
                        # No previous record - treat as new
                        new_pages.append(page_number)
                    elif page_content_hash != last_page_hash:
                        # Content changed
                        changed_pages.append(page_number)
                
                return {
                    'new_pages': new_pages,
                    'changed_pages': changed_pages
                }
                
        except Exception as e:
            self.logger.error(f"Error analyzing page changes: {e}")
            return {'new_pages': [], 'changed_pages': []}
    
    async def _get_notebooks_needing_sync(self, target_name: str, limit: int) -> List[Dict[str, Any]]:
        """Get notebooks that need syncing to target.

        DEPRECATED: Use unified_sync.py version instead. This module is not actively used.
        """
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Find notebooks not successfully synced to this target
                cursor.execute('''
                    SELECT nm.notebook_uuid, nm.visible_name, 
                           MAX(nte.updated_at) as last_updated
                    FROM notebook_metadata nm
                    LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = nm.notebook_uuid 
                        AND sr.target_name = ? 
                        AND sr.status = 'success'
                        AND sr.item_type = 'notebook'
                    )
                    WHERE sr.id IS NULL
                    AND nm.deleted = FALSE
                    AND nte.text IS NOT NULL
                    GROUP BY nm.notebook_uuid, nm.visible_name
                    ORDER BY last_updated DESC
                    LIMIT ?
                ''', (target_name, limit))
                
                items = []
                for row in cursor.fetchall():
                    notebook_uuid, visible_name, last_updated = row
                    items.append({
                        'item_type': 'notebook',
                        'item_id': notebook_uuid,
                        'title': visible_name or 'Untitled Notebook',
                        'updated_at': last_updated or datetime.now().isoformat()
                    })
                
                return items
                
        except Exception as e:
            self.logger.error(f"Error getting notebooks needing sync: {e}")
            return []
    
    async def _get_todos_needing_sync(self, target_name: str, limit: int) -> List[Dict[str, Any]]:
        """Get todos that need syncing to target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT t.id, t.text, t.updated_at
                    FROM todos t
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = CAST(t.id AS TEXT)
                        AND sr.target_name = ? 
                        AND sr.status = 'success'
                        AND sr.item_type = 'todo'
                    )
                    WHERE sr.id IS NULL
                    AND t.completed = FALSE
                    ORDER BY t.updated_at DESC
                    LIMIT ?
                ''', (target_name, limit))
                
                items = []
                for row in cursor.fetchall():
                    todo_id, text, updated_at = row
                    items.append({
                        'item_type': 'todo',
                        'item_id': str(todo_id),
                        'title': text[:50] + '...' if len(text) > 50 else text,
                        'updated_at': updated_at or datetime.now().isoformat()
                    })
                
                return items
                
        except Exception as e:
            self.logger.error(f"Error getting todos needing sync: {e}")
            return []
    
    async def _get_highlights_needing_sync(self, target_name: str, limit: int) -> List[Dict[str, Any]]:
        """Get highlights that need syncing to target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    SELECT eh.id, eh.title, eh.corrected_text, eh.updated_at
                    FROM enhanced_highlights eh
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = CAST(eh.id AS TEXT)
                        AND sr.target_name = ? 
                        AND sr.status = 'success'
                        AND sr.item_type = 'highlight'
                    )
                    WHERE sr.id IS NULL
                    ORDER BY eh.updated_at DESC
                    LIMIT ?
                ''', (target_name, limit))
                
                items = []
                for row in cursor.fetchall():
                    highlight_id, title, text, updated_at = row
                    items.append({
                        'item_type': 'highlight',
                        'item_id': str(highlight_id),
                        'title': title or (text[:50] + '...' if len(text) > 50 else text),
                        'updated_at': updated_at or datetime.now().isoformat()
                    })
                
                return items
                
        except Exception as e:
            self.logger.error(f"Error getting highlights needing sync: {e}")
            return []
    
    def _determine_sync_reason(self, content_changed: bool, metadata_changed: bool, was_accessed: bool) -> str:
        """Determine the reason why sync is needed."""
        reasons = []
        if content_changed:
            reasons.append('content_changed')
        if metadata_changed:
            reasons.append('metadata_changed')
        if was_accessed:
            reasons.append('accessed_since_sync')
        
        if not reasons:
            return 'no_changes'
        
        return ', '.join(reasons)
    
    def _calculate_content_hash(self, pages_data: List[Tuple]) -> str:
        """Calculate hash of all page content for a notebook."""
        # Sort by page number to ensure consistent hashing
        sorted_pages = sorted(pages_data, key=lambda x: x[4])  # page_number at index 4
        
        content_parts = []
        for page_data in sorted_pages:
            page_number, text, confidence = page_data[4], page_data[5], page_data[3]
            content_parts.append(f"page_{page_number}:{text}:{confidence}")
        
        combined_content = '|'.join(content_parts)
        return hashlib.md5(combined_content.encode('utf-8')).hexdigest()
    
    def _calculate_metadata_hash(self, first_page_data: Tuple) -> str:
        """Calculate hash of notebook metadata."""
        # Metadata from first page (all pages have same metadata)
        # Indices: 6=full_path, 7=last_modified, 8=last_opened
        full_path = first_page_data[6] or ''
        last_modified = first_page_data[7] or ''
        last_opened = first_page_data[8] or ''
        
        metadata_content = f"path:{full_path}|modified:{last_modified}|opened:{last_opened}"
        return hashlib.md5(metadata_content.encode('utf-8')).hexdigest()


if __name__ == "__main__":
    # Example usage
    import asyncio
    from .database import DatabaseManager
    
    async def test_change_detection():
        # Initialize components
        db_manager = DatabaseManager("test_change_detection.db")
        detector = UnifiedChangeDetector(db_manager)
        
        # Get items needing sync
        items = await detector.get_all_items_needing_sync("notion", limit=10)
        print(f"Items needing sync: {len(items)}")
        
        for item in items:
            print(f"  {item['item_type']}: {item['title']}")
    
    # Run test
    asyncio.run(test_change_detection())