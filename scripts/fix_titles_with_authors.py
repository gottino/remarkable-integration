#!/usr/bin/env python3
"""Fix book titles that incorrectly include the author name."""

import sqlite3
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config

def main():
    """Remove author names from book titles."""

    # Load config
    config = Config()
    db_path = config.get('database.path')

    print("=" * 80)
    print("Fix Book Titles with Author Names")
    print("=" * 80)
    print()

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Find books where title ends with " - <author>"
    cursor.execute("""
        SELECT notebook_uuid, visible_name, authors
        FROM notebook_metadata
        WHERE authors IS NOT NULL
        AND visible_name LIKE '% - ' || authors
    """)

    books = cursor.fetchall()

    if not books:
        print("✨ No books found with author in title!")
        conn.close()
        return

    print(f"Found {len(books)} books with author in title:")
    print()

    for uuid, title, author in books:
        # Remove " - <author>" from the end
        clean_title = title.rsplit(' - ' + author, 1)[0]

        print(f"  • {title}")
        print(f"    → {clean_title}")
        print(f"    Author: {author}")
        print()

    response = input("Proceed with fixing titles? (yes/no): ")

    if response.lower() != 'yes':
        print("Aborted")
        conn.close()
        return

    print()
    print("Fixing titles...")
    print()

    fixed_count = 0
    for uuid, title, author in books:
        clean_title = title.rsplit(' - ' + author, 1)[0]

        # Update notebook_metadata
        cursor.execute("""
            UPDATE notebook_metadata
            SET visible_name = ?
            WHERE notebook_uuid = ?
        """, (clean_title, uuid))

        # Update enhanced_highlights
        cursor.execute("""
            UPDATE enhanced_highlights
            SET title = ?
            WHERE notebook_uuid = ?
        """, (clean_title, uuid))

        print(f"  ✅ Fixed: {clean_title}")
        fixed_count += 1

    conn.commit()

    print()
    print(f"✅ Fixed {fixed_count} book titles")
    print()
    print("=" * 80)
    print("Next steps:")
    print("=" * 80)
    print()
    print("1. Clear sync records for these books:")
    print("   DELETE FROM highlight_sync_records")
    print("   WHERE notebook_uuid IN (")
    for i, (uuid, _, _) in enumerate(books):
        comma = "," if i < len(books) - 1 else ""
        print(f"       '{uuid}'{comma}")
    print("   );")
    print()
    print("2. Re-sync to Readwise:")
    print("   poetry run python -m src.cli.main sync-readwise")
    print()
    print("3. Manually delete old books with wrong titles from Readwise")
    print()

    conn.close()

if __name__ == "__main__":
    main()
