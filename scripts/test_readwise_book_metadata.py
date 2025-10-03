#!/usr/bin/env python3
"""
Test script to demonstrate Readwise sync with book metadata integration.

This script shows how enhanced highlights are now synced to Readwise with proper
book metadata including title, author, publisher, and publication date.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.database import DatabaseManager
from src.core.book_metadata import get_enhanced_highlights_with_book_info
from src.integrations.readwise_sync import ReadwiseSyncTarget
from src.core.sync_engine import SyncItem, SyncItemType
from src.utils.config import Config
from src.utils.api_keys import get_readwise_api_key

def format_readwise_highlight(highlight_data, book_metadata=None):
    """
    Simulate how ReadwiseSyncTarget formats a highlight with book metadata.
    
    This shows what would be sent to Readwise API without actually calling it.
    """
    # Start with basic highlight data
    title = highlight_data.get('title', 'Untitled Document')
    author = "reMarkable"
    category = "books"
    note_parts = []
    
    # Apply book metadata if available
    if book_metadata:
        title = book_metadata.title
        if book_metadata.authors:
            author = book_metadata.authors
        
        # Set category based on document type
        if book_metadata.document_type == 'epub':
            category = 'books'
        elif book_metadata.document_type == 'pdf':
            category = 'articles'
        
        # Add publication info to note
        if book_metadata.publisher:
            note_parts.append(f"Publisher: {book_metadata.publisher}")
        if book_metadata.publication_date:
            note_parts.append(f"Published: {book_metadata.publication_date}")
    
    # Add original text note if corrected
    if highlight_data.get('corrected_text') and highlight_data.get('original_text'):
        note_parts.append(f"Original OCR: {highlight_data.get('original_text')}")
    
    # Add confidence if available
    if highlight_data.get('confidence'):
        note_parts.append(f"OCR confidence: {highlight_data['confidence']:.1%}")
    
    return {
        "text": highlight_data.get('corrected_text', highlight_data.get('text', '')),
        "title": title,
        "author": author,
        "category": category,
        "source_type": "remarkable",
        "location": highlight_data.get('page_number'),
        "location_type": "page",
        "note": " | ".join(note_parts) if note_parts else None,
        "highlighted_at": "2024-01-01T00:00:00",  # Placeholder
        "highlight_url": f"remarkable://highlight/test",
    }

async def test_readwise_metadata_integration():
    """Test the Readwise integration with book metadata."""
    print("📚 Readwise Book Metadata Integration Test")
    print("=" * 55)
    
    # Load config and connect to database
    config = Config()
    db_path = config.get("database.path", "./data/remarkable_pipeline.db")
    
    print(f"📁 Database: {db_path}")
    
    # Check for Readwise API key
    api_key = get_readwise_api_key()
    if not api_key:
        print("⚠️  No Readwise API key found. This test will show formatted data only.")
        print("   Run: python scripts/setup_readwise.py setup")
        api_key = "test-key"  # Use placeholder for formatting test
    else:
        print("🔑 Readwise API key: ✅ Found")
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection_context() as conn:
            # Get enhanced highlights with book metadata
            print(f"\n📖 Enhanced Highlights with Book Metadata (Latest 5):")
            print("-" * 60)
            
            highlights = get_enhanced_highlights_with_book_info(conn, limit=5)
            
            if not highlights:
                print("   No enhanced highlights found with book metadata.")
                print("   💡 Run highlight extraction to generate enhanced highlights.")
                return
            
            # Create ReadwiseSyncTarget to test formatting
            readwise_target = ReadwiseSyncTarget(
                access_token=api_key,
                db_connection=conn,
                author_name="reMarkable",
                default_category="books"
            )
            
            for i, highlight in enumerate(highlights, 1):
                print(f"\n{i}. Source Highlight:")
                print(f"   📝 Text: \"{highlight.corrected_text[:80]}{'...' if len(highlight.corrected_text) > 80 else ''}\"")
                print(f"   📄 Original Title: {highlight.title}")
                if highlight.page_number:
                    print(f"   📖 Page: {highlight.page_number}")
                
                if highlight.book_metadata:
                    book = highlight.book_metadata
                    print(f"\n   📚 Book Metadata Found:")
                    print(f"      📖 Title: {book.title}")
                    if book.authors:
                        print(f"      ✍️  Author: {book.authors}")
                    if book.publisher:
                        print(f"      🏢 Publisher: {book.publisher}")
                    if book.publication_date:
                        print(f"      📅 Published: {book.publication_date}")
                    print(f"      📄 Type: {book.document_type.upper()}")
                    
                    # Show what would be sent to Readwise
                    highlight_data = {
                        'text': highlight.original_text,
                        'corrected_text': highlight.corrected_text,
                        'title': highlight.title,
                        'page_number': highlight.page_number,
                        'confidence': highlight.confidence,
                        'notebook_uuid': highlight.notebook_uuid
                    }
                    
                    readwise_format = format_readwise_highlight(highlight_data, book)
                    
                    print(f"\n   📤 Readwise Format:")
                    print(f"      📖 Title: \"{readwise_format['title']}\"")
                    print(f"      ✍️  Author: \"{readwise_format['author']}\"")
                    print(f"      🏷️  Category: \"{readwise_format['category']}\"")
                    if readwise_format['note']:
                        print(f"      📝 Note: \"{readwise_format['note']}\"")
                    print(f"      📍 Location: {readwise_format['location']} ({readwise_format['location_type']})")
                else:
                    print(f"\n   ⚠️  No book metadata available")
                    print(f"      📤 Would use: Title=\"{highlight.title}\", Author=\"reMarkable\"")
            
            # Show statistics
            print(f"\n📊 Integration Statistics:")
            print("-" * 30)
            
            with_metadata = sum(1 for h in highlights if h.book_metadata)
            print(f"📖 Highlights with book metadata: {with_metadata}/{len(highlights)}")
            print(f"📚 Book titles found: {len(set(h.book_metadata.title for h in highlights if h.book_metadata))}")
            print(f"✍️  Authors found: {len(set(h.book_metadata.authors for h in highlights if h.book_metadata and h.book_metadata.authors))}")
            
            # Show unique books that would be created in Readwise
            unique_books = {}
            for h in highlights:
                if h.book_metadata:
                    key = (h.book_metadata.title, h.book_metadata.authors)
                    if key not in unique_books:
                        unique_books[key] = {
                            'title': h.book_metadata.title,
                            'author': h.book_metadata.authors or 'Unknown',
                            'category': 'books' if h.book_metadata.document_type == 'epub' else 'articles',
                            'type': h.book_metadata.document_type,
                            'publisher': h.book_metadata.publisher,
                            'published': h.book_metadata.publication_date
                        }
            
            if unique_books:
                print(f"\n📚 Books that would be created/updated in Readwise:")
                print("-" * 50)
                for book_data in unique_books.values():
                    author = book_data['author'] if book_data['author'] else 'Unknown'
                    print(f"   📖 \"{book_data['title']}\" by {author}")
                    print(f"      🏷️  Category: {book_data['category']} ({book_data['type'].upper()})")
                    if book_data['publisher']:
                        print(f"      🏢 Publisher: {book_data['publisher']}")
                    if book_data['published']:
                        print(f"      📅 Published: {book_data['published']}")
            
            print(f"\n✅ Integration test completed!")
            print(f"   💡 Enhanced highlights will now sync to Readwise with proper book metadata")
            if api_key != "test-key":
                print(f"   🚀 To actually sync: Use the unified sync system with Readwise enabled")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

async def main():
    await test_readwise_metadata_integration()

if __name__ == "__main__":
    asyncio.run(main())