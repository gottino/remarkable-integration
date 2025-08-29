#!/usr/bin/env python3
"""
Incremental sync utilities for Notion integration.

Handles smart updates that only sync changed content instead of replacing
entire pages, enabling efficient incremental updates.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any

from ..core.database import DatabaseManager

logger = logging.getLogger(__name__)


class NotionSyncTracker:
    """Tracks sync state and detects changes for incremental updates."""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self._init_sync_tracking_tables()
    
    def _init_sync_tracking_tables(self):
        """Initialize tables for tracking sync state."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Table to track notebook-level sync state
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notion_notebook_sync (
                    notebook_uuid TEXT PRIMARY KEY,
                    notion_page_id TEXT NOT NULL,
                    last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    content_hash TEXT,  -- Hash of all page content
                    total_pages INTEGER,
                    metadata_hash TEXT  -- Hash of metadata (path, timestamps, etc.)
                )
            ''')
            
            # Table to track page-level sync state  
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notion_page_sync (
                    notebook_uuid TEXT,
                    page_number INTEGER,
                    page_uuid TEXT,
                    content_hash TEXT,  -- Hash of page content
                    last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    notion_block_id TEXT,  -- ID of toggle block in Notion
                    PRIMARY KEY (notebook_uuid, page_number)
                )
            ''')
            
            conn.commit()
    
    def get_notebook_changes(self, notebook_uuid: str) -> Dict[str, Any]:
        """
        Analyze what has changed for a notebook since last sync.
        
        Returns:
            Dict with 'is_new', 'content_changed', 'metadata_changed', 'new_pages', 'changed_pages'
        """
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get current notebook state
            # Indices: 0=notebook_uuid, 1=notebook_name, 2=page_uuid, 3=confidence, 4=page_number, 5=text, 6=full_path, 7=last_modified, 8=last_opened
            cursor.execute('''
                SELECT 
                    nte.notebook_uuid, nte.notebook_name, nte.page_uuid, nte.confidence, 
                    nte.page_number, nte.text, nm.full_path, nm.last_modified, nm.last_opened
                FROM notebook_text_extractions nte
                LEFT JOIN notebook_metadata nm ON nte.notebook_uuid = nm.notebook_uuid
                WHERE nte.notebook_uuid = ?
                AND nte.text IS NOT NULL AND length(nte.text) > 10
                ORDER BY nte.page_number
            ''', (notebook_uuid,))
            
            current_pages = cursor.fetchall()
            if not current_pages:
                return {'is_new': True, 'content_changed': False, 'metadata_changed': False}
            
            # Calculate current content and metadata hashes
            current_content_hash = self._calculate_content_hash(current_pages)
            current_metadata_hash = self._calculate_metadata_hash(current_pages[0])
            current_total_pages = len(current_pages)
            
            # Get last sync state
            cursor.execute('''
                SELECT content_hash, total_pages, metadata_hash, notion_page_id, last_synced
                FROM notion_notebook_sync 
                WHERE notebook_uuid = ?
            ''', (notebook_uuid,))
            
            last_sync = cursor.fetchone()
            
            if not last_sync:
                # New notebook
                return {
                    'is_new': True,
                    'content_changed': True,
                    'metadata_changed': True,
                    'new_pages': list(range(1, current_total_pages + 1)),
                    'changed_pages': [],
                    'current_content_hash': current_content_hash,
                    'current_metadata_hash': current_metadata_hash,
                    'current_total_pages': current_total_pages
                }
            
            last_content_hash, last_total_pages, last_metadata_hash, notion_page_id, last_synced = last_sync
            
            # Check what changed
            content_changed = (current_content_hash != last_content_hash) or (current_total_pages != last_total_pages)
            metadata_changed = current_metadata_hash != last_metadata_hash
            
            # Find new and changed pages
            new_pages = []
            changed_pages = []
            
            if content_changed:
                # Get page-level sync state
                cursor.execute('''
                    SELECT page_number, content_hash
                    FROM notion_page_sync
                    WHERE notebook_uuid = ?
                ''', (notebook_uuid,))
                
                synced_pages = {page_num: content_hash for page_num, content_hash in cursor.fetchall()}
                
                for page_data in current_pages:
                    page_number = page_data[4]  # page_number is at index 4
                    page_content_hash = self._calculate_page_content_hash(page_data)
                    
                    if page_number not in synced_pages:
                        new_pages.append(page_number)
                    elif synced_pages[page_number] != page_content_hash:
                        changed_pages.append(page_number)
            
            return {
                'is_new': False,
                'content_changed': content_changed,
                'metadata_changed': metadata_changed,
                'new_pages': new_pages,
                'changed_pages': changed_pages,
                'current_content_hash': current_content_hash,
                'current_metadata_hash': current_metadata_hash,
                'current_total_pages': current_total_pages,
                'notion_page_id': notion_page_id,
                'last_synced': last_synced
            }
    
    def mark_notebook_synced(self, notebook_uuid: str, notion_page_id: str, 
                           content_hash: str, metadata_hash: str, total_pages: int):
        """Mark a notebook as synced with current state."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO notion_notebook_sync 
                (notebook_uuid, notion_page_id, content_hash, metadata_hash, total_pages, last_synced)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (notebook_uuid, notion_page_id, content_hash, metadata_hash, total_pages, datetime.now()))
            conn.commit()
    
    def mark_page_synced(self, notebook_uuid: str, page_number: int, page_uuid: str, 
                        content_hash: str, notion_block_id: Optional[str] = None):
        """Mark a specific page as synced."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO notion_page_sync 
                (notebook_uuid, page_number, page_uuid, content_hash, notion_block_id, last_synced)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (notebook_uuid, page_number, page_uuid, content_hash, notion_block_id, datetime.now()))
            conn.commit()
    
    def get_synced_notebooks(self) -> Set[str]:
        """Get set of notebook UUIDs that have been synced to Notion."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT notebook_uuid FROM notion_notebook_sync')
            return {row[0] for row in cursor.fetchall()}
    
    def remove_sync_record(self, notebook_uuid: str):
        """Remove sync tracking for a notebook (e.g., if deleted from Notion)."""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM notion_notebook_sync WHERE notebook_uuid = ?', (notebook_uuid,))
            cursor.execute('DELETE FROM notion_page_sync WHERE notebook_uuid = ?', (notebook_uuid,))
            conn.commit()
    
    def _calculate_content_hash(self, pages_data: List[Tuple]) -> str:
        """Calculate hash of all page content for a notebook."""
        # Sort by page number to ensure consistent hashing
        sorted_pages = sorted(pages_data, key=lambda x: x[4])  # page_number at index 4
        
        content_parts = []
        for page_data in sorted_pages:
            page_number, text, confidence = page_data[4], page_data[5], page_data[3]  # Fixed confidence index
            content_parts.append(f"page_{page_number}:{text}:{confidence}")
        
        combined_content = '|'.join(content_parts)
        return hashlib.md5(combined_content.encode('utf-8')).hexdigest()
    
    def _calculate_metadata_hash(self, first_page_data: Tuple) -> str:
        """Calculate hash of notebook metadata."""
        # Metadata from first page (all pages have same metadata)
        # Indices: 6=full_path, 7=last_modified, 8=last_opened
        full_path = first_page_data[6] or ''  # index 6
        last_modified = first_page_data[7] or ''  # index 7  
        last_opened = first_page_data[8] or ''  # index 8
        
        metadata_content = f"path:{full_path}|modified:{last_modified}|opened:{last_opened}"
        return hashlib.md5(metadata_content.encode('utf-8')).hexdigest()
    
    def _calculate_page_content_hash(self, page_data: Tuple) -> str:
        """Calculate hash of a single page's content."""
        text, confidence = page_data[5], page_data[3]  # indices 5=text, 3=confidence
        page_content = f"{text}:{confidence}"
        return hashlib.md5(page_content.encode('utf-8')).hexdigest()


