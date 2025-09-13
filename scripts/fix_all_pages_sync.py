#!/usr/bin/env python3
"""
Fix the Test for integration notebook by manually syncing ALL pages,
including those with short text content that are being filtered out.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.integrations.notion_sync import NotionNotebookSync, NotebookPage, Notebook, NotebookMetadata
from src.core.database import DatabaseManager
from src.utils.config import Config
from dataclasses import dataclass
from typing import List
from datetime import datetime

def create_notebook_with_all_pages(db_connection, notebook_uuid: str):
    """Create a Notebook object with ALL pages, including short content ones."""
    
    # Get notebook metadata
    cursor = db_connection.execute('''
        SELECT visible_name, full_path, last_modified, last_opened
        FROM notebook_metadata 
        WHERE notebook_uuid = ?
    ''', (notebook_uuid,))
    
    metadata_row = cursor.fetchone()
    if not metadata_row:
        return None
        
    name, full_path, last_modified, last_opened = metadata_row
    
    # Get ALL pages (no text length filtering)
    cursor = db_connection.execute('''
        SELECT page_number, text, confidence, page_uuid
        FROM notebook_text_extractions 
        WHERE notebook_uuid = ?
        ORDER BY page_number
    ''', (notebook_uuid,))
    
    page_rows = cursor.fetchall()
    
    # Create NotebookPage objects
    pages = []
    for page_num, text, confidence, page_uuid in page_rows:
        page = NotebookPage(
            page_number=page_num,
            text=text or "",  # Handle NULL text
            confidence=confidence or 0.0,
            page_uuid=page_uuid or ""
        )
        pages.append(page)
    
    # Create metadata
    metadata = NotebookMetadata(
        uuid=notebook_uuid,
        name=name,
        full_path=full_path or "",
        last_modified=last_modified or "",
        last_opened=last_opened or ""
    )
    
    # Create notebook
    notebook = Notebook(
        uuid=notebook_uuid,
        name=name,
        pages=pages,
        metadata=metadata
    )
    
    return notebook

def main():
    # Initialize with SSL disabled
    config = Config('config/config.yaml')
    db_manager = DatabaseManager('./data/remarkable_pipeline.db')
    
    # Create notion sync with SSL disabled
    notion_sync = NotionNotebookSync(config, db_manager)
    # SSL will be handled by the existing no-ssl-verify configuration
    
    test_uuid = '98afc255-97ee-4416-96db-ac9a16a33109'
    correct_page_id = '263a6c5dacd0817bbabfd6d7b8e2d10c'
    
    print('🔧 Syncing ALL pages for Test for integration notebook...')
    
    with db_manager.get_connection() as conn:
        # Create notebook with all pages (no filtering)
        notebook = create_notebook_with_all_pages(conn, test_uuid)
        
        if not notebook:
            print('❌ Notebook not found')
            return
            
        print(f'📖 Notebook: {notebook.name}')
        print(f'📄 Total pages to sync: {len(notebook.pages)}')
        
        for page in notebook.pages:
            text_preview = page.text[:50] + '...' if page.text and len(page.text) > 50 else page.text or 'No text'
            print(f'   Page {page.page_number}: "{text_preview}" (length: {len(page.text)})')
        
        try:
            print(f'\\n🔄 Updating Notion page: {correct_page_id}')
            notion_sync.update_existing_page(correct_page_id, notebook, changed_pages=None)
            print('✅ Sync completed successfully!')
            
            # Update database record manually to reflect all pages
            conn.execute('''
                UPDATE notion_notebook_sync 
                SET total_pages = ?, last_synced = ?
                WHERE notebook_uuid = ?
            ''', (len(notebook.pages), datetime.now().isoformat(), test_uuid))
            conn.commit()
            
            print(f'📊 Updated database record: {len(notebook.pages)} pages')
            
        except Exception as e:
            print(f'❌ Sync error: {e}')
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    main()