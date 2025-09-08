#!/usr/bin/env python3
"""
Notion Todo Sync Service - Manages exporting todos to Notion Tasks database.
"""

import os
import sys
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from notion_client import Client

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.database import DatabaseManager
import logging

class NotionTodoSync:
    """Service for syncing todos to Notion Tasks database."""
    
    def __init__(self, notion_token: str, tasks_database_id: str, db_path: str = './data/remarkable_pipeline.db'):
        """
        Initialize the Notion todo sync service.
        
        Args:
            notion_token: Notion API token
            tasks_database_id: ID of the Notion Tasks database
            db_path: Path to the local SQLite database
        """
        self.tasks_database_id = tasks_database_id
        self.db = DatabaseManager(db_path)
        self.logger = logging.getLogger("NotionTodoSync")
        
        # Initialize Notion client with SSL disabled for compatibility
        http_client = httpx.Client(verify=False)
        self.client = Client(auth=notion_token, client=http_client)
    
    def get_notion_workspace_url(self) -> str:
        """Get the base Notion workspace URL."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT notion_page_id FROM notion_notebook_sync LIMIT 1')
            result = cursor.fetchone()
            
            if result:
                return "https://www.notion.so"
            return "https://www.notion.so"
    
    def create_block_link(self, notion_page_id: str, notion_block_id: str) -> str:
        """Create a direct link to a Notion block."""
        base_url = self.get_notion_workspace_url()
        clean_page_id = notion_page_id.replace('-', '')
        clean_block_id = notion_block_id.replace('-', '')
        return f"{base_url}/{clean_page_id}#{clean_block_id}"
    
    def get_todos_to_export(self, days_back: int = 30) -> List[Tuple]:
        """
        Get todos that need to be exported to Notion.
        
        Args:
            days_back: How many days back to look for todos
            
        Returns:
            List of todo data tuples
        """
        cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
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
                WHERE t.actual_date >= ?
                    AND t.actual_date IS NOT NULL
                    AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
                    AND nts.todo_id IS NULL  -- Only todos not yet exported
                ORDER BY t.actual_date DESC
            ''', (cutoff_date,))
            
            return cursor.fetchall()
    
    def export_todo_to_notion(self, todo_data: Tuple, notebook_name: str) -> Optional[str]:
        """
        Export a single todo to Notion Tasks database.
        
        Args:
            todo_data: Tuple of todo information
            notebook_name: Name of the source notebook
            
        Returns:
            Notion page ID if successful, None otherwise
        """
        (todo_id, text, actual_date, page_number, confidence, completed, 
         _, notion_page_id, notion_block_id, created_at) = todo_data
        
        try:
            # Prepare Notion page properties
            properties = {
                "Name": {"title": [{"text": {"content": text}}]},
                "Done": {"checkbox": bool(completed)},
                "Notes": {"rich_text": [{"text": {"content": f"Source: {notebook_name}, Page {page_number}, Confidence: {confidence:.2f}"}}]},
                "Tags": {"multi_select": [{"name": "remarkable"}]}
            }
            
            # Add actual date if available
            if actual_date:
                properties["Due Date"] = {"date": {"start": actual_date}}
            
            # Create the todo page in Notion
            response = self.client.pages.create(
                parent={"database_id": self.tasks_database_id},
                properties=properties
            )
            
            notion_page_id_created = response['id']
            
            # Add page content with source link
            source_link = None
            if notion_page_id and notion_block_id:
                source_link = self.create_block_link(notion_page_id, notion_block_id)
                
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
                                {"type": "text", "text": {"content": f"{notebook_name}, Page {page_number}", "link": {"url": source_link}}}
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
                    self.client.blocks.children.append(
                        block_id=notion_page_id_created,
                        children=content_blocks
                    )
                except Exception as e:
                    self.logger.debug(f"Could not add source content: {e}")
            
            return notion_page_id_created
            
        except Exception as e:
            self.logger.error(f"Failed to export todo {todo_id}: {e}")
            return None
    
    def record_export(self, todo_id: int, notion_page_id: str, export_timestamp: str):
        """Record the todo export in the tracking table."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Store in tracking table
            cursor.execute('''
                INSERT OR REPLACE INTO notion_todo_sync 
                (todo_id, notion_page_id, notion_database_id, exported_at, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (todo_id, notion_page_id, self.tasks_database_id, export_timestamp, export_timestamp))
            
            # Update legacy field
            cursor.execute('''
                UPDATE todos 
                SET notion_exported_at = ?
                WHERE id = ?
            ''', (export_timestamp, todo_id))
            
            conn.commit()
    
    def sync_todos(self, days_back: int = 30, dry_run: bool = False) -> Dict[str, int]:
        """
        Sync todos to Notion Tasks database.
        
        Args:
            days_back: How many days back to look for todos
            dry_run: If True, only show what would be synced
            
        Returns:
            Dictionary with sync statistics
        """
        todos_to_export = self.get_todos_to_export(days_back)
        
        if not todos_to_export:
            self.logger.info("No new todos to export")
            return {"exported": 0, "errors": 0, "total": 0}
        
        # Group by notebook for logging
        by_notebook = {}
        for row in todos_to_export:
            (todo_id, text, actual_date, page_num, confidence, completed, 
             notebook_name, notion_page_id, notion_block_id, created_at) = row
            
            if notebook_name not in by_notebook:
                by_notebook[notebook_name] = []
            
            source_link = None
            if notion_page_id and notion_block_id:
                source_link = self.create_block_link(notion_page_id, notion_block_id)
            
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
        
        # Log what will be exported
        self.logger.info(f"Found {len(todos_to_export)} todos to export:")
        for notebook_name, todos in by_notebook.items():
            self.logger.info(f"  📖 {notebook_name}: {len(todos)} todos")
        
        if dry_run:
            self.logger.info("DRY RUN - No changes made")
            return {"exported": 0, "errors": 0, "total": len(todos_to_export)}
        
        # Export todos
        exported_count = 0
        error_count = 0
        export_timestamp = datetime.now().isoformat()
        
        for notebook_name, notebook_todos in by_notebook.items():
            for todo in notebook_todos:
                # Reconstruct tuple for export function
                todo_data = (
                    todo['id'], todo['text'], todo['actual_date'], todo['page_number'],
                    todo['confidence'], todo['completed'], notebook_name,
                    None, todo['notion_block_id'], todo['created_at']
                )
                
                notion_page_id = self.export_todo_to_notion(todo_data, notebook_name)
                
                if notion_page_id:
                    self.record_export(todo['id'], notion_page_id, export_timestamp)
                    exported_count += 1
                    self.logger.debug(f"Exported: {todo['text'][:50]}...")
                else:
                    error_count += 1
        
        self.logger.info(f"Todo sync complete: {exported_count} exported, {error_count} errors")
        return {"exported": exported_count, "errors": error_count, "total": len(todos_to_export)}
    
    def get_export_stats(self) -> Dict[str, int]:
        """Get statistics about exported todos."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Total exported
            cursor.execute('SELECT COUNT(*) FROM notion_todo_sync')
            total_exported = cursor.fetchone()[0]
            
            # Recent exports (last 7 days)
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            cursor.execute('SELECT COUNT(*) FROM notion_todo_sync WHERE exported_at >= ?', (week_ago,))
            recent_exported = cursor.fetchone()[0]
            
            # Total todos with actual dates
            cursor.execute('SELECT COUNT(*) FROM todos WHERE actual_date IS NOT NULL')
            total_todos = cursor.fetchone()[0]
            
            return {
                "total_exported": total_exported,
                "recent_exported": recent_exported,
                "total_todos": total_todos,
                "export_percentage": round((total_exported / total_todos * 100) if total_todos > 0 else 0, 1)
            }