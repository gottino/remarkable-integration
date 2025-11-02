#!/usr/bin/env python3
"""Check for duplicate books with author 'reMarkable' in Readwise."""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.readwise_sync import ReadwiseAPIClient
from src.utils.api_keys import get_readwise_api_key


async def main():
    """Find books with author 'reMarkable'."""

    # Get Readwise API key
    readwise_api_key = get_readwise_api_key()
    if not readwise_api_key:
        print("❌ Error: Readwise API key not found")
        sys.exit(1)

    print("=" * 80)
    print("Checking for Duplicate Books in Readwise")
    print("=" * 80)
    print()

    # Initialize Readwise client
    async with ReadwiseAPIClient(readwise_api_key) as client:
        # Get all books
        books = await client.get_books()

        print(f"📚 Total books in Readwise: {len(books)}")
        print()

        # Find books with author "reMarkable"
        remarkable_books = [b for b in books if (b.get('author') or '').lower() == 'remarkable']

        if not remarkable_books:
            print("✨ No duplicate books found! (No books with author 'reMarkable')")
            return

        print(f"⚠️  Found {len(remarkable_books)} books with author 'reMarkable':")
        print()

        for book in remarkable_books:
            book_id = book.get('id')
            title = book.get('title', 'Untitled')
            num_highlights = book.get('num_highlights', 0)

            print(f"  • {title}")
            print(f"    - Book ID: {book_id}")
            print(f"    - Author: reMarkable")
            print(f"    - Highlights: {num_highlights}")

            # Check if there's a correct version
            title_lower = title.lower()
            correct_version = [b for b in books if
                             b.get('title', '').lower() == title_lower and
                             (b.get('author') or '').lower() != 'remarkable']

            if correct_version:
                print(f"    - ✅ Correct version exists: '{correct_version[0].get('author')}'")
            else:
                print(f"    - ❓ No correct version found")
            print()

        print("=" * 80)
        print("What to do:")
        print("=" * 80)
        print()
        print("Option 1 (Manual):")
        print("  1. Go to https://readwise.io/books")
        print("  2. Find books with author 'reMarkable'")
        print("  3. Delete them manually")
        print()
        print("Option 2 (Re-sync with correct metadata):")
        print("  1. We'll update the sync code to use real author names")
        print("  2. Clear highlight_sync_records table")
        print("  3. Re-sync all highlights with correct metadata")
        print("  4. Readwise will append to existing correct books")
        print("  5. Then manually delete the 'reMarkable' books")
        print()


if __name__ == "__main__":
    asyncio.run(main())
