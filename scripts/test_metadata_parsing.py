#!/usr/bin/env python3
"""
Test script for metadata parsing in Notion integration.
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.integrations.notion_sync import parse_remarkable_timestamp, parse_path_tags
from src.core.database import DatabaseManager

def test_metadata_parsing():
    """Test the metadata parsing functions."""
    
    print("🧪 Testing Metadata Parsing Functions")
    print("=" * 50)
    
    # Test timestamp parsing
    print("\n📅 Testing timestamp parsing:")
    test_timestamps = [
        "1756296635380",  # Recent timestamp
        "1600171869727",  # Older timestamp  
        "invalid",        # Invalid
        "",              # Empty
        None             # None
    ]
    
    for ts in test_timestamps:
        parsed = parse_remarkable_timestamp(ts)
        print(f"  {ts} → {parsed}")
    
    # Test path parsing
    print("\n📁 Testing path parsing:")
    test_paths = [
        "Archive/Doodle/Reset",
        "Axpo 1:1s/David", 
        "Archive/RAV/20200910 Gabriele Ottino Zeugnisse",
        "Root Level Notebook",
        "",
        None
    ]
    
    for path in test_paths:
        tags = parse_path_tags(path)
        print(f"  '{path}' → {tags}")
    
    # Test with real database data
    print("\n📊 Testing with real database data:")
    db_manager = DatabaseManager('./data/remarkable_pipeline.db')
    
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT visible_name, full_path, last_modified, last_opened
                FROM notebook_metadata 
                LIMIT 5
            ''')
            
            samples = cursor.fetchall()
            for name, path, modified, opened in samples:
                print(f"\n  📓 {name}")
                print(f"     Path: {path}")
                print(f"     Tags: {parse_path_tags(path)}")
                print(f"     Modified: {parse_remarkable_timestamp(modified)}")
                print(f"     Opened: {parse_remarkable_timestamp(opened)}")
                
    except Exception as e:
        print(f"❌ Database error: {e}")
    
    print("\n✅ Metadata parsing tests completed!")

if __name__ == "__main__":
    test_metadata_parsing()