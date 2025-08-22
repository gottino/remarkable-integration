"""
Notebook Text Extractor - Complete pipeline from .rm files to extracted text.

This module integrates:
1. PDF conversion (.rm files → PDF)
2. OCR processing (PDF → text with coordinates)
3. Text cleaning and enhancement
4. Database storage

Usage:
    extractor = NotebookTextExtractor()
    result = extractor.process_notebook(notebook_path)
"""

import os
import json
import logging
import sqlite3
import tempfile
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import time

# Import our existing components
from .pdf_ocr_engine import PDFOCREngine, OCRResult
from .tesseract_ocr_engine import TesseractOCREngine
from .enhanced_tesseract_ocr import EnhancedTesseractOCREngine
from .claude_vision_ocr import ClaudeVisionOCREngine
from ..core.rm_parser import RemarkableParser


@dataclass
class NotebookProcessingResult:
    """Result of notebook processing with text extraction."""
    success: bool
    notebook_uuid: str
    notebook_name: str = "Unknown"
    pages: List['NotebookPage'] = None
    todos: List['TodoItem'] = None
    error_message: str = None
    processing_time_ms: int = None
    
    def __post_init__(self):
        if self.pages is None:
            self.pages = []
        if self.todos is None:
            self.todos = []
from ..core.database import DatabaseManager
from ..core.events import get_event_bus, EventType

logger = logging.getLogger(__name__)


