"""
PDF Text Matcher for Highlight Extraction

Matches corrupted/fragmented text from .rm files against clean PDF text
to recover the original highlighted text with proper formatting and characters.
"""

import re
import logging
from typing import Optional, Tuple, List
from pathlib import Path
from fuzzywuzzy import fuzz
import PyPDF2

logger = logging.getLogger(__name__)


class PDFTextMatcher:
    """Matches highlight text fragments against PDF source to get clean text."""

    def __init__(self, pdf_path: str, fuzzy_threshold: int = 70):
        """
        Initialize PDF text matcher.

        Args:
            pdf_path: Path to the PDF file
            fuzzy_threshold: Minimum fuzzy match score (0-100) to consider a match
        """
        self.pdf_path = Path(pdf_path)
        self.fuzzy_threshold = fuzzy_threshold
        self._page_cache = {}  # Cache extracted page text

        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Open PDF and get page count
        with open(self.pdf_path, 'rb') as f:
            self.reader = PyPDF2.PdfReader(f)
            self.total_pages = len(self.reader.pages)

        logger.debug(f"PDFTextMatcher initialized for {self.pdf_path.name} ({self.total_pages} pages)")

    def get_page_text(self, page_num: int) -> str:
        """
        Extract text from a specific PDF page (1-indexed).

        Args:
            page_num: Page number (1-indexed, like in PDF viewers)

        Returns:
            Extracted text from the page
        """
        if page_num < 1 or page_num > self.total_pages:
            logger.warning(f"Page {page_num} out of range (1-{self.total_pages})")
            return ""

        # Check cache
        if page_num in self._page_cache:
            return self._page_cache[page_num]

        # Extract and cache
        with open(self.pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            page = reader.pages[page_num - 1]  # Convert to 0-indexed
            text = page.extract_text()
            self._page_cache[page_num] = text
            return text

    def clean_pdf_text(self, text: str) -> str:
        """
        Clean PDF text by removing non-printable characters and normalizing whitespace.

        - Removes non-printable control characters (except newlines, tabs, carriage returns)
        - Replaces tabs and multiple spaces with single space
        """
        # Remove non-printable control characters (keep only newlines, tabs, carriage returns)
        # ASCII control characters are 0-31, except \n (10), \r (13), \t (9)
        text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\r\t')

        # Replace tabs and multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    def normalize_text(self, text: str) -> str:
        """
        Normalize text for fuzzy matching.

        - Removes extra whitespace
        - Converts to lowercase
        - Removes special formatting characters
        """
        # Replace tabs and multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        # Convert to lowercase for matching
        text = text.lower()
        # Strip leading/trailing whitespace
        text = text.strip()
        return text

    def find_text_in_page(self, search_text: str, page_num: int) -> Optional[Tuple[str, int, int, int]]:
        """
        Find corrupted text in a PDF page and return clean version.

        Args:
            search_text: The corrupted/fragmented text from .rm file
            page_num: PDF page number (1-indexed) to search

        Returns:
            Tuple of (clean_text, match_score, start_pos, end_pos) or None if not found
        """
        page_text = self.get_page_text(page_num)
        if not page_text:
            return None

        # Normalize both texts for comparison
        search_norm = self.normalize_text(search_text)
        page_norm = self.normalize_text(page_text)

        # Try exact match first (after normalization)
        if search_norm in page_norm:
            # Find position in normalized text
            start_pos = page_norm.index(search_norm)
            end_pos = start_pos + len(search_norm)

            # Map back to original text approximately
            clean_text = self._extract_original_text(page_text, start_pos, end_pos)
            # Clean non-printable characters
            clean_text = self.clean_pdf_text(clean_text)
            logger.debug(f"Exact match found on page {page_num}")
            return (clean_text, 100, start_pos, end_pos)

        # Try fuzzy matching with sliding window
        best_match = self._fuzzy_search(search_norm, page_text, page_norm)

        if best_match and best_match[1] >= self.fuzzy_threshold:
            logger.debug(f"Fuzzy match found on page {page_num} (score: {best_match[1]})")
            return best_match

        return None

    def _fuzzy_search(self, search_norm: str, original_text: str, normalized_text: str) -> Optional[Tuple[str, int, int, int]]:
        """
        Perform fuzzy search using sliding window.

        Returns best match if above threshold, with character positions.
        """
        search_words = search_norm.split()
        search_len = len(search_words)

        if search_len == 0:
            return None

        # Split normalized text into words
        norm_words = normalized_text.split()

        best_score = 0
        best_start_word = 0
        best_end_word = 0

        # Slide window across text
        for i in range(len(norm_words) - search_len + 1):
            window = ' '.join(norm_words[i:i+search_len])
            score = fuzz.ratio(search_norm, window)

            if score > best_score:
                best_score = score
                best_start_word = i
                best_end_word = i + search_len

        if best_score < self.fuzzy_threshold:
            # Try partial matching with longer window (highlight might be truncated)
            for window_size in [search_len + 5, search_len + 10]:
                for i in range(max(0, len(norm_words) - window_size + 1)):
                    window = ' '.join(norm_words[i:i+window_size])
                    score = fuzz.partial_ratio(search_norm, window)

                    if score > best_score:
                        best_score = score
                        best_start_word = i
                        best_end_word = i + window_size

        if best_score >= self.fuzzy_threshold:
            # Convert word positions to character positions
            char_start, char_end = self._word_positions_to_char_positions(
                original_text, best_start_word, best_end_word
            )
            clean_text = original_text[char_start:char_end].strip()
            # Clean non-printable characters and normalize whitespace
            clean_text = self.clean_pdf_text(clean_text)
            return (clean_text, best_score, char_start, char_end)

        return None

    def _word_positions_to_char_positions(self, text: str, start_word: int, end_word: int) -> Tuple[int, int]:
        """
        Convert word positions to character positions in the original text.

        Args:
            text: Original text
            start_word: Starting word index
            end_word: Ending word index (exclusive)

        Returns:
            Tuple of (start_char_pos, end_char_pos)
        """
        words = text.split()
        if start_word >= len(words):
            return (0, 0)

        end_word = min(end_word, len(words))

        # Find character position of start word
        char_pos = 0
        for i, word in enumerate(words):
            if i == start_word:
                start_char = char_pos
                break
            char_pos = text.find(word, char_pos) + len(word)
        else:
            start_char = 0

        # Find character position after end word
        if end_word >= len(words):
            end_char = len(text)
        else:
            char_pos = start_char
            for i in range(start_word, end_word):
                if i >= len(words):
                    break
                char_pos = text.find(words[i], char_pos) + len(words[i])
            end_char = char_pos

        return (start_char, end_char)

    def _extract_text_by_words(self, text: str, start_word: int, end_word: int) -> str:
        """Extract text by word indices from original text."""
        words = text.split()
        if start_word >= len(words):
            return ""
        end_word = min(end_word, len(words))
        return ' '.join(words[start_word:end_word])

    def _extract_original_text(self, original_text: str, start_char: int, end_char: int) -> str:
        """Extract text from original using character positions."""
        # This is approximate - try to find word boundaries
        return original_text[start_char:end_char].strip()

    def expand_to_sentence_boundaries(self, text: str, match_start: int, match_end: int) -> str:
        """
        Expand a text fragment to complete sentence boundaries.

        Args:
            text: Full page text
            match_start: Character position where match starts
            match_end: Character position where match ends

        Returns:
            Expanded text containing complete sentences
        """
        # Sentence ending punctuation (language-agnostic)
        sentence_ends = '.!?…'

        # Find sentence start (expand backwards)
        start = match_start
        while start > 0:
            # Check if previous character is sentence-ending punctuation
            if start > 0 and text[start - 1] in sentence_ends:
                # Check if followed by space or start of text
                if start >= len(text) or text[start].isspace() or text[start].isupper():
                    break
            start -= 1

        # Skip leading whitespace
        while start < len(text) and text[start].isspace():
            start += 1

        # Find sentence end (expand forward)
        end = match_end
        while end < len(text):
            if text[end] in sentence_ends:
                # Include the punctuation
                end += 1
                # Include any following whitespace and quotes/parenthesis
                trailing = set(['"', "'", ')', ']', '}', '»', '\u201c', '\u2019', ' ', '\t', '\n', '\r'])
                while end < len(text) and text[end] in trailing:
                    end += 1
                break
            end += 1

        expanded = text[start:end].strip()

        # Clean non-printable characters and normalize whitespace
        expanded = self.clean_pdf_text(expanded)

        logger.debug(f"Expanded fragment to full sentence(s): {len(expanded) - (match_end - match_start)} chars added")
        return expanded

    def match_highlight(self, corrupted_text: str, page_num: int, search_offset: int = 1, expand_sentences: bool = True) -> Optional[Tuple[str, int]]:
        """
        Match a corrupted highlight against PDF text and optionally expand to full sentences.

        Args:
            corrupted_text: Text extracted from .rm file (may be corrupted)
            page_num: Reported page number from reMarkable (may be off by 1)
            search_offset: Number of pages before/after to search (default: ±1)
            expand_sentences: Whether to expand fragments to complete sentences (default: True)

        Returns:
            Tuple of (clean_text, match_score) or None if no match found
        """
        # Try the exact page first
        result = self.find_text_in_page(corrupted_text, page_num)
        if result and expand_sentences:
            page_text = self.get_page_text(page_num)
            # Estimate character positions from word positions
            expanded = self.expand_to_sentence_boundaries(page_text, result[2], result[3])
            return (expanded, result[1])
        elif result:
            return (result[0], result[1])

        # Try nearby pages (page mapping might be off)
        for offset in range(1, search_offset + 1):
            # Try page+offset
            if page_num + offset <= self.total_pages:
                result = self.find_text_in_page(corrupted_text, page_num + offset)
                if result:
                    logger.debug(f"Found match on page {page_num + offset} (reported as {page_num})")
                    if expand_sentences:
                        page_text = self.get_page_text(page_num + offset)
                        expanded = self.expand_to_sentence_boundaries(page_text, result[2], result[3])
                        return (expanded, result[1])
                    return (result[0], result[1])

            # Try page-offset
            if page_num - offset >= 1:
                result = self.find_text_in_page(corrupted_text, page_num - offset)
                if result:
                    logger.debug(f"Found match on page {page_num - offset} (reported as {page_num})")
                    if expand_sentences:
                        page_text = self.get_page_text(page_num - offset)
                        expanded = self.expand_to_sentence_boundaries(page_text, result[2], result[3])
                        return (expanded, result[1])
                    return (result[0], result[1])

        logger.debug(f"No match found for text on page {page_num} (searched ±{search_offset} pages)")
        return None
