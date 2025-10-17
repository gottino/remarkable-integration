#!/usr/bin/env python3
"""
Verify and fix sync discrepancies between local database and Notion.

This script:
1. Identifies pages in DB with actual content
2. Checks if they're properly synced to Notion
3. Forces re-sync for pages that might have blank/placeholder text in Notion
"""

import sys
import sqlite3
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.database import DatabaseManager
from src.utils.config import Config
from src.integrations.notion_sync import NotionNotebookSync
from src.utils.api_keys import get_notion_api_key
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_pages_needing_resync(db_manager):
    """Find pages that have content in DB but might not be synced correctly to Notion."""

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Find all pages with actual content (not blank placeholders)
        cursor.execute('''
            SELECT
                nte.notebook_uuid,
                nte.notebook_name,
                nte.page_number,
                nte.text,
                nte.confidence,
                nps.last_synced,
                nps.last_synced_content
            FROM notebook_text_extractions nte
            LEFT JOIN notion_page_sync nps
                ON nte.notebook_uuid = nps.notebook_uuid
                AND nte.page_number = nps.page_number
            WHERE nte.text IS NOT NULL
                AND length(nte.text) > 50
                AND nte.text NOT LIKE '%This appears to be a blank%'
                AND nte.text NOT LIKE '%completely empty page%'
            ORDER BY nte.notebook_name, nte.page_number
        ''')

        pages = cursor.fetchall()

        # Categorize pages
        never_synced = []
        possibly_stale = []

        for row in pages:
            uuid, name, page_num, text, confidence, last_synced, synced_content = row

            if not last_synced:
                # Never synced
                never_synced.append({
                    'uuid': uuid,
                    'name': name,
                    'page_number': page_num,
                    'text_preview': text[:100],
                    'confidence': confidence
                })
            elif synced_content and synced_content != text:
                # Synced but content different
                if 'blank' in synced_content.lower() or 'empty page' in synced_content.lower():
                    possibly_stale.append({
                        'uuid': uuid,
                        'name': name,
                        'page_number': page_num,
                        'text_preview': text[:100],
                        'synced_preview': synced_content[:100] if synced_content else 'None',
                        'confidence': confidence
                    })

        return never_synced, possibly_stale


def force_resync_page(notion_client, db_manager, notebook_uuid, page_number):
    """Force a specific page to be re-synced to Notion."""

    with db_manager.get_connection() as conn:
        cursor = conn.cursor()

        # Get page content
        cursor.execute('''
            SELECT notebook_name, text, confidence, page_uuid
            FROM notebook_text_extractions
            WHERE notebook_uuid = ? AND page_number = ?
        ''', (notebook_uuid, page_number))

        row = cursor.fetchone()
        if not row:
            logger.error(f"Page not found: {notebook_uuid} page {page_number}")
            return False

        name, text, confidence, page_uuid = row

        # Find Notion page ID
        notion_page_id = notion_client.find_existing_page(notebook_uuid)
        if not notion_page_id:
            logger.error(f"Notion page not found for notebook: {name}")
            return False

        logger.info(f"🔄 Force resyncing {name} page {page_number} to Notion...")

        # Create a minimal Notebook object with just this page
        from src.core.database import Notebook, NotebookPage, NotebookMetadata

        page_obj = NotebookPage(
            page_number=page_number,
            text=text,
            confidence=confidence,
            page_uuid=page_uuid
        )

        # Get notebook metadata
        cursor.execute('''
            SELECT visible_name, full_path, last_modified, last_opened
            FROM notebook_metadata
            WHERE notebook_uuid = ?
        ''', (notebook_uuid,))

        meta_row = cursor.fetchone()
        if meta_row:
            metadata = NotebookMetadata(
                name=meta_row[0],
                full_path=meta_row[1],
                last_modified=meta_row[2],
                last_opened=meta_row[3]
            )
        else:
            metadata = None

        notebook = Notebook(
            uuid=notebook_uuid,
            name=name,
            pages=[page_obj],
            metadata=metadata
        )

        # Force update with this specific page marked as changed
        try:
            notion_client.update_existing_page(
                notion_page_id,
                notebook,
                changed_pages={page_number}
            )
            logger.info(f"✅ Successfully resynced {name} page {page_number}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to resync {name} page {page_number}: {e}")
            return False


def main():
    """Main verification and repair routine."""

    # Initialize
    config = Config()
    db_path = config.get('database.path', './data/remarkable_pipeline.db')
    db_manager = DatabaseManager(db_path)

    logger.info("🔍 Scanning for sync discrepancies...")

    # Find pages needing resync
    never_synced, possibly_stale = find_pages_needing_resync(db_manager)

    logger.info(f"\n📊 Results:")
    logger.info(f"  - Pages never synced: {len(never_synced)}")
    logger.info(f"  - Pages possibly stale in Notion: {len(possibly_stale)}")

    if never_synced:
        logger.info(f"\n📄 Pages never synced:")
        for page in never_synced[:10]:  # Show first 10
            logger.info(f"  - {page['name']} page {page['page_number']}: {page['text_preview']}...")
        if len(never_synced) > 10:
            logger.info(f"  ... and {len(never_synced) - 10} more")

    if possibly_stale:
        logger.info(f"\n⚠️  Pages possibly stale in Notion:")
        for page in possibly_stale:
            logger.info(f"  - {page['name']} page {page['page_number']}")
            logger.info(f"    DB: {page['text_preview']}...")
            logger.info(f"    Notion: {page['synced_preview']}...")

    # Ask for confirmation to fix
    if possibly_stale:
        response = input(f"\n🔧 Do you want to force resync {len(possibly_stale)} stale pages? (yes/no): ")

        if response.lower() in ['yes', 'y']:
            # Initialize Notion client
            notion_api_key = get_notion_api_key()
            database_id = config.get('integrations.notion.database_id')

            notion_client = NotionNotebookSync(notion_api_key, database_id)

            logger.info(f"\n🔄 Resyncing {len(possibly_stale)} pages...")

            success_count = 0
            for page in possibly_stale:
                if force_resync_page(
                    notion_client,
                    db_manager,
                    page['uuid'],
                    page['page_number']
                ):
                    success_count += 1

            logger.info(f"\n✅ Successfully resynced {success_count}/{len(possibly_stale)} pages")
        else:
            logger.info("Skipping resync")

    logger.info("\n✅ Verification complete")


if __name__ == '__main__':
    main()
