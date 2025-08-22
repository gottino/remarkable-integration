"""
Enhanced Highlight Extractor v2 - Improved OCR Error Correction

This enhanced version addresses the key issues found in the original:

Key Improvements:
1. ✅ Better OCR error correction patterns (D→fi, :→ff, etc.)
2. ✅ More robust fuzzy text matching with preprocessing
3. ✅ Performance optimizations for faster EPUB matching
4. ✅ Better similarity scoring with word-level matching
5. ✅ Improved text normalization for highlight extraction

Fixes specific issues like:
- "gratiDcation" → "gratification" 
- "speciDc" → "specific"
- "e:ectively" → "effectively"
- "deDning" → "defining"
- "Dghts" → "fights"
"""

import os
import json
import re
import logging
import sqlite3
import zipfile
import time
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass
from pathlib import Path
import pandas as pd
from difflib import SequenceMatcher
from collections import defaultdict

# Try to import ebooklib for better EPUB handling
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
    position: int
    confidence: float = 1.0


@dataclass
class EnhancedHighlight:
    """Enhanced highlight with corrected text from EPUB."""
    original_text: str      # OCR text from .rm file
    corrected_text: str     # Real text from EPUB
    page_number: str
    file_name: str
    title: str
    passage_id: int
    confidence: float
    match_score: float      # How well the OCR matched the EPUB text
    correction_applied: bool = False  # Whether text was corrected
    
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
            'match_score': self.match_score,
            'correction_applied': self.correction_applied
        }


@dataclass
class DocumentInfo:
    """Document metadata."""
    content_id: str
    title: str
    file_type: str
    page_mappings: Dict[str, str]
    content_file_path: str


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


