#!/usr/bin/env python3
"""
Simple test to verify database operations are working.
"""

import sys
import os
from pathlib import Path
import sqlite3

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.processors.highlight_extractor import HighlightExtractor, DatabaseManager, process_directory

def test_simple_extraction(directory_path: str):
    """Test simple extraction with debugging."""
    print(f"🧪 Testing simple extraction on: {directory_path}")
    print("=" * 50)
    
    # Create fresh database
    test_db = "simple_test.db"
    if os.path.exists(test_db):
        os.remove(test_db)
    
    # Test process_directory
    db_manager = DatabaseManager(test_db)
    results = process_directory(directory_path, db_manager)
    
    print(f"📊 Process results: {results}")
    total_reported = sum(results.values())
    print(f"🎯 Total reported by process_directory: {total_reported}")
    
    # Check database directly
    conn = db_manager.get_connection()
    cursor = conn.cursor()
    
    # Count highlights in database
    cursor.execute("SELECT COUNT(*) FROM highlights")
    total_in_db = cursor.fetchone()[0]
    print(f"💾 Total in database: {total_in_db}")
    
    # Get sample highlights
    cursor.execute("SELECT title, text, page_number FROM highlights LIMIT 5")
    samples = cursor.fetchall()
    print(f"📝 Sample highlights ({len(samples)}):")
    for i, (title, text, page) in enumerate(samples, 1):
        print(f"   {i}. '{title}' p{page}: '{text[:50]}...'")
    
    # Test retrieval method used by migration
    cursor.execute("SELECT title, text, page_number, file_name, confidence, created_at FROM highlights")
    all_highlights = cursor.fetchall()
    print(f"🔍 Direct query retrieval: {len(all_highlights)} highlights")
    
    conn.close()
    
    # Summary
    if total_reported == total_in_db:
        print("✅ SUCCESS: Reported count matches database count")
    else:
        print(f"❌ MISMATCH: Reported {total_reported} but database has {total_in_db}")
    
    return total_in_db

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python simple_database_test.py <directory_path>")
        sys.exit(1)
    
    directory_path = sys.argv[1]
    test_simple_extraction(directory_path)
