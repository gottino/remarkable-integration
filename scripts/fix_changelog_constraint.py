#!/usr/bin/env python3
"""
Fix the UNIQUE constraint on sync_changelog table.

The current constraint on (source_table, source_id, changed_at) is too restrictive
for multiple operations on the same record within the same timestamp.
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

def fix_changelog_constraint(db: DatabaseManager):
    """Fix the sync_changelog table constraint."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        logger.info("🔧 Fixing sync_changelog UNIQUE constraint...")
        
        # First, check current table structure
        cursor.execute("PRAGMA table_info(sync_changelog)")
        columns = cursor.fetchall()
        logger.info(f"Current table has {len(columns)} columns")
        
        # Drop the unique constraint by recreating the table
        logger.info("📋 Recreating sync_changelog table without restrictive constraint...")
        
        # Backup current data
        cursor.execute("SELECT * FROM sync_changelog")
        existing_data = cursor.fetchall()
        logger.info(f"Backing up {len(existing_data)} existing records")
        
        # Drop existing table
        cursor.execute("DROP TABLE sync_changelog")
        
        # Recreate table with better constraint
        cursor.execute('''
            CREATE TABLE sync_changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- What changed
                source_table TEXT NOT NULL,
                source_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                
                -- When and what changed
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                changed_fields TEXT,
                content_hash_before TEXT,
                content_hash_after TEXT,
                
                -- Processing state
                processed_at TIMESTAMP,
                process_status TEXT DEFAULT 'pending',
                
                -- Optional: link to triggering action
                trigger_source TEXT
                
                -- Removed the UNIQUE constraint that was too restrictive
            )
        ''')
        
        # Recreate indexes
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_changelog_pending
            ON sync_changelog(process_status, changed_at)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_changelog_source
            ON sync_changelog(source_table, source_id, changed_at)
        ''')
        
        # Restore data
        if existing_data:
            logger.info("📥 Restoring existing data...")
            
            # Prepare insert statement (match column count)
            insert_sql = '''
                INSERT INTO sync_changelog (
                    id, source_table, source_id, operation, changed_at,
                    changed_fields, content_hash_before, content_hash_after,
                    processed_at, process_status, trigger_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            
            cursor.executemany(insert_sql, existing_data)
            logger.info(f"✅ Restored {len(existing_data)} records")
        
        conn.commit()
        
        logger.info("🎉 sync_changelog table constraint fixed!")
        
        return True

def main():
    setup_logging()
    global logger
    logger = logging.getLogger(__name__)
    
    logger.info("🔧 Fixing sync_changelog constraint...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    try:
        success = fix_changelog_constraint(db)
        
        if success:
            logger.info("✅ Constraint fix completed successfully!")
            logger.info("Now you can test change tracking without constraint issues")
            return 0
        else:
            logger.error("❌ Failed to fix constraint")
            return 1
        
    except Exception as e:
        logger.error(f"❌ Error fixing constraint: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())