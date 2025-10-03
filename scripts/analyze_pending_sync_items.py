#!/usr/bin/env python3
"""
Analyze Pending Sync Items

This script helps you understand what items are waiting to be synced
by analyzing the database and showing detailed information about content
that needs to be synchronized to various targets.
"""

import argparse
import sqlite3
import sys
import hashlib
from datetime import datetime
from typing import Dict, List, Tuple

# Add src to path
sys.path.insert(0, 'src')

from core.database import DatabaseManager
from core.unified_sync import UnifiedSyncManager
from core.sync_engine import ContentFingerprint


class PendingSyncAnalyzer:
    """Analyzes what items are pending sync to various targets."""

    def __init__(self, db_path: str):
        self.db_manager = DatabaseManager(db_path)
        self.unified_sync = UnifiedSyncManager(self.db_manager)

    def analyze_all_pending_items(self) -> Dict[str, List]:
        """Analyze pending items for all targets."""
        print("🔍 Analyzing pending sync items across all targets...\n")

        all_pending = {}

        # Check each target type
        targets = ['notion', 'readwise', 'notion_todos']

        for target_name in targets:
            print(f"📋 Analyzing {target_name.upper()} pending items:")
            print("=" * 50)

            # Get notebooks needing sync
            notebooks = self._get_notebooks_needing_sync(target_name)
            todos = self._get_todos_needing_sync(target_name)
            highlights = self._get_highlights_needing_sync(target_name)

            all_pending[target_name] = {
                'notebooks': notebooks,
                'todos': todos,
                'highlights': highlights
            }

            # Display summary
            total_items = len(notebooks) + len(todos) + len(highlights)
            print(f"  📊 Summary: {total_items} total items")
            print(f"     - {len(notebooks)} notebooks")
            print(f"     - {len(todos)} todos")
            print(f"     - {len(highlights)} highlights")
            print()

            # Display details
            if notebooks:
                print(f"  📚 NOTEBOOKS NEEDING SYNC ({len(notebooks)}):")
                for i, nb in enumerate(notebooks[:5]):  # Show first 5
                    self._display_notebook_details(nb, i+1)
                if len(notebooks) > 5:
                    print(f"     ... and {len(notebooks) - 5} more notebooks")
                print()

            if todos:
                print(f"  ✅ TODOS NEEDING SYNC ({len(todos)}):")
                for i, todo in enumerate(todos[:5]):  # Show first 5
                    self._display_todo_details(todo, i+1)
                if len(todos) > 5:
                    print(f"     ... and {len(todos) - 5} more todos")
                print()

            if highlights:
                print(f"  🔖 HIGHLIGHTS NEEDING SYNC ({len(highlights)}):")
                for i, highlight in enumerate(highlights[:5]):  # Show first 5
                    self._display_highlight_details(highlight, i+1)
                if len(highlights) > 5:
                    print(f"     ... and {len(highlights) - 5} more highlights")
                print()

            print("-" * 60)
            print()

        return all_pending

    def _get_notebooks_needing_sync(self, target_name: str) -> List[Dict]:
        """Get notebooks that need syncing for a specific target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                # Query notebooks that don't have successful sync records or have changed content
                cursor.execute('''
                    SELECT
                        nm.notebook_uuid,
                        nm.visible_name,
                        nm.full_path,
                        nm.last_modified,
                        nm.last_opened,
                        COUNT(nte.id) as page_count,
                        GROUP_CONCAT(nte.text, '\n\n') as full_text,
                        MAX(nte.updated_at) as last_content_update,
                        sr.content_hash as last_synced_hash,
                        sr.synced_at as last_sync_time,
                        sr.status as sync_status
                    FROM notebook_metadata nm
                    LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
                        AND nte.text IS NOT NULL AND LENGTH(nte.text) > 0
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = nm.notebook_uuid
                        AND sr.target_name = ?
                        AND sr.item_type = 'notebook'
                        AND sr.status = 'success'
                    )
                    WHERE nm.deleted = FALSE
                    AND (
                        sr.id IS NULL  -- Never synced
                        OR sr.status != 'success'  -- Failed sync
                    )
                    GROUP BY nm.notebook_uuid, nm.visible_name, nm.full_path, nm.last_modified, nm.last_opened
                    ORDER BY last_content_update DESC
                ''', (target_name,))

                notebooks = []
                for row in cursor.fetchall():
                    (uuid, name, path, last_mod, last_opened, page_count,
                     full_text, last_update, last_hash, last_sync, sync_status) = row

                    # Calculate current content hash
                    current_hash = None
                    if full_text:
                        current_hash = hashlib.md5(full_text.encode('utf-8')).hexdigest()

                    notebooks.append({
                        'uuid': uuid,
                        'name': name or 'Untitled',
                        'path': path or '',
                        'last_modified': last_mod,
                        'last_opened': last_opened,
                        'page_count': page_count or 0,
                        'content_length': len(full_text) if full_text else 0,
                        'last_content_update': last_update,
                        'current_hash': current_hash,
                        'last_synced_hash': last_hash,
                        'last_sync_time': last_sync,
                        'sync_status': sync_status,
                        'full_text_preview': (full_text[:200] + '...' if full_text and len(full_text) > 200 else full_text) if full_text else None
                    })

                return notebooks

        except Exception as e:
            print(f"❌ Error getting notebooks for {target_name}: {e}")
            return []

    def _get_todos_needing_sync(self, target_name: str) -> List[Dict]:
        """Get todos that need syncing for a specific target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT
                        t.id,
                        t.text,
                        t.notebook_uuid,
                        t.page_number,
                        t.completed,
                        t.updated_at,
                        nm.visible_name as notebook_name,
                        sr.content_hash as last_synced_hash,
                        sr.synced_at as last_sync_time,
                        sr.status as sync_status
                    FROM todos t
                    LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = CAST(t.id AS TEXT)
                        AND sr.target_name = ?
                        AND sr.item_type = 'todo'
                        AND sr.status = 'success'
                    )
                    WHERE t.completed = FALSE
                    AND (
                        sr.id IS NULL  -- Never synced
                        OR sr.status != 'success'  -- Failed sync
                    )
                    ORDER BY t.updated_at DESC
                ''', (target_name,))

                todos = []
                for row in cursor.fetchall():
                    (todo_id, text, notebook_uuid, page_num, completed, updated_at,
                     notebook_name, last_hash, last_sync, sync_status) = row

                    # Calculate current content hash
                    current_hash = hashlib.md5(text.encode('utf-8')).hexdigest() if text else None

                    todos.append({
                        'id': todo_id,
                        'text': text,
                        'notebook_uuid': notebook_uuid,
                        'notebook_name': notebook_name or 'Unknown',
                        'page_number': page_num,
                        'completed': completed,
                        'updated_at': updated_at,
                        'current_hash': current_hash,
                        'last_synced_hash': last_hash,
                        'last_sync_time': last_sync,
                        'sync_status': sync_status
                    })

                return todos

        except Exception as e:
            print(f"❌ Error getting todos for {target_name}: {e}")
            return []

    def _get_highlights_needing_sync(self, target_name: str) -> List[Dict]:
        """Get highlights that need syncing for a specific target."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('''
                    SELECT
                        eh.id,
                        eh.original_text,
                        eh.corrected_text,
                        eh.source_file,
                        eh.page_number,
                        eh.confidence,
                        eh.updated_at,
                        eh.title,
                        sr.content_hash as last_synced_hash,
                        sr.synced_at as last_sync_time,
                        sr.status as sync_status
                    FROM enhanced_highlights eh
                    LEFT JOIN sync_records sr ON (
                        sr.item_id = CAST(eh.id AS TEXT)
                        AND sr.target_name = ?
                        AND sr.item_type = 'highlight'
                        AND sr.status = 'success'
                    )
                    WHERE (
                        sr.id IS NULL  -- Never synced
                        OR sr.status != 'success'  -- Failed sync
                    )
                    ORDER BY eh.updated_at DESC
                ''', (target_name,))

                highlights = []
                for row in cursor.fetchall():
                    (highlight_id, original, corrected, source, page_num, confidence,
                     updated_at, title, last_hash, last_sync, sync_status) = row

                    # Calculate current content hash
                    text_to_hash = corrected or original or ''
                    current_hash = hashlib.md5(text_to_hash.encode('utf-8')).hexdigest() if text_to_hash else None

                    highlights.append({
                        'id': highlight_id,
                        'original_text': original,
                        'corrected_text': corrected,
                        'source_file': source,
                        'title': title,
                        'page_number': page_num,
                        'confidence': confidence,
                        'updated_at': updated_at,
                        'current_hash': current_hash,
                        'last_synced_hash': last_hash,
                        'last_sync_time': last_sync,
                        'sync_status': sync_status
                    })

                return highlights

        except Exception as e:
            print(f"❌ Error getting highlights for {target_name}: {e}")
            return []

    def _display_notebook_details(self, notebook: Dict, index: int):
        """Display detailed notebook information."""
        print(f"     {index}. 📚 {notebook['name']}")
        print(f"        UUID: {notebook['uuid']}")
        print(f"        Path: {notebook['path']}")
        print(f"        Pages: {notebook['page_count']}")
        print(f"        Content: {notebook['content_length']:,} characters")

        if notebook['last_opened']:
            try:
                # Try to parse reMarkable timestamp
                if notebook['last_opened'].isdigit():
                    timestamp = int(notebook['last_opened']) / 1000
                    readable_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    print(f"        Last Opened: {readable_time}")
                else:
                    print(f"        Last Opened: {notebook['last_opened']}")
            except:
                print(f"        Last Opened: {notebook['last_opened']}")

        # Sync status
        if notebook['last_sync_time']:
            print(f"        Last Sync: {notebook['last_sync_time']} ({notebook['sync_status']})")
        else:
            print(f"        Last Sync: Never synced")

        # Content hash comparison
        if notebook['current_hash'] and notebook['last_synced_hash']:
            if notebook['current_hash'] == notebook['last_synced_hash']:
                print(f"        Status: ✅ Content unchanged since last sync")
            else:
                print(f"        Status: 🔄 Content changed since last sync")
        elif not notebook['last_synced_hash']:
            print(f"        Status: 🆕 Never synced before")
        else:
            print(f"        Status: ❓ Cannot determine sync status")

        # Content preview
        if notebook['full_text_preview']:
            print(f"        Preview: {notebook['full_text_preview']}")

        print()

    def _display_todo_details(self, todo: Dict, index: int):
        """Display detailed todo information."""
        print(f"     {index}. ✅ {todo['text'][:80]}{'...' if len(todo['text']) > 80 else ''}")
        print(f"        ID: {todo['id']}")
        print(f"        Notebook: {todo['notebook_name']} (Page {todo['page_number']})")
        print(f"        Updated: {todo['updated_at']}")

        # Sync status
        if todo['last_sync_time']:
            print(f"        Last Sync: {todo['last_sync_time']} ({todo['sync_status']})")
        else:
            print(f"        Last Sync: Never synced")

        # Content hash comparison
        if todo['current_hash'] and todo['last_synced_hash']:
            if todo['current_hash'] == todo['last_synced_hash']:
                print(f"        Status: ✅ Unchanged since last sync")
            else:
                print(f"        Status: 🔄 Changed since last sync")
        else:
            print(f"        Status: 🆕 Never synced")

        print()

    def _display_highlight_details(self, highlight: Dict, index: int):
        """Display detailed highlight information."""
        text = highlight['corrected_text'] or highlight['original_text'] or 'No text'
        print(f"     {index}. 🔖 {text[:80]}{'...' if len(text) > 80 else ''}")
        print(f"        ID: {highlight['id']}")
        print(f"        Source: {highlight['title'] or highlight['source_file']}")
        print(f"        Page: {highlight['page_number']}")
        print(f"        Confidence: {highlight['confidence']:.2f}" if highlight['confidence'] else "        Confidence: N/A")
        print(f"        Updated: {highlight['updated_at']}")

        # Sync status
        if highlight['last_sync_time']:
            print(f"        Last Sync: {highlight['last_sync_time']} ({highlight['sync_status']})")
        else:
            print(f"        Last Sync: Never synced")

        print()

    def get_sync_statistics(self) -> Dict:
        """Get overall sync statistics."""
        stats = {}

        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()

            # Total items by type
            cursor.execute('SELECT COUNT(*) FROM notebook_metadata WHERE deleted = FALSE')
            stats['total_notebooks'] = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM todos WHERE completed = FALSE')
            stats['total_todos'] = cursor.fetchone()[0]

            cursor.execute('SELECT COUNT(*) FROM enhanced_highlights')
            stats['total_highlights'] = cursor.fetchone()[0]

            # Sync record statistics
            cursor.execute('''
                SELECT target_name, item_type, status, COUNT(*) as count
                FROM sync_records
                GROUP BY target_name, item_type, status
                ORDER BY target_name, item_type, status
            ''')

            sync_stats = {}
            for target, item_type, status, count in cursor.fetchall():
                if target not in sync_stats:
                    sync_stats[target] = {}
                if item_type not in sync_stats[target]:
                    sync_stats[target][item_type] = {}
                sync_stats[target][item_type][status] = count

            stats['sync_records'] = sync_stats

        return stats

    def display_summary_statistics(self):
        """Display overall sync statistics."""
        print("📊 SYNC STATISTICS SUMMARY")
        print("=" * 50)

        stats = self.get_sync_statistics()

        print(f"📚 Total Notebooks: {stats['total_notebooks']}")
        print(f"✅ Total Todos: {stats['total_todos']}")
        print(f"🔖 Total Highlights: {stats['total_highlights']}")
        print()

        print("🎯 Sync Records by Target:")
        for target, items in stats['sync_records'].items():
            print(f"  {target.upper()}:")
            for item_type, statuses in items.items():
                total = sum(statuses.values())
                success = statuses.get('success', 0)
                failed = statuses.get('failed', 0)
                pending = statuses.get('pending', 0)

                print(f"    {item_type}: {total} total ({success} success, {failed} failed, {pending} pending)")
        print()


def main():
    parser = argparse.ArgumentParser(description='Analyze pending sync items')
    parser.add_argument('--database', '-d', default='data/remarkable_pipeline.db',
                       help='Database path (default: data/remarkable_pipeline.db)')
    parser.add_argument('--target', '-t', choices=['notion', 'readwise', 'notion_todos'],
                       help='Analyze specific target only')
    parser.add_argument('--summary-only', '-s', action='store_true',
                       help='Show only summary statistics')
    parser.add_argument('--limit', '-l', type=int, default=10,
                       help='Limit number of items to show per category (default: 10)')

    args = parser.parse_args()

    try:
        analyzer = PendingSyncAnalyzer(args.database)

        print(f"🔍 Analyzing pending sync items in: {args.database}")
        print(f"📅 Analysis time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()

        # Show summary statistics
        analyzer.display_summary_statistics()

        if not args.summary_only:
            # Analyze pending items
            if args.target:
                print(f"🎯 Focusing on target: {args.target.upper()}")
                # TODO: Add single target analysis
            else:
                analyzer.analyze_all_pending_items()

    except FileNotFoundError:
        print(f"❌ Database not found: {args.database}")
        return 1
    except Exception as e:
        print(f"❌ Error analyzing sync items: {e}")
        return 1

    return 0


if __name__ == '__main__':
    exit(main())