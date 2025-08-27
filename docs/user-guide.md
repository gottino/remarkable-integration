# User Guide: reMarkable to Digital Workflow

Transform your handwritten reMarkable notes into perfectly searchable digital text with AI-powered transcription.

## 🎯 What This Does

**Before**: Hundreds of handwritten notebook pages locked in proprietary .rm format  
**After**: Beautifully formatted Markdown files with perfect transcription and chronological organization

### Real Example

**Your handwritten page:**
```
                              ⌐ 15-08-2025 ┘

Project Meeting
- Timeline review → Q2 launch confirmed  
- Budget: $50k approved ✓
- Next steps:
  □ Update documentation
  ☑ Schedule team meeting
→ Follow up with stakeholders
```

**Generated output (`Project Meeting.md`):**
```markdown
# Project Meeting

**Date: 15-08-2025**
---

## Project Meeting
- Timeline review → Q2 launch confirmed  
- Budget: $50k approved ✓
- Next steps:
  - [ ] Update documentation
  - [x] Schedule team meeting
→ Follow up with stakeholders
```

## 🚀 Getting Started

### 1. Prerequisites

- **reMarkable tablet** with sync enabled
- **Python 3.11+** and Poetry
- **Claude API key** from [Anthropic Console](https://console.anthropic.com/)

### 2. Installation

```bash
# Clone and install
git clone https://github.com/yourusername/remarkable-integration.git
cd remarkable-integration
poetry install
```

### 3. Setup API Access

```bash
# Secure API key setup with interactive prompt
poetry run python -m src.cli.main config api-key set

# Or set directly with preferred storage method
poetry run python -m src.cli.main config api-key set --method keychain --key "your-api-key"

# Verify setup
poetry run python -m src.cli.main config api-key get
```

The system securely stores your API key using:
- **Keychain** (macOS/Windows) or **Secret Service** (Linux) - Recommended
- **Encrypted file** with machine-specific encryption  
- **Environment variables** (fallback)

No more API keys in command history or config files! 🔒

### 4. Extract Your Notes

```bash
# Point to your reMarkable data directory
poetry run python -m src.cli.main text extract "/path/to/remarkable/data" --output-dir "my_digital_notes"

# Wait for AI magic ✨
# Result: Perfect Markdown files in "my_digital_notes/"
```

## ⚙️ Configuration

The system can be customized through the `config/config.yaml` file. Here are the key settings:

### Basic Configuration

```yaml
# reMarkable tablet settings
remarkable:
  # Path to reMarkable app data directory (for source files)
  source_directory: "~/Library/Containers/com.remarkable.desktop/Data/Documents/remarkable"
  
  # Path to local sync directory (temporary processing)
  local_sync_directory: "./data/remarkable_sync"
  
  # Path to application data directory (processed files, covers, etc.)
  data_directory: "./data"
```

### EPUB Metadata Extraction

The system automatically extracts rich metadata from EPUB files:

**What Gets Extracted:**
- **Authors** (multiple authors supported)
- **Publisher** information  
- **Publication dates** (normalized to YYYY-MM-DD format)
- **Cover images** (stored in `{data_directory}/covers/`)

**Cover Image Detection:**
1. **Direct filename matching**: `cover.jpg`, `cover.png`, etc.
2. **OPF manifest parsing**: Reads EPUB metadata for cover references
3. **Largest image fallback**: Uses biggest image file (minimum 10KB)

**File Structure:**
```
./data/                              # Your configured data_directory
├── covers/                          # Extracted cover images
│   ├── abc123def456_cover.jpeg     # {uuid}_cover.{extension}
│   └── def789ghi012_cover.png
└── remarkable_sync/                 # Synced reMarkable files
    ├── *.metadata
    ├── *.content  
    └── *.epub
```

**Database Storage:**
All metadata is automatically stored in the SQLite database:
```sql
SELECT visible_name, authors, publisher, publication_date, cover_image_path 
FROM notebook_metadata 
WHERE document_type = 'epub';
```

### Platform-Specific Examples

**macOS:**
```yaml
remarkable:
  source_directory: "~/Library/Containers/com.remarkable.desktop/Data/Documents/remarkable"
  local_sync_directory: "./data/remarkable_sync"
  data_directory: "./data"
```

**Windows:**
```yaml
remarkable:
  source_directory: "%APPDATA%/remarkable/desktop"
  local_sync_directory: "./data/remarkable_sync" 
  data_directory: "./data"
```

**Linux:**
```yaml
remarkable:
  source_directory: "~/.local/share/remarkable/desktop"
  local_sync_directory: "./data/remarkable_sync"
  data_directory: "./data"
```

**Production (Docker):**
```yaml
remarkable:
  source_directory: "/remarkable/source"
  local_sync_directory: "/data/remarkable_sync"
  data_directory: "/data"
```

## 📁 Understanding reMarkable Data

### Finding Your Data

**reMarkable Cloud Sync:**
- Windows: `%USERPROFILE%\.local\share\remarkable\desktop`
- macOS: `~/Library/Application Support/remarkable/desktop`
- Linux: `~/.local/share/remarkable/desktop`

**USB Transfer:**
- Connect reMarkable via USB
- Enable USB web interface
- Download files from `/home/root/.local/share/remarkable/xochitl/`

### File Structure
```
remarkable_data/
├── abc123.content     # Notebook metadata
├── abc123.metadata    # Display name, creation date
├── abc123.pagedata    # Page templates
└── abc123/            # Notebook pages
    ├── page1.rm       # Page stroke data
    ├── page2.rm
    └── ...
```

## 🎨 Features in Detail

### Date Recognition Magic

The system recognizes your date annotation patterns:

**Supported formats:**
- `dd-mm-yyyy` (e.g., `21-09-2021`)
- `d-m-yyyy` (e.g., `5-12-2021`)  
- `dd/mm/yyyy` (e.g., `21/09/2021`)

**Supported brackets:**
- `⌐ date ┘` (lying L shape)
- `[ date ]` (square brackets)
- `( date )` (parentheses)
- `┌ date ┐` (corner brackets)

**Location:** Upper right corner of each page

### Symbol Recognition

**Arrows:**
- `→` Right arrow (from `->>`, `->`, `L>`)
- `←` Left arrow (from `<-`, `<--`)
- `↑` Up arrow
- `↓` Down arrow

**Lists:**
- `•` Bullet points (from `*`, `-`, `o`)
- `- [ ]` Unchecked boxes (from `□`, `☐`)
- `- [x]` Checked boxes (from `☑`, `✓`)

**Formatting:**
- **Bold text** detection
- `Code snippets` recognition
- Proper line breaks and spacing

### Smart Todo Extraction

The system automatically extracts checkboxes and creates a separate `todos.md` file alongside your notebook content.

**Recognized Todo Patterns:**
- `□ Task description` → Unchecked todo
- `☑ Task description` → Checked todo  
- `- [ ] Task description` → Unchecked todo
- `- [x] Task description` → Checked todo
- `* [ ] Task description` → Unchecked todo
- `* [✓] Task description` → Checked todo

**Todo Metadata:**
Each extracted todo includes:
- ✅ **Status**: Completed or pending
- 📝 **Text**: The todo description
- 📚 **Source**: Notebook name and page number
- 📅 **Date**: From page date annotations (if available)
- 🎯 **Confidence**: OCR confidence score

**Example todos.md output:**
```markdown
# Todo Items

## 📋 Pending
- [ ] Update project documentation
  - **Source**: Meeting Notes (Page 2)
  - **Date**: 15-08-2025
  - **Confidence**: 0.95

## ✅ Completed  
- [x] Review quarterly budget
  - **Source**: Planning Session (Page 1)
  - **Date**: 14-08-2025
  - **Confidence**: 0.88
```

### Multi-Language Support

**Automatically handles:**
- English + German mixed content
- French, Spanish, Italian
- Technical notation and numbers
- Proper names and places

**No configuration needed** - Claude Vision understands context across languages.

## 📊 Output Formats

### Markdown (Default)
Perfect for note-taking apps like Obsidian, Notion, Logseq:

```markdown
# Meeting Notes

**Date: 15-08-2025**
---

## Action Items
- [x] Complete project proposal
- [ ] Schedule client meeting
→ Follow up by Friday
```

### JSON (Structured Data)
Great for APIs, databases, or custom processing:

```json
{
  "notebook_name": "Meeting Notes",
  "total_pages": 3,
  "processing_time_ms": 12000,
  "pages": {
    "page_1": {
      "text": "**Date: 15-08-2025**\n---\n\n## Action Items...",
      "character_count": 250
    }
  }
}
```

### CSV (Spreadsheet)
Useful for analysis, reporting, or database import:

| notebook_name | page_number | text | character_count | date_extracted |
|---------------|-------------|------|-----------------|----------------|
| Meeting Notes | 1 | **Date: 15-08-2025**... | 250 | 15-08-2025 |

## 🔧 Advanced Usage

### Quality Control

```bash
# Maximum quality (slower, perfect results)
poetry run python -m src.cli.main text extract data/ --confidence 0.9

# Balanced (default)
poetry run python -m src.cli.main text extract data/ --confidence 0.8

# Faster processing (more permissive)
poetry run python -m src.cli.main text extract data/ --confidence 0.6
```

### Batch Processing

```bash
# Process entire reMarkable backup
poetry run python -m src.cli.main text extract "/reMarkable/backup/complete" --output-dir "complete_archive"

# Results in organized directory:
# complete_archive/
# ├── Meeting Notes 2023.md
# ├── Project Ideas.md
# ├── Travel Journal.md
# ├── Personal Diary.md
# └── extraction_summary.json
```

### Specific Notebooks

```bash
# Process single notebook by finding its directory
ls /remarkable/data/  # Find notebook UUID
poetry run python -m src.cli.main text extract "/remarkable/data/abc123-def456-..." --output-dir "single_notebook"
```

## 📱 Integration Workflows

### Obsidian Integration

```bash
# Extract directly to Obsidian vault
poetry run python -m src.cli.main text extract data/ --output-dir "/path/to/ObsidianVault/reMarkable"

# Add to daily notes template:
# ![[reMarkable/Meeting Notes.md]]
```

### Notion Integration

```bash
# Export as Markdown for Notion import
poetry run python -m src.cli.main text extract data/ --format md --output-dir "notion_import"

# Import process:
# 1. In Notion: "Import" → "Markdown"
# 2. Select all .md files from notion_import/
# 3. Choose destination page
```

### Version Control

```bash
# Create git repository of notes
cd my_digital_notes/
git init
git add *.md
git commit -m "Initial handwritten notes archive"

# Update workflow:
poetry run python -m src.cli.main text extract data/ --output-dir "my_digital_notes"
cd my_digital_notes/
git add .
git commit -m "Updated notes from reMarkable $(date)"
```

### API Integration

```bash
# Generate JSON for custom applications
poetry run python -m src.cli.main text extract data/ --format json --output-dir "api_data"

# Use in your applications:
import json
with open('api_data/Meeting Notes.json') as f:
    notebook = json.load(f)
    for page_key, page_data in notebook['pages'].items():
        process_text(page_data['text'])
```

## 🎯 Use Cases

### 1. Digital Note Archive
**Scenario**: Convert years of handwritten notebooks  
**Workflow**: Bulk extraction → Organize by date → Version control  
**Benefit**: Searchable archive of all notes

### 2. Meeting Documentation
**Scenario**: Convert meeting notes to shareable format  
**Workflow**: Single meeting extraction → Markdown → Share via Notion/Slack  
**Benefit**: Professional documentation with minimal effort

### 3. Project Journaling
**Scenario**: Track project progress over time  
**Workflow**: Regular extraction → Chronological organization → Progress tracking  
**Benefit**: Clear project timeline with handwritten insights

### 4. Research Compilation
**Scenario**: Academic research with handwritten annotations  
**Workflow**: Extract research notes → Combine with digital sources → Citation management  
**Benefit**: Unified research database

### 5. Personal Knowledge Management
**Scenario**: Build personal wiki from handwritten thoughts  
**Workflow**: Extract all notes → Tag by topic → Link related content  
**Benefit**: Comprehensive personal knowledge base

## ⚡ Performance Guide

### Processing Times
- **Small notebook** (5-10 pages): 30-60 seconds
- **Medium notebook** (20-50 pages): 2-5 minutes  
- **Large notebook** (100+ pages): 10-20 minutes
- **Complete archive** (1000+ pages): 1-3 hours

### Cost Optimization
Claude API costs approximately:
- **$0.003** per page (average)
- **$3** per 1000 pages
- **$30** for complete reMarkable archive (10,000 pages)

### Quality vs Speed
- **Fast**: `--confidence 0.6` - Good for drafts
- **Balanced**: `--confidence 0.8` - Recommended default
- **Perfect**: `--confidence 0.9` - For final archives

## 🔍 Troubleshooting

### Common Issues

**"No text extracted"**
- Check file paths contain `.rm` files
- Verify API key is set correctly
- Try lower confidence: `--confidence 0.6`

**"API connection failed"**
- Verify internet connection
- Check API key validity at [Anthropic Console](https://console.anthropic.com/)
- For corporate networks: System handles SSL automatically

**"Poor quality results"**
- Increase confidence: `--confidence 0.9`
- Check handwriting clarity (though system handles messy writing well)
- Verify date annotations are in upper right corner

**"Missing dates"**
- Use consistent date format: `dd-mm-yyyy`
- Place in upper right corner
- Use bracket symbols: `⌐ date ┘`

### Getting Help

1. **Check logs**: Enable verbose mode with `-v` flag
2. **Review configuration**: `poetry run python -m src.cli.main config check`
3. **Test API**: `echo $ANTHROPIC_API_KEY` to verify key is set
4. **Sample test**: Try with single page first

## 🎉 Success Tips

### Optimize Your Handwriting Workflow

1. **Date Consistency**: Always use upper right corner for dates
2. **Clear Structure**: Use headings, bullets, and spacing
3. **Symbol Usage**: Leverage arrows (→) and checkboxes for better organization
4. **Regular Extraction**: Process notes weekly to maintain digital archive

### Maximize Quality

1. **Good Lighting**: Write in well-lit conditions
2. **Consistent Pen**: Use reMarkable pen (not pencil) for best recognition
3. **Clear Writing**: Normal handwriting works fine, but avoid extreme angles
4. **Logical Layout**: Organize thoughts in sections for better Markdown structure

### Integration Best Practices

1. **Naming Conventions**: Use descriptive notebook names in reMarkable
2. **Folder Organization**: Create logical folder structure for outputs
3. **Version Control**: Track changes to important notes over time
4. **Backup Strategy**: Keep both handwritten originals and digital copies

---

**🚀 Result**: Transform decades of handwritten notes into a searchable, linkable, shareable digital knowledge base in hours instead of years!

*Your handwriting just became as powerful as any digital note-taking system.* ✨