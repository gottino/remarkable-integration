#!/usr/bin/env python3
"""
Script to build reMarkable folder hierarchy from .metadata files.
Reads all .metadata files and constructs the full folder path for each notebook.
"""

import json
import sys
import logging
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class RemarkableItem:
    """Represents a reMarkable item (folder or document)."""
    uuid: str
    name: str
    parent: Optional[str]
    item_type: str  # 'CollectionType' for folders, 'DocumentType' for documents
    path: Optional[str] = None

class FolderHierarchyBuilder:
    """Builds the folder hierarchy from reMarkable metadata files."""
    
    def __init__(self, remarkable_dir: str):
        self.remarkable_dir = Path(remarkable_dir)
        self.items: Dict[str, RemarkableItem] = {}
        self.paths_cache: Dict[str, str] = {}
    
    def scan_metadata_files(self) -> None:
        """Scan all .metadata files in the reMarkable directory."""
        logger.info(f"Scanning metadata files in: {self.remarkable_dir}")
        
        metadata_files = list(self.remarkable_dir.glob("*.metadata"))
        logger.info(f"Found {len(metadata_files)} metadata files")
        
        for metadata_file in metadata_files:
            try:
                uuid = metadata_file.stem
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                item = RemarkableItem(
                    uuid=uuid,
                    name=metadata.get('visibleName', 'Unknown'),
                    parent=metadata.get('parent', ''),  # Empty string means root
                    item_type=metadata.get('type', 'Unknown')
                )
                
                # Convert empty parent to None for root items
                if item.parent == '':
                    item.parent = None
                    
                self.items[uuid] = item
                
                logger.debug(f"Loaded: {item.name} (UUID: {uuid[:8]}..., Parent: {item.parent[:8] if item.parent else 'ROOT'})")
                
            except Exception as e:
                logger.warning(f"Error reading {metadata_file}: {e}")
        
        logger.info(f"Successfully loaded {len(self.items)} items")
    
    def build_path(self, uuid: str) -> str:
        """Build the full path for an item by traversing up the parent chain."""
        if uuid in self.paths_cache:
            return self.paths_cache[uuid]
        
        if uuid not in self.items:
            logger.warning(f"UUID {uuid} not found in items")
            return f"<UNKNOWN>/{uuid}"
        
        item = self.items[uuid]
        
        # Base case: root item
        if item.parent is None:
            path = item.name
        else:
            # Recursive case: get parent path and append this item's name
            parent_path = self.build_path(item.parent)
            path = f"{parent_path}/{item.name}"
        
        # Cache the result
        self.paths_cache[uuid] = path
        return path
    
    def build_all_paths(self) -> Dict[str, str]:
        """Build paths for all items."""
        logger.info("Building full paths for all items...")
        
        for uuid in self.items:
            self.build_path(uuid)
        
        return self.paths_cache.copy()
    
    def get_documents_with_paths(self) -> Dict[str, str]:
        """Get only documents (not folders) with their full paths."""
        documents = {}
        
        for uuid, item in self.items.items():
            if item.item_type == 'DocumentType':
                path = self.build_path(uuid)
                documents[uuid] = path
        
        return documents
    
    def get_folders_with_paths(self) -> Dict[str, str]:
        """Get only folders with their full paths."""
        folders = {}
        
        for uuid, item in self.items.items():
            if item.item_type == 'CollectionType':
                path = self.build_path(uuid)
                folders[uuid] = path
        
        return folders
    
    def print_hierarchy(self, max_depth: int = None) -> None:
        """Print the folder hierarchy in a tree format."""
        logger.info("Folder Hierarchy:")
        
        # Find root items (no parent)
        root_items = [item for item in self.items.values() if item.parent is None]
        
        # Sort by name for consistent output
        root_items.sort(key=lambda x: x.name.lower())
        
        for root_item in root_items:
            self._print_item(root_item, 0, max_depth)
    
    def _print_item(self, item: RemarkableItem, depth: int, max_depth: Optional[int]) -> None:
        """Recursively print an item and its children."""
        if max_depth is not None and depth > max_depth:
            return
        
        indent = "  " * depth
        item_icon = "📁" if item.item_type == 'CollectionType' else "📄"
        print(f"{indent}{item_icon} {item.name}")
        
        # Find children
        children = [item for item in self.items.values() if item.parent == item.uuid]
        children.sort(key=lambda x: (x.item_type != 'CollectionType', x.name.lower()))  # Folders first, then docs
        
        for child in children:
            self._print_item(child, depth + 1, max_depth)
    
    def export_to_json(self, output_file: str) -> None:
        """Export the hierarchy to a JSON file."""
        export_data = {
            'metadata': {
                'remarkable_dir': str(self.remarkable_dir),
                'total_items': len(self.items),
                'documents': len([i for i in self.items.values() if i.item_type == 'DocumentType']),
                'folders': len([i for i in self.items.values() if i.item_type == 'CollectionType'])
            },
            'documents': self.get_documents_with_paths(),
            'folders': self.get_folders_with_paths(),
            'all_items': {
                uuid: {
                    'name': item.name,
                    'type': item.item_type,
                    'parent': item.parent,
                    'path': self.build_path(uuid)
                }
                for uuid, item in self.items.items()
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"Hierarchy exported to: {output_file}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python build_folder_hierarchy.py <remarkable_directory> [output.json]")
        print("Example: python build_folder_hierarchy.py /Users/name/reMarkable")
        sys.exit(1)
    
    remarkable_dir = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "remarkable_hierarchy.json"
    
    if not Path(remarkable_dir).exists():
        logger.error(f"Directory not found: {remarkable_dir}")
        sys.exit(1)
    
    # Build hierarchy
    builder = FolderHierarchyBuilder(remarkable_dir)
    builder.scan_metadata_files()
    builder.build_all_paths()
    
    # Print summary
    documents = builder.get_documents_with_paths()
    folders = builder.get_folders_with_paths()
    
    logger.info(f"\n📊 Summary:")
    logger.info(f"   📁 Folders: {len(folders)}")
    logger.info(f"   📄 Documents: {len(documents)}")
    logger.info(f"   📋 Total items: {len(builder.items)}")
    
    # Print hierarchy (limited depth for readability)
    print("\n🌳 Folder Structure (max depth 3):")
    builder.print_hierarchy(max_depth=3)
    
    # Show some example document paths
    print(f"\n📄 Example document paths:")
    for i, (uuid, path) in enumerate(list(documents.items())[:5]):
        print(f"   {uuid[:8]}... -> {path}")
    
    if len(documents) > 5:
        print(f"   ... and {len(documents) - 5} more documents")
    
    # Export to JSON
    builder.export_to_json(output_file)

if __name__ == "__main__":
    main()