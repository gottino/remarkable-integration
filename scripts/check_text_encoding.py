#!/usr/bin/env python3
"""Check for encoding issues in enhanced_highlights table."""

import sqlite3
import sys

db_path = "data/remarkable_pipeline.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check row 170 specifically
cursor.execute("SELECT id, corrected_text, original_text FROM enhanced_highlights WHERE id = 170")
row = cursor.fetchone()

if row:
    row_id, corrected, original = row
    print(f"Row ID: {row_id}")
    print(f"\nOriginal text type: {type(original)}")
    print(f"Original text: {original[:100]}...")
    print(f"\nCorrected text type: {type(corrected)}")
    print(f"Corrected text: {corrected[:100]}...")

    # Check if it's bytes
    if isinstance(corrected, bytes):
        print(f"\n⚠️  WARNING: corrected_text is stored as bytes!")
        print(f"Bytes (hex): {corrected[:50].hex()}")
        print(f"Decoded: {corrected.decode('utf-8', errors='replace')[:100]}")
    else:
        print(f"\n✓ corrected_text is stored as string (type: {type(corrected).__name__})")

    # Check for non-printable characters
    non_printable = [c for c in corrected if ord(c) < 32 and c not in '\n\r\t']
    if non_printable:
        print(f"\n⚠️  Found {len(non_printable)} non-printable characters:")
        for c in non_printable[:5]:
            print(f"  - Char code: {ord(c)} (0x{ord(c):02x})")

# Check all rows for encoding issues
cursor.execute("""
    SELECT id, typeof(corrected_text), length(corrected_text)
    FROM enhanced_highlights
    WHERE corrected_text IS NOT NULL
    ORDER BY id
""")

rows = cursor.fetchall()
print(f"\n\n📊 Checked {len(rows)} rows:")
blob_count = sum(1 for r in rows if r[1] == 'blob')
text_count = sum(1 for r in rows if r[1] == 'text')

print(f"  - TEXT type: {text_count}")
print(f"  - BLOB type: {blob_count}")

if blob_count > 0:
    print(f"\n⚠️  Found {blob_count} rows with BLOB type!")
    cursor.execute("""
        SELECT id
        FROM enhanced_highlights
        WHERE typeof(corrected_text) = 'blob'
        LIMIT 10
    """)
    blob_ids = [r[0] for r in cursor.fetchall()]
    print(f"   Row IDs with BLOB: {blob_ids}")

conn.close()
