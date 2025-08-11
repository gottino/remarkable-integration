#!/usr/bin/env python3
"""
Debug version of highlight extractor to find why it's not matching the original method.
This version adds extensive logging to identify where the process fails.
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

# Set up detailed logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')
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
        if self.file_type not in ['pdf', 'epub']:
            raise ValueError(f"Unsupported file type: {self.file_type}")


class DebugHighlightExtractor:
    """Debug version with extensive logging."""
    
    def __init__(self, db_connection=None):
        self.processor_type = "debug_highlight_extractor"
        self.db_connection = db_connection
        
        # Make filtering MUCH more lenient for debugging
        self.min_text_length = 5  # Reduced from 10
        self.text_threshold = 0.3  # Reduced from 0.6 
        self.min_words = 1  # Reduced from 3
        self.symbol_ratio_threshold = 0.5  # Increased from 0.2
        
        self.unwanted_patterns = {
            "reMarkable .lines file, version=6",
            "reMarkable .lines file, version=3"
        }
        
        logger.info(f"🐛 Debug extractor initialized with lenient settings:")
        logger.info(f"   min_text_length: {self.min_text_length}")
        logger.info(f"   text_threshold: {self.text_threshold}")
        logger.info(f"   min_words: {self.min_words}")
        logger.info(f"   symbol_ratio_threshold: {self.symbol_ratio_threshold}")
    
    def debug_directory(self, directory_path: str):
        """Debug analysis of directory contents."""
        logger.info(f"🔍 DEBUG: Analyzing directory {directory_path}")
        
        # Find all .content files
        content_files = []
        for root, _, files in os.walk(directory_path):
            for file_name in files:
                if file_name.endswith('.content'):
                    file_path = os.path.join(root, file_name)
                    content_files.append(file_path)
        
        logger.info(f"📄 Found {len(content_files)} .content files:")
        for content_file in content_files:
            logger.info(f"   {content_file}")
        
        # Analyze each content file
        processable_files = []
        for content_file in content_files:
            can_process = self.can_process(content_file)
            if can_process:
                processable_files.append(content_file)
                logger.info(f"✅ Can process: {os.path.basename(content_file)}")
            else:
                logger.warning(f"❌ Cannot process: {os.path.basename(content_file)}")
        
        logger.info(f"📊 Summary: {len(processable_files)}/{len(content_files)} files are processable")
        
        # Process each file and show detailed results
        total_highlights = 0
        for content_file in processable_files:
            logger.info(f"\n🎯 PROCESSING: {os.path.basename(content_file)}")
            result = self.process_file_debug(content_file)
            if result.success:
                highlight_count = len(result.data.get('highlights', []))
                total_highlights += highlight_count
                logger.info(f"   ✅ Extracted {highlight_count} highlights")
            else:
                logger.error(f"   ❌ Failed: {result.error_message}")
        
        logger.info(f"\n🎉 TOTAL HIGHLIGHTS FOUND: {total_highlights}")
        return total_highlights
    
    def can_process(self, file_path: str) -> bool:
        """Check if file can be processed with detailed logging."""
        logger.debug(f"🔍 Checking if can process: {file_path}")
        
        if not file_path.endswith('.content'):
            logger.debug(f"   ❌ Not a .content file")
            return False
        
        if not os.path.exists(file_path):
            logger.debug(f"   ❌ File does not exist")
            return False
            
        try:
            with open(file_path, 'r') as f:
                content_data = json.load(f)
            
            file_type = content_data.get('fileType', '')
            logger.debug(f"   📋 File type: {file_type}")
            
            if file_type in ['pdf', 'epub']:
                logger.debug(f"   ✅ Supported file type")
                return True
            else:
                logger.debug(f"   ❌ Unsupported file type: {file_type}")
                return False
                
        except Exception as e:
            logger.debug(f"   ❌ Error reading content: {e}")
            return False
    
    def process_file_debug(self, file_path: str):
        """Process file with detailed debugging."""
        logger.info(f"🚀 DEBUG PROCESSING: {file_path}")
        
        try:
            # Step 1: Load document info
            logger.info("📖 Step 1: Loading document info...")
            doc_info = self._load_document_info_debug(file_path)
            logger.info(f"   Title: {doc_info.title}")
            logger.info(f"   Type: {doc_info.file_type}")
            logger.info(f"   Page mappings: {len(doc_info.page_mappings)}")
            
            # Step 2: Find RM files
            logger.info("📁 Step 2: Finding .rm files...")
            rm_files = self._find_rm_files_debug(doc_info)
            logger.info(f"   Found {len(rm_files)} .rm files")
            
            if not rm_files:
                logger.warning("   ⚠️ No .rm files found - this is likely the problem!")
                return type('Result', (), {
                    'success': True, 
                    'data': {'highlights': []}, 
                    'error_message': None
                })()
            
            # Step 3: Process each RM file
            logger.info("🔬 Step 3: Processing .rm files...")
            all_highlights = []
            
            for i, rm_file in enumerate(rm_files):
                logger.info(f"   Processing .rm file {i+1}/{len(rm_files)}: {os.path.basename(rm_file)}")
                highlights = self._extract_highlights_debug(rm_file, doc_info)
                all_highlights.extend(highlights)
                logger.info(f"     → Found {len(highlights)} highlights in this file")
            
            logger.info(f"🎯 FINAL RESULT: {len(all_highlights)} total highlights")
            
            # Show first few highlights
            if all_highlights:
                logger.info("📝 Sample highlights found:")
                for i, highlight in enumerate(all_highlights[:3]):
                    logger.info(f"   {i+1}. Page {highlight.page_number}: '{highlight.text[:60]}...'")
            
            return type('Result', (), {
                'success': True,
                'data': {'highlights': [h.to_dict() for h in all_highlights]},
                'error_message': None
            })()
            
        except Exception as e:
            logger.error(f"❌ Error in process_file_debug: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return type('Result', (), {
                'success': False,
                'data': {},
                'error_message': str(e)
            })()
    
    def _load_document_info_debug(self, content_file_path: str):
        """Load document info with debugging."""
        content_file_path = Path(content_file_path)
        logger.debug(f"📖 Loading document info from: {content_file_path}")
        
        # Load .content file
        with open(content_file_path, 'r') as f:
            content_data = json.load(f)
        
        file_type = content_data.get('fileType', '')
        content_id = content_file_path.stem
        
        logger.debug(f"   Content ID: {content_id}")
        logger.debug(f"   File type: {file_type}")
        
        # Load .metadata file
        metadata_file = content_file_path.parent / f"{content_id}.metadata"
        title = "Unknown Title"
        
        if metadata_file.exists():
            logger.debug(f"   Found metadata file: {metadata_file}")
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                title = metadata.get('visibleName', title)
                logger.debug(f"   Title from metadata: {title}")
            except Exception as e:
                logger.warning(f"   Could not read metadata: {e}")
        else:
            logger.warning(f"   No metadata file found: {metadata_file}")
        
        # Extract page mappings
        page_mappings = self._extract_page_mappings_debug(content_data)
        
        return DocumentInfo(
            content_id=content_id,
            title=title,
            file_type=file_type,
            page_mappings=page_mappings,
            content_file_path=str(content_file_path)
        )
    
    def _extract_page_mappings_debug(self, content_data: Dict) -> Dict[str, str]:
        """Extract page mappings with debugging."""
        logger.debug("🗺️ Extracting page mappings...")
        
        pages_data = content_data.get('cPages', {})
        logger.debug(f"   cPages structure: {type(pages_data)} with keys: {list(pages_data.keys()) if isinstance(pages_data, dict) else 'not a dict'}")
        
        pages_list = pages_data.get('pages', [])
        logger.debug(f"   Found pages list with {len(pages_list)} entries")
        
        page_mappings = {}
        for i, page in enumerate(pages_list):
            logger.debug(f"   Page {i}: {page}")
            if 'id' in page and 'redir' in page and 'value' in page['redir']:
                page_id = page['id']
                page_number = str(page['redir']['value'])
                page_mappings[page_id] = page_number
                logger.debug(f"     Mapped {page_id} → page {page_number}")
        
        logger.debug(f"   Total mappings: {len(page_mappings)}")
        return page_mappings
    
    def _find_rm_files_debug(self, doc_info: DocumentInfo) -> List[str]:
        """Find RM files with debugging."""
        logger.debug(f"📁 Looking for .rm files for document: {doc_info.content_id}")
        
        content_path = Path(doc_info.content_file_path)
        subdirectory = content_path.parent / doc_info.content_id
        
        logger.debug(f"   Expected subdirectory: {subdirectory}")
        logger.debug(f"   Subdirectory exists: {subdirectory.exists()}")
        
        if not subdirectory.exists():
            logger.warning(f"   ❌ Subdirectory does not exist!")
            return []
        
        # List all files in subdirectory
        all_files = list(subdirectory.iterdir())
        logger.debug(f"   Files in subdirectory ({len(all_files)}):")
        for file_path in all_files:
            logger.debug(f"     {file_path.name} ({'directory' if file_path.is_dir() else 'file'})")
        
        # Find .rm files
        rm_files = []
        rm_candidates = [f for f in all_files if f.suffix == '.rm']
        logger.debug(f"   Found {len(rm_candidates)} .rm candidates")
        
        for file_path in rm_candidates:
            # Check for corresponding metadata JSON
            json_file = subdirectory / f"{file_path.stem}-metadata.json"
            has_json = json_file.exists()
            
            logger.debug(f"   {file_path.name}: has_json={has_json}")
            
            if has_json:
                logger.debug(f"     ⏭️ Skipping (has metadata JSON)")
            else:
                logger.debug(f"     ✅ Including (no metadata JSON)")
                rm_files.append(str(file_path))
        
        logger.debug(f"   Final .rm files to process: {len(rm_files)}")
        return rm_files
    
    def _extract_highlights_debug(self, rm_file_path: str, doc_info: DocumentInfo) -> List[Highlight]:
        """Extract highlights with extensive debugging."""
        logger.debug(f"🔬 Processing .rm file: {os.path.basename(rm_file_path)}")
        
        try:
            # Read binary content
            with open(rm_file_path, 'rb') as f:
                binary_content = f.read()
            
            logger.debug(f"   Binary content size: {len(binary_content)} bytes")
            
            # Extract ASCII text
            raw_texts = self._extract_ascii_text_debug(binary_content)
            logger.debug(f"   Raw ASCII sequences found: {len(raw_texts)}")
            
            # Clean text
            cleaned_texts = self._clean_extracted_text_debug(raw_texts)
            logger.debug(f"   After cleaning: {len(cleaned_texts)} texts")
            
            if not cleaned_texts:
                logger.debug(f"   ❌ No cleaned text survived filtering")
                return []
            
            # Get page number
            file_id = Path(rm_file_path).stem
            page_number = doc_info.page_mappings.get(file_id, "Unknown")
            logger.debug(f"   File ID {file_id} → Page {page_number}")
            
            # Create highlights
            highlights = []
            for i, text in enumerate(cleaned_texts):
                highlight = Highlight(
                    text=text,
                    page_number=page_number,
                    file_name=Path(rm_file_path).name,
                    title=doc_info.title
                )
                highlights.append(highlight)
                logger.debug(f"   Highlight {i+1}: '{text[:50]}...' (page {page_number})")
            
            return highlights
            
        except Exception as e:
            logger.error(f"   ❌ Error processing {rm_file_path}: {e}")
            return []
    
    def _extract_ascii_text_debug(self, binary_data: bytes) -> List[str]:
        """Extract ASCII with debugging."""
        pattern = rb'[ -~]{%d,}' % self.min_text_length
        ascii_sequences = re.findall(pattern, binary_data)
        
        logger.debug(f"   ASCII extraction: found {len(ascii_sequences)} sequences >= {self.min_text_length} chars")
        
        texts = [seq.decode('utf-8', errors='ignore') for seq in ascii_sequences]
        
        # Show first few raw extracts
        if texts:
            logger.debug(f"   Sample raw extracts:")
            for i, text in enumerate(texts[:3]):
                logger.debug(f"     {i+1}: '{text[:50]}...'")
        
        return texts
    
    def _clean_extracted_text_debug(self, text_list: List[str]) -> List[str]:
        """Clean text with debugging."""
        logger.debug(f"   🧹 Cleaning {len(text_list)} text sequences")
        
        cleaned_sentences = []
        filtering_stats = {
            'total': len(text_list),
            'empty_after_cleaning': 0,
            'unwanted_patterns': 0,
            'failed_text_ratio': 0,
            'failed_word_count': 0,
            'failed_symbol_ratio': 0,
            'passed': 0
        }
        
        for i, text in enumerate(text_list):
            original_text = text
            
            # Clean
            cleaned_text = text.replace("l!", "").strip()
            
            if not cleaned_text:
                filtering_stats['empty_after_cleaning'] += 1
                continue
            
            if cleaned_text in self.unwanted_patterns:
                filtering_stats['unwanted_patterns'] += 1
                continue
            
            # Apply heuristics with debugging
            if not self._is_mostly_text_debug(cleaned_text):
                filtering_stats['failed_text_ratio'] += 1
                continue
                
            if not self._has_enough_words_debug(cleaned_text):
                filtering_stats['failed_word_count'] += 1
                continue
                
            if not self._has_low_symbol_ratio_debug(cleaned_text):
                filtering_stats['failed_symbol_ratio'] += 1
                continue
            
            filtering_stats['passed'] += 1
            cleaned_sentences.append(cleaned_text)
            
            # Show successful extracts
            if filtering_stats['passed'] <= 3:
                logger.debug(f"   ✅ Passed filter {filtering_stats['passed']}: '{cleaned_text[:50]}...'")
        
        logger.debug(f"   📊 Filtering results: {filtering_stats}")
        return cleaned_sentences
    
    def _is_mostly_text_debug(self, text: str) -> bool:
        """Check text ratio with debugging."""
        if not text:
            return False
        letters = sum(c.isalpha() for c in text)
        ratio = letters / len(text)
        passed = ratio > self.text_threshold
        
        if not passed:
            logger.debug(f"     Failed text ratio: {ratio:.2f} <= {self.text_threshold} for '{text[:30]}...'")
        
        return passed
    
    def _has_enough_words_debug(self, text: str) -> bool:
        """Check word count with debugging."""
        word_count = len(text.split())
        passed = word_count >= self.min_words
        
        if not passed:
            logger.debug(f"     Failed word count: {word_count} < {self.min_words} for '{text[:30]}...'")
        
        return passed
    
    def _has_low_symbol_ratio_debug(self, text: str) -> bool:
        """Check symbol ratio with debugging."""
        if not text:
            return False
        symbols = sum(not c.isalnum() and not c.isspace() for c in text)
        ratio = symbols / len(text)
        passed = ratio < self.symbol_ratio_threshold
        
        if not passed:
            logger.debug(f"     Failed symbol ratio: {ratio:.2f} >= {self.symbol_ratio_threshold} for '{text[:30]}...'")
        
        return passed


def debug_comparison(directory_path: str):
    """Run debug comparison to find the issue."""
    logger.info("🐛🔍 STARTING DEBUG COMPARISON")
    logger.info("=" * 50)
    
    # Create debug extractor
    debug_extractor = DebugHighlightExtractor()
    
    # Run debug analysis
    total_found = debug_extractor.debug_directory(directory_path)
    
    logger.info(f"\n🎯 DEBUG COMPLETE: Found {total_found} highlights total")
    
    if total_found == 0:
        logger.error("\n❌ DEBUGGING RECOMMENDATIONS:")
        logger.error("1. Check if .content files are PDF/EPUB type")
        logger.error("2. Check if subdirectories exist for each .content file")
        logger.error("3. Check if .rm files exist without corresponding -metadata.json files")
        logger.error("4. Check if .rm files contain readable ASCII text")
        logger.error("5. Try even more lenient filtering settings")
    else:
        logger.info(f"\n✅ Debug version found highlights! The issue might be in:")
        logger.info("1. Filtering settings too strict in original version")
        logger.info("2. Database storage not working properly")
        logger.info("3. Different file processing logic")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python debug_highlight_extractor.py <directory_path>")
        sys.exit(1)
    
    directory_path = sys.argv[1]
    debug_comparison(directory_path)
