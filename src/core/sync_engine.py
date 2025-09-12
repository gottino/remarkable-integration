"""
Event-Driven Sync Engine for reMarkable Integration

This module provides a robust, event-driven synchronization system that can push
content from the local database to multiple downstream targets (Notion, etc.)
with intelligent deduplication and error handling.

Core Principles:
1. Local DB as Source of Truth - All changes flow from local database
2. Zero Duplicates - Robust deduplication across all downstream targets  
3. Fast & Reliable - Quick sync with intelligent retry and error handling
4. Target Agnostic - Support multiple downstream apps
5. Event-Driven - React to changes immediately, not polling
"""

import logging
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import json

logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    """Status of a sync operation."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"
    SKIPPED = "skipped"


class SyncItemType(Enum):
    """Types of items that can be synced."""
    NOTEBOOK = "notebook"
    PAGE_TEXT = "page_text"
    TODO = "todo"
    HIGHLIGHT = "highlight"


@dataclass
class SyncResult:
    """Result of a sync operation."""
    status: SyncStatus
    target_id: Optional[str] = None  # External ID in target system
    error_message: Optional[str] = None
    retry_after: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def success(self) -> bool:
        return self.status == SyncStatus.SUCCESS
    
    @property
    def should_retry(self) -> bool:
        return self.status == SyncStatus.RETRY


@dataclass
class SyncItem:
    """Item to be synchronized to external targets."""
    item_type: SyncItemType
    item_id: str  # UUID or primary key in local DB
    content_hash: str  # Hash for duplicate detection
    data: Dict[str, Any]  # The actual content to sync
    source_table: str  # Which table this came from
    created_at: datetime
    updated_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'item_type': self.item_type.value,
            'item_id': self.item_id,
            'content_hash': self.content_hash,
            'data': self.data,
            'source_table': self.source_table,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class SyncTarget(ABC):
    """
    Abstract base class for sync targets.
    
    Each downstream integration (Notion, Readwise, etc.) should implement this interface
    to provide a consistent way to sync content and detect duplicates.
    """
    
    def __init__(self, target_name: str):
        self.target_name = target_name
        self.logger = logging.getLogger(f"{__name__}.{target_name}")
    
    @abstractmethod
    async def sync_item(self, item: SyncItem) -> SyncResult:
        """
        Sync a single item to this target.
        
        Args:
            item: The item to sync
            
        Returns:
            SyncResult indicating success/failure and any metadata
        """
        pass
    
    @abstractmethod
    async def check_duplicate(self, content_hash: str) -> Optional[str]:
        """
        Check if content with this hash already exists in the target.
        
        Args:
            content_hash: Hash of the content to check
            
        Returns:
            External ID if duplicate found, None otherwise
        """
        pass
    
    @abstractmethod
    async def update_item(self, external_id: str, item: SyncItem) -> SyncResult:
        """
        Update an existing item in the target system.
        
        Args:
            external_id: ID of the item in the target system
            item: Updated item data
            
        Returns:
            SyncResult indicating success/failure
        """
        pass
    
    @abstractmethod
    async def delete_item(self, external_id: str) -> SyncResult:
        """
        Delete an item from the target system.
        
        Args:
            external_id: ID of the item in the target system
            
        Returns:
            SyncResult indicating success/failure
        """
        pass
    
    @abstractmethod
    def get_target_info(self) -> Dict[str, Any]:
        """
        Get information about this target for monitoring/debugging.
        
        Returns:
            Dictionary with target information
        """
        pass
    
    def generate_content_hash(self, data: Dict[str, Any]) -> str:
        """
        Generate a deterministic hash for content deduplication.
        
        Args:
            data: Content data to hash
            
        Returns:
            SHA-256 hash string
        """
        # Create a stable representation for hashing
        content_str = json.dumps(data, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(content_str.encode('utf-8')).hexdigest()
    
    async def validate_connection(self) -> bool:
        """
        Validate that the target is accessible and properly configured.
        
        Returns:
            True if connection is valid, False otherwise
        """
        try:
            info = self.get_target_info()
            return info.get('connected', False)
        except Exception as e:
            self.logger.error(f"Connection validation failed for {self.target_name}: {e}")
            return False


class ContentFingerprint:
    """
    Service for generating consistent content fingerprints for deduplication.
    
    This ensures that identical content gets the same hash regardless of
    minor variations in metadata or formatting.
    """
    
    @staticmethod
    def for_notebook(notebook_data: Dict[str, Any]) -> str:
        """Generate fingerprint for notebook content."""
        # Use title, author, and text content for fingerprinting
        content = {
            'title': notebook_data.get('title', '').strip(),
            'author': notebook_data.get('author', '').strip(),
            'text_content': notebook_data.get('text_content', '').strip(),
            # Include page count and key metadata but not timestamps
            'page_count': notebook_data.get('page_count', 0),
            'type': 'notebook'
        }
        return ContentFingerprint._generate_hash(content)
    
    @staticmethod
    def for_page_text(page_data: Dict[str, Any]) -> str:
        """Generate fingerprint for page text content."""
        content = {
            'notebook_uuid': page_data.get('notebook_uuid', ''),
            'page_number': page_data.get('page_number', 0),
            'text': page_data.get('text', '').strip(),
            'confidence': page_data.get('confidence', 0.0),
            'type': 'page_text'
        }
        return ContentFingerprint._generate_hash(content)
    
    @staticmethod
    def for_todo(todo_data: Dict[str, Any]) -> str:
        """Generate fingerprint for todo item."""
        content = {
            'text': todo_data.get('text', '').strip(),
            'notebook_uuid': todo_data.get('notebook_uuid', ''),
            'page_number': todo_data.get('page_number', 0),
            'type': 'todo'
        }
        return ContentFingerprint._generate_hash(content)
    
    @staticmethod
    def for_highlight(highlight_data: Dict[str, Any]) -> str:
        """Generate fingerprint for highlight."""
        content = {
            'text': highlight_data.get('text', '').strip(),
            'corrected_text': highlight_data.get('corrected_text', '').strip(),
            'source_file': highlight_data.get('source_file', ''),
            'page_number': highlight_data.get('page_number', 0),
            'type': 'highlight'
        }
        return ContentFingerprint._generate_hash(content)
    
    @staticmethod
    def _generate_hash(content: Dict[str, Any]) -> str:
        """Generate SHA-256 hash of normalized content."""
        content_str = json.dumps(content, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(content_str.encode('utf-8')).hexdigest()


@dataclass
class SyncRecord:
    """Record of a sync operation for tracking and deduplication."""
    id: Optional[int] = None
    content_hash: str = ""
    target_name: str = ""
    external_id: str = ""
    item_type: SyncItemType = SyncItemType.NOTEBOOK
    status: SyncStatus = SyncStatus.PENDING
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    synced_at: Optional[datetime] = None


class DeduplicationService:
    """
    Service for tracking synced content and preventing duplicates across targets.
    
    This maintains a record of what content has been synced to which targets,
    enabling intelligent duplicate detection and update/merge decisions.
    """
    
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(f"{__name__}.DeduplicationService")
        self._ensure_sync_records_table()
    
    def _ensure_sync_records_table(self):
        """Create sync_records table if it doesn't exist."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS sync_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content_hash TEXT NOT NULL,
                        target_name TEXT NOT NULL,
                        external_id TEXT NOT NULL,
                        item_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        error_message TEXT,
                        retry_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        synced_at TIMESTAMP,
                        UNIQUE(content_hash, target_name)
                    )
                ''')
                
                # Create indexes for efficient lookups
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_hash ON sync_records(content_hash)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_target ON sync_records(target_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_sync_records_status ON sync_records(status)')
                
                conn.commit()
                self.logger.debug("Sync records table and indexes created/verified")
        except Exception as e:
            self.logger.error(f"Error creating sync records table: {e}")
            raise
    
    async def find_existing_syncs(self, content_hash: str) -> List[SyncRecord]:
        """
        Find all existing sync records for this content hash.
        
        Args:
            content_hash: Hash to search for
            
        Returns:
            List of existing sync records
        """
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, content_hash, target_name, external_id, item_type,
                           status, error_message, retry_count, created_at, updated_at, synced_at
                    FROM sync_records 
                    WHERE content_hash = ?
                    ORDER BY created_at DESC
                ''', (content_hash,))
                
                records = []
                for row in cursor.fetchall():
                    records.append(SyncRecord(
                        id=row[0],
                        content_hash=row[1],
                        target_name=row[2],
                        external_id=row[3],
                        item_type=SyncItemType(row[4]),
                        status=SyncStatus(row[5]),
                        error_message=row[6],
                        retry_count=row[7],
                        created_at=datetime.fromisoformat(row[8]) if row[8] else None,
                        updated_at=datetime.fromisoformat(row[9]) if row[9] else None,
                        synced_at=datetime.fromisoformat(row[10]) if row[10] else None
                    ))
                
                return records
        except Exception as e:
            self.logger.error(f"Error finding existing syncs for hash {content_hash}: {e}")
            return []
    
    async def register_sync(self, content_hash: str, target_name: str, 
                          external_id: str, item_type: SyncItemType, 
                          status: SyncStatus = SyncStatus.SUCCESS) -> int:
        """
        Register a successful sync operation.
        
        Args:
            content_hash: Hash of the synced content
            target_name: Name of the target system
            external_id: ID in the target system
            item_type: Type of item synced
            status: Status of the sync operation
            
        Returns:
            ID of the created sync record
        """
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                synced_at = now if status == SyncStatus.SUCCESS else None
                
                cursor.execute('''
                    INSERT OR REPLACE INTO sync_records 
                    (content_hash, target_name, external_id, item_type, status, 
                     retry_count, created_at, updated_at, synced_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                ''', (content_hash, target_name, external_id, item_type.value, 
                      status.value, now, now, synced_at))
                
                record_id = cursor.lastrowid
                conn.commit()
                
                self.logger.debug(f"Registered sync: {content_hash[:8]}... -> {target_name} ({external_id})")
                return record_id
        except Exception as e:
            self.logger.error(f"Error registering sync: {e}")
            raise
    
    async def update_sync_status(self, content_hash: str, target_name: str, 
                               status: SyncStatus, error_message: Optional[str] = None,
                               external_id: Optional[str] = None) -> bool:
        """
        Update the status of an existing sync record.
        
        Args:
            content_hash: Hash of the content
            target_name: Name of the target system
            status: New status
            error_message: Error message if failed
            external_id: External ID if successful
            
        Returns:
            True if record was updated, False otherwise
        """
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                synced_at = now if status == SyncStatus.SUCCESS else None
                
                # Build dynamic query based on provided parameters
                set_clauses = ['status = ?', 'updated_at = ?']
                params = [status.value, now]
                
                if error_message is not None:
                    set_clauses.append('error_message = ?')
                    params.append(error_message)
                
                if external_id is not None:
                    set_clauses.append('external_id = ?')
                    params.append(external_id)
                
                if synced_at:
                    set_clauses.append('synced_at = ?')
                    params.append(synced_at)
                
                # Add WHERE clause parameters
                params.extend([content_hash, target_name])
                
                query = f'''
                    UPDATE sync_records 
                    SET {', '.join(set_clauses)}
                    WHERE content_hash = ? AND target_name = ?
                '''
                
                cursor.execute(query, params)
                updated = cursor.rowcount > 0
                conn.commit()
                
                if updated:
                    self.logger.debug(f"Updated sync status: {content_hash[:8]}... -> {target_name} = {status.value}")
                else:
                    self.logger.warning(f"No sync record found to update: {content_hash[:8]}... -> {target_name}")
                
                return updated
        except Exception as e:
            self.logger.error(f"Error updating sync status: {e}")
            return False
    
    async def is_duplicate(self, content_hash: str, target_name: str) -> Optional[str]:
        """
        Check if content already exists in the target system.
        
        Args:
            content_hash: Hash of the content to check
            target_name: Name of the target system
            
        Returns:
            External ID if duplicate exists, None otherwise
        """
        existing_syncs = await self.find_existing_syncs(content_hash)
        
        for sync_record in existing_syncs:
            if (sync_record.target_name == target_name and 
                sync_record.status == SyncStatus.SUCCESS):
                return sync_record.external_id
        
        return None
    
    async def get_sync_stats(self) -> Dict[str, Any]:
        """Get statistics about sync operations."""
        try:
            with self.db_manager.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Overall stats
                cursor.execute('SELECT COUNT(*) FROM sync_records')
                total_records = cursor.fetchone()[0]
                
                # Stats by status
                cursor.execute('''
                    SELECT status, COUNT(*) 
                    FROM sync_records 
                    GROUP BY status
                ''')
                status_counts = dict(cursor.fetchall())
                
                # Stats by target
                cursor.execute('''
                    SELECT target_name, COUNT(*) 
                    FROM sync_records 
                    GROUP BY target_name
                ''')
                target_counts = dict(cursor.fetchall())
                
                # Recent activity (last 24 hours)
                cursor.execute('''
                    SELECT COUNT(*) 
                    FROM sync_records 
                    WHERE updated_at > datetime('now', '-1 day')
                ''')
                recent_activity = cursor.fetchone()[0]
                
                return {
                    'total_records': total_records,
                    'status_counts': status_counts,
                    'target_counts': target_counts,
                    'recent_activity_24h': recent_activity
                }
        except Exception as e:
            self.logger.error(f"Error getting sync stats: {e}")
            return {}


if __name__ == "__main__":
    # Example usage and testing
    from src.core.database import DatabaseManager
    
    # Initialize components
    db_manager = DatabaseManager("test_sync.db")
    dedup_service = DeduplicationService(db_manager)
    
    # Test content fingerprinting
    notebook_data = {
        'title': 'Test Notebook',
        'author': 'Test Author',
        'text_content': 'This is test content',
        'page_count': 5
    }
    
    hash1 = ContentFingerprint.for_notebook(notebook_data)
    print(f"Notebook hash: {hash1}")
    
    # Test with slightly different data (should be different hash)
    notebook_data['text_content'] = 'This is different content'
    hash2 = ContentFingerprint.for_notebook(notebook_data)
    print(f"Modified notebook hash: {hash2}")
    print(f"Hashes different: {hash1 != hash2}")