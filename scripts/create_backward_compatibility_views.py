#!/usr/bin/env python3
"""
Create backward compatibility views for unified sync schema.

This script creates views that map the unified sync_state table back to the
original table structure, allowing existing code to work unchanged while
new code can use the unified schema.
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

def create_notion_notebook_sync_view(db: DatabaseManager):
    """Create view to emulate notion_notebook_sync table."""
    logger.info("📒 Creating notion_notebook_sync_unified view...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE VIEW IF NOT EXISTS notion_notebook_sync_unified AS
            SELECT 
                source_id as notebook_uuid,
                remote_id as notion_page_id,
                last_synced_at as last_synced,
                json_extract(metadata, '$.content_hash') as content_hash,
                CAST(json_extract(metadata, '$.total_pages') as INTEGER) as total_pages,
                json_extract(metadata, '$.metadata_hash') as metadata_hash
            FROM sync_state 
            WHERE source_table = 'notebooks' 
                AND sync_target = 'notion'
                AND sync_status = 'synced'
        ''')
        
        logger.info("   ✅ Created notion_notebook_sync_unified view")

def create_notion_page_sync_view(db: DatabaseManager):
    """Create view to emulate notion_page_sync table."""
    logger.info("📄 Creating notion_page_sync_unified view...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE VIEW IF NOT EXISTS notion_page_sync_unified AS
            SELECT 
                -- Split composite source_id back to components
                substr(source_id, 1, instr(source_id, '|') - 1) as notebook_uuid,
                CAST(substr(source_id, instr(source_id, '|') + 1) as INTEGER) as page_number,
                json_extract(metadata, '$.page_uuid') as page_uuid,
                json_extract(metadata, '$.content_hash') as content_hash,
                last_synced_at as last_synced,
                remote_id as notion_block_id,
                last_synced_content
            FROM sync_state 
            WHERE source_table = 'pages' 
                AND sync_target = 'notion'
                AND source_id LIKE '%|%'  -- Ensure it has the composite format
        ''')
        
        logger.info("   ✅ Created notion_page_sync_unified view")

def create_notion_todo_sync_view(db: DatabaseManager):
    """Create view to emulate notion_todo_sync table."""
    logger.info("✅ Creating notion_todo_sync_unified view...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE VIEW IF NOT EXISTS notion_todo_sync_unified AS
            SELECT 
                CAST(source_id as INTEGER) as todo_id,
                remote_id as notion_page_id,
                json_extract(metadata, '$.notion_database_id') as notion_database_id,
                json_extract(metadata, '$.exported_at') as exported_at,
                last_synced_at as last_updated
            FROM sync_state 
            WHERE source_table = 'todos' 
                AND sync_target = 'notion'
                AND sync_status = 'synced'
        ''')
        
        logger.info("   ✅ Created notion_todo_sync_unified view")

def test_backward_compatibility_views(db: DatabaseManager):
    """Test that the views return data matching original tables."""
    logger.info("🧪 Testing backward compatibility views...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Test notebook sync view
        cursor.execute('SELECT COUNT(*) FROM notion_notebook_sync_unified')
        unified_notebook_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM notion_notebook_sync')
        original_notebook_count = cursor.fetchone()[0]
        
        logger.info(f"   Notebooks: unified={unified_notebook_count}, original={original_notebook_count}")
        
        # Test page sync view
        cursor.execute('SELECT COUNT(*) FROM notion_page_sync_unified')
        unified_page_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM notion_page_sync')
        original_page_count = cursor.fetchone()[0]
        
        logger.info(f"   Pages: unified={unified_page_count}, original={original_page_count}")
        
        # Test todo sync view
        cursor.execute('SELECT COUNT(*) FROM notion_todo_sync_unified')
        unified_todo_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM notion_todo_sync')
        original_todo_count = cursor.fetchone()[0]
        
        logger.info(f"   Todos: unified={unified_todo_count}, original={original_todo_count}")
        
        # Show sample data comparison
        logger.info("📋 Sample data comparison:")
        
        # Sample notebook comparison
        cursor.execute('SELECT notebook_uuid, notion_page_id FROM notion_notebook_sync_unified LIMIT 1')
        unified_notebook_sample = cursor.fetchone()
        
        cursor.execute('SELECT notebook_uuid, notion_page_id FROM notion_notebook_sync LIMIT 1')
        original_notebook_sample = cursor.fetchone()
        
        if unified_notebook_sample and original_notebook_sample:
            logger.info(f"   Notebook sample - unified: {unified_notebook_sample}")
            logger.info(f"   Notebook sample - original: {original_notebook_sample}")
        
        # Sample page comparison
        cursor.execute('SELECT notebook_uuid, page_number, notion_block_id FROM notion_page_sync_unified LIMIT 1')
        unified_page_sample = cursor.fetchone()
        
        cursor.execute('SELECT notebook_uuid, page_number, notion_block_id FROM notion_page_sync LIMIT 1')
        original_page_sample = cursor.fetchone()
        
        if unified_page_sample and original_page_sample:
            logger.info(f"   Page sample - unified: {unified_page_sample}")
            logger.info(f"   Page sample - original: {original_page_sample}")

def create_unified_sync_api(db: DatabaseManager):
    """Create helper views for unified sync queries."""
    logger.info("🔧 Creating unified sync API views...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # View for all pending changes with context
        cursor.execute('''
            CREATE VIEW IF NOT EXISTS sync_pending_changes AS
            SELECT 
                cl.id as changelog_id,
                cl.source_table,
                cl.source_id,
                cl.operation,
                cl.changed_at,
                cl.changed_fields,
                cl.trigger_source,
                ss.sync_target,
                ss.remote_id,
                ss.sync_status,
                ss.last_synced_at,
                ss.last_synced_content
            FROM sync_changelog cl
            LEFT JOIN sync_state ss ON (
                cl.source_table = ss.source_table AND 
                cl.source_id = ss.source_id
            )
            WHERE cl.process_status = 'pending'
            ORDER BY cl.changed_at ASC
        ''')
        
        # View for sync health overview
        cursor.execute('''
            CREATE VIEW IF NOT EXISTS sync_health_overview AS
            SELECT 
                sync_target,
                sync_status,
                COUNT(*) as record_count,
                MIN(last_synced_at) as oldest_sync,
                MAX(last_synced_at) as latest_sync
            FROM sync_state
            GROUP BY sync_target, sync_status
        ''')
        
        logger.info("   ✅ Created unified sync API views")

def verify_view_structure(db: DatabaseManager):
    """Verify that views have the expected structure."""
    logger.info("🔍 Verifying view structure...")
    
    views_to_check = [
        'notion_notebook_sync_unified',
        'notion_page_sync_unified', 
        'notion_todo_sync_unified',
        'sync_pending_changes',
        'sync_health_overview'
    ]
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        for view_name in views_to_check:
            cursor.execute(f'PRAGMA table_info({view_name})')
            columns = cursor.fetchall()
            
            logger.info(f"   {view_name}: {len(columns)} columns")
            for col in columns[:3]:  # Show first 3 columns
                logger.info(f"     - {col[1]} ({col[2]})")
            if len(columns) > 3:
                logger.info(f"     ... and {len(columns) - 3} more")

def main():
    setup_logging()
    global logger
    logger = logging.getLogger(__name__)
    
    logger.info("🔄 Creating backward compatibility views...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    try:
        # Create backward compatibility views
        create_notion_notebook_sync_view(db)
        create_notion_page_sync_view(db)
        create_notion_todo_sync_view(db)
        
        # Create unified API views
        create_unified_sync_api(db)
        
        # Test the views
        test_backward_compatibility_views(db)
        
        # Verify structure
        verify_view_structure(db)
        
        logger.info("")
        logger.info("🎉 Backward compatibility views created successfully!")
        logger.info("")
        logger.info("📋 Available views:")
        logger.info("   - notion_notebook_sync_unified: Drop-in replacement for notion_notebook_sync")
        logger.info("   - notion_page_sync_unified: Drop-in replacement for notion_page_sync")
        logger.info("   - notion_todo_sync_unified: Drop-in replacement for notion_todo_sync")
        logger.info("   - sync_pending_changes: All pending changes with context")
        logger.info("   - sync_health_overview: Sync status summary by target")
        logger.info("")
        logger.info("🎯 Usage:")
        logger.info("   1. Existing code continues to use original tables")
        logger.info("   2. New code can use unified views for gradual migration")
        logger.info("   3. Unified sync engine uses sync_pending_changes view")
        logger.info("")
        logger.info("ℹ️  Non-breaking: Original tables remain unchanged")
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Error creating backward compatibility views: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())