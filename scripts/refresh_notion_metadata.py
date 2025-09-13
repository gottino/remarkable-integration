#!/usr/bin/env python3
"""
Notion Metadata Refresh Script

Refreshes only the metadata properties of existing Notion pages without touching content.
This updates Last Viewed, Last Modified, Tags (from path), and Total Pages.
"""

import sys
import os
from pathlib import Path
from datetime import datetime

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
    """Refresh metadata for all existing Notion pages."""
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
        
        logger.info("🔄 Starting Notion metadata refresh...")
        logger.info(f"📁 Database: {db_path}")
        logger.info(f"📄 Notion database: {database_id}")
        
        # Refresh metadata in local database first
        with db_manager.get_connection() as conn:
            notion_sync._refresh_metadata_for_sync(conn)
            
            # Fetch all notebooks from database
            notebooks = notion_sync.fetch_notebooks_from_db(conn)
            logger.info(f"📚 Found {len(notebooks)} notebooks in database")
            
            refreshed_count = 0
            
            for notebook in notebooks:
                # Find existing page
                existing_page_id = notion_sync.find_existing_page(notebook.uuid)
                
                if existing_page_id:
                    logger.info(f"🔄 Refreshing metadata for: {notebook.name}")
                    
                    # Build properties to update (same as in file watcher)
                    properties = {
                        "Total Pages": {"number": notebook.total_pages},
                        "Last Updated": {"date": {"start": datetime.now().isoformat()}}
                    }
                    
                    # Add all metadata properties
                    if notebook.metadata:
                        # Add path tags
                        if notebook.metadata.path_tags:
                            properties["Tags"] = {
                                "multi_select": [
                                    {"name": tag} for tag in notebook.metadata.path_tags
                                ]
                            }
                        
                        # Add last modified date
                        if notebook.metadata.last_modified:
                            properties["Last Modified"] = {
                                "date": {
                                    "start": notebook.metadata.last_modified.isoformat()
                                }
                            }
                        
                        # Add last viewed date
                        if notebook.metadata.last_opened:
                            properties["Last Viewed"] = {
                                "date": {
                                    "start": notebook.metadata.last_opened.isoformat()
                                }
                            }
                    
                    # Update only the properties, not the content
                    notion_sync.client.pages.update(page_id=existing_page_id, properties=properties)
                    refreshed_count += 1
                    
                else:
                    logger.warning(f"⚠️ No existing Notion page found for: {notebook.name}")
            
            logger.info(f"✅ Metadata refresh completed! Updated {refreshed_count} Notion pages")
            
    except Exception as e:
        logger.error(f"❌ Metadata refresh failed: {e}")
        raise

if __name__ == "__main__":
    main()