#!/usr/bin/env python3
"""
Debug script to identify why EPUB text matching isn't working for OCR error correction.
This will help pinpoint exactly where the EPUB matching process is failing.
"""

import sys
import os
import sqlite3
from pathlib import Path
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import re
from fuzzywuzzy import fuzz
import difflib

def extract_epub_text(epub_path):
    """Extract all text from EPUB file with detailed logging."""
    print(f"\n📖 Processing EPUB: {epub_path}")
    
    try:
        book = epub.read_epub(epub_path)
        print(f"✅ EPUB loaded successfully")
        
        # Get book metadata
        title = book.get_metadata('DC', 'title')
        print(f"📚 Book title: {title[0][0] if title else 'Unknown'}")
        
        all_text = []
        chapter_count = 0
        
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                chapter_count += 1
                content = item.get_content().decode('utf-8')
                soup = BeautifulSoup(content, 'html.parser')
                
                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()
                
                text = soup.get_text()
                
                # Clean up whitespace
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                clean_text = ' '.join(chunk for chunk in chunks if chunk)
                
                if clean_text:
                    all_text.append(clean_text)
                    print(f"  📄 Chapter {chapter_count}: {len(clean_text)} characters")
        
        full_text = ' '.join(all_text)
        print(f"✅ Total extracted: {len(full_text)} characters from {chapter_count} chapters")
        
        # Show a sample of the text
        sample = full_text[:500] + "..." if len(full_text) > 500 else full_text
        print(f"📝 Text sample: {repr(sample)}")
        
        return full_text
        
    except Exception as e:
        print(f"❌ Error extracting EPUB text: {e}")
        return None

def test_fuzzy_matching(ocr_text, epub_text, min_ratio=60):
    """Test fuzzy matching with detailed logging."""
    print(f"\n🔍 Testing fuzzy matching:")
    print(f"   OCR text: {repr(ocr_text)}")
    print(f"   EPUB text length: {len(epub_text)} characters")
    print(f"   Min ratio: {min_ratio}")
    
    if not epub_text:
        print("❌ No EPUB text to match against")
        return None
    
    # Clean the OCR text for matching
    clean_ocr = re.sub(r'[^\w\s]', ' ', ocr_text.lower())
    clean_ocr = ' '.join(clean_ocr.split())
    print(f"   Cleaned OCR: {repr(clean_ocr)}")
    
    # Try different window sizes
    ocr_words = clean_ocr.split()
    window_sizes = [len(ocr_words), max(1, len(ocr_words) - 1), max(1, len(ocr_words) - 2)]
    
    best_match = None
    best_ratio = 0
    
    for window_size in window_sizes:
        print(f"\n   🪟 Testing window size: {window_size}")
        
        # Create sliding windows of EPUB text
        epub_words = epub_text.lower().split()
        matches_tested = 0
        
        for i in range(0, len(epub_words) - window_size + 1, 50):  # Sample every 50 words for speed
            window_text = ' '.join(epub_words[i:i + window_size])
            ratio = fuzz.ratio(clean_ocr, window_text)
            matches_tested += 1
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = window_text
                print(f"      🎯 New best match (ratio: {ratio}): {repr(window_text[:100])}...")
            
            if matches_tested % 1000 == 0:
                print(f"      📊 Tested {matches_tested} windows, best ratio so far: {best_ratio}")
        
        print(f"   ✅ Window size {window_size}: tested {matches_tested} windows")
        
        if best_ratio >= min_ratio:
            break
    
    print(f"\n🏆 Final best match:")
    print(f"   Ratio: {best_ratio}")
    print(f"   Match: {repr(best_match[:200])}..." if best_match else "None")
    
    return best_match if best_ratio >= min_ratio else None

