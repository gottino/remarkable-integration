"""
Highlight Extractor Module for reMarkable Pipeline

This module extracts highlighted text from reMarkable .rm files associated with 
PDF and EPUB documents. It processes the binary .rm files to find ASCII text 
sequences that represent user highlights, cleans and filters the extracted content,
and maps highlights to their corresponding page numbers.

Standalone version - no external dependencies except standard library and common packages.
"""

import os
import json
import re
import logging
import sqlite3
from typing import List, Dict, Optional
from dataclasses import dataclass
from pathlib import Path
import pandas as pd

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


@dataclass
class ProcessingResult:
    """Result of processing a file."""
    success: bool
    file_path: str
    processor_type: str
    data: Dict = None
    error_message: str = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}


class HighlightExtractor:
    """
    Processes reMarkable .rm files to extract highlighted text from PDF/EPUB documents.
    
    This processor:
    1. Identifies valid .content files (PDF/EPUB only)
    2. Maps .rm files to their corresponding documents
    3. Extracts ASCII text sequences from binary .rm files
    4. Cleans and filters extracted text using quality heuristics
    5. Maps highlights to page numbers using document metadata
    6. Stores results in the database
    """
    
    def __init__(self, db_connection=None):
        """Initialize highlight extractor."""
        self.processor_type = "highlight_extractor"
        self.db_connection = db_connection
        
        # Configuration - UPDATED TO MORE LENIENT SETTINGS
        # Based on debug results, the original settings were too strict
        self.min_text_length = 8   # Reduced from 10 (but not as low as debug's 5)
        self.text_threshold = 0.4  # Reduced from 0.6 (but not as low as debug's 0.3)  
        self.min_words = 2         # Reduced from 3 (but not as low as debug's 1)
        self.symbol_ratio_threshold = 0.3  # Increased from 0.2 (but not as high as debug's 0.5)
        
        # Cache for processed documents
        self._document_cache: Dict[str, DocumentInfo] = {}
        
        # Unwanted content patterns - Updated with reMarkable format artifacts
        self.unwanted_patterns = {
            "reMarkable .lines file, version=6",
            "reMarkable .lines file, version=3",
            "Layer 1<"  # reMarkable file format artifact - false positive
        }
        
        # Unwanted patterns that can appear anywhere in text (not just exact matches)
        self.unwanted_substrings = [
            "Layer 1<",
            "Layer 2<", 
            "Layer 3<",
            "Layer 4<",
            "Layer 5<"
        ]
        
        logger.info("HighlightExtractor initialized with balanced filtering settings")
        logger.info(f"  min_text_length: {self.min_text_length}")
        logger.info(f"  text_threshold: {self.text_threshold}")  
        logger.info(f"  min_words: {self.min_words}")
        logger.info(f"  symbol_ratio_threshold: {self.symbol_ratio_threshold}")
    
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
            with open(file_path, 'r') as f:
                content_data = json.load(f)
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
                # Store in database if connection available
                if self.db_connection:
                    self._store_highlights(highlights, file_path)
            
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
        with open(content_file_path, 'r') as f:
            content_data = json.load(f)
        
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
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
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
            
            logger.debug(f"Read {len(binary_content)} bytes from {os.path.basename(rm_file_path)}")
            
            # Extract ASCII text sequences
            raw_text = self._extract_ascii_text(binary_content)
            logger.debug(f"Extracted {len(raw_text)} ASCII sequences")
            
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
            
            logger.info(f"✅ Extracted {len(highlights)} highlights from {os.path.basename(rm_file_path)}")
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
        logger.debug(f"Cleaning {len(text_list)} text sequences")
        
        cleaned_sentences = []
        
        # Track filtering stats for debugging
        stats = {'original': len(text_list), 'passed': 0, 'failed_empty': 0, 
                'failed_unwanted': 0, 'failed_substring': 0, 'failed_text_ratio': 0, 
                'failed_words': 0, 'failed_symbols': 0}
        
        for text in text_list:
            # Remove "l!" sequences and strip whitespace
            cleaned_text = text.replace("l!", "").strip()
            
            # Skip empty text
            if not cleaned_text:
                stats['failed_empty'] += 1
                continue
            
            # Skip exact unwanted patterns
            if cleaned_text in self.unwanted_patterns:
                stats['failed_unwanted'] += 1
                logger.debug(f"Filtered exact pattern: '{cleaned_text}'")
                continue
            
            # Skip text containing unwanted substrings
            contains_unwanted = False
            for unwanted_substring in self.unwanted_substrings:
                if unwanted_substring in cleaned_text:
                    stats['failed_substring'] += 1
                    logger.debug(f"Filtered substring '{unwanted_substring}' in: '{cleaned_text[:50]}...'")
                    contains_unwanted = True
                    break
            
            if contains_unwanted:
                continue
            
            # Apply quality heuristics
            if not self._is_mostly_text(cleaned_text):
                stats['failed_text_ratio'] += 1
                logger.debug(f"Failed text ratio: '{cleaned_text[:30]}...'")
                continue
                
            if not self._has_enough_words(cleaned_text):
                stats['failed_words'] += 1
                logger.debug(f"Failed word count: '{cleaned_text[:30]}...'")
                continue
                
            if not self._has_low_symbol_ratio(cleaned_text):
                stats['failed_symbols'] += 1
                logger.debug(f"Failed symbol ratio: '{cleaned_text[:30]}...'")
                continue
            
            stats['passed'] += 1
            cleaned_sentences.append(cleaned_text)
        
        logger.debug(f"Filtering results: {stats}")
        if stats['passed'] > 0:
            logger.info(f"✅ {stats['passed']}/{stats['original']} text sequences passed filtering")
        else:
            logger.warning(f"❌ 0/{stats['original']} text sequences passed filtering - check filter settings")
        
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
        if not self.db_connection:
            return
        
        try:
            cursor = self.db_connection.cursor()
            
            # Create highlights table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS highlights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notebook_uuid TEXT NOT NULL,
                    page_uuid TEXT,
                    source_file TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    page_number TEXT,
                    file_name TEXT,
                    confidence REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(notebook_uuid, text, page_number) ON CONFLICT IGNORE
                )
            ''')
            
            # Clear any existing highlights for this source file to prevent duplicates
            cursor.execute('DELETE FROM highlights WHERE source_file = ?', (source_file,))
            
            # Extract document UUID from source file path
            doc_info = self._load_document_info(source_file)
            notebook_uuid = doc_info.content_id
            
            # Insert highlights
            inserted_count = 0
            for highlight in highlights:
                # Extract page UUID from file_name (remove .rm extension)
                page_uuid = Path(highlight.file_name).stem if highlight.file_name else None
                
                cursor.execute('''
                    INSERT INTO highlights 
                    (notebook_uuid, page_uuid, source_file, title, text, page_number, file_name, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    notebook_uuid,
                    page_uuid,
                    source_file,
                    highlight.title,
                    highlight.text,
                    highlight.page_number,
                    highlight.file_name,
                    highlight.confidence
                ))
                inserted_count += 1
            
            self.db_connection.commit()
            logger.info(f"💾 Stored {inserted_count} highlights in database for {os.path.basename(source_file)}")
            
        except Exception as e:
            logger.error(f"Error storing highlights: {e}")
            raise
    
    def get_highlights_for_document(self, title: str) -> List[Dict]:
        """Retrieve all highlights for a specific document."""
        if not self.db_connection:
            return []
        
        try:
            cursor = self.db_connection.cursor()
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
        if not self.db_connection:
            logger.error("No database connection available for export")
            return
        
        try:
            query = '''
                SELECT title, text, page_number, file_name, confidence, created_at
                FROM highlights
            '''
            params = []
            
            if title_filter:
                query += ' WHERE title = ?'
                params.append(title_filter)
            
            query += ' ORDER BY title, page_number, created_at'
            
            df = pd.read_sql_query(query, self.db_connection, params=params)
            df.to_csv(output_path, index=False)
            
            logger.info(f"Exported {len(df)} highlights to {output_path}")
            
        except Exception as e:
            logger.error(f"Error exporting highlights to CSV: {e}")
            raise


