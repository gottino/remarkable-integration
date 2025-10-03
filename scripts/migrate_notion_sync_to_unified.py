#!/usr/bin/env python3
"""
Migrate existing Notion sync tracking data to unified sync_records table.

This script reads from:
- notion_page_sync: Page-level sync tracking with content hashes
- notion_todo_sync: Todo sync tracking
- notion_page_blocks: Block ID mappings

And creates corresponding records in the unified sync_records table.

Usage:
    python scripts/migrate_notion_sync_to_unified.py [--dry-run] [--database-path PATH]
"""

import argparse
import hashlib
import logging
import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Optional

# Add src to path
sys.path.insert(0, 'src')

from core.database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NotionSyncMigrator:
    """Migrates existing Notion sync data to unified sync_records table."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def migrate_all(self, dry_run: bool = True) -> Dict[str, int]:
        """
        Migrate all Notion sync data to unified sync_records.

        Args:
            dry_run: If True, only simulate the migration

        Returns:
            Statistics about the migration
        """
        stats = {
            'pages_migrated': 0,
            'todos_migrated': 0,
            'errors': 0,
            'skipped': 0
        }

        try:
            logger.info(f"{'DRY RUN: ' if dry_run else ''}Starting Notion sync migration...")

            # Step 1: Migrate page sync data
            page_stats = self._migrate_page_sync_data(dry_run)
            stats['pages_migrated'] = page_stats['migrated']
            stats['errors'] += page_stats['errors']
            stats['skipped'] += page_stats['skipped']

            # Step 2: Migrate todo sync data
            todo_stats = self._migrate_todo_sync_data(dry_run)
            stats['todos_migrated'] = todo_stats['migrated']
            stats['errors'] += todo_stats['errors']
            stats['skipped'] += todo_stats['skipped']

            logger.info("Migration completed:")
            logger.info(f"  - Pages migrated: {stats['pages_migrated']}")
            logger.info(f"  - Todos migrated: {stats['todos_migrated']}")
            logger.info(f"  - Errors: {stats['errors']}")
            logger.info(f"  - Skipped: {stats['skipped']}")

            return stats

        except Exception as e:
            logger.error(f"Error during migration: {e}")
            stats['errors'] += 1
            return stats

    def _migrate_page_sync_data(self, dry_run: bool) -> Dict[str, int]:
        """Migrate data from notion_page_sync table."""
        stats = {'migrated': 0, 'errors': 0, 'skipped': 0}

        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Get all page sync records that have corresponding blocks in Notion and don't already have unified sync records
                cursor.execute('''
                    SELECT
                        nps.notebook_uuid,
                        nps.page_number,
                        nps.page_uuid,
                        nps.content_hash,
                        nps.last_synced,
                        npb.notion_block_id,
                        nps.last_synced_content,
                        npb.notion_page_id
                    FROM notion_page_sync nps
                    INNER JOIN notion_page_blocks npb ON (
                        nps.notebook_uuid = npb.notebook_uuid
                        AND nps.page_number = npb.page_number
                    )
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = COALESCE(nps.page_uuid, nps.notebook_uuid || '::' || nps.page_number)
                        AND sr.target_name = 'notion'
                        AND sr.item_type = 'page_text'
                    )
                    WHERE sr.id IS NULL
                    AND nps.last_synced IS NOT NULL
                    ORDER BY nps.last_synced DESC
                ''')

                page_records = cursor.fetchall()
                logger.info(f"Found {len(page_records)} page sync records to migrate")

                for record in page_records:
                    notebook_uuid, page_number, page_uuid, content_hash, last_synced, notion_block_id, last_synced_content, notion_page_id = record

                    try:
                        # Generate a proper content hash if missing
                        if not content_hash and last_synced_content:
                            content_hash = hashlib.md5(last_synced_content.encode('utf-8')).hexdigest()
                        elif not content_hash:
                            # Use a placeholder hash for records without content
                            content_hash = f"legacy_page_{notebook_uuid}_{page_number}"

                        # Create metadata
                        metadata = {
                            'notebook_uuid': notebook_uuid,
                            'page_number': page_number,
                            'notion_block_id': notion_block_id,
                            'migration_source': 'notion_page_sync',
                            'original_sync_date': last_synced,
                            'has_content': bool(last_synced_content)
                        }

                        item_id = page_uuid or f"{notebook_uuid}::{page_number}"

                        if not dry_run:
                            # Insert into sync_records
                            cursor.execute('''
                                INSERT OR REPLACE INTO sync_records
                                (content_hash, target_name, external_id, item_type, status,
                                 item_id, metadata, created_at, updated_at, synced_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                content_hash,
                                'notion',
                                notion_block_id,
                                'page_text',
                                'success',
                                item_id,
                                str(metadata),  # Convert to JSON string
                                last_synced or datetime.now().isoformat(),
                                last_synced or datetime.now().isoformat(),
                                last_synced
                            ))

                        stats['migrated'] += 1

                        if stats['migrated'] % 100 == 0:
                            logger.info(f"Migrated {stats['migrated']} page records...")

                    except Exception as e:
                        logger.error(f"Error migrating page record {notebook_uuid}:{page_number}: {e}")
                        stats['errors'] += 1

                if not dry_run:
                    conn.commit()

                logger.info(f"Page migration completed: {stats['migrated']} records migrated")

        except Exception as e:
            logger.error(f"Error migrating page sync data: {e}")
            stats['errors'] += 1

        return stats

    def _migrate_todo_sync_data(self, dry_run: bool) -> Dict[str, int]:
        """Migrate data from notion_todo_sync table."""
        stats = {'migrated': 0, 'errors': 0, 'skipped': 0}

        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Check if notion_todo_sync table exists
                cursor.execute('''
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='notion_todo_sync'
                ''')

                if not cursor.fetchone():
                    logger.info("notion_todo_sync table not found, skipping todo migration")
                    return stats

                # Get all todo sync records that don't already have unified sync records
                cursor.execute('''
                    SELECT
                        nts.todo_id,
                        nts.notion_page_id,
                        nts.exported_at
                    FROM notion_todo_sync nts
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = CAST(nts.todo_id AS TEXT)
                        AND sr.target_name = 'notion'
                        AND sr.item_type = 'todo'
                    )
                    WHERE sr.id IS NULL
                    AND nts.notion_page_id IS NOT NULL
                    ORDER BY nts.exported_at DESC
                ''')

                todo_records = cursor.fetchall()
                logger.info(f"Found {len(todo_records)} todo sync records to migrate")

                for record in todo_records:
                    todo_id, notion_page_id, exported_at = record

                    try:
                        # Try to get todo data for content hash
                        cursor.execute('''
                            SELECT text, notebook_uuid, page_number
                            FROM todos
                            WHERE id = ?
                        ''', (todo_id,))

                        todo_data = cursor.fetchone()

                        if todo_data:
                            text, notebook_uuid, page_number = todo_data
                            # Generate content hash
                            content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
                        else:
                            # Fallback for missing todos
                            content_hash = f"legacy_todo_{todo_id}"

                        # Create metadata
                        metadata = {
                            'migration_source': 'notion_todo_sync',
                            'original_export_date': exported_at
                        }

                        if not dry_run:
                            # Insert into sync_records
                            cursor.execute('''
                                INSERT OR REPLACE INTO sync_records
                                (content_hash, target_name, external_id, item_type, status,
                                 item_id, metadata, created_at, updated_at, synced_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                content_hash,
                                'notion',
                                notion_page_id,
                                'todo',
                                'success',
                                str(todo_id),
                                str(metadata),
                                exported_at or datetime.now().isoformat(),
                                exported_at or datetime.now().isoformat(),
                                exported_at
                            ))

                        stats['migrated'] += 1

                    except Exception as e:
                        logger.error(f"Error migrating todo record {todo_id}: {e}")
                        stats['errors'] += 1

                if not dry_run:
                    conn.commit()

                logger.info(f"Todo migration completed: {stats['migrated']} records migrated")

        except Exception as e:
            logger.error(f"Error migrating todo sync data: {e}")
            stats['errors'] += 1

        return stats

    def analyze_existing_sync_state(self) -> Dict[str, any]:
        """Analyze the existing sync state to understand what needs migration."""
        analysis = {
            'notion_page_sync_count': 0,
            'notion_todo_sync_count': 0,
            'notion_page_blocks_count': 0,
            'sync_records_count': 0,
            'sample_page_sync': None,
            'sample_todo_sync': None
        }

        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Count existing records
                try:
                    cursor.execute('SELECT COUNT(*) FROM notion_page_sync')
                    analysis['notion_page_sync_count'] = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute('SELECT COUNT(*) FROM notion_todo_sync')
                    analysis['notion_todo_sync_count'] = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute('SELECT COUNT(*) FROM notion_page_blocks')
                    analysis['notion_page_blocks_count'] = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute('SELECT COUNT(*) FROM sync_records WHERE target_name = "notion"')
                    analysis['sync_records_count'] = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    pass

                # Get sample records
                try:
                    cursor.execute('''
                        SELECT notebook_uuid, page_number, content_hash, last_synced
                        FROM notion_page_sync
                        WHERE notion_block_id IS NOT NULL
                        LIMIT 1
                    ''')
                    sample = cursor.fetchone()
                    if sample:
                        analysis['sample_page_sync'] = {
                            'notebook_uuid': sample[0],
                            'page_number': sample[1],
                            'has_content_hash': bool(sample[2]),
                            'last_synced': sample[3]
                        }
                except sqlite3.OperationalError:
                    pass

                try:
                    cursor.execute('''
                        SELECT todo_id, notion_page_id, exported_at
                        FROM notion_todo_sync
                        LIMIT 1
                    ''')
                    sample = cursor.fetchone()
                    if sample:
                        analysis['sample_todo_sync'] = {
                            'todo_id': sample[0],
                            'notion_page_id': sample[1],
                            'exported_at': sample[2]
                        }
                except sqlite3.OperationalError:
                    pass

        except Exception as e:
            logger.error(f"Error analyzing sync state: {e}")
            analysis['error'] = str(e)

        return analysis


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Migrate Notion sync data to unified system')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Only simulate the migration (default: True)')
    parser.add_argument('--execute', action='store_true', default=False,
                       help='Actually execute the migration')
    parser.add_argument('--database-path', type=str,
                       help='Database path (default: data/remarkable_pipeline.db)')
    parser.add_argument('--analyze-only', action='store_true', default=False,
                       help='Only analyze the current sync state')

    args = parser.parse_args()

    # Determine database path
    db_path = args.database_path or 'data/remarkable_pipeline.db'

    # Determine if this is a dry run
    dry_run = not args.execute

    if dry_run and not args.analyze_only:
        logger.info("🧪 DRY RUN MODE - No changes will be made")
    elif not dry_run:
        logger.info("🚀 EXECUTION MODE - Changes will be made to database")
        confirmation = input("Are you sure you want to proceed? (yes/no): ")
        if confirmation.lower() != 'yes':
            logger.info("Aborted by user")
            return 0

    try:
        # Initialize components
        db_manager = DatabaseManager(db_path)
        migrator = NotionSyncMigrator(db_manager)

        if args.analyze_only:
            # Just analyze the current state
            logger.info("🔍 Analyzing existing sync state...")
            analysis = migrator.analyze_existing_sync_state()

            print("\n📊 Sync State Analysis:")
            print(f"  - notion_page_sync records: {analysis['notion_page_sync_count']}")
            print(f"  - notion_todo_sync records: {analysis['notion_todo_sync_count']}")
            print(f"  - notion_page_blocks records: {analysis['notion_page_blocks_count']}")
            print(f"  - Existing unified sync_records (notion): {analysis['sync_records_count']}")

            if analysis.get('sample_page_sync'):
                sample = analysis['sample_page_sync']
                print(f"\n📄 Sample page sync record:")
                print(f"  - Notebook: {sample['notebook_uuid']}")
                print(f"  - Page: {sample['page_number']}")
                print(f"  - Has content hash: {sample['has_content_hash']}")
                print(f"  - Last synced: {sample['last_synced']}")

            if analysis.get('sample_todo_sync'):
                sample = analysis['sample_todo_sync']
                print(f"\n📋 Sample todo sync record:")
                print(f"  - Todo ID: {sample['todo_id']}")
                print(f"  - Notion page: {sample['notion_page_id']}")
                print(f"  - Exported: {sample['exported_at']}")

        else:
            # Run migration
            stats = migrator.migrate_all(dry_run=dry_run)

            if stats['errors'] == 0:
                logger.info("✅ Migration completed successfully")
            else:
                logger.warning(f"⚠️  Migration completed with {stats['errors']} errors")

    except Exception as e:
        logger.error(f"❌ Error in migration: {e}")
        return 1

    return 0


if __name__ == '__main__':
    import asyncio
    exit_code = asyncio.run(main())
    sys.exit(exit_code)