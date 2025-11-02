#!/usr/bin/env python3
"""Test EPUB matching on production database highlights."""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.epub_text_matcher import EPUBTextMatcher
from PyPDF2 import PdfReader

# Paths
epub_path = "/Users/gabriele/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop/02c1d14f-5106-4f02-a699-9a6c97338180.epub"
pdf_path = "/Users/gabriele/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop/02c1d14f-5106-4f02-a699-9a6c97338180.pdf"
db_path = "data/remarkable_pipeline.db"

print("="*80)
print("Testing EPUB Matching on Production Highlights")
print("="*80)
print()

# Get total PDF pages
with open(pdf_path, 'rb') as f:
    reader = PdfReader(f)
    total_pages = len(reader.pages)
    print(f"PDF: {total_pages} pages")

# Initialize EPUB matcher
print(f"EPUB: Initializing matcher...")
matcher = EPUBTextMatcher(epub_path, fuzzy_threshold=85)
print()

# Get highlights from database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("""
    SELECT id, page_number, original_text, corrected_text, confidence
    FROM enhanced_highlights
    WHERE source_file LIKE '%02c1d14f-5106-4f02-a699-9a6c97338180%'
    ORDER BY CAST(page_number AS INTEGER)
    LIMIT 5
""")

highlights = cursor.fetchall()
print(f"Testing {len(highlights)} highlights from 'Das kalte Blut':")
print()

for i, (id, page, original, pdf_text, conf) in enumerate(highlights, 1):
    print(f"{'='*80}")
    print(f"Highlight {i} (ID: {id}, Page: {page})")
    print(f"{'='*80}")

    print(f"\n1. Original .rm text:")
    print(f"   {original[:100]}...")

    print(f"\n2. PDF-matched text (current in DB):")
    print(f"   {pdf_text[:100]}...")

    # Try EPUB matching
    try:
        page_num = int(page)
        result = matcher.match_highlight(
            pdf_text=pdf_text,
            pdf_page=page_num,
            total_pdf_pages=total_pages,
            expand_sentences=True,
            window_size=0.10
        )

        if result:
            epub_text, score = result

            # Validate similarity
            from fuzzywuzzy import fuzz
            similarity = fuzz.ratio(pdf_text[:100], epub_text[:100])

            if score >= 85 and similarity >= 70:
                print(f"\n3. ✅ EPUB-matched text (score: {score}, similarity: {similarity}%):")
                print(f"   {epub_text[:100]}...")

                # Check if it's actually different/better
                if epub_text != pdf_text:
                    print(f"\n   → EPUB version is different!")
                    # Show what changed
                    if len(epub_text) > len(pdf_text):
                        print(f"   → Longer by {len(epub_text) - len(pdf_text)} chars")
                    elif len(epub_text) < len(pdf_text):
                        print(f"   → Shorter by {len(pdf_text) - len(epub_text)} chars")
                else:
                    print(f"\n   → Same as PDF (no artifacts to clean)")
            else:
                print(f"\n3. ⚠️  EPUB match rejected (score: {score}, similarity: {similarity}%)")
                print(f"   → Keeping PDF version")
        else:
            print(f"\n3. ❌ No EPUB match found")
            print(f"   → Keeping PDF version")

    except Exception as e:
        print(f"\n3. ❌ Error: {e}")

    print()

conn.close()

print(f"{'='*80}")
print("Test complete!")
print(f"{'='*80}")
