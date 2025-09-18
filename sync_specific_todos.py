#!/usr/bin/env python3
"""
Sync specific todo items through the unified sync system.

This script properly syncs specific todos with full sync record tracking
and block linking, just like the normal sync process.
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
from src.core.sync_engine import SyncItem, SyncItemType, ContentFingerprint
from src.integrations.notion_unified_sync import NotionSyncTarget
from src.utils.config import Config
from src.utils.api_keys import get_notion_api_key

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def sync_specific_todos(todo_ids: list[int]):
    """Sync specific todo items through the unified sync system."""

    # Initialize components
    db_path = './data/remarkable_pipeline.db'
    db_manager = DatabaseManager(db_path)
    config = Config()

    # Initialize unified sync manager
    sync_manager = UnifiedSyncManager(db_manager)

    # Setup Notion target with todo support
    notion_api_key = get_notion_api_key()
    notion_database_id = config.get('integrations.notion.database_id')
    tasks_database_id = config.get('integrations.notion.tasks_database_id')

    if not notion_api_key or not notion_database_id:
        logger.error("❌ Missing Notion API key or database ID")
        return

    if not tasks_database_id:
        logger.error("❌ Missing tasks database ID - todo sync not configured")
        return

    # Create and register Notion target
    notion_target = NotionSyncTarget(
        notion_token=notion_api_key,
        database_id=notion_database_id,
        tasks_database_id=tasks_database_id,
        verify_ssl=False
    )
    sync_manager.register_target(notion_target)

    logger.info(f"🎯 Syncing specific todos: {todo_ids}")

    # Fetch the specific todos with all block linking information
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Use the same query as unified sync but filter by specific IDs
        placeholders = ','.join(['?' for _ in todo_ids])
        cursor.execute(f'''
            SELECT t.id, t.notebook_uuid, t.text, t.page_number, t.updated_at,
                   nm.visible_name as notebook_name,
                   nns.notion_page_id,
                   npb.notion_block_id,
                   t.actual_date, t.confidence, t.created_at, t.completed
            FROM todos t
            LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
            LEFT JOIN notion_notebook_sync nns ON t.notebook_uuid = nns.notebook_uuid
            LEFT JOIN notion_page_blocks npb ON t.notebook_uuid = npb.notebook_uuid
                AND t.page_number = npb.page_number
            WHERE t.id IN ({placeholders})
            ORDER BY t.id
        ''', todo_ids)

        todos_data = cursor.fetchall()

    if not todos_data:
        logger.error(f"❌ No todos found with IDs: {todo_ids}")
        return

    logger.info(f"📋 Found {len(todos_data)} todos to sync")

    # Process each todo
    synced_count = 0
    failed_count = 0

    for row in todos_data:
        (todo_id, notebook_uuid, text, page_number, updated_at,
         notebook_name, notion_page_id, notion_block_id,
         actual_date, confidence, created_at, completed) = row

        logger.info(f"\n📝 Processing todo {todo_id}: {text[:50]}...")
        logger.info(f"   Notebook: {notebook_name}")
        logger.info(f"   Page: {page_number}")
        logger.info(f"   Completed: {completed}")

        if completed:
            logger.warning(f"   ⏭️ Skipping completed todo")
            continue

        # Create sync item with all the data
        todo_data = {
            'text': text,
            'notebook_uuid': notebook_uuid,
            'page_number': page_number,
            'type': 'todo',
            'todo_id': todo_id,
            'notebook_name': notebook_name,
            'notion_page_id': notion_page_id,
            'notion_block_id': notion_block_id,
            'actual_date': actual_date,
            'confidence': confidence or 0.0,
            'created_at': created_at,
            'completed': completed
        }

        # Calculate content hash
        content_hash = ContentFingerprint.for_todo({
            'text': text,
            'notebook_uuid': notebook_uuid,
            'page_number': page_number,
            'type': 'todo'
        })

        # Create sync item
        sync_item = SyncItem(
            item_type=SyncItemType.TODO,
            item_id=str(todo_id),
            content_hash=content_hash,
            data=todo_data,
            source_table='todos',
            created_at=datetime.fromisoformat(created_at) if created_at else datetime.now(),
            updated_at=datetime.fromisoformat(updated_at) if updated_at else datetime.now()
        )

        # Sync to Notion
        try:
            result = await sync_manager.sync_item_to_target(sync_item, "notion")

            if result.status.value == 'success':
                logger.info(f"   ✅ Successfully synced todo {todo_id}")
                synced_count += 1
            elif result.status.value == 'skipped':
                skip_reason = result.metadata.get('reason', 'unknown') if result.metadata else 'unknown'
                logger.info(f"   ⏭️ Skipped todo {todo_id}: {skip_reason}")
                if skip_reason == 'already_synced':
                    synced_count += 1  # Count as success
            else:
                logger.error(f"   ❌ Failed to sync todo {todo_id}: {result.error_message or 'Unknown error'}")
                failed_count += 1

        except Exception as e:
            logger.error(f"   ❌ Exception syncing todo {todo_id}: {e}")
            failed_count += 1

    # Summary
    logger.info(f"\n📊 Sync Summary:")
    logger.info(f"   ✅ Successfully synced: {synced_count}")
    logger.info(f"   ❌ Failed: {failed_count}")
    logger.info(f"   📋 Total processed: {synced_count + failed_count}")


async def main():
    """Main entry point."""
    # Specific todo IDs to sync
    todo_ids = [908, 909, 910, 911, 912, 913, 914, 915]

    logger.info("🚀 Starting targeted todo sync...")
    await sync_specific_todos(todo_ids)
    logger.info("✅ Targeted todo sync complete!")


if __name__ == "__main__":
    asyncio.run(main())