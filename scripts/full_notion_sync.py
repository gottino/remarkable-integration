#!/usr/bin/env python3
"""
Full Notion Sync Script

Performs a complete sync of all handwritten notebooks from the local database to Notion.
Use this for initial setup or when you want to populate a fresh Notion database.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config
from src.core.database import DatabaseManager
from src.integrations.notion_sync import NotionNotebookSync
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Run full sync of all notebooks to Notion."""
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
        
        # Initialize database
        db_path = config.get('database.path')
        db_manager = DatabaseManager(db_path)
        
        # Initialize Notion sync client
        notion_sync = NotionNotebookSync(
            notion_token=notion_token,
            database_id=database_id,
            verify_ssl=False  # For corporate networks
        )
        
        logger.info("🚀 Starting full Notion sync...")
        logger.info(f"📁 Database: {db_path}")
        logger.info(f"📄 Notion database: {database_id}")
        
        # Perform full sync - use proper sync logic to handle existing pages
        with db_manager.get_connection() as conn:
            result = notion_sync.sync_all_notebooks(conn, update_existing=True)
            
            logger.info(f"✅ Full sync completed!")
            logger.info(f"📊 Synced {len(result)} notebooks to Notion:")
            
            for notebook_uuid, page_id in result.items():
                # Get notebook name from database
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT DISTINCT notebook_name FROM notebook_text_extractions WHERE notebook_uuid = ? LIMIT 1",
                    (notebook_uuid,)
                )
                result_row = cursor.fetchone()
                notebook_name = result_row[0] if result_row else "Unknown"
                
                logger.info(f"  📓 {notebook_name} -> {page_id}")
                
    except Exception as e:
        logger.error(f"❌ Full sync failed: {e}")
        raise

if __name__ == "__main__":
    main()