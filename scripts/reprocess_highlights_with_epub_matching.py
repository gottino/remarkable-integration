#!/usr/bin/env python3
"""
Reprocess existing highlights in database with EPUB text matching.

Reads highlights from enhanced_highlights table and updates corrected_text
by matching original_text against source EPUBs.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.epub_text_matcher import EPUBTextMatcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_epub_path_for_highlight(db_connection: sqlite3.Connection, source_file: str) -> Optional[str]:
    """
    Get EPUB path for a highlight's source file.

    Args:
        db_connection: Database connection
        source_file: Path to the .content file

    Returns:
        Path to EPUB file or None if not found
    """
    # Extract content_id from source_file path
    # source_file format: .../uuid.content
    source_path = Path(source_file)

    # Get the UUID from the filename (remove .content extension)
    if source_path.suffix == '.content':
        content_id = source_path.stem
        doc_dir = source_path.parent
    else:
        # Fallback for other formats
        content_id = source_path.name
        doc_dir = source_path.parent if source_path.is_file() else source_path

    # Look for EPUB in the UUID subdirectory
    # Path format: .../uuid/uuid.epub
    epub_path = doc_dir / content_id / f"{content_id}.epub"

    if epub_path.exists():
        return str(epub_path)

    # Try without subdirectory (direct in parent dir)
    epub_path = doc_dir / f"{content_id}.epub"
    if epub_path.exists():
        return str(epub_path)

    return None


def reprocess_highlights(db_path: str, dry_run: bool = True):
    """
    Reprocess highlights with EPUB text matching.

    Args:
        db_path: Path to database
        dry_run: If True, don't update database, just show what would be done
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all highlights from EPUBs only, with total pages per document
    cursor.execute("""
        SELECT h.id, h.source_file, h.title, h.original_text, h.corrected_text,
               h.page_number, h.confidence, h.notebook_uuid,
               (SELECT MAX(CAST(page_number AS INTEGER))
                FROM enhanced_highlights h2
                WHERE h2.notebook_uuid = h.notebook_uuid
                AND h2.page_number <> 'Unknown') as total_pages
        FROM enhanced_highlights h
        JOIN notebook_metadata n ON h.notebook_uuid = n.notebook_uuid
        WHERE n.document_type = 'epub'
        ORDER BY h.title, h.page_number
    """)

    highlights = cursor.fetchall()
    logger.info(f"Found {len(highlights)} EPUB highlights in database")

    if not highlights:
        logger.info("No EPUB highlights to process")
        return

    # Group by source document to avoid reopening EPUBs
    from collections import defaultdict
    highlights_by_epub = defaultdict(list)

    for highlight in highlights:
        epub_path = get_epub_path_for_highlight(conn, highlight['source_file'])
        if epub_path:
            highlights_by_epub[epub_path].append(highlight)
        else:
            logger.warning(f"No EPUB found for highlight ID {highlight['id']} (source: {highlight['source_file']})")

    logger.info(f"Found {len(highlights_by_epub)} unique EPUB documents")

    # Process each EPUB's highlights
    total_matched = 0
    total_updated = 0

    for epub_path, epub_highlights in highlights_by_epub.items():
        logger.info(f"\n📖 Processing EPUB: {Path(epub_path).name}")
        logger.info(f"   {len(epub_highlights)} highlights to match")

        try:
            matcher = EPUBTextMatcher(epub_path, fuzzy_threshold=65)

            # Get total pages for this EPUB (from first highlight)
            total_pages = epub_highlights[0]['total_pages'] if epub_highlights else 317  # fallback

            for highlight in epub_highlights:
                # Parse page number
                page_num_str = highlight['page_number']
                if page_num_str == "Unknown":
                    logger.debug(f"   Skipping highlight ID {highlight['id']}: unknown page number")
                    continue

                try:
                    page_num = int(page_num_str)
                except (ValueError, TypeError):
                    logger.debug(f"   Skipping highlight ID {highlight['id']}: invalid page number '{page_num_str}'")
                    continue

                # Use original_text as the search text (corrupted version from reMarkable OCR)
                search_text = highlight['original_text'] or highlight['corrected_text']

                # Try to match against EPUB using the API we built
                result = matcher.match_highlight(
                    pdf_text=search_text,  # The OCR'd text from reMarkable
                    pdf_page=page_num,     # Page number in reMarkable's pagination
                    total_pdf_pages=total_pages,  # Total pages in reMarkable's pagination
                    expand_sentences=True,
                    window_size=0.10  # Search ±10% around estimated position
                )

                if result:
                    clean_text, score = result

                    # Validate that the found text is actually similar to the input
                    # (prevents false matches in large search windows)
                    from fuzzywuzzy import fuzz
                    similarity = fuzz.ratio(search_text[:100], clean_text[:100])

                    # Use thresholds from the original pipeline: score >= 85 and similarity >= 70
                    if score >= 85 and similarity >= 70:
                        total_matched += 1

                        # Check if text is different from current corrected_text
                        if clean_text != highlight['corrected_text']:
                            total_updated += 1

                            logger.info(f"   ✓ Match for ID {highlight['id']} (page {page_num}, score: {score}, sim: {similarity})")
                            logger.info(f"      Old: {highlight['corrected_text'][:80]}...")
                            logger.info(f"      New: {clean_text[:80]}...")

                            if not dry_run:
                                # Update database
                                cursor.execute("""
                                    UPDATE enhanced_highlights
                                    SET corrected_text = ?,
                                        confidence = ?
                                    WHERE id = ?
                                """, (clean_text, score / 100.0, highlight['id']))
                        else:
                            logger.debug(f"   = ID {highlight['id']}: text unchanged")
                    else:
                        logger.debug(f"   ✗ Match rejected for ID {highlight['id']}: score={score}, similarity={similarity}")
                else:
                    logger.debug(f"   ✗ No match for ID {highlight['id']} (page {page_num})")

        except Exception as e:
            logger.error(f"   Error processing EPUB {epub_path}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            continue

    # Commit changes
    if not dry_run:
        conn.commit()
        logger.info(f"\n✅ Database updated!")
    else:
        logger.info(f"\n🔍 DRY RUN - No changes made to database")

    logger.info(f"\n📊 Summary:")
    logger.info(f"   Total EPUB highlights: {len(highlights)}")
    logger.info(f"   EPUB matches found: {total_matched}")
    logger.info(f"   Highlights that would be updated: {total_updated}")

    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reprocess highlights with EPUB text matching")
    parser.add_argument(
        "--db",
        default="data/remarkable_pipeline.db",
        help="Path to database (default: data/remarkable_pipeline.db)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually update the database (default is dry-run)"
    )

    args = parser.parse_args()

    if args.live:
        logger.info("🔴 LIVE MODE - Database will be updated")
    else:
        logger.info("🔍 DRY RUN MODE - No changes will be made")

    reprocess_highlights(args.db, dry_run=not args.live)
