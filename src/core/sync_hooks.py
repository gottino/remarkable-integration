#!/usr/bin/env python3
"""
Sync hooks for integrating change tracking into existing operations.

This module provides decorators and helper functions to automatically
track changes when data is written to the database.
"""

import functools
import logging
from typing import Dict, List, Optional, Any, Callable
from contextlib import contextmanager

from .database import DatabaseManager
from .change_tracker import ChangeTracker

logger = logging.getLogger(__name__)


class SyncHookManager:
    """Manages sync hooks for automatic change tracking."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.change_tracker = ChangeTracker(db_manager)
        self.enabled = True
    
    def enable_tracking(self):
        """Enable automatic change tracking."""
        self.enabled = True
        logger.info("🔄 Change tracking enabled")
    
    def disable_tracking(self):
        """Disable automatic change tracking (for bulk operations)."""
        self.enabled = False
        logger.info("⏸️  Change tracking disabled")
    
    @contextmanager
    def tracking_disabled(self):
        """Context manager to temporarily disable tracking."""
        was_enabled = self.enabled
        self.disable_tracking()
        try:
            yield
        finally:
            if was_enabled:
                self.enable_tracking()
    
    def track_notebook_insertion(self, notebook_uuid: str, notebook_data: Dict,
                               trigger_source: str = 'system') -> None:
        """Hook for when a notebook is inserted."""
        if not self.enabled:
            return
        
        # 🔒 CONTENT FILTERING: Only track notebooks that should sync content
        if not self._should_sync_notebook_content(notebook_data):
            logger.debug(f"🚫 Skipping notebook sync tracking for non-content type: {notebook_uuid}")
            return
        
        try:
            self.change_tracker.track_notebook_change(
                notebook_uuid=notebook_uuid,
                operation='INSERT',
                notebook_data=notebook_data,
                trigger_source=trigger_source
            )
            logger.debug(f"📝 Tracked notebook insertion: {notebook_uuid}")
        except Exception as e:
            logger.warning(f"Failed to track notebook insertion {notebook_uuid}: {e}")
    
    def track_notebook_update(self, notebook_uuid: str, updated_fields: Dict,
                            trigger_source: str = 'system') -> None:
        """Hook for when a notebook is updated."""
        if not self.enabled:
            return
        
        # 🔒 CONTENT FILTERING: Only track notebooks that should sync content
        if not self._should_sync_notebook_content(updated_fields):
            logger.debug(f"🚫 Skipping notebook sync tracking for non-content type: {notebook_uuid}")
            return
        
        try:
            self.change_tracker.track_notebook_change(
                notebook_uuid=notebook_uuid,
                operation='UPDATE',
                notebook_data=updated_fields,
                trigger_source=trigger_source
            )
            logger.debug(f"📝 Tracked notebook update: {notebook_uuid}")
        except Exception as e:
            logger.warning(f"Failed to track notebook update {notebook_uuid}: {e}")
    
    def track_page_insertion(self, notebook_uuid: str, page_number: int, 
                           page_data: Dict, trigger_source: str = 'system') -> None:
        """Hook for when a page is inserted."""
        if not self.enabled:
            return
        
        try:
            self.change_tracker.track_page_change(
                notebook_uuid=notebook_uuid,
                page_number=page_number,
                operation='INSERT',
                page_data=page_data,
                trigger_source=trigger_source
            )
            logger.debug(f"📝 Tracked page insertion: {notebook_uuid}|{page_number}")
        except Exception as e:
            logger.warning(f"Failed to track page insertion {notebook_uuid}|{page_number}: {e}")
    
    def track_page_update(self, notebook_uuid: str, page_number: int,
                        content_before: Optional[str], content_after: str,
                        updated_fields: Optional[Dict] = None,
                        trigger_source: str = 'system') -> None:
        """Hook for when a page is updated."""
        if not self.enabled:
            return
        
        # Only track if content actually changed
        if content_before == content_after:
            return
        
        try:
            self.change_tracker.track_page_change(
                notebook_uuid=notebook_uuid,
                page_number=page_number,
                operation='UPDATE',
                content_before=content_before,
                content_after=content_after,
                page_data=updated_fields,
                trigger_source=trigger_source
            )
            logger.debug(f"📝 Tracked page update: {notebook_uuid}|{page_number}")
        except Exception as e:
            logger.warning(f"Failed to track page update {notebook_uuid}|{page_number}: {e}")
    
    def track_todo_insertion(self, todo_id: int, todo_data: Dict,
                           trigger_source: str = 'system') -> None:
        """Hook for when a todo is inserted."""
        if not self.enabled:
            return
        
        try:
            self.change_tracker.track_todo_change(
                todo_id=todo_id,
                operation='INSERT',
                todo_data=todo_data,
                trigger_source=trigger_source
            )
            logger.debug(f"📝 Tracked todo insertion: {todo_id}")
        except Exception as e:
            logger.warning(f"Failed to track todo insertion {todo_id}: {e}")
    
    def track_todo_update(self, todo_id: int, updated_fields: Dict,
                        trigger_source: str = 'system') -> None:
        """Hook for when a todo is updated.""" 
        if not self.enabled:
            return
        
        try:
            self.change_tracker.track_todo_change(
                todo_id=todo_id,
                operation='UPDATE',
                todo_data=updated_fields,
                trigger_source=trigger_source
            )
            logger.debug(f"📝 Tracked todo update: {todo_id}")
        except Exception as e:
            logger.warning(f"Failed to track todo update {todo_id}: {e}")
    
    def get_pending_changes_summary(self) -> Dict[str, Any]:
        """Get a summary of pending changes for monitoring."""
        return self.change_tracker.get_sync_health_metrics()
    
    def _should_sync_notebook_content(self, notebook_data: Dict) -> bool:
        """
        Determine if a notebook should have its content synced to external targets.
        
        Only sync actual handwritten notebooks, not PDFs, EPUBs, or folders.
        """
        document_type = notebook_data.get('document_type', 'unknown').lower()
        
        # 📚 Only sync handwritten notebooks
        if document_type == 'notebook':
            return True
        
        # 🚫 Skip PDFs, EPUBs, folders, and other non-notebook types
        if document_type in ['pdf', 'epub', 'folder', 'unknown']:
            return False
        
        # 🤔 For unknown types, be conservative and skip
        logger.debug(f"Unknown document type '{document_type}' - skipping sync")
        return False


def with_change_tracking(hook_manager: SyncHookManager, 
                        track_type: str, 
                        trigger_source: str = 'system'):
    """
    Decorator to automatically track changes for database operations.
    
    Args:
        hook_manager: SyncHookManager instance
        track_type: Type of tracking ('notebook_insert', 'page_update', etc.)
        trigger_source: Source of the change
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Execute the original function
            result = func(*args, **kwargs)
            
            # Extract parameters for tracking based on function signature
            try:
                if track_type == 'notebook_insert':
                    # Assume first arg is notebook_uuid, second is data dict
                    hook_manager.track_notebook_insertion(
                        args[0], args[1], trigger_source
                    )
                elif track_type == 'page_insert':
                    # Assume args are notebook_uuid, page_number, page_data
                    hook_manager.track_page_insertion(
                        args[0], args[1], args[2], trigger_source
                    )
                elif track_type == 'todo_insert':
                    # Assume first arg is todo_id, second is data dict
                    hook_manager.track_todo_insertion(
                        args[0], args[1], trigger_source
                    )
                # Add more track types as needed
                
            except Exception as e:
                logger.warning(f"Failed to track change in {func.__name__}: {e}")
            
            return result
        
        return wrapper
    return decorator


