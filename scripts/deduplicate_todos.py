#!/usr/bin/env python3
"""
Remove duplicate todos that were created from multiple processing runs.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager

def analyze_duplicates():
    """Analyze the extent of todo duplicates."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        print("🔍 Analyzing todo duplicates...\n")
        
        # Find potential duplicates by grouping identical content
        cursor.execute('''
            SELECT 
                notebook_uuid, page_number, text, actual_date,
                COUNT(*) as duplicate_count,
                GROUP_CONCAT(id) as todo_ids,
                MIN(created_at) as first_created,
                MAX(created_at) as last_created
            FROM todos
            WHERE text IS NOT NULL AND text != ''
            GROUP BY notebook_uuid, page_number, text, actual_date
            HAVING COUNT(*) > 1
            ORDER BY duplicate_count DESC
        ''')
        
        duplicates = cursor.fetchall()
        
        print(f"📊 Found {len(duplicates)} groups of duplicate todos")
        
        total_duplicates = 0
        total_to_keep = 0
        
        for notebook_uuid, page_num, text, date, count, ids, first, last in duplicates[:10]:
            total_duplicates += count - 1  # Keep one, remove the rest
            total_to_keep += 1
            
            # Get notebook name
            cursor.execute('SELECT visible_name FROM notebook_metadata WHERE notebook_uuid = ?', (notebook_uuid,))
            notebook_name = cursor.fetchone()
            notebook_name = notebook_name[0] if notebook_name else "Unknown"
            
            print(f"📝 {notebook_name}, Page {page_num} ({date})")
            print(f"   \"{text[:60]}...\"")
            print(f"   💥 {count} duplicates (IDs: {ids})")
            print(f"   📅 First: {first}, Last: {last}")
            print()
        
        if len(duplicates) > 10:
            print(f"   ... and {len(duplicates) - 10} more duplicate groups")
            for _, _, _, _, count, _, _, _ in duplicates[10:]:
                total_duplicates += count - 1
                total_to_keep += 1
        
        print(f"📈 SUMMARY:")
        print(f"   Total todo entries: {get_total_todos(cursor)}")
        print(f"   Duplicate entries to remove: {total_duplicates}")
        print(f"   Unique todos to keep: {total_to_keep + get_unique_todos(cursor)}")
        print(f"   Reduction: {total_duplicates}/{get_total_todos(cursor)} ({total_duplicates/get_total_todos(cursor)*100:.1f}%)")

def get_total_todos(cursor):
    """Get total todo count."""
    cursor.execute('SELECT COUNT(*) FROM todos')
    return cursor.fetchone()[0]

def get_unique_todos(cursor):
    """Get count of already unique todos."""
    cursor.execute('''
        SELECT COUNT(*)
        FROM (
            SELECT notebook_uuid, page_number, text, actual_date
            FROM todos
            WHERE text IS NOT NULL AND text != ''
            GROUP BY notebook_uuid, page_number, text, actual_date
            HAVING COUNT(*) = 1
        )
    ''')
    return cursor.fetchone()[0]

def remove_duplicates(dry_run=True):
    """Remove duplicate todos, keeping the earliest created_at entry."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        print(f"🧹 {'DRY RUN: ' if dry_run else ''}Removing duplicate todos...")
        print(f"Strategy: Keep the EARLIEST created entry for each unique todo\n")
        
        # Find IDs to delete (keep MIN(id) for each group)
        cursor.execute('''
            SELECT 
                GROUP_CONCAT(id) as all_ids,
                MIN(id) as keep_id,
                COUNT(*) as total_count,
                notebook_uuid, page_number, text, actual_date
            FROM todos
            WHERE text IS NOT NULL AND text != ''
            GROUP BY notebook_uuid, page_number, text, actual_date
            HAVING COUNT(*) > 1
        ''')
        
        duplicate_groups = cursor.fetchall()
        ids_to_delete = []
        
        print(f"📋 Processing {len(duplicate_groups)} duplicate groups...")
        
        for all_ids, keep_id, count, notebook_uuid, page_num, text, date in duplicate_groups:
            # Parse the comma-separated IDs and remove the one we're keeping
            id_list = [int(x) for x in all_ids.split(',')]
            to_delete = [x for x in id_list if x != keep_id]
            ids_to_delete.extend(to_delete)
            
            if not dry_run:
                # Get notebook name for logging
                cursor.execute('SELECT visible_name FROM notebook_metadata WHERE notebook_uuid = ?', (notebook_uuid,))
                notebook_name = cursor.fetchone()
                notebook_name = notebook_name[0] if notebook_name else "Unknown"
                
                print(f"  Keeping ID {keep_id}, removing {len(to_delete)} duplicates")
                print(f"    {notebook_name}, Page {page_num}: \"{text[:50]}...\"")
        
        print(f"\n📊 Summary:")
        print(f"   Duplicate groups found: {len(duplicate_groups)}")
        print(f"   Todo IDs to delete: {len(ids_to_delete)}")
        
        if not dry_run and ids_to_delete:
            # Actually delete the duplicates
            id_placeholders = ','.join(['?'] * len(ids_to_delete))
            cursor.execute(f'DELETE FROM todos WHERE id IN ({id_placeholders})', ids_to_delete)
            conn.commit()
            
            print(f"✅ Deleted {len(ids_to_delete)} duplicate todo entries")
            print(f"📊 Remaining todos: {get_total_todos(cursor)}")
        
        elif dry_run:
            print(f"🧪 DRY RUN - No changes made")
            print(f"💡 To actually remove duplicates, run: remove_duplicates(dry_run=False)")

def main():
    print("🔍 Todo Deduplication Analysis\n")
    
    # First analyze the problem
    analyze_duplicates()
    
    print("\n" + "="*60)
    print("🧹 DEDUPLICATION PREVIEW")
    print("="*60)
    
    # Show what would be removed (dry run)
    remove_duplicates(dry_run=True)

if __name__ == '__main__':
    main()