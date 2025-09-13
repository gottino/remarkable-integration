#!/usr/bin/env python3
"""
Export todos to Notion database with links back to source notebook pages.
"""

import sys
import os
sys.path.append(os.getcwd())

from datetime import datetime, timedelta
from src.core.database import DatabaseManager
from src.utils.config import Config

class NotionTodoExporter:
    """Export todos to Notion with source links."""
    
    def __init__(self, config_path='config/config.yaml'):
        self.config = Config(config_path)
        self.db = DatabaseManager('./data/remarkable_pipeline.db')
        self.notion_token = self.config.get('integrations.notion.api_token')
        
    def create_todos_database(self, database_name="📋 Todos", parent_page_id=None):
        """Create a Notion database for todos."""
        from notion_client import Client
        
        import httpx
        http_client = httpx.Client(verify=False)
        client = Client(auth=self.notion_token, client=http_client)
        
        # If no parent specified, create in the workspace
        parent = {"type": "page_id", "page_id": parent_page_id} if parent_page_id else {"type": "workspace", "workspace": True}
        
        properties = {
            "Title": {"title": {}},  # Todo text
            "Completed": {"checkbox": {}},  # Todo status
            "Source Notebook": {"rich_text": {}},  # Notebook name
            "Source Page": {"number": {}},  # Page number  
            "Actual Date": {"date": {}},  # When todo was written
            "Confidence": {"number": {}},  # OCR confidence
            "Link to Source": {"url": {}},  # Direct link to notebook page block
            "Created": {"created_time": {}},  # When todo was extracted
        }
        
        try:
            response = client.databases.create(
                parent=parent,
                title=[{"type": "text", "text": {"content": database_name}}],
                properties=properties
            )
            
            database_id = response["id"]
            print(f"✅ Created todos database: {database_id}")
            return database_id
            
        except Exception as e:
            print(f"❌ Failed to create database: {e}")
            return None
    
    def get_notion_workspace_url(self):
        """Get the base Notion workspace URL."""
        # Try to extract workspace URL from an existing notebook sync record
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT notion_page_id FROM notion_notebook_sync LIMIT 1')
            result = cursor.fetchone()
            
            if result:
                # Extract workspace from page ID format
                page_id = result[0]
                # Notion URLs are typically: https://www.notion.so/workspace/page_id
                return f"https://www.notion.so"
            
            return "https://www.notion.so"
    
    def create_block_link(self, notion_page_id: str, notion_block_id: str) -> str:
        """Create a direct link to a Notion block."""
        base_url = self.get_notion_workspace_url()
        # Remove dashes from IDs for URL format
        clean_page_id = notion_page_id.replace('-', '')
        clean_block_id = notion_block_id.replace('-', '')
        
        return f"{base_url}/{clean_page_id}#{clean_block_id}"
    
    def export_todos_to_notion(self, database_id: str, days_back: int = 30, dry_run: bool = True):
        """Export recent todos to Notion database with source links."""
        from notion_client import Client
        
        import httpx
        http_client = httpx.Client(verify=False)
        client = Client(auth=self.notion_token, client=http_client)
        cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get todos with their block mappings, excluding already exported ones
            cursor.execute(f'''
                SELECT 
                    t.id, t.text, t.actual_date, t.page_number, t.confidence, t.completed,
                    nm.visible_name as notebook_name,
                    nns.notion_page_id,
                    npb.notion_block_id,
                    t.created_at
                FROM todos t
                LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
                LEFT JOIN notion_notebook_sync nns ON t.notebook_uuid = nns.notebook_uuid
                LEFT JOIN notion_page_blocks npb ON t.notebook_uuid = npb.notebook_uuid 
                    AND t.page_number = npb.page_number
                LEFT JOIN notion_todo_sync nts ON t.id = nts.todo_id
                WHERE t.actual_date >= '{cutoff_date}'
                    AND t.actual_date IS NOT NULL
                    AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
                    AND nts.todo_id IS NULL  -- Only todos not yet exported
                ORDER BY t.actual_date DESC
            ''')
            
            todos_to_export = cursor.fetchall()
            
            print(f"{'='*60}")
            print(f"📤 TODO NOTION EXPORT")
            print(f"{'='*60}")
            print(f"📅 Period: Last {days_back} days (since {cutoff_date})")
            print(f"📝 Todos to export: {len(todos_to_export)}")
            print(f"🎯 Target database: {database_id}")
            print(f"🧪 Dry run: {'Yes' if dry_run else 'No'}")
            print()
            
            if not todos_to_export:
                print("✅ No todos to export!")
                return
            
            # Group by notebook for display
            by_notebook = {}
            linked_count = 0
            
            for row in todos_to_export:
                (todo_id, text, actual_date, page_num, confidence, completed, 
                 notebook_name, notion_page_id, notion_block_id, created_at) = row
                
                if notebook_name not in by_notebook:
                    by_notebook[notebook_name] = []
                
                # Create source link if we have block mapping
                source_link = None
                if notion_page_id and notion_block_id:
                    source_link = self.create_block_link(notion_page_id, notion_block_id)
                    linked_count += 1
                
                by_notebook[notebook_name].append({
                    'id': todo_id,
                    'text': text,
                    'actual_date': actual_date,
                    'page_number': page_num,
                    'confidence': confidence,
                    'completed': completed,
                    'source_link': source_link,
                    'notion_block_id': notion_block_id,
                    'created_at': created_at
                })
            
            print(f"📊 EXPORT PREVIEW:")
            print(f"   📎 Todos with source links: {linked_count}/{len(todos_to_export)}")
            print()
            
            for notebook_name, notebook_todos in by_notebook.items():
                print(f"📖 {notebook_name} ({len(notebook_todos)} todos)")
                
                for todo in notebook_todos[:3]:  # Show first 3 per notebook
                    link_status = "🔗" if todo['source_link'] else "❌"
                    print(f"   {todo['actual_date']} {link_status} \"{todo['text'][:50]}...\" (page {todo['page_number']})")
                    if todo['source_link']:
                        print(f"      Link: {todo['source_link'][:60]}...")
                
                if len(notebook_todos) > 3:
                    print(f"   ... and {len(notebook_todos) - 3} more")
                print()
            
            if dry_run:
                print("🧪 DRY RUN - No changes made")
                print("💡 To actually export, set dry_run=False")
                return
            
            # Actually create todos in Notion
            exported_count = 0
            export_timestamp = datetime.now().isoformat()
            
            for current_notebook_name, notebook_todos in by_notebook.items():
                for todo in notebook_todos:
                    try:
                        # Map to existing Tasks database properties
                        properties = {
                            "Name": {"title": [{"text": {"content": todo['text']}}]},  # Main title field
                            "Done": {"checkbox": bool(todo['completed'])},  # Completion status (convert to boolean)
                            "Notes": {"rich_text": [{"text": {"content": f"Source: {current_notebook_name}, Page {todo['page_number']}, Confidence: {todo['confidence']:.2f}"}}]},
                            "Tags": {"multi_select": [{"name": "remarkable"}]}  # Add remarkable tag
                        }
                        
                        # Add actual date if available (using Due Date field)
                        if todo['actual_date']:
                            properties["Due Date"] = {"date": {"start": todo['actual_date']}}
                        
                        # Create the todo page in Notion
                        response = client.pages.create(
                            parent={"database_id": database_id},
                            properties=properties
                        )
                        
                        # Add page content with link back to source
                        if todo['source_link'] and response.get('id'):
                            page_id = response['id']
                            
                            # Add a simple link back to the source (synced blocks don't work with already-synced blocks)
                            content_blocks = [
                                {
                                    "type": "heading_3",
                                    "heading_3": {
                                        "rich_text": [{"type": "text", "text": {"content": "📝 Source Context"}}]
                                    }
                                },
                                {
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": [
                                            {"type": "text", "text": {"content": "Found in: "}},
                                            {"type": "text", "text": {"content": f"{current_notebook_name}, Page {todo['page_number']}", "link": {"url": todo['source_link']}}}
                                        ]
                                    }
                                },
                                {
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": [{"type": "text", "text": {"content": "Click the link above to view the full context where this todo was found."}}]
                                    }
                                }
                            ]
                            
                            try:
                                client.blocks.children.append(
                                    block_id=page_id,
                                    children=content_blocks
                                )
                            except Exception as e:
                                print(f"   ⚠️  Could not add source content: {e}")
                        
                        # Store the export in the tracking table
                        notion_page_id = response['id']
                        cursor.execute('''
                            INSERT INTO notion_todo_sync 
                            (todo_id, notion_page_id, notion_database_id, exported_at, last_updated)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (todo['id'], notion_page_id, database_id, export_timestamp, export_timestamp))
                        
                        # Also update the legacy field for compatibility
                        cursor.execute('''
                            UPDATE todos 
                            SET notion_exported_at = ?
                            WHERE id = ?
                        ''', (export_timestamp, todo['id']))
                        
                        exported_count += 1
                        
                    except Exception as e:
                        print(f"❌ Failed to export todo {todo['id']}: {e}")
            
            conn.commit()
            print(f"✅ Exported {exported_count} todos to Notion")
            print(f"🎯 Marked {exported_count} todos as exported in database")

def main():
    print("🔗 Export Todos to Notion with Source Links\n")
    
    exporter = NotionTodoExporter()
    
    # For now, just show what would be exported
    print("📋 Preview of todos with block mapping support:")
    exporter.export_todos_to_notion("preview", days_back=30, dry_run=True)
    
    print(f"\n💡 Next steps:")
    print(f"1. Create todos database in Notion")
    print(f"2. Run this script with the database ID to export")
    print(f"3. Use the source links to jump back to notebook context")

if __name__ == '__main__':
    main()