# CLI Usage Guide

The reMarkable Integration CLI provides a comprehensive command-line interface for processing reMarkable files, managing configuration, and working with extracted content.

## Installation & Setup

1. **Install dependencies:**
   ```bash
   poetry install
   ```

2. **Initialize configuration:**
   ```bash
   poetry run python -m src.cli.main config init
   ```

3. **Configure your reMarkable sync directory:**
   ```bash
   # Edit the generated config.yaml file
   nano config.yaml
   
   # Or initialize with sync directory directly
   poetry run python -m src.cli.main config init --sync-dir "/path/to/remarkable"
   ```

4. **Verify setup:**
   ```bash
   poetry run python -m src.cli.main config check
   ```

## Quick Reference

### Configuration Commands
```bash
# Initialize configuration file
poetry run python -m src.cli.main config init

# Check configuration for issues
poetry run python -m src.cli.main config check

# Show current configuration
poetry run python -m src.cli.main config show

# Show specific configuration section
poetry run python -m src.cli.main config show --section remarkable
```

### API Key Management Commands
```bash
# Set up API key securely (interactive)
poetry run python -m src.cli.main config api-key set

# Set API key with specific storage method
poetry run python -m src.cli.main config api-key set --method keychain
poetry run python -m src.cli.main config api-key set --method encrypted
poetry run python -m src.cli.main config api-key set --method auto

# Check API key status  
poetry run python -m src.cli.main config api-key get

# List all stored API keys
poetry run python -m src.cli.main config api-key list

# Remove stored API key
poetry run python -m src.cli.main config api-key remove
```

### ✨ Unified Processing Commands

> 🚀 **NEW**: Process both handwritten notes AND PDF/EPUB highlights in one command!

```bash
# Complete processing - handwritten notes + PDF/EPUB highlights
poetry run python -m src.cli.main process-all "/path/to/remarkable/data" \
  --output-dir "extracted_notes" \
  --export-highlights "highlights.csv" \
  --export-text "text_results.csv"

# Full featured example
poetry run python -m src.cli.main process-all "/remarkable/data" \
  --output-dir "digital_notes" \          # Save extracted text files
  --export-highlights "highlights.csv" \  # Export highlights to CSV
  --export-text "extraction_log.csv" \    # Export text results to CSV
  --enhanced-highlights \                  # Use EPUB text matching
  --format md \                           # Markdown output
  --confidence 0.8 \                      # OCR quality threshold
  --language en \                         # OCR language
  --include-pdf-epub \                    # Include PDF/EPUB in text extraction
  --max-pages 5                           # Limit pages (for testing)

# Quick processing (basic options)
poetry run python -m src.cli.main process-all "/path/to/data" --output-dir "notes"
```

**What `process-all` does:**
1. **Step 1**: Extracts handwritten text from notebook `.rm` files using Claude Vision OCR
2. **Step 2**: Extracts highlights from PDF/EPUB documents (basic or enhanced)
3. **Step 3**: Exports both results to CSV files (optional)
4. **Step 4**: Shows comprehensive summary of all processing

**Key advantages:**
- ⚡ **Single command** for complete reMarkable processing
- 🎯 **Automatic separation** - handwritten vs PDF/EPUB content
- 📊 **Dual export** - separate CSV files for text and highlights
- 🔄 **All features** - combines every option from individual commands

### AI-Powered Text Extraction Commands

> 🚀 **Revolutionary Feature**: Transform handwritten notes into perfect Markdown with human-level accuracy!  
> See **[AI OCR Guide](ai-ocr.md)** for complete setup and optimization details.

```bash
# Extract handwritten text using Claude Vision AI
poetry run python -m src.cli.main text extract "/path/to/remarkable/data" --output-dir "extracted_notes"

# Advanced options
poetry run python -m src.cli.main text extract "/path/to/data" \
  --format md \              # Markdown output (default)
  --confidence 0.8 \         # Quality threshold (0.0-1.0)
  --language en \            # OCR language
  --output-dir "notes"

# Output formats
--format md    # Markdown with page delimiters and date detection
--format json  # Structured data with metadata  
--format csv   # Spreadsheet-compatible export
--format txt   # Plain text (also uses Markdown formatting)
```

