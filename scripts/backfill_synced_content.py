#!/usr/bin/env python3
"""
Backfill last_synced_content for existing synced pages.

This script populates the last_synced_content column with the current text
content for pages that have already been synced to Notion (have last_synced timestamp).
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

def backfill_synced_content(db: DatabaseManager):
    """Backfill the last_synced_content column for existing synced pages."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get pages that have been synced but don't have content stored
        cursor.execute('''
            SELECT 
                nps.notebook_uuid,
                nps.page_number,
                nte.text,
                nm.visible_name as notebook_name,
                nps.last_synced
            FROM notion_page_sync nps
            JOIN notebook_text_extractions nte ON 
                nps.notebook_uuid = nte.notebook_uuid AND 
                nps.page_number = nte.page_number
            JOIN notebook_metadata nm ON nps.notebook_uuid = nm.notebook_uuid
            WHERE nps.last_synced IS NOT NULL 
                AND nps.last_synced_content IS NULL
                AND nte.text IS NOT NULL
                AND length(nte.text) > 0
            ORDER BY nm.visible_name, nps.page_number
        ''')
        
        pages_to_update = cursor.fetchall()
        
        if not pages_to_update:
            return 0, {}
        
        # Group by notebook for reporting
        by_notebook = {}
        for notebook_uuid, page_number, text, notebook_name, last_synced in pages_to_update:
            if notebook_name not in by_notebook:
                by_notebook[notebook_name] = []
            by_notebook[notebook_name].append({
                'notebook_uuid': notebook_uuid,
                'page_number': page_number,
                'text': text,
                'last_synced': last_synced
            })
        
        # Update the pages with their current content
        updated_count = 0
        for notebook_uuid, page_number, text, notebook_name, last_synced in pages_to_update:
            cursor.execute('''
                UPDATE notion_page_sync 
                SET last_synced_content = ?
                WHERE notebook_uuid = ? AND page_number = ?
            ''', (text, notebook_uuid, page_number))
            updated_count += 1
        
        conn.commit()
        
        return updated_count, by_notebook

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("🔄 Backfilling last_synced_content for existing synced pages...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Check current state
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Total synced pages
        cursor.execute('''
            SELECT COUNT(*) FROM notion_page_sync 
            WHERE last_synced IS NOT NULL
        ''')
        total_synced = cursor.fetchone()[0]
        
        # Pages with content already stored
        cursor.execute('''
            SELECT COUNT(*) FROM notion_page_sync 
            WHERE last_synced IS NOT NULL AND last_synced_content IS NOT NULL
        ''')
        already_have_content = cursor.fetchone()[0]
        
        logger.info(f"📊 Current state:")
        logger.info(f"   Total synced pages: {total_synced}")
        logger.info(f"   Pages with stored content: {already_have_content}")
        logger.info(f"   Pages needing backfill: {total_synced - already_have_content}")
    
    if total_synced == already_have_content:
        logger.info("✅ All synced pages already have content stored!")
        return 0
    
    # Perform backfill
    logger.info("🔄 Starting backfill process...")
    updated_count, by_notebook = backfill_synced_content(db)
    
    if updated_count == 0:
        logger.info("✅ No pages needed backfill - all up to date!")
        return 0
    
    # Report results
    logger.info(f"✅ Backfill complete!")
    logger.info(f"   Updated {updated_count} pages across {len(by_notebook)} notebooks")
    logger.info("")
    
    for notebook_name, pages in by_notebook.items():
        logger.info(f"📖 {notebook_name}: {len(pages)} pages")
        for page in pages[:3]:  # Show first 3 pages
            content_preview = page['text'][:50].replace('\n', ' ')
            logger.info(f"   Page {page['page_number']}: {content_preview}...")
        if len(pages) > 3:
            logger.info(f"   ... and {len(pages) - 3} more pages")
    
    # Verify backfill
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM notion_page_sync 
            WHERE last_synced IS NOT NULL AND last_synced_content IS NOT NULL
        ''')
        final_with_content = cursor.fetchone()[0]
        
        logger.info("")
        logger.info(f"🎯 Final state: {final_with_content}/{total_synced} synced pages now have content stored")
        
        if final_with_content == total_synced:
            logger.info("✅ All synced pages now have their content properly stored!")
        else:
            logger.warning(f"⚠️  {total_synced - final_with_content} pages still missing content")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())