# Changelog

All notable changes to the reMarkable Integration project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed - Readwise Sync Metadata Integration (2025-11-02)
- **Book metadata in sync**: Readwise sync now uses real book authors from `notebook_metadata` table instead of hardcoded "reMarkable"
- **Title cleanup**: Fixed book titles that incorrectly included author names
- **Utility scripts**: Created scripts for managing Readwise sync and duplicates
  - `scripts/fix_titles_with_authors.py`: Clean up titles with author suffixes
  - `scripts/fix_readwise_duplicates.py`: Clear sync records for re-syncing
  - `scripts/check_readwise_duplicates.py`: Identify duplicate books
  - `scripts/reprocess_highlights_with_epub_matching.py`: Batch re-extract EPUB highlights with text matching
- **File watcher integration**: File watcher now pulls book metadata (title, author, category) for automatic Readwise sync
- **Deduplication awareness**: Documented Readwise's title+author+source matching behavior for preventing duplicates

### Added - EPUB Text Matching for Artifact-Free Highlights (2025-10-30)
- **Two-stage matching pipeline**: First matches .rm → PDF, then PDF → EPUB for cleanest text
- **Eliminates PDF artifacts**: Removes ligatures and encoding issues (suHcient→sufficient, in^Yexible→inflexible)
- **Position-based windowing**: Searches ±10% of book around PDF page position for efficiency
- **Smart validation**: Rejects false matches (requires 70% similarity + 85% fuzzy score)
- **Automatic fallback**: Keeps PDF text if EPUB match fails or is rejected
- **EPUB-only feature**: Only processes EPUB documents, PDFs skip stage 2
- **Performance**: ~2x slower than PDF-only (~15-20 seconds for 19 highlights)
- **Non-printable character cleanup**: Removes control characters that caused hex display in DB Browser

### Added - PDF Text Matching for Highlights (2025-10-27)
- **Fuzzy text matching**: Matches corrupted .rm highlight text against source PDF to recover clean text
- **Sentence expansion**: Automatically expands fragments to complete sentences with proper boundaries
- **Character recovery**: Restores corrupted umlauts, special characters (ö→ö, ß→ß, etc.)
- **Smart page mapping**: Searches ±2 pages to account for reMarkable/PDF page number differences
- **Whitespace normalization**: Cleans up tabs and formatting from PDF extraction
- **High match rate**: 65% confidence threshold with 100% match rate on test data
- **Works with EPUBs**: Uses reMarkable's generated PDF for EPUB documents
- **No false corrections**: Skips OCR corrections for PDF-matched highlights
- **Performance optimized**: Page caching and efficient sliding window fuzzy matching

### Removed - OCR Engine Fallback (2025-10-27)
- **Removed EasyOCR dependency**: Deleted easyocr and pytesseract from pyproject.toml (~200MB saved)
- **Removed unused code**: Deleted 109 lines of commented SyncManager class
- **Removed integration_sync table**: Cleaned up obsolete database schema
- **Fixed hardcoded paths**: Database path now uses dependency injection
- **Cleaned debug logging**: Converted logger.info() to logger.debug() for cleaner output

### Refactored - Highlight Extraction (2025-10-27)
- **Single extractor**: Consolidated 4 highlight extractor versions into one (3,182 lines removed)
  - Deleted `enhanced_highlight_extractor_v2.py` (1,125 lines) - unused
  - Deleted `enhanced_highlight_extractor.py v1` (1,370 lines) - had abandoned EPUB matching
  - Deleted `highlight_extractor.py` (687 lines) - basic version superseded
- **Simplified CLI**: Removed `--enhanced` and `--compare` flags (one extractor = simpler interface)
- **Updated documentation**: Removed references to deleted flags in README and docs
- **Metadata file handling**: Now processes .rm files with metadata (previously skipped as notebooks)
- **Size filtering**: Efficiently skips empty .rm files (<100 bytes) for performance

### Removed - OCR Engine Fallback (2025-10-26)
- **Removed EasyOCR, Tesseract engines**: Deleted 4 OCR engine files (2,781 lines)
  - `tesseract_ocr_engine.py` (552 lines)
  - `enhanced_tesseract_ocr.py` (714 lines)
  - `pdf_ocr_engine.py` (699 lines)
  - `ocr_engine.py` (816 lines)
