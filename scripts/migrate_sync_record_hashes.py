#!/usr/bin/env python3
"""
Migrate sync record hashes to use consistent ContentFingerprint calculation.

This script updates existing sync records to use the new unified ContentFingerprint
hash calculation method, fixing deduplication issues caused by hash format changes.
"""

import asyncio
import logging
import sys
import os
from datetime import datetime

# Add the parent directory to Python path to import src modules
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.core.database import DatabaseManager
from src.core.sync_engine import ContentFingerprint

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def migrate_sync_record_hashes(dry_run: bool = True):
    """Migrate sync record hashes to use consistent ContentFingerprint calculation."""

    logger.info(f"🔄 Starting sync record hash migration (dry_run={dry_run})")

    # Initialize database
    db_path = './data/remarkable_pipeline.db'
    db_manager = DatabaseManager(db_path)

    stats = {
        'todos_processed': 0,
        'todos_updated': 0,
        'notebooks_processed': 0,
        'notebooks_updated': 0,
        'highlights_processed': 0,
        'highlights_updated': 0,
        'errors': 0
    }

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Migrate TODO sync records
        logger.info("📝 Migrating todo sync records...")
        cursor.execute('''
            SELECT sr.id, sr.item_id, sr.content_hash, sr.target_name,
                   t.text, t.notebook_uuid, t.page_number
            FROM sync_records sr
            JOIN todos t ON sr.item_id = CAST(t.id AS TEXT)
            WHERE sr.item_type = 'todo'
        ''')

        todo_records = cursor.fetchall()
        logger.info(f"Found {len(todo_records)} todo sync records to check")

        for record in todo_records:
            stats['todos_processed'] += 1
            sync_record_id, item_id, old_hash, target_name, text, notebook_uuid, page_number = record

            try:
                # Calculate new hash using ContentFingerprint
                todo_data = {
                    'text': text.strip(),
                    'notebook_uuid': notebook_uuid,
                    'page_number': page_number,
                    'type': 'todo'
                }
                new_hash = ContentFingerprint.for_todo(todo_data)

                if old_hash != new_hash:
                    logger.info(f"  Todo {item_id}: {old_hash[:16]}... → {new_hash[:16]}...")

                    if not dry_run:
                        cursor.execute('''
                            UPDATE sync_records
                            SET content_hash = ?, updated_at = ?
                            WHERE id = ?
                        ''', (new_hash, datetime.now().isoformat(), sync_record_id))

                    stats['todos_updated'] += 1

            except Exception as e:
                logger.error(f"  Error processing todo {item_id}: {e}")
                stats['errors'] += 1

        # Migrate NOTEBOOK sync records
        logger.info("📚 Migrating notebook sync records...")
        cursor.execute('''
            SELECT sr.id, sr.item_id, sr.content_hash, sr.target_name,
                   nm.visible_name
            FROM sync_records sr
            JOIN notebook_metadata nm ON sr.item_id = nm.notebook_uuid
            WHERE sr.item_type = 'notebook'
        ''')

        notebook_records = cursor.fetchall()
        logger.info(f"Found {len(notebook_records)} notebook sync records to check")

        for record in notebook_records:
            stats['notebooks_processed'] += 1
            sync_record_id, notebook_uuid, old_hash, target_name, notebook_name = record

            try:
                # Get notebook pages for hash calculation
                cursor.execute('''
                    SELECT nte.page_number, nte.text, nte.confidence
                    FROM notebook_text_extractions nte
                    WHERE nte.notebook_uuid = ?
                    ORDER BY nte.page_number
                ''', (notebook_uuid,))

                pages_data = cursor.fetchall()

                if not pages_data:
                    continue  # Skip notebooks with no text content

                # Convert pages to text_content for ContentFingerprint compatibility
                text_content = '\n'.join([
                    f"Page {page[0]}: {page[1]}"
                    for page in pages_data
                    if page[1] and page[1].strip()
                ])

                # Create data structure compatible with ContentFingerprint.for_notebook()
                fingerprint_data = {
                    'title': notebook_name or 'Untitled Notebook',
                    'author': '',  # reMarkable doesn't have author concept
                    'text_content': text_content,
                    'page_count': len(pages_data),
                    'type': 'notebook'
                }
                new_hash = ContentFingerprint.for_notebook(fingerprint_data)

                if old_hash != new_hash:
                    logger.info(f"  Notebook {notebook_name}: {old_hash[:16]}... → {new_hash[:16]}...")

                    if not dry_run:
                        cursor.execute('''
                            UPDATE sync_records
                            SET content_hash = ?, updated_at = ?
                            WHERE id = ?
                        ''', (new_hash, datetime.now().isoformat(), sync_record_id))

                    stats['notebooks_updated'] += 1

            except Exception as e:
                logger.error(f"  Error processing notebook {notebook_uuid}: {e}")
                stats['errors'] += 1

        # Migrate HIGHLIGHT sync records (if any)
        logger.info("🔖 Migrating highlight sync records...")
        cursor.execute('''
            SELECT sr.id, sr.item_id, sr.content_hash, sr.target_name
            FROM sync_records sr
            WHERE sr.item_type = 'highlight'
        ''')

        highlight_records = cursor.fetchall()
        logger.info(f"Found {len(highlight_records)} highlight sync records")

        # For highlights, we'd need to join with the highlights table
        # But since the focus is on todos, we'll skip this for now
        stats['highlights_processed'] = len(highlight_records)

        if not dry_run:
            conn.commit()
            logger.info("✅ Database changes committed")
        else:
            logger.info("🔍 Dry run completed - no changes made")

    # Print summary
    logger.info(f"\n📊 Migration Summary:")
    logger.info(f"   Todos: {stats['todos_updated']}/{stats['todos_processed']} updated")
    logger.info(f"   Notebooks: {stats['notebooks_updated']}/{stats['notebooks_processed']} updated")
    logger.info(f"   Highlights: {stats['highlights_updated']}/{stats['highlights_processed']} updated")
    logger.info(f"   Errors: {stats['errors']}")

    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Migrate sync record hashes')
    parser.add_argument('--execute', action='store_true', help='Actually perform the migration (default is dry run)')
    args = parser.parse_args()

    migrate_sync_record_hashes(dry_run=not args.execute)