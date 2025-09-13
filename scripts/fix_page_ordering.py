#!/usr/bin/env python3
"""
Fix page ordering in Notion - ensure pages appear in reverse chronological order (newest first).
"""

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager
from src.integrations.notion_sync import NotionNotebookSync
from src.utils.config import Config

def reorder_notebook_pages(notion_sync, page_id: str, notebook_name: str):
    """Reorder pages in a Notion notebook to be newest first."""
    try:
        # Get all blocks from the page
        blocks_response = notion_sync.client.blocks.children.list(block_id=page_id)
        current_blocks = blocks_response["results"]
        
        header_blocks = []
        page_blocks = []
        
        # Separate header blocks from page blocks
        for block in current_blocks:
            if block["type"] == "toggle":
                # Extract page number from toggle title
                rich_text = block.get("toggle", {}).get("rich_text", [])
                if rich_text:
                    title = rich_text[0].get("text", {}).get("content", "")
                    # Parse "📄 Page X" format
                    if "📄 Page " in title:
                        try:
                            page_num = int(title.split("📄 Page ")[1].split(" ")[0].split("(")[0])
                            page_blocks.append((page_num, block))
                        except (ValueError, IndexError):
                            pass
            else:
                header_blocks.append(block)
        
        if len(page_blocks) <= 1:
            print(f"  ⏭️  {notebook_name}: Only {len(page_blocks)} page blocks, skipping reorder")
            return
            
        # Sort page blocks by page number (reverse = newest first)
        page_blocks.sort(key=lambda x: x[0], reverse=True)
        
        # Check if already in correct order
        current_order = [pb[0] for pb in page_blocks]
        is_ordered = current_order == sorted(current_order, reverse=True)
        
        if is_ordered:
            print(f"  ✅ {notebook_name}: Already in correct order (pages {current_order[0]}-{current_order[-1]})")
            return
            
        print(f"  🔄 {notebook_name}: Reordering {len(page_blocks)} pages (currently: {current_order[0]}-{current_order[-1]})")
        
        # Delete all page blocks (keep header blocks)
        for page_num, block in page_blocks:
            notion_sync.client.blocks.delete(block_id=block["id"])
            
        # Re-add page blocks in correct order (newest first)  
        # Insert after the last header block
        after_block_id = header_blocks[-1]["id"] if header_blocks else None
        
        # Add pages in reverse order so newest appears first
        for page_num, original_block in page_blocks:
            # Recreate the block structure
            new_block = {
                "type": "toggle",
                "toggle": original_block["toggle"]
            }
            
            result = notion_sync.client.blocks.children.append(
                block_id=page_id,
                children=[new_block],
                after=after_block_id
            )
            
            # Update after_block_id to insert subsequent blocks after this one
            # This ensures pages are added in the correct sequence
            if result.get("results"):
                after_block_id = result["results"][0]["id"]
                
        print(f"  ✅ {notebook_name}: Reordered pages (newest first)")
        
    except Exception as e:
        print(f"  ❌ {notebook_name}: Error reordering - {e}")

def main():
    config = Config('config/config.yaml')
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    # Create notion sync with SSL disabled  
    notion_token = config.get('integrations.notion.api_token')
    database_id = config.get('integrations.notion.database_id')
    notion_sync = NotionNotebookSync(notion_token, database_id, verify_ssl=False)
    
    print("🔄 Fixing page ordering in Notion (newest pages first)...")
    
    # Get all notebooks that had sync gaps and were recently fixed
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Find all notebooks that had gaps (these are the ones that were synced)
        cursor.execute('''
            SELECT nns.notebook_uuid, nm.visible_name, nns.notion_page_id, nns.total_pages,
                   COUNT(nte.page_number) as actual_pages
            FROM notion_notebook_sync nns
            LEFT JOIN notebook_metadata nm ON nns.notebook_uuid = nm.notebook_uuid
            LEFT JOIN notebook_text_extractions nte ON nns.notebook_uuid = nte.notebook_uuid
                AND nte.text IS NOT NULL AND length(nte.text) > 0
            GROUP BY nns.notebook_uuid, nm.visible_name, nns.notion_page_id, nns.total_pages
            HAVING actual_pages > 1  -- Only notebooks with multiple pages need reordering
            ORDER BY (actual_pages - nns.total_pages) DESC, nm.visible_name
        ''')
        
        notebooks_to_fix = cursor.fetchall()
        
        print(f"Found {len(notebooks_to_fix)} notebooks to check for page ordering...")
        
        for notebook_uuid, name, page_id, synced_pages, actual_pages in notebooks_to_fix:
            if actual_pages > synced_pages:
                gap_info = f" (recently synced {actual_pages - synced_pages} missing pages)"
            else:
                gap_info = ""
            
            print(f"\n📖 {name} ({actual_pages} pages){gap_info}:")
            reorder_notebook_pages(notion_sync, page_id, name)
    
    print(f"\n✅ Page ordering fixes completed!")

if __name__ == '__main__':
    main()