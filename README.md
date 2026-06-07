# reMarkable Integration

Transform your handwritten reMarkable notes into searchable digital text with AI-powered OCR that rivals human transcription accuracy.

## ✨ Revolutionary Features

### Core OCR & Processing
- **🤖 AI-Powered Handwriting OCR**: Google Gemini Vision reads cursive writing with human-level accuracy
- **🎨 Configurable OCR Prompts**: Customize the model's behavior for domain-specific handwriting
- **📅 Smart Date Recognition**: Automatically detects your date annotations and organizes content chronologically
- **📝 Perfect Markdown Output**: Preserves formatting, arrows (→), bullets (•), and structure
- **🔄 Complete Automation**: .rm files → SVG → PDF → AI transcription → searchable text
- **🌍 Multi-language Support**: Seamlessly handles mixed-language notes
- **🎯 Symbol Recognition**: Arrows, bullets, checkboxes, and custom notation
- **📊 Multiple Export Formats**: Markdown, JSON, CSV with page organization
- **✨ PDF Text Matching**: Recovers clean text from corrupted highlights with fuzzy matching and sentence expansion

### Smart Integrations
- **✅ Smart Todo Extraction**: Automatically extracts checkboxes and syncs to Notion with page links
- **📓 Notion Sync**: Real-time sync with per-page tracking, rate limiting, and intelligent updates
- **📚 Readwise Integration**: Sync highlights from PDF/EPUB annotations directly to Readwise
- **🔄 Unified Sync Architecture**: Event-driven change tracking across all integrations
- **⚡ Real-Time Watching**: File watcher with auto-sync to Notion and intelligent change detection

## Prerequisites

Before running on a new machine, make sure these are in place:

| Requirement | Notes |
|---|---|
| **Python 3.12** | 3.11–3.13 work; 3.14 is not yet supported (some dependencies have no wheels for it). |
| **[Poetry](https://python-poetry.org/)** | Manages the virtualenv and dependencies (`poetry install`). |
| **`rsvg-convert`** (from **librsvg**) | **Required.** Pages render `.rm → SVG → PDF → OCR`, and the SVG→PDF step shells out to `rsvg-convert`. **If it's missing, OCR silently produces nothing** (pages fail to render before reaching the model). |
| **Google (Gemini) API key** | Used for handwriting OCR. Create one at <https://aistudio.google.com/app/apikey> (keys start with `AIza`). |

Install the system dependency:

```bash
# macOS
brew install librsvg

# Debian / Ubuntu
sudo apt-get install -y librsvg2-bin
```

Provide the Gemini API key (stored in the OS keychain), or set `GOOGLE_API_KEY` / `GEMINI_API_KEY` in the environment:

```bash
poetry run python -m src.cli.main config api-key set --service google
```

> **Using Notion or Readwise sync?** You'll also need those API tokens — see the
> [Notion integration guide](docs/notion-integration.md). Note: the **Notion token
> must be reachable via the OS keychain or the `NOTION_API_TOKEN` environment
> variable** for the live watcher's sync to pick it up — a token placed only in
> `config.yaml` is not used by the unified sync path.

## Quick Start

```bash
# Install dependencies  
poetry install

# Set up your Google (Gemini) API key securely
poetry run python -m src.cli.main config api-key set --service google

# 🆕 UNIFIED: Process everything at once - handwritten notes + PDF/EPUB highlights
# Automatically updates metadata for fresh folder structure and timestamps
poetry run python -m src.cli.main process-all "/path/to/remarkable/data" \
  --output-dir "extracted_notes" \
  --export-highlights "highlights.csv"

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
- **[Notion Integration](docs/notion-integration.md)** - Real-time sync with per-page tracking
- **[File Watching System](docs/watching-system.md)** - Automated real-time processing
- **[Highlight Extraction](docs/highlight_extraction.md)** - PDF text matching and highlight processing

## 🚀 Advanced Features

### Text Extraction & OCR
- **Gemini Vision OCR**: Superior handwriting recognition using Google Gemini 2.5 Flash
- **Date Annotation Recognition**: Automatically detects your "lying L" date patterns in note corners
- **Configurable Prompts**: Custom OCR prompts in `config/prompts/ocr_default.txt`
- **Blank Page Filtering**: Automatically skips blank placeholder pages
- **Secure API Key Management**: Encrypted storage with keychain integration
- **Batch Processing**: Handle entire notebook collections automatically

### Notion Integration
- **Per-Page Sync Tracking**: Granular sync records track each page individually
- **Rate Limiting**: 50 pages/sync with 0.35s delays to respect Notion API limits
- **Priority Syncing**: New pages sync before backlog pages
- **Descending Page Order**: Latest pages appear first in Notion
- **Intelligent Updates**: Only syncs pages that have actually changed
- **Todo Linking**: Extracted todos link back to source pages in Notion

### Readwise Integration
- **Highlight Sync**: Automatically sync PDF/EPUB highlights to Readwise
- **Book Metadata**: Extracts author, publisher, publication date
- **Cover Images**: Automatically downloads and stores book covers

### PDF Text Matching for Highlights
- **Fuzzy Text Matching**: Recovers clean text from corrupted .rm highlight annotations
- **Character Recovery**: Automatically restores umlauts, accents, and special characters (ö→ö, ß→ß, é→é)
- **Sentence Expansion**: Expands text fragments to complete sentences with proper boundaries
- **Smart Page Mapping**: Searches ±2 pages to account for page number differences
- **High Accuracy**: 65% confidence threshold with 100% match rate on test data
- **EPUB Support**: Works with EPUBs using reMarkable's generated PDFs
- **No False Corrections**: Skips OCR for PDF-matched highlights to preserve accuracy

### System Architecture
- **Unified Sync**: Event-driven change tracking across all integrations
- **Database Integration**: Store and search extracted text with full metadata
- **Real-Time Watching**: File watcher with auto-sync to Notion
- **Incremental Processing**: Only processes changed content for efficiency

*Transform thousands of handwritten pages into searchable digital archives with seamless integrations in minutes.*