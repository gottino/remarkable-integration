#!/usr/bin/env python3
"""
Fix todo deduplication by adding unique constraints and cleaning existing duplicates.

When pages are reprocessed, todos get inserted multiple times. This script:
1. Identifies and removes duplicate todos
2. Adds unique constraint to prevent future duplicates  
3. Updates the extraction logic to use INSERT OR REPLACE
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

def analyze_duplicates(db: DatabaseManager):
    """Analyze existing todo duplicates."""
    logger.info("🔍 Analyzing todo duplicates...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Count total todos
        cursor.execute('SELECT COUNT(*) FROM todos')
        total_todos = cursor.fetchone()[0]
        
        # Find duplicates by content and location
        cursor.execute('''
            SELECT 
                notebook_uuid, page_number, text, 
                COUNT(*) as duplicate_count,
                MIN(id) as keep_id,
                GROUP_CONCAT(id) as all_ids
            FROM todos 
            GROUP BY notebook_uuid, page_number, text
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC
        ''')
        
        duplicates = cursor.fetchall()
        
        logger.info(f"📊 Analysis results:")
        logger.info(f"   Total todos: {total_todos:,}")
        logger.info(f"   Duplicate groups: {len(duplicates)}")
        
        total_duplicates = sum(count - 1 for _, _, _, count, _, _ in duplicates)
        logger.info(f"   Duplicate todos to remove: {total_duplicates}")
        
        if duplicates:
            logger.info(f"📋 Top duplicate groups:")
            for i, (notebook_uuid, page_number, text, count, keep_id, all_ids) in enumerate(duplicates[:5]):
                logger.info(f"   {i+1}. Page {page_number}: \"{text[:50]}...\" ({count} duplicates)")
                logger.info(f"      Keep ID: {keep_id}, Remove IDs: {all_ids}")
        
        return duplicates, total_duplicates

def remove_duplicates(db: DatabaseManager, duplicates):
    """Remove duplicate todos, keeping the earliest one and cleaning up sync records."""
    logger.info("🗑️  Removing duplicate todos...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        removed_count = 0
        sync_records_removed = 0
        
        for notebook_uuid, page_number, text, duplicate_count, keep_id, all_ids in duplicates:
            # Parse all IDs and remove the one we want to keep
            all_id_list = [int(x) for x in all_ids.split(',')]
            ids_to_remove = [x for x in all_id_list if x != keep_id]
            
            if ids_to_remove:
                # First, remove sync records for duplicate todos
                placeholders = ','.join(['?'] * len(ids_to_remove))
                cursor.execute(f'DELETE FROM notion_todo_sync WHERE todo_id IN ({placeholders})', ids_to_remove)
                sync_records_removed += cursor.rowcount
                
                # Also remove from unified sync_state if present
                str_ids = [str(x) for x in ids_to_remove]
                cursor.execute(f'''
                    DELETE FROM sync_state 
                    WHERE source_table = 'todos' AND source_id IN ({placeholders})
                ''', str_ids)
                
                # Now remove the duplicate todos
                cursor.execute(f'DELETE FROM todos WHERE id IN ({placeholders})', ids_to_remove)
                removed_count += cursor.rowcount
        
        conn.commit()
        logger.info(f"   ✅ Removed {removed_count} duplicate todos")
        logger.info(f"   ✅ Removed {sync_records_removed} associated sync records")
        
        return removed_count

def add_unique_constraint(db: DatabaseManager):
    """Add unique constraint to todos table to prevent future duplicates."""
    logger.info("🔧 Adding unique constraint to todos table...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if unique constraint already exists
        cursor.execute('PRAGMA index_list(todos)')
        indexes = cursor.fetchall()
        
        unique_constraint_exists = False
        for index in indexes:
            if index[2] == 1:  # unique index
                cursor.execute(f'PRAGMA index_info({index[1]})')
                cols = cursor.fetchall()
                col_names = [col[2] for col in cols]
                if set(col_names) == {'notebook_uuid', 'page_number', 'text'}:
                    unique_constraint_exists = True
                    break
        
        if unique_constraint_exists:
            logger.info("   ⚠️  Unique constraint already exists")
            return True
        
        try:
            # Create unique index on the natural key
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_todos_unique_content
                ON todos(notebook_uuid, page_number, text)
            ''')
            
            conn.commit()
            logger.info("   ✅ Added unique constraint on (notebook_uuid, page_number, text)")
            return True
            
        except Exception as e:
            logger.error(f"   ❌ Failed to add unique constraint: {e}")
            return False

def test_constraint(db: DatabaseManager):
    """Test that the unique constraint works."""
    logger.info("🧪 Testing unique constraint...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        try:
            # Try to insert a duplicate (should fail)
            cursor.execute('''
                INSERT INTO todos 
                (notebook_uuid, page_number, text, completed, confidence, created_at, source_file, title)
                VALUES ('test-uuid', '1', 'Test duplicate todo', 0, 1.0, CURRENT_TIMESTAMP, 'test.rm', 'Test')
            ''')
            
            # Try to insert the same thing again (should fail)
            cursor.execute('''
                INSERT INTO todos 
                (notebook_uuid, page_number, text, completed, confidence, created_at, source_file, title)
                VALUES ('test-uuid', '1', 'Test duplicate todo', 0, 1.0, CURRENT_TIMESTAMP, 'test.rm', 'Test')
            ''')
            
            logger.error("   ❌ Unique constraint not working - duplicates allowed")
            return False
            
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                logger.info("   ✅ Unique constraint working correctly")
                
                # Clean up test record
                cursor.execute('''
                    DELETE FROM todos 
                    WHERE notebook_uuid = 'test-uuid' AND page_number = '1' AND text = 'Test duplicate todo'
                ''')
                conn.commit()
                return True
            else:
                logger.error(f"   ❌ Unexpected error: {e}")
                return False

def show_updated_logic_example():
    """Show how to update the extraction logic."""
    logger.info("📝 Updated extraction logic example:")
    logger.info('''
    # OLD (creates duplicates):
    cursor.execute("""
        INSERT INTO todos 
        (notebook_uuid, page_number, text, completed, confidence, created_at, actual_date)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
    """, (notebook_uuid, page_number, text, completed, confidence, actual_date))
    
    # NEW (prevents duplicates):
    cursor.execute("""
        INSERT OR REPLACE INTO todos 
        (notebook_uuid, page_number, text, completed, confidence, created_at, actual_date)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
    """, (notebook_uuid, page_number, text, completed, confidence, actual_date))
    
    # Even better - check if exists first:
    cursor.execute("""
        INSERT INTO todos 
        (notebook_uuid, page_number, text, completed, confidence, created_at, actual_date)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(notebook_uuid, page_number, text) DO UPDATE SET
            completed = excluded.completed,
            confidence = excluded.confidence,
            actual_date = excluded.actual_date,
            updated_at = CURRENT_TIMESTAMP
    """, (notebook_uuid, page_number, text, completed, confidence, actual_date))
    ''')

def main():
    setup_logging()
    global logger
    logger = logging.getLogger(__name__)
    
    logger.info("🚀 Fixing todo deduplication...")
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    if not os.path.exists(db_path):
        logger.error(f"Database not found: {db_path}")
        return 1
    
    db = DatabaseManager(db_path)
    logger.info(f"Connected to database: {db_path}")
    
    try:
        # Step 1: Analyze duplicates
        duplicates, total_duplicate_count = analyze_duplicates(db)
        
        if total_duplicate_count == 0:
            logger.info("✅ No duplicates found - todos table is clean!")
        else:
            # Step 2: Remove duplicates
            removed_count = remove_duplicates(db, duplicates)
            logger.info(f"🧹 Cleaned up {removed_count} duplicate todos")
        
        # Step 3: Add unique constraint
        constraint_added = add_unique_constraint(db)
        
        if constraint_added:
            # Step 4: Test constraint
            constraint_works = test_constraint(db)
            
            if constraint_works:
                logger.info("")
                logger.info("🎉 Todo deduplication fix completed successfully!")
                logger.info("")
                logger.info("📋 Summary:")
                logger.info(f"   - Removed {total_duplicate_count} duplicate todos")
                logger.info("   - Added unique constraint on (notebook_uuid, page_number, text)")
                logger.info("   - Future todo extractions will automatically prevent duplicates")
                logger.info("")
                
                # Show code example
                show_updated_logic_example()
                
                logger.info("")
                logger.info("🎯 Next: Update extraction logic to use INSERT OR REPLACE")
                return 0
            else:
                logger.error("❌ Constraint test failed")
                return 1
        else:
            logger.error("❌ Failed to add unique constraint")
            return 1
        
    except Exception as e:
        logger.error(f"❌ Error fixing todo deduplication: {e}")
        return 1

if __name__ == '__main__':
    sys.exit(main())