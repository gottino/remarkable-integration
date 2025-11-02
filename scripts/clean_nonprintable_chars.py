#!/usr/bin/env python3
"""Clean non-printable characters from existing database entries."""

import sqlite3
import sys

db_path = "data/remarkable_pipeline.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

def clean_text(text):
    """Remove non-printable control characters (except newlines, tabs, carriage returns)."""
    return ''.join(c for c in text if ord(c) >= 32 or c in '\n\r\t')

# Find all affected rows
cursor.execute("SELECT id, corrected_text FROM enhanced_highlights WHERE corrected_text IS NOT NULL")

affected_count = 0
for row_id, text in cursor.fetchall():
    # Check for non-printable characters
    cleaned = clean_text(text)
    if cleaned != text:
        # Update the row
        cursor.execute("UPDATE enhanced_highlights SET corrected_text = ? WHERE id = ?", (cleaned, row_id))
        affected_count += 1
        print(f"Cleaned row {row_id}")

conn.commit()
conn.close()

print(f"\n✅ Cleaned {affected_count} rows")