# Global hook manager instance (initialized when needed)
_global_hook_manager = None


def get_hook_manager(db_manager: Optional[DatabaseManager] = None) -> SyncHookManager:
    """Get or create the global hook manager."""
    global _global_hook_manager
    
    if _global_hook_manager is None:
        if db_manager is None:
            from .database import DatabaseManager
            db_manager = DatabaseManager('./data/remarkable_pipeline.db')
        _global_hook_manager = SyncHookManager(db_manager)
    
    return _global_hook_manager


def track_notebook_operation(operation: str, notebook_uuid: str, 
                           data: Optional[Dict] = None,
                           trigger_source: str = 'system'):
    """Convenience function to track notebook operations."""
    hook_manager = get_hook_manager()
    
    if operation == 'INSERT':
        hook_manager.track_notebook_insertion(notebook_uuid, data or {}, trigger_source)
    elif operation == 'UPDATE':
        hook_manager.track_notebook_update(notebook_uuid, data or {}, trigger_source)


def track_page_operation(operation: str, notebook_uuid: str, page_number: int,
                        data: Optional[Dict] = None,
                        content_before: Optional[str] = None,
                        content_after: Optional[str] = None,
                        trigger_source: str = 'system'):
    """Convenience function to track page operations."""
    hook_manager = get_hook_manager()
    
    if operation == 'INSERT':
        hook_manager.track_page_insertion(notebook_uuid, page_number, data or {}, trigger_source)
    elif operation == 'UPDATE':
        hook_manager.track_page_update(
            notebook_uuid, page_number, content_before, content_after, data, trigger_source
        )


def track_todo_operation(operation: str, todo_id: int,
                        data: Optional[Dict] = None,
                        trigger_source: str = 'system'):
    """Convenience function to track todo operations."""
    hook_manager = get_hook_manager()
    
    if operation == 'INSERT':
        hook_manager.track_todo_insertion(todo_id, data or {}, trigger_source)
    elif operation == 'UPDATE':
        hook_manager.track_todo_update(todo_id, data or {}, trigger_source)