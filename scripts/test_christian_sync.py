#!/usr/bin/env python3
"""
Test sync for Christian notebook to verify the fixed incremental change detection.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager
from src.integrations.notion_sync import NotionNotebookSync
from src.integrations.notion_incremental import NotionSyncTracker
from src.utils.config import Config

def main():
    config = Config('config/config.yaml')
    db_manager = DatabaseManager('./data/remarkable_pipeline.db')
    notion_sync = NotionNotebookSync(config, db_manager)
    sync_tracker = NotionSyncTracker(db_manager)
    
    christian_uuid = '80ecb1eb-0095-407c-b771-2ee063526101'
    
    # Check what changes are detected
    print("🔍 Checking changes for Christian notebook...")
    changes = sync_tracker.get_notebook_changes(christian_uuid)
    
    print(f"📊 Change Detection Results:")
    print(f"   Content changed: {changes['content_changed']}")
    print(f"   New pages: {len(changes['new_pages'])} {changes['new_pages']}")
    print(f"   Changed pages: {len(changes['changed_pages'])} {changes['changed_pages'][:10]}{'...' if len(changes['changed_pages']) > 10 else ''}")
    print(f"   Total pages: {changes['current_total_pages']}")
    print(f"   Last synced: {changes.get('last_synced', 'Never')}")
    
    # Test sync logic without actually calling Notion API
    if changes['content_changed'] and (changes['new_pages'] or changes['changed_pages']):
        all_changed_pages = set(changes['new_pages'] + changes['changed_pages'])
        print(f"✅ Would sync {len(all_changed_pages)} changed pages to Notion")
        print(f"   New pages: {changes['new_pages']}")
        print(f"   Modified pages: {changes['changed_pages'][:10]}{'...' if len(changes['changed_pages']) > 10 else ''}")
    else:
        print("❌ No content changes detected - would only update metadata")
    
    # Check current state in database
    print("\n💾 Database State:")
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check latest pages
        cursor.execute('''
            SELECT page_number, SUBSTR(text, 1, 80) as preview, confidence 
            FROM notebook_text_extractions 
            WHERE notebook_uuid = ? AND page_number >= 24
            ORDER BY page_number
        ''', (christian_uuid,))
        
        latest_pages = cursor.fetchall()
        for page in latest_pages:
            print(f"   Page {page[0]}: \"{page[1]}...\" (conf: {page[2]})")

if __name__ == '__main__':
    main()