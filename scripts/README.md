# Scripts

Utility scripts for the reMarkable pipeline.

## Readwise Integration Scripts

### fix_readwise_duplicates.py
Clears Readwise sync records to enable re-syncing highlights with corrected metadata.

Usage:
```bash
poetry run python scripts/fix_readwise_duplicates.py
```

What it does:
- Shows current sync state (number of highlights synced to Readwise)
- Clears all Readwise entries from `highlight_sync_records` table
- Enables re-sync with updated book metadata (authors, titles)

### check_readwise_duplicates.py
Checks for duplicate books in Readwise with author "reMarkable" or incorrect titles.

Usage:
```bash
poetry run python scripts/check_readwise_duplicates.py
```

### fix_titles_with_authors.py
Removes author names from book titles that incorrectly include them.

Usage:
```bash
poetry run python scripts/fix_titles_with_authors.py
```

Fixes titles like:
- "Amsterdam - Ian McEwan" → "Amsterdam"
- "Ein Bild von Lydia - Lukas Hartmann" → "Ein Bild von Lydia"

### delete_readwise_duplicates.py
Attempts to delete duplicate books from Readwise (Note: Readwise API doesn't support programmatic deletion).

## EPUB Text Matching Scripts

### reprocess_highlights_with_epub_matching.py
Batch reprocesses all EPUB highlights in the database with text matching.

Usage:
```bash
# Dry run (shows what would be changed)
poetry run python scripts/reprocess_highlights_with_epub_matching.py

# Apply changes
poetry run python scripts/reprocess_highlights_with_epub_matching.py --live
```

### reprocess_highlights_with_pdf_matching.py
Batch reprocesses all PDF highlights in the database with text matching.

Usage:
```bash
# Dry run
poetry run python scripts/reprocess_highlights_with_pdf_matching.py

# Apply changes
poetry run python scripts/reprocess_highlights_with_pdf_matching.py --live
```

## Data Quality Scripts

### cleanup_gibberish_highlights.py
Removes gibberish/low-quality highlights from the database.

Usage:
```bash
poetry run python scripts/cleanup_gibberish_highlights.py
```

What it does:
- Scans all highlights for gibberish (excessive symbols, insufficient words, low alphabetic ratio)
- Groups results by book for review
- Prompts for confirmation before deletion
- Removes both highlights and their sync records

Quality criteria:
- Minimum 15 characters
- At least 60% alphabetic characters
- At least 3 words
- Maximum 20% symbol ratio
- No more than 3 consecutive non-alphanumeric characters

## Legacy Scripts

### migrate_highlights.py
Migration tool to help transition from extract_text.py to the new highlight extractor.

Usage:
```bash
# Compare old vs new methods
python migrate_highlights.py /path/to/files --compare

# Migrate to new system
python migrate_highlights.py /path/
