#!/usr/bin/env python3
"""
Migration script to populate .rm file hashes for existing database records.

This script calculates and stores .rm file content hashes for all records
that were processed before the rsync timestamp issue (August 29th, 11am).
This enables proper hash-based incremental processing.
"""

import sys
import os
import hashlib
from pathlib import Path
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import DatabaseManager

def calculate_rm_file_hash(rm_file_path: str) -> str:
    """Calculate hash of .rm file content."""
    try:
        with open(rm_file_path, 'rb') as f:
            content = f.read()
        return hashlib.sha256(content).hexdigest()
    except Exception as e:
        print(f"  ❌ Error calculating hash for {rm_file_path}: {e}")
        return ""

def main():
    print("🔄 Migrating Page Content Hashes")
    print("=" * 50)
    print()
    
    # Set cutoff time - August 29th, 11am (when full processing completed)
    cutoff_time = datetime(2025, 8, 29, 11, 0, 0)
    print("🔄 Replacing ALL OCR text hashes with .rm file content hashes")
    print("   (This ensures proper hash-based incremental processing)")
    print()
    
    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    db_manager = DatabaseManager(db_path)
    
    # Set data directory
    data_directory = './data/remarkable_sync'
    
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Find ALL records to replace OCR hashes with .rm file hashes
        cursor.execute('''
            SELECT DISTINCT notebook_uuid, page_uuid, page_number, created_at, notebook_name
            FROM notebook_text_extractions
            ORDER BY notebook_name, page_number
        ''')
        
        records_to_update = cursor.fetchall()
        total_records = len(records_to_update)
        
        print(f"📊 Found {total_records} records to update with .rm file hashes")
        
        print()
        updated_count = 0
        error_count = 0
        
        # Group by notebook for better progress reporting
        current_notebook = None
        notebook_count = 0
        
        for record in records_to_update:
            notebook_uuid, page_uuid, page_number, created_at, notebook_name = record
            
            if notebook_name != current_notebook:
                current_notebook = notebook_name
                notebook_count += 1
                print(f"📓 {notebook_count}. Processing {notebook_name}...")
            
            # Find the .rm file
            rm_file_path = os.path.join(data_directory, notebook_uuid, f"{page_uuid}.rm")
            
            if not os.path.exists(rm_file_path):
                print(f"  ⚠️  Page {page_number}: .rm file not found")
                error_count += 1
                continue
            
            # Calculate hash
            file_hash = calculate_rm_file_hash(rm_file_path)
            if not file_hash:
                error_count += 1
                continue
            
            # Update the database record
            try:
                cursor.execute('''
                    UPDATE notebook_text_extractions 
                    SET page_content_hash = ?
                    WHERE notebook_uuid = ? AND page_uuid = ? AND page_number = ?
                ''', (file_hash, notebook_uuid, page_uuid, page_number))
                
                updated_count += 1
                
                if updated_count % 10 == 0:
                    print(f"  ✅ Updated {updated_count}/{total_records} records...")
                    
            except Exception as e:
                print(f"  ❌ Error updating record for page {page_number}: {e}")
                error_count += 1
        
        # Commit all changes
        conn.commit()
        
        print()
        print(f"🎉 Migration complete!")
        print(f"   ✅ Updated: {updated_count} records")
        print(f"   ❌ Errors: {error_count} records")
        print(f"   📊 Success rate: {updated_count/(updated_count+error_count)*100:.1f}%")
        print()
        
        # Verify the migration
        cursor.execute('''
            SELECT COUNT(*) FROM notebook_text_extractions 
            WHERE page_content_hash IS NOT NULL AND page_content_hash != ''
        ''')
        total_with_hashes = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM notebook_text_extractions')
        total_records = cursor.fetchone()[0]
        
        print(f"📈 Hash coverage: {total_with_hashes}/{total_records} records ({total_with_hashes/total_records*100:.1f}%)")
        
        if total_with_hashes > 0:
            print()
            print("✅ Hash-based incremental processing is now ready!")
            print("   The system will only process pages with changed .rm file content.")

if __name__ == "__main__":
    main()