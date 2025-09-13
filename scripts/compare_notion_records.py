#!/usr/bin/env python3
"""
Compare Notion database contents with local sync records to identify mismatches.
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
    
    print("🔍 Fetching all pages from Notion database...")
    
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
            
            # Extract notebook UUID and name from properties
            notebook_uuid = None
            notebook_name = None
            
            if "Notebook UUID" in page["properties"]:
                uuid_prop = page["properties"]["Notebook UUID"]
                if uuid_prop["type"] == "rich_text" and uuid_prop["rich_text"]:
                    notebook_uuid = uuid_prop["rich_text"][0]["text"]["content"]
            
            if "Name" in page["properties"]:
                name_prop = page["properties"]["Name"]
                if name_prop["type"] == "title" and name_prop["title"]:
                    notebook_name = name_prop["title"][0]["text"]["content"]
            
            if notebook_uuid:
                notion_pages[notebook_uuid] = {
                    'page_id': page_id,
                    'name': notebook_name
                }
        
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")
    
    print(f"📊 Found {len(notion_pages)} pages in Notion")
    
    # Get sync records from database
    print("\n🔍 Comparing with database sync records...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT nns.notebook_uuid, nns.notion_page_id, nm.visible_name, nns.total_pages
            FROM notion_notebook_sync nns
            LEFT JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
            ORDER BY nm.visible_name
        ''')
        
        sync_records = cursor.fetchall()
    
    print(f"📊 Found {len(sync_records)} sync records in database\n")
    
    # Compare records using notebook UUID as primary key
    matches = 0
    dash_only_mismatches = 0
    real_mismatches = 0
    missing_in_notion = 0
    
    for notebook_uuid, stored_page_id, name, total_pages in sync_records:
        if notebook_uuid in notion_pages:
            actual_page_id = notion_pages[notebook_uuid]['page_id']
            actual_name = notion_pages[notebook_uuid]['name']
            
            # Normalize both IDs by removing dashes for comparison
            stored_normalized = stored_page_id.replace('-', '')
            actual_normalized = actual_page_id.replace('-', '')
            
            if stored_page_id == actual_page_id:
                matches += 1
                print(f"✅ {name}: Page IDs match exactly")
            elif stored_normalized == actual_normalized:
                dash_only_mismatches += 1
                print(f"📝 {name}: Only dash format difference")
                print(f"    Stored: {stored_page_id}")
                print(f"    Actual: {actual_page_id}")
            else:
                real_mismatches += 1
                print(f"❌ {name}: Real page ID mismatch")
                print(f"    Stored: {stored_page_id}")
                print(f"    Actual: {actual_page_id}")
        else:
            missing_in_notion += 1
            print(f"⚠️ {name}: Not found in Notion (UUID: {notebook_uuid})")
    
    print(f"\n📊 Summary:")
    print(f"   ✅ Exact matches: {matches}")
    print(f"   📝 Dash-only differences: {dash_only_mismatches}")
    print(f"   ❌ Real mismatches: {real_mismatches}")
    print(f"   ⚠️ Missing in Notion: {missing_in_notion}")

if __name__ == '__main__':
    main()