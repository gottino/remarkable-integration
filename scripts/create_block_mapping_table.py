#!/usr/bin/env python3
"""
Create database table for storing Notion block mappings.
"""

import sys
import os
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager

def create_block_mapping_table():
    """Create the notion_page_blocks table for storing block mappings."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if table already exists
        cursor.execute('''
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='notion_page_blocks'
        ''')
        
        if cursor.fetchone():
            print("✅ notion_page_blocks table already exists")
            return
        
        # Create the table
        cursor.execute('''
            CREATE TABLE notion_page_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                notebook_uuid TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                notion_page_id TEXT NOT NULL,
                notion_block_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(notebook_uuid, page_number)
            )
        ''')
        
        # Create indexes for better performance
        cursor.execute('''
            CREATE INDEX idx_notion_page_blocks_notebook 
            ON notion_page_blocks(notebook_uuid, page_number)
        ''')
        
        cursor.execute('''
            CREATE INDEX idx_notion_page_blocks_notion_page 
            ON notion_page_blocks(notion_page_id)
        ''')
        
        conn.commit()
        print("✅ Created notion_page_blocks table with indexes")

def main():
    print("🔧 Creating Notion block mapping table...")
    create_block_mapping_table()
    print("✅ Database setup complete!")

if __name__ == '__main__':
    main()