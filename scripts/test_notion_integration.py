#!/usr/bin/env python3
"""
Test script for Notion integration.

This script tests the Notion integration with a small subset of notebooks
to ensure everything works correctly before syncing all data.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import DatabaseManager
from src.integrations.notion_sync import NotionNotebookSync

def test_notion_integration():
    """Test the Notion integration with a small subset of data."""
    
    # Configuration
    NOTION_TOKEN = os.getenv('NOTION_TOKEN')
    DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
    
    if not NOTION_TOKEN:
        print("❌ Please set NOTION_TOKEN environment variable")
        print("💡 Get your token from: https://developers.notion.com/")
        return False
    
    if not DATABASE_ID:
        print("❌ Please set NOTION_DATABASE_ID environment variable")
        print("💡 Copy the database ID from your Notion database URL")
        return False
    
    # Connect to database
    db_manager = DatabaseManager('./data/remarkable_pipeline.db')
    
    try:
        print("🚀 Testing Notion integration...")
        print(f"📊 Database: ./data/remarkable_pipeline.db")
        print(f"🗂️  Notion database: {DATABASE_ID}")
        
        # Initialize sync client (disable SSL verification for corporate networks)
        sync_client = NotionNotebookSync(NOTION_TOKEN, DATABASE_ID, verify_ssl=False)
        
        with db_manager.get_connection() as conn:
            # Get a small sample of notebooks for testing (prefer smaller ones)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT notebook_uuid, notebook_name, COUNT(*) as page_count
                FROM notebook_text_extractions 
                WHERE text IS NOT NULL AND length(text) > 10
                AND notebook_name NOT LIKE '%Luzerner Todesmelodie%'
                GROUP BY notebook_uuid
                ORDER BY page_count ASC
                LIMIT 3
            ''')
            
            test_notebooks = cursor.fetchall()
            
            if not test_notebooks:
                print("❌ No notebooks with extracted text found for testing")
                return False
            
            print(f"\n📖 Testing with {len(test_notebooks)} notebooks:")
            for uuid, name, page_count in test_notebooks:
                print(f"   • {name}: {page_count} pages")
            
            # Test fetching notebooks from database
            print("\n📚 Fetching notebooks from database...")
            notebooks = sync_client.fetch_notebooks_from_db(conn)
            
            # Filter to test notebooks only
            test_uuids = {uuid for uuid, _, _ in test_notebooks}
            test_notebook_objects = [nb for nb in notebooks if nb.uuid in test_uuids]
            
            print(f"✅ Found {len(test_notebook_objects)} notebooks to test")
            
            # Test syncing one notebook
            if test_notebook_objects:
                test_notebook = test_notebook_objects[1]
                print(f"\n🔄 Testing sync with: {test_notebook.name}")
                print(f"   Pages: {test_notebook.total_pages}")
                print(f"   UUID: {test_notebook.uuid[:8]}...")
                
                # Sync the test notebook
                page_id = sync_client.sync_notebook(test_notebook, update_existing=True)
                
                if page_id:
                    print(f"✅ Successfully synced to Notion!")
                    print(f"📄 Notion page ID: {page_id}")
                    return True
                else:
                    print("❌ Failed to sync notebook")
                    return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("🧪 Notion Integration Test")
    print("=" * 50)
    
    success = test_notion_integration()
    
    if success:
        print("\n🎉 Test completed successfully!")
        print("💡 You can now run the full sync with:")
        print("   poetry run python src/cli/main.py sync-notion --database-id YOUR_DATABASE_ID")
    else:
        print("\n❌ Test failed. Please check the errors above.")
        sys.exit(1)