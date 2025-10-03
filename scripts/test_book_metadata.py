#!/usr/bin/env python3
"""
Test script to demonstrate book metadata integration with enhanced highlights.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import DatabaseManager
from src.core.book_metadata import get_enhanced_highlights_with_book_info, get_reading_library_overview
from src.utils.config import Config

def main():
    print("📚 Book Metadata Integration Test")
    print("=" * 50)
    
    # Load config and connect to database
    config = Config()
    db_path = config.get("database.path", "./data/remarkable_pipeline.db")
    
    print(f"📁 Database: {db_path}")
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection_context() as conn:
            # Test 1: Get reading library overview
            print("\n📊 Reading Library Overview:")
            print("-" * 30)
            
            overview = get_reading_library_overview(conn)
            stats = overview.get('stats', {})
            
            print(f"📖 Books with highlights: {stats.get('books_with_highlights', 0)}")
            print(f"💡 Total highlights: {stats.get('total_highlights', 0)}")
            print(f"📚 EPUB books: {stats.get('epub_books', 0)}")
            print(f"📄 PDF books: {stats.get('pdf_books', 0)}")
            
            # Show top authors
            top_authors = stats.get('top_authors', [])
            if top_authors:
                print(f"\n✍️ Top Authors by Highlights:")
                for i, author_info in enumerate(top_authors, 1):
                    print(f"   {i}. {author_info['author']} ({author_info['highlights']} highlights)")
            
            # Show recent reading
            recent_reading = stats.get('recent_reading', [])
            if recent_reading:
                print(f"\n🕒 Recent Reading Activity (Last 30 days):")
                for book in recent_reading:
                    author = f" by {book['author']}" if book['author'] else ""
                    print(f"   📖 {book['title']}{author} ({book['highlights']} highlights)")
            
            # Test 2: Get enhanced highlights with metadata
            print(f"\n💡 Enhanced Highlights with Book Metadata (Latest 10):")
            print("-" * 50)
            
            highlights = get_enhanced_highlights_with_book_info(conn, limit=10)
            
            for i, highlight in enumerate(highlights, 1):
                print(f"\n{i}. Highlight from: {highlight.title}")
                
                if highlight.book_metadata:
                    book = highlight.book_metadata
                    print(f"   📚 Book: {book.title}")
                    if book.authors:
                        print(f"   ✍️  Author: {book.authors}")
                    if book.publisher:
                        print(f"   🏢 Publisher: {book.publisher}")
                    if book.publication_date:
                        print(f"   📅 Published: {book.publication_date}")
                    if book.cover_image_path:
                        cover_exists = Path(book.cover_image_path).exists()
                        print(f"   🖼️  Cover: {'✅ Available' if cover_exists else '❌ Missing'} ({book.cover_image_path})")
                    print(f"   📄 Type: {book.document_type.upper()}")
                    if highlight.page_number:
                        print(f"   📖 Page: {highlight.page_number}")
                else:
                    print(f"   ⚠️  No book metadata available")
                
                # Show highlight text (truncated)
                text = highlight.corrected_text[:100] + "..." if len(highlight.corrected_text) > 100 else highlight.corrected_text
                print(f"   💬 Text: \"{text}\"")
                
                if highlight.match_score:
                    print(f"   🎯 Match Score: {highlight.match_score:.1f}")
            
            if not highlights:
                print("   No enhanced highlights found with notebook associations.")
                print("   💡 Run the highlight extraction process to generate enhanced highlights.")
            
            # Test 3: Show books with highlights
            print(f"\n📚 Books with Highlights:")
            print("-" * 30)
            
            books_with_highlights = overview.get('books_with_highlights', [])
            for book in books_with_highlights[:10]:  # Show top 10
                author = f" by {book['authors']}" if book['authors'] else ""
                cover_status = "🖼️" if book['cover_image_path'] and Path(book['cover_image_path']).exists() else "📄"
                print(f"   {cover_status} {book['title']}{author} ({book['highlight_count']} highlights)")
            
            if not books_with_highlights:
                print("   No books with highlights found.")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()