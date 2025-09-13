#!/usr/bin/env python3
"""
Sync missing pages to Notion for all notebooks with page count mismatches.
This will identify notebooks where the database has more pages than Notion
and update only those notebooks with the missing content.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.integrations.notion_sync import NotionNotebookSync
from src.core.database import DatabaseManager
from src.utils.config import Config

def get_notebooks_with_missing_pages(db_connection):
    """Get list of notebooks that have missing pages in Notion."""
    cursor = db_connection.execute('''
        SELECT 
            nm.notebook_uuid,
            nm.visible_name,
            COUNT(nte.page_number) as db_pages,
            COALESCE(nns.total_pages, 0) as notion_pages,
            nns.notion_page_id,
            nns.last_synced
        FROM notebook_metadata nm
        LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
        LEFT JOIN notion_notebook_sync nns ON nm.notebook_uuid = nns.notebook_uuid
        WHERE nm.item_type = 'DocumentType' 
        AND nm.document_type = 'notebook'
        AND nte.notebook_uuid IS NOT NULL  -- Has extracted text
        GROUP BY nm.notebook_uuid, nm.visible_name, nns.total_pages, nns.notion_page_id, nns.last_synced
        HAVING COUNT(nte.page_number) > COALESCE(nns.total_pages, 0)
        ORDER BY (COUNT(nte.page_number) - COALESCE(nns.total_pages, 0)) DESC
    ''')
    
    return cursor.fetchall()

def main():
    # Initialize
    config = Config('config/config.yaml')
    db_manager = DatabaseManager('./data/remarkable_pipeline.db')
    notion_sync = NotionNotebookSync(config, db_manager)
    
    print('🔍 Finding notebooks with missing pages in Notion...')
    
    with db_manager.get_connection() as conn:
        missing_pages_notebooks = get_notebooks_with_missing_pages(conn)
        
        if not missing_pages_notebooks:
            print('✅ All notebooks are up to date!')
            return
        
        print(f'📊 Found {len(missing_pages_notebooks)} notebooks with missing pages:')
        
        total_missing = 0
        for uuid, name, db_pages, notion_pages, notion_id, last_synced in missing_pages_notebooks:
            missing = db_pages - notion_pages
            total_missing += missing
            status = "Has Notion page" if notion_id else "No Notion page"
            print(f'  {name[:40]:<40} | Missing: {missing:2d} | {status}')
        
        print(f'\n📈 Total missing pages: {total_missing}')
        
        print(f'\n🚀 Starting sync process for {len(missing_pages_notebooks)} notebooks...')
        
        success_count = 0
        error_count = 0
        
        for i, (uuid, name, db_pages, notion_pages, notion_id, last_synced) in enumerate(missing_pages_notebooks, 1):
            missing = db_pages - notion_pages
            
            print(f'\n[{i}/{len(missing_pages_notebooks)}] 📖 {name} ({missing} missing pages)')
            
            try:
                # Fetch all notebooks from database and filter for our target
                all_notebooks = notion_sync.fetch_notebooks_from_db(conn, refresh_changed_metadata=False)
                notebooks = [nb for nb in all_notebooks if nb.uuid == uuid]
                
                if not notebooks:
                    print('   ❌ Notebook not found in database')
                    error_count += 1
                    continue
                
                notebook = notebooks[0]
                print(f'   📄 Loaded {len(notebook.pages)} pages from database')
                
                if notion_id:
                    # Update existing Notion page
                    print('   🔄 Updating existing Notion page...')
                    notion_sync.update_existing_page(notion_id, notebook, changed_pages=None)
                    print(f'   ✅ Updated page: {notion_id}')
                else:
                    # Create new Notion page
                    print('   📝 Creating new Notion page...')
                    new_page_id = notion_sync.create_new_page(notebook)
                    print(f'   ✅ Created page: {new_page_id}')
                
                success_count += 1
                
                # Verify the update
                cursor = conn.execute('SELECT total_pages FROM notion_notebook_sync WHERE notebook_uuid = ?', (uuid,))
                new_record = cursor.fetchone()
                if new_record:
                    print(f'   📊 Notion now has {new_record[0]} pages (was {notion_pages})')
                
            except Exception as e:
                print(f'   ❌ Error syncing {name}: {e}')
                error_count += 1
                continue
        
        print(f'\n🎉 Sync completed!')
        print(f'   ✅ Successfully synced: {success_count} notebooks')
        print(f'   ❌ Errors: {error_count} notebooks')
        
        if success_count > 0:
            print(f'\n🔍 Verifying results...')
            # Re-check missing pages
            missing_after = get_notebooks_with_missing_pages(conn)
            remaining_missing = sum(row[2] - row[3] for row in missing_after)
            print(f'   📊 Remaining missing pages: {remaining_missing}')

if __name__ == '__main__':
    main()