#!/usr/bin/env python3
"""Simple script to sync highlights directly to Readwise API."""

import sys
import asyncio
import sqlite3
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.integrations.readwise_sync import ReadwiseAPIClient
from src.utils.api_keys import get_readwise_api_key
from src.utils.config import Config


async def main():
    """Sync highlights directly to Readwise using API client."""

    # Load config
    config = Config()
    db_path = config.get('database.path')

    print("=" * 80)
    print("Simple Readwise Sync")
    print("=" * 80)
    print()

    # Get Readwise API key
    readwise_api_key = get_readwise_api_key()
    if not readwise_api_key:
        print("❌ Error: Readwise API key not found")
        sys.exit(1)

    # Initialize Readwise client
    client = ReadwiseAPIClient(readwise_api_key)

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get highlights grouped by document
    cursor.execute('''
        SELECT notebook_uuid, title, COUNT(*) as highlight_count
        FROM enhanced_highlights
        GROUP BY notebook_uuid, title
        ORDER BY MAX(created_at) DESC
    ''')

    documents = cursor.fetchall()

    print(f"📚 Found {len(documents)} documents")
    print()

    # Process each document
    for doc_uuid, title, count in documents:
        print(f"Processing: {title} ({count} highlights)")

        # Get highlights for this document
        cursor.execute('''
            SELECT id, original_text, corrected_text, page_number
            FROM enhanced_highlights
            WHERE notebook_uuid = ?
            ORDER BY CAST(page_number AS INTEGER)
        ''', (doc_uuid,))

        highlights = cursor.fetchall()

        # Format for Readwise
        readwise_highlights = []
        for h_id, original, corrected, page in highlights:
            # Use corrected text if available
            text = corrected if corrected and corrected.strip() else original

            # Convert page to int
            try:
                page_int = int(page) if page else None
            except (ValueError, TypeError):
                page_int = None

            highlight = {
                "text": text,
                "title": title,
                "author": "reMarkable",
                "category": "books",
                "source_type": "remarkable",
                "highlighted_at": datetime.now().isoformat(),
            }

            # Add page number if available
            if page_int is not None:
                highlight["location"] = page_int
                highlight["location_type"] = "page"

            readwise_highlights.append(highlight)

        # Send to Readwise
        try:
            async with client as api_client:
                result = await api_client.import_highlights(readwise_highlights)
                print(f"  ✅ Synced {len(readwise_highlights)} highlights")
                if result and 'detail' in result:
                    print(f"     {result['detail']}")
        except Exception as e:
            print(f"  ❌ Error: {e}")

        print()

    conn.close()

    print("=" * 80)
    print("Sync complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
