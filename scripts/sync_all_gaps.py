#!/usr/bin/env python3
"""
Automatically sync all notebooks where database has more content than Notion.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager
from src.integrations.notion_incremental import NotionSyncTracker
from src.integrations.notion_sync import NotionNotebookSync
from src.utils.config import Config

def main():
    config = Config('config/config.yaml')
    db = DatabaseManager('./data/remarkable_pipeline.db')
    sync_tracker = NotionSyncTracker(db)
    
    # Create NotionNotebookSync with SSL verification disabled
    notion_token = config.get('integrations.notion.api_token')
    database_id = config.get('integrations.notion.database_id')
    notion_sync = NotionNotebookSync(notion_token, database_id, verify_ssl=False)
    
    print("🔄 Auto-syncing all notebooks with content gaps...\n")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Find notebooks with gaps
        cursor.execute('''
            SELECT nns.notebook_uuid, nm.visible_name, nns.total_pages, nns.notion_page_id
            FROM notion_notebook_sync nns
            LEFT JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
            ORDER BY nm.visible_name
        ''')
        
        sync_records = cursor.fetchall()
        synced_count = 0
        
        for notebook_uuid, name, synced_pages, page_id in sync_records:
            # Count actual pages
            cursor.execute('''
                SELECT COUNT(*) 
                FROM notebook_text_extractions 
                WHERE notebook_uuid = ? AND text IS NOT NULL AND length(text) > 0
            ''', (notebook_uuid,))
            
            actual_pages = cursor.fetchone()[0]
            
            if actual_pages > synced_pages:
                gap = actual_pages - synced_pages
                print(f"📝 {name}: syncing {gap} missing pages...")
                
                try:
                    # Check what changes are detected
                    changes = sync_tracker.get_notebook_changes(notebook_uuid)
                    
                    if changes['new_pages']:
                        # Get notebook and sync
                        notebooks = notion_sync.fetch_notebooks_from_db(conn, refresh_changed_metadata=False)
                        notebook = next((nb for nb in notebooks if nb.uuid == notebook_uuid), None)
                        
                        if notebook:
                            new_pages_set = set(changes['new_pages'])
                            notion_sync.update_existing_page(page_id, notebook, new_pages_set)
                            
                            # Mark as synced
                            sync_tracker.mark_notebook_synced(
                                notebook_uuid, page_id,
                                changes['current_content_hash'],
                                changes['current_metadata_hash'], 
                                changes['current_total_pages']
                            )
                            
                            synced_count += 1
                            print(f"   ✅ Synced {len(new_pages_set)} pages")
                        else:
                            print(f"   ❌ Notebook not found")
                    else:
                        # Force detection by reducing sync record count
                        cursor.execute('''
                            UPDATE notion_notebook_sync 
                            SET total_pages = ? 
                            WHERE notebook_uuid = ?
                        ''', (synced_pages - gap, notebook_uuid))
                        conn.commit()
                        print(f"   🔧 Fixed sync record to trigger detection")
                        
                except Exception as e:
                    print(f"   ❌ Error: {e}")
    
    print(f"\n🎉 Successfully synced {synced_count} notebooks with gaps")

if __name__ == '__main__':
    main()