class ImprovedEPUBTextExtractor:
    """Optimized EPUB text extractor with better performance and text handling."""
    
    def __init__(self, epub_path: str):
        self.epub_path = epub_path
        self.full_text = ""
        self.chapter_texts = []
        self.word_index = defaultdict(list)  # Word -> list of positions
        self._extract_text_and_index()
    
    def _extract_text_and_index(self):
        """Extract text and build word index for fast searching."""
        try:
            if EBOOKLIB_AVAILABLE:
                self._extract_with_ebooklib()
            else:
                self._extract_basic()
            
            # Build word index for fast searching
            self._build_word_index()
            
        except Exception as e:
            logger.error(f"Failed to extract text from {self.epub_path}: {e}")
            self.full_text = ""
            self.chapter_texts = []
    
    def _extract_with_ebooklib(self):
        """Extract text using ebooklib."""
        book = epub.read_epub(self.epub_path)
        chapter_texts = []
        
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = item.get_content().decode('utf-8', errors='ignore')
                text = self._clean_html(content)
                if text.strip():
                    chapter_texts.append(text)
        
        self.chapter_texts = chapter_texts
        self.full_text = '\n\n'.join(chapter_texts)
        logger.debug(f"Extracted {len(self.full_text)} characters from {len(chapter_texts)} chapters")
    
    def _extract_basic(self):
        """Extract text using basic ZIP handling."""
        chapter_texts = []
        
        with zipfile.ZipFile(self.epub_path, 'r') as zip_file:
            html_files = [f for f in zip_file.namelist() 
                         if f.endswith(('.html', '.xhtml', '.htm')) and ('OEBPS' in f or 'chapter' in f.lower())]
            
            for html_file in sorted(html_files):
                try:
                    content = zip_file.read(html_file).decode('utf-8', errors='ignore')
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
    
    def _build_word_index(self):
        """Build an index of word positions for fast searching."""
        if not self.full_text:
            return
        
        # Normalize text for indexing
        normalized_text = self._normalize_for_indexing(self.full_text)
        words = normalized_text.split()
        
        # Build position index
        current_pos = 0
        for word in words:
            if len(word) >= 3:  # Only index meaningful words
                self.word_index[word].append(current_pos)
            current_pos += len(word) + 1  # +1 for space
    
    def _normalize_for_indexing(self, text: str) -> str:
        """Normalize text for word indexing."""
        # Convert to lowercase and remove punctuation for indexing
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def find_best_match_optimized(self, search_text: str, min_similarity: float = 0.6) -> Optional[Tuple[str, float, int]]:
        """
        Optimized text matching using word index and better preprocessing.
        
        Args:
            search_text: Text to search for (may contain OCR errors)
            min_similarity: Minimum similarity score
            
        Returns:
            Tuple of (matched_text, similarity_score, position) or None
        """
        if not self.full_text or not search_text:
            return None
        
        # Preprocess the search text for better matching
        processed_search = self._preprocess_ocr_text(search_text)
        normalized_search = self._normalize_for_indexing(processed_search)
        
        if len(normalized_search) < 10:
            return None
        
        # Extract meaningful words from search text
        search_words = [w for w in normalized_search.split() if len(w) >= 3]
        if len(search_words) < 2:
            return None
        
        # Find candidate positions using word index
        candidate_positions = self._find_candidate_positions(search_words)
        
        if not candidate_positions:
            return None
        
        # Test promising candidates
        best_match = None
        best_score = min_similarity
        
        normalized_full_text = self._normalize_for_indexing(self.full_text)
        search_length = len(normalized_search)
        
        # Limit candidates to prevent timeout
        for pos in candidate_positions[:30]:  # Top 30 candidates
            for window_multiplier in [1.0, 0.8, 1.3]:  # Try different window sizes
                window_size = int(search_length * window_multiplier)
                window_size = max(window_size, 50)  # Minimum window
                
                if pos + window_size > len(normalized_full_text):
                    continue
                
                window_text = normalized_full_text[pos:pos + window_size]
                
                # Quick similarity check
                if self._quick_word_similarity(normalized_search, window_text) > 0.4:
                    similarity = SequenceMatcher(None, normalized_search, window_text).ratio()
                    
                    if similarity > best_score:
                        # Find original formatted text
                        original_text = self._extract_original_text(pos, window_size)
                        best_match = (original_text, similarity, pos)
                        best_score = similarity
                        
                        # Early exit for excellent matches
                        if similarity > 0.9:
                            return best_match
        
        return best_match
    
    def _preprocess_ocr_text(self, text: str) -> str:
        """
        Preprocess OCR text to fix common errors before matching.
        
        This addresses the specific OCR errors we found:
        - D → fi (gratification, specific, defining)
        - : → ff (effectively)
        - Various ligature corruptions
        """
        # Fix common OCR errors in reMarkable highlights
        ocr_corrections = [
            # Ligature corrections - these are the most common issues
            (r'\bgratiDcation\b', 'gratification'),
            (r'\bspeciDc\b', 'specific'),
            (r'\bdeDning\b', 'defining'),
            (r'\bDghts\b', 'fights'),
            (r'\bDnal\b', 'final'),
            (r'\bDrst\b', 'first'),
            (r'\bDle\b', 'file'),
            (r'\bDaws\b', 'flaws'),
            (r'\bsigniDcant\b', 'significant'),
            
            # ff ligature corrections
            (r'\be:ectively\b', 'effectively'),
            (r'\be:ort\b', 'effort'),
            (r'\bdi:erent\b', 'different'),
            (r'\bdi:icult\b', 'difficult'),
            (r'\bo:er\b', 'offer'),
            (r'\bsu:ering\b', 'suffering'),
            
            # General patterns for fi and ff ligatures
            (r'([a-z])D([a-z])', r'\1fi\2'),  # aDc → afic
            (r'([a-z]):([a-z])', r'\1ff\2'),  # a:ect → affect
            
            # Other common OCR errors
            (r'\brn\b', 'm'),     # rn often becomes m
            (r'\bcl\b', 'd'),     # cl often becomes d
            (r'\b0\b', 'o'),      # 0 vs O
            (r'\b1\b', 'l'),      # 1 vs l
            
            # Word boundary fixes
            (r'\s+', ' '),        # Normalize whitespace
        ]
        
        corrected_text = text
        for pattern, replacement in ocr_corrections:
            corrected_text = re.sub(pattern, replacement, corrected_text, flags=re.IGNORECASE)
        
        return corrected_text.strip()
    
    def _find_candidate_positions(self, search_words: List[str]) -> List[int]:
        """Find candidate positions using word index."""
        if not search_words:
            return []
        
        # Find positions for the most unique words first
        word_frequencies = {word: len(self.word_index[word]) for word in search_words if word in self.word_index}
        
        if not word_frequencies:
            return []
        
        # Sort by frequency (less frequent = more unique)
        sorted_words = sorted(word_frequencies.items(), key=lambda x: x[1])
        
        # Start with the most unique word
        unique_word = sorted_words[0][0]
        candidate_positions = self.word_index[unique_word][:]
        
        # Filter candidates that have other words nearby
        filtered_candidates = []
        normalized_full_text = self._normalize_for_indexing(self.full_text)
        
        for pos in candidate_positions:
            # Check if other search words appear nearby
            window_start = max(0, pos - 100)
            window_end = min(len(normalized_full_text), pos + 200)
            window = normalized_full_text[window_start:window_end]
            
            words_found = sum(1 for word in search_words[:5] if word in window)  # Check first 5 words
            
            if words_found >= min(2, len(search_words)):  # At least 2 words or all if fewer
                filtered_candidates.append(pos)
        
        # Sort by position and return top candidates
        return sorted(filtered_candidates)[:50]
    
    def _quick_word_similarity(self, text1: str, text2: str) -> float:
        """Quick word-based similarity check."""
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        return intersection / union if union > 0 else 0.0
    
    def _extract_original_text(self, start_pos: int, length: int) -> str:
        """Extract the original formatted text from the position in normalized text."""
        # This is simplified - a more sophisticated approach would maintain
        # a mapping between normalized and original positions
        
        # Estimate position in original text
        normalized_chars = len(self._normalize_for_indexing(self.full_text[:start_pos]))
        ratio = start_pos / max(normalized_chars, 1)
        
        estimated_start = int(len(self.full_text) * ratio * 0.8)  # Conservative estimate
        estimated_end = min(len(self.full_text), estimated_start + length * 2)
        
        section = self.full_text[estimated_start:estimated_end]
        
        # Try to find sentence boundaries
        sentences = re.split(r'[.!?]+\s+', section)
        if len(sentences) >= 2:
            # Return middle sentences to avoid partial cuts
            middle_sentences = sentences[1:-1] if len(sentences) > 2 else sentences
            result = '. '.join(middle_sentences)
            if result and not result.endswith(('.', '!', '?')):
                result += '.'
            return result[:500]  # Limit length
        else:
            return section[:500]


