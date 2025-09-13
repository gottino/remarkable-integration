#!/usr/bin/env python3
"""
Update all sync records with correct Notion page IDs.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager
from src.integrations.notion_sync import NotionNotebookSync
from src.utils.config import Config

def main():
    config = Config('config/config.yaml')
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    # Create notion sync with SSL disabled
    notion_token = config.get('integrations.notion.api_token')
    database_id = config.get('integrations.notion.database_id')
    notion_sync = NotionNotebookSync(notion_token, database_id, verify_ssl=False)
    
    print("🔍 Fetching all pages from Notion...")
    
    # Get all pages from Notion (handle pagination)
    notion_pages = {}
    has_more = True
    start_cursor = None
    
    while has_more:
        query_params = {"database_id": database_id, "page_size": 100}
        if start_cursor:
            query_params["start_cursor"] = start_cursor
            
        response = notion_sync.client.databases.query(**query_params)
        
        for page in response["results"]:
            page_id = page["id"]
            
            # Extract notebook UUID
            if "Notebook UUID" in page["properties"]:
                uuid_prop = page["properties"]["Notebook UUID"]
                if uuid_prop["type"] == "rich_text" and uuid_prop["rich_text"]:
                    notebook_uuid = uuid_prop["rich_text"][0]["text"]["content"]
                    notion_pages[notebook_uuid] = page_id
        
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")
    
    print(f"📊 Found {len(notion_pages)} pages in Notion")
    
    # Update sync records with correct page IDs
    print("🔧 Updating sync records with correct page IDs...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        updated_count = 0
        
        for notebook_uuid, correct_page_id in notion_pages.items():
            cursor.execute('''
                UPDATE notion_notebook_sync 
                SET notion_page_id = ? 
                WHERE notebook_uuid = ?
            ''', (correct_page_id, notebook_uuid))
            
            if cursor.rowcount > 0:
                updated_count += 1
        
        conn.commit()
        print(f"✅ Updated {updated_count} sync records with correct page IDs")

if __name__ == '__main__':
    main()