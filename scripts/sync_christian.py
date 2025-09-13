#!/usr/bin/env python3

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
    
    print("🔍 Testing fixed incremental sync for Christian...")
    changes = sync_tracker.get_notebook_changes(christian_uuid)
    
    print(f"📊 New pages to sync: {len(changes['new_pages'])} {changes['new_pages']}")
    print(f"📊 Changed pages: {len(changes['changed_pages'])} {changes['changed_pages'][:5]}{'...' if len(changes['changed_pages']) > 5 else ''}")
    
    if changes['new_pages']:
        with db_manager.get_connection() as conn:
            notebooks = notion_sync.fetch_notebooks_from_db(conn, refresh_changed_metadata=False)
            christian_notebook = next((nb for nb in notebooks if nb.uuid == christian_uuid), None)
            
            if christian_notebook:
                page_id = notion_sync.find_existing_page(christian_uuid)
                print(f"📝 Syncing {len(changes['new_pages'])} new pages to Notion page: {page_id}")
                
                new_pages_set = set(changes['new_pages'])
                notion_sync.update_existing_page(page_id, christian_notebook, new_pages_set)
                
                # Mark as synced
                sync_tracker.mark_notebook_synced(
                    christian_uuid, page_id,
                    changes['current_content_hash'],
                    changes['current_metadata_hash'], 
                    changes['current_total_pages']
                )
                print("✅ Christian notebook new pages synced successfully!")
            else:
                print("❌ Notebook not found")
    else:
        print("ℹ️ No new pages to sync")

if __name__ == '__main__':
    main()