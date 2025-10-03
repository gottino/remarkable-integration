#!/usr/bin/env python3
"""
One-time migration script to create sync_records for existing highlights.

This script generates sync records for highlights that have already been synced to Readwise,
preventing them from being synced again when the file watcher runs.

Run this ONCE before starting the file watcher with highlight sync enabled.
"""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from src.core.sync_engine import ContentFingerprint, SyncItemType
from datetime import datetime


def migrate_existing_highlights(db_path: str, dry_run: bool = True):
    """Create sync_records for existing highlights already in Readwise."""

    db_manager = DatabaseManager(db_path)

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Get all existing highlights
        cursor.execute('''
            SELECT id, title, original_text, corrected_text, page_number, notebook_uuid,
                   file_name, source_file
            FROM enhanced_highlights
            ORDER BY id
        ''')

        highlights = cursor.fetchall()

        if not highlights:
            print("No highlights found in database.")
            return

        print(f"Found {len(highlights)} highlights in enhanced_highlights table")
        print(f"Mode: {'DRY RUN (no changes will be made)' if dry_run else 'LIVE (will create sync records)'}")
        print()

        created_count = 0

        for highlight_id, title, original_text, corrected_text, page_num, uuid, file_name, source_file in highlights:
            # Prepare highlight data for hash calculation
            highlight_data = {
                'id': highlight_id,
                'title': title,
                'text': original_text,
                'corrected_text': corrected_text,
                'page_number': page_num,
                'notebook_uuid': uuid,
                'file_name': file_name,
                'source_file': source_file
            }

            # Generate content hash (same logic as file watcher)
            content_hash = ContentFingerprint.for_highlight(highlight_data)
            item_id = f"{uuid}_{highlight_id}"

            print(f"Highlight {highlight_id}: '{title}' (page {page_num})")
            print(f"  Item ID: {item_id}")
            print(f"  Hash: {content_hash[:16]}...")

            if not dry_run:
                # Check if sync record already exists
                cursor.execute('''
                    SELECT id FROM sync_records
                    WHERE item_id = ? AND target_name = 'readwise'
                ''', (item_id,))

                if cursor.fetchone():
                    print(f"  → Already has sync record, skipping")
                else:
                    # Create sync record
                    cursor.execute('''
                        INSERT INTO sync_records
                        (item_type, item_id, target_name, content_hash, external_id, status, synced_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        SyncItemType.HIGHLIGHT.value,
                        item_id,
                        'readwise',
                        content_hash,
                        f'readwise_{item_id}',  # external_id (placeholder since we don't have the actual Readwise ID)
                        'completed',
                        datetime.now().isoformat()
                    ))
                    created_count += 1
                    print(f"  → Created sync record")
            else:
                print(f"  → Would create sync record (dry run)")

            print()

        if not dry_run:
            conn.commit()
            print(f"✅ Migration complete: Created {created_count} sync records")
        else:
            print(f"✅ Dry run complete: Would create sync records for {len(highlights)} highlights")
            print()
            print("To apply these changes, run:")
            print(f"  poetry run python {__file__} --live")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Migrate existing highlights to sync_records')
    parser.add_argument('--live', action='store_true',
                       help='Actually create sync records (default is dry run)')
    parser.add_argument('--db', type=str,
                       default='data/remarkable_pipeline.db',
                       help='Path to database (default: data/remarkable_pipeline.db)')

    args = parser.parse_args()

    migrate_existing_highlights(args.db, dry_run=not args.live)
