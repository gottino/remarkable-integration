#!/usr/bin/env python3
"""Manually sync highlights from database to Readwise."""

import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from src.integrations.readwise_sync import ReadwiseSyncTarget
from src.core.sync_engine import SyncItem, SyncItemType, ContentFingerprint
from src.core.unified_sync import UnifiedSyncManager
from src.utils.api_keys import get_readwise_api_key
from src.utils.config import Config


async def main():
    """Sync all highlights from database to Readwise."""

    # Load config
    config = Config()
    db_path = config.get('database.path')

    print("=" * 80)
    print("Syncing Highlights to Readwise")
    print("=" * 80)
    print()

    # Get Readwise API key
    readwise_api_key = get_readwise_api_key()
    if not readwise_api_key:
        print("❌ Error: Readwise API key not found")
        print("   Set it using the config command or READWISE_API_KEY environment variable")
        sys.exit(1)

    # Initialize database and sync manager
    db_manager = DatabaseManager(db_path)
    unified_sync_manager = UnifiedSyncManager(db_manager)

    # Setup Readwise target
    try:
        with db_manager.get_connection() as conn:
            readwise_target = ReadwiseSyncTarget(
                access_token=readwise_api_key,
                db_connection=conn,
                author_name="reMarkable",
                default_category="books"
            )
            unified_sync_manager.register_target(readwise_target)
            print("✅ Readwise sync target registered")
            print()
    except Exception as e:
        print(f"❌ Error setting up Readwise: {e}")
        sys.exit(1)

    # Get all highlights from database
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Get highlights grouped by document
        cursor.execute('''
            SELECT notebook_uuid, title, COUNT(*) as highlight_count
            FROM enhanced_highlights
            GROUP BY notebook_uuid, title
            ORDER BY MAX(created_at) DESC
        ''')

        documents = cursor.fetchall()

        if not documents:
            print("📭 No highlights found in database")
            return

        print(f"📚 Found {len(documents)} documents with highlights:")
        print()

        total_highlights = 0
        for doc_uuid, title, count in documents:
            print(f"  • {title}: {count} highlights")
            total_highlights += count

        print()
        print(f"Total: {total_highlights} highlights across {len(documents)} documents")
        print()

        # Check which ones are already synced
        cursor.execute('''
            SELECT COUNT(DISTINCT item_id)
            FROM sync_records
            WHERE target_name = 'readwise' AND item_type = 'highlight' AND status = 'completed'
        ''')
        synced_count = cursor.fetchone()[0]

        print(f"Already synced: {synced_count} highlights")
        print(f"Remaining: {total_highlights - synced_count} highlights to sync")
        print()

        # Process each document
        for doc_uuid, title, count in documents:
            print("-" * 80)
            print(f"Processing: {title} ({count} highlights)")
            print("-" * 80)

            # Get highlights for this document
            cursor.execute('''
                SELECT id, title, original_text, corrected_text, page_number, notebook_uuid, file_name
                FROM enhanced_highlights
                WHERE notebook_uuid = ?
                ORDER BY CAST(page_number AS INTEGER)
            ''', (doc_uuid,))

            highlights = cursor.fetchall()

            if not highlights:
                print(f"⚠️  No highlights found for {doc_uuid}")
                continue

            # Create SyncItems for each highlight
            sync_items = []
            from datetime import datetime
            for h_id, h_title, original, corrected, page, notebook_uuid, filename in highlights:
                # Convert page number to integer (Readwise requires this)
                try:
                    page_int = int(page) if page else 0
                except (ValueError, TypeError):
                    page_int = 0

                # Create content hash using for_highlight method
                highlight_data = {
                    'text': original,
                    'corrected_text': corrected,
                    'source_file': filename or '',
                    'page_number': page or 0
                }
                content_hash = ContentFingerprint.for_highlight(highlight_data)

                # Create sync item with structure expected by ReadwiseSyncTarget
                sync_item = SyncItem(
                    item_type=SyncItemType.HIGHLIGHT,
                    item_id=f"{notebook_uuid}_{h_id}",
                    content_hash=content_hash,
                    data={
                        'text': original,  # Original corrupted text
                        'corrected_text': corrected,  # Clean text (preferred)
                        'title': h_title,
                        'page_number': page_int,  # Must be integer
                        'notebook_uuid': notebook_uuid,
                        'filename': filename,
                        'highlight_id': h_id
                    },
                    source_table='enhanced_highlights',
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                sync_items.append(sync_item)

            # Sync this document's highlights
            try:
                results = []
                for sync_item in sync_items:
                    result = await unified_sync_manager.sync_item_to_target(sync_item, "readwise")
                    results.append(result)

                # Count successes using SyncStatus enum
                from src.core.sync_engine import SyncStatus
                success_count = sum(1 for r in results if r.status == SyncStatus.SUCCESS)
                skip_count = sum(1 for r in results if r.status == SyncStatus.SKIPPED)
                error_count = sum(1 for r in results if r.status == SyncStatus.FAILED)

                if success_count > 0:
                    print(f"  ✅ Synced {success_count} highlights")
                if skip_count > 0:
                    print(f"  ⏭️  Skipped {skip_count} (already synced)")
                if error_count > 0:
                    print(f"  ❌ Failed {error_count}")
                    for i, r in enumerate(results):
                        if r.status == SyncStatus.FAILED:
                            print(f"     [{i+1}] Error: {r.error_message}")

            except Exception as e:
                print(f"  ❌ Error syncing highlights: {e}")
                import traceback
                traceback.print_exc()

            print()

    print("=" * 80)
    print("Sync complete!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
