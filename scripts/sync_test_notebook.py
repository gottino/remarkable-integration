#!/usr/bin/env python3
"""
Manual sync script for the 'Test for integration' notebook.
This will update the existing Notion page with all 6 pages.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.integrations.notion_sync import NotionNotebookSync
from src.core.database import DatabaseManager
from src.utils.config import Config

def main():
    # Initialize
    config = Config.from_file('config/config.yaml')
    db_manager = DatabaseManager('./data/remarkable_pipeline.db')
    notion_sync = NotionNotebookSync(config, db_manager)
    
    test_uuid = '98afc255-97ee-4416-96db-ac9a16a33109'
    
    print('🔄 Manual sync for "Test for integration" notebook...')
    
    # Sync this specific notebook
    with db_manager.get_connection() as conn:
        print('📚 Fetching notebook from database...')
        notebooks = notion_sync.fetch_notebooks_from_db(conn, [test_uuid], refresh_metadata=False)
        
        if not notebooks:
            print('❌ No notebook found in database')
            return
            
        notebook = notebooks[0]
        print(f'📖 Notebook: {notebook.name}')
        print(f'📄 Pages in notebook object: {len(notebook.pages)}')
        
        for page in notebook.pages:
            preview = page.text[:50] + '...' if page.text and len(page.text) > 50 else page.text or 'No text'
            print(f'   Page {page.number}: {preview}')
        
        # Check existing Notion sync record
        cursor = conn.execute('SELECT notion_page_id, total_pages FROM notion_notebook_sync WHERE notebook_uuid = ?', (test_uuid,))
        sync_record = cursor.fetchone()
        
        if sync_record:
            page_id, current_total = sync_record
            print(f'\n📝 Existing Notion page: {page_id}')
            print(f'📊 Currently shows {current_total} pages in Notion, but we have {len(notebook.pages)} pages')
            
            print('🔄 Updating existing Notion page with all content...')
            updated_page_id = notion_sync.update_existing_page(notebook, page_id, changed_pages=None)
            print(f'✅ Updated page ID: {updated_page_id}')
            
            # Check updated sync record
            cursor = conn.execute('SELECT total_pages, last_synced FROM notion_notebook_sync WHERE notebook_uuid = ?', (test_uuid,))
            new_record = cursor.fetchone()
            if new_record:
                print(f'📊 After sync - total pages in record: {new_record[0]}')
                print(f'🕐 Last synced: {new_record[1]}')
        else:
            print('❌ No existing Notion page found - this is unexpected')

if __name__ == '__main__':
    main()