**Requirements:**
- Set `ANTHROPIC_API_KEY` environment variable
- reMarkable data directory with `.rm`, `.content`, `.metadata` files

**Features:**
- 🎯 **Human-level accuracy** on cursive handwriting
- 📅 **Automatic date detection** from your corner annotations  
- 📝 **Perfect Markdown** with arrows (→), bullets (•), structure
- 🌍 **Multi-language support** (English, German, etc.)
- 📄 **Page organization** with clear delimiters

### Legacy File Processing Commands
```bash
# Process all files in a directory (basic extraction)
poetry run python -m src.cli.main process directory /path/to/remarkable

# Process with enhanced EPUB text matching
poetry run python -m src.cli.main process directory /path/to/remarkable --enhanced

# Process and export results to CSV
poetry run python -m src.cli.main process directory /path/to/remarkable --export highlights.csv

# Compare basic vs enhanced extraction methods
poetry run python -m src.cli.main process directory /path/to/remarkable --compare

# Process a single file
poetry run python -m src.cli.main process file /path/to/document.content --enhanced --show
```

### Database Management
```bash
# Show database statistics
poetry run python -m src.cli.main database stats

# Create manual backup
poetry run python -m src.cli.main database backup

# Clean up old data (keep last 30 days)
poetry run python -m src.cli.main database cleanup --days 30 --vacuum
```

### Export Commands
```bash
# Export all highlights to CSV
poetry run python -m src.cli.main export -o highlights.csv

# Export enhanced highlights
poetry run python -m src.cli.main export -o enhanced_highlights.csv --enhanced

# Export highlights for specific document
poetry run python -m src.cli.main export -o book_highlights.csv --title "My Book Title"
```

### Utility Commands
```bash
# Show version information
poetry run python -m src.cli.main version

# Watch directory for changes (placeholder)
poetry run python -m src.cli.main watch

# Get help for any command
poetry run python -m src.cli.main --help
poetry run python -m src.cli.main <command> --help
```

## Common Workflows

### First-Time Setup
```bash
# 1. Install and configure
poetry install
poetry run python -m src.cli.main config init --sync-dir "/Users/yourname/reMarkable"

# 2. Set up Claude API key for AI OCR
poetry run python -m src.cli.main config api-key set

# 3. Verify setup
poetry run python -m src.cli.main config check

# 4. Process everything at once (RECOMMENDED)
poetry run python -m src.cli.main process-all "/Users/yourname/reMarkable" \
  --output-dir "digital_notes" \
  --export-highlights "all_highlights.csv" \
  --export-text "extraction_log.csv" \
  --enhanced-highlights
```

### Daily Usage - Unified Processing (RECOMMENDED)
```bash
# Process everything in one command
poetry run python -m src.cli.main process-all "/path/to/remarkable" \
  --output-dir "today_notes" \
  --export-highlights "today_highlights.csv" \
  --enhanced-highlights

# Quick processing without exports
poetry run python -m src.cli.main process-all "/path/to/remarkable" --output-dir "notes"

# Check what's in the database
poetry run python -m src.cli.main database stats
```

### Daily Usage - Individual Commands
```bash
# Process new files and export highlights (legacy approach)
poetry run python -m src.cli.main process directory "/Users/yourname/reMarkable" --enhanced --export today_highlights.csv

# Extract handwritten text separately
poetry run python -m src.cli.main text extract "/path/to/remarkable" --output-dir "notes"

# Export all highlights for external use
poetry run python -m src.cli.main export -o all_highlights.csv --enhanced
```

### Maintenance
```bash
# Create backup before major operations
poetry run python -m src.cli.main database backup -o backup_$(date +%Y%m%d).db

# Clean up old data and optimize database
poetry run python -m src.cli.main database cleanup --days 60 --vacuum

# Check configuration after updates
poetry run python -m src.cli.main config check
```

## Advanced Usage

### Configuration Options
The CLI supports extensive configuration through `config.yaml`:

```yaml
remarkable:
  sync_directory: "/Users/yourname/reMarkable"
  backup_directory: "/Users/yourname/reMarkable/backups"

processing:
  highlight_extraction:
    enabled: true
    min_text_length: 8
    text_threshold: 0.4

integrations:
  notion:
    enabled: true
    api_token: "your_token_here"
  readwise:
    enabled: true
    api_token: "your_token_here"

logging:
  level: "INFO"
  file: "remarkable_integration.log"
```

