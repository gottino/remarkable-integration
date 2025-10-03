#!/usr/bin/env python3
"""
One-time sync script to upload existing enhanced highlights to Readwise.

This script syncs all existing enhanced highlights from the local database
to Readwise with proper book metadata and deduplication.
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
from datetime import datetime
import hashlib

async def sync_existing_highlights():
    """Sync all existing enhanced highlights to Readwise."""
    print("🔄 One-Time Readwise Sync - Existing Highlights")
    print("=" * 55)
    
    # Load config and connect to database
    config = Config()
    db_path = config.get("database.path", "./data/remarkable_pipeline.db")
    
    print(f"📁 Database: {db_path}")
    
    # Check for Readwise API key
    api_key = get_readwise_api_key()
    if not api_key:
        print("❌ No Readwise API key found")
        print("   Run: python scripts/setup_readwise.py setup")
        return False
    
    print("🔑 Readwise API key: ✅ Found")
    
    try:
        db_manager = DatabaseManager(db_path)
        
        with db_manager.get_connection_context() as conn:
            # Get all enhanced highlights with book metadata
            print(f"\n📖 Loading enhanced highlights with book metadata...")
            
            highlights = get_enhanced_highlights_with_book_info(conn, limit=None)
            
            if not highlights:
                print("   No enhanced highlights found.")
                return True
            
            print(f"   Found {len(highlights)} enhanced highlights")
            
            # Group highlights by book
            books = {}
            for highlight in highlights:
                if highlight.book_metadata:
                    key = (highlight.book_metadata.title, highlight.book_metadata.authors)
                    if key not in books:
                        books[key] = []
                    books[key].append(highlight)
            
            print(f"   Organized into {len(books)} unique books")
            
            # Setup Readwise sync target
            readwise_target = ReadwiseSyncTarget(
                access_token=api_key,
                db_connection=conn,
                author_name="reMarkable",
                default_category="books"
            )
            
            print(f"\n🚀 Starting sync to Readwise...")
            
            total_synced = 0
            total_failed = 0
            
            for (book_title, book_author), book_highlights in books.items():
                print(f"\n📚 Syncing book: \"{book_title}\" by {book_author or 'Unknown'}")
                print(f"   📝 {len(book_highlights)} highlights")
                
                book_synced = 0
                book_failed = 0
                
                # TEMP DEBUG: Only process first highlight
                for i, highlight in enumerate(book_highlights[:1], 1):
                    try:
                        # Debug: Check highlight structure
                        if i == 1:  # Log first highlight structure for debugging
                            print(f"   🔍 Debug - Highlight type: {type(highlight)}")
                            print(f"   🔍 Debug - Highlight attributes: {dir(highlight)}")
                            if hasattr(highlight, 'original_text'):
                                print(f"   🔍 Debug - Has original_text: {highlight.original_text[:50]}...")
                        
                        # Create sync item data - access attributes directly from dataclass
                        highlight_data = {
                            'text': highlight.original_text or '',
                            'corrected_text': highlight.corrected_text or '',
                            'title': highlight.title or 'Untitled',
                            'page_number': int(highlight.page_number) if highlight.page_number and str(highlight.page_number).isdigit() else None,
                            'confidence': highlight.confidence,
                            'notebook_uuid': highlight.notebook_uuid,
                            'match_score': highlight.match_score
                        }
                        
                        # Debug: Check what's being passed to sync_item
                        if i == 1:
                            print(f"   🔍 Debug - highlight_data type: {type(highlight_data)}")
                            print(f"   🔍 Debug - highlight_data keys: {highlight_data.keys()}")
                            print(f"   🔍 Debug - page_number: {highlight_data['page_number']} (type: {type(highlight_data['page_number'])})")
                        
                        # Create content hash for deduplication
                        text_for_hash = highlight.corrected_text or highlight.original_text or ''
                        content_hash = hashlib.sha256(
                            f"{highlight.notebook_uuid}:{text_for_hash}:{highlight.page_number or ''}".encode()
                        ).hexdigest()
                        
                        sync_item = SyncItem(
                            item_type=SyncItemType.HIGHLIGHT,
                            item_id=f"{highlight.highlight_id}",
                            content_hash=content_hash,
                            data=highlight_data,
                            source_table='enhanced_highlights',
                            created_at=datetime.now(),
                            updated_at=datetime.now()
                        )
                        
                        # Sync to Readwise
                        if i == 1:
                            print(f"   🔍 Debug - About to sync: {sync_item}")
                            print(f"   🔍 Debug - sync_item.data type: {type(sync_item.data)}")
                        
                        result = await readwise_target.sync_item(sync_item)
                        
                        if result.success:
                            book_synced += 1
                            total_synced += 1
                            if i % 10 == 0 or i == len(book_highlights):
                                print(f"   ✅ Synced {i}/{len(book_highlights)} highlights")
                        else:
                            book_failed += 1
                            total_failed += 1
                            print(f"   ⚠️  Failed highlight {i}: {result.error_message}")
                        
                        # Small delay to respect rate limits
                        if i % 5 == 0:
                            await asyncio.sleep(0.5)
                    
                    except Exception as e:
                        book_failed += 1
                        total_failed += 1
                        print(f"   ❌ Error syncing highlight {i}: {e}")
                        import traceback
                        print(f"   🔍 Debug - Full traceback for highlight {i}:")
                        traceback.print_exc()
                
                print(f"   📊 Book completed: {book_synced} synced, {book_failed} failed")
            
            # Summary
            print(f"\n🎉 Sync Complete!")
            print(f"   ✅ Total synced: {total_synced}")
            print(f"   ❌ Total failed: {total_failed}")
            print(f"   📚 Books processed: {len(books)}")
            
            if total_synced > 0:
                print(f"\n🔗 Check your Readwise library: https://readwise.io/library")
            
            return total_failed == 0
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

async def main():
    success = await sync_existing_highlights()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Sync interrupted")
        sys.exit(1)