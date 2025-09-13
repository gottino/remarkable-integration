#!/usr/bin/env python3
"""
Create database table for tracking todo exports to Notion.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager

def create_todo_sync_table():
    """Create the notion_todo_sync table for tracking todo exports."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if table already exists
        cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='notion_todo_sync'
        ''')
        
        if cursor.fetchone():
            print("✅ notion_todo_sync table already exists")
            return
        
        # Create the table
        cursor.execute('''
            CREATE TABLE notion_todo_sync (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                todo_id INTEGER NOT NULL,
                notion_page_id TEXT NOT NULL,
                notion_database_id TEXT NOT NULL,
                exported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(todo_id),
                FOREIGN KEY(todo_id) REFERENCES todos(id)
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('''
            CREATE INDEX idx_notion_todo_sync_todo_id 
            ON notion_todo_sync(todo_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX idx_notion_todo_sync_notion_page 
            ON notion_todo_sync(notion_page_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX idx_notion_todo_sync_database 
            ON notion_todo_sync(notion_database_id)
        ''')
        
        conn.commit()
        print("✅ Created notion_todo_sync table with indexes")

def migrate_existing_exports():
    """Migrate existing exported todos to the new tracking table."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Count existing exported todos
        cursor.execute('SELECT COUNT(*) FROM todos WHERE notion_exported_at IS NOT NULL')
        existing_count = cursor.fetchone()[0]
        
        if existing_count > 0:
            print(f"⚠️  Found {existing_count} previously exported todos")
            print("   These will need to be re-exported to populate the new tracking table")
            print("   Or you can manually populate notion_todo_sync if you have the Notion page IDs")
            
            # Reset export status so they can be re-exported with proper tracking
            cursor.execute('UPDATE todos SET notion_exported_at = NULL')
            conn.commit()
            print("   Reset export status for proper re-tracking")
        else:
            print("✅ No existing exports found")

def main():
    print("🔧 Creating Notion todo sync tracking table...")
    create_todo_sync_table()
    migrate_existing_exports()
    print("✅ Database setup complete!")

if __name__ == '__main__':
    main()