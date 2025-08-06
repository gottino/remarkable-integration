"""
Highlight Extractor Module for reMarkable Pipeline

This module extracts highlighted text from reMarkable .rm files associated with 
PDF and EPUB documents. It processes the binary .rm files to find ASCII text 
sequences that represent user highlights, cleans and filters the extracted content,
and maps highlights to their corresponding page numbers.

Key Features:
- Extracts highlights from .rm files for PDF/EPUB documents
- Maps highlights to page numbers using .content file metadata
- Filters out unwanted content and applies text quality heuristics
- Integrates with the pipeline's database and event system
"""

import os
import json
import re
import logging
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

from .base_processor import BaseProcessor, ProcessingResult
from ..core.database import DatabaseManager
from ..core.events import EventType
from ..utils.file_utils import read_json_file
from ..utils.validation import validate_file_exists


# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class Highlight:
    """Represents an extracted highlight with metadata."""
    text: str
    page_number: str
    file_name: str
    title: str
    confidence: float = 1.0
    
    def to_dict(self) -> Dict:
        """Convert highlight to dictionary for storage."""
        return {
            'text': self.text,
            'page_number': self.page_number,
            'file_name': self.file_name,
            'title': self.title,
            'confidence': self.confidence
        }


@dataclass
class DocumentInfo:
    """Document metadata extracted from .content and .metadata files."""
    content_id: str
    title: str
    file_type: str
    page_mappings: Dict[str, str]
    content_file_path: str
    
    def __post_init__(self):
        """Validate document info after initialization."""
        if self.file_type not in ['pdf', 'epub']:
            raise ValueError(f"Unsupported file type: {self.file_type}")


