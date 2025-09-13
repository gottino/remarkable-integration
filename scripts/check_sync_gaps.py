#!/usr/bin/env python3
"""
Check for notebooks where database has more pages than Notion sync records
and optionally sync the missing content.
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
    notion_sync = NotionNotebookSync(config, db)
    
    print("🔍 Checking for sync gaps across all notebooks...\n")
    
    gaps = []
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Find all notebooks with sync records
        cursor.execute('''
            SELECT nns.notebook_uuid, nm.visible_name, nns.total_pages, nns.last_synced, nns.notion_page_id
            FROM notion_notebook_sync nns
            LEFT JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
            ORDER BY nm.visible_name
        ''')
        
        sync_records = cursor.fetchall()
        
        for notebook_uuid, name, synced_pages, last_synced, page_id in sync_records:
            # Count actual pages in database
            cursor.execute('''
                SELECT COUNT(*) 
                FROM notebook_text_extractions 
                WHERE notebook_uuid = ? AND text IS NOT NULL AND length(text) > 0
            ''', (notebook_uuid,))
            
            actual_pages = cursor.fetchone()[0]
            
            if actual_pages > synced_pages:
                gap = actual_pages - synced_pages
                gaps.append({
                    'uuid': notebook_uuid,
                    'name': name or 'Unknown',
                    'actual': actual_pages,
                    'synced': synced_pages,
                    'gap': gap,
                    'page_id': page_id,
                    'last_synced': last_synced
                })
                
                print(f"📊 {name}: {actual_pages} pages in DB, {synced_pages} synced → {gap} missing")
    
    print(f"\n📈 Found {len(gaps)} notebooks with sync gaps")
    
    if gaps and input("\n❓ Sync missing pages? (y/n): ").lower() == 'y':
        print("\n🔄 Starting sync for notebooks with gaps...")
        
        for gap in gaps:
            try:
                print(f"\n📝 Processing {gap['name']}...")
                changes = sync_tracker.get_notebook_changes(gap['uuid'])
                
                if changes['new_pages']:
                    print(f"   New pages to sync: {changes['new_pages']}")
                    
                    # Get notebook and sync
                    with db.get_connection() as conn:
                        notebooks = notion_sync.fetch_notebooks_from_db(conn, refresh_changed_metadata=False)
                        notebook = next((nb for nb in notebooks if nb.uuid == gap['uuid']), None)
                        
                        if notebook:
                            new_pages_set = set(changes['new_pages'])
                            notion_sync.update_existing_page(gap['page_id'], notebook, new_pages_set)
                            
                            # Mark as synced
                            sync_tracker.mark_notebook_synced(
                                gap['uuid'], gap['page_id'],
                                changes['current_content_hash'],
                                changes['current_metadata_hash'], 
                                changes['current_total_pages']
                            )
                            print(f"   ✅ Synced {len(new_pages_set)} new pages")
                        else:
                            print(f"   ❌ Notebook not found")
                else:
                    print(f"   ℹ️ No new pages detected (change detection issue)")
                    
            except Exception as e:
                print(f"   ❌ Error: {e}")

if __name__ == '__main__':
    main()