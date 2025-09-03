#!/usr/bin/env python3
"""
Database recovery script to restore missing entries from backup database.

This script identifies entries that exist in the backup but are missing from 
the current database and restores them safely.
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

def main():
    print("🔧 Database Recovery from Backup")
    print("=" * 50)
    print()
    
    # Database paths
    current_db = './data/remarkable_pipeline.db'
    backup_db = './data/backups/remarkable_pipeline_backup_20250829_115146.db'
    
    print(f"📂 Current database: {current_db}")
    print(f"📂 Backup database: {backup_db}")
    print()
    
    # First, analyze what's missing
    print("🔍 Analyzing missing entries...")
    
    with sqlite3.connect(backup_db) as backup_conn:
        with sqlite3.connect(current_db) as current_conn:
            backup_cursor = backup_conn.cursor()
            current_cursor = current_conn.cursor()
            
            # Get all entries from backup
            backup_cursor.execute('''
                SELECT notebook_uuid, page_uuid, page_number, notebook_name,
                       text, confidence, bounding_box, language, created_at
                FROM notebook_text_extractions
                ORDER BY notebook_name, page_number
            ''')
            backup_entries = backup_cursor.fetchall()
            
            print(f"📊 Backup database has {len(backup_entries)} total entries")
            
            # Check which ones are missing from current
            missing_entries = []
            existing_count = 0
            
            for entry in backup_entries:
                notebook_uuid, page_uuid, page_number = entry[0], entry[1], entry[2]
                
                # Check if this entry exists in current database
                current_cursor.execute('''
                    SELECT COUNT(*) FROM notebook_text_extractions 
                    WHERE notebook_uuid = ? AND page_uuid = ? AND page_number = ?
                ''', (notebook_uuid, page_uuid, page_number))
                
                count = current_cursor.fetchone()[0]
                if count == 0:
                    missing_entries.append(entry)
                else:
                    existing_count += 1
            
            print(f"📊 Current database has {existing_count} matching entries")
            print(f"❌ Missing entries: {len(missing_entries)}")
            print()
            
            if len(missing_entries) == 0:
                print("✅ No missing entries found - databases are in sync")
                return
            
            # Group missing entries by notebook for reporting
            notebooks_affected = {}
            for entry in missing_entries:
                notebook_name = entry[3]
                if notebook_name not in notebooks_affected:
                    notebooks_affected[notebook_name] = 0
                notebooks_affected[notebook_name] += 1
            
            print(f"📋 Affected notebooks ({len(notebooks_affected)} total):")
            for name, count in sorted(notebooks_affected.items(), key=lambda x: x[1], reverse=True):
                print(f"   {name}: {count} missing pages")
            print()
            
            # Ask for confirmation (in script context, we'll proceed)
            print("🔄 Proceeding with recovery...")
            print()
            
            # Restore missing entries
            restored_count = 0
            error_count = 0
            current_notebook = None
            
            for entry in missing_entries:
                notebook_uuid, page_uuid, page_number, notebook_name, text, confidence, bounding_box, language, created_at = entry
                
                if notebook_name != current_notebook:
                    current_notebook = notebook_name
                    print(f"📓 Restoring {notebook_name}...")
                
                try:
                    # Insert the missing entry (without page_content_hash initially)
                    current_cursor.execute('''
                        INSERT INTO notebook_text_extractions 
                        (notebook_uuid, notebook_name, page_uuid, page_number, 
                         text, confidence, bounding_box, language, created_at, page_content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        notebook_uuid,
                        notebook_name, 
                        page_uuid,
                        page_number,
                        text,
                        confidence,
                        bounding_box,
                        language,
                        created_at,
                        ""  # Empty hash - will be populated by hash migration
                    ))
                    
                    restored_count += 1
                    
                    if restored_count % 50 == 0:
                        print(f"  ✅ Restored {restored_count}/{len(missing_entries)} entries...")
                        current_conn.commit()  # Commit every 50 entries
                        
                except Exception as e:
                    print(f"  ❌ Error restoring page {page_number}: {e}")
                    error_count += 1
            
            # Final commit
            current_conn.commit()
            
            print()
            print(f"🎉 Recovery complete!")
            print(f"   ✅ Restored: {restored_count} entries")
            print(f"   ❌ Errors: {error_count} entries")
            print(f"   📊 Success rate: {restored_count/(restored_count+error_count)*100:.1f}%")
            print()
            print("⚠️  Note: Restored entries have empty page_content_hash")
            print("   Run hash migration script to populate .rm file hashes")

if __name__ == "__main__":
    main()