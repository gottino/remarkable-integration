#!/usr/bin/env python3
"""
Fix the Test for integration notebook by creating a new Notion page
since the existing one is not found (404 error).
"""

import sys
import os
sys.path.append(os.getcwd())

from src.integrations.notion_sync import NotionNotebookSync
from src.core.database import DatabaseManager
from src.utils.config import Config

def main():
    # Initialize
    config = Config('config/config.yaml')
    db_manager = DatabaseManager('./data/remarkable_pipeline.db')
    notion_sync = NotionNotebookSync(config, db_manager)
    
    test_uuid = '98afc255-97ee-4416-96db-ac9a16a33109'
    
    print('🔧 Fixing "Test for integration" notebook...')
    
    with db_manager.get_connection() as conn:
        # First, delete the old sync record with the invalid page ID
        cursor = conn.execute('SELECT notion_page_id FROM notion_notebook_sync WHERE notebook_uuid = ?', (test_uuid,))
        old_record = cursor.fetchone()
        
        if old_record:
            old_page_id = old_record[0]
            print(f'📝 Removing old sync record with invalid page ID: {old_page_id}')
            conn.execute('DELETE FROM notion_notebook_sync WHERE notebook_uuid = ?', (test_uuid,))
            conn.commit()
        
        # Fetch the notebook data
        all_notebooks = notion_sync.fetch_notebooks_from_db(conn, refresh_changed_metadata=False)
        notebooks = [nb for nb in all_notebooks if nb.uuid == test_uuid]
        
        if not notebooks:
            print('❌ Notebook not found in database')
            return
            
        notebook = notebooks[0]
        print(f'📖 Notebook: {notebook.name}')
        print(f'📄 Found {len(notebook.pages)} pages in database')
        
        # Create a new Notion page
        print('🆕 Creating new Notion page...')
        try:
            new_page_id = notion_sync.create_new_page(notebook)
            print(f'✅ Created new Notion page: {new_page_id}')
            
            # Verify the new sync record
            cursor = conn.execute('SELECT total_pages, last_synced FROM notion_notebook_sync WHERE notebook_uuid = ?', (test_uuid,))
            new_record = cursor.fetchone()
            if new_record:
                total_pages, last_synced = new_record
                print(f'📊 New sync record: {total_pages} pages, synced at {last_synced}')
            
        except Exception as e:
            print(f'❌ Error creating new page: {e}')
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()