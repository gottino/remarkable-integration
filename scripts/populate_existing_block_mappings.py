#!/usr/bin/env python3
"""
Retrieve block IDs from existing Notion pages and populate the block mapping table.
"""

import sys
import os
import re
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager
from src.integrations.notion_sync import NotionNotebookSync
from src.utils.config import Config

def extract_page_number_from_title(title_text: str) -> int:
    """Extract page number from toggle title like '📄 Page 15' or '📄 Page 15 (🟢 0.9)'."""
    # Look for pattern: 📄 Page {number}
    match = re.search(r'📄\s*Page\s+(\d+)', title_text)
    if match:
        return int(match.group(1))
    return None

def populate_block_mappings():
    """Scan existing Notion pages and populate block mappings."""
    
    config = Config('config/config.yaml')
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    # Create notion sync with SSL disabled
    notion_token = config.get('integrations.notion.api_token')
    database_id = config.get('integrations.notion.database_id')
    notion_sync = NotionNotebookSync(notion_token, database_id, verify_ssl=False)
    
    print("🔍 Scanning existing Notion pages for block IDs...")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all notebook sync records
        cursor.execute('''
            SELECT nns.notebook_uuid, nm.visible_name, nns.notion_page_id
            FROM notion_notebook_sync nns
            LEFT JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
            ORDER BY nm.visible_name
        ''')
        
        sync_records = cursor.fetchall()
        print(f"📚 Found {len(sync_records)} notebooks with Notion pages")
        
        total_blocks_found = 0
        notebooks_processed = 0
        
        for notebook_uuid, notebook_name, notion_page_id in sync_records:
            print(f"\n📖 Processing: {notebook_name}")
            print(f"   Page ID: {notion_page_id}")
            
            try:
                # Get all blocks from this Notion page
                blocks_response = notion_sync.client.blocks.children.list(
                    block_id=notion_page_id,
                    page_size=100  # Get up to 100 blocks
                )
                
                blocks = blocks_response["results"]
                page_blocks_found = 0
                
                # Process each block to find page toggles
                for block in blocks:
                    if block["type"] == "toggle":
                        # Extract page number from toggle title
                        toggle_content = block.get("toggle", {})
                        rich_text = toggle_content.get("rich_text", [])
                        
                        if rich_text and len(rich_text) > 0:
                            title_text = rich_text[0].get("text", {}).get("content", "")
                            page_number = extract_page_number_from_title(title_text)
                            
                            if page_number:
                                block_id = block["id"]
                                
                                # Store the mapping
                                cursor.execute('''
                                    INSERT OR REPLACE INTO notion_page_blocks 
                                    (notebook_uuid, page_number, notion_page_id, notion_block_id, updated_at)
                                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                                ''', (notebook_uuid, page_number, notion_page_id, block_id))
                                
                                page_blocks_found += 1
                                total_blocks_found += 1
                                
                                print(f"   📄 Page {page_number}: {block_id}")
                
                # Handle pagination if needed
                while blocks_response.get("has_more", False):
                    blocks_response = notion_sync.client.blocks.children.list(
                        block_id=notion_page_id,
                        start_cursor=blocks_response.get("next_cursor"),
                        page_size=100
                    )
                    
                    blocks = blocks_response["results"]
                    
                    for block in blocks:
                        if block["type"] == "toggle":
                            toggle_content = block.get("toggle", {})
                            rich_text = toggle_content.get("rich_text", [])
                            
                            if rich_text and len(rich_text) > 0:
                                title_text = rich_text[0].get("text", {}).get("content", "")
                                page_number = extract_page_number_from_title(title_text)
                                
                                if page_number:
                                    block_id = block["id"]
                                    
                                    cursor.execute('''
                                        INSERT OR REPLACE INTO notion_page_blocks 
                                        (notebook_uuid, page_number, notion_page_id, notion_block_id, updated_at)
                                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                                    ''', (notebook_uuid, page_number, notion_page_id, block_id))
                                    
                                    page_blocks_found += 1
                                    total_blocks_found += 1
                                    
                                    print(f"   📄 Page {page_number}: {block_id}")
                
                print(f"   ✅ Found {page_blocks_found} page blocks")
                notebooks_processed += 1
                
            except Exception as e:
                print(f"   ❌ Error processing {notebook_name}: {e}")
                continue
        
        # Commit all changes
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"📊 MAPPING RESULTS:")
        print(f"   📚 Notebooks processed: {notebooks_processed}/{len(sync_records)}")
        print(f"   📄 Total page blocks mapped: {total_blocks_found}")
        
        # Show some sample mappings
        cursor.execute('''
            SELECT npb.notebook_uuid, nm.visible_name, npb.page_number, npb.notion_block_id
            FROM notion_page_blocks npb
            LEFT JOIN notebook_metadata nm ON npb.notebook_uuid = nm.notebook_uuid
            ORDER BY nm.visible_name, npb.page_number
            LIMIT 10
        ''')
        
        samples = cursor.fetchall()
        print(f"\n🔍 Sample mappings:")
        for uuid, name, page_num, block_id in samples:
            print(f"   {name} page {page_num}: {block_id}")
        
        print(f"\n✅ Block mapping population complete!")

def verify_mappings():
    """Verify the populated mappings."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Count total mappings
        cursor.execute('SELECT COUNT(*) FROM notion_page_blocks')
        total_mappings = cursor.fetchone()[0]
        
        # Count by notebook
        cursor.execute('''
            SELECT nm.visible_name, COUNT(*) as block_count
            FROM notion_page_blocks npb
            LEFT JOIN notebook_metadata nm ON npb.notebook_uuid = nm.notebook_uuid
            GROUP BY nm.visible_name
            ORDER BY block_count DESC
            LIMIT 10
        ''')
        
        top_notebooks = cursor.fetchall()
        
        print(f"\n📊 MAPPING VERIFICATION:")
        print(f"   Total block mappings: {total_mappings}")
        print(f"\n   Top notebooks by page count:")
        for name, count in top_notebooks:
            print(f"     {name}: {count} pages")

def main():
    print("🔗 Populate Block Mappings from Existing Notion Pages\n")
    
    populate_block_mappings()
    verify_mappings()
    
    print(f"\n💡 Next steps:")
    print(f"   • Block mappings are now available for todo linking")
    print(f"   • New pages will automatically capture block IDs going forward") 
    print(f"   • Ready to create todos with source links!")

if __name__ == '__main__':
    main()