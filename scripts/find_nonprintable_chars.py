#!/usr/bin/env python3
"""Find all rows with non-printable characters."""

import sqlite3

db_path = "data/remarkable_pipeline.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute("SELECT id, corrected_text FROM enhanced_highlights WHERE corrected_text IS NOT NULL")

affected_rows = []
for row_id, text in cursor.fetchall():
    # Check for non-printable characters (excluding newlines, tabs, carriage returns)
    non_printable = [c for c in text if ord(c) < 32 and c not in '\n\r\t']
    if non_printable:
        affected_rows.append((row_id, len(non_printable), set(ord(c) for c in non_printable)))

print(f"Found {len(affected_rows)} rows with non-printable characters:\n")
for row_id, count, char_codes in affected_rows[:20]:
    chars_hex = ', '.join(f"0x{c:02x}" for c in sorted(char_codes))
    print(f"  Row {row_id}: {count} non-printable chars ({chars_hex})")

if len(affected_rows) > 20:
    print(f"\n  ... and {len(affected_rows) - 20} more rows")

conn.close()
