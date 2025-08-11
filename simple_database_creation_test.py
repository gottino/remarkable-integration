#!/usr/bin/env python3
"""
Simple test to verify database creation works at all.
"""

import os
import sys
import sqlite3
from pathlib import Path

def test_basic_database_creation():
    """Test basic database creation."""
    print("🧪 Testing Basic Database Creation")
    print("=" * 35)
    
    # Test 1: Basic SQLite
    print("\n1️⃣ Testing basic SQLite...")
    try:
        test_db = "basic_test.db"
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, text TEXT)")
        cursor.execute("INSERT INTO test (text) VALUES ('hello')")
        conn.commit()
        conn.close()
        
        if os.path.exists(test_db):
            size = os.path.getsize(test_db)
            print(f"✅ Basic SQLite works ({size} bytes)")
            print(f"   Database created at: {os.path.abspath(test_db)}")
            os.remove(test_db)
        else:
            print("❌ Basic SQLite failed - no file created")
            return False
    except Exception as e:
        print(f"❌ Basic SQLite failed: {e}")
        return False
    
    # Test 2: Test with directory creation
    print("\n2️⃣ Testing with directory creation...")
    try:
        test_dir = "test_data_dir"
        test_db = os.path.join(test_dir, "test.db")
        
        # Create directory
        os.makedirs(test_dir, exist_ok=True)
        
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, text TEXT)")
        conn.commit()
        conn.close()
        
        if os.path.exists(test_db):
            size = os.path.getsize(test_db)
            print(f"✅ Directory creation works ({size} bytes)")
            print(f"   Database created at: {os.path.abspath(test_db)}")
            
            # Clean up
            os.remove(test_db)
            os.rmdir(test_dir)
        else:
            print("❌ Directory creation test failed")
            return False
    except Exception as e:
        print(f"❌ Directory creation test failed: {e}")
        return False
    
    # Test 3: Test DatabaseManager class
    print("\n3️⃣ Testing DatabaseManager class...")
    try:
        # Add project root to path
        project_root = Path(__file__).parent
        sys.path.insert(0, str(project_root))
        
        from src.processors.enhanced_highlight_extractor import DatabaseManager
        
        test_db = "database_manager_test.db"
        db_manager = DatabaseManager(test_db)
        
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, text TEXT)")
        cursor.execute("INSERT INTO test (text) VALUES ('database manager test')")
        conn.commit()
        conn.close()
        
        if os.path.exists(test_db):
            size = os.path.getsize(test_db)
            print(f"✅ DatabaseManager works ({size} bytes)")
            print(f"   Database created at: {os.path.abspath(test_db)}")
            os.remove(test_db)
        else:
            print("❌ DatabaseManager test failed")
            return False
            
    except ImportError as e:
        print(f"❌ DatabaseManager import failed: {e}")
        print("   Make sure enhanced_highlight_extractor.py is in src/processors/")
        return False
    except Exception as e:
        print(f"❌ DatabaseManager test failed: {e}")
        return False
    
    print(f"\n✅ All database creation tests passed!")
    print(f"   SQLite and database creation is working correctly.")
    return True


def test_enhanced_extractor_import():
    """Test if enhanced extractor can be imported and initialized."""
    print(f"\n🔧 Testing Enhanced Extractor Import")
    print("=" * 35)
    
    try:
        project_root = Path(__file__).parent
        sys.path.insert(0, str(project_root))
        
        print("   Importing enhanced_highlight_extractor...")
        from src.processors.enhanced_highlight_extractor import (
            EnhancedHighlightExtractor,
            DatabaseManager,
            process_directory_enhanced
        )
        print("✅ Enhanced extractor imported successfully")
        
        print("   Creating DatabaseManager...")
        db_manager = DatabaseManager("import_test.db")
        print("✅ DatabaseManager created")
        
        print("   Creating EnhancedHighlightExtractor...")
        extractor = EnhancedHighlightExtractor(db_manager.get_connection(), enable_epub_matching=False)
        print("✅ EnhancedHighlightExtractor created")
        
        # Clean up
        if os.path.exists("import_test.db"):
            os.remove("import_test.db")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        print(f"   Check that enhanced_highlight_extractor.py is in src/processors/")
        return False
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test runner."""
    print("🧪 Database Creation Diagnostic")
    print("=" * 30)
    
    print(f"Current working directory: {os.getcwd()}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")
    
    # Test basic database creation
    basic_test = test_basic_database_creation()
    
    if not basic_test:
        print(f"\n❌ Basic database tests failed!")
        print(f"   There may be a fundamental issue with SQLite or file permissions.")
        return
    
    # Test enhanced extractor import
    import_test = test_enhanced_extractor_import()
    
    if not import_test:
        print(f"\n❌ Enhanced extractor import failed!")
        print(f"   The enhanced extractor module has issues.")
        return
    
    print(f"\n🎉 All tests passed!")
    print(f"   Database creation should work correctly.")
    print(f"   If you're still not seeing databases, the issue is likely:")
    print(f"   1. Running the command from a different directory")
    print(f"   2. The enhanced extractor not actually running to completion")
    print(f"   3. An error during execution that's not being shown")
    
    print(f"\n💡 Next steps:")
    print(f"   1. Run: python debug_enhanced_extractor.py /path/to/remarkable/files")
    print(f"   2. Check for any error messages during execution")
    print(f"   3. Make sure you're running from the project root directory")


if __name__ == "__main__":
    main()
