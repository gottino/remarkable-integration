#!/usr/bin/env python3
"""
Test script for enhanced Notion integration with markdown formatting and incremental sync.
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.integrations.notion_markdown import MarkdownToNotionConverter

def test_markdown_conversion():
    """Test the markdown to Notion block conversion."""
    print("🧪 Testing Markdown to Notion Conversion")
    print("=" * 50)
    
    converter = MarkdownToNotionConverter()
    
    # Sample text with markdown-like formatting (similar to what we saw in the database)
    test_text = """**Date: 3-12-2021**
---

## Spesen

- [x] Kommunikationsstrategie Workplace
- Onboarding Markus
  → Docs
  → list of people
  → goals + expectations

- Spesen Yannick
- Legal: Multi-Geo
- Kinderzulage
- Fix it Stelle
- [x] Bewerbungen Lead Engineer
- Review Collaboration Hub
  → User Adoption Strategy?
- [x] Stellenbeschrieb Andrea Schraner
- Web Strategy Comms
- Ende Probezeit Pascale
- [x] IT Mgt Meeting Summary"""
    
    print("📝 Input text:")
    print(test_text)
    print("\n" + "=" * 50)
    
    # Convert to Notion blocks
    blocks = converter.text_to_notion_blocks(test_text)
    
    print(f"📦 Generated {len(blocks)} Notion blocks:")
    print()
    
    for i, block in enumerate(blocks, 1):
        block_type = block['type']
        print(f"{i}. {block_type.upper()}")
        
        if block_type == 'heading_1':
            content = block['heading_1']['rich_text'][0]['text']['content']
            print(f"   Content: {content}")
        elif block_type == 'heading_2':
            content = block['heading_2']['rich_text'][0]['text']['content']
            print(f"   Content: {content}")
        elif block_type == 'heading_3':
            content = block['heading_3']['rich_text'][0]['text']['content']
            print(f"   Content: {content}")
        elif block_type == 'paragraph':
            content = block['paragraph']['rich_text'][0]['text']['content']
            print(f"   Content: {content[:100]}{'...' if len(content) > 100 else ''}")
        elif block_type == 'to_do':
            content = block['to_do']['rich_text'][0]['text']['content']
            checked = block['to_do']['checked']
            status = "✅" if checked else "☐"
            print(f"   {status} {content}")
        elif block_type == 'bulleted_list_item':
            content = block['bulleted_list_item']['rich_text'][0]['text']['content']
            print(f"   • {content}")
        elif block_type == 'numbered_list_item':
            content = block['numbered_list_item']['rich_text'][0]['text']['content']
            print(f"   1. {content}")
        elif block_type == 'divider':
            print("   ---")
        
        print()
    
    print("✅ Markdown conversion test completed!")

if __name__ == "__main__":
    test_markdown_conversion()