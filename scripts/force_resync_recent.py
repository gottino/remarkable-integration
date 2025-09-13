#!/usr/bin/env python3
"""
Force re-sync of recently accessed notebooks to Notion.

This script forces a complete re-sync of notebooks that were accessed in the last week,
ensuring that all current content gets pushed to Notion with the new timestamp-based logic.
"""

import os
import sys
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

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

def get_recently_accessed_notebooks(db: DatabaseManager, days_back: int = 7) -> List[dict]:
    """Get notebooks that were accessed in the last N days."""
    cutoff_timestamp = (datetime.now() - timedelta(days=days_back)).timestamp() * 1000
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                nm.notebook_uuid,
                nm.visible_name,
                nm.last_opened,
                COUNT(nte.page_number) as page_count,
                MAX(nte.page_number) as max_page,
                MAX(nte.created_at) as latest_content,
                nns.last_synced
            FROM notebook_metadata nm
            LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
                AND nte.text IS NOT NULL AND length(nte.text) > 0
            LEFT JOIN notion_notebook_sync nns ON nm.notebook_uuid = nns.notebook_uuid
            WHERE nm.last_opened IS NOT NULL 
                AND CAST(nm.last_opened AS INTEGER) > ?
            GROUP BY nm.notebook_uuid, nm.visible_name, nm.last_opened, nns.last_synced
            ORDER BY CAST(nm.last_opened AS INTEGER) DESC
        ''', (cutoff_timestamp,))
        
        results = []
        for row in cursor.fetchall():
            uuid, name, last_opened_str, page_count, max_page, latest_content, last_synced = row
            
            # Convert reMarkable timestamp to readable format
            last_opened_dt = None
            if last_opened_str:
                try:
                    # reMarkable timestamps are in milliseconds, UTC
                    utc_timestamp = datetime.fromtimestamp(int(last_opened_str) / 1000, tz=timezone.utc)
                    last_opened_dt = utc_timestamp.replace(tzinfo=None)
                except (ValueError, TypeError):
                    pass
            
            results.append({
                'uuid': uuid,
                'name': name,
                'last_opened': last_opened_dt,
                'page_count': page_count or 0,
                'max_page': max_page or 0,
                'latest_content': latest_content,
                'last_synced': last_synced,
                'has_sync_record': last_synced is not None
            })
        
        return results

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
            
            logging.debug(f"   Cleared sync state: notebook={'Yes' if notebook_cleared else 'No'}, {pages_cleared} pages")
            return True
            
    except Exception as e:
        logging.error(f"   Failed to clear sync state: {e}")
        return False

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    days_back = 7
    logger.info(f"🔍 Finding notebooks accessed in the last {days_back} days...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Get recently accessed notebooks
    recent_notebooks = get_recently_accessed_notebooks(db, days_back)
    
    if not recent_notebooks:
        logger.info(f"📭 No notebooks found that were accessed in the last {days_back} days")
        return 0
    
    logger.info(f"📚 Found {len(recent_notebooks)} recently accessed notebooks:")
    
    # Show what will be re-synced
    total_pages = 0
    notebooks_to_resync = []
    
    for nb in recent_notebooks:
        logger.info(f"")
        logger.info(f"📔 {nb['name']}")
        logger.info(f"   UUID: {nb['uuid']}")
        logger.info(f"   Last opened: {nb['last_opened']}")
        logger.info(f"   Content: {nb['page_count']} pages (up to page {nb['max_page']})")
        logger.info(f"   Latest content: {nb['latest_content']}")
        
        if nb['has_sync_record']:
            logger.info(f"   Last synced: {nb['last_synced']}")
            logger.info(f"   📤 Will be re-synced (clearing existing sync state)")
            notebooks_to_resync.append(nb)
            total_pages += nb['page_count']
        else:
            logger.info(f"   📝 New notebook (will be synced normally)")
    
    if not notebooks_to_resync:
        logger.info(f"\\n✅ All recently accessed notebooks are new - no re-sync needed")
        logger.info(f"   They will be synced normally on next sync run")
        return 0
    
    logger.info(f"\\n🎯 Summary:")
    logger.info(f"   {len(notebooks_to_resync)} notebooks will be re-synced")
    logger.info(f"   {total_pages} total pages will be re-processed")
    logger.info(f"\\n🚀 Proceeding with re-sync...")
    
    # Force re-sync each notebook
    success_count = 0
    for nb in notebooks_to_resync:
        logger.info(f"\\n🔄 Processing: {nb['name']}")
        success = force_resync_notebook(db, nb['uuid'])
        
        if success:
            logger.info(f"   ✅ Marked for re-sync")
            success_count += 1
        else:
            logger.error(f"   ❌ Failed to mark for re-sync")
    
    logger.info(f"\\n🎉 Re-sync preparation complete!")
    logger.info(f"   ✅ {success_count}/{len(notebooks_to_resync)} notebooks marked for re-sync")
    logger.info(f"\\n📋 Next steps:")
    logger.info(f"   1. Run: poetry run python -m src.cli.main sync-notion --database-id YOUR_DB_ID")
    logger.info(f"   2. Or use the watch command to trigger automatic sync")
    logger.info(f"\\n💡 The new timestamp-based logic will ensure proper content sync going forward!")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())