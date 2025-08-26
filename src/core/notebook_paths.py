"""
reMarkable notebook path management.
Handles building and storing folder hierarchy from .metadata files.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass
import sqlite3

logger = logging.getLogger(__name__)

@dataclass
class RemarkableItem:
    """Represents a reMarkable item (folder or document) with complete metadata."""
    uuid: str
    visible_name: str
    parent: Optional[str]
    item_type: str  # 'CollectionType' for folders, 'DocumentType' for documents
    document_type: str = 'unknown'  # 'notebook', 'pdf', 'epub', 'folder', 'unknown'
    last_modified: Optional[str] = None
    last_opened: Optional[str] = None
    last_opened_page: Optional[int] = None
    deleted: bool = False
    pinned: bool = False
    synced: bool = False
    version: Optional[int] = None
    path: Optional[str] = None

class NotebookPathManager:
    """Manages reMarkable notebook folder paths and database integration."""
    
    def __init__(self, remarkable_dir: str, db_connection=None):
        self.remarkable_dir = Path(remarkable_dir)
        self.db_connection = db_connection
        self.items: Dict[str, RemarkableItem] = {}
        self.paths_cache: Dict[str, str] = {}
    
    def _get_document_type(self, uuid: str) -> str:
        """
        Determine the actual document type by reading .content file.
        
        Returns:
            'notebook' - handwritten notebook
            'pdf' - PDF document
            'epub' - EPUB document  
            'folder' - collection/folder
            'unknown' - cannot determine
        """
        # Check if it's a folder first (no .content file)
        content_file = self.remarkable_dir / f"{uuid}.content"
        
        if not content_file.exists():
            return 'folder'
        
        try:
            with open(content_file, 'r') as f:
                content_data = json.load(f)
            
            file_type = content_data.get('fileType', '')
            
            if file_type == '':
                # Empty fileType usually means handwritten notebook
                return 'notebook'
            elif file_type == 'notebook':
                return 'notebook'  
            elif file_type == 'pdf':
                return 'pdf'
            elif file_type == 'epub':
                return 'epub'
            else:
                logger.debug(f"Unknown fileType '{file_type}' for {uuid}")
                return 'unknown'
                
        except Exception as e:
            logger.debug(f"Could not read content file for {uuid}: {e}")
            return 'unknown'

    def scan_metadata_files(self) -> None:
        """Scan all .metadata files in the reMarkable directory and determine document types."""
        logger.info(f"Scanning metadata files in: {self.remarkable_dir}")
        
        metadata_files = list(self.remarkable_dir.glob("*.metadata"))
        logger.info(f"Found {len(metadata_files)} metadata files")
        
        for metadata_file in metadata_files:
            try:
                uuid = metadata_file.stem
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                # Determine document type
                document_type = self._get_document_type(uuid)
                
                item = RemarkableItem(
                    uuid=uuid,
                    visible_name=metadata.get('visibleName', 'Unknown'),
                    parent=metadata.get('parent', ''),  # Empty string means root
                    item_type=metadata.get('type', 'Unknown'),
                    document_type=document_type,
                    last_modified=metadata.get('lastModified'),
                    last_opened=metadata.get('lastOpened'),
                    last_opened_page=metadata.get('lastOpenedPage'),
                    deleted=metadata.get('deleted', False),
                    pinned=metadata.get('pinned', False),
                    synced=metadata.get('synced', False),
                    version=metadata.get('version')
                )
                
                # Convert empty parent to None for root items
                if item.parent == '':
                    item.parent = None
                    
                self.items[uuid] = item
                
                logger.debug(f"Loaded: {item.visible_name} (UUID: {uuid[:8]}..., Type: {document_type}, Parent: {item.parent[:8] if item.parent else 'ROOT'})")
                
            except Exception as e:
                logger.warning(f"Error reading {metadata_file}: {e}")
        
        # Log statistics
        doc_types = {}
        for item in self.items.values():
            doc_types[item.document_type] = doc_types.get(item.document_type, 0) + 1
        
        logger.info(f"Successfully loaded {len(self.items)} items:")
        for doc_type, count in sorted(doc_types.items()):
            logger.info(f"  📄 {doc_type}: {count}")
    
    def build_path(self, uuid: str) -> str:
        """Build the full path for an item by traversing up the parent chain."""
        if uuid in self.paths_cache:
            return self.paths_cache[uuid]
        
        if uuid not in self.items:
            logger.warning(f"UUID {uuid} not found in items")
            return f"<UNKNOWN>/{uuid}"
        
        item = self.items[uuid]
        
        # Base case: root item
        if item.parent is None:
            path = item.visible_name
        else:
            # Recursive case: get parent path and append this item's name
            parent_path = self.build_path(item.parent)
            path = f"{parent_path}/{item.visible_name}"
        
        # Cache the result
        self.paths_cache[uuid] = path
        return path
    
    def build_all_paths(self) -> Dict[str, str]:
        """Build paths for all items."""
        logger.info("Building full paths for all items...")
        
        for uuid in self.items:
            self.build_path(uuid)
        
        return self.paths_cache.copy()
    
    def get_notebook_path(self, uuid: str) -> Optional[str]:
        """Get the full path for a specific notebook UUID."""
        if uuid not in self.paths_cache:
            self.build_path(uuid)
        return self.paths_cache.get(uuid)
    
    def create_metadata_table(self) -> None:
        """Create the notebook_metadata table in the database."""
        if not self.db_connection:
            logger.warning("No database connection available")
            return
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notebook_metadata (
                    notebook_uuid TEXT PRIMARY KEY,
                    visible_name TEXT NOT NULL,
                    full_path TEXT NOT NULL,
                    parent_uuid TEXT,
                    item_type TEXT NOT NULL,
                    document_type TEXT NOT NULL DEFAULT 'unknown',
                    last_modified TEXT,
                    last_opened TEXT,
                    last_opened_page INTEGER,
                    deleted BOOLEAN DEFAULT FALSE,
                    pinned BOOLEAN DEFAULT FALSE,
                    synced BOOLEAN DEFAULT FALSE,
                    version INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Add document_type column to existing databases if it doesn't exist
            try:
                cursor.execute('ALTER TABLE notebook_metadata ADD COLUMN document_type TEXT DEFAULT "unknown"')
                logger.info("Added document_type column to existing notebook_metadata table")
            except:
                # Column already exists, ignore
                pass
            
            # Create indexes for faster lookups
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_notebook_metadata_path 
                ON notebook_metadata(full_path)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_notebook_metadata_last_modified 
                ON notebook_metadata(last_modified)
            ''')
            
            self.db_connection.commit()
            logger.info("Created notebook_metadata table")
            
        except Exception as e:
            logger.error(f"Error creating notebook_metadata table: {e}")
    
    def store_metadata_in_database(self) -> int:
        """Store all notebook metadata in the database."""
        if not self.db_connection:
            logger.warning("No database connection available")
            return 0
        
        try:
            cursor = self.db_connection.cursor()
            
            # Clear existing metadata
            cursor.execute('DELETE FROM notebook_metadata')
            
            # Insert all metadata
            stored_count = 0
            for uuid, item in self.items.items():
                path = self.build_path(uuid)
                
                cursor.execute('''
                    INSERT INTO notebook_metadata 
                    (notebook_uuid, visible_name, full_path, parent_uuid, item_type, document_type,
                     last_modified, last_opened, last_opened_page, deleted, pinned, synced, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    uuid,
                    item.visible_name,
                    path,
                    item.parent,
                    item.item_type,
                    item.document_type,
                    item.last_modified,
                    item.last_opened,
                    item.last_opened_page,
                    item.deleted,
                    item.pinned,
                    item.synced,
                    item.version
                ))
                stored_count += 1
            
            self.db_connection.commit()
            logger.info(f"Stored {stored_count} notebook metadata records in database")
            return stored_count
            
        except Exception as e:
            logger.error(f"Error storing metadata in database: {e}")
            return 0
    
    def get_path_from_database(self, notebook_uuid: str) -> Optional[str]:
        """Get notebook path from database."""
        if not self.db_connection:
            return None
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                'SELECT full_path FROM notebook_metadata WHERE notebook_uuid = ?', 
                (notebook_uuid,)
            )
            result = cursor.fetchone()
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"Error getting path from database: {e}")
            return None
    
    def update_database_metadata(self) -> int:
        """Update database with current remarkable directory metadata."""
        logger.info("Updating notebook metadata in database...")
        
        # Scan and build paths
        self.scan_metadata_files()
        self.build_all_paths()
        
        # Create table if needed
        self.create_metadata_table()
        
        # Store in database
        return self.store_metadata_in_database()
    
    def get_documents_with_paths(self) -> Dict[str, str]:
        """Get only documents (not folders) with their full paths."""
        documents = {}
        
        for uuid, item in self.items.items():
            if item.item_type == 'DocumentType':
                path = self.build_path(uuid)
                documents[uuid] = path
        
        return documents

def update_notebook_metadata(remarkable_dir: str, db_connection) -> int:
    """Convenience function to update notebook metadata in database."""
    manager = NotebookPathManager(remarkable_dir, db_connection)
    return manager.update_database_metadata()

def get_notebook_path(notebook_uuid: str, db_connection) -> Optional[str]:
    """Convenience function to get notebook path from database."""
    if not db_connection:
        return None
    
    try:
        cursor = db_connection.cursor()
        cursor.execute(
            'SELECT full_path FROM notebook_metadata WHERE notebook_uuid = ?', 
            (notebook_uuid,)
        )
        result = cursor.fetchone()
        return result[0] if result else None
        
    except Exception as e:
        logger.error(f"Error getting notebook path: {e}")
        return None

def get_notebook_metadata(notebook_uuid: str, db_connection) -> Optional[Dict]:
    """Convenience function to get complete notebook metadata from database."""
    if not db_connection:
        return None
    
    try:
        cursor = db_connection.cursor()
        cursor.execute('''
            SELECT notebook_uuid, visible_name, full_path, parent_uuid, item_type,
                   last_modified, last_opened, last_opened_page, deleted, pinned, synced, version
            FROM notebook_metadata WHERE notebook_uuid = ?
        ''', (notebook_uuid,))
        result = cursor.fetchone()
        
        if result:
            return {
                'notebook_uuid': result[0],
                'visible_name': result[1],
                'full_path': result[2],
                'parent_uuid': result[3],
                'item_type': result[4],
                'last_modified': result[5],
                'last_opened': result[6],
                'last_opened_page': result[7],
                'deleted': result[8],
                'pinned': result[9],
                'synced': result[10],
                'version': result[11]
            }
        return None
        
    except Exception as e:
        logger.error(f"Error getting notebook metadata: {e}")
        return None