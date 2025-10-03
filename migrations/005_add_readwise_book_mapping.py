#!/usr/bin/env python3
"""
Migration 005: Add Readwise book mapping table.

Creates a table to track the relationship between local notebook UUIDs
and Readwise book IDs to ensure highlights from the same book are grouped correctly.
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def apply_migration(cursor: sqlite3.Cursor):
    """Apply the migration to create readwise_book_mapping table."""
    
    # Create readwise_book_mapping table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS readwise_book_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notebook_uuid TEXT NOT NULL,
            readwise_book_id INTEGER NOT NULL,
            book_title TEXT NOT NULL,
            book_author TEXT,
            book_category TEXT,
            document_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(notebook_uuid) ON CONFLICT REPLACE,
            UNIQUE(readwise_book_id) ON CONFLICT IGNORE
        )
    ''')
    
    logger.info("Created readwise_book_mapping table")
    
    # Create indexes for faster lookups
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_readwise_book_mapping_notebook ON readwise_book_mapping(notebook_uuid)')
        logger.info("Created index on notebook_uuid")
    except Exception as e:
        logger.warning(f"Could not create index on notebook_uuid: {e}")
    
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_readwise_book_mapping_readwise_id ON readwise_book_mapping(readwise_book_id)')
        logger.info("Created index on readwise_book_id")
    except Exception as e:
        logger.warning(f"Could not create index on readwise_book_id: {e}")
    
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_readwise_book_mapping_title_author ON readwise_book_mapping(book_title, book_author)')
        logger.info("Created composite index on book_title and book_author")
    except Exception as e:
        logger.warning(f"Could not create composite index: {e}")

def rollback_migration(cursor: sqlite3.Cursor):
    """Rollback the migration."""
    cursor.execute('DROP TABLE IF EXISTS readwise_book_mapping')
    logger.info("Dropped readwise_book_mapping table")

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
    
    print(f"🔧 Running migration 005 on database: {db_path}")
    
    try:
        db_manager = DatabaseManager(db_path)
        with db_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Apply migration
            apply_migration(cursor)
            
            # Record migration in schema_migrations table
            cursor.execute(
                'INSERT OR IGNORE INTO schema_migrations (version, description) VALUES (?, ?)',
                (5, 'Add Readwise book mapping table')
            )
            
            conn.commit()
            print("✅ Migration 005 completed successfully")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)