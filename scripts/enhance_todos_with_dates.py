#!/usr/bin/env python3
"""
Enhance todos table with actual todo dates and Notion export tracking.
"""

import sys
import os
sys.path.append(os.getcwd())

import re
from datetime import datetime
from src.core.database import DatabaseManager

def parse_date_from_content(page_content: str) -> datetime:
    """Extract date from page content using common patterns."""
    if not page_content:
        return None
    
    # Date patterns in order of preference
    date_patterns = [
        r'\*\*Date:\s*(\d{1,2}-\d{1,2}-\d{4})\*\*',  # **Date: 16-8-2025**
        r'Date:\s*(\d{1,2}-\d{1,2}-\d{4})',           # Date: 16-8-2025
        r'^\*\*(\d{1,2}-\d{1,2}-\d{4})\*\*',         # **16-8-2025** at start
        r'(\d{1,2}-\d{1,2}-\d{4})',                   # 16-8-2025 (standalone)
        r'\*\*Date:\s*(\d{1,2}/\d{1,2}/\d{4})\*\*',  # **Date: 16/8/2025**
        r'(\d{1,2}/\d{1,2}/\d{4})',                  # 16/8/2025
    ]
    
    for pattern in date_patterns:
        matches = re.search(pattern, page_content, re.MULTILINE)
        if matches:
            date_str = matches.group(1)
            try:
                # Handle both - and / separators
                if '-' in date_str:
                    return datetime.strptime(date_str, '%d-%m-%Y')
                else:
                    return datetime.strptime(date_str, '%d/%m/%Y')
            except ValueError:
                continue
    
    return None

def add_date_columns():
    """Add new columns to todos table."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if columns already exist
        cursor.execute('PRAGMA table_info(todos)')
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        if 'actual_date' not in existing_columns:
            print("➕ Adding 'actual_date' column...")
            cursor.execute('ALTER TABLE todos ADD COLUMN actual_date TEXT')
        
        if 'notion_exported_at' not in existing_columns:
            print("➕ Adding 'notion_exported_at' column...")
            cursor.execute('ALTER TABLE todos ADD COLUMN notion_exported_at TEXT')
        
        conn.commit()
        print("✅ Table schema updated")

def extract_and_update_dates():
    """Extract dates from page content and update todos table."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all todos with their page content
        cursor.execute('''
            SELECT t.id, t.notebook_uuid, t.page_number, nte.text as page_content
            FROM todos t
            LEFT JOIN notebook_text_extractions nte ON t.notebook_uuid = nte.notebook_uuid AND t.page_number = nte.page_number
            WHERE t.actual_date IS NULL
        ''')
        
        todos_to_update = cursor.fetchall()
        print(f"🔄 Processing {len(todos_to_update)} todos for date extraction...")
        
        updated_count = 0
        no_date_count = 0
        
        for todo_id, notebook_uuid, page_number, page_content in todos_to_update:
            actual_date = parse_date_from_content(page_content)
            
            if actual_date:
                # Store as ISO format string
                date_str = actual_date.strftime('%Y-%m-%d')
                cursor.execute('''
                    UPDATE todos SET actual_date = ? WHERE id = ?
                ''', (date_str, todo_id))
                updated_count += 1
            else:
                no_date_count += 1
        
        conn.commit()
        print(f"✅ Updated {updated_count} todos with actual dates")
        print(f"⚠️  {no_date_count} todos had no extractable date")

def analyze_todos_by_date():
    """Analyze todos by actual date for filtering decisions."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        print("\n=== TODO ANALYSIS BY ACTUAL DATE ===")
        
        # Total todos
        cursor.execute('SELECT COUNT(*) FROM todos')
        total = cursor.fetchone()[0]
        print(f"📊 Total todos: {total}")
        
        # Todos with extracted dates
        cursor.execute('SELECT COUNT(*) FROM todos WHERE actual_date IS NOT NULL')
        with_dates = cursor.fetchone()[0]
        print(f"📅 Todos with extracted dates: {with_dates} ({with_dates/total*100:.1f}%)")
        
        # Date range analysis
        cursor.execute('''
            SELECT MIN(actual_date), MAX(actual_date) 
            FROM todos 
            WHERE actual_date IS NOT NULL
        ''')
        min_date, max_date = cursor.fetchone()
        print(f"📆 Date range: {min_date} to {max_date}")
        
        # Recent todos (last 30 days from max date)
        if max_date:
            max_date_obj = datetime.strptime(max_date, '%Y-%m-%d')
            cutoff_date = max_date_obj.replace(month=max_date_obj.month-1) if max_date_obj.month > 1 else max_date_obj.replace(year=max_date_obj.year-1, month=12)
            cutoff_str = cutoff_date.strftime('%Y-%m-%d')
            
            cursor.execute(f'''
                SELECT COUNT(*) FROM todos t
                LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
                WHERE t.actual_date >= '{cutoff_str}'
                AND t.actual_date IS NOT NULL
                AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
            ''')
            recent_by_date = cursor.fetchone()[0]
            print(f"🗓️  Recent todos by actual date (last 30 days, non-archive): {recent_by_date}")
            
            # Top notebooks by recent todos
            cursor.execute(f'''
                SELECT nm.visible_name, COUNT(*) as count, MIN(t.actual_date), MAX(t.actual_date)
                FROM todos t
                LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
                WHERE t.actual_date >= '{cutoff_str}'
                AND t.actual_date IS NOT NULL
                AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
                GROUP BY nm.visible_name
                ORDER BY count DESC
                LIMIT 10
            ''')
            
            print(f"\n📚 Top notebooks with recent todos (by actual date):")
            for name, count, min_date, max_date in cursor.fetchall():
                print(f"  {name}: {count} todos ({min_date} to {max_date})")

def main():
    print("🔄 Enhancing todos with actual dates and export tracking...")
    
    # Step 1: Add new columns
    add_date_columns()
    
    # Step 2: Extract dates from content
    extract_and_update_dates()
    
    # Step 3: Analyze results
    analyze_todos_by_date()
    
    print("\n✅ Todo enhancement completed!")
    print("\nNext steps:")
    print("1. Review the analysis above")
    print("2. Run todo export with date-based filtering")
    print("3. Export to Notion with notion_exported_at timestamp")

if __name__ == '__main__':
    main()