class EnhancedHighlightExtractorV2:
    """Enhanced highlight extractor v2 with improved OCR correction."""
    
    def __init__(self, db_connection=None, enable_epub_matching=True):
        self.processor_type = "enhanced_highlight_extractor_v2"
        self.db_connection = db_connection
        self.enable_epub_matching = enable_epub_matching
        
        # More lenient filtering since we'll clean up with EPUB matching
        self.min_text_length = 5
        self.text_threshold = 0.25  # More lenient
        self.min_words = 1
        self.symbol_ratio_threshold = 0.6  # More lenient
        
        # EPUB matching settings
        self.min_similarity = 0.5  # Slightly lower threshold
        self.merge_distance = 50
        
        self._document_cache: Dict[str, any] = {}
        
        # Enhanced unwanted patterns
        self.unwanted_patterns = {
            "reMarkable .lines file, version=6",
            "reMarkable .lines file, version=3",
            "Layer 1<", "Layer 2<", "Layer 3<", "Layer 4<", "Layer 5<"
        }
        
        self.unwanted_substrings = [
            "Layer 1<", "Layer 2<", "Layer 3<", "Layer 4<", "Layer 5<",
            ".lines file", "remarkable", "version="
        ]
        
        mode = "with enhanced EPUB matching" if enable_epub_matching else "basic mode"
        logger.info(f"Enhanced HighlightExtractor v2 initialized {mode}")
        logger.info(f"  OCR error correction: Enhanced (D→fi, :→ff, etc.)")
        logger.info(f"  Text preprocessing: Improved ligature handling")
        logger.info(f"  Performance: Optimized with word indexing")
    
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
            
            if not self.enable_epub_matching:
                return True
            
            # Check for EPUB file
            epub_path = self._find_epub_file(file_path)
            return epub_path is not None
            
        except Exception as e:
            logger.warning(f"Could not check file {file_path}: {e}")
            return False
    
    def _find_epub_file(self, content_file_path: str) -> Optional[str]:
        """Find corresponding EPUB file."""
        content_path = Path(content_file_path)
        base_name = content_path.stem
        
        # Look for exact match first
        exact_epub = content_path.parent / f"{base_name}.epub"
        if exact_epub.exists():
            return str(exact_epub)
        
        # Look for similar names
        parent_dir = content_path.parent
        for epub_file in parent_dir.glob("*.epub"):
            if base_name in epub_file.stem or epub_file.stem in base_name:
                logger.info(f"Found similar EPUB: {epub_file}")
                return str(epub_file)
        
        logger.warning(f"No EPUB found for {content_file_path}")
        return None
    
    def process_file(self, file_path: str):
        """Process file with enhanced OCR correction."""
        try:
            start_time = time.time()
            logger.info(f"Processing with enhanced OCR correction: {file_path}")
            
            # Extract raw highlights
            raw_highlights = self._extract_raw_highlights(file_path)
            
            if not raw_highlights:
                logger.info(f"No raw highlights found in {file_path}")
                return self._create_result(True, file_path, [])
            
            logger.info(f"Extracted {len(raw_highlights)} raw highlights")
            
            # EPUB processing
            epub_extractor = None
            if self.enable_epub_matching:
                epub_path = self._find_epub_file(file_path)
                if epub_path:
                    logger.info(f"Loading EPUB with optimized extractor: {epub_path}")
                    epub_extractor = ImprovedEPUBTextExtractor(epub_path)
                    
                    if not epub_extractor.full_text:
                        logger.warning("Could not extract EPUB text - falling back to basic mode")
                        epub_extractor = None
                else:
                    logger.warning("No EPUB found - using basic processing")
            
            # Enhance highlights
            if epub_extractor:
                enhanced_highlights = self._enhance_highlights_v2(raw_highlights, epub_extractor, file_path)
            else:
                # Fallback without EPUB correction but with OCR preprocessing
                enhanced_highlights = self._enhance_highlights_without_epub(raw_highlights, file_path)
            
            # Merge adjacent highlights
            merged_highlights = self._merge_adjacent_highlights(enhanced_highlights)
            
            processing_time = time.time() - start_time
            logger.info(f"Enhanced processing completed in {processing_time:.1f}s: {len(merged_highlights)} passages from {len(raw_highlights)} raw highlights")
            
            # Store in database
            if self.db_connection and merged_highlights:
                self._store_enhanced_highlights(merged_highlights, file_path)
            
            return self._create_result(True, file_path, merged_highlights)
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return self._create_result(False, file_path, [], str(e))
    
    def _enhance_highlights_v2(self, raw_highlights: List[RawHighlight], 
                              epub_extractor: ImprovedEPUBTextExtractor, file_path: str) -> List[EnhancedHighlight]:
        """Enhanced highlighting with improved OCR correction."""
        enhanced_highlights = []
        doc_info = self._load_document_info(file_path)
        
        total_highlights = len(raw_highlights)
        logger.info(f"🔍 Enhancing {total_highlights} highlights with improved EPUB matching...")
        
        start_time = time.time()
        max_time_per_highlight = 2.0  # Reduced timeout
        max_total_time = 45.0  # Reduced total timeout
        
        for i, raw_highlight in enumerate(raw_highlights):
            # Progress logging
            if i % 10 == 0 or i == total_highlights - 1:
                elapsed = time.time() - start_time
                progress = (i + 1) / total_highlights * 100
                logger.info(f"   Progress: {progress:.0f}% ({i+1}/{total_highlights}) - {elapsed:.1f}s elapsed")
            
            # Timeout check
            elapsed = time.time() - start_time
            if elapsed > max_total_time:
                logger.warning(f"⏰ Timeout reached - processing remaining highlights without EPUB matching")
                # Process remaining without EPUB matching
                for j in range(i, total_highlights):
                    remaining = raw_highlights[j]
                    enhanced = self._create_basic_enhanced_highlight(remaining, doc_info, j)
                    enhanced_highlights.append(enhanced)
                break
            
            highlight_start_time = time.time()
            
            # Try EPUB matching with improved algorithm
            match_result = None
            try:
                match_result = epub_extractor.find_best_match_optimized(raw_highlight.text, self.min_similarity)
                
                highlight_elapsed = time.time() - highlight_start_time
                if highlight_elapsed > max_time_per_highlight:
                    logger.debug(f"  ⏰ Highlight {i+1} took {highlight_elapsed:.1f}s")
                
            except Exception as e:
                logger.debug(f"  ❌ EPUB matching error for highlight {i+1}: {e}")
                match_result = None
            
            if match_result:
                corrected_text, match_score, position = match_result
                logger.debug(f"  ✅ Enhanced highlight {i+1} (score: {match_score:.2f})")
                
                enhanced = EnhancedHighlight(
                    original_text=raw_highlight.text,
                    corrected_text=corrected_text,
                    page_number=raw_highlight.page_number,
                    file_name=raw_highlight.file_name,
                    title=doc_info.title,
                    passage_id=i,
                    confidence=raw_highlight.confidence,
                    match_score=match_score,
                    correction_applied=True
                )
            else:
                # Apply OCR preprocessing even without EPUB match
                logger.debug(f"  🔧 OCR preprocessing for highlight {i+1}")
                enhanced = self._create_preprocessed_highlight(raw_highlight, doc_info, i)
            
            enhanced_highlights.append(enhanced)
        
        total_elapsed = time.time() - start_time
        corrected_count = sum(1 for h in enhanced_highlights if h.correction_applied)
        logger.info(f"🎯 Enhancement completed in {total_elapsed:.1f}s: {corrected_count}/{total_highlights} highlights corrected via EPUB")
        
        return enhanced_highlights
    
    def _enhance_highlights_without_epub(self, raw_highlights: List[RawHighlight], file_path: str) -> List[EnhancedHighlight]:
        """Enhance highlights using OCR preprocessing only (no EPUB)."""
        enhanced_highlights = []
        doc_info = self._load_document_info(file_path)
        
        logger.info(f"🔧 Applying OCR preprocessing to {len(raw_highlights)} highlights...")
        
        for i, raw_highlight in enumerate(raw_highlights):
            enhanced = self._create_preprocessed_highlight(raw_highlight, doc_info, i)
            enhanced_highlights.append(enhanced)
        
        logger.info(f"✅ OCR preprocessing completed for {len(enhanced_highlights)} highlights")
        return enhanced_highlights
    
    def _create_preprocessed_highlight(self, raw_highlight: RawHighlight, doc_info: DocumentInfo, passage_id: int) -> EnhancedHighlight:
        """Create enhanced highlight with OCR preprocessing applied."""
        # Apply OCR error correction
        corrected_text = self._preprocess_ocr_text(raw_highlight.text)
        correction_applied = corrected_text != raw_highlight.text
        
        if correction_applied:
            logger.debug(f"  🔧 OCR correction: '{raw_highlight.text}' → '{corrected_text}'")
        
        return EnhancedHighlight(
            original_text=raw_highlight.text,
            corrected_text=corrected_text,
            page_number=raw_highlight.page_number,
            file_name=raw_highlight.file_name,
            title=doc_info.title,
            passage_id=passage_id,
            confidence=raw_highlight.confidence * (0.9 if correction_applied else 0.7),
            match_score=0.8 if correction_applied else 0.0,
            correction_applied=correction_applied
        )
    
    def _create_basic_enhanced_highlight(self, raw_highlight: RawHighlight, doc_info: DocumentInfo, passage_id: int) -> EnhancedHighlight:
        """Create basic enhanced highlight without processing."""
        return EnhancedHighlight(
            original_text=raw_highlight.text,
            corrected_text=raw_highlight.text,
            page_number=raw_highlight.page_number,
            file_name=raw_highlight.file_name,
            title=doc_info.title,
            passage_id=passage_id,
            confidence=raw_highlight.confidence * 0.6,  # Lower confidence
            match_score=0.0,
            correction_applied=False
        )
    
    def _preprocess_ocr_text(self, text: str) -> str:
        """Preprocess OCR text to fix common errors (same as in EPUB extractor)."""
        # Use the same preprocessing as in ImprovedEPUBTextExtractor
        epub_extractor = ImprovedEPUBTextExtractor.__new__(ImprovedEPUBTextExtractor)
        return epub_extractor._preprocess_ocr_text(text)
    
    # [Include all the other methods from the original enhanced extractor: _extract_raw_highlights, 
    # _load_document_info, _find_rm_files, etc. - they remain largely the same]
    
    def _extract_raw_highlights(self, file_path: str) -> List[RawHighlight]:
        """Extract raw highlights using existing logic."""
        try:
            doc_info = self._load_document_info(file_path)
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
        
        cache_key = str(content_file_path)
        if cache_key in self._document_cache:
            return self._document_cache[cache_key]
        
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
            with open(rm_file_path, 'rb') as f:
                binary_content = f.read()
            
            raw_text = self._extract_ascii_text(binary_content)
            cleaned_text = self._clean_extracted_text(raw_text)
            
            if not cleaned_text:
                return []
            
            file_id = Path(rm_file_path).stem
            page_number = doc_info.page_mappings.get(file_id, "Unknown")
            
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
            cleaned_text = text.replace("l!", "").strip()
            
            if not cleaned_text:
                continue
            
            if cleaned_text in self.unwanted_patterns:
                continue
            
            contains_unwanted = False
            for unwanted_substring in self.unwanted_substrings:
                if unwanted_substring in cleaned_text:
                    contains_unwanted = True
                    break
            
            if contains_unwanted:
                continue
            
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
        
        if len(text) < 20:
            score *= 0.8
        
        if text.endswith('.') or text.endswith('!') or text.endswith('?'):
            score *= 1.1
        
        if not self._has_low_symbol_ratio(text):
            score *= 0.7
        
        return min(score, 1.0)
    
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
            
            should_merge = self._should_merge_highlights(previous, current)
            
            if should_merge:
                current.passage_id = passage_id
                current_group.append(current)
            else:
                if len(current_group) > 1:
                    merged_highlight = self._merge_highlight_group(current_group)
                    merged.append(merged_highlight)
                else:
                    merged.append(current_group[0])
                
                passage_id += 1
                current.passage_id = passage_id
                current_group = [current]
        
        if len(current_group) > 1:
            merged_highlight = self._merge_highlight_group(current_group)
            merged.append(merged_highlight)
        else:
            merged.append(current_group[0])
        
        logger.info(f"Merged {len(highlights)} highlights into {len(merged)} passages")
        return merged
    
    def _should_merge_highlights(self, h1: EnhancedHighlight, h2: EnhancedHighlight) -> bool:
        """Determine if two highlights should be merged."""
        if h1.page_number == h2.page_number:
            return True
        
        try:
            p1 = int(h1.page_number) if h1.page_number.isdigit() else 0
            p2 = int(h2.page_number) if h2.page_number.isdigit() else 0
            if abs(p1 - p2) <= 1:
                text1 = h1.corrected_text.strip()
                text2 = h2.corrected_text.strip()
                
                if (not text1.endswith(('.', '!', '?')) and 
                    text2 and not text2[0].isupper()):
                    return True
        except:
            pass
        
        return False
    
    def _merge_highlight_group(self, group: List[EnhancedHighlight]) -> EnhancedHighlight:
        """Merge a group of highlights into a single passage."""
        combined_text = ' '.join(h.corrected_text for h in group)
        combined_original = ' '.join(h.original_text for h in group)
        
        combined_text = re.sub(r'\s+', ' ', combined_text).strip()
        combined_original = re.sub(r'\s+', ' ', combined_original).strip()
        
        first = group[0]
        
        avg_confidence = sum(h.confidence for h in group) / len(group)
        avg_match_score = sum(h.match_score for h in group) / len(group)
        
        pages = [h.page_number for h in group]
        page_range = pages[0] if len(set(pages)) == 1 else f"{min(pages)}-{max(pages)}"
        
        correction_applied = any(h.correction_applied for h in group)
        
        return EnhancedHighlight(
            original_text=combined_original,
            corrected_text=combined_text,
            page_number=page_range,
            file_name=first.file_name,
            title=first.title,
            passage_id=first.passage_id,
            confidence=avg_confidence,
            match_score=avg_match_score,
            correction_applied=correction_applied
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
                CREATE TABLE IF NOT EXISTS enhanced_highlights_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_file TEXT NOT NULL,
                    title TEXT NOT NULL,
                    original_text TEXT NOT NULL,
                    corrected_text TEXT NOT NULL,
                    page_number TEXT,
                    file_name TEXT,
                    passage_id INTEGER,
                    confidence REAL,
                    match_score REAL,
                    correction_applied BOOLEAN,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_file, corrected_text, page_number) ON CONFLICT IGNORE
                )
            ''')
            
            # Clear existing highlights for this source
            cursor.execute('DELETE FROM enhanced_highlights_v2 WHERE source_file = ?', (source_file,))
            
            # Insert enhanced highlights
            for highlight in highlights:
                cursor.execute('''
                    INSERT INTO enhanced_highlights_v2 
                    (source_file, title, original_text, corrected_text, page_number, 
                     file_name, passage_id, confidence, match_score, correction_applied)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    source_file, highlight.title, highlight.original_text,
                    highlight.corrected_text, highlight.page_number, highlight.file_name,
                    highlight.passage_id, highlight.confidence, highlight.match_score,
                    highlight.correction_applied
                ))
            
            self.db_connection.commit()
            corrected_count = sum(1 for h in highlights if h.correction_applied)
            logger.info(f"💾 Stored {len(highlights)} enhanced highlights ({corrected_count} corrected)")
            
        except Exception as e:
            logger.error(f"Error storing enhanced highlights: {e}")


