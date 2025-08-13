# reMarkable Integration

A Python-based integration that automatically processes reMarkable tablet data, extracting handwritten text, highlights, and todos, then syncing them to various productivity applications.

## Features

- **Automatic Sync**: Monitor reMarkable sync folder for real-time processing
- **Handwritten Text Transcription**: OCR recognition with date detection
- **Todo Recognition**: Detect checkbox patterns and convert to actionable tasks
- **History Tracking**: Maintain a log of all changes and processing
- **Multiple Integrations**: 
  - Notion (for notes and content)
  - Microsoft To Do (for task management)
  - Readwise (for highlights)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/remarkable-integration.git
cd remarkable-integration

# Install dependencies with Poetry
poetry install

# Initialize configuration
poetry run python -m src.cli.main config init

# Edit configuration with your reMarkable sync directory
nano config.yaml

# Verify configuration
poetry run python -m src.cli.main config check

# Process your reMarkable files
poetry run python -m src.cli.main process directory /path/to/remarkable/sync --enhanced
```

## CLI Usage

The reMarkable Integration CLI provides a comprehensive command-line interface for processing reMarkable files, managing configuration, and working with extracted content.

### Installation & Setup

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

### Quick Reference

#### Configuration Commands
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

#### File Processing Commands
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

#### Database Management
```bash
# Show database statistics
poetry run python -m src.cli.main database stats

# Create manual backup
poetry run python -m src.cli.main database backup

# Clean up old data (keep last 30 days)
poetry run python -m src.cli.main database cleanup --days 30 --vacuum
```

#### Export Commands
```bash
# Export all highlights to CSV
poetry run python -m src.cli.main export -o highlights.csv

# Export enhanced highlights
poetry run python -m src.cli.main export -o enhanced_highlights.csv --enhanced

# Export highlights for specific document
poetry run python -m src.cli.main export -o book_highlights.csv --title "My Book Title"
```

#### Utility Commands
```bash
# Show version information
poetry run python -m src.cli.main version

# Watch directory for changes (placeholder)
poetry run python -m src.cli.main watch

# Get help for any command
poetry run python -m src.cli.main --help
poetry run python -m src.cli.main <command> --help
```

### Common Workflows

#### First-Time Setup
```bash
# 1. Install and configure
poetry install
poetry run python -m src.cli.main config init --sync-dir "/Users/yourname/reMarkable"

# 2. Verify setup
poetry run python -m src.cli.main config check

# 3. Process existing files
poetry run python -m src.cli.main process directory "/Users/yourname/reMarkable" --enhanced
```

#### Daily Usage
```bash
# Process new files and export highlights
poetry run python -m src.cli.main process directory "/Users/yourname/reMarkable" --enhanced --export today_highlights.csv

# Check what's in the database
poetry run python -m src.cli.main database stats

# Export all highlights for external use
poetry run python -m src.cli.main export -o all_highlights.csv --enhanced
```

#### Maintenance
```bash
# Create backup before major operations
poetry run python -m src.cli.main database backup -o backup_$(date +%Y%m%d).db

# Clean up old data and optimize database
poetry run python -m src.cli.main database cleanup --days 60 --vacuum

# Check configuration after updates
poetry run python -m src.cli.main config check
```

### Advanced Usage

#### Configuration Options
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

#### Environment Variables
Override configuration with environment variables:
```bash
export REMARKABLE_SYNC_DIR="/path/to/remarkable"
export REMARKABLE_LOG_LEVEL="DEBUG"
poetry run python -m src.cli.main process directory "/path/to/files"
```

#### Processing Options
- **Basic extraction**: Fast text extraction from .rm files
- **Enhanced extraction**: Uses EPUB text matching to correct OCR errors and merge fragments
- **Compare mode**: Runs both methods and shows performance comparison

#### Verbose Logging
```bash
# Enable verbose logging for any command
poetry run python -m src.cli.main -v process directory /path/to/files

# Or set in configuration
poetry run python -m src.cli.main -c debug-config.yaml process directory /path/to/files
```