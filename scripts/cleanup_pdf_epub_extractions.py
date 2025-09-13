#!/usr/bin/env python3
"""
Clean up incorrectly extracted PDF/EPUB content from notebook text extractions.

This script removes text extraction records for documents that are PDFs or EPUBs,
since these should not be treated as notebooks for Notion sync.
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

def get_non_notebook_extractions(db: DatabaseManager):
    """Get text extractions for non-notebook documents."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                nm.notebook_uuid,
                nm.visible_name, 
                nm.document_type,
                COUNT(nte.page_number) as page_count,
                MIN(nte.created_at) as first_extraction,
                MAX(nte.created_at) as last_extraction
            FROM notebook_metadata nm
            JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
            WHERE nm.document_type <> 'notebook'
            GROUP BY nm.notebook_uuid, nm.visible_name, nm.document_type
            ORDER BY page_count DESC
        ''')
        
        return cursor.fetchall()

def cleanup_non_notebook_extractions(db: DatabaseManager):
    """Remove text extraction records for PDFs and EPUBs."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get count before cleanup
        cursor.execute('''
            SELECT COUNT(*) FROM notebook_text_extractions nte
            JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
            WHERE nm.document_type <> 'notebook'
        ''')
        before_count = cursor.fetchone()[0]
        
        # Delete the extractions
        cursor.execute('''
            DELETE FROM notebook_text_extractions
            WHERE notebook_uuid IN (
                SELECT notebook_uuid FROM notebook_metadata 
                WHERE document_type <> 'notebook'
            )
        ''')
        deleted_count = cursor.rowcount
        
        conn.commit()
        
        return before_count, deleted_count

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    logger.info("🧹 Cleaning up PDF/EPUB extractions from notebook text extractions...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Get non-notebook extractions
    non_notebook_extractions = get_non_notebook_extractions(db)
    
    if not non_notebook_extractions:
        logger.info("✅ No PDF/EPUB extractions found - database is clean!")
        return 0
    
    logger.info(f"📋 Found text extractions for {len(non_notebook_extractions)} non-notebook documents:")
    
    total_pages = 0
    for uuid, name, doc_type, page_count, first_extraction, last_extraction in non_notebook_extractions:
        logger.info(f"")
        logger.info(f"📄 {name}")
        logger.info(f"   Type: {doc_type}")
        logger.info(f"   Pages extracted: {page_count}")
        logger.info(f"   Extraction period: {first_extraction} to {last_extraction}")
        total_pages += page_count
    
    logger.info(f"")
    logger.info(f"🎯 Total: {total_pages} pages from {len(non_notebook_extractions)} documents will be removed")
    
    # Clean up the extractions
    logger.info(f"🔥 Removing PDF/EPUB text extractions...")
    before_count, deleted_count = cleanup_non_notebook_extractions(db)
    
    logger.info(f"✅ Cleanup complete!")
    logger.info(f"   Removed {deleted_count} text extraction records")
    logger.info(f"   These were from PDF/EPUB documents, not actual notebooks")
    
    # Verify cleanup
    remaining_extractions = get_non_notebook_extractions(db)
    if not remaining_extractions:
        logger.info(f"🎯 All PDF/EPUB extractions successfully removed!")
        logger.info(f"📝 Only actual notebook content will now be synced to Notion")
    else:
        logger.warning(f"⚠️  {len(remaining_extractions)} non-notebook extractions still remain")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())