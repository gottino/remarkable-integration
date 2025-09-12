#!/usr/bin/env python3
"""
Reverse Backfill: Notion-to-Database Block ID Mapping

This script takes a much more efficient approach by:
1. Getting all notebook pages from Notion database
2. Fetching all blocks for each page in bulk
3. Parsing page identifiers and matching to database records
4. Bulk inserting all block mappings at once

This is orders of magnitude faster than the individual page approach.
"""

import sqlite3
import asyncio
import logging
from typing import Dict, List, Tuple, Optional, Set
import sys
import os
import re

# Add the src directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.integrations.notion_sync import NotionNotebookSync
from src.utils.config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ReverseNotionBlockMapper:
    """Maps Notion blocks back to database records efficiently."""
    
    def __init__(self, db_path: str = './data/remarkable_pipeline.db'):
        self.db_path = db_path
        self.config = Config()
        self.notion_sync = None
        self.block_mappings = []  # [(notebook_uuid, page_number, notion_page_id, block_id)]
    
    async def initialize_notion_sync(self):
        """Initialize Notion sync client."""
        notion_token = self.config.get('integrations.notion.api_token')
        database_id = self.config.get('integrations.notion.database_id')
        
        if not notion_token or not database_id:
            raise ValueError("Notion API token and database ID must be configured")
            
        self.notion_sync = NotionNotebookSync(notion_token, database_id, verify_ssl=False)
    
    def get_synced_notebooks(self) -> List[Tuple[str, str, str]]:
        """Get all notebooks that have been synced to Notion."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    nns.notebook_uuid,
                    nns.notion_page_id,
                    nm.visible_name
                FROM notion_notebook_sync nns
                JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
                WHERE nns.notion_page_id IS NOT NULL
                ORDER BY nm.visible_name
            ''')
            
            return cursor.fetchall()
    
    def get_extracted_pages_for_notebook(self, notebook_uuid: str) -> Set[int]:
        """Get all page numbers that have been extracted for a notebook."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT DISTINCT page_number 
                FROM notebook_text_extractions 
                WHERE notebook_uuid = ?
            ''', (notebook_uuid,))
            
            return {row[0] for row in cursor.fetchall()}
    
    async def fetch_all_blocks_for_page(self, notion_page_id: str) -> List[Dict]:
        """Fetch all blocks for a Notion page."""
        try:
            response = self.notion_sync.client.blocks.children.list(block_id=notion_page_id)
            return response.get('results', [])
        except Exception as e:
            logger.error(f"Error fetching blocks for page {notion_page_id}: {e}")
            return []
    
    def parse_page_blocks(self, blocks: List[Dict], notebook_uuid: str, 
                         notion_page_id: str, extracted_pages: Set[int]) -> List[Tuple[str, int, str, str]]:
        """Parse blocks to find page toggle blocks and extract mappings."""
        mappings = []
        
        # Pattern to match: "📄 Page {number}" (with optional confidence indicator)
        page_pattern = re.compile(r'^📄 Page (\d+)')
        
        for block in blocks:
            if block.get('type') != 'toggle':
                continue
            
            # Extract title from toggle block
            rich_text = block.get('toggle', {}).get('rich_text', [])
            if not rich_text:
                continue
            
            title = rich_text[0].get('text', {}).get('content', '')
            match = page_pattern.match(title)
            
            if match:
                page_number = int(match.group(1))
                block_id = block['id']
                
                # Only include if this page was actually extracted to our database
                if page_number in extracted_pages:
                    mappings.append((notebook_uuid, page_number, notion_page_id, block_id))
                    logger.debug(f"Found mapping: {notebook_uuid[:8]}... p{page_number} -> {block_id[:20]}...")
        
        return mappings
    
    async def process_notebook(self, notebook_uuid: str, notion_page_id: str, 
                              notebook_name: str) -> int:
        """Process a single notebook and extract all its block mappings."""
        logger.info(f"📖 Processing: {notebook_name} ({notebook_uuid[:8]}...)")
        
        # Get pages that have been extracted for this notebook
        extracted_pages = self.get_extracted_pages_for_notebook(notebook_uuid)
        
        if not extracted_pages:
            logger.warning(f"  ⚠️  No extracted pages found for {notebook_name}")
            return 0
        
        logger.info(f"  📄 Found {len(extracted_pages)} extracted pages")
        
        # Fetch all blocks from Notion page
        blocks = await self.fetch_all_blocks_for_page(notion_page_id)
        
        if not blocks:
            logger.warning(f"  ⚠️  No blocks found in Notion page")
            return 0
        
        # Parse blocks to find page mappings
        mappings = self.parse_page_blocks(blocks, notebook_uuid, notion_page_id, extracted_pages)
        
        # Add to our collection
        self.block_mappings.extend(mappings)
        
        logger.info(f"  ✅ Found {len(mappings)} page block mappings")
        return len(mappings)
    
    def bulk_insert_mappings(self, dry_run: bool = False) -> int:
        """Bulk insert all collected block mappings."""
        if not self.block_mappings:
            logger.warning("No block mappings to insert")
            return 0
        
        if dry_run:
            logger.info(f"🔍 DRY RUN: Would insert {len(self.block_mappings)} block mappings")
            for notebook_uuid, page_num, notion_page_id, block_id in self.block_mappings[:5]:
                logger.info(f"  Would map: {notebook_uuid[:8]}... p{page_num} -> {block_id[:20]}...")
            if len(self.block_mappings) > 5:
                logger.info(f"  ... and {len(self.block_mappings) - 5} more")
            return len(self.block_mappings)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Prepare data for bulk insert
                insert_data = [
                    (notebook_uuid, page_number, notion_page_id, block_id)
                    for notebook_uuid, page_number, notion_page_id, block_id in self.block_mappings
                ]
                
                # Use INSERT OR REPLACE to handle duplicates
                cursor.executemany('''
                    INSERT OR REPLACE INTO notion_page_blocks 
                    (notebook_uuid, page_number, notion_page_id, notion_block_id, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', insert_data)
                
                conn.commit()
                rows_inserted = cursor.rowcount
                
                logger.info(f"✅ Successfully inserted {rows_inserted} block mappings")
                return rows_inserted
                
        except Exception as e:
            logger.error(f"Failed to bulk insert mappings: {e}")
            return 0
    
    async def run_reverse_backfill(self, limit: Optional[int] = None, dry_run: bool = False):
        """Run the reverse backfill process (Notion → Database)."""
        logger.info("🚀 Starting Reverse Notion block mapping (Notion → Database)...")
        
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No changes will be made")
        
        # Initialize Notion client
        if not dry_run:
            await self.initialize_notion_sync()
        
        # Get all notebooks synced to Notion
        synced_notebooks = self.get_synced_notebooks()
        
        if not synced_notebooks:
            logger.info("⚠️  No notebooks found synced to Notion")
            return
        
        total_notebooks = len(synced_notebooks)
        if limit:
            synced_notebooks = synced_notebooks[:limit]
        
        logger.info(f"📊 Found {total_notebooks} notebooks synced to Notion")
        logger.info(f"🎯 Processing {len(synced_notebooks)} notebooks...")
        
        total_mappings = 0
        
        for i, (notebook_uuid, notion_page_id, notebook_name) in enumerate(synced_notebooks, 1):
            logger.info(f"\n[{i}/{len(synced_notebooks)}] {notebook_name}")
            logger.info(f"  UUID: {notebook_uuid}")
            logger.info(f"  Notion Page: {notion_page_id}")
            
            if dry_run:
                # Just count extracted pages
                extracted_pages = self.get_extracted_pages_for_notebook(notebook_uuid)
                logger.info(f"  Would process {len(extracted_pages)} extracted pages")
            else:
                try:
                    mappings = await self.process_notebook(notebook_uuid, notion_page_id, notebook_name)
                    total_mappings += mappings
                    
                    # Small delay to be nice to Notion API
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"  ❌ Failed to process notebook: {e}")
        
        # Bulk insert all mappings
        if not dry_run:
            if self.block_mappings:
                inserted = self.bulk_insert_mappings(dry_run=False)
                logger.info(f"\n🎉 Reverse backfill complete!")
                logger.info(f"   📊 Total mappings collected: {len(self.block_mappings)}")
                logger.info(f"   💾 Successfully inserted: {inserted}")
            else:
                logger.info(f"\n⚠️  No block mappings found to insert")
        else:
            self.bulk_insert_mappings(dry_run=True)
            logger.info(f"\n🔍 Dry run complete!")


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Reverse backfill Notion block IDs (Notion → Database)')
    parser.add_argument('--limit', type=int, help='Limit number of notebooks to process')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    mapper = ReverseNotionBlockMapper()
    await mapper.run_reverse_backfill(limit=args.limit, dry_run=args.dry_run)


if __name__ == '__main__':
    asyncio.run(main())