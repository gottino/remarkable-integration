#!/usr/bin/env python3
"""
Test sync for a single notebook - Test for integration.
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
    
    print('🔄 Testing sync for "Test for integration" notebook...')
    
    with db_manager.get_connection() as conn:
        # Get current state
        cursor = conn.execute('''
            SELECT COUNT(*) as db_pages
            FROM notebook_text_extractions 
            WHERE notebook_uuid = ?
        ''', (test_uuid,))
        db_pages = cursor.fetchone()[0]
        
        cursor = conn.execute('SELECT total_pages, notion_page_id FROM notion_notebook_sync WHERE notebook_uuid = ?', (test_uuid,))
        sync_record = cursor.fetchone()
        notion_pages, notion_id = sync_record if sync_record else (0, None)
        
        print(f'📊 Current state: {db_pages} pages in DB, {notion_pages} in Notion sync record')
        
        # Fetch all notebooks and find our target
        all_notebooks = notion_sync.fetch_notebooks_from_db(conn, refresh_changed_metadata=False)
        notebooks = [nb for nb in all_notebooks if nb.uuid == test_uuid]
        
        if not notebooks:
            print('❌ Notebook not found in database')
            return
            
        notebook = notebooks[0]
        print(f'📖 Notebook: {notebook.name}')
        print(f'📄 Loaded {len(notebook.pages)} pages from database')
        
        for i, page in enumerate(notebook.pages[:3]):  # Show first 3 pages
            preview = page.text[:50] + '...' if page.text and len(page.text) > 50 else page.text or 'No text'
            print(f'   Page {page.page_number}: {preview}')
        
        if len(notebook.pages) > 3:
            print(f'   ... and {len(notebook.pages) - 3} more pages')
        
        if notion_id:
            print(f'\\n🔄 Updating existing Notion page: {notion_id}')
            try:
                notion_sync.update_existing_page(notion_id, notebook, changed_pages=None)
                print('✅ Update completed')
                
                # Check result
                cursor = conn.execute('SELECT total_pages FROM notion_notebook_sync WHERE notebook_uuid = ?', (test_uuid,))
                new_record = cursor.fetchone()
                if new_record:
                    print(f'📊 After sync: {new_record[0]} pages in Notion record (was {notion_pages})')
                    
            except Exception as e:
                print(f'❌ Error: {e}')
                import traceback
                traceback.print_exc()
        else:
            print('❌ No existing Notion page found')

if __name__ == '__main__':
    main()