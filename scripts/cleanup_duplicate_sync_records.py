#!/usr/bin/env python3
"""
Clean up duplicate sync records caused by hash algorithm changes.

This script removes old sync records with 32-char MD5 hashes, keeping only
the newer records with 64-char SHA256 hashes to fix deduplication issues.
"""

import asyncio
import logging
import sys
import os
from datetime import datetime

# Add the parent directory to Python path to import src modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.core.database import DatabaseManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cleanup_duplicate_sync_records(dry_run: bool = True):
    """Clean up duplicate sync records by removing old MD5 hash records."""

    logger.info(f"🧹 Starting sync record cleanup (dry_run={dry_run})")

    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    db_manager = DatabaseManager(db_path)

    stats = {
        'old_records_found': 0,
        'old_records_deleted': 0,
        'errors': 0
    }

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Find sync records with 32-char hashes (old MD5 format)
        cursor.execute('''
            SELECT id, item_id, item_type, target_name, content_hash, created_at
            FROM sync_records
            WHERE LENGTH(content_hash) = 32
            ORDER BY item_type, item_id, created_at
        ''')

        old_records = cursor.fetchall()
        stats['old_records_found'] = len(old_records)

        logger.info(f"Found {len(old_records)} old sync records with 32-char hashes")

        if not old_records:
            logger.info("✅ No old records to clean up")
            return stats

        # Group by item to see duplicates
        by_item = {}
        for record in old_records:
            record_id, item_id, item_type, target_name, content_hash, created_at = record
            key = (item_id, item_type, target_name)
            if key not in by_item:
                by_item[key] = []
            by_item[key].append(record)

        # Show some examples of what will be cleaned up
        logger.info("Examples of records to be removed:")
        for i, (key, records) in enumerate(list(by_item.items())[:5]):
            item_id, item_type, target_name = key
            logger.info(f"  {item_type} {item_id} → {target_name}: {len(records)} old record(s)")
            for record in records[:2]:  # Show first 2
                logger.info(f"    Hash: {record[4]} (created: {record[5]})")

        if len(by_item) > 5:
            logger.info(f"  ... and {len(by_item) - 5} more items")

        # Delete old records
        if not dry_run:
            for record in old_records:
                record_id = record[0]
                try:
                    cursor.execute('DELETE FROM sync_records WHERE id = ?', (record_id,))
                    stats['old_records_deleted'] += 1
                except Exception as e:
                    logger.error(f"Error deleting record {record_id}: {e}")
                    stats['errors'] += 1

            conn.commit()
            logger.info("✅ Database changes committed")
        else:
            logger.info("🔍 Dry run completed - no changes made")
            stats['old_records_deleted'] = stats['old_records_found']  # Would be deleted

    # Print summary
    logger.info(f"\n📊 Cleanup Summary:")
    logger.info(f"   Old records found: {stats['old_records_found']}")
    logger.info(f"   Old records deleted: {stats['old_records_deleted']}")
    logger.info(f"   Errors: {stats['errors']}")

    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Clean up duplicate sync records')
    parser.add_argument('--execute', action='store_true', help='Actually perform the cleanup (default is dry run)')
    args = parser.parse_args()

    cleanup_duplicate_sync_records(dry_run=not args.execute)