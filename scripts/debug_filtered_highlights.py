#!/usr/bin/env python3
"""
Debug script to see what highlights are being filtered out and why.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.processors.enhanced_highlight_extractor import EnhancedHighlightExtractor
import logging
import os

# Global variable to track current file being processed
current_rm_file = None

# Monkey-patch the extraction method to track current file
original_extract_from_single = EnhancedHighlightExtractor._extract_highlights_from_single_rm_file

def debug_extract_from_single(self, rm_file_path, doc_info):
    global current_rm_file
    current_rm_file = os.path.basename(rm_file_path)
    print(f"\n📄 Processing: {current_rm_file}")
    result = original_extract_from_single(self, rm_file_path, doc_info)
    print(f"   → Extracted {len(result)} highlight(s) from this file")
    return result

# Monkey-patch the filtering method to show what's being rejected
original_clean_extracted_text = EnhancedHighlightExtractor._clean_extracted_text

def debug_clean_extracted_text(self, text_list):
    """Debug version that shows what's being filtered"""
    global current_rm_file
    cleaned_sentences = []

    for text in text_list:
        # Remove "l!" sequences and strip whitespace
        cleaned_text = text.replace("l!", "").strip()
        if not cleaned_text:
            print(f"  ❌ [{current_rm_file}] REJECTED (empty): {repr(text[:50])}")
            continue

        # Skip exact unwanted patterns
        if cleaned_text in self.unwanted_patterns:
            print(f"  ❌ [{current_rm_file}] REJECTED (unwanted pattern match): {repr(cleaned_text[:80])}")
            continue

        # Skip text containing unwanted substrings
        contains_unwanted = False
        for unwanted_substring in self.unwanted_substrings:
            if unwanted_substring in cleaned_text:
                contains_unwanted = True
                break

        if contains_unwanted:
            print(f"  ❌ [{current_rm_file}] REJECTED (unwanted substring): {repr(cleaned_text[:80])}")
            continue

        # Check each quality filter
        if len(cleaned_text) < self.min_text_length:
            print(f"  ❌ [{current_rm_file}] REJECTED (too short, {len(cleaned_text)} < {self.min_text_length}): {repr(cleaned_text)}")
            continue

        if not self._is_mostly_text(cleaned_text):
            letters = sum(c.isalpha() for c in cleaned_text)
            ratio = letters / len(cleaned_text)
            print(f"  ❌ [{current_rm_file}] REJECTED (not enough letters, {ratio:.1%} < {self.text_threshold:.1%}): {repr(cleaned_text[:80])}")
            continue

        if not self._has_enough_words(cleaned_text):
            word_count = len(cleaned_text.split())
            print(f"  ❌ [{current_rm_file}] REJECTED (not enough words, {word_count} < {self.min_words}): {repr(cleaned_text[:80])}")
            continue

        if not self._has_low_symbol_ratio(cleaned_text):
            symbols = sum(not c.isalnum() and not c.isspace() for c in cleaned_text)
            ratio = symbols / len(cleaned_text)
            print(f"  ❌ [{current_rm_file}] REJECTED (too many symbols, {ratio:.1%} > {self.symbol_ratio_threshold:.1%}): {repr(cleaned_text[:80])}")
            continue

        if not self._has_no_excessive_consecutive_symbols(cleaned_text):
            print(f"  ❌ [{current_rm_file}] REJECTED (consecutive symbols > {self.max_consecutive_symbols}): {repr(cleaned_text[:80])}")
            continue

        print(f"  ✅ [{current_rm_file}] ACCEPTED: {repr(cleaned_text[:80])}")
        cleaned_sentences.append(cleaned_text)

    return cleaned_sentences

# Apply the monkey patches
EnhancedHighlightExtractor._extract_highlights_from_single_rm_file = debug_extract_from_single
EnhancedHighlightExtractor._clean_extracted_text = debug_clean_extracted_text

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

# Process the notebook in question
extractor = EnhancedHighlightExtractor()
content_file = '/Users/gabriele/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop/02c1d14f-5106-4f02-a699-9a6c97338180.content'

print("=" * 80)
print("PROCESSING NOTEBOOK WITH DEBUG OUTPUT")
print("=" * 80)

result = extractor.process_file(content_file)
print("\n" + "=" * 80)
print(f"FINAL RESULT: {len(result.data['highlights'])} highlights extracted")
print("=" * 80)
