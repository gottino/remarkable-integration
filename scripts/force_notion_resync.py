#!/usr/bin/env python3
"""
Force re-sync of specific notebooks to Notion.

This script forces a complete re-sync of specified notebooks by clearing their sync state,
ensuring that all current content gets pushed to Notion.
"""

import os
import sys
import logging
from typing import List, Optional

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.core.database import DatabaseManager
from src.integrations.notion_incremental import NotionSyncTracker

def setup_logging():
    """Setup logging for the script."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def get_notebook_info(db: DatabaseManager, notebook_uuid: str) -> Optional[dict]:
    """Get notebook information."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT nm.visible_name, COUNT(nte.page_number) as page_count, 
                   MAX(nte.page_number) as max_page, MIN(nte.created_at) as earliest_content,
                   MAX(nte.created_at) as latest_content
            FROM notebook_metadata nm
            LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
                AND nte.text IS NOT NULL AND length(nte.text) > 0
            WHERE nm.notebook_uuid = ?
            GROUP BY nm.notebook_uuid, nm.visible_name
        ''', (notebook_uuid,))
        
        result = cursor.fetchone()
        if result:
            return {
                'name': result[0],
                'page_count': result[1],
                'max_page': result[2],
                'earliest_content': result[3],
                'latest_content': result[4]
            }
        return None

def force_resync_notebook(db: DatabaseManager, notebook_uuid: str) -> bool:
    """Force re-sync of a notebook by clearing its sync state."""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Clear notebook sync state
            cursor.execute('DELETE FROM notion_notebook_sync WHERE notebook_uuid = ?', (notebook_uuid,))
            notebook_cleared = cursor.rowcount > 0
            
            # Clear page sync state  
            cursor.execute('DELETE FROM notion_page_sync WHERE notebook_uuid = ?', (notebook_uuid,))
            pages_cleared = cursor.rowcount
            
            conn.commit()
            
            logging.info(f"   Cleared sync state: notebook={'Yes' if notebook_cleared else 'No'}, {pages_cleared} pages")
            return True
            
    except Exception as e:
        logging.error(f"   Failed to clear sync state: {e}")
        return False

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Notebooks to force re-sync
    target_notebooks = [
        'ee2fbab7-9f7c-406a-ae5f-dc29168c24ba',  # Collaboration
        '7ff6c6b6-4daa-4e56-9c15-bacb1444ac90',  # Recruiting
    ]
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Process each notebook
    for notebook_uuid in target_notebooks:
        logger.info(f"\\n📔 Processing notebook: {notebook_uuid}")
        
        # Get notebook info
        info = get_notebook_info(db, notebook_uuid)
        if not info:
            logger.warning(f"   Notebook not found or has no content")
            continue
            
        logger.info(f"   Name: {info['name']}")
        logger.info(f"   Content: {info['page_count']} pages (up to page {info['max_page']})")
        logger.info(f"   Content dates: {info['earliest_content']} to {info['latest_content']}")
        
        # Check current sync state
        tracker = NotionSyncTracker(db)
        changes = tracker.get_notebook_changes(notebook_uuid)
        
        if changes['is_new']:
            logger.info(f"   Status: New notebook (not yet synced)")
        else:
            logger.info(f"   Status: Last synced {changes['last_synced']}")
            logger.info(f"   Sync thinks: content_changed={changes['content_changed']}, {changes['current_total_pages']} pages")
        
        # Force re-sync
        logger.info(f"   🔄 Forcing re-sync...")
        success = force_resync_notebook(db, notebook_uuid)
        
        if success:
            logger.info(f"   ✅ Notebook marked for re-sync")
        else:
            logger.error(f"   ❌ Failed to mark for re-sync")
    
    logger.info(f"\\n🎯 Re-sync preparation complete!")
    logger.info(f"   Next steps:")
    logger.info(f"   1. Run: poetry run python -m src.cli.main sync-notion --database-id YOUR_DB_ID")
    logger.info(f"   2. Or use the watch command to trigger automatic sync")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())