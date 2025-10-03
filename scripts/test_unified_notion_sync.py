#!/usr/bin/env python3
"""
Test script for the unified sync system with Notion integration.

This verifies that our new unified sync architecture works properly
with the existing Notion integration before implementing Readwise.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import DatabaseManager
from src.core.unified_sync import UnifiedSyncManager
from src.core.change_detection import UnifiedChangeDetector
from src.core.sync_targets import NotionSyncTarget, create_sync_target
from src.core.sync_engine import SyncItem, SyncItemType, ContentFingerprint
from datetime import datetime

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_unified_notion_sync():
    """Test the unified sync system with Notion integration."""
    
    print("🚀 Testing Unified Sync System with Notion")
    print("=" * 50)
    
    # Initialize components
    try:
        db_manager = DatabaseManager('remarkable_pipeline.db')
        sync_manager = UnifiedSyncManager(db_manager)
        change_detector = UnifiedChangeDetector(db_manager)
        
        print("✅ Initialized unified sync components")
    except Exception as e:
        print(f"❌ Failed to initialize components: {e}")
        return False
    
    # Test 1: Check sync stats
    print("\n📊 Testing Sync Stats...")
    try:
        stats = await sync_manager.get_sync_stats()
        print(f"  Total sync records: {stats['total_records']}")
        print(f"  Recent activity (24h): {stats['recent_activity_24h']}")
        print(f"  Status breakdown: {stats['status_counts']}")
        print("✅ Sync stats working")
    except Exception as e:
        print(f"❌ Sync stats failed: {e}")
        return False
    
    # Test 2: Check change detection
    print("\n🔍 Testing Change Detection...")
    try:
        items_needing_sync = await change_detector.get_all_items_needing_sync('notion', limit=10)
        print(f"  Found {len(items_needing_sync)} items needing sync to Notion")
        
        for i, item in enumerate(items_needing_sync[:3]):  # Show first 3
            print(f"  {i+1}. {item['item_type']}: {item['title'][:50]}...")
        
        print("✅ Change detection working")
    except Exception as e:
        print(f"❌ Change detection failed: {e}")
        return False
    
    # Test 3: Test notebook change analysis
    print("\n📖 Testing Notebook Change Analysis...")
    try:
        # Get a notebook to test with
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT notebook_uuid, notebook_name 
                FROM notebook_text_extractions 
                LIMIT 1
            ''')
            notebook_row = cursor.fetchone()
        
        if notebook_row:
            notebook_uuid, notebook_name = notebook_row
            print(f"  Testing with notebook: {notebook_name}")
            
            # Analyze changes for this notebook
            changes = await change_detector.detect_notebook_changes(notebook_uuid, 'notion')
            
            print(f"  Notebook exists: {changes.get('notebook_exists', False)}")
            print(f"  Needs sync: {changes.get('needs_sync', False)}")
            print(f"  Total pages: {changes.get('current_total_pages', 0)}")
            print(f"  Is new to target: {changes.get('is_new_to_target', False)}")
            print(f"  Reason: {changes.get('reason', 'unknown')}")
            
            if changes.get('new_pages'):
                print(f"  New pages: {changes['new_pages'][:5]}...")
            if changes.get('changed_pages'):
                print(f"  Changed pages: {changes['changed_pages'][:5]}...")
                
            print("✅ Notebook change analysis working")
        else:
            print("  ⚠️  No notebooks found in database - skipping detailed analysis")
            print("✅ Change analysis component functional")
            
    except Exception as e:
        print(f"❌ Notebook change analysis failed: {e}")
        return False
    
    # Test 4: Test sync record creation and retrieval
    print("\n📝 Testing Sync Record Management...")
    try:
        # Create a test sync record
        test_content_hash = "test_unified_sync_123"
        test_item_id = "test_notebook_456"
        
        # Check if record already exists
        existing_record = await sync_manager.get_sync_record(test_content_hash, 'notion')
        
        if not existing_record:
            print("  Creating test sync record...")
            from src.core.sync_engine import SyncResult, SyncStatus
            
            test_result = SyncResult(
                status=SyncStatus.SUCCESS,
                target_id='notion_page_test_123',
                metadata={'test': True, 'created_by': 'unified_sync_test'}
            )
            
            await sync_manager.record_sync_result(
                content_hash=test_content_hash,
                target_name='notion',
                item_id=test_item_id,
                item_type=SyncItemType.NOTEBOOK,
                result=test_result,
                metadata={'source_table': 'test', 'test_run': True}
            )
            print("  ✅ Created test sync record")
        else:
            print("  ✅ Found existing test sync record")
        
        # Retrieve the record
        record = await sync_manager.get_sync_record(test_content_hash, 'notion')
        if record:
            print(f"  Record ID: {record['id']}")
            print(f"  External ID: {record['external_id']}")
            print(f"  Status: {record['status']}")
            print(f"  Item ID: {record['item_id']}")
            print("✅ Sync record management working")
        else:
            print("❌ Failed to retrieve sync record")
            return False
            
    except Exception as e:
        print(f"❌ Sync record management failed: {e}")
        return False
    
    # Test 5: Test with Mock Sync Target (since we don't want to actually sync to Notion in a test)
    print("\n🎯 Testing Mock Sync Target...")
    try:
        # Create a mock target for safe testing
        mock_target = create_sync_target("mock", target_name="test_notion", fail_rate=0.0)
        sync_manager.register_target(mock_target)
        
        # Create a test sync item
        test_notebook_data = {
            'title': 'Test Unified Sync Notebook',
            'text_content': 'This is a test notebook for unified sync',
            'page_count': 3,
            'notebook_uuid': 'test-unified-123',
            'pages': [
                {'page_number': 1, 'text': 'Page 1 content', 'confidence': 0.9},
                {'page_number': 2, 'text': 'Page 2 content', 'confidence': 0.8},
                {'page_number': 3, 'text': 'Page 3 content', 'confidence': 0.7}
            ]
        }
        
        content_hash = ContentFingerprint.for_notebook(test_notebook_data)
        
        test_sync_item = SyncItem(
            item_type=SyncItemType.NOTEBOOK,
            item_id='test-unified-123',
            content_hash=content_hash,
            data=test_notebook_data,
            source_table='notebook_text_extractions',
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Test sync to mock target
        result = await sync_manager.sync_item_to_target(test_sync_item, "test_notion")
        
        print(f"  Sync result: {result.status}")
        print(f"  Target ID: {result.target_id}")
        print(f"  Metadata: {result.metadata}")
        
        if result.success:
            print("✅ Mock sync target working")
        else:
            print(f"❌ Mock sync failed: {result.error_message}")
            return False
            
    except Exception as e:
        print(f"❌ Mock sync target failed: {e}")
        return False
    
    # Test 6: Final stats check
    print("\n📈 Final Stats Check...")
    try:
        final_stats = await sync_manager.get_sync_stats()
        print(f"  Total sync records: {final_stats['total_records']}")
        print(f"  Status breakdown: {final_stats['status_counts']}")
        print("✅ Final stats check passed")
    except Exception as e:
        print(f"❌ Final stats check failed: {e}")
        return False
    
    print("\n🎉 All Tests Passed!")
    print("=" * 50)
    print("The unified sync foundation is working correctly and ready for:")
    print("  • Notion integration (existing)")
    print("  • Readwise integration (next step)")
    print("  • Any other sync targets")
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_unified_notion_sync())
    sys.exit(0 if success else 1)