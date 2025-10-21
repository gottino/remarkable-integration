#!/usr/bin/env python3
"""
Reorder existing page blocks in Notion to descending order (highest page number first).

This script:
1. Fetches all blocks from a Notion page
2. Identifies page toggle blocks and extracts page numbers
3. Deletes all page blocks
4. Re-inserts them in descending order (newest first)
"""

import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config
from src.utils.api_keys import get_notion_api_key
from notion_client import Client
import httpx

def reorder_notion_pages(page_id: str, dry_run: bool = True):
    """
    Reorder page blocks in a Notion page to descending order.

    Args:
        page_id: Notion page ID to reorder
        dry_run: If True, only show what would be done without making changes
    """
    print("=" * 80)
    print("REORDER NOTION PAGE BLOCKS")
    print("=" * 80)
    print(f"Notion Page ID: {page_id}")
    print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will modify Notion)'}")
    print()

    # Get Notion client
    api_key = get_notion_api_key()
    if not api_key:
        print("❌ No Notion API key found. Use 'config api-key set' to configure.")
        return

    # Disable SSL verification for corporate environments
    http_client = httpx.Client(verify=False)
    client = Client(auth=api_key, client=http_client)
    print("⚠️  SSL verification disabled for corporate environment")

    # Fetch all blocks
    print("📥 Fetching blocks from Notion...")
    blocks_response = client.blocks.children.list(block_id=page_id)
    all_blocks = blocks_response["results"]

    # Separate header blocks from page blocks
    header_blocks = []
    page_blocks = []
    page_block_data = []  # Store (page_number, block_id, block_data)

    for block in all_blocks:
        if block["type"] == "toggle":
            # Extract page number from toggle title
            rich_text = block.get("toggle", {}).get("rich_text", [])
            if rich_text:
                title = rich_text[0].get("text", {}).get("content", "")
                # Parse "📄 Page X" format
                if "📄 Page " in title:
                    try:
                        page_num = int(title.split("📄 Page ")[1].split(" ")[0].split("(")[0])

                        # Fetch children blocks for this toggle
                        print(f"  Found page {page_num}: {block['id']}, fetching children...")
                        children_response = client.blocks.children.list(block_id=block["id"])
                        children = children_response.get("results", [])

                        page_blocks.append(block)
                        page_block_data.append((page_num, block["id"], block, children))
                        print(f"    → {len(children)} child blocks")
                    except (ValueError, IndexError):
                        print(f"  ⚠️  Could not parse page number from: {title}")
                        header_blocks.append(block)
                else:
                    header_blocks.append(block)
        else:
            # Keep header, summary, divider blocks
            header_blocks.append(block)

    print(f"\n📊 Summary:")
    print(f"  Header blocks: {len(header_blocks)}")
    print(f"  Page blocks: {len(page_blocks)}")

    if not page_blocks:
        print("\n⚠️  No page blocks found to reorder.")
        return

    # Sort page blocks by page number (descending)
    page_block_data.sort(key=lambda x: x[0], reverse=True)

    print(f"\n📋 Current order: {[x[0] for x in sorted(page_block_data, key=lambda x: list(all_blocks).index(next(b for b in all_blocks if b['id'] == x[1])))][:10]}...")
    print(f"📋 Target order: {[x[0] for x in page_block_data][:10]}...")

    # Check if already in correct order
    current_order = []
    for block in all_blocks:
        if block["type"] == "toggle":
            for page_num, block_id, _, _ in page_block_data:
                if block["id"] == block_id:
                    current_order.append(page_num)
                    break

    if current_order == [x[0] for x in page_block_data]:
        print("\n✅ Pages are already in correct descending order. Nothing to do.")
        return

    if dry_run:
        print("\n🔍 DRY RUN - Would perform the following actions:")
        print(f"  1. Delete {len(page_blocks)} page blocks")
        print(f"  2. Re-insert them in descending order: {[x[0] for x in page_block_data][:10]}...")
        print("\nRun with --live to actually reorder the pages.")
        return

    # LIVE MODE: Delete and re-insert
    print(f"\n🗑️  Deleting {len(page_blocks)} page blocks...")
    for i, (page_num, block_id, _, _) in enumerate(page_block_data, 1):
        client.blocks.delete(block_id=block_id)
        print(f"  Deleted page {page_num} ({i}/{len(page_blocks)})")
        time.sleep(0.1)  # Small delay to avoid rate limits

    print(f"\n📝 Re-inserting {len(page_block_data)} pages in descending order...")

    # Find the last header block to use as insertion anchor
    last_header_id = header_blocks[-1]["id"] if header_blocks else None
    last_inserted_id = last_header_id

    for i, (page_num, _, block_data, children) in enumerate(page_block_data, 1):
        # Reconstruct the block without the ID (Notion will assign a new one)
        new_block = {
            "type": block_data["type"],
            block_data["type"]: block_data[block_data["type"]]
        }

        # Insert after the last inserted block
        result = client.blocks.children.append(
            block_id=page_id,
            children=[new_block],
            after=last_inserted_id
        )

        if result.get("results") and len(result["results"]) > 0:
            new_block_id = result["results"][0]["id"]
            last_inserted_id = new_block_id
            print(f"  Inserted page {page_num} ({i}/{len(page_block_data)})")

            # Re-insert children blocks if any
            if children:
                print(f"    → Re-inserting {len(children)} child blocks...")
                children_to_insert = []
                for child in children:
                    # Reconstruct child block without ID
                    child_block = {
                        "type": child["type"],
                        child["type"]: child[child["type"]]
                    }
                    children_to_insert.append(child_block)

                # Insert children in batches of 100 (Notion API limit)
                for batch_start in range(0, len(children_to_insert), 100):
                    batch = children_to_insert[batch_start:batch_start + 100]
                    client.blocks.children.append(
                        block_id=new_block_id,
                        children=batch
                    )
                    time.sleep(0.35)  # Rate limiting

        time.sleep(0.35)  # Rate limiting

    print(f"\n✅ Successfully reordered {len(page_block_data)} pages in descending order!")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python reorder_notion_pages.py <notion_page_id> [--live]")
        print("\nExample:")
        print("  python reorder_notion_pages.py abc123def456  # Dry run")
        print("  python reorder_notion_pages.py abc123def456 --live  # Actually reorder")
        sys.exit(1)

    page_id = sys.argv[1]
    dry_run = '--live' not in sys.argv

    reorder_notion_pages(page_id, dry_run=dry_run)
