#!/usr/bin/env python3
"""
Backfill page_sync_records table by querying Notion to see which pages actually exist.

This script:
1. Queries all synced notebooks from sync_records
2. For each notebook, fetches the actual pages from Notion
3. Creates page_sync_records for pages that exist in Notion
4. Reports on pages in DB that aren't in Notion (need syncing)
"""

import sqlite3
import hashlib
import sys
import os
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config
from src.utils.api_keys import get_notion_api_key
import httpx


def get_notion_client():
    """Get Notion client with API key."""
    api_key = get_notion_api_key()
    if not api_key:
        raise ValueError("No Notion API key found. Use 'config api-key set' to configure.")

    # Create custom client that can handle SSL issues
    custom_client = httpx.Client(
        verify=False,  # Disable SSL verification for corporate environments
        timeout=30.0
    )

    return {
        'client': custom_client,
        'api_key': api_key,
        'base_url': 'https://api.notion.com/v1'
    }


def fetch_notion_pages_from_block(client_info, page_id):
    """
    Fetch all toggle blocks (pages) from a Notion page.

    Returns list of dicts with {page_number, block_id}
    """
    pages = []

    try:
        # Get all blocks from the Notion page
        response = client_info['client'].get(
            f"{client_info['base_url']}/blocks/{page_id}/children",
            headers={
                'Authorization': f"Bearer {client_info['api_key']}",
                'Notion-Version': '2022-06-28'
            },
            params={'page_size': 100}
        )
        response.raise_for_status()
        data = response.json()

        # Parse toggle blocks (which represent individual pages)
        for block in data.get('results', []):
            if block['type'] == 'toggle':
                # Extract page number from toggle title
                rich_text = block.get('toggle', {}).get('rich_text', [])
                if rich_text:
                    title = rich_text[0].get('text', {}).get('content', '')
                    # Parse "📄 Page X" format
                    if "📄 Page " in title:
                        try:
                            page_num = int(title.split("📄 Page ")[1].split(" ")[0].split("(")[0])
                            block_id = block['id']
                            pages.append({'page_number': page_num, 'block_id': block_id})
                        except (ValueError, IndexError):
                            continue

        print(f"  Found {len(pages)} pages in Notion")
        return pages

    except Exception as e:
        print(f"  ⚠️  Error fetching pages from Notion: {e}")
        return []


def backfill_page_sync_records(db_path, dry_run=True):
    """
    Backfill page_sync_records by querying Notion.

    Args:
        db_path: Path to database
        dry_run: If True, don't actually write records, just report what would happen
    """
    print("=" * 80)
    print("PAGE SYNC RECORDS BACKFILL")
    print("=" * 80)
    print(f"Database: {db_path}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will write to DB)'}")
    print()

    # Get Notion client
    try:
        client_info = get_notion_client()
        print("✓ Notion API client initialized\n")
    except Exception as e:
        print(f"✗ Failed to initialize Notion client: {e}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all synced notebooks from notion_notebook_sync table
    cursor.execute("""
        SELECT nns.notion_page_id, nns.notebook_uuid, nns.last_synced
        FROM notion_notebook_sync nns
        WHERE nns.notion_page_id IS NOT NULL
        ORDER BY nns.last_synced DESC
    """)

    notebooks = cursor.fetchall()
    print(f"Found {len(notebooks)} synced notebooks in notion_notebook_sync table\n")

    total_pages_backfilled = 0
    total_pages_missing = 0

    for notion_page_id, notebook_uuid, synced_at in notebooks:

        # Get notebook name from DB
        cursor.execute("""
            SELECT notebook_name, COUNT(*) as page_count
            FROM notebook_text_extractions
            WHERE notebook_uuid = ?
            GROUP BY notebook_name
        """, (notebook_uuid,))

        result = cursor.fetchone()
        if not result:
            print(f"⚠️  No pages found in DB for {notebook_uuid}, skipping")
            continue

        notebook_name, db_page_count = result
        print(f"\n{'='*60}")
        print(f"Notebook: {notebook_name}")
        print(f"  UUID: {notebook_uuid}")
        print(f"  Notion page ID: {notion_page_id}")
        print(f"  Pages in DB: {db_page_count}")
        print(f"  Last synced: {synced_at}")

        # Fetch actual pages from Notion
        notion_pages = fetch_notion_pages_from_block(client_info, notion_page_id)

        if not notion_pages:
            print(f"  ⚠️  No pages found in Notion (may be rate limited or empty)")
            continue

        # Get page content from DB for hash calculation
        cursor.execute("""
            SELECT page_number, text
            FROM notebook_text_extractions
            WHERE notebook_uuid = ?
            AND text IS NOT NULL
            AND length(text) > 0
            ORDER BY page_number
        """, (notebook_uuid,))

        db_pages = {page_num: text for page_num, text in cursor.fetchall()}

        # Match DB pages with Notion pages
        notion_page_nums = {p['page_number'] for p in notion_pages}
        db_page_nums = set(db_pages.keys())

        pages_in_both = notion_page_nums & db_page_nums
        pages_only_in_notion = notion_page_nums - db_page_nums
        pages_only_in_db = db_page_nums - notion_page_nums

        print(f"\n  📊 Page Analysis:")
        print(f"    Pages in both DB and Notion: {len(pages_in_both)}")
        print(f"    Pages only in Notion: {len(pages_only_in_notion)}")
        print(f"    Pages only in DB (need sync): {len(pages_only_in_db)}")

        if pages_only_in_db:
            print(f"    Missing from Notion: {sorted(list(pages_only_in_db))[:20]}{'...' if len(pages_only_in_db) > 20 else ''}")
            total_pages_missing += len(pages_only_in_db)

        # Create sync records for pages that exist in both
        backfilled_count = 0
        for notion_page_info in notion_pages:
            page_num = notion_page_info['page_number']
            block_id = notion_page_info['block_id']

            if page_num in db_pages:
                text = db_pages[page_num]
                content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()

                if not dry_run:
                    cursor.execute("""
                        INSERT OR REPLACE INTO page_sync_records
                        (notebook_uuid, page_number, content_hash, target_name, notion_page_id,
                         notion_block_id, status, synced_at, updated_at)
                        VALUES (?, ?, ?, 'notion', ?, ?, 'success', ?, CURRENT_TIMESTAMP)
                    """, (notebook_uuid, page_num, content_hash, notion_page_id, block_id, synced_at))

                backfilled_count += 1

        if not dry_run:
            conn.commit()

        print(f"  ✅ {'Would backfill' if dry_run else 'Backfilled'} {backfilled_count} page sync records")
        total_pages_backfilled += backfilled_count

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total pages backfilled: {total_pages_backfilled}")
    print(f"Total pages in DB but not in Notion: {total_pages_missing}")
    print()

    if dry_run:
        print("ℹ️  This was a DRY RUN. No changes were made.")
        print("   Run with --live to actually write sync records.")
    else:
        print("✅ Backfill complete!")

    conn.close()


if __name__ == '__main__':
    db_path = 'data/remarkable_pipeline.db'

    # Check for --live flag
    dry_run = '--live' not in sys.argv

    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    backfill_page_sync_records(db_path, dry_run=dry_run)
