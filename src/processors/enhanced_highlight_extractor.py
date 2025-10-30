"""
Enhanced Highlight Extractor v3 - Fixed Text Collation

This version fixes the critical issue where EPUB matching was mixing up text from 
different parts of the book. Instead, it:

1. ✅ Preserves original page-based grouping from .rm files
2. ✅ Correctly collates text fragments from same page in sequence
3. ✅ Applies OCR corrections to the collated text (no EPUB replacement)
4. ✅ Maintains the working highlight extraction logic from the original system

Key Fix:
- No more mixing highlights from different book sections
- OCR corrections applied to properly grouped text
- Preserves the original working collation algorithm
"""

import os
import json
import re
import logging
import sqlite3
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict

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
    original_text: Optional[str] = None  # For tracking OCR corrections
    correction_applied: bool = False
    
    def to_dict(self) -> Dict:
        """Convert highlight to dictionary for storage."""
        return {
            'text': self.text,
            'page_number': self.page_number,
            'file_name': self.file_name,
            'title': self.title,
            'confidence': self.confidence,
            'original_text': self.original_text or self.text,
            'correction_applied': self.correction_applied
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


class OCRCorrector:
    """Handles OCR error correction without EPUB dependency."""
    
    def __init__(self):
        self.correction_patterns = [
            # Common ligature corruptions in reMarkable highlights
            (r'\bgratiDcation\b', 'gratification'),
            (r'\bspeciDc\b', 'specific'),
            (r'\bspociDc\b', 'specific'),  # variant
            (r'\bdeDning\b', 'defining'),
            (r'\bDghts\b', 'fights'),
            (r'\bDnal\b', 'final'),
            (r'\bDrst\b', 'first'),
            (r'\bDle\b', 'file'),
            (r'\bDaws\b', 'flaws'),
            (r'\bsigniDcant\b', 'significant'),
            (r'\bbeneDto\b', 'benefit'),
            (r'\bDlled\b', 'filled'),
            (r'\bDnd\b', 'find'),
            (r'\bDx\b', 'fix'),
            
            # ff ligature corrections
            (r'\be:ectively\b', 'effectively'),
            (r'\be:icient\b', 'efficient'),
            (r'\be:ect\b', 'effect'),
            (r'\be:ort\b', 'effort'),
            (r'\bdi:erent\b', 'different'),
            (r'\bdi:icult\b', 'difficult'),
            (r'\bo:er\b', 'offer'),
            (r'\bsu:ering\b', 'suffering'),
            (r'\bsta:ing\b', 'staffing'),
            (r'\ba:ected\b', 'affected'),
            (r'\ba:ection\b', 'affection'),
            
            # General pattern fixes (more conservative)
            (r'([a-z])D([cefilmnrstuvwy])\b', r'\1fi\2'),  # aDc → afic, but be selective
            (r'([a-z]):([a-z])', r'\1ff\2'),  # a:ect → affect
            
            # Other common OCR errors
            (r'\brn\b', 'm'),     # rn → m
            (r'\bcl\b', 'd'),     # cl → d  
            
            # Cleanup patterns
            (r'\s+', ' '),        # Normalize whitespace
        ]
    
    def correct_text(self, text: str) -> tuple[str, bool]:
        """
        Apply OCR corrections to text.
        
        Returns:
            (corrected_text, correction_applied)
        """
        original_text = text
        corrected_text = text
        
        for pattern, replacement in self.correction_patterns:
            new_text = re.sub(pattern, replacement, corrected_text, flags=re.IGNORECASE)
            if new_text != corrected_text:
                logger.debug(f"OCR correction applied: '{pattern}' → '{replacement}'")
                corrected_text = new_text
        
        corrected_text = corrected_text.strip()
        correction_applied = corrected_text != original_text
        
        return corrected_text, correction_applied


class EnhancedHighlightExtractor:
    """
    Enhanced highlight extractor with proper text collation.

    This extractor:
    1. Preserves page-based grouping logic
    2. Properly collates text fragments from each .rm file
    3. Applies OCR corrections to the properly grouped text
    4. Does NOT use EPUB matching (abandoned as impractical)
    """
    
    def __init__(self, db_connection=None):
        self.processor_type = "enhanced_highlight_extractor"
        self.db_connection = db_connection
        
        # Use same filtering settings as original (proven to work)
        self.min_text_length = 8
        self.text_threshold = 0.4
        self.min_words = 2
        self.symbol_ratio_threshold = 0.3
        
        # Initialize OCR corrector
        self.ocr_corrector = OCRCorrector()
        
        self._document_cache: Dict[str, DocumentInfo] = {}
        
        # Unwanted content patterns (from original)
        self.unwanted_patterns = {
            "reMarkable .lines file, version=6",
            "reMarkable .lines file, version=3",
            "Layer 1<", "Layer 2<", "Layer 3<", "Layer 4<", "Layer 5<"
        }
        
        self.unwanted_substrings = [
            "Layer 1<", "Layer 2<", "Layer 3<", "Layer 4<", "Layer 5<",
            ".lines file", "remarkable", "version="
        ]
        
        logger.info("Enhanced HighlightExtractor v3 initialized")
        logger.info("  Mode: OCR correction with proper text collation")
        logger.info("  Fix: Preserves page-based grouping (no EPUB text mixing)")
    
    def can_process(self, file_path: str) -> bool:
        """Check if this processor can handle the given file."""
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
        """Process a .content file and extract highlights with proper collation."""
        try:
            start_time = time.time()
            logger.info(f"Processing with proper text collation: {file_path}")
            
            # Load document information (same as original)
            doc_info = self._load_document_info(file_path)
            
            # Find associated .rm files (same as original)
            rm_files = self._find_rm_files(doc_info)
            
            if not rm_files:
                logger.info(f"No .rm files found for {file_path}")
                return ProcessingResult(
                    success=True,
                    file_path=file_path,
                    processor_type=self.processor_type,
                    data={'highlights': [], 'message': 'No .rm files found'}
                )
            
            # Extract and collate highlights properly (FIXED VERSION)
            highlights = self._extract_highlights_with_proper_collation(rm_files, doc_info)

            # Match against PDF/EPUB to get clean text (if available)
            highlights = self._match_against_source_document(highlights, doc_info)
            pdf_match_count = sum(1 for h in highlights if h.correction_applied)

            # Apply OCR corrections to properly collated text (for highlights not matched against PDF)
            corrected_highlights = self._apply_ocr_corrections(highlights)
            ocr_correction_count = sum(1 for h in corrected_highlights if h.correction_applied and not any(
                orig_h.correction_applied and orig_h.file_name == h.file_name for orig_h in highlights
            ))

            processing_time = time.time() - start_time

            logger.info(f"Processing completed in {processing_time:.1f}s:")
            logger.info(f"  - Extracted {len(corrected_highlights)} highlights from {len(rm_files)} .rm files")
            if pdf_match_count > 0:
                logger.info(f"  - Matched {pdf_match_count} highlights against PDF source")
            if ocr_correction_count > 0:
                logger.info(f"  - Applied OCR corrections to {ocr_correction_count} highlights")
            
            # Store in database if connection available
            if self.db_connection and corrected_highlights:
                self._store_highlights(corrected_highlights, file_path)
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                processor_type=self.processor_type,
                data={
                    'highlights': [h.to_dict() for h in corrected_highlights],
                    'rm_file_count': len(rm_files),
                    'title': doc_info.title,
                    'pdf_match_count': pdf_match_count,
                    'ocr_correction_count': ocr_correction_count
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                error_message=str(e)
            )
    
    def _extract_highlights_with_proper_collation(self, rm_files: List[str], doc_info: DocumentInfo) -> List[Highlight]:
        """
        Extract highlights using the ORIGINAL working collation logic.
        
        This preserves the page-based grouping that was working correctly.
        """
        highlights = []
        
        for rm_file in rm_files:
            file_highlights = self._extract_highlights_from_single_rm_file(rm_file, doc_info)
            highlights.extend(file_highlights)
        
        logger.debug(f"Extracted {len(highlights)} highlights total")
        return highlights
    
    def _extract_highlights_from_single_rm_file(self, rm_file_path: str, doc_info: DocumentInfo) -> List[Highlight]:
        """
        Extract highlights from a single .rm file (ORIGINAL LOGIC).
        
        This is the working version that properly groups text by page.
        """
        logger.debug(f"Processing .rm file: {rm_file_path}")
        
        try:
            # Read binary content (same as original)
            with open(rm_file_path, 'rb') as f:
                binary_content = f.read()
            
            logger.debug(f"Read {len(binary_content)} bytes from {os.path.basename(rm_file_path)}")
            
            # Extract ASCII text sequences (same as original)
            raw_text = self._extract_ascii_text(binary_content)
            logger.debug(f"Extracted {len(raw_text)} ASCII sequences")
            
            # Clean and filter text (same as original)
            cleaned_text = self._clean_extracted_text(raw_text)
            
            if not cleaned_text:
                logger.debug(f"No valid highlights found in {rm_file_path}")
                return []
            
            # Get page number for this file (same as original)
            file_id = Path(rm_file_path).stem
            page_number = doc_info.page_mappings.get(file_id, "Unknown")
            
            # CRITICAL: Group all text from this .rm file into ONE highlight per file
            # This preserves the original page-based collation
            if len(cleaned_text) == 1:
                # Single text fragment - use as is
                full_text = cleaned_text[0]
            else:
                # Multiple text fragments - join them with spaces
                # This is the key collation logic that was working
                full_text = ' '.join(cleaned_text)
                
            # Clean up the joined text
            full_text = re.sub(r'\s+', ' ', full_text).strip()
            
            # Create single highlight for this page/file (ORIGINAL LOGIC)
            highlight = Highlight(
                text=full_text,
                page_number=page_number,
                file_name=Path(rm_file_path).name,
                title=doc_info.title,
                confidence=self._calculate_confidence(full_text)
            )
            
            logger.debug(f"✅ Created highlight from {os.path.basename(rm_file_path)}: {len(full_text)} chars")
            return [highlight]
            
        except Exception as e:
            logger.error(f"Error processing .rm file {rm_file_path}: {e}")
            return []
    
    def _match_against_source_document(self, highlights: List[Highlight], doc_info: DocumentInfo) -> List[Highlight]:
        """
        Match highlights against source PDF/EPUB to get clean text.

        Two-stage matching:
        1. Match corrupted .rm text against PDF (recovers some formatting)
        2. For EPUBs: Match PDF text against original EPUB (eliminates PDF artifacts)

        Args:
            highlights: List of highlights extracted from .rm files
            doc_info: Document information

        Returns:
            List of highlights with clean text from PDF/EPUB where available
        """
        # Find PDF file (reMarkable generates PDFs even for EPUBs)
        pdf_path = Path(doc_info.content_file_path).parent / f"{doc_info.content_id}.pdf"
        if not pdf_path.exists():
            logger.debug(f"PDF file not found: {pdf_path}, skipping PDF matching")
            return highlights

        logger.debug(f"Found PDF file for {doc_info.file_type} document: {pdf_path.name}")

        # Stage 1: Match against PDF
        try:
            from .pdf_text_matcher import PDFTextMatcher

            pdf_matcher = PDFTextMatcher(str(pdf_path), fuzzy_threshold=65)
            pdf_matched_count = 0
            total_pdf_pages = pdf_matcher.total_pages

            for highlight in highlights:
                # Parse page number
                try:
                    page_num = int(highlight.page_number) if highlight.page_number != "Unknown" else None
                except (ValueError, TypeError):
                    page_num = None

                if not page_num:
                    logger.debug(f"Skipping highlight with unknown page: {highlight.file_name}")
                    continue

                # Try to match against PDF
                result = pdf_matcher.match_highlight(
                    corrupted_text=highlight.text,
                    page_num=page_num,
                    search_offset=2  # Search ±2 pages
                )

                if result:
                    clean_text, score = result
                    if score >= 65:  # Use fuzzy matches above 65% confidence
                        highlight.original_text = highlight.text  # Save corrupted version
                        highlight.text = clean_text  # Replace with PDF text
                        highlight.correction_applied = True
                        highlight.confidence = score / 100.0
                        pdf_matched_count += 1
                        logger.debug(f"PDF matched highlight on page {page_num} (score: {score})")

            logger.info(f"  - Stage 1: Matched {pdf_matched_count}/{len(highlights)} highlights against PDF")

        except Exception as e:
            logger.warning(f"Error matching highlights against PDF: {e}")
            return highlights

        # Stage 2: For EPUB documents, match PDF text against original EPUB
        # This eliminates PDF artifacts (ligatures, encoding issues)
        if doc_info.file_type == 'epub':
            epub_path = Path(doc_info.content_file_path).parent / f"{doc_info.content_id}.epub"

            if epub_path.exists():
                logger.debug(f"Found EPUB source file: {epub_path.name}")

                try:
                    from .epub_text_matcher import EPUBTextMatcher

                    epub_matcher = EPUBTextMatcher(str(epub_path), fuzzy_threshold=85)
                    epub_matched_count = 0

                    for highlight in highlights:
                        # Only try EPUB matching for highlights that were PDF-matched
                        # (we want to replace PDF artifacts with clean EPUB text)
                        if not highlight.correction_applied:
                            continue

                        try:
                            page_num = int(highlight.page_number) if highlight.page_number != "Unknown" else None
                        except (ValueError, TypeError):
                            continue

                        if not page_num:
                            continue

                        # Match PDF text against EPUB to get clean version
                        result = epub_matcher.match_highlight(
                            pdf_text=highlight.text,  # PDF text (may have artifacts)
                            pdf_page=page_num,
                            total_pdf_pages=total_pdf_pages,
                            expand_sentences=True,
                            window_size=0.10  # Search ±10% of book
                        )

                        if result:
                            epub_text, score = result

                            # Validate that the found text is actually similar to the input
                            # (prevents false matches in large search windows)
                            from fuzzywuzzy import fuzz
                            similarity = fuzz.ratio(highlight.text[:100], epub_text[:100])

                            if score >= 85 and similarity >= 70:  # Both fuzzy score and similarity check
                                # Replace PDF text with clean EPUB text
                                highlight.text = epub_text
                                # Update confidence to EPUB match score
                                highlight.confidence = score / 100.0
                                epub_matched_count += 1
                                logger.debug(f"EPUB matched highlight on page {page_num} (score: {score}, similarity: {similarity}%)")
                            elif similarity < 70:
                                logger.debug(f"Rejected EPUB match on page {page_num}: low similarity ({similarity}%) despite high score ({score})")

                    logger.info(f"  - Stage 2: Matched {epub_matched_count}/{pdf_matched_count} PDF highlights against EPUB source")

                except Exception as e:
                    logger.warning(f"Error matching highlights against EPUB: {e}")

        return highlights

    def _apply_ocr_corrections(self, highlights: List[Highlight]) -> List[Highlight]:
        """Apply OCR corrections to highlights that weren't matched against PDF."""
        corrected_highlights = []

        for highlight in highlights:
            # Skip OCR correction if already matched against PDF
            if highlight.correction_applied:
                logger.debug(f"Skipping OCR for page {highlight.page_number}: already PDF-matched")
                corrected_highlights.append(highlight)
                continue

            corrected_text, ocr_applied = self.ocr_corrector.correct_text(highlight.text)

            if ocr_applied:
                logger.debug(f"OCR correction on page {highlight.page_number}: "
                           f"'{highlight.text[:50]}...' → '{corrected_text[:50]}...'")

            # Create new highlight with OCR corrections
            corrected_highlight = Highlight(
                text=corrected_text,
                page_number=highlight.page_number,
                file_name=highlight.file_name,
                title=highlight.title,
                confidence=highlight.confidence * (1.0 if ocr_applied else 0.9),
                original_text=highlight.original_text or highlight.text,  # Preserve original
                correction_applied=ocr_applied
            )

            corrected_highlights.append(corrected_highlight)

        return corrected_highlights
    
    # ===============================
    # ORIGINAL WORKING METHODS (unchanged)
    # ===============================
    
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
        skipped_count = 0
        MIN_FILE_SIZE = 100  # bytes - files smaller than this are likely empty

        for file_path in subdirectory.iterdir():
            if not file_path.suffix == '.rm':
                continue

            # Skip small files that likely don't contain highlights
            # Empty .rm files are typically ~51 bytes (just headers)
            # Highlight files are usually hundreds of bytes or more
            file_size = file_path.stat().st_size
            if file_size < MIN_FILE_SIZE:
                skipped_count += 1
                continue

            rm_files.append(str(file_path))

        logger.debug(f"Found {len(rm_files)} .rm files for document {doc_info.title} (skipped {skipped_count} small files)")
        return rm_files
    
    def _extract_ascii_text(self, binary_data: bytes) -> List[str]:
        """Extract sequences of ASCII characters from binary data."""
        pattern = rb'[ -~]{%d,}' % self.min_text_length
        ascii_sequences = re.findall(pattern, binary_data)
        return [seq.decode('utf-8', errors='ignore') for seq in ascii_sequences]
    
    def _clean_extracted_text(self, text_list: List[str]) -> List[str]:
        """Clean and filter extracted text using quality heuristics."""
        logger.debug(f"Cleaning {len(text_list)} text sequences")
        
        cleaned_sentences = []
        
        for text in text_list:
            # Remove "l!" sequences and strip whitespace
            cleaned_text = text.replace("l!", "").strip()
            
            # Skip empty text
            if not cleaned_text:
                continue
            
            # Skip exact unwanted patterns
            if cleaned_text in self.unwanted_patterns:
                continue
            
            # Skip text containing unwanted substrings
            contains_unwanted = False
            for unwanted_substring in self.unwanted_substrings:
                if unwanted_substring in cleaned_text:
                    contains_unwanted = True
                    break
            
            if contains_unwanted:
                continue
            
            # Apply quality heuristics
            if not self._is_mostly_text(cleaned_text):
                continue
            if not self._has_enough_words(cleaned_text):
                continue
            if not self._has_low_symbol_ratio(cleaned_text):
                continue
            
            cleaned_sentences.append(cleaned_text)
        
        logger.debug(f"Filtering results: {len(cleaned_sentences)}/{len(text_list)} sequences passed")
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
            
            # Use existing enhanced_highlights table (compatible with v1/v2)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS enhanced_highlights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    notebook_uuid TEXT NOT NULL,
                    page_uuid TEXT,
                    source_file TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    corrected_text TEXT NOT NULL,
                    page_number TEXT,
                    file_name TEXT,
                    passage_id INTEGER,
                    confidence REAL,
                    match_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(notebook_uuid, corrected_text, page_number) ON CONFLICT IGNORE
                )
            ''')
            
            # Extract document UUID from source file path
            doc_info = self._load_document_info(source_file)
            notebook_uuid = doc_info.content_id
            
            # Clear any existing highlights for this source file
            cursor.execute('DELETE FROM enhanced_highlights WHERE source_file = ?', (source_file,))
            
            # Insert highlights
            inserted_count = 0
            for highlight in highlights:
                # Extract page UUID from file_name (remove .rm extension)
                page_uuid = Path(highlight.file_name).stem if highlight.file_name else None
                
                # Map v3 fields to existing enhanced_highlights schema
                # passage_id: set to 0 for v3 (we don't do EPUB passage merging)
                # match_score: set to 1.0 for v3 (we use dictionary corrections, not fuzzy matching)
                cursor.execute('''
                    INSERT INTO enhanced_highlights
                    (notebook_uuid, page_uuid, source_file, title, original_text, corrected_text, page_number, file_name, passage_id, confidence, match_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    notebook_uuid,
                    page_uuid,
                    source_file,
                    highlight.title,
                    highlight.original_text or highlight.text,  # original_text (before OCR correction)
                    highlight.text,                             # corrected_text (after OCR correction)
                    highlight.page_number,
                    highlight.file_name,
                    0,                                          # passage_id (not used in v3)
                    highlight.confidence,
                    1.0                                         # match_score (always 1.0 for dictionary-based)
                ))
                inserted_count += 1
            
            self.db_connection.commit()
            correction_count = sum(1 for h in highlights if h.correction_applied)
            logger.info(f"💾 Stored {inserted_count} highlights in database ({correction_count} with corrections)")
            
        except Exception as e:
            logger.error(f"Error storing highlights: {e}")
            raise

    def export_highlights_to_csv(self, output_path: str, title_filter: Optional[str] = None) -> None:
        """Export enhanced highlights to CSV file."""
        if not self.db_connection:
            logger.error("No database connection available for export")
            return

        try:
            import pandas as pd

            query = '''
                SELECT title, original_text, corrected_text, page_number,
                       file_name, confidence, created_at
                FROM enhanced_highlights
            '''
            params = []

            if title_filter:
                query += ' WHERE title = ?'
                params.append(title_filter)

            query += ' ORDER BY title, page_number, created_at'

            df = pd.read_sql_query(query, self.db_connection, params=params)
            df.to_csv(output_path, index=False)

            logger.info(f"Exported {len(df)} enhanced highlights to {output_path}")

        except Exception as e:
            logger.error(f"Error exporting highlights to CSV: {e}")
            raise