### Environment Variables
Override configuration with environment variables:
```bash
export REMARKABLE_SYNC_DIR="/path/to/remarkable"
export REMARKABLE_LOG_LEVEL="DEBUG"
poetry run python -m src.cli.main process directory "/path/to/files"
```

### Processing Options
- **Basic extraction**: Fast text extraction from .rm files
- **Enhanced extraction**: Uses EPUB text matching to correct OCR errors and merge fragments
- **Compare mode**: Runs both methods and shows performance comparison

### Verbose Logging
```bash
# Enable verbose logging for any command
poetry run python -m src.cli.main -v process directory /path/to/files

# Or set in configuration
poetry run python -m src.cli.main -c debug-config.yaml process directory /path/to/files
```

## Troubleshooting

### Common Issues

#### Configuration Not Found
```bash
# Error: Configuration issues found: remarkable.sync_directory is required
# Solution: Initialize and configure
poetry run python -m src.cli.main config init --sync-dir "/path/to/remarkable"
```

#### Permission Errors
```bash
# Error: Database directory not writable
# Solution: Check permissions or change database path
poetry run python -m src.cli.main config show --section database
```

#### No Files Found
```bash
# Error: No .content files found
# Solution: Verify sync directory contains reMarkable files
ls -la "/path/to/remarkable/"
```

#### AI OCR Issues
```bash
# Error: Claude Vision OCR engine not available
# Solution: Set your Anthropic API key
export ANTHROPIC_API_KEY="your-api-key-here"

# Error: SSL certificate verification failed  
# Solution: The system automatically handles SSL issues in corporate environments

# Error: No text extracted
# Solutions:
# 1. Check input path contains .rm files
# 2. Lower confidence threshold: --confidence 0.6
# 3. Verify API key has credits
# 4. Check network connectivity
```

## 🎯 Quick Examples

### Complete Workflow (UNIFIED APPROACH)
```bash
# 1. Setup
export ANTHROPIC_API_KEY="your-key"
poetry install

# 2. Process everything at once - handwritten notes + highlights
poetry run python -m src.cli.main process-all "/remarkable/data" \
  --output-dir "digital_notes" \
  --export-highlights "highlights.csv" \
  --enhanced-highlights

# 3. Result: Perfect Markdown files + extracted highlights ready for any app!
```

### Integration Examples
```bash
# Complete processing to Obsidian vault
poetry run python -m src.cli.main process-all data/ \
  --output-dir "/path/to/obsidian/vault" \
  --export-highlights "/path/to/obsidian/highlights.csv" \
  --enhanced-highlights

# Export structured data (text only)
poetry run python -m src.cli.main text extract data/ --format json --output-dir "api_data"

# Create spreadsheet exports for analysis
poetry run python -m src.cli.main process-all data/ \
  --format csv \
  --export-text "text_analysis.csv" \
  --export-highlights "highlight_analysis.csv"
```
poetry run python -m src.cli.main config check
```

### Debug Mode
Enable verbose logging for troubleshooting:
```bash
poetry run python -m src.cli.main -v process directory /path/to/files
```

## Command Reference

| Command | Description | Type |
|---------|-------------|------|
| **`process-all`** | **🆕 Process handwritten notes + highlights together** | **Unified** |
| `text extract` | Extract handwritten text using AI OCR | Text |
| `text analyze` | Analyze library for cost estimation | Text |
| `process directory` | Process highlights from PDF/EPUB files | Highlights |
| `process file` | Process single file for highlights | Highlights |
| `config init` | Initialize configuration file | Config |
| `config check` | Validate configuration | Config |
| `config show` | Display configuration | Config |
| `config api-key set` | Set up Anthropic API key | Config |
| `database stats` | Show database statistics | Database |
| `database backup` | Create database backup | Database |
| `database cleanup` | Clean old data | Database |
| `export` | Export highlights to CSV | Export |
| `version` | Show version information | Utility |
| `watch` | Watch directory for changes | Utility |

For detailed help on any command:
```bash
poetry run python -m src.cli.main <command> --help
```