- **Claude Vision only**: System now uses Claude Vision OCR exclusively for superior handwriting recognition
- **Removed CLI commands**: Deleted obsolete `ocr directory`, `ocr file`, `ocr pdf-directory`, `ocr pdf-file` commands
- **Simplified export**: Removed `--ocr` flag from export command
- **Code cleanup**: Net reduction of 3,289 lines of code

### Added - Per-Page Sync Tracking (2025-10-20/21)
- **Per-page sync records**: Individual `page_sync_records` table tracks each page separately
- **Rate limiting**: 50 pages/sync with 0.35s delays to respect Notion API limits
- **Priority syncing**: New pages sync before backlog pages
- **Descending page order**: Latest pages appear first in Notion (468 → 467 → 466...)
- **Gap detection**: Automatically identifies pages missing from Notion
- **Backfill script**: `backfill_page_sync_records.py` to populate existing Notion pages
- **Content hashing**: SHA256 hashes detect actual content changes

### Added - Configurable OCR Prompts (2025-10-17)
- **Custom Claude prompts**: Edit `config/prompts/claude_ocr_default.txt` for domain-specific handwriting
- **Use cases**: Medical terminology, scientific notation, technical diagrams, foreign languages
- **Bullet conversion fixes**: Improved markdown formatting for bullet points

### Added - Blank Page Filtering (2025-10-17)
- **Automatic filtering**: Skips Claude's "blank page" placeholders
- **Performance improvement**: Reduces Notion API calls and sync time
- **Cleaner output**: Only syncs pages with actual content

### Added - Readwise Integration (2025-10-03)
- **Highlight sync**: Automatically syncs PDF/EPUB highlights to Readwise
- **Book metadata extraction**: Author, publisher, publication date from EPUB files
- **Cover image extraction**: Automatically downloads and stores book covers
- **Deduplication**: Prevents duplicate highlights in Readwise
- **Batch processing**: Initial sync support for existing highlights
- **Dual processing**: Separate pipelines for notebooks vs PDF/EPUB highlights

### Added - Last Viewed Property (2025-09-24)
- **Last Viewed property**: Maps reMarkable's last_opened to Notion's "Last Viewed"
- **Metadata refresh**: Automatic updates for path changes and timestamps

### Added - Unified Sync Architecture (2025-09-21)
- **Consolidated sync**: Unified architecture as the only sync method
- **Event-driven change tracking**: Centralized sync system across all integrations (2025-09-09)
- **Content-based detection**: Only syncs when actual content changes (2025-09-08)
- **Eliminates duplicate storage**: Single source of truth in database (2025-09-15)
- **Intelligent sync decisions**: Logs detailed reasons for sync/skip decisions

### Added - Todo Extraction and Sync (2025-09-18)
- **Automatic extraction**: Detects checkboxes in handwritten notes
- **Notion database integration**: Creates dedicated todo database
- **Page linking**: Todos include links back to source notebook pages (2025-09-12)
- **Intelligent deduplication**: Prevents duplicate todos when pages reprocess (2025-09-10)
- **Automated sync**: File watcher automatically syncs todos to Notion

### Added - Notion Integration Enhancements (2025-09-03/12)
- **Real-time automation**: Complete pipeline with intelligent sync (2025-09-03)
- **Block ID mapping**: Efficient reverse backfill for existing pages (2025-09-12)
- **Markdown formatting**: Enhanced formatting with proper block conversion (2025-08-29)
- **Incremental sync**: Only updates changed notebooks

### Added - Enhanced Metadata System (2025-08-27)
- **EPUB metadata extraction**: Author, publisher, publication date
- **Cover image detection**: Multiple strategies (filename, OPF manifest, largest image)
- **Notebook exclusion**: Configure patterns to skip template notebooks
- **Document type detection**: Automatic classification (notebook/PDF/EPUB)
- **Folder hierarchy**: Full path tracking for organization

### Added - File Watching System (2025-08-19)
- **Real-time monitoring**: Watches reMarkable directory for changes
- **Direct processing**: No intermediate copying, works directly from source
- **Two-tier architecture**: Sync + local processing
- **Auto-sync to Notion**: Automatically syncs changed notebooks
- **Debouncing**: Waits for changes to settle (5-second default)
- **Incremental updates**: Only processes changed pages

