# reMarkable Integration

Transform your handwritten reMarkable notes into searchable digital text with AI-powered OCR that rivals human transcription accuracy.

## ✨ Revolutionary Features

- **🤖 AI-Powered Handwriting OCR**: Claude Vision technology reads cursive writing with human-level accuracy
- **📅 Smart Date Recognition**: Automatically detects your date annotations and organizes content chronologically  
- **📝 Perfect Markdown Output**: Preserves formatting, arrows (→), bullets (•), and structure
- **🔄 Complete Automation**: .rm files → SVG → PDF → AI transcription → searchable text
- **🌍 Multi-language Support**: Seamlessly handles mixed-language notes
- **🎯 Symbol Recognition**: Arrows, bullets, checkboxes, and custom notation
- **📊 Multiple Export Formats**: Markdown, JSON, CSV with page organization
- **✅ Smart Todo Extraction**: Automatically extracts checkboxes into separate todo list

## Quick Start

```bash
# Install dependencies  
poetry install

# Set up your Claude API key securely
poetry run python -m src.cli.main config api-key set

# 🆕 UNIFIED: Process everything at once - handwritten notes + PDF/EPUB highlights
poetry run python -m src.cli.main process-all "/path/to/remarkable/data" \
  --output-dir "extracted_notes" \
  --export-highlights "highlights.csv" \
  --enhanced-highlights

# OR extract handwritten text only
poetry run python -m src.cli.main text extract "/path/to/remarkable/data" --output-dir "extracted_notes"

# Result: Perfect Markdown files + extracted highlights with chronological organization!
```

## 🎯 What You Get

**Input**: Handwritten reMarkable notebook pages
**Output**: 
```markdown
# Your Notebook

**Date: 21-09-2021**
---

## Meeting Notes
- Project timeline → Q2 launch
- Budget approval ✓
- Next steps:
  - [ ] Schedule review meeting
  - [x] Update documentation
```

## 📚 Documentation

- **[User Guide](docs/user-guide.md)** - Complete workflow and integration examples
- **[AI OCR Guide](docs/ai-ocr.md)** - Text extraction setup and optimization  
- **[CLI Reference](docs/cli-usage.md)** - Complete command-line documentation
- **[Highlight Extraction](docs/highlight_extraction.md)** - Legacy highlight processing

## 🚀 Advanced Features

- **Date Annotation Recognition**: Automatically detects your "lying L" date patterns in note corners
- **Multi-Engine OCR**: Falls back from Claude → EasyOCR → Enhanced Tesseract → Tesseract  
- **Secure API Key Management**: Encrypted storage with keychain integration
- **Batch Processing**: Handle entire notebook collections automatically
- **Database Integration**: Store and search extracted text with full metadata

*Transform thousands of handwritten pages into searchable digital archives in minutes.*