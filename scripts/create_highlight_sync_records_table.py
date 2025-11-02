#!/usr/bin/env python3
"""Create highlight_sync_records table for per-highlight sync tracking."""

import sys
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config


def main():
    """Create the highlight_sync_records table."""

    # Load config
    config = Config()
    db_path = config.get('database.path')

    print("=" * 80)
    print("Creating highlight_sync_records Table")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if table already exists
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='highlight_sync_records'
    """)

    if cursor.fetchone():
        print("⚠️  Table 'highlight_sync_records' already exists")
        response = input("Drop and recreate? (y/N): ")
        if response.lower() != 'y':
            print("Aborted")
            conn.close()
            return

        cursor.execute("DROP TABLE highlight_sync_records")
        print("✓ Dropped existing table")

    # Create table
    cursor.execute("""
        CREATE TABLE highlight_sync_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            highlight_id INTEGER NOT NULL,
            notebook_uuid TEXT NOT NULL,
            target_name TEXT NOT NULL,
            external_id TEXT,
            content_hash TEXT NOT NULL,
            synced_at TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'pending',
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(highlight_id, target_name),
            FOREIGN KEY (highlight_id) REFERENCES enhanced_highlights(id) ON DELETE CASCADE
        )
    """)

    print("✓ Created table 'highlight_sync_records'")

    # Create indexes for efficient queries
    cursor.execute("""
        CREATE INDEX idx_highlight_sync_highlight_id
        ON highlight_sync_records(highlight_id)
    """)

    cursor.execute("""
        CREATE INDEX idx_highlight_sync_notebook_uuid
        ON highlight_sync_records(notebook_uuid)
    """)

    cursor.execute("""
        CREATE INDEX idx_highlight_sync_target
        ON highlight_sync_records(target_name)
    """)

    cursor.execute("""
        CREATE INDEX idx_highlight_sync_status
        ON highlight_sync_records(status)
    """)

    cursor.execute("""
        CREATE INDEX idx_highlight_sync_content_hash
        ON highlight_sync_records(content_hash)
    """)

    print("✓ Created indexes")

    conn.commit()

    # Show table schema
    cursor.execute("PRAGMA table_info(highlight_sync_records)")
    columns = cursor.fetchall()

    print()
    print("Table schema:")
    print("-" * 80)
    for col in columns:
        print(f"  {col[1]:20} {col[2]:15} {'NOT NULL' if col[3] else ''}")

    conn.close()

    print()
    print("=" * 80)
    print("✅ Table created successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