### Added - Smart Todo Extraction (2025-08-17)
- **Intelligent extraction**: Recognizes checkbox patterns in handwriting
- **Confidence tracking**: OCR confidence scores for each todo
- **Date association**: Links todos to page dates

### Added - Secure API Key Management (2025-08-15)
- **Keychain integration**: macOS/Windows secure storage
- **Encrypted file fallback**: Machine-specific encryption
- **Environment variables**: Alternative configuration method
- **No plain text**: API keys never stored in config files

## [1.0.0] - 2025-08-15

### Added - Core OCR System
- **Claude Vision OCR**: Human-level handwriting recognition
- **Date annotation detection**: Automatic "lying L" date pattern recognition
- **Multi-language support**: English, German, French, Spanish, Italian
- **Symbol recognition**: Arrows (→), bullets (•), checkboxes (☑)
- **Perfect Markdown output**: Preserves structure and formatting
- **Multiple export formats**: Markdown, JSON, CSV
- **Multi-engine fallback**: Claude → EasyOCR → Enhanced Tesseract → Tesseract

### Added - Database System
- **SQLite integration**: Store extracted text with full metadata
- **Incremental processing**: Page-level granularity with content hashing
- **Backup support**: Automatic database backups
- **Query interface**: Database stats, cleanup, and export commands

### Added - Configuration System
- **Secure API key management**: Keychain integration for macOS/Windows
- **Encrypted file storage**: Machine-specific encryption
- **Environment variables**: Fallback configuration method
- **YAML configuration**: Flexible config file structure
- **Notebook exclusion**: Skip specific notebooks by name or UUID

### Added - Notion Integration (Initial)
- **Database sync**: One Notion page per notebook
- **Toggle blocks**: Each page becomes collapsible section
- **Markdown formatting**: Headings, lists, checkboxes converted properly
- **Confidence indicators**: Visual OCR quality indicators (🟢🟡🔴)
- **Rich metadata**: Path, tags, timestamps from reMarkable
- **Intelligent incremental sync**: Only updates changed notebooks

### Added - CLI Interface
- **Text extraction**: `text extract` command for AI-powered OCR
- **Unified processing**: `process-all` for combined handwritten + highlights
- **Configuration management**: `config` commands for setup
- **Database operations**: Stats, backup, cleanup commands
- **Export functionality**: CSV export for highlights and text

## Security

### Added
- **Secure API key storage**: Keychain integration (macOS/Windows) and Secret Service (Linux)
- **Encrypted file fallback**: Machine-specific encryption for API keys
- **No keys in config**: API keys never stored in plain text configuration files
- **SSL handling**: Automatic SSL certificate handling for corporate networks

## Performance

### Optimizations
- **Incremental processing**: Only processes changed pages (not entire notebooks)
- **Content hashing**: Detects actual content changes, not just file modifications
- **Database indexing**: Optimized queries for change detection
- **Rate limiting**: Respects Notion API limits (3 requests/second)
- **Batch processing**: Groups operations for efficiency
- **Direct file processing**: No intermediate file copying

## [Backlog/Future]

### Planned Features
- Obsidian plugin integration
- Mobile app for iOS/Android
- Web dashboard for monitoring sync status
- Advanced search across all notebooks
- Custom export templates
- Multi-user support
- Cloud backup integration

---

## Version History Summary

- **1.0.0** (2025-08-15): Initial release with Claude Vision OCR, basic Notion sync, database system
- **1.1.0** (2025-08-19): File watching, EPUB metadata, enhanced Notion integration
- **1.2.0** (2025-09-08): Todo extraction, unified sync architecture
- **1.3.0** (2025-10-03): Readwise integration, dual processing
- **1.4.0** (2025-10-17): Configurable prompts, blank filtering
- **1.5.0** (2025-10-21): Per-page sync tracking, rate limiting, priority syncing

## Migration Guides

### Migrating to Per-Page Sync Tracking

If you have existing Notion pages synced before October 2025:

```bash
# Backfill sync records from existing Notion pages
poetry run python scripts/backfill_page_sync_records.py  # Dry run
poetry run python scripts/backfill_page_sync_records.py --live  # Actually backfill
```

This creates `page_sync_records` entries for all pages currently in Notion.

### Migrating to Unified Sync Architecture

The unified sync system is automatically enabled. No migration needed - the system creates necessary tables on first run.

---

For more details on any feature, see the [documentation](docs/).