@dataclass
class TodoItem:
    """A todo item extracted from handwritten notes."""
    text: str
    completed: bool
    notebook_name: str
    notebook_uuid: str
    page_number: int
    date_extracted: Optional[str] = None  # Date from page annotation
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for export."""
        return {
            'text': self.text,
            'completed': self.completed,
            'notebook_name': self.notebook_name,
            'notebook_uuid': self.notebook_uuid,
            'page_number': self.page_number,
            'date_extracted': self.date_extracted,
            'confidence': self.confidence
        }


@dataclass
class NotebookPage:
    """Information about a notebook page."""
    page_uuid: str
    page_number: int
    rm_file_path: Path
    ocr_results: List[OCRResult]


@dataclass
class NotebookAnalysis:
    """Analysis result for a notebook without processing."""
    notebook_uuid: str
    notebook_name: str
    page_count: int
    has_pdf_epub: bool
    file_type: str  # 'notebook', 'pdf', 'epub'
    estimated_cost: float
    created_time: Optional[str] = None
    last_modified: Optional[str] = None


@dataclass
class NotebookTextResult:
    """Result of text extraction from a complete notebook."""
    success: bool
    notebook_uuid: str
    notebook_name: str
    pages: List[NotebookPage]
    total_text_regions: int
    processing_time_ms: int
    todos: List[TodoItem]
    error_message: Optional[str] = None
    
    def get_full_text(self, separator: str = "\n") -> str:
        """Get all text from all pages concatenated."""
        all_text = []
        for page in self.pages:
            page_text = []
            # Sort by y-coordinate then x-coordinate (reading order)
            sorted_results = sorted(
                page.ocr_results, 
                key=lambda r: (r.bounding_box.y, r.bounding_box.x)
            )
            for result in sorted_results:
                page_text.append(result.text)
            
            if page_text:
                all_text.append(" ".join(page_text))
        
        return separator.join(all_text)
    
    def get_text_by_page(self) -> Dict[int, str]:
        """Get text organized by page number."""
        page_texts = {}
        for page in self.pages:
            page_text = []
            # Sort by reading order
            sorted_results = sorted(
                page.ocr_results, 
                key=lambda r: (r.bounding_box.y, r.bounding_box.x)
            )
            for result in sorted_results:
                page_text.append(result.text)
            
            page_texts[page.page_number] = " ".join(page_text)
        
        return page_texts
    
    def extract_todos(self) -> List[TodoItem]:
        """Extract todo items from Claude Vision processed text."""
        import re
        
        todos = []
        
        for page in self.pages:
            # Get the full text for this page (Claude Vision gives us nicely formatted text)
            page_text = ""
            for ocr_result in page.ocr_results:
                page_text += ocr_result.text + "\n"
            
            if not page_text.strip():
                continue
                
            # Extract date from page text (Claude Vision often includes it)
            page_date = self._extract_date_from_text(page_text)
            
            # Split into lines and look for todo patterns
            lines = page_text.split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Look for checkbox patterns in the formatted text
                todo_patterns = [
                    # Markdown-style checkboxes (what Claude Vision outputs)
                    (r'^\s*-\s*\[\s*\]\s*(.+)', False),  # - [ ] task
                    (r'^\s*-\s*\[x\]\s*(.+)', True),     # - [x] task
                    (r'^\s*-\s*\[X\]\s*(.+)', True),     # - [X] task
                    (r'^\s*-\s*\[✓\]\s*(.+)', True),     # - [✓] task
                    (r'^\s*-\s*\[☑\]\s*(.+)', True),     # - [☑] task
                    # Unicode checkbox symbols
                    (r'^\s*-?\s*☐\s*(.+)', False),       # ☐ task
                    (r'^\s*-?\s*☑\s*(.+)', True),        # ☑ task
                    (r'^\s*-?\s*✓\s*(.+)', True),        # ✓ task
                    (r'^\s*-?\s*□\s*(.+)', False),       # □ task
                ]
                
                for pattern, completed in todo_patterns:
                    match = re.match(pattern, line, re.IGNORECASE)
                    if match:
                        todo_text = match.group(1).strip()
                        if todo_text and len(todo_text) > 2:  # Filter out very short matches
                            todo = TodoItem(
                                text=todo_text,
                                completed=completed,
                                notebook_name=self.notebook_name,
                                notebook_uuid=self.notebook_uuid,
                                page_number=page.page_number,
                                date_extracted=page_date,
                                confidence=1.0  # High confidence since Claude Vision processed it well
                            )
                            todos.append(todo)
                        break  # Don't match multiple patterns for same line
        
        return todos
    
    def _extract_date_from_page(self, page: NotebookPage) -> Optional[str]:
        """Extract date annotation from a page."""
        import re
        
        # Look for date patterns in upper area of page (date annotations)
        date_patterns = [
            r'[⌐\[\(┌]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s*[┘\]\)┐]?',
            r'[⌐\[\(┌]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2})\s*[┘\]\)┐]?'
        ]
        
        # Only look at OCR results from upper part of page (dates are usually in corners)
        upper_results = [r for r in page.ocr_results if r.bounding_box.y < 200]
        
        for result in upper_results:
            text = result.text.strip()
            for pattern in date_patterns:
                match = re.search(pattern, text)
                if match:
                    date_str = match.group(1)
                    # Normalize date format to dd-mm-yyyy
                    if len(date_str.split('-')[2]) == 2:  # 2-digit year
                        parts = date_str.split('-')
                        if len(parts) == 3:
                            date_str = f"{parts[0]}-{parts[1]}-20{parts[2]}"
                    return date_str
        
        return None
    
    def _extract_date_from_text(self, text: str) -> Optional[str]:
        """Extract date from Claude Vision processed text."""
        import re
        
        # Look for date patterns in the text (Claude Vision often formats dates nicely)
        date_patterns = [
            r'\*\*Date:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})\*\*',  # **Date: dd-mm-yyyy**
            r'Date:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',          # Date: dd-mm-yyyy
            r'[⌐\[\(┌]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})\s*[┘\]\)┐]?',  # bracketed dates
            r'[⌐\[\(┌]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2})\s*[┘\]\)┐]?'   # 2-digit year
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                # Normalize date format to dd-mm-yyyy
                if '-' in date_str and len(date_str.split('-')[2]) == 2:  # 2-digit year
                    parts = date_str.split('-')
                    if len(parts) == 3:
                        date_str = f"{parts[0]}-{parts[1]}-20{parts[2]}"
                elif '/' in date_str and len(date_str.split('/')[2]) == 2:  # 2-digit year with /
                    parts = date_str.split('/')
                    if len(parts) == 3:
                        date_str = f"{parts[0]}-{parts[1]}-20{parts[2]}"
                    else:
                        date_str = date_str.replace('/', '-')  # normalize to -
                return date_str
        
        return None


class NotebookTextExtractor:
    """Complete text extraction pipeline for reMarkable notebooks."""
    
    def __init__(
        self,
        data_directory: str = "./data/test_sync",
        db_connection: Optional[sqlite3.Connection] = None,
        db_manager: Optional['DatabaseManager'] = None,
        language: str = 'en',
        confidence_threshold: float = 0.7,
        enable_gpu: bool = False,
        temp_dir: Optional[str] = None
    ):
        """
        Initialize the notebook text extractor.
        
        Args:
            data_directory: Directory containing reMarkable data files
            db_connection: Optional database connection for storing results
            language: Language code for OCR (default: 'en')
            confidence_threshold: Minimum confidence for text recognition
            enable_gpu: Whether to use GPU acceleration (if available)
            temp_dir: Temporary directory for PDF conversion
        """
        self.data_directory = data_directory
        self.db_connection = db_connection
        self.db_manager = db_manager
        self.temp_dir = temp_dir or tempfile.gettempdir()
        
        # Initialize components
        # Note: rm_parser will be initialized per directory in process_directory()
        self.rm_parser = None
        self.filter_pdf_epub = False  # Filter out notebooks with associated PDF/EPUB files
        self.max_pages = None  # Maximum pages to process per notebook (for testing)
        self.notebook_filter_list = None  # List of notebook UUIDs/names to process selectively
        
        # OCR Engine Priority:
        # 1. Claude Vision (best for handwriting)
        # 2. EasyOCR (good general purpose)
        # 3. Enhanced Tesseract (improved traditional OCR)
        # 4. Regular Tesseract (fallback)
        
        # Try Claude Vision first (best for handwriting)
        logger.info("Trying Claude Vision OCR (best for handwriting)...")
        self.ocr_engine = ClaudeVisionOCREngine(
            db_connection=db_connection,
            confidence_threshold=confidence_threshold
        )
        
        # If Claude not available, try EasyOCR
        if not self.ocr_engine.is_available():
            logger.info("Claude Vision not available, trying EasyOCR...")
            self.ocr_engine = PDFOCREngine(
                db_connection=db_connection,
                language=language,
                confidence_threshold=confidence_threshold,
                enable_gpu=enable_gpu
            )
            
            # If EasyOCR not available, try Enhanced Tesseract
            if not self.ocr_engine.is_available():
                logger.info("EasyOCR not available, trying Enhanced Tesseract OCR...")
                # Convert language code: 'en' -> 'eng' for Tesseract
                tesseract_lang = 'eng' if language == 'en' else language
                self.ocr_engine = EnhancedTesseractOCREngine(
                    db_connection=db_connection,
                    language=tesseract_lang,
                    confidence_threshold=confidence_threshold * 100,  # Tesseract uses 0-100 scale
                    use_multiple_configs=True
                )
                
                # If Enhanced Tesseract fails, fall back to regular Tesseract
                if not self.ocr_engine.is_available():
                    logger.info("Enhanced Tesseract not available, trying regular Tesseract OCR...")
                    self.ocr_engine = TesseractOCREngine(
                        db_connection=db_connection,
                        language=tesseract_lang,
                        confidence_threshold=confidence_threshold * 100
                    )
        
        logger.info(f"Notebook Text Extractor initialized")
        logger.info(f"  OCR available: {self.ocr_engine.is_available()}")
        logger.info(f"  Language: {language}")
        logger.info(f"  Confidence threshold: {confidence_threshold}")
    
    def _get_db_connection(self):
        """Get a thread-safe database connection."""
        if self.db_manager:
            return self.db_manager.get_connection()
        elif self.db_connection:
            # For backwards compatibility, but this may have thread issues
            return self.db_connection
        else:
            return None
    
    def is_available(self) -> bool:
        """Check if the extractor is ready to process files."""
        return self.ocr_engine.is_available()
    
    def find_notebooks(self, input_path: str) -> List[Dict[str, Any]]:
        """Find all notebook documents in the given path."""
        input_path = Path(input_path)
        notebooks = []
        
        # Find all .metadata files
        for metadata_file in input_path.rglob("*.metadata"):
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # Only process DocumentType (not CollectionType folders)
                if metadata.get('type') == 'DocumentType':
                    uuid = metadata_file.stem
                    doc_name = metadata.get('visibleName', uuid)
                    
                    # Check if this document has a .content file (indicates it's a notebook)
                    content_file = metadata_file.with_suffix('.content')
                    if content_file.exists():
                        notebooks.append({
                            'uuid': uuid,
                            'name': doc_name,
                            'metadata_file': metadata_file,
                            'content_file': content_file,
                            'metadata': metadata
                        })
            except Exception as e:
                logger.warning(f"Error reading {metadata_file}: {e}")
                continue
        
        return notebooks
    
    def process_notebook(self, notebook_info: Dict[str, Any], input_path: str) -> NotebookTextResult:
        """
        Process a single notebook and extract all text.
        
        Args:
            notebook_info: Notebook information from find_notebooks()
            input_path: Base path containing the notebook files
            
        Returns:
            NotebookTextResult with extracted text
        """
        start_time = time.time()
        
        uuid = notebook_info['uuid']
        doc_name = notebook_info['name']
        content_file = notebook_info['content_file']
        
        logger.info(f"Processing notebook: {doc_name}")
        
        if not self.is_available():
            return NotebookTextResult(
                success=False,
                notebook_uuid=uuid,
                notebook_name=doc_name,
                pages=[],
                total_text_regions=0,
                processing_time_ms=0,
                todos=[],
                error_message="OCR engine not available"
            )
        
        try:
            # Read content file to get page list
            with open(content_file, 'r', encoding='utf-8') as f:
                content = json.load(f)
            
            # Get page list - try multiple approaches for different .content formats
            page_uuid_list = []
            
            # Method 1: formatVersion-specific handling
            if content.get('formatVersion') == 1:
                page_uuid_list = content.get('pages', [])
            elif content.get('formatVersion') == 2:
                pages = content.get('cPages', {}).get('pages', [])
                page_uuid_list = [page['id'] for page in pages if 'deleted' not in page]
            # Method 2: Fallback - direct pages array (common in many versions including v5)
            elif 'pages' in content:
                page_uuid_list = content.get('pages', [])
            else:
                raise ValueError(f"Unknown format version: {content.get('formatVersion')} and no 'pages' array found")
            
            if not page_uuid_list:
                raise ValueError("No pages found in notebook")
            
            logger.info(f"  Found {len(page_uuid_list)} pages")
            
            # Apply page limit if specified
            if self.max_pages and len(page_uuid_list) > self.max_pages:
                original_count = len(page_uuid_list)
                page_uuid_list = page_uuid_list[:self.max_pages]
                logger.info(f"  Limited to first {len(page_uuid_list)} pages (out of {original_count})")
            
            # Process each page
            processed_pages = []
            total_text_regions = 0
            
            with tempfile.TemporaryDirectory(prefix='notebook_text_extractor_') as tmpdir:
                tmpdir = Path(tmpdir)
                
                for page_num, page_uuid in enumerate(page_uuid_list, 1):
                    logger.debug(f"  Processing page {page_num}/{len(page_uuid_list)}")
                    
                    # Find the .rm file for this page
                    page_rm_file = Path(input_path) / uuid / f"{page_uuid}.rm"
                    
                    if not page_rm_file.exists():
                        logger.warning(f"  Page {page_num} .rm file not found: {page_rm_file}")
                        continue
                    
                    try:
                        # Convert page to PDF and extract text
                        page_result = self._process_single_page(
                            page_rm_file, page_uuid, page_num, tmpdir
                        )
                        
                        if page_result:
                            processed_pages.append(page_result)
                            total_text_regions += len(page_result.ocr_results)
                            logger.debug(f"    ✓ Page {page_num}: {len(page_result.ocr_results)} text regions")
                        else:
                            logger.warning(f"    ✗ Page {page_num}: No text extracted")
                    
                    except Exception as e:
                        logger.error(f"    ✗ Page {page_num}: Error processing - {e}")
                        continue
            
            processing_time = int((time.time() - start_time) * 1000)
            
            # Store results in database if available
            if (self.db_connection or self.db_manager) and processed_pages:
                self._store_notebook_results(uuid, doc_name, processed_pages)
            
            # Emit completion event
            event_bus = get_event_bus()
            if event_bus:
                event_bus.emit(EventType.TEXT_EXTRACTION_COMPLETED, {
                    'notebook_uuid': uuid,
                    'notebook_name': doc_name,
                    'page_count': len(processed_pages),
                    'text_regions': total_text_regions,
                    'processing_time_ms': processing_time
                })
            
            logger.info(f"  ✓ Completed: {total_text_regions} text regions from {len(processed_pages)} pages")
            
            # Create result and extract todos
            result = NotebookTextResult(
                success=True,
                notebook_uuid=uuid,
                notebook_name=doc_name,
                pages=processed_pages,
                total_text_regions=total_text_regions,
                processing_time_ms=processing_time,
                todos=[]
            )
            
            # Extract todos from the text
            result.todos = result.extract_todos()
            logger.info(f"  ✓ Extracted {len(result.todos)} todo items")
            
            # Store todos in database if available
            if (self.db_connection or self.db_manager) and result.todos:
                self._store_todos(result.todos)
            
            return result
            
        except Exception as e:
            processing_time = int((time.time() - start_time) * 1000)
            logger.error(f"  ✗ Error processing notebook {doc_name}: {e}")
            
            return NotebookTextResult(
                success=False,
                notebook_uuid=uuid,
                notebook_name=doc_name,
                pages=[],
                total_text_regions=0,
                processing_time_ms=processing_time,
                todos=[],
                error_message=str(e)
            )
    
    def _process_single_page(
        self, 
        rm_file: Path, 
        page_uuid: str, 
        page_number: int, 
        temp_dir: Path
    ) -> Optional[NotebookPage]:
        """Process a single page: .rm → SVG → PDF → OCR."""
        try:
            # Convert .rm to SVG using rm_parser (supports both v5 and v6)
            svg_file = temp_dir / f"page_{page_number:03d}.svg"
            # Extract notebook UUID and page UUID from file path
            # rm_file should be like: /path/uuid/page_uuid.rm
            notebook_uuid = rm_file.parent.name
            page_uuid_from_file = rm_file.stem
            
            page_info = self.rm_parser.convert_page_to_svg(
                notebook_uuid, page_uuid_from_file, str(svg_file)
            )
            
            if not svg_file.exists():
                logger.error(f"Failed to create SVG for page {page_number}")
                return None
            
            # Convert SVG to PDF
            pdf_file = temp_dir / f"page_{page_number:03d}.pdf"
            if not self._svg_to_pdf(svg_file, pdf_file):
                logger.error(f"Failed to create PDF for page {page_number}")
                return None
            
            # Perform OCR on PDF
            ocr_result = self.ocr_engine.process_file(str(pdf_file))
            
            if not ocr_result.success:
                logger.error(f"OCR failed for page {page_number}: {ocr_result.error_message}")
                return None
            
            return NotebookPage(
                page_uuid=page_uuid,
                page_number=page_number,
                rm_file_path=rm_file,
                ocr_results=ocr_result.ocr_results
            )
            
        except Exception as e:
            logger.error(f"Error processing page {page_number}: {e}")
            return None
    
    def _svg_to_pdf(self, svg_file: Path, pdf_file: Path) -> bool:
        """Convert SVG to PDF using rsvg-convert."""
        try:
            import subprocess
            import shutil
            
            if not shutil.which('rsvg-convert'):
                logger.error("rsvg-convert not found - needed for PDF generation")
                return False
            
            width_mm = 157  # Standard reMarkable page width in mm
            height_mm = 210  # Standard reMarkable page height in mm
            
            command = [
                'rsvg-convert',
                '--format=pdf',
                f'--width={width_mm}mm',
                f'--height={height_mm}mm',
                str(svg_file)
            ]
            
            result = subprocess.run(command, capture_output=True, timeout=30)
            
            if result.returncode == 0:
                with open(pdf_file, 'wb') as f:
                    f.write(result.stdout)
                return True
            else:
                logger.error(f"rsvg-convert error: {result.stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"SVG to PDF conversion failed: {e}")
            return False
    
    def _store_notebook_results(
        self, 
        notebook_uuid: str, 
        notebook_name: str, 
        pages: List[NotebookPage]
    ):
        """Store notebook text extraction results in database."""
        db_conn = self._get_db_connection()
        if not db_conn:
            return
        
        try:
            cursor = db_conn.cursor()
            
            # Create notebook_text_extractions table if it doesn't exist
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notebook_text_extractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notebook_uuid TEXT NOT NULL,
                    notebook_name TEXT NOT NULL,
                    page_uuid TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    bounding_box TEXT,
                    language TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(notebook_uuid, page_uuid, text, confidence)
                )
            ''')
            
            # Clear existing results for this notebook
            cursor.execute(
                'DELETE FROM notebook_text_extractions WHERE notebook_uuid = ?', 
                (notebook_uuid,)
            )
            
            # Insert new results
            for page in pages:
                for result in page.ocr_results:
                    cursor.execute('''
                        INSERT INTO notebook_text_extractions 
                        (notebook_uuid, notebook_name, page_uuid, page_number, 
                         text, confidence, bounding_box, language)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        notebook_uuid,
                        notebook_name,
                        page.page_uuid,
                        page.page_number,
                        result.text,
                        result.confidence,
                        json.dumps(result.bounding_box.to_dict()),
                        result.language
                    ))
            
            db_conn.commit()
            
            total_regions = sum(len(page.ocr_results) for page in pages)
            logger.info(f"Stored {total_regions} text regions for notebook {notebook_name}")
            
        except Exception as e:
            logger.error(f"Error storing notebook results: {e}")
        finally:
            if self.db_manager:  # Close the connection if we created it
                db_conn.close()
    
    def _calculate_page_content_hash(self, page: NotebookPage) -> str:
        """Calculate hash of page content for change detection."""
        import hashlib
        
        # Include factors that affect OCR results
        content_parts = [
            str(page.page_number),
            str(len(page.ocr_results)),  # Number of text regions
            # Hash of all text content
            '|'.join(sorted(result.text for result in page.ocr_results)),
            # Bounding boxes (for position changes)
            str(sorted(str(result.bounding_box) for result in page.ocr_results))
        ]
        
        content_string = '|'.join(content_parts)
        return hashlib.md5(content_string.encode('utf-8')).hexdigest()
    
    def _store_notebook_results_incremental(
        self, 
        notebook_uuid: str, 
        notebook_name: str, 
        pages: List[NotebookPage]
    ):
        """Store results with page-level incremental updates."""
        db_conn = self._get_db_connection()
        if not db_conn:
            return
        
        try:
            cursor = db_conn.cursor()
            updated_pages = 0
            total_regions = 0
            
            # For each page that was processed
            for page in pages:
                page_hash = self._calculate_page_content_hash(page)
                
                # Check if this page needs updating
                cursor.execute('''
                    SELECT page_content_hash FROM notebook_text_extractions 
                    WHERE notebook_uuid = ? AND page_uuid = ? 
                    LIMIT 1
                ''', (notebook_uuid, page.page_uuid))
                
                existing_hash = cursor.fetchone()
                
                if existing_hash and existing_hash[0] == page_hash:
                    logger.debug(f"Page {page.page_number} unchanged, skipping")
                    continue
                
                # Page has changed - update it
                logger.info(f"Updating page {page.page_number} in notebook {notebook_name}")
                updated_pages += 1
                
                # Delete old entries for this specific page
                cursor.execute('''
                    DELETE FROM notebook_text_extractions 
                    WHERE notebook_uuid = ? AND page_uuid = ?
                ''', (notebook_uuid, page.page_uuid))
                
                # Insert new entries for this page
                for result in page.ocr_results:
                    cursor.execute('''
                        INSERT INTO notebook_text_extractions 
                        (notebook_uuid, notebook_name, page_uuid, page_number, 
                         text, confidence, bounding_box, language, page_content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        notebook_uuid,
                        notebook_name,
                        page.page_uuid,
                        page.page_number,
                        result.text,
                        result.confidence,
                        json.dumps(result.bounding_box.to_dict()),
                        result.language,
                        page_hash
                    ))
                    total_regions += 1
            
            db_conn.commit()
            
            if updated_pages > 0:
                logger.info(f"Updated {updated_pages} pages with {total_regions} text regions for notebook {notebook_name}")
            else:
                logger.info(f"No changes detected in notebook {notebook_name}")
                
        except Exception as e:
            logger.error(f"Error in incremental notebook update: {e}")
            db_conn.rollback()
        finally:
            if self.db_manager:  # Close the connection if we created it
                db_conn.close()
    
    def process_notebook_incremental(self, notebook_uuid: str, force_reprocess: bool = False) -> NotebookProcessingResult:
        """Process notebook with incremental updates."""
        notebook_name = "Unknown Notebook"  # Initialize default value
        try:
            # Find the notebook directory
            notebook_dir = None
            for root, dirs, files in os.walk(self.data_directory):
                if notebook_uuid in dirs:
                    notebook_dir = os.path.join(root, notebook_uuid)
                    break
            
            if not notebook_dir:
                return NotebookProcessingResult(
                    success=False,
                    error_message=f"Notebook directory not found: {notebook_uuid}",
                    notebook_name="Unknown",
                    notebook_uuid=notebook_uuid
                )
            
            # Get notebook metadata
            metadata_file = os.path.join(os.path.dirname(notebook_dir), f"{notebook_uuid}.metadata")
            
            if os.path.exists(metadata_file):
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        notebook_name = metadata.get('visibleName', 'Unknown Notebook')
                except:
                    notebook_name = "Unknown Notebook"
            
            start_time = time.time()
            
            # Initialize rm_parser with the parent directory for v6 support
            parent_dir = os.path.dirname(notebook_dir)
            self.rm_parser = RemarkableParser(parent_dir, debug=False)
            
            # Process the notebook using the existing process_notebook method
            content_file = os.path.join(parent_dir, f"{notebook_uuid}.content")
            
            notebook_info = {
                'uuid': notebook_uuid,
                'name': notebook_name,
                'path': notebook_dir,
                'content_file': content_file
            }
            
            logger.info(f"Processing notebook: {notebook_name}")
            # Pass the parent directory, not the notebook directory itself
            result = self.process_notebook(notebook_info, parent_dir)
            
            if result.success:
                # Convert NotebookTextResult to NotebookProcessingResult
                notebook_result = NotebookProcessingResult(
                    success=True,
                    notebook_uuid=notebook_uuid,
                    notebook_name=notebook_name,
                    pages=result.pages if hasattr(result, 'pages') else [],
                    todos=result.todos if hasattr(result, 'todos') else []
                )
                
                if force_reprocess:
                    logger.info(f"Force reprocessing - using regular storage")
                    self._store_notebook_results(notebook_uuid, notebook_name, result.pages if hasattr(result, 'pages') else [])
                else:
                    logger.info(f"Using incremental storage")
                    self._store_notebook_results_incremental(notebook_uuid, notebook_name, result.pages if hasattr(result, 'pages') else [])
                
                return notebook_result
            else:
                return NotebookProcessingResult(
                    success=False,
                    notebook_uuid=notebook_uuid,
                    notebook_name=notebook_name,
                    error_message=result.error_message if hasattr(result, 'error_message') else "Processing failed"
                )
            
            
        except Exception as e:
            logger.error(f"Error processing notebook {notebook_uuid}: {e}")
            return NotebookProcessingResult(
                success=False,
                error_message=str(e),
                notebook_name=notebook_name,
                notebook_uuid=notebook_uuid
            )
    
    def _store_todos(self, todos: List[TodoItem]):
        """Store extracted todos in database."""
        db_conn = self._get_db_connection()
        if not db_conn:
            return
        
        try:
            cursor = db_conn.cursor()
            
            logger.info(f"Attempting to store {len(todos)} todos in database")
            
            # Insert todos into the todos table
            for i, todo in enumerate(todos):
                logger.debug(f"Storing todo {i+1}: {todo.text[:50]}...")
                cursor.execute('''
                    INSERT INTO todos 
                    (notebook_uuid, page_uuid, source_file, title, text, page_number, completed, confidence, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    todo.notebook_uuid,
                    None,  # page_uuid - could be added if needed
                    todo.notebook_name,  # Clean source file name without UUID in brackets
                    todo.text[:100],  # Use first 100 chars as title
                    todo.text,
                    str(todo.page_number),
                    todo.completed,
                    todo.confidence
                ))
            
            db_conn.commit()
            logger.info(f"Successfully stored {len(todos)} todos in database")
            
        except Exception as e:
            logger.error(f"Error storing todos in database: {e}")
        finally:
            if self.db_manager:  # Close the connection if we created it
                db_conn.close()
    
    def _load_notebook_list(self, notebook_list_file: str) -> set:
        """Load notebook UUIDs/names from file for selective processing."""
        notebook_set = set()
        
        try:
            with open(notebook_list_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):  # Skip empty lines and comments
                        notebook_set.add(line)
            
            logger.info(f"Loaded {len(notebook_set)} notebooks from filter list: {notebook_list_file}")
            
        except Exception as e:
            logger.error(f"Error loading notebook list from {notebook_list_file}: {e}")
            
        return notebook_set
    
    def process_directory(self, directory_path: str) -> Dict[str, NotebookTextResult]:
        """
        Process all notebooks in a directory and extract text.
        
        Args:
            directory_path: Directory containing reMarkable files
            
        Returns:
            Dictionary mapping notebook UUIDs to results
        """
        results = {}
        
        logger.info(f"Processing directory with text extraction: {directory_path}")
        
        # Initialize rm_parser with the directory path for v6 support
        self.rm_parser = RemarkableParser(directory_path, debug=False)
        
        # Find all notebooks
        notebooks = self.find_notebooks(directory_path)
        
        if not notebooks:
            logger.warning("No notebooks found")
            return results
        
        logger.info(f"Found {len(notebooks)} notebooks")
        
        # Filter notebooks if PDF/EPUB filtering is enabled
        if self.filter_pdf_epub:
            original_count = len(notebooks)
            notebooks = [nb for nb in notebooks if not self._has_associated_pdf_epub(nb['uuid'], directory_path)]
            filtered_count = original_count - len(notebooks)
            if filtered_count > 0:
                logger.info(f"Filtered out {filtered_count} notebooks with associated PDF/EPUB files")
        
        # Filter notebooks if selective list is provided
        if self.notebook_filter_list:
            original_count = len(notebooks)
            notebooks = [nb for nb in notebooks if nb['uuid'] in self.notebook_filter_list or nb['name'] in self.notebook_filter_list]
            filtered_count = original_count - len(notebooks)
            if filtered_count > 0:
                logger.info(f"Selected {len(notebooks)} notebooks from filter list (excluded {filtered_count})")
            elif len(notebooks) == 0:
                logger.warning("No notebooks matched the filter list. Check UUIDs/names in the list file.")
        
        # Process each notebook
        for i, notebook in enumerate(notebooks, 1):
            logger.info(f"[{i}/{len(notebooks)}] Processing: {notebook['name']}")
            
            try:
                result = self.process_notebook(notebook, directory_path)
                results[notebook['uuid']] = result
                
                if result.success:
                    logger.info(f"  ✓ Success: {result.total_text_regions} text regions")
                else:
                    logger.error(f"  ✗ Failed: {result.error_message}")
                    
            except Exception as e:
                logger.error(f"  ✗ Error processing {notebook['name']}: {e}")
                results[notebook['uuid']] = NotebookTextResult(
                    success=False,
                    notebook_uuid=notebook['uuid'],
                    notebook_name=notebook['name'],
                    pages=[],
                    total_text_regions=0,
                    processing_time_ms=0,
                    error_message=str(e)
                )
        
        # Summary
        successful = len([r for r in results.values() if r.success])
        total_regions = sum(r.total_text_regions for r in results.values())
        
        logger.info(f"Text extraction complete: {successful}/{len(results)} notebooks, {total_regions} total text regions")
        
        return results
    
    def analyze_directory(self, directory_path: str, cost_per_page: float = 0.003) -> Dict[str, NotebookAnalysis]:
        """
        Analyze all notebooks in a directory without processing - dry run for cost estimation.
        
        Args:
            directory_path: Directory containing reMarkable files
            cost_per_page: Estimated cost per page for Claude Vision OCR (default: $0.003)
            
        Returns:
            Dictionary mapping notebook UUIDs to analysis results
        """
        analyses = {}
        
        logger.info(f"Analyzing directory (dry-run): {directory_path}")
        
        # Find all notebooks
        notebooks = self.find_notebooks(directory_path)
        
        if not notebooks:
            logger.warning("No notebooks found")
            return analyses
        
        logger.info(f"Found {len(notebooks)} total items")
        
        # Filter notebooks if selective list is provided
        if self.notebook_filter_list:
            original_count = len(notebooks)
            notebooks = [nb for nb in notebooks if nb['uuid'] in self.notebook_filter_list or nb['name'] in self.notebook_filter_list]
            filtered_count = original_count - len(notebooks)
            if filtered_count > 0:
                logger.info(f"Selected {len(notebooks)} notebooks from filter list (excluded {filtered_count})")
            elif len(notebooks) == 0:
                logger.warning("No notebooks matched the filter list. Check UUIDs/names in the list file.")
        
        handwriting_notebooks = 0
        pdf_epub_notebooks = 0
        total_handwriting_pages = 0
        
        for i, notebook_info in enumerate(notebooks, 1):
            uuid = notebook_info['uuid']
            doc_name = notebook_info['name']
            content_file = notebook_info['content_file']
            
            logger.debug(f"[{i}/{len(notebooks)}] Analyzing: {doc_name}")
            
            try:
                # Read content file to determine type and page count
                with open(content_file, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                
                # Get file type
                file_type = content.get('fileType', 'unknown')
                
                # Get page count - try multiple approaches for different .content formats
                page_count = 0
                
                # Method 1: Direct pageCount field (common in many versions)
                if 'pageCount' in content:
                    page_count = content.get('pageCount', 0)
                # Method 2: formatVersion-specific handling
                elif content.get('formatVersion') == 1:
                    page_count = len(content.get('pages', []))
                elif content.get('formatVersion') == 2:
                    pages = content.get('cPages', {}).get('pages', [])
                    page_count = len([page for page in pages if 'deleted' not in page])
                # Method 3: Fallback - count pages array if available
                elif 'pages' in content:
                    page_count = len(content.get('pages', []))
                
                # Check for associated PDF/EPUB files
                has_pdf_epub = self._has_associated_pdf_epub(directory_path, uuid)
                
                # Read metadata for timestamps
                metadata_file = Path(directory_path) / f"{uuid}.metadata"
                created_time = None
                last_modified = None
                
                if metadata_file.exists():
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                        created_time = metadata.get('createdTime')
                        last_modified = metadata.get('lastModified')
                
                # Calculate estimated cost (only for handwriting notebooks)
                estimated_cost = 0.0
                if file_type == 'notebook' and not has_pdf_epub and page_count > 0:
                    estimated_cost = page_count * cost_per_page
                    handwriting_notebooks += 1
                    total_handwriting_pages += page_count
                elif file_type in ['pdf', 'epub'] or has_pdf_epub:
                    pdf_epub_notebooks += 1
                
                analysis = NotebookAnalysis(
                    notebook_uuid=uuid,
                    notebook_name=doc_name,
                    page_count=page_count,
                    has_pdf_epub=has_pdf_epub,
                    file_type=file_type,
                    estimated_cost=estimated_cost,
                    created_time=created_time,
                    last_modified=last_modified
                )
                
                analyses[uuid] = analysis
                
            except Exception as e:
                logger.error(f"Error analyzing {doc_name}: {e}")
                continue
        
        # Summary
        total_estimated_cost = sum(a.estimated_cost for a in analyses.values())
        
        logger.info(f"📊 Analysis Summary:")
        logger.info(f"  Total items: {len(notebooks)}")
        logger.info(f"  Handwriting notebooks (will be processed): {handwriting_notebooks}")
        logger.info(f"  PDF/EPUB notebooks (will be skipped): {pdf_epub_notebooks}")
        logger.info(f"  Total handwriting pages: {total_handwriting_pages}")
        logger.info(f"  Estimated cost: ${total_estimated_cost:.2f}")
        
        return analyses
    
    def _has_associated_pdf_epub(self, directory_path: str, uuid: str) -> bool:
        """Check if a notebook has an associated PDF or EPUB file."""
        base_path = Path(directory_path) / uuid
        
        # Check for PDF files in the notebook directory
        if base_path.exists():
            pdf_files = list(base_path.glob("*.pdf"))
            epub_files = list(base_path.glob("*.epub"))
            
            if pdf_files or epub_files:
                return True
        
        # Check metadata for source type (imported PDFs/EPUBs have source info)
        metadata_file = Path(directory_path) / f"{uuid}.metadata"
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                    source = metadata.get('source', '')
                    if source and source != '':
                        return True
            except:
                pass
        
        return False
    
    def export_text_to_file(
        self, 
        notebook_result: NotebookTextResult, 
        output_file: str,
        format: str = 'txt'
    ):
        """
        Export extracted text to file with enhanced Markdown formatting.
        
        Args:
            notebook_result: Result from process_notebook()
            output_file: Output file path
            format: Output format ('txt', 'json', 'csv', 'md')
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format.lower() in ['txt', 'md']:
            # Use Markdown format for both txt and md extensions
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(f"# {notebook_result.notebook_name}\n\n")
                
                # Write each page with delimiters
                for i, page in enumerate(notebook_result.pages, 1):
                    if i > 1:  # Add page separator for pages after the first
                        f.write(f"\n---\n\n## Page {page.page_number}\n\n")
                    
                    # Extract text from page
                    page_text = ""
                    for result in page.ocr_results:
                        page_text += result.text
                    
                    # Check if the text already contains date formatting from Claude
                    if page_text.strip():
                        # If Claude already formatted with date, use as-is
                        if page_text.startswith("**Date:"):
                            f.write(page_text)
                        else:
                            # Add page marker if no date found
                            if i == 1:
                                f.write(page_text)
                            else:
                                f.write(page_text)
                    
                    f.write("\n\n")
        
        elif format.lower() == 'json':
            # Enhanced JSON with page structure
            pages_data = {}
            for page in notebook_result.pages:
                page_text = ""
                for result in page.ocr_results:
                    page_text += result.text
                
                pages_data[f"page_{page.page_number}"] = {
                    'page_number': page.page_number,
                    'text': page_text,
                    'ocr_results_count': len(page.ocr_results)
                }
            
            data = {
                'notebook_uuid': notebook_result.notebook_uuid,
                'notebook_name': notebook_result.notebook_name,
                'total_pages': len(notebook_result.pages),
                'total_text_regions': notebook_result.total_text_regions,
                'processing_time_ms': notebook_result.processing_time_ms,
                'pages': pages_data
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        
        elif format.lower() == 'csv':
            import pandas as pd
            
            rows = []
            for page in notebook_result.pages:
                page_text = ""
                for result in page.ocr_results:
                    page_text += result.text
                
                rows.append({
                    'notebook_name': notebook_result.notebook_name,
                    'notebook_uuid': notebook_result.notebook_uuid,
                    'page_number': page.page_number,
                    'text': page_text,
                    'character_count': len(page_text),
                    'ocr_results_count': len(page.ocr_results)
                })
            
            df = pd.DataFrame(rows)
            df.to_csv(output_path, index=False)
        
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        logger.info(f"Exported text to {output_path}")
    
    def export_todos_to_file(
        self, 
        todos: List[TodoItem], 
        output_file: str,
        format: str = 'md'
    ):
        """
        Export extracted todos to file.
        
        Args:
            todos: List of TodoItem objects
            output_file: Output file path
            format: Output format ('txt', 'json', 'csv', 'md')
        """
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if format.lower() in ['txt', 'md']:
            # Markdown format with organization
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("# Todo Items\n\n")
                f.write("*Extracted from handwritten notebooks*\n\n")
                
                # Group todos by completion status
                completed_todos = [t for t in todos if t.completed]
                pending_todos = [t for t in todos if not t.completed]
                
                if pending_todos:
                    f.write("## 📋 Pending\n\n")
                    for todo in pending_todos:
                        f.write(f"- [ ] {todo.text}\n")
                        f.write(f"  - **Source**: {todo.notebook_name} (Page {todo.page_number})\n")
                        if todo.date_extracted:
                            f.write(f"  - **Date**: {todo.date_extracted}\n")
                        if todo.confidence > 0:
                            f.write(f"  - **Confidence**: {todo.confidence:.2f}\n")
                        f.write("\n")
                
                if completed_todos:
                    f.write("## ✅ Completed\n\n")
                    for todo in completed_todos:
                        f.write(f"- [x] {todo.text}\n")
                        f.write(f"  - **Source**: {todo.notebook_name} (Page {todo.page_number})\n")
                        if todo.date_extracted:
                            f.write(f"  - **Date**: {todo.date_extracted}\n")
                        if todo.confidence > 0:
                            f.write(f"  - **Confidence**: {todo.confidence:.2f}\n")
                        f.write("\n")
                
                # Summary
                f.write(f"---\n\n")
                f.write(f"**Summary**: {len(pending_todos)} pending, {len(completed_todos)} completed ({len(todos)} total)\n")
        
        elif format.lower() == 'json':
            # JSON format
            data = {
                'total_todos': len(todos),
                'pending_count': len([t for t in todos if not t.completed]),
                'completed_count': len([t for t in todos if t.completed]),
                'todos': [todo.to_dict() for todo in todos]
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        
        elif format.lower() == 'csv':
            # CSV format
            import pandas as pd
            
            rows = [todo.to_dict() for todo in todos]
            df = pd.DataFrame(rows)
            df.to_csv(output_path, index=False)
        
        else:
            raise ValueError(f"Unsupported format: {format}")
        
        logger.info(f"Exported {len(todos)} todos to {output_path}")


# Utility functions for standalone usage

def analyze_remarkable_library(
    directory_path: str,
    output_file: Optional[str] = None,
    cost_per_page: float = 0.003,
    notebook_list: Optional[str] = None
) -> Dict[str, NotebookAnalysis]:
    """
    Standalone function to analyze reMarkable library without processing - dry run.
    
    Args:
        directory_path: Directory containing reMarkable files
        output_file: Optional CSV file to save analysis results
        cost_per_page: Estimated cost per page for Claude Vision OCR
        notebook_list: Path to file containing notebook UUIDs or names to analyze
        
    Returns:
        Dictionary mapping notebook UUIDs to analysis results
    """
    extractor = NotebookTextExtractor()
    
    # Set notebook list filter if specified
    if notebook_list:
        extractor.notebook_filter_list = extractor._load_notebook_list(notebook_list)
        logger.info(f"Notebook filter enabled: Will analyze {len(extractor.notebook_filter_list)} specified notebooks")
    
    results = extractor.analyze_directory(directory_path, cost_per_page)
    
    # Export analysis to CSV if requested
    if output_file:
        import pandas as pd
        
        analysis_data = []
        for analysis in results.values():
            # Convert timestamps if they exist
            created_date = None
            modified_date = None
            
            if analysis.created_time:
                try:
                    import datetime
                    created_date = datetime.datetime.fromtimestamp(int(analysis.created_time) / 1000).strftime('%Y-%m-%d %H:%M:%S')
                except:
                    created_date = analysis.created_time
            
            if analysis.last_modified:
                try:
                    import datetime
                    modified_date = datetime.datetime.fromtimestamp(int(analysis.last_modified) / 1000).strftime('%Y-%m-%d %H:%M:%S')
                except:
                    modified_date = analysis.last_modified
            
            analysis_data.append({
                'notebook_name': analysis.notebook_name,
                'notebook_uuid': analysis.notebook_uuid,
                'file_type': analysis.file_type,
                'page_count': analysis.page_count,
                'has_pdf_epub': analysis.has_pdf_epub,
                'will_process': analysis.file_type == 'notebook' and not analysis.has_pdf_epub and analysis.page_count > 0,
                'estimated_cost_usd': analysis.estimated_cost,
                'created_date': created_date,
                'last_modified': modified_date
            })
        
        df = pd.DataFrame(analysis_data)
        df = df.sort_values(['will_process', 'estimated_cost_usd'], ascending=[False, False])
        df.to_csv(output_file, index=False)
        
        print(f"📊 Analysis exported to: {output_file}")
    
    return results


def extract_text_from_directory(
    directory_path: str,
    output_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    language: str = 'en',
    confidence_threshold: float = 0.7,
    output_format: str = 'md',
    include_pdf_epub: bool = False,
    max_pages: Optional[int] = None,
    notebook_list: Optional[str] = None
) -> Dict[str, NotebookTextResult]:
    """
    Standalone function to extract text from all notebooks in a directory.
    
    Args:
        directory_path: Directory containing reMarkable files
        output_dir: Optional directory to save individual text files
        db_path: Optional database path for storing results
        language: Language for OCR
        confidence_threshold: Minimum confidence threshold
        output_format: Output format ('txt', 'md', 'json', 'csv')
        include_pdf_epub: Include notebooks with associated PDF/EPUB files
        max_pages: Maximum pages to process per notebook (for testing)
        notebook_list: Path to file containing notebook UUIDs or names to process
        
    Returns:
        Dictionary mapping notebook UUIDs to results
    """
    db_manager = None
    if db_path:
        db_manager = DatabaseManager(db_path)
    
    try:
        with (db_manager.get_connection() if db_manager else sqlite3.connect(":memory:")) as conn:
            extractor = NotebookTextExtractor(
                db_connection=conn,
                language=language,
                confidence_threshold=confidence_threshold
            )
            
            if not extractor.is_available():
                logger.error("Text extraction not available - check EasyOCR and pdf2image installation")
                return {}
            
            # Apply filtering if needed
            if not include_pdf_epub:
                logger.info("Filtering enabled: Will skip notebooks with associated PDF/EPUB files")
                extractor.filter_pdf_epub = True
            
            # Set max pages limit if specified
            if max_pages:
                logger.info(f"Page limit enabled: Will process maximum {max_pages} pages per notebook")
                extractor.max_pages = max_pages
            
            # Set notebook list filter if specified
            if notebook_list:
                extractor.notebook_filter_list = extractor._load_notebook_list(notebook_list)
                logger.info(f"Notebook filter enabled: Will process {len(extractor.notebook_filter_list)} specified notebooks")
            
            results = extractor.process_directory(directory_path)
            
            # Export individual text files if requested
            if output_dir:
                output_path = Path(output_dir)
                output_path.mkdir(parents=True, exist_ok=True)
                
                # Collect all todos across notebooks
                all_todos = []
                
                for result in results.values():
                    if result.success:
                        # Create output file respecting reMarkable folder structure
                        try:
                            from ..utils.export_helpers import create_output_path
                            
                            # Use appropriate file extension
                            file_extension = 'md' if output_format == 'txt' else output_format
                            
                            db_conn = self._get_db_connection()
                            output_file_path = create_output_path(
                                result.notebook_uuid, 
                                result.notebook_name, 
                                db_conn,
                                str(output_path),
                                f".{file_extension}"
                            )
                            output_file = Path(output_file_path)
                            
                            # Ensure directory exists
                            output_file.parent.mkdir(parents=True, exist_ok=True)
                            
                        except Exception as e:
                            logger.warning(f"Could not create remarkable path, using fallback: {e}")
                            # Fallback to original logic
                            safe_name = "".join(c for c in result.notebook_name if c.isalnum() or c in ' -_()[]').strip()
                            file_extension = 'md' if output_format == 'txt' else output_format
                            output_file = output_path / f"{safe_name}.{file_extension}"
                        
                        extractor.export_text_to_file(result, str(output_file), output_format)
                        
                        # Collect todos from this notebook
                        all_todos.extend(result.todos)
                
                # Export todos to separate file if any were found
                if all_todos:
                    todos_file = output_path / f"todos.{output_format}"
                    extractor.export_todos_to_file(all_todos, str(todos_file), output_format)
                    logger.info(f"✓ Exported {len(all_todos)} todos to {todos_file}")
            
            return results
            
    except Exception as e:
        logger.error(f"Error in extract_text_from_directory: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {}


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python notebook_text_extractor.py <directory_path> [--output-dir DIR] [--db PATH] [--language LANG]")
        print("  directory_path: Directory containing reMarkable files")
        print("  --output-dir: Directory to save individual text files")
        print("  --db: Database path for storing results")
        print("  --language: OCR language (default: en)")
        sys.exit(1)
    
    target_path = sys.argv[1]
    output_dir = None
    db_path = None
    language = 'en'
    
    # Parse optional arguments
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--output-dir' and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--db' and i + 1 < len(sys.argv):
            db_path = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--language' and i + 1 < len(sys.argv):
            language = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    
    print("🚀 reMarkable Notebook Text Extractor")
    print("=" * 50)
    print(f"📂 Input path: {target_path}")
    if output_dir:
        print(f"📁 Output directory: {output_dir}")
    if db_path:
        print(f"🗃️  Database: {db_path}")
    print(f"🌐 Language: {language}")
    print()
    
    if not Path(target_path).exists():
        print(f"❌ Input path does not exist: {target_path}")
        sys.exit(1)
    
    try:
        results = extract_text_from_directory(
            target_path,
            output_dir=output_dir,
            db_path=db_path,
            language=language
        )
        
        successful = len([r for r in results.values() if r.success])
        total_regions = sum(r.total_text_regions for r in results.values())
        
        print("\n📊 Text Extraction Summary")
        print("=" * 30)
        print(f"Total notebooks: {len(results)}")
        print(f"Successfully processed: {successful}")
        print(f"Total text regions: {total_regions}")
        
        success_rate = (successful / len(results)) * 100 if results else 0
        print(f"Success rate: {success_rate:.1f}%")
        
        if successful > 0:
            print(f"\nResults by notebook:")
            for result in results.values():
                if result.success:
                    print(f"   {result.notebook_name}: {result.total_text_regions} text regions")
        
        print("\n🎉 Text extraction completed!")
        
    except KeyboardInterrupt:
        print("\n⏹️  Extraction interrupted by user")
    except Exception as e:
        print(f"\n❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)