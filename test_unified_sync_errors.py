#!/usr/bin/env python3
"""
Test script to verify unified sync error reporting improvements.
"""

import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path
import sys
import os

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.database import DatabaseManager
from src.core.unified_sync import UnifiedSyncManager
from src.core.sync_engine import SyncItem, SyncItemType, SyncStatus, SyncResult
from src.integrations.notion_unified_sync import NotionSyncTarget

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class MockNotionSyncTarget(NotionSyncTarget):
    """Mock Notion sync target for testing error scenarios."""

    def __init__(self):
        # Initialize with dummy credentials
        self.target_name = "test_notion"
        self.logger = logging.getLogger(f"{__name__}.test_notion")
        self._content_hash_cache = {}

    async def sync_item(self, item: SyncItem) -> SyncResult:
        """Mock sync that demonstrates different scenarios."""
        if item.item_type == SyncItemType.NOTEBOOK:
            notebook_data = item.data
            pages = notebook_data.get('pages', [])

            # Simulate different test scenarios based on notebook name
            notebook_name = notebook_data.get('title', 'Unknown')

            if notebook_name == "Empty Notebook":
                # Test scenario: No pages to sync
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'No pages to sync'}
                )
            elif notebook_name == "Already Synced":
                # Test scenario: Already synced
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'already_synced'}
                )
            elif notebook_name == "Notion Error":
                # Test scenario: Notion API error
                raise Exception("Notion API returned 500: Internal server error")
            elif notebook_name == "Success":
                # Test scenario: Successful sync
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id="mock_notion_page_123",
                    metadata={'action': 'created', 'pages_synced': len(pages)}
                )
            else:
                # Default error case
                return SyncResult(
                    status=SyncStatus.FAILED,
                    error_message="Unknown notebook scenario"
                )
        else:
            return SyncResult(
                status=SyncStatus.SKIPPED,
                metadata={'reason': f'Unsupported item type: {item.item_type}'}
            )

async def test_error_scenarios():
    """Test different unified sync error scenarios."""

    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_db:
        db_path = tmp_db.name

    try:
        # Initialize components
        db_manager = DatabaseManager(db_path)
        sync_manager = UnifiedSyncManager(db_manager)

        # Register mock target
        mock_target = MockNotionSyncTarget()
        sync_manager.register_target(mock_target)

        # Test scenarios
        test_scenarios = [
            {
                'name': 'Empty Notebook',
                'pages': [],
                'expected_status': SyncStatus.SKIPPED,
                'expected_reason': 'No pages to sync'
            },
            {
                'name': 'Already Synced',
                'pages': [{'page_number': 1, 'text': 'Some content', 'confidence': 0.9}],
                'expected_status': SyncStatus.SKIPPED,
                'expected_reason': 'already_synced'
            },
            {
                'name': 'Notion Error',
                'pages': [{'page_number': 1, 'text': 'Some content', 'confidence': 0.9}],
                'expected_status': SyncStatus.FAILED,
                'expected_error_contains': 'Notion API returned 500'
            },
            {
                'name': 'Success',
                'pages': [{'page_number': 1, 'text': 'Some content', 'confidence': 0.9}],
                'expected_status': SyncStatus.SUCCESS,
                'expected_target_id': 'mock_notion_page_123'
            }
        ]

        print("\n🧪 Testing Unified Sync Error Reporting\n")

        for scenario in test_scenarios:
            print(f"📝 Testing: {scenario['name']}")

            # Create sync item
            sync_item = SyncItem(
                item_type=SyncItemType.NOTEBOOK,
                item_id=f"test_notebook_{scenario['name'].replace(' ', '_').lower()}",
                content_hash="test_hash_123",
                data={
                    'title': scenario['name'],
                    'pages': scenario['pages'],
                    'notebook_uuid': f"uuid_{scenario['name'].replace(' ', '_').lower()}"
                },
                source_table="test",
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

            # Test sync
            result = await sync_manager.sync_item_to_target(sync_item, "test_notion")

            # Verify results
            print(f"   Status: {result.status.value}")
            if result.error_message:
                print(f"   Error: {result.error_message}")
            if result.metadata:
                print(f"   Metadata: {result.metadata}")

            # Assertions
            assert result.status == scenario['expected_status'], f"Expected {scenario['expected_status']}, got {result.status}"

            if 'expected_reason' in scenario:
                assert result.metadata and result.metadata.get('reason') == scenario['expected_reason'], \
                    f"Expected reason '{scenario['expected_reason']}', got {result.metadata.get('reason') if result.metadata else None}"

            if 'expected_error_contains' in scenario:
                assert result.error_message and scenario['expected_error_contains'] in result.error_message, \
                    f"Expected error containing '{scenario['expected_error_contains']}', got '{result.error_message}'"

            if 'expected_target_id' in scenario:
                assert result.target_id == scenario['expected_target_id'], \
                    f"Expected target_id '{scenario['expected_target_id']}', got '{result.target_id}'"

            print(f"   ✅ Test passed\n")

        print("🎉 All unified sync error reporting tests passed!")

    finally:
        # Clean up
        Path(db_path).unlink(missing_ok=True)

if __name__ == "__main__":
    asyncio.run(test_error_scenarios())