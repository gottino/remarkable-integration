#!/usr/bin/env python3
"""
Debug script to verify database queries are returning correct content.
"""

import sqlite3
import sys
import os

def check_notebook_content(db_path, notebook_uuid, notebook_name):
    """Check what content we get for a specific notebook."""
    print(f"\n🔍 Checking notebook: {notebook_name} ({notebook_uuid})")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Use the exact same query as the file watcher
    cursor.execute('''
        SELECT
            nte.notebook_uuid, nte.notebook_name, nte.page_number,
            nte.text, nte.confidence, nte.page_uuid,
            nm.full_path, nm.last_modified, nm.last_opened
        FROM notebook_text_extractions nte
        LEFT JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
        WHERE nte.notebook_uuid = ?
            AND nte.text IS NOT NULL AND length(nte.text) > 0
        ORDER BY nte.page_number
    ''', (notebook_uuid,))

    rows = cursor.fetchall()
    print(f"Found {len(rows)} pages")

    # Check first few pages
    for i, row in enumerate(rows[:3]):
        uuid, name, page_num, text, confidence, page_uuid, full_path, last_modified, last_opened = row
        text_preview = text[:80].replace('\n', ' ') if text else "NO TEXT"
        print(f"   Page {page_num}: '{text_preview}...'")

    # Check last few pages
    if len(rows) > 3:
        print(f"   ... {len(rows) - 6} pages skipped ...")
        for row in rows[-3:]:
            uuid, name, page_num, text, confidence, page_uuid, full_path, last_modified, last_opened = row
            text_preview = text[:80].replace('\n', ' ') if text else "NO TEXT"
            print(f"   Page {page_num}: '{text_preview}...'")

    # Specifically check page 16 if it's Test for integration
    if "Test for integration" in notebook_name:
        page_16_row = next((row for row in rows if row[2] == 16), None)
        if page_16_row:
            text = page_16_row[3]
            print(f"\n🚨 CRITICAL: Page 16 content: '{text[:100]}'")

            # Check if this contains any feedback content
            if "feedback" in text.lower() or "Ask team what they need" in text:
                print("❌ ERROR: Page 16 contains feedback content - THIS IS WRONG!")
            else:
                print("✅ Page 16 content looks correct")
        else:
            print("❌ Page 16 not found!")

    conn.close()

if __name__ == "__main__":
    db_path = "data/remarkable_pipeline.db"

    # Check the problematic notebook
    check_notebook_content(
        db_path,
        "98afc255-97ee-4416-96db-ac9a16a33109",
        "Test for integration"
    )

    # Also check if Team notebook exists and has the feedback content
    print(f"\n{'='*60}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Find notebooks that might contain the feedback content
    cursor.execute('''
        SELECT DISTINCT nm.visible_name, nm.notebook_uuid
        FROM notebook_metadata nm
        JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
        WHERE nte.text LIKE '%Ask team what they need to make their work easier%'
           OR nte.text LIKE '%Feedback loop from team%'
    ''')

    feedback_notebooks = cursor.fetchall()
    print(f"Found {len(feedback_notebooks)} notebooks with feedback content:")
    for name, uuid in feedback_notebooks:
        print(f"   {name} ({uuid})")
        check_notebook_content(db_path, uuid, name)

    conn.close()