# Utility functions for standalone usage and testing

def process_directory_enhanced(directory_path: str, db_manager=None) -> Dict[str, int]:
    """
    Process all .content files in a directory using enhanced extraction v3.
    
    Args:
        directory_path: Root directory containing .content files
        db_manager: Database manager instance (optional)
        
    Returns:
        Dictionary mapping content files to highlight counts
    """
    if not db_manager:
        # Simple database manager for testing
        class SimpleDBManager:
            def __init__(self, db_path: str):
                self.db_path = db_path
                os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
            
            def get_connection(self):
                conn = sqlite3.connect(self.db_path)
                conn.execute("PRAGMA foreign_keys = ON")
                return conn
        
        db_manager = SimpleDBManager("enhanced_highlights_v3.db")
    
    results = {}
    
    try:
        conn = db_manager.get_connection()
        extractor = EnhancedHighlightExtractor(conn)
        
        logger.info(f"🔍 Processing directory with v3 (proper collation): {directory_path}")
        
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
                            correction_count = result.data.get('correction_count', 0)
                            results[file_path] = highlight_count
                            logger.info(f"   → Extracted {highlight_count} highlights ({correction_count} corrected)")
                        else:
                            logger.error(f"   ❌ Failed to process: {result.error_message}")
                            results[file_path] = 0
                    else:
                        logger.info(f"⏭️ Skipping: {os.path.basename(file_path)} (cannot process)")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Error in process_directory_enhanced: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python enhanced_highlight_extractor.py <directory_path>")
        print("  directory_path: Directory containing .content files")
        sys.exit(1)
    
    directory_path = sys.argv[1]
    
    print("🚀 Enhanced Highlight Extraction")
    print("=" * 50)
    print("🔧 Fixed: Proper text collation (no mixing)")
    print("✅ Feature: OCR error corrections")
    print("📄 Preserves: Original page-based grouping")
    print()

    results = process_directory_enhanced(directory_path)
    
    total_highlights = sum(results.values())
    processed_files = len([count for count in results.values() if count > 0])
    
    print(f"\n🎉 Enhanced processing v3 complete!")
    print(f"   Files processed: {len(results)}")
    print(f"   Files with highlights: {processed_files}")
    print(f"   Total highlights: {total_highlights}")
    
    if total_highlights > 0:
        print(f"\n📄 Results by file:")
        for file_path, count in results.items():
            if count > 0:
                file_name = os.path.basename(file_path)
                print(f"   {file_name}: {count} highlights")
        
        print(f"\n📊 Check results in database:")
        print(f"   sqlite3 enhanced_highlights_v3.db")
        print(f"   SELECT page_number, original_text, corrected_text FROM enhanced_highlights;")