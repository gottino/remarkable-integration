#!/usr/bin/env python3
"""
Migration 004: Add notebook associations to highlights table.

Adds missing fields needed to associate highlights with their source notebooks:
- notebook_uuid: UUID of the source notebook
- page_uuid: UUID of the specific page (for multi-page documents)
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def apply_migration(cursor: sqlite3.Cursor):
    """Apply the migration to add notebook associations to highlights table."""
    
    # Add notebook_uuid column
    try:
        cursor.execute('ALTER TABLE highlights ADD COLUMN notebook_uuid TEXT')
        logger.info("Added notebook_uuid column to highlights")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            logger.debug("notebook_uuid column already exists")
        else:
            raise
    
    # Add page_uuid column
    try:
        cursor.execute('ALTER TABLE highlights ADD COLUMN page_uuid TEXT')
        logger.info("Added page_uuid column to highlights")
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e).lower():
            logger.debug("page_uuid column already exists")
        else:
            raise
    
    # Create indexes for faster lookups
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_highlights_notebook_uuid ON highlights(notebook_uuid)')
        logger.info("Created index on notebook_uuid")
    except Exception as e:
        logger.warning(f"Could not create index on notebook_uuid: {e}")
    
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_highlights_page_uuid ON highlights(page_uuid)')
        logger.info("Created index on page_uuid")
    except Exception as e:
        logger.warning(f"Could not create index on page_uuid: {e}")

def backfill_notebook_associations(cursor: sqlite3.Cursor):
    """
    Backfill notebook_uuid for existing highlights based on source_file patterns.
    
    reMarkable source files follow the pattern:
    - UUID.content for notebook content
    - UUID/page_uuid.rm for individual pages
    """
    logger.info("Backfilling notebook associations for existing highlights...")
    
    try:
        # Get all highlights without notebook_uuid
        cursor.execute("""
            SELECT id, source_file, title 
            FROM highlights 
            WHERE notebook_uuid IS NULL
        """)
        highlights = cursor.fetchall()
        
        logger.info(f"Found {len(highlights)} highlights to backfill")
        
        updated_count = 0
        for highlight_id, source_file, title in highlights:
            notebook_uuid = None
            page_uuid = None
            
            # Extract UUID from different source_file patterns
            if source_file:
                # Pattern 1: "UUID.content" -> notebook_uuid = UUID
                if source_file.endswith('.content'):
                    notebook_uuid = source_file[:-8]  # Remove ".content"
                
                # Pattern 2: "UUID/page_uuid.rm" -> notebook_uuid = UUID, page_uuid = page_uuid
                elif '/' in source_file and source_file.endswith('.rm'):
                    parts = source_file.split('/')
                    if len(parts) >= 2:
                        notebook_uuid = parts[0]
                        page_file = parts[-1]  # Get the last part (filename)
                        if page_file.endswith('.rm'):
                            page_uuid = page_file[:-3]  # Remove ".rm"
                
                # Pattern 3: Just a UUID string (less common)
                elif len(source_file) == 36 and source_file.count('-') == 4:
                    # Looks like a plain UUID
                    notebook_uuid = source_file
            
            # Update the highlight if we found a notebook_uuid
            if notebook_uuid:
                cursor.execute("""
                    UPDATE highlights 
                    SET notebook_uuid = ?, page_uuid = ?
                    WHERE id = ?
                """, (notebook_uuid, page_uuid, highlight_id))
                updated_count += 1
                
                if updated_count % 100 == 0:
                    logger.debug(f"Backfilled {updated_count} highlights...")
        
        logger.info(f"Successfully backfilled {updated_count} highlight associations")
        return updated_count
        
    except Exception as e:
        logger.error(f"Error during backfill: {e}")
        return 0

if __name__ == "__main__":
    # Run migration directly
    import sys
    import os
    
    # Add project root to path
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    from src.core.database import DatabaseManager
    from src.utils.config import Config
    
    # Load config and get database path
    config = Config()
    db_path = config.get("database.path", "./data/remarkable_pipeline.db")
    
    print(f"🔧 Running migration 004 on database: {db_path}")
    
    try:
        db_manager = DatabaseManager(db_path)
        with db_manager.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Apply migration
            apply_migration(cursor)
            
            # Backfill existing data
            backfilled = backfill_notebook_associations(cursor)
            
            # Record migration in schema_migrations table
            cursor.execute(
                'INSERT OR IGNORE INTO schema_migrations (version, description) VALUES (?, ?)',
                (4, 'Add notebook associations to highlights table')
            )
            
            conn.commit()
            print(f"✅ Migration 004 completed successfully. Backfilled {backfilled} highlights.")
            
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)