#!/usr/bin/env python3
"""
Test script for enhanced highlight extraction with EPUB text matching.
"""

import sys
import os
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import systems for comparison
try:
    from src.processors.highlight_extractor import HighlightExtractor as OriginalExtractor
    from src.processors.highlight_extractor import DatabaseManager, process_directory as process_original
    ORIGINAL_AVAILABLE = True
except ImportError as e:
    print(f"❌ Original extractor not available: {e}")
    ORIGINAL_AVAILABLE = False

try:
    from src.processors.enhanced_highlight_extractor import EnhancedHighlightExtractor, process_directory_enhanced
    ENHANCED_AVAILABLE = True
except ImportError as e:
    print(f"❌ Enhanced extractor not available: {e}")
    print("   Make sure enhanced_highlight_extractor.py is in src/processors/")
    ENHANCED_AVAILABLE = False


def test_epub_extraction(directory_path: str):
    """Test enhanced EPUB extraction vs original method."""
    print("🔬 Testing Enhanced vs Original Highlight Extraction")
    print("=" * 60)
    
    if not ENHANCED_AVAILABLE:
        print("❌ Enhanced extractor not available")
        return
    
    # Test enhanced method
    print("📚 Testing Enhanced Method (with EPUB matching)...")
    enhanced_db = "enhanced_test.db"
    if os.path.exists(enhanced_db):
        os.remove(enhanced_db)
    
    enhanced_results = process_directory_enhanced(directory_path, DatabaseManager(enhanced_db))
    enhanced_total = sum(enhanced_results.values())
    
    print(f"   ✅ Enhanced: {enhanced_total} passages from {len(enhanced_results)} files")
    
    # Test original method for comparison
    if ORIGINAL_AVAILABLE:
        print("\n📄 Testing Original Method...")
        original_db = "original_test.db"
        if os.path.exists(original_db):
            os.remove(original_db)
        
        original_results = process_original(directory_path, DatabaseManager(original_db))
        original_total = sum(original_results.values())
        
        print(f"   ✅ Original: {original_total} highlights from {len(original_results)} files")
        
        # Comparison
        print(f"\n📊 Comparison:")
        print(f"   Original highlights: {original_total}")
        print(f"   Enhanced passages: {enhanced_total}")
        if original_total > 0:
            ratio = enhanced_total / original_total
            print(f"   Ratio: {ratio:.2f} (enhanced/original)")
            if ratio < 1:
                print(f"   📈 Enhanced merged {original_total - enhanced_total} highlights into passages")
        
        # Show sample results
        show_sample_comparison(enhanced_db, original_db)
    
    else:
        print("\n⏭️ Skipping original method comparison (not available)")


def show_sample_comparison(enhanced_db: str, original_db: str):
    """Show sample results from both databases."""
    print(f"\n📋 Sample Results Comparison:")
    print("=" * 40)
    
    try:
        import sqlite3
        
        # Enhanced results
        print("🔬 Enhanced Results (first 3):")
        with sqlite3.connect(enhanced_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT title, corrected_text, original_text, match_score, page_number 
                FROM enhanced_highlights 
                LIMIT 3
            """)
            
            for i, (title, corrected, original, score, page) in enumerate(cursor.fetchall(), 1):
                print(f"\n   {i}. '{title}' (page {page})")
                print(f"      Original: '{original[:80]}...'")
                print(f"      Enhanced: '{corrected[:80]}...'")
                print(f"      Match Score: {score:.2f}")
        
        # Original results
        print(f"\n📄 Original Results (first 3):")
        with sqlite3.connect(original_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT title, text, page_number 
                FROM highlights 
                LIMIT 3
            """)
            
            for i, (title, text, page) in enumerate(cursor.fetchall(), 1):
                print(f"\n   {i}. '{title}' (page {page})")
                print(f"      Text: '{text[:80]}...'")
    
    except Exception as e:
        print(f"   ❌ Error showing samples: {e}")


def test_epub_text_extraction(epub_path: str):
    """Test EPUB text extraction specifically."""
    print(f"📖 Testing EPUB Text Extraction: {epub_path}")
    print("=" * 50)
    
    if not ENHANCED_AVAILABLE:
        print("❌ Enhanced extractor not available")
        return
    
    try:
        from src.processors.enhanced_highlight_extractor import EPUBTextExtractor
        
        # Test EPUB extraction
        extractor = EPUBTextExtractor(epub_path)
        
        print(f"📊 EPUB Analysis:")
        print(f"   Total text length: {len(extractor.full_text):,} characters")
        print(f"   Chapters found: {len(extractor.chapter_texts)}")
        print(f"   Average chapter length: {len(extractor.full_text) // max(len(extractor.chapter_texts), 1):,} chars")
        
        # Test text matching
        test_searches = [
            "the high pitch of excitement",  # Clean text
            "speciDc",                       # OCR error
            "mutual gratiDcation",          # Another OCR error
        ]
        
        print(f"\n🔍 Testing Text Matching:")
        for search_text in test_searches:
            print(f"\n   Searching for: '{search_text}'")
            result = extractor.find_best_match(search_text)
            
            if result:
                matched_text, score, position = result
                print(f"   ✅ Match found (score: {score:.2f})")
                print(f"      Result: '{matched_text[:100]}...'")
            else:
                print(f"   ❌ No good match found")
    
    except Exception as e:
        print(f"❌ Error testing EPUB extraction: {e}")
        import traceback
        traceback.print_exc()


def find_epub_files(directory_path: str):
    """Find EPUB files in directory for testing."""
    epub_files = []
    for root, _, files in os.walk(directory_path):
        for file in files:
            if file.endswith('.epub'):
                epub_files.append(os.path.join(root, file))
    return epub_files


def main():
    """Main test runner."""
    print("🧪 Enhanced Highlight Extraction Test Suite")
    print("=" * 50)
    
    if len(sys.argv) < 2:
        print("Usage: python test_enhanced_extraction.py <directory_path> [epub_file]")
        print("  directory_path: Directory containing .content files")
        print("  epub_file: Optional specific EPUB file to test")
        return
    
    directory_path = sys.argv[1]
    
    if not os.path.exists(directory_path):
        print(f"❌ Directory not found: {directory_path}")
        return
    
    # Test 1: Enhanced extraction
    test_epub_extraction(directory_path)
    
    # Test 2: Specific EPUB file (if provided)
    if len(sys.argv) > 2:
        epub_path = sys.argv[2]
        if os.path.exists(epub_path):
            print(f"\n" + "=" * 60)
            test_epub_text_extraction(epub_path)
        else:
            print(f"❌ EPUB file not found: {epub_path}")
    
    # Test 3: Find and test available EPUB files
    else:
        epub_files = find_epub_files(directory_path)
        if epub_files:
            print(f"\n📚 Found {len(epub_files)} EPUB files in directory:")
            for epub_file in epub_files[:3]:  # Test first 3
                print(f"   {os.path.basename(epub_file)}")
            
            # Test first EPUB
            print(f"\n" + "=" * 60)
            test_epub_text_extraction(epub_files[0])
        else:
            print(f"\n📚 No EPUB files found in {directory_path}")
    
    print(f"\n🎯 Testing complete!")
    print(f"\n💡 Next steps:")
    print(f"   1. Check the enhanced vs original comparison above")
    print(f"   2. Look at the sample results to see text improvements")
    print(f"   3. Run: python view_database.py enhanced_test.db")


if __name__ == "__main__":
    main()
