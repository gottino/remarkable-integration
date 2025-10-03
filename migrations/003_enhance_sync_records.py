#!/usr/bin/env python3
"""
Migration 003: Enhance sync_records table for unified sync system.

Adds missing fields needed for the unified sync architecture:
- item_id: Local identifier for the item being synced
- metadata: JSON field for additional sync-specific information
"""

import sqlite3
import logging
import json
from pathlib import Path

logger = logging.getLogger(__name__)

def apply_migration(cursor: sqlite3.Cursor):
    """Apply the migration to enhance sync_records table."""
    
    # Add item_id column
    try:
        cursor.execute('ALTER TABLE sync_records ADD COLUMN item_id TEXT')
        logger.info("Added item_id column to sync_records")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            logger.debug("item_id column already exists")
        else:
            raise
    
    # Add metadata column for JSON data
    try:
        cursor.execute('ALTER TABLE sync_records ADD COLUMN metadata TEXT')
        logger.info("Added metadata column to sync_records")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            logger.debug("metadata column already exists")
        else:
            raise
    
    # Create index for item_id for faster lookups
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_item_id ON sync_records(item_id)')
        logger.info("Created index on item_id")
    except Exception as e:
        logger.warning(f"Could not create index on item_id: {e}")
    
    # Create index for combined lookups
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_item_target ON sync_records(item_id, target_name)')
        logger.info("Created composite index on item_id and target_name")
    except Exception as e:
        logger.warning(f"Could not create composite index: {e}")

def rollback_migration(cursor: sqlite3.Cursor):
    """Rollback the migration (SQLite doesn't support dropping columns easily)."""
    logger.warning("SQLite doesn't support dropping columns easily. Manual rollback required.")
    # In a real rollback, we'd need to recreate the table without the new columns

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
    
    print(f"🔧 Running migration 003 on database: {db_path}")
    
    try:
        db_manager = DatabaseManager(db_path)
        with db_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Apply migration
            apply_migration(cursor)
            
            # Record migration in schema_migrations table
            cursor.execute(
                'INSERT OR IGNORE INTO schema_migrations (version, description) VALUES (?, ?)',
                (3, 'Enhance sync_records table for unified sync system')
            )
            
            conn.commit()
            print("✅ Migration 003 completed successfully")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)