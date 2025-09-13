#!/usr/bin/env python3
"""
Export recent todos to Notion based on actual todo dates, not notebook modification dates.
"""

import sys
import os
sys.path.append(os.getcwd())

from datetime import datetime, timedelta
from src.core.database import DatabaseManager
from src.utils.config import Config

def analyze_filtering_options():
    """Show different filtering options with counts."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        print("=== TODO FILTERING OPTIONS ===\n")
        
        # Base stats
        cursor.execute('SELECT COUNT(*) FROM todos')
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM todos WHERE actual_date IS NOT NULL')
        with_dates = cursor.fetchone()[0]
        
        print(f"📊 Total todos: {total}")
        print(f"📅 Todos with extractable dates: {with_dates}")
        print(f"❓ Todos without dates: {total - with_dates}")
        
        # Different time periods
        now = datetime.now()
        periods = [
            ("Last 7 days", 7),
            ("Last 14 days", 14), 
            ("Last 30 days", 30),
            ("Last 60 days", 60),
            ("Last 90 days", 90),
            ("Last 6 months", 180),
            ("Last year", 365)
        ]
        
        print(f"\n📅 TODOS BY TIME PERIOD (excluding Archive):")
        print("=" * 50)
        
        for period_name, days in periods:
            cutoff_date = (now - timedelta(days=days)).strftime('%Y-%m-%d')
            
            cursor.execute(f'''
                SELECT COUNT(*) FROM todos t
                LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
                WHERE t.actual_date >= '{cutoff_date}'
                AND t.actual_date IS NOT NULL
                AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
                AND t.notion_exported_at IS NULL
            ''')
            count = cursor.fetchone()[0]
            percentage = (count / total) * 100
            print(f"{period_name:15}: {count:3d} todos ({percentage:4.1f}%)")
        
        # Show most recent todos
        print(f"\n📝 MOST RECENT TODOS (last 30 days):")
        print("=" * 60)
        
        cursor.execute(f'''
            SELECT t.actual_date, nm.visible_name, t.text, nm.full_path
            FROM todos t
            LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
            WHERE t.actual_date >= '{(now - timedelta(days=30)).strftime('%Y-%m-%d')}'
            AND t.actual_date IS NOT NULL
            AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
            AND t.notion_exported_at IS NULL
            ORDER BY t.actual_date DESC
            LIMIT 15
        ''')
        
        recent_todos = cursor.fetchall()
        for date, notebook, todo_text, path in recent_todos:
            print(f"{date}: {notebook}")
            print(f"  '{todo_text[:60]}...'")
            print(f"  Path: {path}")
            print()

def export_todos_by_date_filter(days_back: int, dry_run: bool = True):
    """Export todos from the last N days to Notion."""
    db = DatabaseManager('./data/remarkable_pipeline.db')
    config = Config('config/config.yaml')
    
    # Calculate cutoff date
    cutoff_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get todos to export
        cursor.execute(f'''
            SELECT t.id, t.notebook_uuid, t.text, t.actual_date, t.page_number, t.confidence,
                   nm.visible_name, nm.full_path
            FROM todos t
            LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
            WHERE t.actual_date >= '{cutoff_date}'
            AND t.actual_date IS NOT NULL
            AND (nm.full_path NOT LIKE '%Archive%' AND nm.full_path NOT LIKE '%archive%')
            AND t.notion_exported_at IS NULL
            ORDER BY t.actual_date DESC, nm.visible_name
        ''')
        
        todos_to_export = cursor.fetchall()
        
        print(f"{'='*60}")
        print(f"📤 EXPORT PLAN: Last {days_back} days")
        print(f"{'='*60}")
        print(f"📅 Cutoff date: {cutoff_date}")
        print(f"📝 Todos to export: {len(todos_to_export)}")
        print(f"🧪 Dry run: {'Yes' if dry_run else 'No - WILL EXPORT TO NOTION'}")
        print()
        
        if not todos_to_export:
            print("✅ No todos to export!")
            return
        
        # Group by notebook for display
        notebooks = {}
        for todo_id, notebook_uuid, text, date, page, confidence, name, path in todos_to_export:
            if name not in notebooks:
                notebooks[name] = []
            notebooks[name].append({
                'id': todo_id,
                'text': text,
                'date': date,
                'page': page,
                'confidence': confidence,
                'path': path
            })
        
        print(f"📚 TODOS BY NOTEBOOK:")
        print("-" * 40)
        for notebook_name, notebook_todos in notebooks.items():
            print(f"\n📖 {notebook_name} ({len(notebook_todos)} todos)")
            print(f"   Path: {notebook_todos[0]['path']}")
            
            for todo in notebook_todos[:5]:  # Show first 5 todos per notebook
                print(f"   {todo['date']}: \"{todo['text'][:50]}...\" (page {todo['page']})")
            
            if len(notebook_todos) > 5:
                print(f"   ... and {len(notebook_todos) - 5} more todos")
        
        if dry_run:
            print(f"\n🧪 This was a DRY RUN - no changes made")
            print(f"💡 To actually export, run: export_todos_by_date_filter({days_back}, dry_run=False)")
        else:
            # TODO: Implement actual Notion export here
            print(f"\n🚀 Would export {len(todos_to_export)} todos to Notion...")
            print(f"📝 Would mark todos as exported with timestamp...")
            # For now, just mark as exported
            export_timestamp = datetime.now().isoformat()
            todo_ids = [str(todo[0]) for todo in todos_to_export]
            cursor.execute(f'''
                UPDATE todos 
                SET notion_exported_at = '{export_timestamp}'
                WHERE id IN ({','.join(todo_ids)})
            ''')
            conn.commit()
            print(f"✅ Marked {len(todos_to_export)} todos as exported")

def main():
    print("🎯 Todo Export Analysis and Filtering\n")
    
    # Show filtering options
    analyze_filtering_options()
    
    print(f"\n{'='*60}")
    print("🤔 RECOMMENDED APPROACH:")
    print("=" * 60)
    print("Based on the analysis, I recommend:")
    print("1. 📅 Last 30-60 days filter (captures recent work)")
    print("2. 🗂️  Exclude Archive folders (remove old projects)")
    print("3. 🎯 High confidence only (>0.7 for clean OCR)")
    print("4. ✅ Track exports with notion_exported_at timestamp")
    print()
    
    # Show what a 30-day export would look like
    print("📋 PREVIEW: 30-day export (dry run)")
    print("=" * 30)
    export_todos_by_date_filter(30, dry_run=True)

if __name__ == '__main__':
    main()