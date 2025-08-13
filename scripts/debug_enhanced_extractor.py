#!/usr/bin/env python3
"""
Debug script to figure out why no database is being created.
This will trace through the execution step by step.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

def debug_enhanced_extractor(directory_path: str):
    """Debug the enhanced extractor execution step by step."""
    print("🐛 Debug Enhanced Extractor Execution")
    print("=" * 40)
    
    # Step 1: Check imports
    print("\n1️⃣ Testing imports...")
    try:
        project_root = Path(__file__).parent
        sys.path.insert(0, str(project_root))
        
        from src.processors.enhanced_highlight_extractor import (
            EnhancedHighlightExtractor,
            DatabaseManager,
            process_directory_enhanced
        )
        print("✅ Enhanced extractor imported successfully")
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        print("   Make sure enhanced_highlight_extractor.py is in src/processors/")
        return False
    
    # Step 2: Check directory structure
    print(f"\n2️⃣ Checking directory: {directory_path}")
    if not os.path.exists(directory_path):
        print(f"❌ Directory not found: {directory_path}")
        return False
    
    # Find files
    content_files = []
    epub_files = []
    rm_files = []
    
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            file_path = os.path.join(root, file)
            if file.endswith('.content'):
                content_files.append(file_path)
            elif file.endswith('.epub'):
                epub_files.append(file_path)
            elif file.endswith('.rm'):
                rm_files.append(file_path)
    
    print(f"   📄 Found {len(content_files)} .content files")
    print(f"   📚 Found {len(epub_files)} .epub files")
    print(f"   📝 Found {len(rm_files)} .rm files")
    
    if not content_files:
        print("❌ No .content files found!")
        return False
    
    # Step 3: Test database creation
    print(f"\n3️⃣ Testing database creation...")
    test_db_path = "debug_test.db"
    
    try:
        db_manager = DatabaseManager(test_db_path)
        print(f"✅ DatabaseManager created")
        print(f"   Database path: {os.path.abspath(test_db_path)}")
        
        # Test connection
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, test_text TEXT)")
        cursor.execute("INSERT INTO test_table (test_text) VALUES ('test')")
        conn.commit()
        conn.close()
        
        if os.path.exists(test_db_path):
            size = os.path.getsize(test_db_path)
            print(f"✅ Test database created successfully ({size} bytes)")
            os.remove(test_db_path)  # Clean up
        else:
            print("❌ Test database was not created")
            return False
            
    except Exception as e:
        print(f"❌ Database creation failed: {e}")
        return False
    
    # Step 4: Test enhanced extractor initialization
    print(f"\n4️⃣ Testing enhanced extractor...")
    try:
        db_manager = DatabaseManager("debug_enhanced.db")
        extractor = EnhancedHighlightExtractor(db_manager.get_connection(), enable_epub_matching=False)
        print("✅ Enhanced extractor initialized")
    except Exception as e:
        print(f"❌ Enhanced extractor initialization failed: {e}")
        return False
    
    # Step 5: Test file processing capability
    print(f"\n5️⃣ Testing file processing...")
    processable_files = []
    
    for content_file in content_files[:3]:  # Test first 3 files
        try:
            can_process = extractor.can_process(content_file)
            file_name = os.path.basename(content_file)
            
            if can_process:
                print(f"   ✅ Can process: {file_name}")
                processable_files.append(content_file)
            else:
                print(f"   ❌ Cannot process: {file_name}")
                
                # Debug why it can't be processed
                try:
                    with open(content_file, 'r') as f:
                        content_data = json.load(f)
                    file_type = content_data.get('fileType', 'unknown')
                    print(f"      File type: {file_type}")
                    
                    if file_type not in ['pdf', 'epub']:
                        print(f"      Reason: Unsupported file type")
                    else:
                        print(f"      Reason: Unknown (file type is supported)")
                        
                except Exception as e:
                    print(f"      Reason: Could not read content file: {e}")
                    
        except Exception as e:
            print(f"   ❌ Error checking {os.path.basename(content_file)}: {e}")
    
    if not processable_files:
        print("❌ No processable files found!")
        return False
    
    # Step 6: Test actual processing
    print(f"\n6️⃣ Testing actual processing...")
    test_file = processable_files[0]
    print(f"   Processing: {os.path.basename(test_file)}")
    
    try:
        result = extractor.process_file(test_file)
        
        if result.success:
            highlight_count = len(result.data.get('highlights', []))
            print(f"   ✅ Processing successful: {highlight_count} highlights extracted")
            
            if highlight_count == 0:
                print("   ⚠️  No highlights found - this might be normal if file has no highlights")
            
        else:
            print(f"   ❌ Processing failed: {result.error_message}")
            return False
            
    except Exception as e:
        print(f"   ❌ Processing error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 7: Test process_directory_enhanced
    print(f"\n7️⃣ Testing process_directory_enhanced...")
    final_db_path = "debug_final_test.db"
    
    try:
        print(f"   Database will be created at: {os.path.abspath(final_db_path)}")
        
        db_manager = DatabaseManager(final_db_path)
        results = process_directory_enhanced(directory_path, db_manager, enable_epub_matching=False)
        
        total_highlights = sum(results.values())
        print(f"   ✅ process_directory_enhanced completed")
        print(f"   📊 Results: {total_highlights} highlights from {len(results)} files")
        
        # Check if database was actually created
        if os.path.exists(final_db_path):
            size = os.path.getsize(final_db_path)
            print(f"   ✅ Database created: {final_db_path} ({size} bytes)")
            
            # Check database contents
            import sqlite3
            with sqlite3.connect(final_db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                print(f"   📋 Tables in database: {tables}")
                
                if 'enhanced_highlights' in tables:
                    cursor.execute("SELECT COUNT(*) FROM enhanced_highlights")
                    db_count = cursor.fetchone()[0]
                    print(f"   💾 Highlights in database: {db_count}")
                else:
                    print("   ⚠️  No enhanced_highlights table found")
            
        else:
            print(f"   ❌ Database was not created at: {final_db_path}")
            return False
            
    except Exception as e:
        print(f"   ❌ process_directory_enhanced failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"\n🎉 Debug completed successfully!")
    print(f"   Database location: {os.path.abspath(final_db_path)}")
    
    # Clean up
    cleanup = input("\nClean up debug database? [Y/n]: ").strip().lower()
    if cleanup != 'n':
        if os.path.exists(final_db_path):
            os.remove(final_db_path)
            print("🧹 Debug database cleaned up")
    
    return True


def main():
    """Main debug runner."""
    print("🐛 Enhanced Highlight Extractor Debug Tool")
    print("=" * 45)
    
    if len(sys.argv) < 2:
        print("Usage: python debug_enhanced_extractor.py <directory_path>")
        print("  directory_path: Directory containing .content files")
        
        # Try to find test directories
        possible_dirs = ["test_data", "data", "../test_data"]
        found = False
        
        for test_dir in possible_dirs:
            if os.path.exists(test_dir):
                content_files = []
                for root, _, files in os.walk(test_dir):
                    content_files.extend([f for f in files if f.endswith('.content')])
                
                if content_files:
                    print(f"\n💡 Found test directory: {test_dir} ({len(content_files)} .content files)")
                    print(f"   Try: python debug_enhanced_extractor.py {test_dir}")
                    found = True
        
        if not found:
            print("\n💡 No test directories found. Please specify a directory with .content files.")
        
        return
    
    directory_path = sys.argv[1]
    
    success = debug_enhanced_extractor(directory_path)
    
    if success:
        print(f"\n✅ Enhanced extractor is working correctly!")
        print(f"   The issue may be with how you're running it normally.")
        print(f"   Try the exact same command that worked in this debug.")
    else:
        print(f"\n❌ Found issues with enhanced extractor!")
        print(f"   Check the error messages above to fix the problems.")


if __name__ == "__main__":
    main()