def should_sync_notebook(notebook_uuid: str, sync_tracker: NotionSyncTracker, 
                        force_update: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """
    Determine if a notebook should be synced and what type of sync is needed.
    
    Args:
        notebook_uuid: UUID of notebook to check
        sync_tracker: Sync tracking instance
        force_update: If True, sync even if no changes detected
        
    Returns:
        Tuple of (should_sync, change_info)
    """
    if force_update:
        # For force updates, we still want to know what changed for logging
        changes = sync_tracker.get_notebook_changes(notebook_uuid)
        return True, changes
    
    changes = sync_tracker.get_notebook_changes(notebook_uuid)
    
    # Sync if it's new or if there are content/metadata changes
    should_sync = (
        changes['is_new'] or 
        changes['content_changed'] or 
        changes['metadata_changed']
    )
    
    return should_sync, changes


def log_sync_decision(notebook_name: str, notebook_uuid: str, should_sync: bool, changes: Dict[str, Any]):
    """Log the sync decision and reasoning."""
    if not should_sync:
        logger.info(f"⏭️ Skipping {notebook_name}: No changes detected")
        return
    
    if changes['is_new']:
        logger.info(f"📄 New notebook: {notebook_name}")
    else:
        change_reasons = []
        if changes['content_changed']:
            new_pages = len(changes.get('new_pages', []))
            changed_pages = len(changes.get('changed_pages', []))
            change_reasons.append(f"{new_pages} new pages, {changed_pages} changed pages")
        
        if changes['metadata_changed']:
            change_reasons.append("metadata updated")
        
        reason = ", ".join(change_reasons)
        logger.info(f"🔄 Updating {notebook_name}: {reason}")