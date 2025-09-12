# Direct File Watching System

The reMarkable Integration features a streamlined file watching system that provides real-time processing of your handwritten notes with intelligent change detection.

## Architecture Overview

```
reMarkable Source Directory → [FileWatcher] → [Change Detection] → [Text Extraction]
     (monitors changes)         (processes)      (incremental)        (AI-powered)
```

### Simplified Direct Processing
- **Monitors**: Original reMarkable desktop app data directory
- **Processes**: Files directly without intermediate copying
- **Benefits**: Real-time processing, reduced disk usage, simplified configuration

## Quick Start

### 🚀 **Complete Pipeline Setup (First Time)**

#### **Step 1: Set Up API Key** (for AI-powered OCR)
```bash
poetry run python -m src.cli.main config api-key set
```
Follow the prompts to enter your Anthropic API key from [console.anthropic.com](https://console.anthropic.com/).

#### **Step 2: Configure Your Setup**
Create or update your `config.yaml`:

```yaml
remarkable:
  # Path to reMarkable desktop app data directory
  source_directory: "~/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop"  # macOS
  # source_directory: "%APPDATA%/remarkable/desktop"  # Windows  
  # source_directory: "~/.local/share/remarkable/desktop"  # Linux
```

#### **Step 3: Verify Configuration**
```bash
poetry run python -m src.cli.main config check
```

#### **Step 4: Start the File Watching System**
```bash
# Start the direct file watching system with text extraction
poetry run python -m src.cli.main watch
```

### 🎯 **What Happens When You Start**

When you run the watch command, you'll see:

```
🚀 Starting reMarkable file watching system...
📁 Source: ~/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop
⚙️  Sync on startup: Yes
⚡ Process immediately: Yes

✅ File watching system started successfully!
📡 Monitoring reMarkable directory for changes...
🔄 Processing files automatically...

💡 The system will:
   1. Watch your reMarkable directory for changes
   2. Process changed notebooks with incremental updates
   3. Extract text using AI-powered OCR
   4. Auto-sync processed notebooks to Notion

Press Ctrl+C to stop watching...
```

### 🔄 **The Complete Automated Workflow**

Once started, here's what happens automatically:

1. **You write/edit in reMarkable app** → Changes saved to app directory
2. **FileWatcher detects change** → Triggers processing after debounce
3. **Change detection analyzes files** → Identifies only modified pages
4. **NotebookTextExtractor processes** → Uses incremental updates (only changed pages)
5. **AI OCR extracts text** → Claude Vision reads your handwriting
6. **Database stores results** → Searchable text with metadata
7. **Ready for export/integration** → Notion, Readwise, etc.

### ⚡ **Advanced Startup Options**

```bash
# Override source directory if needed
poetry run python -m src.cli.main watch \
  --source-directory "~/path/to/remarkable/data"

# Verbose logging to see what's happening
poetry run python -m src.cli.main --verbose watch

# Control processing behavior
poetry run python -m src.cli.main watch \
  --sync-on-startup \
  --process-immediately
```

### 🧪 **Testing Mode Setup**

For testing without using your full reMarkable data:

```bash
# 1. Update config for testing
poetry run python -m src.cli.main watch \
  --source-directory "./test_data/rm_files"

# 2. Add some test .content/.rm files to test_data/rm_files/
# 3. Watch the pipeline process them automatically
```

### 🛟 **First-Time Troubleshooting**

#### **If the watch command fails:**
```bash
# Check if source directory exists
ls "~/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop"

# Check configuration
poetry run python -m src.cli.main config show

# Check API key is set
poetry run python -m src.cli.main config api-key get
```

#### **If no processing happens:**
- Make sure you have notebooks in your reMarkable app
- Try making a change in a notebook to trigger detection  
- Check the logs with `--verbose` flag

### 💡 **Production Usage Tips**

#### **Run in Background**
```bash
# Use nohup for continuous operation
nohup poetry run python -m src.cli.main watch > watch.log 2>&1 &

# Or use screen/tmux
screen -S remarkable-watch
poetry run python -m src.cli.main watch
# Ctrl+A, D to detach
```

#### **Monitor Progress**
```bash
# Check what's being extracted
poetry run python -m src.cli.main database stats

# View recent activity
tail -f watch.log
```

#### **Export Results**
```bash
# Get your extracted text
poetry run python -m src.cli.main export --output results.csv

# Export specific notebook text
poetry run python -m src.cli.main text extract \
  "~/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop" \
  --output-dir "extracted_notes" \
  --format md
```

### 🔄 **Alternative: Manual Processing**

If you prefer batch processing instead of continuous watching:

```bash
# Process all notebooks once
poetry run python -m src.cli.main text extract \
  "~/Library/Containers/com.remarkable.desktop/Data/Library/Application Support/remarkable/desktop" \
  --output-dir "extracted_notes" \
  --format md
```

## Key Features

### ✅ Real-Time Processing
- Detects changes immediately when you save notes in reMarkable app
- Processes files directly from source directory
- Processes only changed notebooks

### ✅ Incremental Updates
- **Page-level granularity**: Only updates pages that actually changed
- **Content hashing**: Detects changes in text, position, or confidence
- **Preserves history**: Keeps timestamps for unchanged content
- **Atomic updates**: Database transactions ensure consistency

### ✅ Smart Debouncing
- Waits for changes to settle before processing
- Configurable debounce period (default: 5 seconds)
- Handles rapid successive changes gracefully

### ✅ Safe Operation
- Read-only access to original reMarkable app files
- Never modifies source files
- Automatic backup support
- Graceful error handling

## Configuration Options

```yaml
remarkable:
  # Core directory
  source_directory: "path/to/remarkable/app/data"
  
  # Exclusion patterns
  exclude_notebooks:
    names:
      - "Template*"
      - "*Draft*"
    uuids:
      - "uuid-to-exclude"
  
  # Processing settings
processing:
  file_watching:
    enabled: true
    processing_cooldown: 5  # Seconds between processing same file
    watch_patterns:
      - "*.content"
      - "*.rm"
    ignore_patterns:
      - ".*"
      - "*.tmp"
```

## Command Line Options

```bash
# Basic usage
poetry run python -m src.cli.main watch

# Override source directory
poetry run python -m src.cli.main watch --source-directory "/path/to/remarkable/data"

# Control processing behavior
poetry run python -m src.cli.main watch --sync-on-startup --process-immediately
```

## How Incremental Updates Work

### Content Hash Calculation
Each page's content is hashed based on:
- Page number
- Number of text regions
- All extracted text content
- Bounding box positions

### Update Logic
1. **Process notebook** → Extract text from all pages
2. **For each page**:
   - Calculate content hash
   - Compare with stored hash in database
   - If unchanged → Skip (preserves created_at timestamp)
   - If changed → Update only that page
3. **Atomic commit** → All changes saved together

### Database Schema
```sql
CREATE TABLE notebook_text_extractions (
    id INTEGER PRIMARY KEY,
    notebook_uuid TEXT NOT NULL,
    notebook_name TEXT NOT NULL,
    page_uuid TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    text TEXT NOT NULL,
    confidence REAL NOT NULL,
    bounding_box TEXT,
    language TEXT,
    page_content_hash TEXT,        -- For change detection
    created_at TIMESTAMP,          -- When first extracted
    updated_at TIMESTAMP           -- When last updated
);
```

## Platform-Specific Setup

### macOS
```yaml
remarkable:
  source_directory: "~/Library/Containers/com.remarkable.desktop/Data/Documents/remarkable"
```

### Windows
```yaml
remarkable:
  source_directory: "%APPDATA%/remarkable/desktop"
```

### Linux
```yaml
remarkable:
  source_directory: "~/.local/share/remarkable/desktop"
```

## Troubleshooting

### Source Directory Not Found
- Ensure reMarkable desktop app is installed
- Check that app has synced data at least once
- Verify the path in your config file

### Permission Issues
- Ensure read access to reMarkable app directory
- On macOS, may need to grant Terminal full disk access

### No Processing Happening
- Check that files are actually changing in source directory
- Check logs for error messages
- Ensure API key is configured for OCR processing

## Monitoring and Logs

The system provides detailed logging of:
- File change detection
- Processing results
- Incremental update decisions

Use `--verbose` flag for detailed logging:
```bash
poetry run python -m src.cli.main --verbose watch
```

## Performance

### Efficiency Gains
- **Processing**: Only processes changed pages (not entire notebooks)
- **Database**: Indexed lookups for change detection
- **Memory**: Minimal overhead with async operations
- **Disk**: No intermediate file copying required

### Typical Performance
- **Change detection**: < 1 second
- **Incremental processing**: 2-10 seconds per changed page
- **Database updates**: < 1 second

## Integration with Existing Workflows

The direct file watching system works seamlessly with:
- **Manual processing**: `text extract` command still works
- **Batch processing**: `process directory` command still works  
- **Export functions**: All export commands work with incrementally updated data
- **Integrations**: Notion, Readwise, etc. work with real-time updates

## Migration from Legacy Setup

If you're upgrading from the old two-tier sync setup:

1. **Update config**:
   ```yaml
   # Old
   remarkable:
     sync_directory: "/path/to/remarkable"
     local_sync_directory: "./data/remarkable_sync"
   
   # New (simplified)
   remarkable:
     source_directory: "/path/to/remarkable/app/data"
   ```

2. **Clean up old directories** (optional):
   ```bash
   # Remove local sync directory if no longer needed
   rm -rf ./data/remarkable_sync
   ```

3. **Existing database**: Works seamlessly with new architecture (no migration needed)

The system is backward compatible and your existing data will continue to work without any changes.