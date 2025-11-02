#!/usr/bin/env python3
"""Fix Readwise duplicate books by re-syncing with correct metadata."""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config


def main():
    """Clear sync records and prepare for re-sync with correct metadata."""

    # Load config
    config = Config()
    db_path = config.get('database.path')

    print("=" * 80)
    print("Fix Readwise Duplicate Books")
    print("=" * 80)
    print()

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check current state
    cursor.execute("SELECT COUNT(*) FROM highlight_sync_records WHERE target_name='readwise'")
    current_count = cursor.fetchone()[0]

    print(f"Current state:")
    print(f"  • {current_count} highlights tracked as synced to Readwise")
    print()

    print("What this script will do:")
    print("  1. Clear all Readwise sync records from highlight_sync_records")
    print("  2. This will cause ALL highlights to be re-synced")
    print("  3. Next sync will use correct author names from book metadata")
    print("  4. Readwise will append to existing correct books (by title+author match)")
    print()

    print("Then you'll need to:")
    print("  5. Manually delete the 5 books with author 'reMarkable' from Readwise")
    print("     (Go to https://readwise.io/books and search for author:reMarkable)")
    print()

    response = input("Proceed with clearing sync records? (yes/no): ")

    if response.lower() != 'yes':
        print("Aborted")
        conn.close()
        return

    print()
    print("Clearing sync records...")

    # Clear Readwise sync records
    cursor.execute("DELETE FROM highlight_sync_records WHERE target_name='readwise'")
    deleted_count = cursor.rowcount
    conn.commit()

    print(f"✅ Cleared {deleted_count} Readwise sync records")
    print()

    print("=" * 80)
    print("Next steps:")
    print("=" * 80)
    print()
    print("1. Run the sync command:")
    print("   poetry run python -m src.cli.main sync-readwise")
    print()
    print("   This will re-sync all highlights with CORRECT metadata")
    print("   (author names from book_metadata table)")
    print()
    print("2. Go to Readwise and manually delete duplicate books:")
    print("   https://readwise.io/books")
    print("   Search for: author:reMarkable")
    print("   Delete these 5 books:")
    print("   • Amsterdam - Ian McEwan")
    print("   • The Story of My Experiments with Truth: An Autobiography")
    print("   • Love Is Never Enough...")
    print("   • the great gatsby - f")
    print("   • Das kalte Blut")
    print()
    print("✨ Done! Future syncs will use correct metadata automatically.")
    print()

    conn.close()


if __name__ == "__main__":
    main()
