"""
Book and Article Metadata Integration.

This module provides functions to associate enhanced highlights with their source
book/article metadata including title, author, publisher, publication date, and cover image.
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class BookMetadata:
    """Represents metadata for a book or article."""
    notebook_uuid: str
    title: str
    full_path: str
    document_type: str  # 'epub', 'pdf', 'notebook'
    authors: Optional[str] = None
    publisher: Optional[str] = None
    publication_date: Optional[str] = None
    cover_image_path: Optional[str] = None
    last_modified: Optional[str] = None
    last_opened: Optional[str] = None

@dataclass
class EnhancedHighlightWithMetadata:
    """Enhanced highlight with associated book/article metadata."""
    # Highlight data
    highlight_id: int
    source_file: str
    title: str
    original_text: str
    corrected_text: str
    page_number: Optional[str]
    confidence: Optional[float]
    match_score: Optional[float]
    created_at: str
    notebook_uuid: Optional[str]
    page_uuid: Optional[str]
    
    # Book/Article metadata
    book_metadata: Optional[BookMetadata] = None

class BookMetadataManager:
    """Manages book and article metadata associations with highlights."""
    
    def __init__(self, db_connection: sqlite3.Connection):
        """Initialize with database connection."""
        self.db_connection = db_connection
    
    def get_book_metadata(self, notebook_uuid: str) -> Optional[BookMetadata]:
        """Get book/article metadata for a specific notebook UUID."""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute("""
                SELECT notebook_uuid, visible_name, full_path, document_type,
                       authors, publisher, publication_date, cover_image_path,
                       last_modified, last_opened
                FROM notebook_metadata 
                WHERE notebook_uuid = ?
            """, (notebook_uuid,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return BookMetadata(
                notebook_uuid=row[0],
                title=row[1],
                full_path=row[2],
                document_type=row[3],
                authors=row[4],
                publisher=row[5],
                publication_date=row[6],
                cover_image_path=row[7],
                last_modified=row[8],
                last_opened=row[9]
            )
            
        except Exception as e:
            logger.error(f"Error getting book metadata for {notebook_uuid}: {e}")
            return None
    
    def get_enhanced_highlights_with_metadata(
        self, 
        limit: Optional[int] = None,
        document_types: Optional[List[str]] = None
    ) -> List[EnhancedHighlightWithMetadata]:
        """
        Get enhanced highlights with their associated book/article metadata.
        
        Args:
            limit: Maximum number of highlights to return
            document_types: Filter by document types (e.g., ['epub', 'pdf'])
            
        Returns:
            List of enhanced highlights with metadata
        """
        try:
            cursor = self.db_connection.cursor()
            
            # Build query with optional filters
            query = """
                SELECT 
                    eh.id, eh.source_file, eh.title, eh.original_text, eh.corrected_text,
                    eh.page_number, eh.confidence, eh.match_score, eh.created_at,
                    eh.notebook_uuid, eh.page_uuid,
                    nm.visible_name, nm.full_path, nm.document_type,
                    nm.authors, nm.publisher, nm.publication_date, nm.cover_image_path,
                    nm.last_modified, nm.last_opened
                FROM enhanced_highlights eh
                LEFT JOIN notebook_metadata nm ON eh.notebook_uuid = nm.notebook_uuid
                WHERE eh.notebook_uuid IS NOT NULL
            """
            
            params = []
            
            if document_types:
                placeholders = ','.join('?' for _ in document_types)
                query += f" AND nm.document_type IN ({placeholders})"
                params.extend(document_types)
            
            query += " ORDER BY eh.created_at DESC"
            
            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            highlights = []
            for row in rows:
                # Create book metadata if we have notebook metadata
                book_metadata = None
                if row[11]:  # nm.visible_name exists
                    book_metadata = BookMetadata(
                        notebook_uuid=row[9],  # eh.notebook_uuid
                        title=row[11],         # nm.visible_name
                        full_path=row[12],     # nm.full_path
                        document_type=row[13], # nm.document_type
                        authors=row[14],       # nm.authors
                        publisher=row[15],     # nm.publisher
                        publication_date=row[16], # nm.publication_date
                        cover_image_path=row[17], # nm.cover_image_path
                        last_modified=row[18], # nm.last_modified
                        last_opened=row[19]    # nm.last_opened
                    )
                
                highlight = EnhancedHighlightWithMetadata(
                    highlight_id=row[0],
                    source_file=row[1],
                    title=row[2],
                    original_text=row[3],
                    corrected_text=row[4],
                    page_number=row[5],
                    confidence=row[6],
                    match_score=row[7],
                    created_at=row[8],
                    notebook_uuid=row[9],
                    page_uuid=row[10],
                    book_metadata=book_metadata
                )
                
                highlights.append(highlight)
            
            logger.info(f"Retrieved {len(highlights)} enhanced highlights with metadata")
            return highlights
            
        except Exception as e:
            logger.error(f"Error getting enhanced highlights with metadata: {e}")
            return []
    
    def get_highlights_by_book(self, notebook_uuid: str) -> List[EnhancedHighlightWithMetadata]:
        """Get all enhanced highlights for a specific book/article."""
        return self.get_enhanced_highlights_with_metadata(
            limit=None,
            document_types=None
        )
    
    def get_books_with_highlights(self) -> List[Dict[str, Any]]:
        """Get all books/articles that have highlights, with highlight counts."""
        try:
            cursor = self.db_connection.cursor()
            cursor.execute("""
                SELECT 
                    nm.notebook_uuid,
                    nm.visible_name,
                    nm.full_path,
                    nm.document_type,
                    nm.authors,
                    nm.publisher,
                    nm.publication_date,
                    nm.cover_image_path,
                    COUNT(eh.id) as highlight_count
                FROM notebook_metadata nm
                INNER JOIN enhanced_highlights eh ON nm.notebook_uuid = eh.notebook_uuid
                WHERE nm.document_type IN ('epub', 'pdf')
                GROUP BY nm.notebook_uuid
                ORDER BY highlight_count DESC, nm.visible_name
            """)
            
            books = []
            for row in cursor.fetchall():
                books.append({
                    'notebook_uuid': row[0],
                    'title': row[1],
                    'full_path': row[2],
                    'document_type': row[3],
                    'authors': row[4],
                    'publisher': row[5],
                    'publication_date': row[6],
                    'cover_image_path': row[7],
                    'highlight_count': row[8]
                })
            
            logger.info(f"Found {len(books)} books/articles with highlights")
            return books
            
        except Exception as e:
            logger.error(f"Error getting books with highlights: {e}")
            return []
    
    def get_reading_stats(self) -> Dict[str, Any]:
        """Get reading statistics from the enhanced highlights and metadata."""
        try:
            cursor = self.db_connection.cursor()
            
            # Get basic stats
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT eh.notebook_uuid) as books_with_highlights,
                    COUNT(eh.id) as total_highlights,
                    COUNT(DISTINCT CASE WHEN nm.document_type = 'epub' THEN eh.notebook_uuid END) as epub_books,
                    COUNT(DISTINCT CASE WHEN nm.document_type = 'pdf' THEN eh.notebook_uuid END) as pdf_books
                FROM enhanced_highlights eh
                LEFT JOIN notebook_metadata nm ON eh.notebook_uuid = nm.notebook_uuid
                WHERE eh.notebook_uuid IS NOT NULL
            """)
            
            stats_row = cursor.fetchone()
            
            # Get authors with most highlights
            cursor.execute("""
                SELECT 
                    nm.authors,
                    COUNT(eh.id) as highlight_count
                FROM enhanced_highlights eh
                JOIN notebook_metadata nm ON eh.notebook_uuid = nm.notebook_uuid
                WHERE nm.authors IS NOT NULL
                GROUP BY nm.authors
                ORDER BY highlight_count DESC
                LIMIT 5
            """)
            
            top_authors = [{'author': row[0], 'highlights': row[1]} for row in cursor.fetchall()]
            
            # Get recent reading activity
            cursor.execute("""
                SELECT 
                    nm.visible_name,
                    nm.authors,
                    COUNT(eh.id) as highlights,
                    MAX(eh.created_at) as last_highlight
                FROM enhanced_highlights eh
                JOIN notebook_metadata nm ON eh.notebook_uuid = nm.notebook_uuid
                WHERE eh.created_at > datetime('now', '-30 days')
                GROUP BY eh.notebook_uuid
                ORDER BY last_highlight DESC
                LIMIT 5
            """)
            
            recent_books = []
            for row in cursor.fetchall():
                recent_books.append({
                    'title': row[0],
                    'author': row[1],
                    'highlights': row[2],
                    'last_highlight': row[3]
                })
            
            return {
                'books_with_highlights': stats_row[0] if stats_row else 0,
                'total_highlights': stats_row[1] if stats_row else 0,
                'epub_books': stats_row[2] if stats_row else 0,
                'pdf_books': stats_row[3] if stats_row else 0,
                'top_authors': top_authors,
                'recent_reading': recent_books
            }
            
        except Exception as e:
            logger.error(f"Error getting reading stats: {e}")
            return {}

def get_book_metadata_manager(db_connection: sqlite3.Connection) -> BookMetadataManager:
    """Convenience function to create a BookMetadataManager instance."""
    return BookMetadataManager(db_connection)

# Convenience functions for common operations
def get_enhanced_highlights_with_book_info(
    db_connection: sqlite3.Connection,
    limit: Optional[int] = 50,
    epub_only: bool = False
) -> List[EnhancedHighlightWithMetadata]:
    """Get enhanced highlights with book metadata - convenience function."""
    manager = BookMetadataManager(db_connection)
    document_types = ['epub'] if epub_only else ['epub', 'pdf']
    return manager.get_enhanced_highlights_with_metadata(
        limit=limit,
        document_types=document_types
    )

def get_reading_library_overview(db_connection: sqlite3.Connection) -> Dict[str, Any]:
    """Get a complete overview of the reading library - convenience function."""
    manager = BookMetadataManager(db_connection)
    
    return {
        'stats': manager.get_reading_stats(),
        'books_with_highlights': manager.get_books_with_highlights()
    }