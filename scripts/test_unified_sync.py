#!/usr/bin/env python3
"""
Test the unified sync system with the "Test for integration" notebook.
"""

import asyncio
import logging
import sys
import os
from datetime import datetime

# Add the src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.database import DatabaseManager
from src.core.unified_sync import UnifiedSyncManager
from src.integrations.notion_unified_sync import NotionSyncTarget
from src.utils.config import Config
from src.utils.api_keys import get_notion_api_key

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TARGET_NOTEBOOK_UUID = "98afc255-97ee-4416-96db-ac9a16a33109"  # Test for integration
TARGET_NOTEBOOK_NAME = "Test for integration"

async def test_unified_sync():
    """Test unified sync for the Test for integration notebook."""

    logger.info(f"🧪 Testing unified sync for: {TARGET_NOTEBOOK_NAME}")

    # Initialize components
    db_path = './data/remarkable_pipeline.db'
    db_manager = DatabaseManager(db_path)
    config = Config()

    # Initialize unified sync manager
    sync_manager = UnifiedSyncManager(db_manager)

    # Setup Notion target
    notion_api_key = get_notion_api_key()
    notion_database_id = config.get('integrations.notion.database_id')
    tasks_database_id = config.get('integrations.notion.tasks_database_id')

    if not notion_api_key or not notion_database_id:
        logger.error("❌ Missing Notion API key or database ID")
        return

    # Create and register Notion target
    notion_target = NotionSyncTarget(
        notion_token=notion_api_key,
        database_id=notion_database_id,
        tasks_database_id=tasks_database_id,
        verify_ssl=False
    )
    sync_manager.register_target(notion_target)

    logger.info(f"🎯 Testing sync for notebook: {TARGET_NOTEBOOK_NAME}")
    logger.info(f"   UUID: {TARGET_NOTEBOOK_UUID}")

    try:
        # Test 1: Check if notebook needs sync
        logger.info("\n📋 TEST 1: Checking if notebook needs sync...")
        notebooks_to_sync = await sync_manager._get_notebooks_needing_sync("notion", limit=100)

        target_notebook = None
        for notebook in notebooks_to_sync:
            if notebook['item_id'] == TARGET_NOTEBOOK_UUID:
                target_notebook = notebook
                break

        if target_notebook:
            logger.info(f"✅ Notebook found in sync queue")
            logger.info(f"   Content hash: {target_notebook['content_hash']}")
            logger.info(f"   Pages: {len(target_notebook['data'].get('pages', []))}")
        else:
            logger.info(f"⏭️ Notebook not in sync queue (may already be synced)")

        # Test 2: Force sync the notebook if it's in the queue
        if target_notebook:
            logger.info(f"\n📋 TEST 2: Force syncing the notebook...")
            from src.core.sync_engine import SyncItem, SyncItemType
            from datetime import datetime

            sync_item = SyncItem(
                item_type=SyncItemType.NOTEBOOK,
                item_id=target_notebook['item_id'],
                content_hash=target_notebook['content_hash'],
                data=target_notebook['data'],
                source_table=target_notebook['source_table'],
                created_at=datetime.now(),
                updated_at=datetime.now()
            )

            result = await sync_manager.sync_item_to_target(sync_item, "notion")

            logger.info(f"📊 Sync Result:")
            logger.info(f"   Status: {result.status.value}")
            logger.info(f"   Target ID: {result.target_id}")
            if result.error_message:
                logger.error(f"   Error: {result.error_message}")
            if result.metadata:
                logger.info(f"   Metadata: {result.metadata}")
        else:
            logger.info(f"\n📋 TEST 2: Skipping sync (notebook not in queue)")

        # Test 3: Check todos from this notebook
        logger.info(f"\n📋 TEST 3: Checking todos from notebook...")
        if tasks_database_id:
            todos_to_sync = await sync_manager._get_todos_needing_sync("notion", limit=50)

            notebook_todos = [todo for todo in todos_to_sync
                            if todo['data'].get('notebook_uuid') == TARGET_NOTEBOOK_UUID]

            if notebook_todos:
                logger.info(f"📝 Found {len(notebook_todos)} todos to sync from this notebook")
                for todo in notebook_todos[:3]:  # Show first 3
                    todo_text = todo['data'].get('text', '')[:50]
                    logger.info(f"   Todo {todo['item_id']}: {todo_text}...")

                # Sync the first todo as a test
                if notebook_todos:
                    first_todo = notebook_todos[0]
                    todo_sync_item = SyncItem(
                        item_type=SyncItemType.TODO,
                        item_id=first_todo['item_id'],
                        content_hash=first_todo['content_hash'],
                        data=first_todo['data'],
                        source_table=first_todo['source_table'],
                        created_at=datetime.now(),
                        updated_at=datetime.now()
                    )

                    todo_result = await sync_manager.sync_item_to_target(todo_sync_item, "notion")
                    logger.info(f"📝 First todo sync result: {todo_result.status.value}")
                    if todo_result.error_message:
                        logger.error(f"   Todo sync error: {todo_result.error_message}")
            else:
                logger.info(f"📝 No todos found needing sync from this notebook")
        else:
            logger.info(f"📝 Todo sync not configured (no tasks_database_id)")

        logger.info(f"\n✅ Unified sync test completed for: {TARGET_NOTEBOOK_NAME}")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_unified_sync())