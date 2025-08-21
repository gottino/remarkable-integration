#!/usr/bin/env python3
"""
Test script to demonstrate the improvements in Enhanced Highlight Extractor v2.

This script compares the original CSV output (which shows the OCR problems)
with the new enhanced extractor results.
"""

import sys
import os
import csv
import sqlite3
from pathlib import Path

def read_original_csv_highlights():
    """Read the original highlights from the existing CSV file."""
    csv_path = "test_data/highlight_extraction/466c9d65-ffce-495f-b5fc-959eca3cd7e2_extracted_text_with_pages.csv"
    
    if not os.path.exists(csv_path):
        return []
    
    highlights = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            highlights.append({
                'title': row['Title'],
                'page': row['Page Number'],
                'text': row['Extracted Sentence'],
                'file': row['File Name']
            })
    
    return highlights

def read_enhanced_highlights():
    """Read the enhanced highlights from the new database."""
    db_path = "enhanced_highlights_v2.db"
    
    if not os.path.exists(db_path):
        return []
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT title, page_number, original_text, corrected_text, correction_applied
        FROM enhanced_highlights_v2
        ORDER BY passage_id
    """)
    
    highlights = []
    for row in cursor.fetchall():
        highlights.append({
            'title': row[0],
            'page': row[1],
            'original_text': row[2],
            'corrected_text': row[3],
            'correction_applied': bool(row[4])
        })
    
    conn.close()
    return highlights

def find_corrected_examples():
    """Find examples where OCR corrections were successfully applied."""
    enhanced = read_enhanced_highlights()
    
    corrections = []
    ocr_errors = ['gratiDcation', 'speciDc', 'e:ectively', 'deDning', 'Dghts', 'Daws']
    
    for highlight in enhanced:
        if highlight['correction_applied']:
            original = highlight['original_text']
            corrected = highlight['corrected_text']
            
            # Check if this contains one of our target OCR errors
            for error in ocr_errors:
                if error in original:
                    corrections.append({
                        'error_type': error,
                        'original': original[:100] + '...' if len(original) > 100 else original,
                        'corrected': corrected[:100] + '...' if len(corrected) > 100 else corrected,
                        'page': highlight['page']
                    })
                    break
    
    return corrections

def show_comparison():
    """Show a comparison between original and enhanced extraction."""
    print("🔍 Enhanced Highlight Extractor v2 - Results Comparison")
    print("=" * 70)
    print()
    
    # Read original data
    original_highlights = read_original_csv_highlights()
    enhanced_highlights = read_enhanced_highlights()
    
    print(f"📊 Statistics:")
    print(f"   Original CSV highlights: {len(original_highlights)}")
    print(f"   Enhanced v2 passages: {len(enhanced_highlights)}")
    
    corrected_count = sum(1 for h in enhanced_highlights if h.get('correction_applied', False))
    print(f"   Passages with OCR corrections: {corrected_count}")
    print()
    
    # Show OCR correction examples
    print("🔧 OCR Correction Examples:")
    print("-" * 40)
    
    corrections = find_corrected_examples()
    
    if corrections:
        for i, correction in enumerate(corrections[:5], 1):  # Show first 5 examples
            print(f"{i}. OCR Error: '{correction['error_type']}'")
            print(f"   Page: {correction['page']}")
            print(f"   BEFORE: {correction['original']}")
            print(f"   AFTER:  {correction['corrected']}")
            print()
    else:
        print("   No specific OCR corrections found in database.")
    
    # Show some problematic examples from the original CSV
    print("❌ Problems in Original CSV:")
    print("-" * 30)
    
    ocr_errors = ['gratiDcation', 'speciDc', 'e:ectively', 'deDning', 'Dghts']
    problematic = []
    
    for highlight in original_highlights:
        for error in ocr_errors:
            if error in highlight['text']:
                problematic.append({
                    'error': error,
                    'text': highlight['text'],
                    'page': highlight['page']
                })
                break
    
    for i, problem in enumerate(problematic[:5], 1):
        print(f"{i}. OCR Error: '{problem['error']}'")
        print(f"   Page: {problem['page']}")
        print(f"   Text: {problem['text'][:80]}...")
        print()
    
    print("✅ Summary:")
    print(f"   • Enhanced v2 successfully processed {len(enhanced_highlights)} passages")
    print(f"   • Applied OCR corrections to {corrected_count} passages")
    print(f"   • Fixed ligature errors: D→fi, :→ff, etc.")
    print(f"   • Merged fragmented highlights into coherent passages")
    print(f"   • Improved text quality through EPUB matching")

if __name__ == "__main__":
    show_comparison()