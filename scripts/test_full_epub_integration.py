#!/usr/bin/env python3
"""Test full EPUB matching integration with Das kalte Blut."""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.enhanced_highlight_extractor import EnhancedHighlightExtractor, process_directory_enhanced
from src.core.database import DatabaseManager

# Path to reMarkable data
remarkable_dir = "/Users/gabriele/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop"

# Use a test database
test_db = "test_epub_highlights.db"

print("="*80)
print("Testing EPUB Text Matching Integration")
print("="*80)
print(f"\nTest database: {test_db}")
print(f"Source directory: {remarkable_dir}")
print()

# Initialize database
db_manager = DatabaseManager(test_db)

# Process only Das kalte Blut (02c1d14f-5106-4f02-a699-9a6c97338180)
print("Processing 'Das kalte Blut' with EPUB matching...")
print()

results = process_directory_enhanced(remarkable_dir, db_manager)

# Check results
print("\n" + "="*80)
print("Results Summary")
print("="*80)

with db_manager.get_connection() as conn:
    cursor = conn.cursor()

    # Count total highlights
    cursor.execute("SELECT COUNT(*) FROM enhanced_highlights")
    total = cursor.fetchone()[0]
    print(f"Total highlights extracted: {total}")

    # Check for Das kalte Blut specifically
    cursor.execute("""
        SELECT COUNT(*)
        FROM enhanced_highlights
        WHERE title LIKE '%kalte%'
    """)
    kalte_blut_count = cursor.fetchone()[0]
    print(f"Highlights from 'Das kalte Blut': {kalte_blut_count}")

    # Sample some highlights to check EPUB matching
    if kalte_blut_count > 0:
        print(f"\nSample highlights:")
        print("-"*80)

        cursor.execute("""
            SELECT page_number, substr(original_text, 1, 80) as orig,
                   substr(corrected_text, 1, 80) as corr, confidence
            FROM enhanced_highlights
            WHERE title LIKE '%kalte%'
            ORDER BY CAST(page_number AS INTEGER)
            LIMIT 5
        """)

        for row in cursor.fetchall():
            page, orig, corr, conf = row
            print(f"\nPage {page} (confidence: {conf:.2f}):")
            print(f"  Original: {orig}...")
            print(f"  Corrected: {corr}...")

            # Check if they're different
            if orig[:50] != corr[:50]:
                print(f"  ✓ Text was cleaned!")

print(f"\n{'='*80}")
print("Test complete!")
print(f"{'='*80}")
