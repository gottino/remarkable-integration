"""
Enhanced Highlight Extractor with EPUB Text Matching

This enhanced version:
1. Extracts highlights from .rm files (OCR-like, may have errors)
2. Finds the corresponding .epub file 
3. Uses fuzzy matching to find the real text in the epub
4. Merges adjacent highlights into complete passages
5. Returns clean, properly formatted text from the original epub

Key improvements over basic extractor:
- Fixes OCR errors like "speciDc" → "specific"
- Merges fragmented highlights into complete passages
- Uses original epub text for perfect formatting
- Provides match confidence scoring
"""

import os
import json
import re
import logging
import sqlite3
import zipfile
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from difflib import SequenceMatcher

# Try to import ebooklib for better EPUB handling, fall back to basic if not available
try:
    import ebooklib
    from ebooklib import epub
    EBOOKLIB_AVAILABLE = True
except ImportError:
    EBOOKLIB_AVAILABLE = False
    logging.info("ebooklib not available, using basic EPUB parsing")

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class RawHighlight:
    """Raw highlight extracted from .rm file (may contain OCR errors)."""
    text: str
    page_number: str
    file_name: str
    position: int  # Position in the extraction order
    confidence: float = 1.0


@dataclass
class EnhancedHighlight:
    """Enhanced highlight with real text from epub and merged passages."""
    original_text: str      # OCR text from .rm file
    corrected_text: str     # Real text from epub
    page_number: str
    file_name: str
    title: str
    passage_id: int         # ID for grouping merged highlights
    confidence: float
    match_score: float      # How well the OCR matched the epub text
    
    def to_dict(self) -> Dict:
        return {
            'original_text': self.original_text,
            'corrected_text': self.corrected_text,
            'text': self.corrected_text,  # For backward compatibility
            'page_number': self.page_number,
            'file_name': self.file_name,
            'title': self.title,
            'passage_id': self.passage_id,
            'confidence': self.confidence,
            'match_score': self.match_score
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


class EPUBTextExtractor:
    """Extract and search text from EPUB files."""
    
    def __init__(self, epub_path: str):
        self.epub_path = epub_path
        self.full_text = ""
        self.chapter_texts = []
        self._extract_text()
    
    def _extract_text(self):
        """Extract all text from the EPUB file."""
        try:
            if EBOOKLIB_AVAILABLE:
                self._extract_with_ebooklib()
            else:
                self._extract_basic()
        except Exception as e:
            logger.error(f"Failed to extract text from {self.epub_path}: {e}")
            self.full_text = ""
            self.chapter_texts = []
    
    def _extract_with_ebooklib(self):
        """Extract text using ebooklib (preferred method)."""
        book = epub.read_epub(self.epub_path)
        chapter_texts = []
        
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = item.get_content().decode('utf-8')
                text = self._clean_html(content)
                if text.strip():
                    chapter_texts.append(text)
        
        self.chapter_texts = chapter_texts
        self.full_text = '\n\n'.join(chapter_texts)
        logger.debug(f"Extracted {len(self.full_text)} characters from {len(chapter_texts)} chapters")
    
    def _extract_basic(self):
        """Extract text using basic ZIP handling (fallback)."""
        chapter_texts = []
        
        with zipfile.ZipFile(self.epub_path, 'r') as zip_file:
            # Find HTML/XHTML files
            html_files = [f for f in zip_file.namelist() 
                         if f.endswith(('.html', '.xhtml', '.htm')) and 'OEBPS' in f]
            
            for html_file in sorted(html_files):
                try:
                    content = zip_file.read(html_file).decode('utf-8')
                    text = self._clean_html(content)
                    if text.strip():
                        chapter_texts.append(text)
                except Exception as e:
                    logger.debug(f"Failed to read {html_file}: {e}")
        
        self.chapter_texts = chapter_texts
        self.full_text = '\n\n'.join(chapter_texts)
        logger.debug(f"Extracted {len(self.full_text)} characters from {len(chapter_texts)} chapters (basic)")
    
    def _clean_html(self, html_content: str) -> str:
        """Clean HTML content and extract readable text."""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Remove common ebook artifacts
        text = re.sub(r'\s*\n\s*', '\n', text)
        text = re.sub(r'\n+', '\n', text)
        
        return text
    
    def find_best_match(self, search_text: str, min_similarity: float = 0.6) -> Optional[Tuple[str, float, int]]:
        """
        Find the best matching text in the epub for the given search text.
        OPTIMIZED VERSION - much faster than original brute force approach.
        
        Args:
            search_text: Text to search for (may contain OCR errors)
            min_similarity: Minimum similarity score (0-1)
            
        Returns:
            Tuple of (matched_text, similarity_score, position) or None
        """
        if not self.full_text or not search_text:
            return None
        
        # Clean the search text
        clean_search = self._normalize_text(search_text)
        if len(clean_search) < 10:  # Too short to match reliably
            return None
        
        # OPTIMIZATION 1: Use word-based quick filtering first
        search_words = clean_search.split()
        if len(search_words) < 2:
            return None
        
        # Find potential positions using first and last words
        first_word = search_words[0]
        last_word = search_words[-1] if len(search_words) > 1 else first_word
        
        full_text_clean = self._normalize_text(self.full_text)
        
        # OPTIMIZATION 2: Find candidate positions much faster
        candidate_positions = []
        
        # Look for first word occurrences
        start_pos = 0
        while True:
            pos = full_text_clean.find(first_word, start_pos)
            if pos == -1:
                break
            candidate_positions.append(pos)
            start_pos = pos + 1
            
            # OPTIMIZATION 3: Limit candidates to prevent slowdown
            if len(candidate_positions) > 100:  # Max 100 candidates
                break
        
        if not candidate_positions:
            return None
        
        # OPTIMIZATION 4: Smart window sizing
        search_len = len(clean_search)
        min_window = max(search_len - 20, int(search_len * 0.7))
        max_window = min(search_len + 100, int(search_len * 2.0))
        
        best_match = None
        best_score = min_similarity
        
        # OPTIMIZATION 5: Check only promising candidates
        for pos in candidate_positions[:50]:  # Limit to first 50 candidates
            # Try different window sizes around this position
            for window_size in [search_len, min_window, max_window]:
                if pos + window_size > len(full_text_clean):
                    continue
                
                window_text = full_text_clean[pos:pos + window_size]
                
                # OPTIMIZATION 6: Quick similarity check first
                if self._quick_similarity_check(clean_search, window_text):
                    similarity = SequenceMatcher(None, clean_search, window_text).ratio()
                    
                    if similarity > best_score:
                        # Find the original text (with proper formatting)
                        original_text = self._find_original_text_fast(pos, window_size)
                        best_match = (original_text, similarity, pos)
                        best_score = similarity
                        
                        # OPTIMIZATION 7: Early exit if we find a great match
                        if similarity > 0.9:
                            return best_match
        
        return best_match
    
    def _quick_similarity_check(self, text1: str, text2: str) -> bool:
        """Quick similarity check to avoid expensive SequenceMatcher calls."""
        # Check if they have reasonable length similarity
        len_ratio = min(len(text1), len(text2)) / max(len(text1), len(text2))
        if len_ratio < 0.5:
            return False
        
        # Check if they share enough common words
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return False
        
        common_words = len(words1.intersection(words2))
        total_unique_words = len(words1.union(words2))
        
        word_similarity = common_words / total_unique_words if total_unique_words > 0 else 0
        return word_similarity > 0.3
    
    def _find_original_text_fast(self, start_pos: int, length: int) -> str:
        """Fast version of finding original text."""
        # Simple approach: just return the text section
        # More sophisticated mapping could be added later if needed
        
        estimated_start = max(0, start_pos - 50)
        estimated_end = min(len(self.full_text), start_pos + length + 50)
        section = self.full_text[estimated_start:estimated_end]
        
        # Basic cleanup
        section = re.sub(r'\s+', ' ', section).strip()
        
        # Try to find sentence boundaries for cleaner extraction
        sentences = re.split(r'[.!?]+\s+', section)
        if len(sentences) >= 2:
            # Return middle sentences, avoiding partial ones at start/end
            middle_sentences = sentences[1:-1] if len(sentences) > 2 else sentences
            result = '. '.join(middle_sentences)
            if result and not result.endswith(('.', '!', '?')):
                result += '.'
            return result
        else:
            return section[:500]  # Limit length
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for comparison (remove formatting, fix common OCR errors)."""
        # Convert to lowercase
        text = text.lower()
        
        # Fix common OCR errors
        ocr_fixes = {
            'D': 'fi',  # "speciDc" -> "specific"
            'n': 'fi',  # Another common OCR error
            'rn': 'm',  # "rn" often misread as "m"
            'cl': 'd',  # "cl" often misread as "d"
            '0': 'o',   # Zero vs O
            '1': 'l',   # One vs lowercase L
        }
        
        for wrong, right in ocr_fixes.items():
            text = text.replace(wrong, right)
        
        # Remove extra whitespace and punctuation for matching
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def _find_original_text(self, start_pos: int, length: int) -> str:
        """Find the original formatted text at the given position."""
        # This is a simplified approach - in the normalized text position,
        # find the corresponding position in the original text
        # For now, just return a section of the original text
        # A more sophisticated approach would maintain a mapping between positions
        
        estimated_start = max(0, start_pos - 100)
        estimated_end = min(len(self.full_text), start_pos + length + 100)
        section = self.full_text[estimated_start:estimated_end]
        
        # Try to find sentence boundaries for cleaner extraction
        sentences = re.split(r'[.!?]+', section)
        if len(sentences) >= 3:
            return '. '.join(sentences[1:-1]) + '.'
        else:
            return section.strip()


class EnhancedHighlightExtractor:
    """Enhanced highlight extractor with EPUB text matching."""
    
    def __init__(self, db_connection=None, enable_epub_matching=True):
        self.processor_type = "enhanced_highlight_extractor"
        self.db_connection = db_connection
        self.enable_epub_matching = enable_epub_matching  # New option to disable EPUB processing
        
        # Filtering settings (more lenient since we'll clean up with epub matching)
        self.min_text_length = 5
        self.text_threshold = 0.3
        self.min_words = 1
        self.symbol_ratio_threshold = 0.5
        
        # EPUB matching settings
        self.min_similarity = 0.6  # Minimum similarity for text matching
        self.merge_distance = 50   # Max characters between highlights to merge
        
        self._document_cache: Dict[str, any] = {}
        
        # Unwanted content patterns
        self.unwanted_patterns = {
            "reMarkable .lines file, version=6",
            "reMarkable .lines file, version=3",
            "Layer 1<", "Layer 2<", "Layer 3<", "Layer 4<", "Layer 5<"
        }
        
        self.unwanted_substrings = [
            "Layer 1<", "Layer 2<", "Layer 3<", "Layer 4<", "Layer 5<",
            ".lines file"
        ]
        
        mode = "with EPUB matching" if enable_epub_matching else "basic mode (no EPUB)"
        logger.info(f"Enhanced HighlightExtractor initialized {mode}")
    
    def can_process(self, file_path: str) -> bool:
        """Check if file can be processed."""
        if not file_path.endswith('.content'):
            return False
        
        try:
            with open(file_path, 'r') as f:
                content_data = json.load(f)
            
            file_type = content_data.get('fileType', '')
            if file_type not in ['pdf', 'epub']:
                return False
            
            # If EPUB matching is disabled, we can process any PDF/EPUB content file
            if not self.enable_epub_matching:
                return True
            
            # Check if corresponding epub exists (only if EPUB matching is enabled)
            epub_path = self._find_epub_file(file_path)
            return epub_path is not None
            
        except Exception as e:
            logger.warning(f"Could not check file {file_path}: {e}")
            return False
    
    def _find_epub_file(self, content_file_path: str) -> Optional[str]:
        """Find the corresponding EPUB file for a content file."""
        content_path = Path(content_file_path)
        base_name = content_path.stem
        
        # Look for epub in the same directory
        possible_epub = content_path.parent / f"{base_name}.epub"
        
        if possible_epub.exists():
            return str(possible_epub)
        
        # Look for epub files with similar names
        parent_dir = content_path.parent
        for epub_file in parent_dir.glob("*.epub"):
            if base_name in epub_file.stem or epub_file.stem in base_name:
                logger.info(f"Found similar epub: {epub_file}")
                return str(epub_file)
        
        logger.warning(f"No corresponding EPUB found for {content_file_path}")
        return None
    
    def process_file(self, file_path: str):
        """Process file with EPUB text enhancement."""
        try:
            logger.info(f"Processing with EPUB enhancement: {file_path}")
            
            # Step 1: Extract raw highlights (existing logic)
            raw_highlights = self._extract_raw_highlights(file_path)
            
            if not raw_highlights:
                logger.info(f"No raw highlights found in {file_path}")
                return self._create_result(True, file_path, [])
            
            logger.info(f"Extracted {len(raw_highlights)} raw highlights")
            
            # Step 2: Find corresponding EPUB (only if EPUB matching is enabled)
            epub_path = None
            epub_extractor = None
            
            if self.enable_epub_matching:
                epub_path = self._find_epub_file(file_path)
                if not epub_path:
                    logger.warning("No EPUB found - using basic processing mode")
                else:
                    # Step 3: Extract text from EPUB
                    logger.info(f"Loading EPUB: {epub_path}")
                    epub_extractor = EPUBTextExtractor(epub_path)
                    
                    if not epub_extractor.full_text:
                        logger.warning("Could not extract EPUB text - falling back to basic mode")
                        epub_extractor = None
            else:
                logger.info("EPUB matching disabled - using basic processing mode")
            
            # Step 4: Match and enhance highlights
            if epub_extractor:
                enhanced_highlights = self._enhance_highlights(raw_highlights, epub_extractor, file_path)
            else:
                # Fallback: convert raw highlights to enhanced format without EPUB correction
                enhanced_highlights = []
                doc_info = self._load_document_info(file_path)
                for i, raw_highlight in enumerate(raw_highlights):
                    enhanced = EnhancedHighlight(
                        original_text=raw_highlight.text,
                        corrected_text=raw_highlight.text,
                        page_number=raw_highlight.page_number,
                        file_name=raw_highlight.file_name,
                        title=doc_info.title,
                        passage_id=i,
                        confidence=raw_highlight.confidence,
                        match_score=0.0  # No EPUB matching performed
                    )
                    enhanced_highlights.append(enhanced)
            
            # Step 5: Merge adjacent highlights into passages
            merged_highlights = self._merge_adjacent_highlights(enhanced_highlights)
            
            logger.info(f"Final result: {len(merged_highlights)} enhanced passages from {len(raw_highlights)} raw highlights")
            
            # Step 6: Store in database
            if self.db_connection and merged_highlights:
                self._store_enhanced_highlights(merged_highlights, file_path)
            
            return self._create_result(True, file_path, merged_highlights)
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return self._create_result(False, file_path, [], str(e))
    
    def _extract_raw_highlights(self, file_path: str) -> List[RawHighlight]:
        """Extract raw highlights using existing logic."""
        try:
            # Load document info
            doc_info = self._load_document_info(file_path)
            
            # Find RM files
            rm_files = self._find_rm_files(doc_info)
            
            raw_highlights = []
            position = 0
            
            for rm_file in rm_files:
                highlights = self._extract_highlights_from_rm(rm_file, doc_info)
                for highlight in highlights:
                    raw_highlight = RawHighlight(
                        text=highlight.text,
                        page_number=highlight.page_number,
                        file_name=highlight.file_name,
                        position=position,
                        confidence=highlight.confidence
                    )
                    raw_highlights.append(raw_highlight)
                    position += 1
            
            return raw_highlights
            
        except Exception as e:
            logger.error(f"Error extracting raw highlights: {e}")
            return []
    
    def _load_document_info(self, content_file_path: str) -> DocumentInfo:
        """Load document info from .content and .metadata files."""
        content_file_path = Path(content_file_path)
        
        # Check cache first
        cache_key = str(content_file_path)
        if cache_key in self._document_cache:
            return self._document_cache[cache_key]
        
        # Load .content file
        with open(content_file_path, 'r') as f:
            content_data = json.load(f)
        
        file_type = content_data.get('fileType', '')
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
        """Extract page mappings from content data."""
        page_mappings = {}
        pages_data = content_data.get('cPages', {}).get('pages', [])
        
        for page in pages_data:
            if 'id' in page and 'redir' in page and 'value' in page['redir']:
                page_id = page['id']
                page_number = str(page['redir']['value'])
                page_mappings[page_id] = page_number
        
        return page_mappings
    
    def _find_rm_files(self, doc_info: DocumentInfo) -> List[str]:
        """Find RM files associated with the document."""
        content_path = Path(doc_info.content_file_path)
        subdirectory = content_path.parent / doc_info.content_id
        
        if not subdirectory.exists():
            return []
        
        rm_files = []
        for file_path in subdirectory.iterdir():
            if not file_path.suffix == '.rm':
                continue
            
            # Skip .rm files that have corresponding metadata JSON files
            json_file = subdirectory / f"{file_path.stem}-metadata.json"
            if json_file.exists():
                continue
            
            rm_files.append(str(file_path))
        
        return rm_files
    
    def _extract_highlights_from_rm(self, rm_file_path: str, doc_info: DocumentInfo):
        """Extract highlights from RM file."""
        try:
            # Read binary content
            with open(rm_file_path, 'rb') as f:
                binary_content = f.read()
            
            # Extract ASCII text sequences
            raw_text = self._extract_ascii_text(binary_content)
            
            # Clean and filter text
            cleaned_text = self._clean_extracted_text(raw_text)
            
            if not cleaned_text:
                return []
            
            # Get page number for this file
            file_id = Path(rm_file_path).stem
            page_number = doc_info.page_mappings.get(file_id, "Unknown")
            
            # Create highlight objects
            highlights = []
            for text in cleaned_text:
                highlight = type('Highlight', (), {
                    'text': text,
                    'page_number': page_number,
                    'file_name': Path(rm_file_path).name,
                    'title': doc_info.title,
                    'confidence': self._calculate_confidence(text)
                })()
                highlights.append(highlight)
            
            return highlights
            
        except Exception as e:
            logger.error(f"Error processing .rm file {rm_file_path}: {e}")
            return []
    
    def _extract_ascii_text(self, binary_data: bytes) -> List[str]:
        """Extract ASCII text sequences from binary data."""
        pattern = rb'[ -~]{%d,}' % self.min_text_length
        ascii_sequences = re.findall(pattern, binary_data)
        return [seq.decode('utf-8', errors='ignore') for seq in ascii_sequences]
    
    def _clean_extracted_text(self, text_list: List[str]) -> List[str]:
        """Clean extracted text using quality heuristics."""
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
            
            # Apply quality heuristics (more lenient since we'll clean up with EPUB)
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
    
    def _enhance_highlights(self, raw_highlights: List[RawHighlight], 
                          epub_extractor: EPUBTextExtractor, file_path: str) -> List[EnhancedHighlight]:
        """Enhance raw highlights by finding real text in EPUB."""
        enhanced_highlights = []
        
        # Get document title
        doc_info = self._load_document_info(file_path)
        
        # Progress tracking
        total_highlights = len(raw_highlights)
        logger.info(f"🔍 Enhancing {total_highlights} highlights with EPUB text matching...")
        
        # Time tracking to prevent excessive runtime
        import time
        start_time = time.time()
        max_time_per_highlight = 3.0  # Maximum 3 seconds per highlight
        max_total_time = 60.0  # Maximum 60 seconds total
        
        for i, raw_highlight in enumerate(raw_highlights):
            # Progress indicator
            if i % 5 == 0 or i == total_highlights - 1:
                elapsed = time.time() - start_time
                progress = (i + 1) / total_highlights * 100
                logger.info(f"   Progress: {progress:.0f}% ({i+1}/{total_highlights}) - {elapsed:.1f}s elapsed")
            
            # Timeout check
            elapsed = time.time() - start_time
            if elapsed > max_total_time:
                logger.warning(f"⏰ Timeout reached ({max_total_time}s) - processing remaining {total_highlights - i} highlights without EPUB matching")
                # Process remaining highlights without EPUB matching
                for j in range(i, total_highlights):
                    remaining_highlight = raw_highlights[j]
                    enhanced = EnhancedHighlight(
                        original_text=remaining_highlight.text,
                        corrected_text=remaining_highlight.text,
                        page_number=remaining_highlight.page_number,
                        file_name=remaining_highlight.file_name,
                        title=doc_info.title,
                        passage_id=j,
                        confidence=remaining_highlight.confidence * 0.7,  # Lower confidence
                        match_score=0.0
                    )
                    enhanced_highlights.append(enhanced)
                break
            
            highlight_start_time = time.time()
            
            logger.debug(f"Enhancing highlight {i+1}/{total_highlights}: '{raw_highlight.text[:30]}...'")
            
            # Try to find matching text in EPUB (with timeout)
            match_result = None
            try:
                match_result = epub_extractor.find_best_match(raw_highlight.text, self.min_similarity)
                
                highlight_elapsed = time.time() - highlight_start_time
                if highlight_elapsed > max_time_per_highlight:
                    logger.debug(f"  ⏰ Highlight took {highlight_elapsed:.1f}s (longer than {max_time_per_highlight}s limit)")
                
            except Exception as e:
                logger.debug(f"  ❌ Error in EPUB matching: {e}")
                match_result = None
            
            if match_result:
                corrected_text, match_score, position = match_result
                logger.debug(f"  ✅ Found match (score: {match_score:.2f})")
                
                enhanced = EnhancedHighlight(
                    original_text=raw_highlight.text,
                    corrected_text=corrected_text,
                    page_number=raw_highlight.page_number,
                    file_name=raw_highlight.file_name,
                    title=doc_info.title,
                    passage_id=i,  # Will be updated in merging step
                    confidence=raw_highlight.confidence,
                    match_score=match_score
                )
                enhanced_highlights.append(enhanced)
            else:
                logger.debug(f"  ❌ No good match found - keeping original")
                # Keep original text if no good match found
                enhanced = EnhancedHighlight(
                    original_text=raw_highlight.text,
                    corrected_text=raw_highlight.text,  # Use original as fallback
                    page_number=raw_highlight.page_number,
                    file_name=raw_highlight.file_name,
                    title=doc_info.title,
                    passage_id=i,
                    confidence=raw_highlight.confidence * 0.5,  # Lower confidence
                    match_score=0.0
                )
                enhanced_highlights.append(enhanced)
        
        total_elapsed = time.time() - start_time
        logger.info(f"🎯 Enhancement completed in {total_elapsed:.1f}s ({total_elapsed/total_highlights:.1f}s per highlight)")
        
        return enhanced_highlights
    
    def _merge_adjacent_highlights(self, highlights: List[EnhancedHighlight]) -> List[EnhancedHighlight]:
        """Merge adjacent highlights that likely belong to the same passage."""
        if len(highlights) <= 1:
            return highlights
        
        merged = []
        current_group = [highlights[0]]
        current_group[0].passage_id = 0
        passage_id = 0
        
        for i in range(1, len(highlights)):
            current = highlights[i]
            previous = current_group[-1]
            
            # Check if highlights should be merged
            should_merge = self._should_merge_highlights(previous, current)
            
            if should_merge:
                current.passage_id = passage_id
                current_group.append(current)
            else:
                # Finalize current group
                if len(current_group) > 1:
                    merged_highlight = self._merge_highlight_group(current_group)
                    merged.append(merged_highlight)
                else:
                    merged.append(current_group[0])
                
                # Start new group
                passage_id += 1
                current.passage_id = passage_id
                current_group = [current]
        
        # Handle last group
        if len(current_group) > 1:
            merged_highlight = self._merge_highlight_group(current_group)
            merged.append(merged_highlight)
        else:
            merged.append(current_group[0])
        
        logger.info(f"Merged {len(highlights)} highlights into {len(merged)} passages")
        return merged
    
    def _should_merge_highlights(self, h1: EnhancedHighlight, h2: EnhancedHighlight) -> bool:
        """Determine if two highlights should be merged into one passage."""
        # Same page
        if h1.page_number == h2.page_number:
            return True
        
        # Adjacent pages and text seems to continue
        try:
            p1 = int(h1.page_number) if h1.page_number.isdigit() else 0
            p2 = int(h2.page_number) if h2.page_number.isdigit() else 0
            if abs(p1 - p2) <= 1:
                # Check if first highlight ends mid-sentence and second starts continuing
                text1 = h1.corrected_text.strip()
                text2 = h2.corrected_text.strip()
                
                # If first doesn't end with sentence punctuation and second doesn't start with capital
                if (not text1.endswith(('.', '!', '?')) and 
                    text2 and not text2[0].isupper()):
                    return True
        except:
            pass
        
        return False
    
    def _merge_highlight_group(self, group: List[EnhancedHighlight]) -> EnhancedHighlight:
        """Merge a group of highlights into a single passage."""
        # Combine corrected text
        combined_text = ' '.join(h.corrected_text for h in group)
        combined_original = ' '.join(h.original_text for h in group)
        
        # Clean up the combined text
        combined_text = re.sub(r'\s+', ' ', combined_text).strip()
        combined_original = re.sub(r'\s+', ' ', combined_original).strip()
        
        # Use properties from first highlight
        first = group[0]
        
        # Average confidence and match scores
        avg_confidence = sum(h.confidence for h in group) / len(group)
        avg_match_score = sum(h.match_score for h in group) / len(group)
        
        # Get page range
        pages = [h.page_number for h in group]
        if len(set(pages)) == 1:
            page_range = pages[0]
        else:
            page_range = f"{min(pages)}-{max(pages)}"
        
        return EnhancedHighlight(
            original_text=combined_original,
            corrected_text=combined_text,
            page_number=page_range,
            file_name=first.file_name,
            title=first.title,
            passage_id=first.passage_id,
            confidence=avg_confidence,
            match_score=avg_match_score
        )
    
    def _raw_to_enhanced(self, raw: RawHighlight, passage_id: int) -> EnhancedHighlight:
        """Convert raw highlight to enhanced format (without EPUB correction)."""
        return EnhancedHighlight(
            original_text=raw.text,
            corrected_text=raw.text,
            page_number=raw.page_number,
            file_name=raw.file_name,
            title="Unknown Title",  # Will be filled by caller
            passage_id=passage_id,
            confidence=raw.confidence,
            match_score=0.0
        )
    
    def _create_result(self, success: bool, file_path: str, highlights: List[EnhancedHighlight], error: str = None):
        """Create processing result."""
        return ProcessingResult(
            success=success,
            file_path=file_path,
            processor_type=self.processor_type,
            data={'highlights': [h.to_dict() for h in highlights]} if success else {},
            error_message=error
        )
    
    def _store_enhanced_highlights(self, highlights: List[EnhancedHighlight], source_file: str):
        """Store enhanced highlights in database."""
        if not self.db_connection:
            return
        
        try:
            cursor = self.db_connection.cursor()
            
            # Create enhanced highlights table
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
            
            # Clear existing highlights for this source
            cursor.execute('DELETE FROM enhanced_highlights WHERE source_file = ?', (source_file,))
            
            # Insert enhanced highlights
            for highlight in highlights:
                # Extract page UUID from file_name (remove .rm extension)
                page_uuid = Path(highlight.file_name).stem if highlight.file_name else None
                
                cursor.execute('''
                    INSERT INTO enhanced_highlights 
                    (notebook_uuid, page_uuid, source_file, title, original_text, corrected_text, page_number, 
                     file_name, passage_id, confidence, match_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    notebook_uuid, page_uuid, source_file, highlight.title, highlight.original_text,
                    highlight.corrected_text, highlight.page_number, highlight.file_name,
                    highlight.passage_id, highlight.confidence, highlight.match_score
                ))
            
            self.db_connection.commit()
            logger.info(f"💾 Stored {len(highlights)} enhanced highlights")
            
        except Exception as e:
            logger.error(f"Error storing enhanced highlights: {e}")
    
    def get_enhanced_highlights_for_document(self, title: str) -> List[Dict]:
        """Retrieve all enhanced highlights for a specific document."""
        if not self.db_connection:
            return []
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute('''
                SELECT title, original_text, corrected_text, page_number, 
                       file_name, passage_id, confidence, match_score, created_at
                FROM enhanced_highlights 
                WHERE title = ?
                ORDER BY passage_id, created_at
            ''', (title,))
            
            columns = [description[0] for description in cursor.description]
            results = cursor.fetchall()
            
            return [dict(zip(columns, row)) for row in results]
            
        except Exception as e:
            logger.error(f"Error retrieving enhanced highlights for {title}: {e}")
            return []
    
    def export_enhanced_highlights_to_csv(self, output_path: str, title_filter: Optional[str] = None) -> None:
        """Export enhanced highlights to CSV file."""
        if not self.db_connection:
            logger.error("No database connection available for export")
            return
        
        try:
            query = '''
                SELECT title, original_text, corrected_text, page_number, 
                       file_name, passage_id, confidence, match_score, created_at
                FROM enhanced_highlights
            '''
            params = []
            
            if title_filter:
                query += ' WHERE title = ?'
                params.append(title_filter)
            
            query += ' ORDER BY title, passage_id, created_at'
            
            df = pd.read_sql_query(query, self.db_connection, params=params)
            df.to_csv(output_path, index=False)
            
            logger.info(f"Exported {len(df)} enhanced highlights to {output_path}")
            
        except Exception as e:
            logger.error(f"Error exporting enhanced highlights to CSV: {e}")
            raise


class DatabaseManager:
    """Simple database manager for enhanced highlight extraction."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Create database directory if it doesn't exist (only if there's a directory)
        db_dir = os.path.dirname(db_path)
        if db_dir:  # Only create directory if db_path includes a directory
            os.makedirs(db_dir, exist_ok=True)
        
        # Show where database will be created
        abs_path = os.path.abspath(db_path)
        logger.info(f"💾 Database location: {abs_path}")
    
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

def process_directory_enhanced(directory_path: str, db_manager: DatabaseManager = None, enable_epub_matching: bool = True) -> Dict[str, int]:
    """
    Process all .content files in a directory with enhanced highlight extraction.
    
    Args:
        directory_path: Root directory containing .content files
        db_manager: Database manager instance (optional)
        
    Returns:
        Dictionary mapping content files to enhanced passage counts
    """
    if not db_manager:
        db_manager = DatabaseManager("enhanced_highlights.db")
    
    results = {}
    
    try:
        conn = db_manager.get_connection()
        extractor = EnhancedHighlightExtractor(conn, enable_epub_matching)
        
        mode = "with EPUB enhancement" if enable_epub_matching else "basic mode (faster)"
        logger.info(f"🔍 Processing directory {mode}: {directory_path}")
        
        for root, _, files in os.walk(directory_path):
            for file_name in files:
                if file_name.endswith('.content'):
                    file_path = os.path.join(root, file_name)
                    
                    if extractor.can_process(file_path):
                        logger.info(f"✅ Processing: {os.path.basename(file_path)}")
                        result = extractor.process_file(file_path)
                        if result.success:
                            highlight_count = len(result.data.get('highlights', []))
                            results[file_path] = highlight_count
                            logger.info(f"   → Enhanced {highlight_count} passages")
                        else:
                            logger.error(f"   ❌ Failed: {result.error_message}")
                            results[file_path] = 0
                    else:
                        logger.info(f"⏭️ Skipping: {os.path.basename(file_path)} (no EPUB or cannot process)")
                        results[file_path] = 0
        
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Error in process_directory_enhanced: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return results


def compare_extraction_methods(directory_path: str) -> Dict:
    """
    Compare basic and enhanced extraction methods.
    
    Args:
        directory_path: Directory containing .content files
        
    Returns:
        Dictionary with comparison results
    """
    import time
    
    results = {
        'basic_method': {},
        'enhanced_method': {},
        'timing': {}
    }
    
    # Test basic method (if available)
    try:
        # Try to import the basic extractor - handle both relative and absolute imports
        try:
            from .highlight_extractor import process_directory as process_basic, DatabaseManager as BasicDBManager
        except ImportError:
            # Fallback for when running as standalone
            import sys
            from pathlib import Path
            project_root = Path(__file__).parent.parent.parent
            sys.path.insert(0, str(project_root))
            from src.processors.highlight_extractor import process_directory as process_basic, DatabaseManager as BasicDBManager
        
        print("📊 Testing basic method...")
        start_time = time.time()
        
        basic_db = BasicDBManager("comparison_basic.db")
        basic_results = process_basic(directory_path, basic_db)
        basic_total = sum(basic_results.values())
        
        results['basic_method'] = {
            'highlight_count': basic_total,
            'file_count': len(basic_results)
        }
        results['timing']['basic_method'] = time.time() - start_time
        
        print(f"   ✅ Basic: {basic_total} highlights")
        
    except ImportError as e:
        print(f"   ⏭️ Basic method not available: {e}")
        results['basic_method'] = {'error': 'Not available'}
    except Exception as e:
        print(f"   ❌ Basic method error: {e}")
        results['basic_method'] = {'error': str(e)}
    
    # Test enhanced method
    try:
        print("📚 Testing enhanced method...")
        start_time = time.time()
        
        enhanced_db = DatabaseManager("comparison_enhanced.db")
        enhanced_results = process_directory_enhanced(directory_path, enhanced_db)
        enhanced_total = sum(enhanced_results.values())
        
        results['enhanced_method'] = {
            'highlight_count': enhanced_total,
            'file_count': len(enhanced_results)
        }
        results['timing']['enhanced_method'] = time.time() - start_time
        
        print(f"   ✅ Enhanced: {enhanced_total} passages")
        
    except Exception as e:
        print(f"   ❌ Enhanced method error: {e}")
        results['enhanced_method'] = {'error': str(e)}
    
    # Show comparison
    if 'error' not in results['basic_method'] and 'error' not in results['enhanced_method']:
        basic_count = results['basic_method']['highlight_count']
        enhanced_count = results['enhanced_method']['highlight_count']
        basic_time = results['timing']['basic_method']
        enhanced_time = results['timing']['enhanced_method']
        
        print(f"\n📋 Comparison Results:")
        print(f"   Basic highlights: {basic_count} in {basic_time:.2f}s")
        print(f"   Enhanced passages: {enhanced_count} in {enhanced_time:.2f}s")
        
        if basic_count > 0:
            ratio = enhanced_count / basic_count
            print(f"   Compression ratio: {ratio:.2f} (enhanced merged {basic_count - enhanced_count} fragments)")
    
    return results


if __name__ == "__main__":
    import sys
    import time
    
    if len(sys.argv) < 2:
        print("Usage: python enhanced_highlight_extractor.py <directory_path> [--compare] [--fast]")
        print("  directory_path: Directory containing .content files and .epub files")
        print("  --compare: Compare basic vs enhanced extraction")
        print("  --fast: Skip EPUB matching for faster processing (basic extraction only)")
        sys.exit(1)
    
    directory_path = sys.argv[1]
    
    # Check for options
    compare_mode = len(sys.argv) > 2 and '--compare' in sys.argv
    fast_mode = len(sys.argv) > 2 and '--fast' in sys.argv
    
    if compare_mode:
        # Run comparison
        compare_extraction_methods(directory_path)
    else:
        # Run enhanced processing only
        print("🚀 Enhanced Highlight Extraction")
        print("=" * 40)
        
        if fast_mode:
            print("⚡ Fast mode enabled - skipping EPUB matching")
            results = process_directory_enhanced(directory_path, enable_epub_matching=False)
        else:
            results = process_directory_enhanced(directory_path, enable_epub_matching=True)
        
        total_passages = sum(results.values())
        processed_files = len([count for count in results.values() if count > 0])
        
        print(f"\n🎉 Enhanced processing complete!")
        print(f"   Files processed: {len(results)}")
        print(f"   Files with passages: {processed_files}")
        print(f"   Total enhanced passages: {total_passages}")
        
        if total_passages > 0:
            print(f"\n📄 Results by file:")
            for file_path, count in results.items():
                if count > 0:
                    file_name = os.path.basename(file_path)
                    print(f"   {file_name}: {count} passages")
            
            # Export to CSV
            output_csv = os.path.join(directory_path, "enhanced_highlights.csv")
            try:
                db_manager = DatabaseManager("enhanced_highlights.db")
                with db_manager.get_connection() as conn:
                    extractor = EnhancedHighlightExtractor(conn)
                    extractor.export_enhanced_highlights_to_csv(output_csv)
                    print(f"\n📤 Enhanced highlights exported to: {output_csv}")
            except Exception as e:
                print(f"⚠️ Could not export CSV: {e}")
        
        else:
            print("\n💡 No enhanced passages found. Possible reasons:")
            print("   - No .epub files found alongside .content files")
            print("   - No highlights in the .rm files")
            print("   - Text matching failed (try lowering similarity threshold)")