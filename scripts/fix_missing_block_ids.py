#!/usr/bin/env python3
"""
Fix missing notion_block_id values in notion_page_sync table.

This script backfills missing block IDs from the notion_page_blocks table
to the notion_page_sync table to fix the content propagation issue.
"""

import os
import sys
import logging
from typing import List, Tuple

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

def get_missing_block_ids(db: DatabaseManager) -> List[Tuple]:
    """Get all pages in notion_page_sync that are missing block IDs."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT nps.notebook_uuid, nps.page_number, npb.notion_block_id
            FROM notion_page_sync nps
            LEFT JOIN notion_page_blocks npb ON 
                nps.notebook_uuid = npb.notebook_uuid AND 
                nps.page_number = npb.page_number
            WHERE (nps.notion_block_id IS NULL OR nps.notion_block_id = '')
                AND npb.notion_block_id IS NOT NULL
                AND npb.notion_block_id != ''
            ORDER BY nps.notebook_uuid, nps.page_number
        ''')
        return cursor.fetchall()

def update_missing_block_ids(db: DatabaseManager, missing_records: List[Tuple]) -> int:
    """Update notion_page_sync with block IDs from notion_page_blocks."""
    updated_count = 0
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        for notebook_uuid, page_number, notion_block_id in missing_records:
            cursor.execute('''
                UPDATE notion_page_sync 
                SET notion_block_id = ?
                WHERE notebook_uuid = ? AND page_number = ?
            ''', (notion_block_id, notebook_uuid, page_number))
            
            if cursor.rowcount > 0:
                updated_count += 1
                logging.debug(f"Updated {notebook_uuid} page {page_number} with block ID {notion_block_id}")
        
        conn.commit()
    
    return updated_count

def get_stats(db: DatabaseManager) -> dict:
    """Get statistics about the sync tables."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Total pages in sync table
        cursor.execute('SELECT COUNT(*) FROM notion_page_sync')
        total_pages = cursor.fetchone()[0]
        
        # Pages with block IDs
        cursor.execute('''
            SELECT COUNT(*) FROM notion_page_sync 
            WHERE notion_block_id IS NOT NULL AND notion_block_id != ''
        ''')
        with_block_ids = cursor.fetchone()[0]
        
        # Pages with block mappings available
        cursor.execute('''
            SELECT COUNT(*) FROM notion_page_blocks 
            WHERE notion_block_id IS NOT NULL AND notion_block_id != ''
        ''')
        available_block_ids = cursor.fetchone()[0]
        
        return {
            'total_pages': total_pages,
            'with_block_ids': with_block_ids,
            'available_block_ids': available_block_ids,
            'missing_block_ids': total_pages - with_block_ids
        }

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Get initial statistics
    initial_stats = get_stats(db)
    logger.info(f"📊 Initial Stats:")
    logger.info(f"   Total pages in sync table: {initial_stats['total_pages']}")
    logger.info(f"   Pages with block IDs: {initial_stats['with_block_ids']}")
    logger.info(f"   Pages missing block IDs: {initial_stats['missing_block_ids']}")
    logger.info(f"   Available block mappings: {initial_stats['available_block_ids']}")
    
    # Find pages missing block IDs that can be fixed
    logger.info("🔍 Finding pages with missing block IDs...")
    missing_records = get_missing_block_ids(db)
    
    if not missing_records:
        logger.info("✅ No missing block IDs found - all pages are properly linked!")
        return 0
    
    logger.info(f"📋 Found {len(missing_records)} pages that can be fixed")
    
    # Group by notebook for reporting
    by_notebook = {}
    for notebook_uuid, page_number, block_id in missing_records:
        if notebook_uuid not in by_notebook:
            by_notebook[notebook_uuid] = []
        by_notebook[notebook_uuid].append(page_number)
    
    logger.info(f"📖 Affected notebooks:")
    for notebook_uuid, pages in by_notebook.items():
        logger.info(f"   {notebook_uuid}: {len(pages)} pages")
    
    # Update the missing block IDs
    logger.info("🔧 Updating missing block IDs...")
    updated_count = update_missing_block_ids(db, missing_records)
    
    # Get final statistics
    final_stats = get_stats(db)
    
    logger.info(f"✅ Update complete!")
    logger.info(f"   Updated {updated_count} pages")
    logger.info(f"   Pages with block IDs: {initial_stats['with_block_ids']} → {final_stats['with_block_ids']}")
    logger.info(f"   Coverage: {final_stats['with_block_ids']}/{final_stats['total_pages']} ({final_stats['with_block_ids']/final_stats['total_pages']*100:.1f}%)")
    
    if final_stats['missing_block_ids'] > 0:
        logger.warning(f"⚠️  Still missing block IDs for {final_stats['missing_block_ids']} pages")
        logger.info("   These pages may need to be re-synced to Notion")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())