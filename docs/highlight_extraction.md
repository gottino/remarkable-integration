# Highlight Extraction

This document explains how to use the highlight extraction feature.

## Overview
The highlight extractor processes reMarkable .content files (PDF/EPUB) and their associated .rm files to extract highlighted text. It uses intelligent PDF text matching to recover clean text from corrupted reMarkable annotations.

## Quick Start

### 1. Basic Usage
```python
from src.processors.enhanced_highlight_extractor import EnhancedHighlightExtractor, process_directory_enhanced
from src.core.database import DatabaseManager

# Initialize
db_manager = DatabaseManager("highlights.db")
results = process_directory_enhanced("/path/to/remarkable/files", db_manager)

# Export to CSV
with db_manager.get_connection() as conn:
    extractor = EnhancedHighlightExtractor(conn)
    extractor.export_highlights_to_csv("highlights.csv")
```

### 2. Interactive Demo
```bash
python examples/highlight_extraction_demo.py --interactive
```

## Features

### PDF Text Matching (NEW)
The highlight extractor now uses intelligent PDF text matching to recover clean, properly formatted text from corrupted reMarkable annotations:

- **Fuzzy text matching**: Matches corrupted .rm highlight text against source PDF using sliding window algorithm
- **Character recovery**: Automatically restores corrupted special characters (ö→ö, ß→ß, é→é, etc.)
- **Sentence expansion**: Expands text fragments to complete sentences with proper boundaries
- **Smart page mapping**: Searches ±2 pages to account for reMarkable/PDF page number differences
- **High accuracy**: 65% confidence threshold with 100% match rate on test data
- **EPUB support**: Works with EPUB documents using reMarkable's generated PDF
- **Performance optimized**: Page-level caching and efficient fuzzy matching

### Example: Corrupted vs Clean Text

**Before (corrupted .rm text):**
```
rlich will ich es wissen, weil Sie es wissen es schon. Niemand wei ber sich. Nur Gott wei ber dich.
```

**After (PDF-matched clean text):**
```
»Natürlich will ich es wissen, weil Sie es wissen wollen.« »Ich weiß es schon.« »Niemand weiß irgendwas über sich. Nur Gott weiß alles über dich.
```

### How PDF Matching Works

1. **Extract corrupted text** from .rm file with page number
2. **Search PDF** on reported page ±2 pages (page numbers may differ)
3. **Fuzzy match** using normalized text (lowercase, whitespace cleaned)
4. **Expand to sentences** if fragment doesn't start/end at sentence boundaries
5. **Normalize whitespace** to clean up tabs and formatting
6. **Skip OCR** if PDF match successful (prevents false corrections)

### Other Features
- Extract highlights from PDF and EPUB annotations
- Map highlights to page numbers
- Quality filtering using text heuristics
- Database storage with confidence scoring
- Event system integration for downstream processing
- CSV export for backward compatibility

## Configuration

### PDF Text Matching
The PDF text matcher uses these settings:

- `fuzzy_threshold`: Minimum match confidence (default: 65%)
- `search_offset`: Pages to search before/after (default: ±2)
- `expand_sentences`: Expand fragments to full sentences (default: True)

### Highlight Extraction
The highlight extractor uses these configuration options:

- `min_text_length`: Minimum ASCII sequence length (default: 10)
- `text_threshold`: Minimum ratio of alphabetic characters (default: 0.6)
- `min_words`: Minimum word count (default: 3)
- `symbol_ratio_threshold`: Maximum symbol-to-character ratio (default: 0.2)

## Technical Details

### File Processing
The extractor processes .rm files efficiently:

- **Size filtering**: Skips files smaller than 100 bytes (empty/metadata-only files)
- **Metadata handling**: Processes .rm files even if they have metadata JSON files
- **Page caching**: Caches extracted PDF pages for performance

### Match Pipeline
Highlights go through a multi-stage pipeline:

1. **Extraction**: Parse .rm files for highlight annotations
2. **PDF Matching**: Match against source PDF (if available)
3. **OCR Correction**: Apply corrections to non-PDF-matched text (if needed)
4. **Quality Filtering**: Remove low-quality or blank highlights
5. **Database Storage**: Store with confidence scores and metadata

### Confidence Scores
- **1.0 (100%)**: Exact match or very high confidence fuzzy match
- **0.75-0.99**: Good fuzzy match from PDF
- **0.65-0.74**: Acceptable fuzzy match (may have minor differences)
- **<0.65**: No PDF match, falls back to OCR correction or original text
