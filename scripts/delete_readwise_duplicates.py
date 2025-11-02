#!/usr/bin/env python3
"""Delete duplicate books with author 'reMarkable' from Readwise."""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.readwise_sync import ReadwiseAPIClient
from src.utils.api_keys import get_readwise_api_key


async def main():
    """Delete books with author 'reMarkable'."""

    # Get Readwise API key
    readwise_api_key = get_readwise_api_key()
    if not readwise_api_key:
        print("❌ Error: Readwise API key not found")
        sys.exit(1)

    print("=" * 80)
    print("Delete Duplicate Books from Readwise")
    print("=" * 80)
    print()

    # Initialize Readwise client
    async with ReadwiseAPIClient(readwise_api_key) as client:
        # Get all books
        books = await client.get_books()

        # Find books with author "reMarkable"
        remarkable_books = [b for b in books if (b.get('author') or '').lower() == 'remarkable']

        if not remarkable_books:
            print("✨ No duplicate books found! (No books with author 'reMarkable')")
            return

        print(f"Found {len(remarkable_books)} books with author 'reMarkable':")
        print()

        for book in remarkable_books:
            book_id = book.get('id')
            title = book.get('title', 'Untitled')
            num_highlights = book.get('num_highlights', 0)

            print(f"  • {title}")
            print(f"    - Book ID: {book_id}")
            print(f"    - Highlights: {num_highlights}")
            print()

        print("⚠️  WARNING: This will permanently delete these books from Readwise!")
        print()
        response = input("Proceed with deletion? (yes/no): ")

        if response.lower() != 'yes':
            print("Aborted")
            return

        print()
        print("Deleting books...")
        print()

        # Delete each book
        deleted_count = 0
        for book in remarkable_books:
            book_id = book.get('id')
            title = book.get('title', 'Untitled')

            try:
                # Delete book using Readwise API
                await client._rate_limit()
                async with client.session.delete(
                    f"{client.base_url}/books/{book_id}/"
                ) as response:
                    if response.status == 204:
                        print(f"  ✅ Deleted: {title}")
                        deleted_count += 1
                    else:
                        error_text = await response.text()
                        print(f"  ❌ Failed to delete '{title}': {response.status} - {error_text}")
            except Exception as e:
                print(f"  ❌ Error deleting '{title}': {e}")

        print()
        print("=" * 80)
        print(f"✅ Deleted {deleted_count} of {len(remarkable_books)} books")
        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
