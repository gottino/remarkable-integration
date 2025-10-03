"""
Readwise Integration for reMarkable Pipeline.

This module provides comprehensive integration with the Readwise API for syncing
highlights, notes, and notebook content from reMarkable devices.

Key Features:
- Full integration with unified sync system
- Support for highlights, notebook pages, and reading notes
- Automatic deduplication via Readwise API
- Proper attribution and metadata preservation
- Rate limiting and error handling
"""

import asyncio
import json
import logging
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
import aiohttp

from ..core.sync_engine import SyncTarget, SyncItem, SyncResult, SyncStatus, SyncItemType
from ..core.book_metadata import BookMetadataManager

logger = logging.getLogger(__name__)


class ReadwiseAPIClient:
    """
    Async client for Readwise API v2.
    
    Handles authentication, rate limiting, and API interactions
    for importing highlights and reading content.
    """
    
    def __init__(self, access_token: str, rate_limit_per_minute: int = 240):
        self.access_token = access_token
        self.base_url = "https://readwise.io/api/v2"
        self.rate_limit = rate_limit_per_minute
        self.last_request_time = 0
        self.request_count = 0
        self.logger = logging.getLogger(f"{__name__}.ReadwiseAPIClient")
        
        # Request session
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession(
            headers={
                'Authorization': f'Token {self.access_token}',
                'Content-Type': 'application/json'
            },
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def _rate_limit(self):
        """Implement rate limiting."""
        current_time = time.time()
        
        # Reset counter every minute
        if current_time - self.last_request_time > 60:
            self.request_count = 0
            self.last_request_time = current_time
        
        # Wait if we're approaching rate limit
        if self.request_count >= self.rate_limit - 5:  # Leave some buffer
            sleep_time = 60 - (current_time - self.last_request_time)
            if sleep_time > 0:
                self.logger.info(f"Rate limiting: waiting {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
                self.request_count = 0
                self.last_request_time = time.time()
        
        self.request_count += 1
    
    async def import_highlights(self, highlights: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Import highlights to Readwise.
        
        Args:
            highlights: List of highlight dictionaries
            
        Returns:
            API response with import results
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        await self._rate_limit()
        
        payload = {"highlights": highlights}
        
        try:
            async with self.session.post(f"{self.base_url}/highlights/", json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    self.logger.info(f"Successfully imported {len(highlights)} highlights")
                    return result
                elif response.status == 400:
                    error_data = await response.json()
                    self.logger.error(f"Import validation error: {error_data}")
                    raise ValueError(f"Invalid highlight data: {error_data}")
                elif response.status == 429:
                    self.logger.warning("Rate limited by Readwise API")
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=429,
                        message="Rate limited"
                    )
                else:
                    error_text = await response.text()
                    self.logger.error(f"Readwise API error {response.status}: {error_text}")
                    response.raise_for_status()
                    
        except aiohttp.ClientError as e:
            self.logger.error(f"Network error importing highlights: {e}")
            raise
    
    async def get_books(self, page_size: int = 1000) -> List[Dict[str, Any]]:
        """
        Get list of books/documents in Readwise.
        
        Args:
            page_size: Number of books per page
            
        Returns:
            List of book dictionaries with id, title, author, etc.
        """
        if not self.session:
            raise RuntimeError("Client not initialized. Use async context manager.")
        
        await self._rate_limit()
        
        try:
            params = {"page_size": page_size}
            async with self.session.get(f"{self.base_url}/books/", params=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data.get('results', [])
                
        except aiohttp.ClientError as e:
            self.logger.error(f"Error fetching books: {e}")
            raise
    
    async def find_book_by_title_author(self, title: str, author: str) -> Optional[Dict[str, Any]]:
        """
        Find a book in Readwise by title and author.
        
        Args:
            title: Book title to search for
            author: Book author to search for
            
        Returns:
            Book dictionary if found, None otherwise
        """
        books = await self.get_books()
        
        # Normalize strings for comparison (case-insensitive, strip whitespace)
        title_norm = title.strip().lower() if title else ""
        author_norm = author.strip().lower() if author else ""
        
        for book in books:
            book_title = (book.get('title', '') or '').strip().lower()
            book_author = (book.get('author', '') or '').strip().lower()
            
            if book_title == title_norm and book_author == author_norm:
                self.logger.debug(f"Found existing book: {book.get('title')} by {book.get('author')} (ID: {book.get('id')})")
                return book
        
        self.logger.debug(f"No existing book found for: {title} by {author}")
        return None
    
    async def test_connection(self) -> bool:
        """
        Test if the API connection and token are working.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            if not self.session:
                async with ReadwiseAPIClient(self.access_token) as client:
                    return await client.test_connection()
            
            await self._rate_limit()
            async with self.session.get(f"{self.base_url}/auth/") as response:
                if response.status == 204:  # Readwise returns 204 for successful auth
                    self.logger.info("Readwise API connection successful")
                    return True
                else:
                    self.logger.error(f"Readwise API auth failed: {response.status}")
                    if response.status == 401:
                        self.logger.error("Invalid or missing API token")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error testing Readwise connection: {e}")
            return False


class ReadwiseSyncTarget(SyncTarget):
    """
    Readwise implementation of the unified sync target interface.
    
    Syncs highlights, notebook pages, and reading notes to Readwise
    with proper attribution and metadata preservation.
    """
    
    def __init__(self, access_token: str, db_connection: Optional[sqlite3.Connection] = None,
                 author_name: str = "reMarkable", default_category: str = "books"):
        super().__init__("readwise")
        self.access_token = access_token
        self.author_name = author_name
        self.default_category = default_category
        self.client = ReadwiseAPIClient(access_token)
        
        # Book metadata manager for rich metadata
        self.book_metadata_manager = BookMetadataManager(db_connection) if db_connection else None
        self.db_connection = db_connection
    
    async def sync_item(self, item: SyncItem) -> SyncResult:
        """Sync a single item to Readwise."""
        try:
            if item.item_type == SyncItemType.HIGHLIGHT:
                return await self._sync_highlight(item)
            elif item.item_type == SyncItemType.NOTEBOOK:
                return await self._sync_notebook(item)
            elif item.item_type == SyncItemType.PAGE_TEXT:
                return await self._sync_page_text(item)
            elif item.item_type == SyncItemType.TODO:
                return await self._sync_todo(item)
            else:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': f'Unsupported item type for Readwise: {item.item_type}'}
                )
        except Exception as e:
            self.logger.error(f"Error syncing {item.item_type} to Readwise: {e}")
            return SyncResult(
                status=SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_highlight(self, item: SyncItem) -> SyncResult:
        """Sync a highlight to Readwise."""
        try:
            highlight_data = item.data
            
            # Get book metadata if available
            title = highlight_data.get('title', 'Untitled Document')
            author = self.author_name
            category = self.default_category
            note_parts = []
            
            # Try to get rich book metadata from notebook UUID
            notebook_uuid = highlight_data.get('notebook_uuid')
            if notebook_uuid and self.book_metadata_manager:
                book_metadata = self.book_metadata_manager.get_book_metadata(notebook_uuid)
                if book_metadata:
                    # Use actual book title and author
                    title = book_metadata.title
                    if book_metadata.authors:
                        author = book_metadata.authors
                    
                    # Set category based on document type
                    if book_metadata.document_type == 'epub':
                        category = 'books'
                    elif book_metadata.document_type == 'pdf':
                        category = 'articles'  # PDFs are often articles/papers
                    
                    # Add publication info to note if available
                    if book_metadata.publisher:
                        note_parts.append(f"Publisher: {book_metadata.publisher}")
                    if book_metadata.publication_date:
                        note_parts.append(f"Published: {book_metadata.publication_date}")
            
            # Add original text note if this is a corrected highlight
            if highlight_data.get('corrected_text'):
                original_text = highlight_data.get('text', '')
                note_parts.append(f"Original OCR: {original_text}")
            
            # Format highlight for Readwise
            readwise_highlight = {
                "text": highlight_data.get('corrected_text', highlight_data.get('text', '')),
                "title": title,
                "author": author,
                "category": category,
                "source_type": "remarkable",
                "location": highlight_data.get('page_number'),
                "location_type": "page",
                "note": " | ".join(note_parts) if note_parts else None,
                "highlighted_at": datetime.now().isoformat(),
                "highlight_url": f"remarkable://highlight/{item.item_id}",  # Custom URL scheme
            }
            
            # Add cover image if available and publicly accessible
            if notebook_uuid and self.book_metadata_manager:
                book_metadata = self.book_metadata_manager.get_book_metadata(notebook_uuid)
                if book_metadata and book_metadata.cover_image_path:
                    # For now, we only add cover images if they're already web URLs
                    # Future enhancement: upload local images to cloud storage
                    if book_metadata.cover_image_path.startswith(('http://', 'https://')):
                        readwise_highlight["image_url"] = book_metadata.cover_image_path
                        self.logger.debug(f"Added cover image URL for book: {title}")
                    else:
                        self.logger.debug(f"Skipping local cover image (not web URL): {book_metadata.cover_image_path}")
            
            # Add confidence score if available
            if 'confidence' in highlight_data:
                confidence_note = f"OCR confidence: {highlight_data['confidence']:.1%}"
                if readwise_highlight["note"]:
                    readwise_highlight["note"] += f" | {confidence_note}"
                else:
                    readwise_highlight["note"] = confidence_note
            
            # Remove None values
            readwise_highlight = {k: v for k, v in readwise_highlight.items() if v is not None}
            
            # Check if we need to track the book ID for this highlight
            notebook_uuid = highlight_data.get('notebook_uuid')
            if notebook_uuid and title != 'Untitled Document' and author != self.author_name:
                # Try to get existing book ID first to ensure consistency
                existing_book_id = await self.get_or_find_readwise_book_id(notebook_uuid, title, author)
                if existing_book_id:
                    self.logger.debug(f"Using existing Readwise book ID {existing_book_id} for highlight")
                    
            async with self.client as client:
                result = await client.import_highlights([readwise_highlight])
                
                # Extract book ID from response if this is a new book
                if notebook_uuid and result and 'highlights' in result:
                    for highlight_result in result['highlights']:
                        if 'book_id' in highlight_result:
                            book_id = highlight_result['book_id']
                            # Store the mapping if we don't have it yet
                            if not self.get_readwise_book_id(notebook_uuid):
                                self.store_readwise_book_mapping(notebook_uuid, book_id)
                            break
                
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id=str(result.get('id', f'readwise_highlight_{item.item_id}')),
                    metadata={
                        'readwise_response': result,
                        'highlight_count': 1,
                        'source_file': highlight_data.get('source_file', ''),
                        'book_title': title,
                        'book_author': author,
                        'book_category': category
                    }
                )
                
        except Exception as e:
            return SyncResult(
                status=SyncStatus.RETRY if "rate" in str(e).lower() else SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_notebook(self, item: SyncItem) -> SyncResult:
        """Sync a complete notebook to Readwise as a book with page highlights."""
        try:
            notebook_data = item.data
            notebook_name = notebook_data.get('title', 'Untitled Notebook')
            pages = notebook_data.get('pages', [])
            
            if not pages:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'No pages to sync'}
                )
            
            # Get book metadata if available
            title = notebook_name
            author = self.author_name
            category = self.default_category
            
            # Try to get rich book metadata from notebook UUID
            notebook_uuid = notebook_data.get('notebook_uuid', item.item_id)
            if notebook_uuid and self.book_metadata_manager:
                book_metadata = self.book_metadata_manager.get_book_metadata(notebook_uuid)
                if book_metadata:
                    title = book_metadata.title
                    if book_metadata.authors:
                        author = book_metadata.authors
                    
                    # Set category based on document type
                    if book_metadata.document_type == 'epub':
                        category = 'books'
                    elif book_metadata.document_type == 'pdf':
                        category = 'articles'
            
            # Create highlights for each page with significant content
            highlights = []
            
            for page in pages:
                page_text = page.get('text', '').strip()
                page_number = page.get('page_number', 0)
                confidence = page.get('confidence', 0.0)
                
                # Only sync pages with meaningful content
                if len(page_text) < 10:  # Skip very short content
                    continue
                
                # Truncate very long pages for readability
                if len(page_text) > 2000:
                    page_text = page_text[:1950] + "..."
                
                highlight = {
                    "text": page_text,
                    "title": title,
                    "author": author,
                    "category": category,
                    "source_type": "remarkable",
                    "location": page_number,
                    "location_type": "page",
                    "highlighted_at": datetime.now().isoformat(),
                    "highlight_url": f"remarkable://notebook/{item.item_id}/page/{page_number}",
                }
                
                # Add confidence note if low
                if confidence < 0.7:
                    highlight["note"] = f"OCR confidence: {confidence:.1%} - may contain errors"
                
                highlights.append(highlight)
            
            if not highlights:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'No pages with sufficient content'}
                )
            
            # Import to Readwise in batches (max 100 per request recommended)
            batch_size = 50
            all_results = []
            
            async with self.client as client:
                for i in range(0, len(highlights), batch_size):
                    batch = highlights[i:i + batch_size]
                    result = await client.import_highlights(batch)
                    all_results.append(result)
                    
                    # Small delay between batches
                    if i + batch_size < len(highlights):
                        await asyncio.sleep(1)
            
            return SyncResult(
                status=SyncStatus.SUCCESS,
                target_id=f'readwise_notebook_{item.item_id}',
                metadata={
                    'readwise_responses': all_results,
                    'highlight_count': len(highlights),
                    'total_pages': len(pages),
                    'synced_pages': len(highlights),
                    'notebook_name': notebook_name
                }
            )
            
        except Exception as e:
            return SyncResult(
                status=SyncStatus.RETRY if "rate" in str(e).lower() else SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_page_text(self, item: SyncItem) -> SyncResult:
        """Sync individual page text to Readwise."""
        try:
            page_data = item.data
            notebook_uuid = page_data.get('notebook_uuid')
            page_number = page_data.get('page_number', 0)
            page_text = page_data.get('text', '').strip()
            
            if len(page_text) < 10:  # Skip very short content
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'Page text too short to be meaningful'}
                )
            
            # Get notebook name for title
            notebook_name = page_data.get('notebook_name', 'Unknown Notebook')
            
            highlight = {
                "text": page_text[:2000] + ("..." if len(page_text) > 2000 else ""),
                "title": notebook_name,
                "author": self.author_name,
                "category": self.default_category,
                "source_type": "remarkable",
                "location": page_number,
                "location_type": "page",
                "highlighted_at": datetime.now().isoformat(),
                "highlight_url": f"remarkable://notebook/{notebook_uuid}/page/{page_number}",
            }
            
            # Add confidence note if available and low
            confidence = page_data.get('confidence', 1.0)
            if confidence < 0.7:
                highlight["note"] = f"OCR confidence: {confidence:.1%} - may contain errors"
            
            async with self.client as client:
                result = await client.import_highlights([highlight])
                
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id=str(result.get('id', f'readwise_page_{item.item_id}')),
                    metadata={
                        'readwise_response': result,
                        'notebook_uuid': notebook_uuid,
                        'page_number': page_number
                    }
                )
                
        except Exception as e:
            return SyncResult(
                status=SyncStatus.RETRY if "rate" in str(e).lower() else SyncStatus.FAILED,
                error_message=str(e)
            )
    
    async def _sync_todo(self, item: SyncItem) -> SyncResult:
        """Sync a todo item to Readwise as a highlight with todo context."""
        try:
            todo_data = item.data
            todo_text = todo_data.get('text', '').strip()
            
            if not todo_text:
                return SyncResult(
                    status=SyncStatus.SKIPPED,
                    metadata={'reason': 'Empty todo text'}
                )
            
            # Get context information
            notebook_uuid = todo_data.get('notebook_uuid', '')
            page_number = todo_data.get('page_number', 0)
            
            highlight = {
                "text": todo_text,
                "title": "reMarkable Tasks",
                "author": self.author_name,
                "category": "articles",  # Use articles for todos/tasks
                "source_type": "remarkable",
                "location": page_number if page_number else None,
                "location_type": "page" if page_number else None,
                "highlighted_at": datetime.now().isoformat(),
                "highlight_url": f"remarkable://todo/{item.item_id}",
                "note": f"📝 Task from notebook {notebook_uuid[:8]}..." if notebook_uuid else "📝 reMarkable Task"
            }
            
            # Remove None values
            highlight = {k: v for k, v in highlight.items() if v is not None}
            
            async with self.client as client:
                result = await client.import_highlights([highlight])
                
                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    target_id=str(result.get('id', f'readwise_todo_{item.item_id}')),
                    metadata={
                        'readwise_response': result,
                        'todo_text': todo_text
                    }
                )
                
        except Exception as e:
            return SyncResult(
                status=SyncStatus.RETRY if "rate" in str(e).lower() else SyncStatus.FAILED,
                error_message=str(e)
            )
    
    def get_readwise_book_id(self, notebook_uuid: str) -> Optional[int]:
        """Get Readwise book ID for a notebook UUID from local mapping."""
        if not self.db_connection:
            return None
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute(
                'SELECT readwise_book_id FROM readwise_book_mapping WHERE notebook_uuid = ?',
                (notebook_uuid,)
            )
            result = cursor.fetchone()
            
            if result:
                self.logger.debug(f"Found cached Readwise book ID {result[0]} for notebook {notebook_uuid}")
                return result[0]
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting Readwise book ID: {e}")
            return None
    
    def store_readwise_book_mapping(self, notebook_uuid: str, readwise_book_id: int):
        """Store mapping between notebook UUID and Readwise book ID."""
        if not self.db_connection:
            return
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO readwise_book_mapping 
                (notebook_uuid, readwise_book_id)
                VALUES (?, ?)
            ''', (notebook_uuid, readwise_book_id))
            
            self.db_connection.commit()
            self.logger.info(f"Stored book mapping: notebook {notebook_uuid} -> Readwise ID {readwise_book_id}")
            
        except Exception as e:
            self.logger.error(f"Error storing Readwise book mapping: {e}")
    
    async def get_or_find_readwise_book_id(self, notebook_uuid: str, title: str, author: str) -> Optional[int]:
        """Get Readwise book ID, checking both local mapping and Readwise API."""
        # First check local mapping
        book_id = self.get_readwise_book_id(notebook_uuid)
        if book_id:
            return book_id
        
        # If not found locally, check Readwise API
        try:
            async with self.client as client:
                book = await client.find_book_by_title_author(title, author)
                if book:
                    book_id = book.get('id')
                    if book_id:
                        # Store the mapping for future use
                        self.store_readwise_book_mapping(notebook_uuid, book_id)
                        return book_id
        
        except Exception as e:
            self.logger.error(f"Error checking Readwise for existing book: {e}")
        
        return None
    
    async def check_duplicate(self, content_hash: str) -> Optional[str]:
        """
        Check if content already exists in Readwise.
        
        Readwise handles deduplication automatically based on title/author/text/source_url,
        so we don't need to implement manual duplicate checking.
        """
        return None  # Let Readwise handle deduplication
    
    async def update_item(self, external_id: str, item: SyncItem) -> SyncResult:
        """
        Update an existing item in Readwise.
        
        Readwise doesn't support updates via API, so we'll re-import
        which will be deduplicated automatically.
        """
        # Re-import the item (Readwise will deduplicate)
        return await self.sync_item(item)
    
    async def delete_item(self, external_id: str) -> SyncResult:
        """
        Delete an item from Readwise.
        
        Readwise doesn't support deletion via API.
        """
        return SyncResult(
            status=SyncStatus.SKIPPED,
            metadata={'reason': 'Readwise API does not support deletion'}
        )
    
    def get_target_info(self) -> Dict[str, Any]:
        """Get information about this Readwise target."""
        return {
            'target_name': self.target_name,
            'connected': bool(self.access_token),
            'author_name': self.author_name,
            'default_category': self.default_category,
            'api_base_url': self.client.base_url,
            'capabilities': {
                'notebooks': True,
                'todos': True,
                'highlights': True,
                'page_text': True,
                'updates': False,  # Re-import instead
                'deletions': False  # Not supported by API
            }
        }
    
    async def validate_connection(self) -> bool:
        """Validate that the Readwise connection is working."""
        try:
            async with self.client as client:
                return await client.test_connection()
        except Exception as e:
            self.logger.error(f"Connection validation failed: {e}")
            return False


if __name__ == "__main__":
    # Example usage and testing
    import asyncio
    import os
    
    async def test_readwise_sync():
        # This would require a real Readwise token
        token = os.getenv('READWISE_TOKEN')
        if not token:
            print("Set READWISE_TOKEN environment variable to test")
            return
        
        # Test connection
        target = ReadwiseSyncTarget(token)
        
        if await target.validate_connection():
            print("✅ Readwise connection successful")
            
            # Test target info
            info = target.get_target_info()
            print(f"Target info: {info}")
        else:
            print("❌ Readwise connection failed")
    
    # Uncomment to test with real token
    # asyncio.run(test_readwise_sync())