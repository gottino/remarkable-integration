#!/usr/bin/env python3
"""
Migrate existing sync states to unified sync schema.

This script migrates data from the existing notion_*_sync tables
to the new unified sync_state table without disrupting current operations.
"""

import os
import sys
import logging
import json
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

def migrate_notebook_sync_states(db: DatabaseManager):
    """Migrate from notion_notebook_sync to unified sync_state."""
    logger.info("📒 Migrating notebook sync states...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get existing notebook sync states
        cursor.execute('''
            SELECT 
                notebook_uuid, notion_page_id, last_synced, 
                content_hash, total_pages, metadata_hash
            FROM notion_notebook_sync
        ''')
        notebook_states = cursor.fetchall()
        
        migrated_count = 0
        for notebook_uuid, notion_page_id, last_synced, content_hash, total_pages, metadata_hash in notebook_states:
            # Create metadata JSON
            metadata = {
                'content_hash': content_hash,
                'total_pages': total_pages,
                'metadata_hash': metadata_hash,
                'migrated_from': 'notion_notebook_sync'
            }
            
            # Insert into unified sync_state
            cursor.execute('''
                INSERT OR IGNORE INTO sync_state (
                    source_table, source_id, sync_target,
                    remote_id, last_synced_at, sync_status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                'notebooks',           # source_table
                notebook_uuid,        # source_id  
                'notion',             # sync_target
                notion_page_id,       # remote_id
                last_synced,          # last_synced_at
                'synced',             # sync_status
                json.dumps(metadata)  # metadata
            ))
            migrated_count += 1
        
        conn.commit()
        logger.info(f"   ✅ Migrated {migrated_count} notebook sync states")
        return migrated_count

def migrate_page_sync_states(db: DatabaseManager):
    """Migrate from notion_page_sync to unified sync_state.""" 
    logger.info("📄 Migrating page sync states...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get existing page sync states with content
        cursor.execute('''
            SELECT 
                notebook_uuid, page_number, page_uuid, content_hash,
                last_synced, notion_block_id, last_synced_content
            FROM notion_page_sync
        ''')
        page_states = cursor.fetchall()
        
        migrated_count = 0
        for notebook_uuid, page_number, page_uuid, content_hash, last_synced, notion_block_id, last_synced_content in page_states:
            # Create composite source_id for pages
            source_id = f"{notebook_uuid}|{page_number}"
            
            # Create metadata JSON
            metadata = {
                'page_uuid': page_uuid,
                'content_hash': content_hash,
                'page_number': page_number,
                'migrated_from': 'notion_page_sync'
            }
            
            # Insert into unified sync_state
            cursor.execute('''
                INSERT OR IGNORE INTO sync_state (
                    source_table, source_id, sync_target,
                    remote_id, last_synced_content, last_synced_at, 
                    sync_status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'pages',                    # source_table
                source_id,                  # source_id (composite)
                'notion',                   # sync_target  
                notion_block_id,            # remote_id
                last_synced_content,        # last_synced_content
                last_synced,                # last_synced_at
                'synced',                   # sync_status
                json.dumps(metadata)        # metadata
            ))
            migrated_count += 1
        
        conn.commit()
        logger.info(f"   ✅ Migrated {migrated_count} page sync states")
        return migrated_count

def migrate_todo_sync_states(db: DatabaseManager):
    """Migrate from notion_todo_sync to unified sync_state."""
    logger.info("✅ Migrating todo sync states...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get existing todo sync states
        cursor.execute('''
            SELECT 
                todo_id, notion_page_id, notion_database_id,
                exported_at, last_updated
            FROM notion_todo_sync
        ''')
        todo_states = cursor.fetchall()
        
        migrated_count = 0
        for todo_id, notion_page_id, notion_database_id, exported_at, last_updated in todo_states:
            # Create metadata JSON
            metadata = {
                'notion_database_id': notion_database_id,
                'exported_at': exported_at,
                'migrated_from': 'notion_todo_sync'
            }
            
            # Insert into unified sync_state
            cursor.execute('''
                INSERT OR IGNORE INTO sync_state (
                    source_table, source_id, sync_target,
                    remote_id, last_synced_at, sync_status, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                'todos',                  # source_table
                str(todo_id),            # source_id
                'notion',                # sync_target
                notion_page_id,          # remote_id (Notion page created for todo)
                last_updated or exported_at,  # last_synced_at
                'synced',                # sync_status
                json.dumps(metadata)     # metadata
            ))
            migrated_count += 1
        
        conn.commit()
        logger.info(f"   ✅ Migrated {migrated_count} todo sync states")
        return migrated_count

def verify_migration(db: DatabaseManager):
    """Verify the migration was successful."""
    logger.info("🔍 Verifying migration...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Count records in unified sync_state by source type
        cursor.execute('''
            SELECT source_table, sync_target, COUNT(*) as count
            FROM sync_state
            GROUP BY source_table, sync_target
            ORDER BY source_table
        ''')
        unified_counts = cursor.fetchall()
        
        # Count original tables for comparison
        cursor.execute('SELECT COUNT(*) FROM notion_notebook_sync')
        original_notebooks = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM notion_page_sync')
        original_pages = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM notion_todo_sync')
        original_todos = cursor.fetchone()[0]
        
        logger.info("📊 Migration verification:")
        logger.info(f"   Original tables:")
        logger.info(f"     - notion_notebook_sync: {original_notebooks}")
        logger.info(f"     - notion_page_sync: {original_pages}")
        logger.info(f"     - notion_todo_sync: {original_todos}")
        logger.info(f"   Unified sync_state:")
        
        total_migrated = 0
        for source_table, sync_target, count in unified_counts:
            logger.info(f"     - {source_table} → {sync_target}: {count}")
            total_migrated += count
        
        expected_total = original_notebooks + original_pages + original_todos
        
        if total_migrated == expected_total:
            logger.info(f"   ✅ Migration successful: {total_migrated}/{expected_total} records")
            return True
        else:
            logger.warning(f"   ⚠️  Partial migration: {total_migrated}/{expected_total} records")
            return False

def create_sample_changelog_entries(db: DatabaseManager):
    """Create some sample changelog entries for testing."""
    logger.info("📝 Creating sample changelog entries...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Add a few sample changelog entries to demonstrate the system
        sample_changes = [
            ('notebooks', 'sample-notebook-uuid', 'UPDATE', 'Example notebook content update'),
            ('pages', 'sample-notebook-uuid|1', 'INSERT', 'New page added'),
            ('todos', '999', 'UPDATE', 'Todo text modified'),
        ]
        
        for source_table, source_id, operation, description in sample_changes:
            cursor.execute('''
                INSERT INTO sync_changelog (
                    source_table, source_id, operation, 
                    trigger_source, process_status
                ) VALUES (?, ?, ?, ?, ?)
            ''', (source_table, source_id, operation, 'migration_test', 'pending'))
        
        conn.commit()
        logger.info(f"   ✅ Created {len(sample_changes)} sample changelog entries")

def main():
    setup_logging()
    global logger
    logger = logging.getLogger(__name__)
    
    logger.info("🔄 Starting migration to unified sync schema...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    # Check if unified schema exists
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name IN ('sync_state', 'sync_changelog')
        ''')
        unified_tables = [row[0] for row in cursor.fetchall()]
    
    if len(unified_tables) != 2:
        logger.error("❌ Unified schema not found. Run add_unified_sync_schema.py first.")
        return 1
    
    try:
        # Perform migrations
        total_migrated = 0
        total_migrated += migrate_notebook_sync_states(db)
        total_migrated += migrate_page_sync_states(db)  
        total_migrated += migrate_todo_sync_states(db)
        
        # Verify migration
        migration_success = verify_migration(db)
        
        # Add sample changelog entries
        create_sample_changelog_entries(db)
        
        if migration_success:
            logger.info("")
            logger.info("🎉 Migration completed successfully!")
            logger.info(f"   Migrated {total_migrated} sync state records to unified schema")
            logger.info("")
            logger.info("🎯 Next Steps:")
            logger.info("   1. Existing sync continues using original tables")
            logger.info("   2. New sync logic can use unified schema")
            logger.info("   3. Gradually transition to unified approach")
            logger.info("   4. Create backward compatibility views")
            logger.info("")
            logger.info("ℹ️  Non-breaking: All original sync tables remain unchanged")
            return 0
        else:
            logger.error("❌ Migration verification failed")
            return 1
        
    except Exception as e:
        logger.error(f"❌ Error during migration: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())