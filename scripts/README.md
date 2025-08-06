# Scripts

Utility scripts for the reMarkable pipeline.

## migrate_highlights.py
Migration tool to help transition from extract_text.py to the new highlight extractor.

Usage:
```bash
# Compare old vs new methods
python migrate_highlights.py /path/to/files --compare

# Migrate to new system
python migrate_highlights.py /path/
