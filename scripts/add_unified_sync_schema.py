#!/usr/bin/env python3
"""
Add unified sync schema for target-agnostic sync state management.

This script creates the new unified sync tables alongside existing ones
for non-breaking foundation work. The new schema supports any sync target
(Notion, Readwise, etc.) with a generic approach.
"""

import os
import sys
import logging
from datetime import datetime

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

def create_unified_sync_tables(db: DatabaseManager):
    """Create the unified sync schema tables."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        logger.info("🗂️  Creating unified sync_state table...")
        
        # Unified sync state table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_state (
                -- Source record identification
                source_table TEXT NOT NULL,           -- 'notebooks', 'pages', 'todos', 'highlights'
                source_id TEXT NOT NULL,              -- UUID, composite key like 'uuid|page_num'
                
                -- Target system identification  
                sync_target TEXT NOT NULL,            -- 'notion', 'readwise', 'obsidian'
                
                -- Sync state tracking
                remote_id TEXT,                       -- Target-specific ID (notion page ID, etc.)
                last_synced_content TEXT,             -- Full content for reliable comparison
                last_synced_at TIMESTAMP,
                sync_version INTEGER DEFAULT 1,       -- Handle schema evolution
                sync_status TEXT DEFAULT 'pending',   -- 'pending', 'synced', 'failed', 'skipped'
                
                -- Metadata for target-specific data (JSON)
                metadata TEXT,                        -- Store target-specific info as JSON
                
                -- Audit fields
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                PRIMARY KEY (source_table, source_id, sync_target)
            )
        ''')
        
        logger.info("📝 Creating unified sync_changelog table...")
        
        # Unified change log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                
                -- What changed
                source_table TEXT NOT NULL,
                source_id TEXT NOT NULL,
                operation TEXT NOT NULL,              -- 'INSERT', 'UPDATE', 'DELETE'
                
                -- When and what changed
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                changed_fields TEXT,                  -- JSON array of changed field names
                content_hash_before TEXT,             -- Content hash before change
                content_hash_after TEXT,              -- Content hash after change
                
                -- Processing state
                processed_at TIMESTAMP,
                process_status TEXT DEFAULT 'pending', -- 'pending', 'processed', 'failed'
                
                -- Optional: link to triggering action
                trigger_source TEXT,                  -- 'file_watcher', 'manual_sync', 'api'
                
                -- Indexing for performance
                UNIQUE(source_table, source_id, changed_at)
            )
        ''')
        
        logger.info("📊 Creating indexes for performance...")
        
        # Performance indexes
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sync_state_target 
            ON sync_state(sync_target, sync_status)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_sync_state_updated
            ON sync_state(updated_at)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_changelog_pending
            ON sync_changelog(process_status, changed_at)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_changelog_source
            ON sync_changelog(source_table, source_id, changed_at)
        ''')
        
        logger.info("🔧 Adding triggers for updated_at maintenance...")
        
        # Auto-update trigger for sync_state
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS sync_state_updated_at
                AFTER UPDATE ON sync_state
                BEGIN
                    UPDATE sync_state 
                    SET updated_at = CURRENT_TIMESTAMP 
                    WHERE source_table = NEW.source_table 
                        AND source_id = NEW.source_id 
                        AND sync_target = NEW.sync_target;
                END
        ''')
        
        conn.commit()
        
        return True

def verify_schema(db: DatabaseManager):
    """Verify the unified schema was created correctly."""
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check tables exist
        cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('sync_state', 'sync_changelog')
        ''')
        tables = [row[0] for row in cursor.fetchall()]
        
        if len(tables) != 2:
            return False, f"Expected 2 tables, found {len(tables)}: {tables}"
        
        # Check sync_state columns
        cursor.execute('PRAGMA table_info(sync_state)')
        sync_state_columns = [col[1] for col in cursor.fetchall()]
        required_columns = [
            'source_table', 'source_id', 'sync_target', 'remote_id',
            'last_synced_content', 'last_synced_at', 'sync_status', 'metadata'
        ]
        
        missing_columns = [col for col in required_columns if col not in sync_state_columns]
        if missing_columns:
            return False, f"Missing sync_state columns: {missing_columns}"
        
        # Check sync_changelog columns  
        cursor.execute('PRAGMA table_info(sync_changelog)')
        changelog_columns = [col[1] for col in cursor.fetchall()]
        required_changelog_columns = [
            'id', 'source_table', 'source_id', 'operation', 'changed_at', 'process_status'
        ]
        
        missing_changelog_columns = [col for col in required_changelog_columns if col not in changelog_columns]
        if missing_changelog_columns:
            return False, f"Missing sync_changelog columns: {missing_changelog_columns}"
        
        return True, "Schema verification passed"

def main():
    setup_logging()
    global logger
    logger = logging.getLogger(__name__)
    
    logger.info("🚀 Adding unified sync schema...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Check if tables already exist
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('sync_state', 'sync_changelog')
        ''')
        existing_tables = [row[0] for row in cursor.fetchall()]
    
    if existing_tables:
        logger.info(f"⚠️  Tables already exist: {existing_tables}")
        logger.info("Skipping creation (tables already present)")
        return 0
    
    try:
        # Create unified schema
        success = create_unified_sync_tables(db)
        
        if not success:
            logger.error("❌ Failed to create unified sync schema")
            return 1
        
        # Verify schema
        verification_passed, message = verify_schema(db)
        if not verification_passed:
            logger.error(f"❌ Schema verification failed: {message}")
            return 1
        
        logger.info("✅ Unified sync schema created successfully!")
        logger.info("")
        logger.info("📋 Schema Summary:")
        logger.info("   - sync_state: Unified sync state for all targets")
        logger.info("   - sync_changelog: Change tracking for event-driven sync")
        logger.info("   - Indexes: Optimized for common query patterns")
        logger.info("   - Triggers: Auto-maintain updated_at timestamps")
        logger.info("")
        logger.info("🎯 Next Steps:")
        logger.info("   1. Run migration script to populate from existing sync tables")
        logger.info("   2. Add change tracking to write operations")
        logger.info("   3. Build generic sync engine using new schema")
        logger.info("")
        logger.info("ℹ️  Non-breaking: Existing sync continues to work unchanged")
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Error creating unified sync schema: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())