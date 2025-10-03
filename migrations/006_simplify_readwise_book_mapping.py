#!/usr/bin/env python3
"""
Migration 006: Simplify readwise_book_mapping table.

Removes redundant columns that duplicate information already in notebook_metadata.
The table should only be a simple linking table between notebook_uuid and readwise_book_id.
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def apply_migration(cursor: sqlite3.Cursor):
    """Apply the migration to simplify readwise_book_mapping table."""
    
    # Create the new simplified table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS readwise_book_mapping_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notebook_uuid TEXT NOT NULL UNIQUE,
            readwise_book_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(notebook_uuid) ON CONFLICT REPLACE
        )
    ''')
    
    logger.info("Created simplified readwise_book_mapping_new table")
    
    # Migrate existing data if the old table exists
    try:
        cursor.execute('''
            INSERT INTO readwise_book_mapping_new (notebook_uuid, readwise_book_id, created_at)
            SELECT notebook_uuid, readwise_book_id, created_at 
            FROM readwise_book_mapping
        ''')
        
        # Drop the old table
        cursor.execute('DROP TABLE readwise_book_mapping')
        
        # Rename the new table
        cursor.execute('ALTER TABLE readwise_book_mapping_new RENAME TO readwise_book_mapping')
        
        logger.info("Migrated existing data and replaced table")
        
    except sqlite3.OperationalError as e:
        if 'no such table' in str(e).lower():
            # Old table doesn't exist, just rename the new one
            cursor.execute('ALTER TABLE readwise_book_mapping_new RENAME TO readwise_book_mapping')
            logger.info("Created new simplified table (no existing data to migrate)")
        else:
            raise
    
    # Create indexes for the simplified table
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_readwise_book_mapping_notebook ON readwise_book_mapping(notebook_uuid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_readwise_book_mapping_readwise_id ON readwise_book_mapping(readwise_book_id)')
        logger.info("Created indexes for simplified table")
    except Exception as e:
        logger.warning(f"Could not create indexes: {e}")

def rollback_migration(cursor: sqlite3.Cursor):
    """Rollback the migration."""
    cursor.execute('DROP TABLE IF EXISTS readwise_book_mapping')
    logger.info("Dropped simplified readwise_book_mapping table")

if __name__ == "__main__":
    # Run migration directly
    import sys
    import os
    
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    from src.core.database import DatabaseManager
    from src.utils.config import Config
    
    # Load config and get database path
    config = Config()
    db_path = config.get("database.path", "./data/remarkable_pipeline.db")
    
    print(f"🔧 Running migration 006 on database: {db_path}")
    print("   📝 Simplifying readwise_book_mapping table (removing redundant columns)")
    
    try:
        db_manager = DatabaseManager(db_path)
        with db_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Apply migration
            apply_migration(cursor)
            
            # Record migration in schema_migrations table
            cursor.execute(
                'INSERT OR IGNORE INTO schema_migrations (version, description) VALUES (?, ?)',
                (6, 'Simplify readwise_book_mapping table - remove redundant columns')
            )
            
            conn.commit()
            print("✅ Migration 006 completed successfully")
            print("   📋 Table now only stores notebook_uuid ↔ readwise_book_id mapping")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)