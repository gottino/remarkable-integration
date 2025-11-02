#!/usr/bin/env python3
"""
Reprocess existing highlights in database with PDF text matching.

Reads highlights from enhanced_highlights table and updates corrected_text
by matching original_text against source PDFs.
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, Tuple
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.processors.pdf_text_matcher import PDFTextMatcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_pdf_path_for_highlight(db_connection: sqlite3.Connection, source_file: str) -> Optional[str]:
    """
    Get PDF path for a highlight's source file.

    Args:
        db_connection: Database connection
        source_file: Path to the .content file

    Returns:
        Path to PDF file or None if not found
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

    # Look for PDF in the UUID subdirectory
    # Path format: .../uuid/uuid.pdf
    pdf_path = doc_dir / content_id / f"{content_id}.pdf"

    if pdf_path.exists():
        return str(pdf_path)

    # Try without subdirectory (direct in parent dir)
    pdf_path = doc_dir / f"{content_id}.pdf"
    if pdf_path.exists():
        return str(pdf_path)

    return None


def reprocess_highlights(db_path: str, dry_run: bool = True):
    """
    Reprocess highlights with PDF text matching.

    Args:
        db_path: Path to database
        dry_run: If True, don't update database, just show what would be done
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all highlights
    cursor.execute("""
        SELECT id, source_file, title, original_text, corrected_text,
               page_number, confidence
        FROM enhanced_highlights
        ORDER BY title, page_number
    """)

    highlights = cursor.fetchall()
    logger.info(f"Found {len(highlights)} highlights in database")

    if not highlights:
        logger.info("No highlights to process")
        return

    # Group by source document to avoid reopening PDFs
    from collections import defaultdict
    highlights_by_pdf = defaultdict(list)

    for highlight in highlights:
        pdf_path = get_pdf_path_for_highlight(conn, highlight['source_file'])
        if pdf_path:
            highlights_by_pdf[pdf_path].append(highlight)
        else:
            logger.warning(f"No PDF found for highlight ID {highlight['id']} (source: {highlight['source_file']})")

    logger.info(f"Found {len(highlights_by_pdf)} unique PDF documents")

    # Process each PDF's highlights
    total_matched = 0
    total_updated = 0

    for pdf_path, pdf_highlights in highlights_by_pdf.items():
        logger.info(f"\n📖 Processing PDF: {Path(pdf_path).name}")
        logger.info(f"   {len(pdf_highlights)} highlights to match")

        try:
            matcher = PDFTextMatcher(pdf_path, fuzzy_threshold=65)

            for highlight in pdf_highlights:
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

                # Use original_text as the search text (corrupted version)
                search_text = highlight['original_text'] or highlight['corrected_text']

                # Try to match against PDF
                result = matcher.match_highlight(
                    corrupted_text=search_text,
                    page_num=page_num,
                    search_offset=2,
                    expand_sentences=True
                )

                if result:
                    clean_text, score = result
                    total_matched += 1

                    # Check if text is different from current corrected_text
                    if clean_text != highlight['corrected_text']:
                        total_updated += 1

                        logger.info(f"   ✓ Match for ID {highlight['id']} (page {page_num}, score: {score})")
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
                    logger.debug(f"   ✗ No match for ID {highlight['id']} (page {page_num})")

        except Exception as e:
            logger.error(f"   Error processing PDF {pdf_path}: {e}")
            continue

    # Commit changes
    if not dry_run:
        conn.commit()
        logger.info(f"\n✅ Database updated!")
    else:
        logger.info(f"\n🔍 DRY RUN - No changes made to database")

    logger.info(f"\n📊 Summary:")
    logger.info(f"   Total highlights: {len(highlights)}")
    logger.info(f"   PDF matches found: {total_matched}")
    logger.info(f"   Highlights that would be updated: {total_updated}")

    conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reprocess highlights with PDF text matching")
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
