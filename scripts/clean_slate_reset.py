#!/usr/bin/env python3
"""
Clean slate reset - Clear all Notion sync state for fresh start.

This script clears ALL Notion sync state so that all notebooks will be 
treated as new when syncing to a fresh Notion database.
"""

import os
import sys
import logging

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.core.database import DatabaseManager

def setup_logging():
    """Setup logging for the script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def get_sync_stats(db: DatabaseManager) -> dict:
    """Get current sync statistics."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Count notebook sync records
        cursor.execute('SELECT COUNT(*) FROM notion_notebook_sync')
        notebook_syncs = cursor.fetchone()[0]
        
        # Count page sync records  
        cursor.execute('SELECT COUNT(*) FROM notion_page_sync')
        page_syncs = cursor.fetchone()[0]
        
        # Count block mappings
        cursor.execute('SELECT COUNT(*) FROM notion_page_blocks')
        block_mappings = cursor.fetchone()[0]
        
        # Count todo syncs
        cursor.execute('SELECT COUNT(*) FROM notion_todo_sync')
        todo_syncs = cursor.fetchone()[0]
        
        return {
            'notebook_syncs': notebook_syncs,
            'page_syncs': page_syncs, 
            'block_mappings': block_mappings,
            'todo_syncs': todo_syncs
        }

def clear_all_sync_state(db: DatabaseManager) -> dict:
    """Clear all Notion sync state."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Clear notebook sync state
        cursor.execute('DELETE FROM notion_notebook_sync')
        notebook_cleared = cursor.rowcount
        
        # Clear page sync state
        cursor.execute('DELETE FROM notion_page_sync') 
        page_cleared = cursor.rowcount
        
        # Clear block mappings
        cursor.execute('DELETE FROM notion_page_blocks')
        block_cleared = cursor.rowcount
        
        # Clear todo sync state
        cursor.execute('DELETE FROM notion_todo_sync')
        todo_cleared = cursor.rowcount
        
        conn.commit()
        
        return {
            'notebook_cleared': notebook_cleared,
            'page_cleared': page_cleared,
            'block_cleared': block_cleared,
            'todo_cleared': todo_cleared
        }

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("🧹 Clean Slate Reset - Clearing all Notion sync state")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Get initial stats
    initial_stats = get_sync_stats(db)
    logger.info(f"📊 Current sync state:")
    logger.info(f"   Notebook sync records: {initial_stats['notebook_syncs']}")
    logger.info(f"   Page sync records: {initial_stats['page_syncs']}")
    logger.info(f"   Block mappings: {initial_stats['block_mappings']}")
    logger.info(f"   Todo sync records: {initial_stats['todo_syncs']}")
    
    if all(count == 0 for count in initial_stats.values()):
        logger.info("✅ Already clean - no sync state to clear!")
        return 0
    
    # Clear everything
    logger.info("🔥 Clearing all sync state...")
    cleared_stats = clear_all_sync_state(db)
    
    # Verify clean state
    final_stats = get_sync_stats(db)
    
    logger.info("✅ Clean slate reset complete!")
    logger.info(f"📋 Cleared:")
    logger.info(f"   Notebook sync records: {cleared_stats['notebook_cleared']}")
    logger.info(f"   Page sync records: {cleared_stats['page_cleared']}")
    logger.info(f"   Block mappings: {cleared_stats['block_cleared']}")
    logger.info(f"   Todo sync records: {cleared_stats['todo_cleared']}")
    
    if all(count == 0 for count in final_stats.values()):
        logger.info("🎯 Database is now in clean slate state!")
        logger.info("📋 Next steps:")
        logger.info("   1. Create a new Notion database")
        logger.info("   2. Run: poetry run python -m src.cli.main sync-notion --database-id NEW_DB_ID")
        logger.info("   3. All notebooks will be treated as new and synced with proper page order")
        logger.info("   4. Future incremental syncs will use the new timestamp-based logic")
    else:
        logger.error("❌ Clean slate failed - some records remain")
        return 1
    
    return 0

if __name__ == '__main__':
    sys.exit(main())