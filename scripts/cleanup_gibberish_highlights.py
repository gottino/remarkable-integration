#!/usr/bin/env python3
"""Remove gibberish/low-quality highlights from the database."""

import sqlite3
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.config import Config


def is_gibberish(text: str) -> bool:
    """Check if text appears to be gibberish."""
    if not text or len(text) < 15:
        return True

    # Check alphabetic character ratio (need at least 60%)
    letters = sum(c.isalpha() for c in text)
    if letters / len(text) < 0.6:
        return True

    # Check word count (need at least 3 words)
    words = text.split()
    if len(words) < 3:
        return True

    # Check symbol ratio (max 20%)
    symbols = sum(not c.isalnum() and not c.isspace() for c in text)
    if symbols / len(text) > 0.2:
        return True

    # Check for excessive consecutive symbols
    consecutive_count = 0
    for char in text:
        if not char.isalnum() and not char.isspace():
            consecutive_count += 1
            if consecutive_count > 3:
                return True
        else:
            consecutive_count = 0

    return False


def main():
    """Remove gibberish highlights from the database."""

    config = Config()
    db_path = config.get('database.path')

    print("=" * 80)
    print("Cleanup Gibberish Highlights")
    print("=" * 80)
    print(f"Database: {db_path}")
    print()

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get all highlights
    cursor.execute("""
        SELECT id, title, original_text, corrected_text
        FROM enhanced_highlights
    """)

    all_highlights = cursor.fetchall()
    print(f"Total highlights: {len(all_highlights)}")

    # Check each highlight
    gibberish_ids = []
    gibberish_by_book = {}

    for id, title, original_text, corrected_text in all_highlights:
        # Check both original and corrected text
        text_to_check = corrected_text if corrected_text else original_text

        if is_gibberish(text_to_check):
            gibberish_ids.append(id)
            if title not in gibberish_by_book:
                gibberish_by_book[title] = []
            gibberish_by_book[title].append((id, text_to_check[:80]))

    print(f"Gibberish highlights found: {len(gibberish_ids)}")
    print()

    if not gibberish_ids:
        print("✨ No gibberish highlights found!")
        conn.close()
        return

    # Show examples by book
    print("Gibberish highlights by book:")
    print("-" * 80)
    for title, highlights in sorted(gibberish_by_book.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"\n{title}: {len(highlights)} gibberish highlights")
        for id, text_sample in highlights[:3]:  # Show first 3 examples
            print(f"  ID {id}: {text_sample}...")

    print()
    print("=" * 80)
    response = input(f"Delete {len(gibberish_ids)} gibberish highlights? (yes/no): ")

    if response.lower() != 'yes':
        print("Aborted")
        conn.close()
        return

    # Delete gibberish highlights
    placeholders = ','.join('?' * len(gibberish_ids))
    cursor.execute(f"DELETE FROM enhanced_highlights WHERE id IN ({placeholders})", gibberish_ids)

    # Also delete their sync records
    cursor.execute(f"DELETE FROM highlight_sync_records WHERE highlight_id IN ({placeholders})", gibberish_ids)

    conn.commit()

    print(f"\n✅ Deleted {len(gibberish_ids)} gibberish highlights")
    print("=" * 80)

    conn.close()


if __name__ == "__main__":
    main()
