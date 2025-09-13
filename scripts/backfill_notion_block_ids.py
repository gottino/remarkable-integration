#!/usr/bin/env python3
"""
Backfill missing Notion block IDs for synced pages.

This script scans Notion pages that have been synced but are missing block ID mappings,
then retrieves and stores the block IDs for each page within those notebooks.
"""

import sqlite3
import asyncio
import logging
from typing import Dict, List, Tuple, Optional
import sys
import os

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.integrations.notion_sync import NotionNotebookSync
from src.utils.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NotionBlockIDBackfiller:
    """Backfills missing Notion block IDs for already synced pages."""
    
    def __init__(self, db_path: str = './data/remarkable_pipeline.db'):
        self.db_path = db_path
        self.config = Config()
        self.notion_sync = None
    
    async def initialize_notion_sync(self):
        """Initialize Notion sync client."""
        notion_token = self.config.get('integrations.notion.api_token')
        database_id = self.config.get('integrations.notion.database_id') 
        
        if not notion_token or not database_id:
            raise ValueError("Notion API token and database ID must be configured")
            
        self.notion_sync = NotionNotebookSync(notion_token, database_id, verify_ssl=False)
    
    def get_notebooks_missing_block_ids(self) -> List[Tuple[str, str, str]]:
        """Get notebooks that are synced to Notion but missing block ID mappings."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Find notebooks synced to Notion but missing block mappings
            cursor.execute('''
                SELECT 
                    nns.notebook_uuid,
                    nns.notion_page_id,
                    nm.visible_name
                FROM notion_notebook_sync nns
                LEFT JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
                LEFT JOIN notion_page_blocks npb ON nns.notebook_uuid = npb.notebook_uuid
                WHERE nns.notion_page_id IS NOT NULL
                GROUP BY nns.notebook_uuid, nns.notion_page_id
                HAVING COUNT(npb.notion_block_id) = 0
                ORDER BY nm.visible_name
            ''')
            
            return cursor.fetchall()
    
    def get_missing_page_block_mappings(self) -> List[Tuple[str, str, str, int]]:
        """Get individual pages that need block ID mappings."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Find individual pages that have been extracted but don't have block mappings
            cursor.execute('''
                SELECT DISTINCT
                    nte.notebook_uuid,
                    nns.notion_page_id,
                    nm.visible_name,
                    nte.page_number
                FROM notebook_text_extractions nte
                JOIN notion_notebook_sync nns ON nte.notebook_uuid = nns.notebook_uuid
                JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
                LEFT JOIN notion_page_blocks npb ON (
                    nte.notebook_uuid = npb.notebook_uuid 
                    AND nte.page_number = npb.page_number
                )
                WHERE nns.notion_page_id IS NOT NULL
                    AND npb.notion_block_id IS NULL
                ORDER BY nm.visible_name, nte.page_number
            ''')
            
            return cursor.fetchall()
    
    def get_synced_pages_for_notebook(self, notebook_uuid: str) -> List[int]:
        """Get page numbers that have been extracted for a notebook."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get pages that have been extracted (have text content)
            cursor.execute('''
                SELECT DISTINCT page_number 
                FROM notebook_text_extractions 
                WHERE notebook_uuid = ?
                ORDER BY page_number
            ''', (notebook_uuid,))
            
            return [row[0] for row in cursor.fetchall()]
    
    async def find_page_block_in_notion(self, notion_page_id: str, page_number: int) -> Optional[str]:
        """Find the toggle block ID for a specific page number within a Notion page."""
        try:
            # Get all blocks in the page
            response = self.notion_sync.client.blocks.children.list(block_id=notion_page_id)
            
            # Look for toggle block with the proper page format
            page_identifier = f"📄 Page {page_number}"
            
            for block in response.get('results', []):
                if block.get('type') == 'toggle':
                    # Check toggle heading for the proper page format
                    rich_text = block.get('toggle', {}).get('rich_text', [])
                    if rich_text:
                        title = rich_text[0].get('text', {}).get('content', '')
                        if title.startswith(page_identifier):
                            return block['id']
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding page toggle block in Notion: {e}")
            return None
    
    def store_block_mapping(self, notebook_uuid: str, page_number: int, 
                          notion_page_id: str, notion_block_id: str) -> bool:
        """Store a block ID mapping in the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO notion_page_blocks 
                    (notebook_uuid, page_number, notion_page_id, notion_block_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (notebook_uuid, page_number, notion_page_id, notion_block_id))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Failed to store block mapping: {e}")
            return False
    
    async def backfill_notebook_block_ids(self, notebook_uuid: str, notion_page_id: str, 
                                        notebook_name: str) -> int:
        """Backfill block IDs for all pages in a notebook."""
        logger.info(f"🔍 Backfilling block IDs for: {notebook_name}")
        
        # Get pages that have been synced for this notebook
        synced_pages = self.get_synced_pages_for_notebook(notebook_uuid)
        
        if not synced_pages:
            logger.warning(f"  ⚠️  No synced pages found for {notebook_name}")
            return 0
        
        backfilled_count = 0
        
        for page_number in synced_pages:
            try:
                # Find the block ID for this page
                block_id = await self.find_page_block_in_notion(notion_page_id, page_number)
                
                if block_id:
                    # Store the mapping
                    if self.store_block_mapping(notebook_uuid, page_number, notion_page_id, block_id):
                        logger.info(f"  ✅ Page {page_number}: {block_id[:20]}...")
                        backfilled_count += 1
                    else:
                        logger.error(f"  ❌ Failed to store mapping for page {page_number}")
                else:
                    logger.warning(f"  ⚠️  Page {page_number}: No block found in Notion")
                
                # Small delay to be nice to Notion API
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"  ❌ Error processing page {page_number}: {e}")
        
        logger.info(f"  📊 Backfilled {backfilled_count}/{len(synced_pages)} pages for {notebook_name}")
        return backfilled_count
    
    async def backfill_individual_page(self, notebook_uuid: str, notion_page_id: str, 
                                     page_number: int, notebook_name: str) -> bool:
        """Backfill block ID for a single page."""
        try:
            # Find the block ID for this page
            block_id = await self.find_page_block_in_notion(notion_page_id, page_number)
            
            if block_id:
                # Store the mapping
                if self.store_block_mapping(notebook_uuid, page_number, notion_page_id, block_id):
                    logger.info(f"  ✅ {notebook_name} p{page_number}: {block_id[:20]}...")
                    return True
                else:
                    logger.error(f"  ❌ {notebook_name} p{page_number}: Failed to store mapping")
            else:
                logger.warning(f"  ⚠️  {notebook_name} p{page_number}: No block found in Notion")
            
            return False
            
        except Exception as e:
            logger.error(f"  ❌ {notebook_name} p{page_number}: Error - {e}")
            return False

    async def run_backfill(self, limit: Optional[int] = None, dry_run: bool = False, 
                          page_mode: bool = True):
        """Run the backfill process."""
        logger.info("🚀 Starting Notion block ID backfill process...")
        
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No changes will be made")
        
        # Initialize Notion client  
        if not dry_run:
            await self.initialize_notion_sync()
        
        if page_mode:
            # Page-level backfill (more granular)
            missing_pages = self.get_missing_page_block_mappings()
            
            if not missing_pages:
                logger.info("✅ All extracted pages already have block ID mappings!")
                return
            
            total_pages = len(missing_pages)
            if limit:
                missing_pages = missing_pages[:limit]
                
            logger.info(f"📊 Found {total_pages} individual pages missing block IDs")
            logger.info(f"🎯 Processing {len(missing_pages)} pages...")
            
            total_backfilled = 0
            current_notebook = None
            
            for i, (notebook_uuid, notion_page_id, notebook_name, page_number) in enumerate(missing_pages, 1):
                # Group output by notebook for cleaner display
                if current_notebook != notebook_name:
                    logger.info(f"\n📖 {notebook_name} ({notebook_uuid[:8]}...)")
                    current_notebook = notebook_name
                
                if dry_run:
                    logger.info(f"  🔍 Would backfill page {page_number}")
                else:
                    try:
                        if await self.backfill_individual_page(notebook_uuid, notion_page_id, 
                                                             page_number, notebook_name):
                            total_backfilled += 1
                        
                        # Small delay to be nice to Notion API
                        await asyncio.sleep(0.1)
                        
                    except Exception as e:
                        logger.error(f"  ❌ Failed to process page {page_number}: {e}")
            
            if not dry_run:
                logger.info(f"\n🎉 Page backfill complete! Total pages backfilled: {total_backfilled}")
            else:
                logger.info(f"\n🔍 Dry run complete! Found {len(missing_pages)} pages to process")
        
        else:
            # Notebook-level backfill (legacy approach)
            missing_notebooks = self.get_notebooks_missing_block_ids()
            
            if not missing_notebooks:
                logger.info("✅ All synced notebooks already have block ID mappings!")
                return
            
            total_notebooks = len(missing_notebooks)
            if limit:
                missing_notebooks = missing_notebooks[:limit]
                
            logger.info(f"📊 Found {total_notebooks} notebooks missing block IDs")
            logger.info(f"🎯 Processing {len(missing_notebooks)} notebooks...")
            
            total_backfilled = 0
            
            for i, (notebook_uuid, notion_page_id, notebook_name) in enumerate(missing_notebooks, 1):
                logger.info(f"\n📖 [{i}/{len(missing_notebooks)}] Processing: {notebook_name}")
                logger.info(f"   UUID: {notebook_uuid}")
                logger.info(f"   Notion Page: {notion_page_id}")
                
                if dry_run:
                    # Just count what would be processed
                    synced_pages = self.get_synced_pages_for_notebook(notebook_uuid)
                    logger.info(f"   Would backfill {len(synced_pages)} pages")
                else:
                    try:
                        backfilled = await self.backfill_notebook_block_ids(
                            notebook_uuid, notion_page_id, notebook_name
                        )
                        total_backfilled += backfilled
                        
                    except Exception as e:
                        logger.error(f"   ❌ Failed to process notebook: {e}")
            
            if not dry_run:
                logger.info(f"\n🎉 Backfill complete! Total pages backfilled: {total_backfilled}")
            else:
                logger.info(f"\n🔍 Dry run complete! Found {len(missing_notebooks)} notebooks to process")


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Backfill missing Notion block IDs')
    parser.add_argument('--limit', type=int, help='Limit number of items to process')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--notebook-mode', action='store_true', help='Use notebook-level backfill instead of page-level')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    backfiller = NotionBlockIDBackfiller()
    await backfiller.run_backfill(
        limit=args.limit, 
        dry_run=args.dry_run, 
        page_mode=not args.notebook_mode
    )


if __name__ == '__main__':
    asyncio.run(main())