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
pip install -e .

# Copy configuration template
cp config/config.yaml.example config/config.yaml

# Edit configuration with your settings
nano config/config.yaml

# Run the integration
remarkable-integration start