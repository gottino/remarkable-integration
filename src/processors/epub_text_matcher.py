"""
EPUB Text Matcher for Highlight Extraction

Matches text from PDFs (with artifacts) against clean EPUB source text
to eliminate PDF extraction artifacts like ligatures and encoding issues.
"""

import re
import logging
from typing import Optional, Tuple, List
from pathlib import Path
from fuzzywuzzy import fuzz
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class EPUBTextMatcher:
    """Matches PDF text (with artifacts) against clean EPUB source text."""

    def __init__(self, epub_path: str, fuzzy_threshold: int = 85):
        """
        Initialize EPUB text matcher.

        Args:
            epub_path: Path to the EPUB file
            fuzzy_threshold: Minimum fuzzy match score (0-100) to consider a match
        """
        self.epub_path = Path(epub_path)
        self.fuzzy_threshold = fuzzy_threshold
        self._full_text = None  # Cache for full extracted text
        self._text_length = 0

        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB not found: {epub_path}")

        logger.debug(f"EPUBTextMatcher initialized for {self.epub_path.name}")

    def _extract_full_text(self) -> str:
        """
        Extract all text content from the EPUB file.

        Returns:
            Full text content of the EPUB
        """
        if self._full_text is not None:
            return self._full_text

        logger.debug(f"Extracting text from EPUB: {self.epub_path.name}")

        try:
            book = epub.read_epub(str(self.epub_path))
            text_parts = []

            # Extract text from all document items
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    # Parse HTML content
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    # Remove script and style elements
                    for script in soup(["script", "style"]):
                        script.decompose()
                    # Get text
                    text = soup.get_text()
                    # Clean up whitespace
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    text = ' '.join(chunk for chunk in chunks if chunk)
                    text_parts.append(text)

            self._full_text = ' '.join(text_parts)
            self._text_length = len(self._full_text)
            logger.info(f"Extracted {self._text_length:,} characters from EPUB")

            return self._full_text

        except Exception as e:
            logger.error(f"Error extracting text from EPUB: {e}")
            raise

    def get_text_chunk(self, position_ratio: float, window_size: float = 0.10) -> Tuple[str, int]:
        """
        Extract a chunk of text around a position in the EPUB.

        Args:
            position_ratio: Position in the book as ratio (0.0 to 1.0)
            window_size: Size of window to extract (ratio of total book)

        Returns:
            Tuple of (text_chunk, start_position)
        """
        full_text = self._extract_full_text()

        # Calculate position
        center_pos = int(position_ratio * self._text_length)
        window_chars = int(window_size * self._text_length)

        # Calculate chunk boundaries
        start_pos = max(0, center_pos - window_chars // 2)
        end_pos = min(self._text_length, center_pos + window_chars // 2)

        chunk = full_text[start_pos:end_pos]

        logger.debug(f"Extracted {len(chunk):,} char chunk around position {position_ratio:.1%} "
                    f"(±{window_size:.1%} window)")

        return (chunk, start_pos)

    def normalize_text(self, text: str) -> str:
        """
        Normalize text for fuzzy matching.

        - Removes extra whitespace
        - Converts to lowercase
        """
        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        # Convert to lowercase
        text = text.lower()
        # Strip leading/trailing whitespace
        text = text.strip()
        return text

    def match_text_in_chunk(self, search_text: str, chunk: str, chunk_start_pos: int) -> Optional[Tuple[str, int, int, int]]:
        """
        Find PDF text in EPUB chunk and return clean version.

        Args:
            search_text: The PDF-extracted text (may have artifacts)
            chunk: EPUB text chunk to search in
            chunk_start_pos: Character position where chunk starts in full text

        Returns:
            Tuple of (clean_text, match_score, start_pos, end_pos) or None if not found
        """
        # Normalize both texts for comparison
        search_norm = self.normalize_text(search_text)
        chunk_norm = self.normalize_text(chunk)

        # Try exact match first (after normalization)
        if search_norm in chunk_norm:
            start_pos = chunk_norm.index(search_norm)
            end_pos = start_pos + len(search_norm)
            clean_text = chunk[start_pos:end_pos].strip()
            logger.debug(f"Exact match found in EPUB chunk")
            return (clean_text, 100, chunk_start_pos + start_pos, chunk_start_pos + end_pos)

        # Try fuzzy matching with sliding window
        best_match = self._fuzzy_search(search_norm, chunk, chunk_norm, chunk_start_pos)

        if best_match and best_match[1] >= self.fuzzy_threshold:
            logger.debug(f"Fuzzy match found in EPUB chunk (score: {best_match[1]})")
            return best_match

        return None

    def _fuzzy_search(self, search_norm: str, original_text: str, normalized_text: str, text_start_pos: int) -> Optional[Tuple[str, int, int, int]]:
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

        # Try partial matching with longer windows if needed
        if best_score < self.fuzzy_threshold:
            for window_size in [search_len + 5, search_len + 10, search_len + 20]:
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
            # Normalize whitespace
            clean_text = re.sub(r'\s+', ' ', clean_text)
            return (clean_text, best_score, text_start_pos + char_start, text_start_pos + char_end)

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

    def expand_to_sentence_boundaries(self, text: str, match_start: int, match_end: int) -> str:
        """
        Expand a text fragment to complete sentence boundaries.

        Args:
            text: Full text (or chunk)
            match_start: Character position where match starts
            match_end: Character position where match ends

        Returns:
            Expanded text containing complete sentences
        """
        # Sentence ending punctuation
        sentence_ends = '.!?…'

        # Find sentence start (expand backwards)
        start = match_start
        while start > 0:
            if start > 0 and text[start - 1] in sentence_ends:
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
                end += 1
                trailing = set(['"', "'", ')', ']', '}', '»', '\u201c', '\u2019', ' ', '\t', '\n', '\r'])
                while end < len(text) and text[end] in trailing:
                    end += 1
                break
            end += 1

        expanded = text[start:end].strip()
        # Normalize whitespace
        expanded = re.sub(r'\s+', ' ', expanded)

        logger.debug(f"Expanded to full sentence(s): {len(expanded) - (match_end - match_start)} chars added")
        return expanded

    def match_highlight(self, pdf_text: str, pdf_page: int, total_pdf_pages: int,
                       expand_sentences: bool = True, window_size: float = 0.10) -> Optional[Tuple[str, int]]:
        """
        Match PDF-extracted text against EPUB to get clean text.

        Args:
            pdf_text: Text extracted from PDF (may have artifacts)
            pdf_page: PDF page number where highlight appears
            total_pdf_pages: Total number of pages in PDF
            expand_sentences: Whether to expand fragments to complete sentences
            window_size: Size of EPUB window to search (ratio of total book)

        Returns:
            Tuple of (clean_text, match_score) or None if no match found
        """
        # Calculate position in book
        position_ratio = pdf_page / total_pdf_pages if total_pdf_pages > 0 else 0.5

        # Extract chunk from EPUB around this position
        chunk, chunk_start_pos = self.get_text_chunk(position_ratio, window_size)

        # Try to match PDF text in this chunk
        result = self.match_text_in_chunk(pdf_text, chunk, chunk_start_pos)

        if result:
            clean_text, score, start_pos, end_pos = result

            # Optionally expand to sentence boundaries
            if expand_sentences:
                # Get more context if needed for sentence expansion
                full_text = self._extract_full_text()
                # Make sure we have enough context
                context_start = max(0, start_pos - 500)
                context_end = min(len(full_text), end_pos + 500)
                context = full_text[context_start:context_end]
                # Adjust positions relative to context
                rel_start = start_pos - context_start
                rel_end = end_pos - context_start
                expanded = self.expand_to_sentence_boundaries(context, rel_start, rel_end)
                return (expanded, score)

            return (clean_text, score)

        # If no match in default window, try larger windows
        for larger_window in [0.15, 0.20, 0.30]:
            logger.debug(f"No match with {window_size:.1%} window, trying {larger_window:.1%}")
            chunk, chunk_start_pos = self.get_text_chunk(position_ratio, larger_window)
            result = self.match_text_in_chunk(pdf_text, chunk, chunk_start_pos)

            if result:
                clean_text, score, start_pos, end_pos = result

                if expand_sentences:
                    full_text = self._extract_full_text()
                    context_start = max(0, start_pos - 500)
                    context_end = min(len(full_text), end_pos + 500)
                    context = full_text[context_start:context_end]
                    rel_start = start_pos - context_start
                    rel_end = end_pos - context_start
                    expanded = self.expand_to_sentence_boundaries(context, rel_start, rel_end)
                    return (expanded, score)

                return (clean_text, score)

        logger.debug(f"No match found in EPUB (tried windows up to 30%)")
        return None