def test_highlight_samples(db_path, epub_path, limit=5):
    """Test EPUB matching on actual highlight samples."""
    print(f"\n🧪 Testing with actual highlights from: {db_path}")
    
    # Connect to database
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get some sample highlights
        cursor.execute("""
            SELECT text, epub_match, match_confidence 
            FROM highlights 
            WHERE length(text) > 10 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (limit,))
        
        highlights = cursor.fetchall()
        print(f"✅ Found {len(highlights)} highlights to test")
        
        # Extract EPUB text
        epub_text = extract_epub_text(epub_path) if epub_path else None
        
        for i, (text, epub_match, confidence) in enumerate(highlights, 1):
            print(f"\n🔬 Testing highlight {i}/{len(highlights)}:")
            print(f"   Original text: {repr(text)}")
            print(f"   Stored EPUB match: {repr(epub_match) if epub_match else 'None'}")
            print(f"   Stored confidence: {confidence}")
            
            # Test our matching
            if epub_text:
                found_match = test_fuzzy_matching(text, epub_text)
                if found_match:
                    print(f"   ✅ Our test found: {repr(found_match[:100])}...")
                else:
                    print(f"   ❌ Our test found no match")
            else:
                print(f"   ⚠️  No EPUB text available for testing")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Database error: {e}")

def check_file_associations(remarkable_dir):
    """Check which files have associated EPUBs."""
    print(f"\n📁 Checking file associations in: {remarkable_dir}")
    
    if not os.path.exists(remarkable_dir):
        print(f"❌ Directory doesn't exist: {remarkable_dir}")
        return
    
    pdf_files = list(Path(remarkable_dir).glob("*.pdf"))
    epub_files = list(Path(remarkable_dir).glob("*.epub"))
    
    print(f"📄 Found {len(pdf_files)} PDF files")
    print(f"📖 Found {len(epub_files)} EPUB files")
    
    if pdf_files:
        print(f"\n📄 PDF files:")
        for pdf in pdf_files[:5]:  # Show first 5
            print(f"   {pdf.name}")
    
    if epub_files:
        print(f"\n📖 EPUB files:")
        for epub_file in epub_files[:5]:  # Show first 5
            print(f"   {epub_file.name}")
    
    # Check for matching pairs
    pdf_stems = {f.stem for f in pdf_files}
    epub_stems = {f.stem for f in epub_files}
    matches = pdf_stems & epub_stems
    
    print(f"\n🔗 Potential matches (same filename): {len(matches)}")
    for match in matches:
        print(f"   {match}")

def main():
    print("🔍 EPUB Text Matching Debug Tool")
    print("=" * 50)
    
    # Configuration - update these paths
    DATABASE_PATH = "debug_enhanced.db"  # Path to your highlights database
    EPUB_PATH = None  # Path to a specific EPUB file to test
    REMARKABLE_DIR = "/Users/gabriele/Documents/Development/remarkable-integration/test_data/highlight_extraction"  # Update this
    
    print(f"🔧 Configuration:")
    print(f"   Database: {DATABASE_PATH}")
    print(f"   EPUB: {EPUB_PATH if EPUB_PATH else 'Not specified'}")
    print(f"   reMarkable dir: {REMARKABLE_DIR}")
    
    # Check if database exists
    if not os.path.exists(DATABASE_PATH):
        print(f"❌ Database not found: {DATABASE_PATH}")
        print("   Please update DATABASE_PATH in the script")
        return
    
    # Check file associations
    check_file_associations(REMARKABLE_DIR)
    
    # If EPUB specified, test it
    if EPUB_PATH and os.path.exists(EPUB_PATH):
        print(f"\n🧪 Testing specific EPUB file:")
        epub_text = extract_epub_text(EPUB_PATH)
        
        # Test with sample highlights
        test_highlight_samples(DATABASE_PATH, EPUB_PATH)
    else:
        print(f"\n⚠️  No EPUB file specified for testing")
        print(f"   Update EPUB_PATH in the script to test EPUB matching")
        
        # Still test database content
        test_highlight_samples(DATABASE_PATH, None)

if __name__ == "__main__":
    main()
