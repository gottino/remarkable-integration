# Notion Integration for reMarkable Notebooks

This integration syncs extracted handwritten text from your reMarkable notebooks to a Notion database, creating organized pages with content grouped by notebook pages in reverse order (latest pages first).

## Features

- 📓 **One Notion page per notebook**: Each handwritten notebook becomes a Notion page
- 🔄 **Reverse page order**: Latest notebook pages appear first in Notion  
- 🎛️ **Toggle blocks**: Each notebook page becomes a collapsible toggle for easy navigation
- 🎯 **Smart filtering**: Automatically excludes imported books (PDF/EPUB) and focuses on handwritten content
- 🔄 **Intelligent incremental sync**: Only updates notebooks that have actually changed
- ✨ **Markdown formatting**: Converts markdown-like text (headings, lists, checkboxes) to proper Notion formatting
- 📊 **Confidence indicators**: Shows OCR confidence levels for extracted text
- 🏷️ **Rich metadata**: Includes path, tags, last modified/viewed dates from reMarkable

## Setup Instructions

### 1. Create a Notion Integration

1. Go to [Notion Developers](https://developers.notion.com/)
2. Click **"New Integration"**
3. Give it a name (e.g., "reMarkable Sync")
4. Select the workspace where you want to sync notebooks
5. Click **"Submit"**
6. Copy the **Integration Token** (starts with `secret_`)

### 2. Create a Notion Database

1. In Notion, create a new page
2. Add a **Database** (full page)
3. Set up these properties:
   - **Name** (Title) - Will contain notebook names
   - **Notebook UUID** (Text) - For tracking notebooks
   - **Total Pages** (Number) - Number of pages in notebook  
   - **Last Updated** (Date) - When the sync last ran
   - **reMarkable Path** (Text) - Full path in reMarkable (e.g., "Archive/Meeting Notes/ProjectX")
   - **Tags** (Multi-select) - Path folders as tags (e.g., "Archive", "Meeting Notes")
   - **Last Modified** (Date) - When the notebook was last modified on reMarkable
   - **Last Viewed** (Date) - When the notebook was last opened on reMarkable

4. **Share the database** with your integration:
   - Click **"Share"** in the top-right
   - Click **"Invite"** 
   - Find your integration name and click **"Invite"**

5. **Copy the Database ID**:
   - From the database URL: `https://notion.so/your-workspace/DATABASE_ID?v=...`
   - Copy the part between the last `/` and `?` (32 characters)

### 3. Configure the Integration

You can provide credentials in several ways:

#### Option A: Environment Variables
```bash
export NOTION_TOKEN="secret_your_token_here"
export NOTION_DATABASE_ID="your_database_id_here"
```

#### Option B: Config File
Edit `config/config.yaml`:
```yaml
integrations:
  notion:
    enabled: true
    api_token: "secret_your_token_here"
    database_id: "your_database_id_here"
```

## Usage

### Test the Integration
First, test with a small subset:
```bash
# Set environment variables
export NOTION_TOKEN="secret_your_token_here" 
export NOTION_DATABASE_ID="your_database_id_here"

# Run test
poetry run python scripts/test_notion_integration.py
```

### Full Sync
Sync all handwritten notebooks:
```bash
poetry run python src/cli/main.py sync-notion --database-id YOUR_DATABASE_ID
```

### Advanced Options
```bash
# Sync with custom token
poetry run python src/cli/main.py sync-notion --token secret_your_token --database-id YOUR_DATABASE_ID

# Don't update existing pages
poetry run python src/cli/main.py sync-notion --database-id YOUR_DATABASE_ID --no-update-existing

# Exclude specific notebooks
poetry run python src/cli/main.py sync-notion --database-id YOUR_DATABASE_ID --exclude-pattern "Draft*" --exclude-pattern "Test*"

# Disable SSL verification (for corporate networks)
poetry run python src/cli/main.py sync-notion --database-id YOUR_DATABASE_ID --no-ssl-verify

# Force full update (skip intelligent incremental sync)
poetry run python src/cli/main.py sync-notion --database-id YOUR_DATABASE_ID --force-update
```

## Enhanced Features

### Markdown Formatting
The integration automatically converts markdown-like text from your handwritten notes into proper Notion formatting:

- **Headings**: `## Meeting Notes` → Notion heading blocks
- **Checkboxes**: `- [x] Complete task` → Notion checkbox blocks (checked/unchecked)
- **Bullet points**: `- Important point` → Notion bullet list items
- **Bold text**: `**Important**` → **Bold** text in Notion
- **Dividers**: `---` → Notion divider blocks

### Intelligent Incremental Sync
The system tracks what has been synced and only updates what has changed:

- 🆕 **New notebooks**: Automatically detected and synced
- 📝 **Content changes**: Only notebooks with new/modified pages are updated
- 🏷️ **Metadata changes**: Updates when path, timestamps, or other metadata changes
- ⏭️ **Unchanged content**: Skipped entirely for fast sync times

The first sync will process all notebooks. Subsequent syncs will be much faster as only changed content is processed.

### Rich Metadata Integration
Each Notion page includes comprehensive metadata from your reMarkable:

- **Path hierarchy**: Converted to searchable tags (e.g., `Archive/Meeting Notes` → tags: `Archive`, `Meeting Notes`)
- **Last Modified**: When the notebook was last edited on reMarkable
- **Last Viewed**: When the notebook was last opened on reMarkable
- **Total Pages**: Current page count
- **Last Updated**: When the Notion sync last ran

## How It Works

### Page Structure
Each Notion page contains:

1. **Header**: Notebook name with 📓 emoji
2. **Summary**: Total pages and UUID info
3. **Page Toggles**: One toggle per notebook page (in reverse order)
   - **Page X** with confidence indicator (🟢🟡🔴)
   - Extracted text formatted as paragraphs
   - Empty pages show "(No readable text extracted)"

### Example Notion Page Structure
```
📓 Meeting Notes

Total pages: 12 | UUID: a1b2c3d4...
─────────────────────────────────

▶ 📄 Page 12 (🟢 0.9)
   Latest meeting notes from today's discussion...
   Action items and follow-ups...

▶ 📄 Page 11 (🟡 0.7) 
   Previous meeting notes...

▶ 📄 Page 10 (🟢 0.8)
   Project planning session...
```

### Confidence Indicators
- 🟢 **High confidence** (> 0.8): Text extraction is very reliable
- 🟡 **Medium confidence** (0.5-0.8): Good extraction, may have minor errors  
- 🔴 **Low confidence** (< 0.5): Text may have significant OCR errors

## Filtering

By default, the integration:
- ✅ **Includes**: Handwritten notebooks with extracted text
- ⏭️ **Excludes**: Imported books (PDF/EPUB files like "Luzerner Todesmelodie")
- ⏭️ **Excludes**: Notebooks with no readable text

You can add custom exclusion patterns with `--exclude-pattern`.

## Troubleshooting

### "❌ Notion token required"
- Make sure your token starts with `secret_`
- Set the token via environment variable or config file
- Get a new token from [Notion Developers](https://developers.notion.com/)

### "❌ Database not found"
- Make sure you shared the database with your integration
- Check that the database ID is correct (32 characters)
- The database must be a full-page database, not an inline one

### "❌ No notebooks found"
- Make sure you've extracted text from your notebooks first:
  ```bash
  poetry run python src/cli/main.py extract-text ./data/remarkable_sync
  ```

### Pages not updating
- Use `--update-existing` flag to overwrite existing pages
- Check that the Notebook UUID matches between runs

## Security Notes

- Your Notion token gives access to your workspace - keep it secure
- The integration only needs access to the specific database you share with it
- Tokens can be revoked at any time from the Notion Developer portal
- No reMarkable data is sent anywhere except to your Notion workspace

## Advanced Configuration

### Custom Database Schema
If you want additional properties in your Notion database:

1. Add the properties to your database manually
2. They won't be populated automatically but will be preserved during updates
3. Examples: Tags, Categories, Review Status, etc.

### Automation

#### Real-Time Watching System (Recommended)
Enable automatic real-time sync with the watching system:

```bash
# 1. Set up Notion credentials
poetry run python scripts/setup_notion_watching.py

# 2. Start the complete watching pipeline
poetry run python src/cli/main.py watch
```

The watching system provides complete automation:
- **Real-time monitoring**: Watches your reMarkable app directory for changes
- **Direct processing**: Processes files directly from source directory
- **Smart processing**: Only processes changed notebooks with incremental OCR
- **Auto-sync to Notion**: Immediately syncs processed notebooks with markdown formatting
- **Intelligent updates**: Only updates Notion pages that have actually changed

#### Manual/Scheduled Sync
Alternative options for periodic syncing:

1. **Cron job** (every hour):
```bash
0 * * * * cd /path/to/remarkable-integration && poetry run python src/cli/main.py sync-notion --database-id YOUR_ID --no-ssl-verify
```

2. **Manual sync** when needed:
```bash
poetry run python src/cli/main.py sync-notion --database-id YOUR_ID --no-ssl-verify
```