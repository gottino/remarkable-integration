#!/usr/bin/env python3
"""
Quick script to check what methods are available in RmToSvgConverter.
"""

import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

try:
    from remarkable_integration.core.rm2svg import RmToSvgConverter
    
    print("🔍 RmToSvgConverter methods:")
    converter = RmToSvgConverter()
    
    methods = [method for method in dir(converter) if not method.startswith('_')]
    for method in methods:
        print(f"  - {method}")
        
    print(f"\nTotal methods: {len(methods)}")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
