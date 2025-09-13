#!/usr/bin/env python3
"""
Final sync gap analysis and missing content sync after page ID fixes.
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
    
    print("🔍 Analyzing sync gaps after page ID fixes...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Find notebooks with gaps (database pages > synced pages)
        cursor.execute('''
            SELECT nns.notebook_uuid, nm.visible_name, nns.total_pages, nns.notion_page_id,
                   COUNT(nte.page_number) as actual_pages
            FROM notion_notebook_sync nns
            LEFT JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
            LEFT JOIN notebook_text_extractions nte ON nns.notebook_uuid = nte.notebook_uuid
                AND nte.text IS NOT NULL AND length(nte.text) > 0
            GROUP BY nns.notebook_uuid, nm.visible_name, nns.total_pages, nns.notion_page_id
            HAVING actual_pages > nns.total_pages
            ORDER BY (actual_pages - nns.total_pages) DESC
        ''')
        
        gaps = cursor.fetchall()
        
        if not gaps:
            print("✅ No sync gaps found - all content is up to date!")
            return
            
        print(f"\n📊 Found {len(gaps)} notebooks with sync gaps:")
        total_missing = 0
        
        for notebook_uuid, name, synced_pages, page_id, actual_pages in gaps:
            gap = actual_pages - synced_pages
            total_missing += gap
            print(f"📝 {name}: {gap} missing pages ({actual_pages} actual vs {synced_pages} synced)")
        
        print(f"\n🔄 Total missing pages to sync: {total_missing}")
        
        if total_missing > 0:
            print("\n⚠️ Run the following command to sync all missing content:")
            print("poetry run python sync_all_gaps.py")
        
if __name__ == '__main__':
    main()