class HighlightExtractor(BaseProcessor):
    """
    Processes reMarkable .rm files to extract highlighted text from PDF/EPUB documents.
    
    This processor:
    1. Identifies valid .content files (PDF/EPUB only)
    2. Maps .rm files to their corresponding documents
    3. Extracts ASCII text sequences from binary .rm files
    4. Cleans and filters extracted text using quality heuristics
    5. Maps highlights to page numbers using document metadata
    6. Stores results in the database and triggers events
    """
    
    def __init__(self, db_manager: DatabaseManager):
        super().__init__(db_manager)
        self.processor_type = "highlight_extractor"
        
        # Configuration
        self.min_text_length = 10
        self.text_threshold = 0.6
        self.min_words = 3
        self.symbol_ratio_threshold = 0.2
        
        # Cache for processed documents
        self._document_cache: Dict[str, DocumentInfo] = {}
        
        # Unwanted content patterns
        self.unwanted_patterns = {
            "reMarkable .lines file, version=6",
            "reMarkable .lines file, version=3"
        }
        
        logger.info("HighlightExtractor initialized")
    
    def can_process(self, file_path: str) -> bool:
        """
        Check if this processor can handle the given file.
        
        Args:
            file_path: Path to the file to check
            
        Returns:
            True if file is a .content file with PDF/EPUB type, False otherwise
        """
        if not file_path.endswith('.content'):
            return False
            
        try:
            content_data = read_json_file(file_path)
            file_type = content_data.get('fileType', '')
            return file_type in ['pdf', 'epub']
        except Exception as e:
            logger.warning(f"Could not read content file {file_path}: {e}")
            return False
    
    def process_file(self, file_path: str) -> ProcessingResult:
        """
        Process a .content file and extract highlights from associated .rm files.
        
        Args:
            file_path: Path to the .content file
            
        Returns:
            ProcessingResult with extracted highlights and processing metadata
        """
        try:
            logger.info(f"Processing content file: {file_path}")
            
            # Load document information
            doc_info = self._load_document_info(file_path)
            
            # Find associated .rm files
            rm_files = self._find_rm_files(doc_info)
            
            if not rm_files:
                logger.info(f"No .rm files found for {file_path}")
                return ProcessingResult(
                    success=True,
                    file_path=file_path,
                    processor_type=self.processor_type,
                    data={'highlights': [], 'message': 'No .rm files found'}
                )
            
            # Extract highlights from all .rm files
            highlights = []
            for rm_file in rm_files:
                file_highlights = self._extract_highlights_from_rm(rm_file, doc_info)
                highlights.extend(file_highlights)
            
            if highlights:
                # Store in database
                self._store_highlights(highlights, file_path)
                
                # Trigger event
                self._trigger_event(EventType.HIGHLIGHTS_EXTRACTED, {
                    'file_path': file_path,
                    'highlight_count': len(highlights),
                    'title': doc_info.title
                })
            
            logger.info(f"Extracted {len(highlights)} highlights from {len(rm_files)} .rm files")
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                processor_type=self.processor_type,
                data={
                    'highlights': [h.to_dict() for h in highlights],
                    'rm_file_count': len(rm_files),
                    'title': doc_info.title
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                error_message=str(e)
            )
    
    def _load_document_info(self, content_file_path: str) -> DocumentInfo:
        """Load document information from .content and .metadata files."""
        content_file_path = Path(content_file_path)
        
        # Check cache first
        cache_key = str(content_file_path)
        if cache_key in self._document_cache:
            return self._document_cache[cache_key]
        
        # Load .content file
        content_data = read_json_file(str(content_file_path))
        file_type = content_data.get('fileType', '')
        
        if file_type not in ['pdf', 'epub']:
            raise ValueError(f"Unsupported file type: {file_type}")
        
        # Get document ID from filename
        content_id = content_file_path.stem
        
        # Load .metadata file for title
        metadata_file = content_file_path.parent / f"{content_id}.metadata"
        title = "Unknown Title"
        
        if metadata_file.exists():
            try:
                metadata = read_json_file(str(metadata_file))
                title = metadata.get('visibleName', title)
            except Exception as e:
                logger.warning(f"Could not read metadata file {metadata_file}: {e}")
        
        # Extract page mappings
        page_mappings = self._extract_page_mappings(content_data)
        
        doc_info = DocumentInfo(
            content_id=content_id,
            title=title,
            file_type=file_type,
            page_mappings=page_mappings,
            content_file_path=str(content_file_path)
        )
        
        # Cache the result
        self._document_cache[cache_key] = doc_info
        
        return doc_info
    
    def _extract_page_mappings(self, content_data: Dict) -> Dict[str, str]:
        """Extract page ID to page number mappings from content data."""
        page_mappings = {}
        
        pages_data = content_data.get('cPages', {}).get('pages', [])
        
        for page in pages_data:
            if 'id' in page and 'redir' in page and 'value' in page['redir']:
                page_id = page['id']
                page_number = str(page['redir']['value'])
                page_mappings[page_id] = page_number
        
        logger.debug(f"Extracted {len(page_mappings)} page mappings")
        return page_mappings
    
    def _find_rm_files(self, doc_info: DocumentInfo) -> List[str]:
        """Find .rm files associated with the document."""
        content_path = Path(doc_info.content_file_path)
        subdirectory = content_path.parent / doc_info.content_id
        
        if not subdirectory.exists():
            logger.debug(f"Subdirectory does not exist: {subdirectory}")
            return []
        
        rm_files = []
        
        for file_path in subdirectory.iterdir():
            if not file_path.suffix == '.rm':
                continue
            
            # Skip .rm files that have corresponding metadata JSON files
            # (these are typically notebook files, not highlights)
            json_file = subdirectory / f"{file_path.stem}-metadata.json"
            if json_file.exists():
                logger.debug(f"Skipping {file_path.name}: has metadata JSON file")
                continue
            
            rm_files.append(str(file_path))
        
        logger.debug(f"Found {len(rm_files)} .rm files for document {doc_info.title}")
        return rm_files
    
    def _extract_highlights_from_rm(self, rm_file_path: str, doc_info: DocumentInfo) -> List[Highlight]:
        """Extract highlights from a single .rm file."""
        logger.debug(f"Processing .rm file: {rm_file_path}")
        
        try:
            # Read binary content
            with open(rm_file_path, 'rb') as f:
                binary_content = f.read()
            
            # Extract ASCII text sequences
            raw_text = self._extract_ascii_text(binary_content)
            
            # Clean and filter text
            cleaned_text = self._clean_extracted_text(raw_text)
            
            if not cleaned_text:
                logger.debug(f"No valid highlights found in {rm_file_path}")
                return []
            
            # Get page number for this file
            file_id = Path(rm_file_path).stem
            page_number = doc_info.page_mappings.get(file_id, "Unknown")
            
            # Create highlight objects
            highlights = []
            for text in cleaned_text:
                highlight = Highlight(
                    text=text,
                    page_number=page_number,
                    file_name=Path(rm_file_path).name,
                    title=doc_info.title,
                    confidence=self._calculate_confidence(text)
                )
                highlights.append(highlight)
            
            logger.debug(f"Extracted {len(highlights)} highlights from {rm_file_path}")
            return highlights
            
        except Exception as e:
            logger.error(f"Error processing .rm file {rm_file_path}: {e}")
            return []
    
    def _extract_ascii_text(self, binary_data: bytes) -> List[str]:
        """Extract sequences of ASCII characters from binary data."""
        pattern = rb'[ -~]{%d,}' % self.min_text_length
        ascii_sequences = re.findall(pattern, binary_data)
        return [seq.decode('utf-8', errors='ignore') for seq in ascii_sequences]
    
    def _clean_extracted_text(self, text_list: List[str]) -> List[str]:
        """Clean and filter extracted text using quality heuristics."""
        cleaned_sentences = []
        
        for text in text_list:
            # Remove "l!" sequences and strip whitespace
            cleaned_text = text.replace("l!", "").strip()
            
            # Skip empty text or unwanted patterns
            if not cleaned_text or cleaned_text in self.unwanted_patterns:
                continue
            
            # Apply quality heuristics
            if not self._is_mostly_text(cleaned_text):
                continue
            if not self._has_enough_words(cleaned_text):
                continue
            if not self._has_low_symbol_ratio(cleaned_text):
                continue
            
            cleaned_sentences.append(cleaned_text)
        
        return cleaned_sentences
    
    def _is_mostly_text(self, text: str) -> bool:
        """Check if text is mostly alphabetic characters."""
        if not text:
            return False
        letters = sum(c.isalpha() for c in text)
        return letters / len(text) > self.text_threshold
    
    def _has_enough_words(self, text: str) -> bool:
        """Check if text has enough words to be meaningful."""
        return len(text.split()) >= self.min_words
    
    def _has_low_symbol_ratio(self, text: str) -> bool:
        """Check if text has a reasonable ratio of symbols to characters."""
        if not text:
            return False
        symbols = sum(not c.isalnum() and not c.isspace() for c in text)
        return symbols / len(text) < self.symbol_ratio_threshold
    
    def _calculate_confidence(self, text: str) -> float:
        """Calculate confidence score for extracted text."""
        # Simple confidence calculation based on text quality
        score = 1.0
        
        # Penalize very short text
        if len(text) < 20:
            score *= 0.8
        
        # Reward proper sentence structure
        if text.endswith('.') or text.endswith('!') or text.endswith('?'):
            score *= 1.1
        
        # Penalize high symbol ratio
        if not self._has_low_symbol_ratio(text):
            score *= 0.7
        
        return min(score, 1.0)
    
    def _store_highlights(self, highlights: List[Highlight], source_file: str) -> None:
        """Store highlights in the database."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create highlights table if it doesn't exist
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS highlights (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_file TEXT NOT NULL,
                        title TEXT NOT NULL,
                        text TEXT NOT NULL,
                        page_number TEXT,
                        file_name TEXT,
                        confidence REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Insert highlights
                for highlight in highlights:
                    cursor.execute('''
                        INSERT INTO highlights 
                        (source_file, title, text, page_number, file_name, confidence)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        source_file,
                        highlight.title,
                        highlight.text,
                        highlight.page_number,
                        highlight.file_name,
                        highlight.confidence
                    ))
                
                conn.commit()
                logger.debug(f"Stored {len(highlights)} highlights in database")
                
        except Exception as e:
            logger.error(f"Error storing highlights: {e}")
            raise
    
    def get_highlights_for_document(self, title: str) -> List[Dict]:
        """Retrieve all highlights for a specific document."""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT title, text, page_number, file_name, confidence, created_at
                    FROM highlights 
                    WHERE title = ?
                    ORDER BY page_number, created_at
                ''', (title,))
                
                columns = [description[0] for description in cursor.description]
                results = cursor.fetchall()
                
                return [dict(zip(columns, row)) for row in results]
                
        except Exception as e:
            logger.error(f"Error retrieving highlights for {title}: {e}")
            return []
    
    def export_highlights_to_csv(self, output_path: str, title_filter: Optional[str] = None) -> None:
        """Export highlights to CSV file."""
        try:
            with self.db_manager.get_connection() as conn:
                query = '''
                    SELECT title, text, page_number, file_name, confidence, created_at
                    FROM highlights
                '''
                params = []
                
                if title_filter:
                    query += ' WHERE title = ?'
                    params.append(title_filter)
                
                query += ' ORDER BY title, page_number, created_at'
                
                df = pd.read_sql_query(query, conn, params=params)
                df.to_csv(output_path, index=False)
                
                logger.info(f"Exported {len(df)} highlights to {output_path}")
                
        except Exception as e:
            logger.error(f"Error exporting highlights to CSV: {e}")
            raise


# Utility functions for backward compatibility and standalone usage

def process_directory(directory_path: str, db_manager: DatabaseManager) -> Dict[str, int]:
    """
    Process all .content files in a directory and extract highlights.
    
    Args:
        directory_path: Root directory containing .content files
        db_manager: Database manager instance
        
    Returns:
        Dictionary mapping content files to highlight counts
    """
    extractor = HighlightExtractor(db_manager)
    results = {}
    
    for root, _, files in os.walk(directory_path):
        for file_name in files:
            if file_name.endswith('.content'):
                file_path = os.path.join(root, file_name)
                
                if extractor.can_process(file_path):
                    result = extractor.process_file(file_path)
                    if result.success:
                        highlight_count = len(result.data.get('highlights', []))
                        results[file_path] = highlight_count
                        logger.info(f"Processed {file_path}: {highlight_count} highlights")
                    else:
                        logger.error(f"Failed to process {file_path}: {result.error_message}")
                        results[file_path] = 0
    
    return results


if __name__ == "__main__":
    # Example standalone usage
    import sys
    from ..core.database import DatabaseManager
    
    if len(sys.argv) != 2:
        print("Usage: python highlight_extractor.py <directory_path>")
        sys.exit(1)
    
    directory_path = sys.argv[1]
    
    # Initialize database manager
    db_manager = DatabaseManager("highlights_test.db")
    
    # Process directory
    results = process_directory(directory_path, db_manager)
    
    print(f"\nProcessing complete! Results:")
    for file_path, count in results.items():
        print(f"  {os.path.basename(file_path)}: {count} highlights")
    
    # Export all highlights to CSV
    extractor = HighlightExtractor(db_manager)
    output_csv = os.path.join(directory_path, "all_highlights.csv")
    extractor.export_highlights_to_csv(output_csv)
    print(f"\nAll highlights exported to: {output_csv}")
