#!/usr/bin/env python3
"""
Establish baseline sync state for Notion integration.

This script queries the Notion database to find existing pages that match
local notebooks and creates sync records to prevent duplicate syncing.

Usage:
    python scripts/establish_notion_baseline.py [--dry-run] [--database-path PATH]
"""

import argparse
import asyncio
import hashlib
import logging
import sqlite3
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add src to path
sys.path.insert(0, 'src')

from core.database import DatabaseManager
from utils.api_keys import get_notion_api_key, get_notion_database_id
from integrations.notion_sync import NotionNotebookSync

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NotionBaselineEstablisher:
    """Establishes baseline sync state by mapping existing Notion pages to local notebooks."""

    def __init__(self, db_manager: DatabaseManager, notion_token: str, database_id: str):
        self.db_manager = db_manager
        self.notion_token = notion_token
        self.database_id = database_id

        # Initialize Notion client
        self.notion_client = NotionNotebookSync(
            notion_token=notion_token,
            database_id=database_id,
            verify_ssl=True
        )

    async def establish_baseline(self, dry_run: bool = True) -> Dict[str, int]:
        """
        Establish baseline by mapping existing Notion pages to local notebooks.

        Args:
            dry_run: If True, only simulate the process

        Returns:
            Statistics about the baseline establishment
        """
        stats = {
            'notion_pages_found': 0,
            'local_notebooks_found': 0,
            'matches_created': 0,
            'errors': 0
        }

        try:
            logger.info(f"{'DRY RUN: ' if dry_run else ''}Establishing Notion sync baseline...")

            # Step 1: Get all existing Notion pages from the database
            notion_pages = await self._get_existing_notion_pages()
            stats['notion_pages_found'] = len(notion_pages)
            logger.info(f"Found {len(notion_pages)} existing Notion pages")

            # Step 2: Get all local notebooks
            local_notebooks = await self._get_local_notebooks()
            stats['local_notebooks_found'] = len(local_notebooks)
            logger.info(f"Found {len(local_notebooks)} local notebooks")

            # Step 3: Try to match Notion pages with local notebooks
            matches = await self._match_pages_to_notebooks(notion_pages, local_notebooks)
            logger.info(f"Found {len(matches)} potential matches")

            # Step 4: Create sync records for matches
            if not dry_run:
                for match in matches:
                    try:
                        await self._create_sync_record(match)
                        stats['matches_created'] += 1
                    except Exception as e:
                        logger.error(f"Error creating sync record for {match['notebook_uuid']}: {e}")
                        stats['errors'] += 1
            else:
                stats['matches_created'] = len(matches)
                logger.info("DRY RUN: Would create sync records for all matches")

            # Step 5: Report results
            logger.info("Baseline establishment completed:")
            logger.info(f"  - Notion pages found: {stats['notion_pages_found']}")
            logger.info(f"  - Local notebooks found: {stats['local_notebooks_found']}")
            logger.info(f"  - Sync records {'would be ' if dry_run else ''}created: {stats['matches_created']}")
            if stats['errors'] > 0:
                logger.warning(f"  - Errors: {stats['errors']}")

            return stats

        except Exception as e:
            logger.error(f"Error establishing baseline: {e}")
            stats['errors'] += 1
            return stats

    async def _get_existing_notion_pages(self) -> List[Dict[str, str]]:
        """Get list of existing Notion pages from the database."""
        # This would query the Notion database via API
        # For now, we'll simulate this or use any existing tracking

        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Check if we have any existing sync records for notion
                cursor.execute('''
                    SELECT external_id, item_id, metadata
                    FROM sync_records
                    WHERE target_name = 'notion' AND item_type = 'notebook'
                    AND status = 'success'
                ''')

                pages = []
                for row in cursor.fetchall():
                    external_id, item_id, metadata = row
                    pages.append({
                        'notion_page_id': external_id,
                        'notebook_uuid': item_id,
                        'metadata': metadata
                    })

                return pages

        except Exception as e:
            logger.error(f"Error getting existing Notion pages: {e}")
            return []

    async def _get_local_notebooks(self) -> List[Dict[str, str]]:
        """Get all local notebooks that have text content."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT
                        nte.notebook_uuid,
                        nte.notebook_name,
                        GROUP_CONCAT(nte.text, '\n\n') as full_text,
                        COUNT(*) as page_count,
                        MAX(nte.updated_at) as last_updated
                    FROM notebook_text_extractions nte
                    WHERE nte.text IS NOT NULL AND LENGTH(nte.text) > 0
                    GROUP BY nte.notebook_uuid, nte.notebook_name
                    ORDER BY last_updated DESC
                ''')

                notebooks = []
                for row in cursor.fetchall():
                    notebook_uuid, notebook_name, full_text, page_count, last_updated = row

                    # Generate content hash for matching
                    content_hash = hashlib.md5(full_text.encode('utf-8')).hexdigest()

                    notebooks.append({
                        'notebook_uuid': notebook_uuid,
                        'notebook_name': notebook_name or 'Untitled',
                        'full_text': full_text,
                        'page_count': page_count,
                        'last_updated': last_updated,
                        'content_hash': content_hash
                    })

                return notebooks

        except Exception as e:
            logger.error(f"Error getting local notebooks: {e}")
            return []

    async def _match_pages_to_notebooks(self, notion_pages: List[Dict], local_notebooks: List[Dict]) -> List[Dict]:
        """Match Notion pages to local notebooks based on available criteria."""
        matches = []

        # First, match by UUID if we have that info
        notion_uuids = {page.get('notebook_uuid') for page in notion_pages if page.get('notebook_uuid')}
        local_uuids = {nb['notebook_uuid'] for nb in local_notebooks}

        for notebook in local_notebooks:
            if notebook['notebook_uuid'] in notion_uuids:
                # Find the corresponding Notion page
                notion_page = next(
                    page for page in notion_pages
                    if page.get('notebook_uuid') == notebook['notebook_uuid']
                )

                matches.append({
                    'notebook_uuid': notebook['notebook_uuid'],
                    'notebook_name': notebook['notebook_name'],
                    'notion_page_id': notion_page['notion_page_id'],
                    'content_hash': notebook['content_hash'],
                    'match_method': 'uuid',
                    'page_count': notebook['page_count']
                })

        logger.info(f"Matched {len(matches)} notebooks by UUID")

        # TODO: Add more sophisticated matching methods:
        # - Title similarity
        # - Content hash comparison (if we can get Notion page content)
        # - Creation date correlation

        return matches

    async def _create_sync_record(self, match: Dict[str, str]) -> None:
        """Create a sync record for a matched notebook/page pair."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Create metadata
                metadata = {
                    'notebook_name': match['notebook_name'],
                    'page_count': match['page_count'],
                    'match_method': match['match_method'],
                    'baseline_establishment': True,
                    'created_at': datetime.now().isoformat()
                }

                # Insert sync record
                cursor.execute('''
                    INSERT OR REPLACE INTO sync_records
                    (content_hash, target_name, external_id, item_type, status,
                     item_id, metadata, created_at, updated_at, synced_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    match['content_hash'],
                    'notion',
                    match['notion_page_id'],
                    'notebook',
                    'success',
                    match['notebook_uuid'],
                    str(metadata),  # Convert to JSON string
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    datetime.now().isoformat()
                ))

                conn.commit()
                logger.info(f"Created sync record for notebook: {match['notebook_name']}")

        except Exception as e:
            logger.error(f"Error creating sync record: {e}")
            raise


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Establish Notion sync baseline')
    parser.add_argument('--dry-run', action='store_true', default=True,
                       help='Only simulate the process (default: True)')
    parser.add_argument('--execute', action='store_true', default=False,
                       help='Actually execute the baseline establishment')
    parser.add_argument('--database-path', type=str,
                       help='Database path (default: from config)')

    args = parser.parse_args()

    # Determine if this is a dry run
    dry_run = not args.execute

    if dry_run:
        logger.info("🧪 DRY RUN MODE - No changes will be made")
    else:
        logger.info("🚀 EXECUTION MODE - Changes will be made to database")
        confirmation = input("Are you sure you want to proceed? (yes/no): ")
        if confirmation.lower() != 'yes':
            logger.info("Aborted by user")
            return

    try:
        # Get configuration
        from utils.config import Config
        config = Config()

        # Get database path
        db_path = args.database_path or config.get('database.path')
        if not db_path:
            logger.error("No database path specified")
            return

        # Get Notion credentials
        notion_token = get_notion_api_key()
        database_id = get_notion_database_id()

        if not notion_token or not database_id:
            logger.error("Notion credentials not found. Please configure NOTION_TOKEN and NOTION_DATABASE_ID")
            return

        # Initialize components
        db_manager = DatabaseManager(db_path)
        establisher = NotionBaselineEstablisher(db_manager, notion_token, database_id)

        # Run baseline establishment
        stats = await establisher.establish_baseline(dry_run=dry_run)

        if stats['errors'] == 0:
            logger.info("✅ Baseline establishment completed successfully")
        else:
            logger.warning(f"⚠️  Baseline establishment completed with {stats['errors']} errors")

    except Exception as e:
        logger.error(f"❌ Error in baseline establishment: {e}")
        return 1

    return 0


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)