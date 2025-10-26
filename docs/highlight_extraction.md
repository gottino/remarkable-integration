# Highlight Extraction

This document explains how to use the highlight extraction feature.

## Overview
The highlight extractor processes reMarkable .content files (PDF/EPUB) and their associated .rm files to extract highlighted text.

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
- Extract highlights from PDF and EPUB annotations
- Map highlights to page numbers
- Quality filtering using text heuristics
- Database storage with confidence scoring
- Event system integration for downstream processing
- CSV export for backward compatibility

## Configuration
The highlight extractor uses these configuration options:

- `min_text_length`: Minimum ASCII sequence length (default: 10)
- `text_threshold`: Minimum ratio of alphabetic characters (default: 0.6)
- `min_words`: Minimum word count (default: 3)
- `symbol_ratio_threshold`: Maximum symbol-to-character ratio (default: 0.2)
