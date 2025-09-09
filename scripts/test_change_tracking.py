#!/usr/bin/env python3
"""
Test the change tracking system.

This script demonstrates and tests the change tracking infrastructure
with various operations and scenarios.
"""

import os
import sys
import logging
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.core.database import DatabaseManager
from src.core.change_tracker import ChangeTracker
from src.core.sync_hooks import SyncHookManager, track_notebook_operation, track_page_operation, track_todo_operation

def setup_logging():
    """Setup logging for the script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def test_basic_change_tracking(db: DatabaseManager):
    """Test basic change tracking functionality."""
    logger.info("🧪 Testing basic change tracking...")
    
    tracker = ChangeTracker(db)
    
    # Test notebook change tracking
    notebook_data = {
        'name': 'Test Notebook',
        'visible_name': 'Test Notebook',
        'total_pages': 5
    }
    
    changelog_id = tracker.track_notebook_change(
        notebook_uuid='test-notebook-123',
        operation='INSERT',
        notebook_data=notebook_data,
        trigger_source='test_script'
    )
    
    logger.info(f"   ✅ Tracked notebook change (changelog #{changelog_id})")
    
    # Test page change tracking
    page_data = {
        'text': 'This is test page content',
        'confidence': 0.95
    }
    
    changelog_id = tracker.track_page_change(
        notebook_uuid='test-notebook-123',
        page_number=1,
        operation='INSERT',
        page_data=page_data,
        trigger_source='test_script'
    )
    
    logger.info(f"   ✅ Tracked page change (changelog #{changelog_id})")
    
    # Test page update with before/after content
    changelog_id = tracker.track_page_change(
        notebook_uuid='test-notebook-123',
        page_number=1,
        operation='UPDATE',
        content_before='This is test page content',
        content_after='This is updated test page content with more text',
        trigger_source='test_script'
    )
    
    logger.info(f"   ✅ Tracked page update with content comparison (changelog #{changelog_id})")
    
    # Test todo change tracking
    todo_data = {
        'text': 'Test todo item',
        'actual_date': '2025-09-09',
        'completed': False,
        'confidence': 1.0
    }
    
    changelog_id = tracker.track_todo_change(
        todo_id=999999,
        operation='INSERT',
        todo_data=todo_data,
        trigger_source='test_script'
    )
    
    logger.info(f"   ✅ Tracked todo change (changelog #{changelog_id})")
    
    return tracker

def test_hook_manager(db: DatabaseManager):
    """Test the sync hook manager."""
    logger.info("🔗 Testing sync hook manager...")
    
    hook_manager = SyncHookManager(db)
    
    # Test notebook operations
    notebook_data = {
        'name': 'Hooked Notebook',
        'visible_name': 'Hooked Notebook',
        'full_path': 'Test/Hooked Notebook'
    }
    
    hook_manager.track_notebook_insertion(
        notebook_uuid='hooked-notebook-456',
        notebook_data=notebook_data,
        trigger_source='hook_test'
    )
    
    logger.info("   ✅ Tracked notebook insertion via hook")
    
    # Test page operations
    page_data = {
        'text': 'Hooked page content',
        'page_number': 1
    }
    
    hook_manager.track_page_insertion(
        notebook_uuid='hooked-notebook-456',
        page_number=1,
        page_data=page_data,
        trigger_source='hook_test'
    )
    
    logger.info("   ✅ Tracked page insertion via hook")
    
    # Test page update
    hook_manager.track_page_update(
        notebook_uuid='hooked-notebook-456',
        page_number=1,
        content_before='Hooked page content',
        content_after='Updated hooked page content',
        trigger_source='hook_test'
    )
    
    logger.info("   ✅ Tracked page update via hook")
    
    return hook_manager

def test_convenience_functions():
    """Test convenience functions."""
    logger.info("🛠️  Testing convenience functions...")
    
    # Test notebook operation tracking
    track_notebook_operation(
        operation='UPDATE',
        notebook_uuid='convenience-notebook-789',
        data={'name': 'Updated via convenience function'},
        trigger_source='convenience_test'
    )
    
    logger.info("   ✅ Tracked notebook operation via convenience function")
    
    # Test page operation tracking
    track_page_operation(
        operation='UPDATE',
        notebook_uuid='convenience-notebook-789',
        page_number=2,
        content_before='Original content',
        content_after='Updated content via convenience function',
        trigger_source='convenience_test'
    )
    
    logger.info("   ✅ Tracked page operation via convenience function")
    
    # Test todo operation tracking
    track_todo_operation(
        operation='INSERT',
        todo_id=888888,
        data={'text': 'Todo via convenience function'},
        trigger_source='convenience_test'
    )
    
    logger.info("   ✅ Tracked todo operation via convenience function")

def test_batch_tracking(tracker: ChangeTracker):
    """Test batch change tracking."""
    logger.info("📦 Testing batch change tracking...")
    
    with tracker.batch_tracking(trigger_source='batch_test') as batch:
        # Track multiple changes in a batch
        batch.track('notebooks', 'batch-notebook-1', 'INSERT', 
                   content_after='Batch notebook 1')
        batch.track('notebooks', 'batch-notebook-2', 'INSERT',
                   content_after='Batch notebook 2')
        batch.track('pages', 'batch-notebook-1|1', 'INSERT',
                   content_after='Batch page content 1')
        batch.track('pages', 'batch-notebook-1|2', 'INSERT',
                   content_after='Batch page content 2')
        batch.track('todos', '777777', 'INSERT',
                   content_after='text:Batch todo|completed:False')
    
    logger.info("   ✅ Completed batch tracking of 5 changes")

def show_pending_changes(tracker: ChangeTracker):
    """Display pending changes for review."""
    logger.info("📋 Showing pending changes...")
    
    pending = tracker.get_pending_changes(limit=10)
    
    if not pending:
        logger.info("   No pending changes found")
        return
    
    logger.info(f"   Found {len(pending)} pending changes:")
    
    for i, change in enumerate(pending, 1):
        logger.info(f"   {i}. {change['operation']} on {change['source_table']}:{change['source_id']}")
        logger.info(f"      Changed: {change['changed_at']}")
        logger.info(f"      Trigger: {change['trigger_source']}")
        if change['changed_fields']:
            logger.info(f"      Fields: {change['changed_fields']}")
        if change['sync_target']:
            logger.info(f"      Sync target: {change['sync_target']} (status: {change['sync_status']})")
        logger.info("")

def show_sync_health(tracker: ChangeTracker):
    """Display sync health metrics."""
    logger.info("📊 Sync health metrics:")
    
    metrics = tracker.get_sync_health_metrics()
    
    logger.info(f"   Total pending changes: {metrics['total_pending']}")
    
    if metrics['pending_changes']:
        logger.info("   Pending by table:")
        for table, count in metrics['pending_changes'].items():
            logger.info(f"     - {table}: {count}")
    
    if metrics['oldest_pending']:
        logger.info(f"   Oldest pending: {metrics['oldest_pending']}")
    
    logger.info(f"   Success rate (24h): {metrics['success_rate_24h']}%")
    
    if metrics['sync_state_summary']:
        logger.info("   Sync state summary:")
        for target, statuses in metrics['sync_state_summary'].items():
            logger.info(f"     {target}:")
            for status, count in statuses.items():
                logger.info(f"       - {status}: {count:,}")

def cleanup_test_data(db: DatabaseManager):
    """Clean up test data from the changelog."""
    logger.info("🧹 Cleaning up test data...")
    
    test_sources = ['test_script', 'hook_test', 'convenience_test', 'batch_test']
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        placeholders = ','.join(['?'] * len(test_sources))
        cursor.execute(f'''
            DELETE FROM sync_changelog 
            WHERE trigger_source IN ({placeholders})
        ''', test_sources)
        
        deleted = cursor.rowcount
        conn.commit()
        
        logger.info(f"   🗑️  Deleted {deleted} test changelog entries")

def main():
    setup_logging()
    global logger
    logger = logging.getLogger(__name__)
    
    logger.info("🚀 Testing change tracking system...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    try:
        # Run tests
        tracker = test_basic_change_tracking(db)
        hook_manager = test_hook_manager(db)
        test_convenience_functions()
        test_batch_tracking(tracker)
        
        # Show results
        show_pending_changes(tracker)
        show_sync_health(tracker)
        
        logger.info("")
        logger.info("🎉 Change tracking system tests completed successfully!")
        logger.info("")
        logger.info("🎯 Next Steps:")
        logger.info("   1. Integrate hooks into existing write operations")
        logger.info("   2. Build sync engine to process pending changes")
        logger.info("   3. Add monitoring dashboard for sync health")
        
        # Clean up test data
        cleanup_test_data(db)
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Error during change tracking tests: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())