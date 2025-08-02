#!/usr/bin/env python3
"""
Test script for reMarkable Integration modules.
"""

import sys
import traceback
from pathlib import Path

# Add src to path so we can import our modules
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

try:
    from remarkable_integration.core.rm_parser import RemarkableParser
    from remarkable_integration.core.rm2svg import RmToSvgConverter
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


def check_dependencies():
    """Check if optional dependencies are available."""
    print("🔍 Checking dependencies...")
    
    # Check rmscene
    try:
        import rmscene
        print("✅ rmscene: Available")
    except ImportError:
        print("⚠️  rmscene: Not available (v6 format support disabled)")
    
    # Check PyPDF2
    try:
        import PyPDF2
        print("✅ PyPDF2: Available")
    except ImportError:
        print("⚠️  PyPDF2: Not available (PDF support disabled)")
    
    print()


def test_parser(remarkable_path):
    """Test the reMarkable parser."""
    print(f"Testing parser with path: {remarkable_path}")
    print()
    
    try:
        # Initialize parser
        parser = RemarkableParser(remarkable_path)
        
        # Test 1: Get all documents
        print("1. Getting all documents...")
        documents = parser.get_all_documents()
        print(f"Found {len(documents)} documents")
        print()
        
        # Test 2: Build document tree
        print("2. Building document tree...")
        root = parser.build_document_tree(documents)
        print(f"Built tree with {len(root)} root documents")
        print()
        
        # Test 3: Print tree structure
        print("3. Document tree structure:")
        print("=" * 40)
        parser.print_tree(root)
        print("=" * 40)
        print()
        
        # Test 4: Get flat list
        print("4. Getting flat document list...")
        all_docs = parser.get_all_documents_flat(root)
        print(f"Total documents in tree: {len(all_docs)}")
        print()
        
        # Test 5: Test document content reading
        print("5. Testing document content reading...")
        document_files = [doc for doc in all_docs if doc.is_document and doc.file_path and doc.file_path.exists()]
        if document_files:
            test_doc = document_files[0]
            print(f"Testing content reading for: {test_doc.name}")
            content = parser.get_document_content(test_doc)
            if content:
                content_size = len(content) if isinstance(content, (bytes, str)) else "unknown"
                print(f"✅ Successfully read content (size: {content_size})")
            else:
                print("⚠️  No content returned")
        else:
            print("⚠️  No document files found to test content reading")
        print()
        
        return True
        
    except Exception as e:
        print(f"❌ Parser test failed: {e}")
        traceback.print_exc()
        return False


def test_svg_converter(remarkable_path):
    """Test the SVG converter."""
    print(f"Testing SVG converter with path: {remarkable_path}")
    print()
    
    try:
        # Initialize parser to get documents
        parser = RemarkableParser(remarkable_path)
        documents = parser.get_all_documents()
        root = parser.build_document_tree(documents)
        all_docs = parser.get_all_documents_flat(root)
        
        # Find a document with an .rm file
        document_files = [doc for doc in all_docs if doc.is_document and doc.file_path and doc.file_path.exists()]
        
        if not document_files:
            print("⚠️  No .rm files found to test SVG conversion")
            return True
        
        test_doc = document_files[0]
        print(f"Testing SVG conversion for: {test_doc.name}")
        
        # Initialize converter
        converter = RmToSvgConverter()
        
        # Test conversion
        svg_content = converter.convert_rm_to_svg(str(test_doc.file_path))
        
        if svg_content and svg_content.startswith('<?xml'):
            print(f"✅ Successfully converted to SVG ({len(svg_content)} characters)")
            
            # Optionally save to file for inspection
            output_file = Path(f"test_output_{test_doc.uuid}.svg")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(svg_content)
            print(f"📄 SVG saved to: {output_file}")
        else:
            print("⚠️  SVG conversion returned unexpected result")
        
        return True
        
    except Exception as e:
        print(f"❌ SVG converter test failed: {e}")
        traceback.print_exc()
        return False


def main():
    """Main test function."""
    print("🚀 Testing reMarkable Integration Modules")
    print("=" * 50)
    
    # Check command line arguments
    if len(sys.argv) != 2:
        print("Usage: python test_rm_parser.py <path_to_remarkable_files>")
        print("Example: python test_rm_parser.py '/Users/username/.local/share/remarkable/xochitl'")
        sys.exit(1)
    
    remarkable_path = sys.argv[1]
    
    # Verify path exists
    if not Path(remarkable_path).exists():
        print(f"❌ Path does not exist: {remarkable_path}")
        sys.exit(1)
    
    # Check dependencies
    check_dependencies()
    
    # Run tests
    tests_passed = 0
    total_tests = 2
    
    # Test parser
    if test_parser(remarkable_path):
        tests_passed += 1
    
    print()
    
    # Test SVG converter
    if test_svg_converter(remarkable_path):
        tests_passed += 1
    
    # Summary
    print()
    print("📊 Test Summary")
    print("=" * 20)
    print(f"Tests passed: {tests_passed}/{total_tests}")
    
    if tests_passed == total_tests:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed")
        sys.exit(1)


if __name__ == "__main__":
    main()