#!/usr/bin/env python3

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager
from src.integrations.notion_incremental import NotionSyncTracker

def main():
    db = DatabaseManager('./data/remarkable_pipeline.db')
    tracker = NotionSyncTracker(db)
    notebook_uuid = 'e7e7a737-e5f8-4813-acda-8873cb496d09'
    
    print("🔍 Marton - Design sync status:")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Fix: Set sync record to 35 pages to trigger detection of missing pages 37-38
        cursor.execute('UPDATE notion_notebook_sync SET total_pages = 35 WHERE notebook_uuid = ?', (notebook_uuid,))
        conn.commit()
        print("✅ Updated sync record to 35 pages")
    
    # Now check what change detection finds
    changes = tracker.get_notebook_changes(notebook_uuid)
    print(f"📊 After fix:")
    print(f"   Content changed: {changes['content_changed']}")
    print(f"   New pages: {changes['new_pages']}")
    print(f"   Changed pages: {changes['changed_pages']}")
    print(f"   Current total: {changes['current_total_pages']}")

if __name__ == '__main__':
    main()