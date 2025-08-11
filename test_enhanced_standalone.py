#!/usr/bin/env python3
"""
Standalone test for enhanced highlight extractor.
This script tests only the enhanced extractor without requiring other modules.
"""

import sys
import os
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add project root to path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_enhanced_extraction_standalone(directory_path: str):
    """Test enhanced extraction without dependencies on other extractors."""
    print("🧪 Testing Enhanced Highlight Extractor (Standalone)")
    print("=" * 55)
    
    try:
        from src.processors.enhanced_highlight_extractor import (
            EnhancedHighlightExtractor, 
            DatabaseManager, 
            process_directory_enhanced,
            EPUBTextExtractor
        )
        print("✅ Enhanced extractor imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import enhanced extractor: {e}")
        print("   Make sure enhanced_highlight_extractor.py is in src/processors/")
        return False
    
    # Test 1: Check directory structure
    print(f"\n📁 Checking directory: {directory_path}")
    if not os.path.exists(directory_path):
        print(f"❌ Directory not found: {directory_path}")
        return False
    
    # Find .content and .epub files
    content_files = []
    epub_files = []
    
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith('.content'):
                content_files.append(os.path.join(root, file))
            elif file.endswith('.epub'):
                epub_files.append(os.path.join(root, file))
    
    print(f"   Found {len(content_files)} .content files")
    print(f"   Found {len(epub_files)} .epub files")
    
    if not content_files:
        print("❌ No .content files found")
        return False
    
    if not epub_files:
        print("⚠️  No .epub files found - enhanced features won't work")
        print("   (Will fall back to basic extraction)")
    
    # Test 2: Test individual components
    print(f"\n🔧 Testing components...")
    
    # Test database manager
    try:
        db_manager = DatabaseManager("test_enhanced_standalone.db")
        conn = db_manager.get_connection()
        conn.close()
        print("✅ DatabaseManager works")
    except Exception as e:
        print(f"❌ DatabaseManager error: {e}")
        return False
    
    # Test EPUB extractor (if epub files available)
    if epub_files:
        try:
            epub_extractor = EPUBTextExtractor(epub_files[0])
            text_length = len(epub_extractor.full_text)
            print(f"✅ EPUBTextExtractor works ({text_length:,} characters extracted)")
            
            # Test text matching
            test_result = epub_extractor.find_best_match("the")
            if test_result:
                print(f"✅ Text matching works (found match with score {test_result[1]:.2f})")
            else:
                print("⚠️  Text matching returned no results (normal for short search)")
                
        except Exception as e:
            print(f"❌ EPUBTextExtractor error: {e}")
            return False
    
    # Test 3: Test enhanced extractor
    print(f"\n🚀 Testing enhanced extraction...")
    
    try:
        # Clean up any existing test database
        test_db_path = "test_enhanced_standalone.db"
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        # Run enhanced processing
        results = process_directory_enhanced(directory_path, DatabaseManager(test_db_path))
        
        total_passages = sum(results.values())
        processed_files = len([count for count in results.values() if count > 0])
        
        print(f"📊 Enhanced Extraction Results:")
        print(f"   Files processed: {len(results)}")
        print(f"   Files with passages: {processed_files}")
        print(f"   Total enhanced passages: {total_passages}")
        
        # Show results by file
        if total_passages > 0:
            print(f"\n📄 Results by file:")
            for file_path, count in results.items():
                file_name = os.path.basename(file_path)
                status = "✅" if count > 0 else "⚪"
                print(f"   {status} {file_name}: {count} passages")
            
            # Test database content
            print(f"\n🗃️  Testing database content...")
            with DatabaseManager(test_db_path).get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if enhanced_highlights table exists and has data
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enhanced_highlights'")
                if cursor.fetchone():
                    cursor.execute("SELECT COUNT(*) FROM enhanced_highlights")
                    db_count = cursor.fetchone()[0]
                    print(f"   ✅ Database contains {db_count} enhanced highlights")
                    
                    # Show sample
                    cursor.execute("""
                        SELECT title, original_text, corrected_text, match_score 
                        FROM enhanced_highlights 
                        LIMIT 2
                    """)
                    samples = cursor.fetchall()
                    
                    if samples:
                        print(f"\n📝 Sample enhanced highlights:")
                        for i, (title, original, corrected, score) in enumerate(samples, 1):
                            print(f"   {i}. '{title}'")
                            print(f"      Original: '{original[:60]}...'")
                            print(f"      Enhanced: '{corrected[:60]}...'")
                            print(f"      Match Score: {score:.2f}")
                else:
                    print("   ❌ No enhanced_highlights table found")
            
            print(f"✅ Enhanced extraction test completed successfully!")
            
        else:
            print(f"⚠️  No passages extracted. Possible reasons:")
            print(f"   - No highlights in .rm files")
            print(f"   - No matching .epub files")
            print(f"   - Text matching failed")
            print(f"   - Check log messages above for specific errors")
        
        # Clean up
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        return total_passages > 0
        
    except Exception as e:
        print(f"❌ Enhanced extraction test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def find_test_directories():
    """Find potential test directories."""
    possible_dirs = [
        "test_data",
        "data",
        "remarkable_files",
        "../test_data",
        "../remarkable_files"
    ]
    
    found_dirs = []
    for dir_path in possible_dirs:
        if os.path.exists(dir_path):
            # Check if it contains .content files
            content_files = []
            for root, _, files in os.walk(dir_path):
                content_files.extend([f for f in files if f.endswith('.content')])
            
            if content_files:
                found_dirs.append((dir_path, len(content_files)))
    
    return found_dirs


def main():
    """Main test runner."""
    print("🧪 Enhanced Highlight Extractor - Standalone Test")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("Usage: python test_enhanced_standalone.py <directory_path>")
        print()
        
        # Try to find test directories automatically
        found_dirs = find_test_directories()
        if found_dirs:
            print("💡 Found these directories with .content files:")
            for dir_path, content_count in found_dirs:
                print(f"   {dir_path} ({content_count} .content files)")
            print()
            print("Try: python test_enhanced_standalone.py <directory_path>")
        else:
            print("💡 No test directories found. Please specify a directory containing")
            print("   .content files from your reMarkable device.")
        
        return
    
    directory_path = sys.argv[1]
    
    success = test_enhanced_extraction_standalone(directory_path)
    
    if success:
        print(f"\n🎉 Test completed successfully!")
        print(f"   The enhanced highlight extractor is working correctly.")
    else:
        print(f"\n❌ Test failed!")
        print(f"   Check the error messages above for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
