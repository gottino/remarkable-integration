#!/usr/bin/env python3
"""
Test script for the complete watching pipeline with Notion integration.

This script simulates the watching pipeline by processing a test notebook
and syncing it to Notion to verify the complete workflow.
"""

import sys
import os
import asyncio
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import DatabaseManager
from src.processors.notebook_text_extractor import NotebookTextExtractor

async def test_complete_pipeline():
    """Test the complete pipeline from text extraction to Notion sync."""
    
    print("🧪 Testing Complete Watching Pipeline")
    print("=" * 50)
    print()
    
    # Check configuration
    from src.utils.config import Config
    config_path = project_root / 'config' / 'config.yaml'
    config = Config(config_path)
    
    # Check Notion credentials
    notion_token = os.getenv('NOTION_TOKEN') or config.get('integrations.notion.api_token')
    notion_database_id = os.getenv('NOTION_DATABASE_ID') or config.get('integrations.notion.database_id')
    
    if not notion_token or not notion_database_id:
        print("❌ Notion credentials not configured")
        print("💡 Run: poetry run python scripts/setup_notion_watching.py")
        return False
    
    print(f"✅ Notion integration configured")
    print(f"   Token: {notion_token[:20]}...")
    print(f"   Database: {notion_database_id}")
    print()
    
    # Initialize components
    db_path = config.get('database.path', './data/remarkable_pipeline.db')
    db_manager = DatabaseManager(db_path)
    
    print(f"📊 Using database: {db_path}")
    print()
    
    # Initialize text extractor (same as watch command)
    data_directory = config.get('remarkable.local_sync_directory', './data/remarkable_sync')
    
    text_extractor = NotebookTextExtractor(
        data_directory=data_directory,
        db_manager=db_manager
    )
    
    # Initialize Notion client
    try:
        from src.integrations.notion_sync import NotionNotebookSync
        notion_client = NotionNotebookSync(notion_token, notion_database_id, verify_ssl=False)
        print("✅ Notion client initialized")
    except ImportError:
        print("❌ notion-client not installed. Run: poetry add notion-client")
        return False
    except Exception as e:
        print(f"❌ Failed to initialize Notion client: {e}")
        return False
    
    print()
    
    # Get a test notebook (handwritten only)
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT nte.notebook_uuid, nte.notebook_name, COUNT(*) as page_count
            FROM notebook_text_extractions nte
            JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
            WHERE nte.text IS NOT NULL AND length(nte.text) > 10
            AND nm.document_type = 'notebook'
            AND nte.notebook_name NOT LIKE '%Luzerner Todesmelodie%'
            GROUP BY nte.notebook_uuid
            ORDER BY page_count ASC
            LIMIT 1
        ''')
        
        test_notebook = cursor.fetchone()
        
        if not test_notebook:
            print("❌ No test notebook found with extracted text")
            print("💡 Run text extraction first: python src/cli/main.py extract-text ./data/remarkable_sync")
            return False
        
        test_uuid, test_name, page_count = test_notebook
        print(f"🔬 Testing with notebook: {test_name}")
        print(f"   UUID: {test_uuid}")
        print(f"   Pages: {page_count}")
        print()
    
    # Test 1: Text extraction (simulating incremental processing)
    print("📝 Step 1: Testing incremental text extraction...")
    try:
        result = text_extractor.process_notebook_incremental(test_uuid)
        if result.success:
            print(f"✅ Text extraction successful: {result.notebook_name}")
            print(f"   Pages in result: {len(result.pages) if result.pages else 0}")
            print(f"   Processing time: {result.processing_time_ms}ms" if result.processing_time_ms else "")
        else:
            print(f"❌ Text extraction failed: {result.error_message}")
            return False
    except Exception as e:
        print(f"❌ Text extraction error: {e}")
        return False
    
    print()
    
    # Test 2: Notion sync (simulating automatic sync)
    print("📄 Step 2: Testing Notion sync...")
    try:
        # Fetch the notebook for Notion sync
        with db_manager.get_connection() as conn:
            notebooks = notion_client.fetch_notebooks_from_db(conn)
            target_notebook = next((nb for nb in notebooks if nb.uuid == test_uuid), None)
            
            if target_notebook:
                # Test the smart sync
                page_id = notion_client.sync_notebook(target_notebook, update_existing=True)
                print(f"✅ Notion sync successful: {target_notebook.name}")
                print(f"   Page ID: {page_id}")
            else:
                print("❌ Test notebook not found for Notion sync")
                return False
                
    except Exception as e:
        print(f"❌ Notion sync error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    
    # Test 3: Complete pipeline simulation
    print("🔄 Step 3: Testing complete pipeline simulation...")
    try:
        # Simulate the file watcher pipeline
        print(f"   1. File change detected: {test_uuid}.content")
        print("   2. Processing notebook with OCR...")
        
        # Re-process to simulate change detection
        result = text_extractor.process_notebook_incremental(test_uuid)
        print(f"   3. Processing result: {'Success' if result.success else 'Failed'}")
        
        if result.success:
            print("   4. Triggering Notion sync...")
            # Get fresh notebook data and sync
            with db_manager.get_connection() as conn:
                notebooks = notion_client.fetch_notebooks_from_db(conn)
                target_notebook = next((nb for nb in notebooks if nb.uuid == test_uuid), None)
                
                if target_notebook:
                    page_id = notion_client.sync_notebook(target_notebook, update_existing=True)
                    print(f"   5. Notion sync completed: {page_id}")
                    print("✅ Complete pipeline test successful!")
                else:
                    print("   5. Notebook not found for sync")
                    return False
        else:
            print(f"   Processing failed: {result.error_message}")
            return False
            
    except Exception as e:
        print(f"❌ Pipeline simulation error: {e}")
        return False
    
    print()
    print("🎉 All tests passed! The watching pipeline is ready.")
    print()
    print("🚀 To start the complete watching system:")
    print("   poetry run python src/cli/main.py watch")
    print()
    print("💡 The system will automatically:")
    print("   • Monitor reMarkable app directory for changes")
    print("   • Sync changed files to local directory") 
    print("   • Process notebooks with incremental OCR")
    print("   • Auto-sync processed notebooks to Notion")
    print("   • Use intelligent change detection for fast updates")
    
    return True

if __name__ == "__main__":
    try:
        success = asyncio.run(test_complete_pipeline())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n❌ Test cancelled")
        sys.exit(1)