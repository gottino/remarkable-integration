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

# Install dependencies
poetry install

# Initialize configuration
poetry run python -m src.cli.main config init --sync-dir "/path/to/your/remarkable"

# Process your reMarkable files
poetry run python -m src.cli.main process directory "/path/to/remarkable" --enhanced

# Export highlights to CSV
poetry run python -m src.cli.main export -o highlights.csv --enhanced
```

## Documentation

- **[CLI Usage Guide](docs/cli-usage.md)** - Complete command-line interface documentation
- **[Highlight Extraction](docs/highlight_extraction.md)** - Technical details on highlight processing

For help with any command:
```bash
poetry run python -m src.cli.main --help
```