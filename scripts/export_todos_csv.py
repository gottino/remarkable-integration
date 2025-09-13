#!/usr/bin/env python3
"""
Export filtered todos to CSV file for review before Notion import.
"""

import sys
import os
import csv
from datetime import datetime, timedelta
sys.path.append(os.getcwd())

from src.core.database import DatabaseManager

def export_todos_to_csv(days_back: int = 30, output_file: str = "recent_todos.csv"):
    """Export recent todos to CSV file."""
    
    db = DatabaseManager('./data/remarkable_pipeline.db')
    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get todos to export with all relevant info
        cursor.execute(f'''
            SELECT 
                t.actual_date,
                nm.visible_name as notebook,
                nm.full_path as path,
                t.page_number,
                t.text as todo_text,
                t.confidence,
                t.completed,
                t.created_at
            FROM todos t
            LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
            WHERE t.actual_date >= '{cutoff_date}'
            AND t.actual_date IS NOT NULL
            AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
            AND t.notion_exported_at IS NULL
            ORDER BY t.actual_date DESC, nm.visible_name, t.page_number
        ''')
        
        todos = cursor.fetchall()
        
        print(f"📝 Exporting {len(todos)} todos from last {days_back} days...")
        print(f"📅 Cutoff date: {cutoff_date}")
        print(f"📁 Output file: {output_file}")
        
        if not todos:
            print("✅ No todos to export!")
            return
        
        # Write to CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Header
            writer.writerow([
                'Date',
                'Notebook', 
                'Path',
                'Page',
                'Todo',
                'Confidence',
                'Completed',
                'Created At'
            ])
            
            # Data rows
            for row in todos:
                writer.writerow(row)
        
        print(f"✅ Exported {len(todos)} todos to {output_file}")
        
        # Show summary by notebook
        notebooks = {}
        for row in todos:
            notebook = row[1]  # notebook name
            if notebook not in notebooks:
                notebooks[notebook] = 0
            notebooks[notebook] += 1
        
        print(f"\n📚 Summary by notebook:")
        for notebook, count in sorted(notebooks.items(), key=lambda x: x[1], reverse=True):
            print(f"  {notebook}: {count} todos")

def main():
    print("📋 Exporting Recent Todos to CSV\n")
    
    # Default: last 30 days
    export_todos_to_csv(30, "recent_todos_30_days.csv")
    
    # Also create a 60-day version for comparison
    print("\n" + "="*50)
    export_todos_to_csv(60, "recent_todos_60_days.csv")

if __name__ == '__main__':
    main()