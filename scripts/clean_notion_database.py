#!/usr/bin/env python3
"""
Clean Notion Database Script

Deletes all pages from the configured Notion database.
Use this before doing a full sync to start with a clean slate.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config
from src.integrations.notion_sync import NotionNotebookSync
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Clean all pages from the Notion database."""
    try:
        # Load configuration
        config = Config()
        
        # Check if Notion is enabled
        if not config.get('integrations.notion.enabled'):
            logger.error("❌ Notion integration is not enabled in config")
            return
        
        # Get Notion credentials
        notion_token = config.get('integrations.notion.api_token')
        database_id = config.get('integrations.notion.database_id')
        
        if not notion_token or not database_id:
            logger.error("❌ Notion API token or database ID not configured")
            return
        
        # Initialize Notion sync client
        notion_sync = NotionNotebookSync(
            notion_token=notion_token,
            database_id=database_id,
            verify_ssl=False  # For corporate networks
        )
        
        logger.info("🧹 Starting Notion database cleanup...")
        logger.info(f"📄 Notion database: {database_id}")
        
        # Get all pages in the database (including archived ones)
        all_pages = []
        has_more = True
        start_cursor = None
        
        while has_more:
            query_params = {"database_id": database_id}
            if start_cursor:
                query_params["start_cursor"] = start_cursor
                
            response = notion_sync.client.databases.query(**query_params)
            all_pages.extend(response["results"])
            has_more = response["has_more"]
            start_cursor = response.get("next_cursor")
        
        pages = all_pages
        
        if not pages:
            logger.info("✅ Database is already empty")
            return
        
        logger.info(f"🗑️ Found {len(pages)} pages to delete")
        
        # Show what will be deleted
        logger.info(f"⚠️ Will archive ALL {len(pages)} pages from Notion database")
        logger.info(f"Database ID: {database_id}")
        
        # Delete all pages
        deleted_count = 0
        for page in pages:
            try:
                page_id = page["id"]
                title = "Unknown"
                
                # Try to get page title for logging
                if "properties" in page and "Name" in page["properties"]:
                    title_prop = page["properties"]["Name"]
                    if "title" in title_prop and title_prop["title"]:
                        title = title_prop["title"][0]["text"]["content"]
                
                # Check if page is already archived
                if page.get("archived", False):
                    logger.info(f"📁 Already archived: {title}")
                else:
                    notion_sync.client.pages.update(page_id=page_id, archived=True)
                    logger.info(f"🗑️ Archived: {title}")
                deleted_count += 1
                
            except Exception as e:
                logger.error(f"❌ Failed to delete page {page_id}: {e}")
        
        logger.info(f"✅ Cleanup completed! Deleted {deleted_count}/{len(pages)} pages")
        
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        raise

if __name__ == "__main__":
    main()