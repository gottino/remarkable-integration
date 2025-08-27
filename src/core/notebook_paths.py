"""
reMarkable notebook path management.
Handles building and storing folder hierarchy from .metadata files.
"""

import json
import logging
import zipfile
import shutil
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass
import sqlite3
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

@dataclass
class RemarkableItem:
    """Represents a reMarkable item (folder or document) with complete metadata."""
    uuid: str
    visible_name: str
    parent: Optional[str]
    item_type: str  # 'CollectionType' for folders, 'DocumentType' for documents
    document_type: str = 'unknown'  # 'notebook', 'pdf', 'epub', 'folder', 'unknown'
    authors: Optional[str] = None  # For EPUB/PDF: comma-separated author names
    publisher: Optional[str] = None  # For EPUB/PDF: publisher name
    publication_date: Optional[str] = None  # For EPUB/PDF: publication date (ISO format)
    cover_image_path: Optional[str] = None  # For EPUB/PDF: path to extracted cover image
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
    
    def __init__(self, remarkable_dir: str, db_connection=None, data_dir: str = None):
        self.remarkable_dir = Path(remarkable_dir)
        self.db_connection = db_connection
        self.data_dir = Path(data_dir) if data_dir else Path('/data')
        self.items: Dict[str, RemarkableItem] = {}
        self.paths_cache: Dict[str, str] = {}
    
    def _get_document_metadata(self, uuid: str) -> tuple[str, Optional[str], Optional[str], Optional[str], Optional[str]]:
        """
        Extract document type and metadata by reading .content file.
        
        Returns:
            Tuple of (document_type, authors, publisher, publication_date, cover_image_path)
            - document_type: 'notebook', 'pdf', 'epub', 'folder', 'unknown'
            - authors: comma-separated author names (for EPUB/PDF)
            - publisher: publisher name (for EPUB/PDF) 
            - publication_date: ISO date string (for EPUB/PDF)
            - cover_image_path: path to extracted cover image (for EPUB/PDF)
        """
        # Check if it's a folder first (no .content file)
        content_file = self.remarkable_dir / f"{uuid}.content"
        
        if not content_file.exists():
            return 'folder', None, None, None, None
        
        try:
            with open(content_file, 'r') as f:
                content_data = json.load(f)
            
            file_type = content_data.get('fileType', '')
            
            if file_type == '':
                # Empty fileType usually means handwritten notebook
                return 'notebook', None, None, None, None
            elif file_type == 'notebook':
                return 'notebook', None, None, None, None
            elif file_type == 'pdf':
                # PDF files might have documentMetadata too
                authors, publisher, pub_date = self._extract_document_metadata(content_data)
                # TODO: Implement PDF cover extraction if needed
                return 'pdf', authors, publisher, pub_date, None
            elif file_type == 'epub':
                # Extract EPUB metadata and cover from documentMetadata block
                authors, publisher, pub_date = self._extract_document_metadata(content_data)
                cover_path = self._extract_epub_cover(uuid)
                return 'epub', authors, publisher, pub_date, cover_path
            else:
                logger.debug(f"Unknown fileType '{file_type}' for {uuid}")
                return 'unknown', None, None, None, None
                
        except Exception as e:
            logger.debug(f"Could not read content file for {uuid}: {e}")
            return 'unknown', None, None, None, None

    def _extract_document_metadata(self, content_data: Dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract authors, publisher, and publication date from documentMetadata.
        
        Returns:
            Tuple of (authors, publisher, publication_date)
        """
        document_metadata = content_data.get('documentMetadata', {})
        
        # Extract authors - handle list format
        authors = None
        if 'authors' in document_metadata:
            authors_list = document_metadata['authors']
            if isinstance(authors_list, list) and authors_list:
                # Join multiple authors with comma
                authors = ', '.join(str(author) for author in authors_list)
            elif isinstance(authors_list, str):
                authors = authors_list
        
        # Extract publisher
        publisher = document_metadata.get('publisher')
        if publisher and isinstance(publisher, str):
            publisher = publisher.strip()
        else:
            publisher = None
        
        # Extract publication date
        publication_date = document_metadata.get('publicationDate')
        if publication_date and isinstance(publication_date, str):
            # Keep ISO format but clean it up
            try:
                # Parse and reformat to clean ISO date
                from datetime import datetime
                dt = datetime.fromisoformat(publication_date.replace('Z', '+00:00'))
                publication_date = dt.strftime('%Y-%m-%d')
            except:
                # If parsing fails, keep original format
                publication_date = publication_date.strip()
        else:
            publication_date = None
        
        return authors, publisher, publication_date

    def _extract_epub_cover(self, uuid: str) -> Optional[str]:
        """
        Extract cover image from EPUB file and save it to covers directory.
        
        Returns:
            Path to extracted cover image file, or None if no cover found
        """
        epub_file = self.remarkable_dir / f"{uuid}.epub"
        
        if not epub_file.exists():
            logger.debug(f"EPUB file not found for {uuid}")
            return None
        
        try:
            # Create covers directory in data directory
            covers_dir = self.data_dir / "covers"
            covers_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(epub_file, 'r') as epub_zip:
                # Strategy 1: Look for files named "cover.*" in root
                for file_path in epub_zip.namelist():
                    filename = Path(file_path).name.lower()
                    if filename.startswith('cover.') and filename.split('.')[-1] in ['jpg', 'jpeg', 'png', 'gif']:
                        cover_filename = f"{uuid}_cover.{filename.split('.')[-1]}"
                        cover_path = covers_dir / cover_filename
                        
                        with epub_zip.open(file_path) as cover_file:
                            with open(cover_path, 'wb') as output_file:
                                shutil.copyfileobj(cover_file, output_file)
                        
                        logger.debug(f"Extracted cover image for {uuid}: {cover_filename}")
                        return str(cover_path)
                
                # Strategy 2: Parse OPF file for cover references
                cover_path = self._find_cover_from_opf(epub_zip, uuid, covers_dir)
                if cover_path:
                    return cover_path
                
                # Strategy 3: Find largest image file
                cover_path = self._find_largest_image(epub_zip, uuid, covers_dir)
                if cover_path:
                    return cover_path
                
                logger.debug(f"No cover image found for EPUB {uuid}")
                return None
                
        except Exception as e:
            logger.debug(f"Error extracting cover for {uuid}: {e}")
            return None

    def _find_cover_from_opf(self, epub_zip: zipfile.ZipFile, uuid: str, covers_dir: Path) -> Optional[str]:
        """Find cover image by parsing OPF manifest file."""
        try:
            # Find OPF file
            opf_files = [f for f in epub_zip.namelist() if f.endswith('.opf')]
            if not opf_files:
                return None
            
            opf_content = epub_zip.read(opf_files[0]).decode('utf-8')
            root = ET.fromstring(opf_content)
            
            # Define namespace
            ns = {'': 'http://www.idpf.org/2007/opf'}
            
            # Look for cover metadata
            cover_id = None
            for meta in root.findall('.//meta[@name="cover"]', ns):
                cover_id = meta.get('content')
                break
            
            if cover_id:
                # Find the item with matching id in manifest
                for item in root.findall('.//item', ns):
                    if item.get('id') == cover_id:
                        href = item.get('href')
                        if href:
                            # Resolve relative path
                            opf_dir = str(Path(opf_files[0]).parent)
                            if opf_dir == '.':
                                cover_file_path = href
                            else:
                                cover_file_path = f"{opf_dir}/{href}"
                            
                            # Extract the cover
                            if cover_file_path in epub_zip.namelist():
                                ext = Path(href).suffix.lower()
                                if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                                    cover_filename = f"{uuid}_cover{ext}"
                                    cover_path = covers_dir / cover_filename
                                    
                                    with epub_zip.open(cover_file_path) as cover_file:
                                        with open(cover_path, 'wb') as output_file:
                                            shutil.copyfileobj(cover_file, output_file)
                                    
                                    logger.debug(f"Extracted cover from OPF for {uuid}: {cover_filename}")
                                    return str(cover_path)
            
            return None
            
        except Exception as e:
            logger.debug(f"Error parsing OPF for cover: {e}")
            return None

    def _find_largest_image(self, epub_zip: zipfile.ZipFile, uuid: str, covers_dir: Path) -> Optional[str]:
        """Find the largest image file as fallback cover."""
        try:
            largest_image = None
            largest_size = 0
            
            for file_path in epub_zip.namelist():
                if Path(file_path).suffix.lower() in ['.jpg', '.jpeg', '.png', '.gif']:
                    try:
                        file_info = epub_zip.getinfo(file_path)
                        if file_info.file_size > largest_size:
                            largest_size = file_info.file_size
                            largest_image = file_path
                    except:
                        continue
            
            if largest_image and largest_size > 10000:  # At least 10KB
                ext = Path(largest_image).suffix.lower()
                cover_filename = f"{uuid}_cover{ext}"
                cover_path = covers_dir / cover_filename
                
                with epub_zip.open(largest_image) as cover_file:
                    with open(cover_path, 'wb') as output_file:
                        shutil.copyfileobj(cover_file, output_file)
                
                logger.debug(f"Extracted largest image as cover for {uuid}: {cover_filename}")
                return str(cover_path)
            
            return None
            
        except Exception as e:
            logger.debug(f"Error finding largest image: {e}")
            return None

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
                
                # Extract document type and metadata
                document_type, authors, publisher, publication_date, cover_image_path = self._get_document_metadata(uuid)
                
                item = RemarkableItem(
                    uuid=uuid,
                    visible_name=metadata.get('visibleName', 'Unknown'),
                    parent=metadata.get('parent', ''),  # Empty string means root
                    item_type=metadata.get('type', 'Unknown'),
                    document_type=document_type,
                    authors=authors,
                    publisher=publisher,
                    publication_date=publication_date,
                    cover_image_path=cover_image_path,
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
                
                metadata_info = f"Type: {document_type}"
                if authors:
                    metadata_info += f", Author: {authors}"
                if publisher:
                    metadata_info += f", Publisher: {publisher}"
                if publication_date:
                    metadata_info += f", Date: {publication_date}"
                
                logger.debug(f"Loaded: {item.visible_name} (UUID: {uuid[:8]}..., {metadata_info}, Parent: {item.parent[:8] if item.parent else 'ROOT'})")
                
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
                    authors TEXT,
                    publisher TEXT,
                    publication_date TEXT,
                    cover_image_path TEXT,
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
            
            # Add new columns to existing databases if they don't exist
            new_columns = [
                ('document_type', 'TEXT DEFAULT "unknown"'),
                ('authors', 'TEXT'),
                ('publisher', 'TEXT'), 
                ('publication_date', 'TEXT'),
                ('cover_image_path', 'TEXT')
            ]
            
            for column_name, column_def in new_columns:
                try:
                    cursor.execute(f'ALTER TABLE notebook_metadata ADD COLUMN {column_name} {column_def}')
                    logger.debug(f"Added {column_name} column to existing notebook_metadata table")
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
                     authors, publisher, publication_date, cover_image_path,
                     last_modified, last_opened, last_opened_page, deleted, pinned, synced, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    uuid,
                    item.visible_name,
                    path,
                    item.parent,
                    item.item_type,
                    item.document_type,
                    item.authors,
                    item.publisher,
                    item.publication_date,
                    item.cover_image_path,
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

def update_notebook_metadata(remarkable_dir: str, db_connection, data_dir: str = None) -> int:
    """Convenience function to update notebook metadata in database."""
    manager = NotebookPathManager(remarkable_dir, db_connection, data_dir)
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