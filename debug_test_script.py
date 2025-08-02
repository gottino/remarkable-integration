#!/usr/bin/env python3
"""
Debug test script for reMarkable Integration modules.
"""

import sys
import traceback
import json
from pathlib import Path

# Add src to path so we can import our modules
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

try:
    from remarkable_integration.core.rm_parser import RemarkableParser, RemarkableDocument
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


def debug_documents(remarkable_path):
    """Debug the document structure to find the recursion issue."""
    print(f"🔍 Debugging documents in: {remarkable_path}")
    print("=" * 60)
    
    parser = RemarkableParser(remarkable_path)
    
    # Step 1: Get all documents
    print("1. Getting all documents...")
    documents = parser.get_all_documents()
    print(f"Found {len(documents)} documents")
    print()
    
    # Step 2: Analyze the document structure
    print("2. Analyzing document relationships...")
    doc_dict = {doc.uuid: doc for doc in documents}
    
    print(f"Document UUIDs and their parents:")
    for doc in documents:
        parent_name = "None"
        if doc.parent and doc.parent in doc_dict:
            parent_name = doc_dict[doc.parent].name
        elif doc.parent:
            parent_name = f"MISSING: {doc.parent}"
        
        print(f"  {doc.uuid[:8]}... '{doc.name}' -> parent: {parent_name}")
    print()
    
    # Step 3: Check for circular references
    print("3. Checking for circular references...")
    
    def find_circular_refs(doc_uuid, visited_path):
        """Find circular references in parent chain."""
        if doc_uuid in visited_path:
            return visited_path + [doc_uuid]  # Found a cycle
        
        if not doc_uuid or doc_uuid not in doc_dict:
            return None  # End of chain
        
        doc = doc_dict[doc_uuid]
        if not doc.parent:
            return None  # Reached root
        
        return find_circular_refs(doc.parent, visited_path + [doc_uuid])
    
    circular_refs = []
    for doc in documents:
        cycle = find_circular_refs(doc.uuid, [])
        if cycle:
            circular_refs.append(cycle)
    
    if circular_refs:
        print("❌ Found circular references:")
        for i, cycle in enumerate(circular_refs):
            print(f"  Cycle {i+1}: {' -> '.join([doc_dict[uuid].name if uuid in doc_dict else uuid for uuid in cycle])}")
    else:
        print("✅ No circular references found")
    print()
    
    # Step 4: Check for orphaned parents
    print("4. Checking for orphaned parent references...")
    orphaned = []
    for doc in documents:
        if doc.parent and doc.parent != "" and doc.parent not in doc_dict:
            orphaned.append((doc, doc.parent))
    
    if orphaned:
        print(f"⚠️  Found {len(orphaned)} documents with missing parents:")
        for doc, parent_uuid in orphaned:
            print(f"  '{doc.name}' -> missing parent: {parent_uuid}")
    else:
        print("✅ All parent references are valid")
    print()
    
    # Step 5: Try to build tree with detailed logging
    print("5. Attempting to build tree with debug logging...")
    
    class DebugParser(RemarkableParser):
        def _is_trashed_safe(self, doc, doc_dict, visited=None):
            if visited is None:
                visited = set()
            
            print(f"    Checking if '{doc.name}' ({doc.uuid[:8]}...) is trashed. Visited: {len(visited)} docs")
            
            # If we've already visited this document, there's a cycle
            if doc.uuid in visited:
                print(f"    ❌ CYCLE DETECTED at '{doc.name}' - treating as not trashed")
                return False
            
            # Check if this document is explicitly trashed
            if doc.name == "trash" or doc.visible_name == "trash":
                print(f"    ✅ '{doc.name}' is explicitly trashed")
                return True
            
            # If no parent, it's not trashed
            if not doc.parent or doc.parent == "":
                print(f"    ✅ '{doc.name}' has no parent - not trashed")
                return False
            
            # Add this document to visited set
            new_visited = visited.copy()
            new_visited.add(doc.uuid)
            
            # Check parent recursively
            parent_doc = doc_dict.get(doc.parent)
            if parent_doc:
                print(f"    ➡️  Checking parent '{parent_doc.name}' of '{doc.name}'")
                return self._is_trashed_safe(parent_doc, doc_dict, new_visited)
            else:
                print(f"    ⚠️  Parent {doc.parent} not found for '{doc.name}' - treating as not trashed")
                return False
    
    debug_parser = DebugParser(remarkable_path)
    
    try:
        print("  Building tree...")
        root_docs = debug_parser.build_document_tree(documents)
        print(f"✅ Successfully built tree with {len(root_docs)} root documents")
        
        # Print the tree
        print("\n📁 Document tree:")
        debug_parser.print_tree(root_docs)
        
    except RecursionError as e:
        print(f"❌ Recursion error during tree building: {e}")
        return False
    except Exception as e:
        print(f"❌ Other error during tree building: {e}")
        traceback.print_exc()
        return False
    
    return True


def main():
    """Main debug function."""
    print("🚀 Debugging reMarkable Integration - Recursion Issue")
    print("=" * 60)
    
    # Check command line arguments
    if len(sys.argv) != 2:
        print("Usage: python debug_test_rm_parser.py <path_to_remarkable_files>")
        sys.exit(1)
    
    remarkable_path = sys.argv[1]
    
    # Verify path exists
    if not Path(remarkable_path).exists():
        print(f"❌ Path does not exist: {remarkable_path}")
        sys.exit(1)
    
    # Debug the documents
    if debug_documents(remarkable_path):
        print("\n🎉 Debug completed successfully!")
    else:
        print("\n❌ Debug failed - see output above for details")


if __name__ == "__main__":
    main()