# Utility functions for standalone usage and testing

def process_directory_enhanced_v2(directory_path: str, db_manager=None, enable_epub_matching: bool = True) -> Dict[str, int]:
    """
    Process directory with enhanced v2 highlight extraction.
    
    Returns:
        Dictionary mapping content files to enhanced passage counts
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
        
        db_manager = SimpleDBManager("enhanced_highlights_v2.db")
    
    results = {}
    
    try:
        conn = db_manager.get_connection()
        extractor = EnhancedHighlightExtractorV2(conn, enable_epub_matching)
        
        mode = "with enhanced EPUB matching v2" if enable_epub_matching else "basic mode v2"
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
                        logger.info(f"⏭️ Skipping: {os.path.basename(file_path)} (cannot process)")
                        results[file_path] = 0
        
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Error in process_directory_enhanced_v2: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python enhanced_highlight_extractor_v2.py <directory_path> [--fast]")
        print("  directory_path: Directory containing .content files and .epub files")
        print("  --fast: Skip EPUB matching for faster processing")
        sys.exit(1)
    
    directory_path = sys.argv[1]
    fast_mode = len(sys.argv) > 2 and '--fast' in sys.argv
    
    print("🚀 Enhanced Highlight Extraction v2")
    print("=" * 50)
    print("🔧 Features: Improved OCR correction (D→fi, :→ff)")
    print("⚡ Performance: Optimized EPUB matching")
    print("🎯 Quality: Better fuzzy text alignment")
    print()
    
    if fast_mode:
        print("⚡ Fast mode enabled - skipping EPUB matching")
        results = process_directory_enhanced_v2(directory_path, enable_epub_matching=False)
    else:
        results = process_directory_enhanced_v2(directory_path, enable_epub_matching=True)
    
    total_passages = sum(results.values())
    processed_files = len([count for count in results.values() if count > 0])
    
    print(f"\n🎉 Enhanced processing v2 complete!")
    print(f"   Files processed: {len(results)}")
    print(f"   Files with passages: {processed_files}")
    print(f"   Total enhanced passages: {total_passages}")
    
    if total_passages > 0:
        print(f"\n📄 Results by file:")
        for file_path, count in results.items():
            if count > 0:
                file_name = os.path.basename(file_path)
                print(f"   {file_name}: {count} passages")