class DatabaseManager:
    """Simple database manager for highlight extraction."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Create database directory if it doesn't exist (only if there's a directory)
        db_dir = os.path.dirname(db_path)
        if db_dir:  # Only create directory if db_path includes a directory
            os.makedirs(db_dir, exist_ok=True)
    
    def get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        # Enable foreign keys and set up basic configuration
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    def __enter__(self):
        """Context manager entry."""
        self.connection = self.get_connection()
        return self.connection
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if hasattr(self, 'connection'):
            self.connection.close()


# Utility functions for backward compatibility and standalone usage

def process_directory(directory_path: str, db_manager: DatabaseManager = None) -> Dict[str, int]:
    """
    Process all .content files in a directory and extract highlights.
    
    Args:
        directory_path: Root directory containing .content files
        db_manager: Database manager instance (optional)
        
    Returns:
        Dictionary mapping content files to highlight counts
    """
    if not db_manager:
        db_manager = DatabaseManager("highlights.db")
    
    results = {}
    
    # Use a single connection for all processing
    try:
        conn = db_manager.get_connection()
        extractor = HighlightExtractor(conn)
        
        logger.info(f"🔍 Processing directory: {directory_path}")
        
        for root, _, files in os.walk(directory_path):
            for file_name in files:
                if file_name.endswith('.content'):
                    file_path = os.path.join(root, file_name)
                    logger.info(f"📄 Found .content file: {file_path}")
                    
                    if extractor.can_process(file_path):
                        logger.info(f"✅ Processing: {os.path.basename(file_path)}")
                        result = extractor.process_file(file_path)
                        if result.success:
                            highlight_count = len(result.data.get('highlights', []))
                            results[file_path] = highlight_count
                            logger.info(f"   → Extracted {highlight_count} highlights")
                            
                            # Verify highlights were stored in database
                            if highlight_count > 0:
                                cursor = conn.cursor()
                                cursor.execute("SELECT COUNT(*) FROM highlights WHERE source_file = ?", (file_path,))
                                stored_count = cursor.fetchone()[0]
                                logger.info(f"   → {stored_count} highlights stored in database")
                                
                                if stored_count != highlight_count:
                                    logger.warning(f"   ⚠️ Mismatch: extracted {highlight_count} but stored {stored_count}")
                        else:
                            logger.error(f"   ❌ Failed to process: {result.error_message}")
                            results[file_path] = 0
                    else:
                        logger.info(f"⏭️ Skipping: {os.path.basename(file_path)} (cannot process)")
        
        # Final database check
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM highlights")
        total_in_db = cursor.fetchone()[0]
        logger.info(f"📊 Total highlights in database: {total_in_db}")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Error in process_directory: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return results


if __name__ == "__main__":
    # Example standalone usage
    import sys
    
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
    with db_manager.get_connection() as conn:
        extractor = HighlightExtractor(conn)
        output_csv = os.path.join(directory_path, "all_highlights.csv")
        extractor.export_highlights_to_csv(output_csv)
        print(f"\nAll highlights exported to: {output_csv}")