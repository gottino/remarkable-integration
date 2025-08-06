#!/bin/bash

# Setup script to create the new directory structure and files
# Run this from your remarkable-pipeline root directory

echo "🚀 Setting up Highlight Extractor integration..."

# Create new directories
echo "📁 Creating directories..."
mkdir -p examples
mkdir -p scripts
mkdir -p tests
mkdir -p docs

# Create __init__.py files for new directories
touch examples/__init__.py
touch scripts/__init__.py

# Copy the main highlight extractor to the right location
echo "📄 Setting up highlight_extractor.py..."
echo "# Copy the highlight_extractor.py artifact content to: src/processors/highlight_extractor.py"

# Copy the updated events module
echo "📄 Setting up updated events.py..."
echo "# Copy the events_with_highlights artifact content to: src/core/events.py"

# Copy the example script
echo "📄 Setting up demo script..."
echo "# Copy the highlight_integration_example.py artifact content to: examples/highlight_extraction_demo.py"

# Copy the migration script  
echo "📄 Setting up migration script..."
echo "# Copy the migration_script artifact content to: scripts/migrate_highlights.py"

# Make scripts executable
chmod +x scripts/migrate_highlights.py
chmod +x examples/highlight_extraction_demo.py

# Create documentation
echo "📚 Creating documentation..."
cat > docs/highlight_extraction.md << 'EOF'
# Highlight Extraction

This document explains how to use the highlight extraction feature.

## Overview
The highlight extractor processes reMarkable .content files (PDF/EPUB) and their associated .rm files to extract highlighted text.

## Quick Start

### 1. Basic Usage
```python
from src.processors.highlight_extractor import HighlightExtractor, process_directory  
from src.core.database import DatabaseManager

# Initialize
db_manager = DatabaseManager("highlights.db")
results = process_directory("/path/to/remarkable/files", db_manager)

# Export to CSV
extractor = HighlightExtractor(db_manager)
extractor.export_highlights_to_csv("highlights.csv")
```

### 2. Interactive Demo
```bash
python examples/highlight_extraction_demo.py --interactive
```

### 3. Migration from extract_text.py
```bash
python scripts/migrate_highlights.py /path/to/files --compare
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
EOF

# Create example README
cat > examples/README.md << 'EOF'
# Examples

This directory contains example scripts and demonstrations.

## highlight_extraction_demo.py
Interactive demonstration of the highlight extraction system.

Usage:
```bash
# Interactive mode
python highlight_extraction_demo.py --interactive

# Process directory
python highlight_extraction_demo.py --directory /path/to/files

# Start file watcher  
python highlight_extraction_demo.py --watch

# Export highlights
python highlight_extraction_demo.py --export highlights.csv
```
EOF

# Create scripts README  
cat > scripts/README.md << 'EOF'
# Scripts

Utility scripts for the reMarkable pipeline.

## migrate_highlights.py
Migration tool to help transition from extract_text.py to the new highlight extractor.

Usage:
```bash
# Compare old vs new methods
python migrate_highlights.py /path/to/files --compare

# Migrate to new system
python migrate_highlights.py /path/