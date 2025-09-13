#!/usr/bin/env python3
"""
Create new Notion pages for notebooks with invalid page IDs or missing content.
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
    """Create a Notebook object with ALL pages."""
    
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
        AND text IS NOT NULL AND length(text) > 0
        ORDER BY page_number
    ''', (notebook_uuid,))
    
    page_rows = cursor.fetchall()
    
    # Create NotebookPage objects
    pages = []
    for page_num, text, confidence, page_uuid in page_rows:
        page = NotebookPage(
            page_number=page_num,
            text=text or "",
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
    notion_token = config.get('integrations.notion.api_token')
    database_id = config.get('integrations.notion.database_id')
    notion_sync = NotionNotebookSync(notion_token, database_id, verify_ssl=False)
    
    print('🔧 Creating missing Notion pages for notebooks with sync gaps...')
    
    # Test with specific notebooks that had issues
    test_notebooks = [
        ('80ecb1eb-0095-407c-b771-2ee063526101', 'Christian'),  # 3 missing pages
        ('e7e7a737-e5f8-4813-acda-8873cb496d09', 'Marton - Design')  # Many missing pages
    ]
    
    for notebook_uuid, expected_name in test_notebooks:
        print(f'\n📖 Processing {expected_name}...')
        
        with db_manager.get_connection() as conn:
            # Create notebook with all pages
            notebook = create_notebook_with_all_pages(conn, notebook_uuid)
            
            if not notebook:
                print('❌ Notebook not found')
                continue
                
            print(f'📄 Total pages to sync: {len(notebook.pages)}')
            
            try:
                # Check if page exists
                existing_page_id = notion_sync.find_existing_page(notebook_uuid)
                
                if existing_page_id:
                    print(f'🔄 Updating existing page: {existing_page_id}')
                    notion_sync.update_existing_page(existing_page_id, notebook, changed_pages=None)
                else:
                    print(f'📖 Creating new page for: {notebook.name}')
                    page_id = notion_sync.create_notebook_page(notebook)
                    print(f'✅ Created page: {page_id}')
                
                print('✅ Sync completed successfully!')
                
            except Exception as e:
                print(f'❌ Sync error: {e}')

if __name__ == '__main__':
    main()