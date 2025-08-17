"""
reMarkable file parser module.

Adapted from rmtool.py to fit the remarkable-integration project structure.
Handles parsing of .rm files, metadata, and content for both v6 and pre-v6 formats.
"""

import datetime
import glob
import json
import os
import os.path
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path

try:
    import rmc
    import rmscene
    VERSION_6_SUPPORT = True
except ImportError:
    VERSION_6_SUPPORT = False
    print("Warning: rmscene/rmc not available, v6 support disabled")

try:
    import PyPDF2
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("Warning: PyPDF2 not available, PDF support disabled")

# Try to import rm2svg for pre-v6 support
# Import our own rm2svg module
try:
    from .rm2svg import RmToSvgConverter
    PRE_V6_SUPPORT = True
except ImportError:
    PRE_V6_SUPPORT = False
    print("Warning: rm2svg module not available, pre-v6 support disabled")


@dataclass
class PageInfo:
    """Information about a parsed page."""
    width: float
    height: float
    xpos_delta: float = 0.0
    ypos_delta: float = 0.0


@dataclass
class RemarkableDocument:
    """Represents a reMarkable document with metadata and content."""
    uuid: str
    visible_name: str
    last_modified: datetime.datetime
    doc_type: str  # 'DocumentType' or 'CollectionType'
    parent: str
    content: Optional[Dict] = None
    metadata: Optional[Dict] = None
    children: List['RemarkableDocument'] = None
    
    def __post_init__(self):
        if self.children is None:
            self.children = []


class RemarkableParser:
    """Parser for reMarkable files and folder structure."""
    
    def __init__(self, root_dir: str, debug: bool = False):
        """
        Initialize the parser.
        
        Args:
            root_dir: Path to the reMarkable sync folder
            debug: Enable debug output
        """
        self.root_dir = Path(root_dir)
        self.debug = debug
        
    def read_metadata(self, uuid: str) -> Dict:
        """Read metadata file for a given UUID."""
        metadata_file = self.root_dir / f"{uuid}.metadata"
        try:
            with open(metadata_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            if self.debug:
                print(f"Error reading metadata for {uuid}: {e}")
            return {}
    
    def read_content(self, uuid: str) -> Dict:
        """Read content file for a given UUID."""
        content_file = self.root_dir / f"{uuid}.content"
        try:
            with open(content_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            if self.debug:
                print(f"Error reading content for {uuid}: {e}")
            return {}
    
    def read_pagedata(self, uuid: str) -> List[str]:
        """Read pagedata file for a given UUID."""
        pagedata_file = self.root_dir / f"{uuid}.pagedata"
        try:
            with open(pagedata_file, 'r') as f:
                return f.read().split()
        except FileNotFoundError:
            if self.debug:
                print(f"No pagedata found for {uuid}")
            return []
    
    def get_all_documents(self) -> List[RemarkableDocument]:
        """Get all documents from the reMarkable folder."""
        documents = []
        metadata_files = glob.glob(str(self.root_dir / "*.metadata"))
        
        for metadata_file in metadata_files:
            uuid = Path(metadata_file).stem
            metadata = self.read_metadata(uuid)
            
            if not metadata:
                continue
                
            # Convert timestamp to datetime
            last_modified = datetime.datetime.fromtimestamp(
                int(metadata.get('lastModified', 0)) / 1000
            )
            
            doc = RemarkableDocument(
                uuid=uuid,
                visible_name=metadata.get('visibleName', 'Unknown'),
                last_modified=last_modified,
                doc_type=metadata.get('type', 'Unknown'),
                parent=metadata.get('parent', ''),
                metadata=metadata
            )
            
            # Read content if it's a document
            if doc.doc_type == 'DocumentType':
                doc.content = self.read_content(uuid)
                
            documents.append(doc)
        
        return documents
    
    def build_document_tree(self, documents: List[RemarkableDocument]) -> RemarkableDocument:
        """Build a tree structure from the flat list of documents."""
        # Create a root node
        root = RemarkableDocument(
            uuid='',
            visible_name='Root',
            last_modified=datetime.datetime.now(),
            doc_type='CollectionType',
            parent=''
        )
        
        # Create a lookup dictionary
        doc_dict = {doc.uuid: doc for doc in documents}
        doc_dict[''] = root
        
        # Build the tree by assigning children to parents
        for doc in documents:
            # Skip trashed items
            if self._is_trashed(doc, doc_dict):
                continue
                
            parent_uuid = doc.parent
            if parent_uuid in doc_dict:
                doc_dict[parent_uuid].children.append(doc)
        
        # Sort children by visible name
        self._sort_tree(root)
        
        return root
    
    def _is_trashed(self, doc: RemarkableDocument, doc_dict: Dict[str, RemarkableDocument]) -> bool:
        """Check if a document or its parent is trashed."""
        if doc.parent == 'trash':
            return True
        
        if doc.parent in doc_dict:
            return self._is_trashed(doc_dict[doc.parent], doc_dict)
        
        return False
    
    def _sort_tree(self, node: RemarkableDocument):
        """Sort children in the tree alphabetically."""
        node.children.sort(key=lambda x: x.visible_name.lower())
        for child in node.children:
            self._sort_tree(child)
    
    def get_document_pages(self, uuid: str) -> List[str]:
        """Get list of page UUIDs for a document."""
        content = self.read_content(uuid)
        if not content:
            return []
        
        format_version = content.get('formatVersion', 1)
        
        if format_version == 1:
            return content.get('pages', [])
        elif format_version == 2:
            pages = content.get('cPages', {}).get('pages', [])
            return [page['id'] for page in pages if 'deleted' not in page]
        
        return []
    
    def convert_page_to_svg(self, uuid: str, page_uuid: str, output_path: str, 
                           coloured_annotations: bool = False) -> Optional[PageInfo]:
        """
        Convert a single page to SVG.
        
        Args:
            uuid: Document UUID
            page_uuid: Page UUID
            output_path: Output SVG file path
            coloured_annotations: Use colored annotations for markup
            
        Returns:
            PageInfo object with page dimensions, or None if conversion failed
        """
        page_path = self.root_dir / uuid / f"{page_uuid}.rm"
        
        if not page_path.exists():
            if self.debug:
                print(f"Page file not found: {page_path}")
            return None
        
        try:
            # Determine version
            with open(page_path, 'rb') as file:
                head_fmt = 'reMarkable .lines file, version=v'
                head = file.read(len(head_fmt)).decode()
                version = head[-1] if head[:-1] == head_fmt[:-1] else None
            
            if version == '6' and VERSION_6_SUPPORT:
                # Use rmc for v6
                rmc.rm_to_svg(str(page_path), output_path)
                # Return default page info for v6 files
                return PageInfo(
                    width=1404,  # Default reMarkable width
                    height=1872,  # Default reMarkable height
                    xpos_delta=0.0,
                    ypos_delta=0.0
                )
            elif version in ['1', '2', '3', '4', '5'] and PRE_V6_SUPPORT:
                # Use our refactored rm2svg for pre-v6
                converter = RmToSvgConverter(coloured_annotations)
                result = converter.convert_file(str(page_path), output_path)
                
                if result.success:
                    return PageInfo(width=result.width, height=result.height)
                else:
                    if self.debug:
                        print(f"Conversion failed: {result.error_message}")
                    return None
            else:
                if self.debug:
                    print(f"Unsupported version or missing converter: {version}")
                return None
                
        except Exception as e:
            if self.debug:
                print(f"Error converting page {page_uuid}: {e}")
            return None
    
    def extract_text_from_document(self, uuid: str) -> str:
        """
        Extract text from a document (placeholder for OCR functionality).
        
        This is where you would integrate OCR processing.
        """
        # This is a placeholder - you'll implement OCR here
        pages = self.get_document_pages(uuid)
        
        extracted_text = []
        for page_uuid in pages:
            # Here you would:
            # 1. Convert page to SVG using convert_page_to_svg
            # 2. Run OCR on the SVG or convert to image first
            # 3. Extract text
            extracted_text.append(f"[Text from page {page_uuid}]")
        
        return "\n".join(extracted_text)
    
    def list_documents(self, root_node: Optional[RemarkableDocument] = None, 
                      indent: int = 0) -> List[Tuple[str, RemarkableDocument]]:
        """
        List all documents in a tree structure.
        
        Returns:
            List of (indented_name, document) tuples
        """
        if root_node is None:
            documents = self.get_all_documents()
            root_node = self.build_document_tree(documents)
        
        result = []
        
        if root_node.uuid != '':  # Don't include the artificial root
            indent_str = '  ' * indent
            timestamp = root_node.last_modified.strftime("%Y%m%d-%H:%M:%S")
            display_name = f"{indent_str}{root_node.uuid} {timestamp} {root_node.visible_name}"
            result.append((display_name, root_node))
        
        for child in root_node.children:
            result.extend(self.list_documents(child, indent + 1))
        
        return result


def run_subprocess(command: str, dry_run: bool = False) -> Tuple[int, bytes, bytes]:
    """
    Run a subprocess command.
    
    Args:
        command: Command to run
        dry_run: If True, don't actually run the command
        
    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    if dry_run:
        return 0, b'stdout', b'stderr'
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=False
        )
        return result.returncode, result.stdout, result.stderr
    except Exception as e:
        return 1, b'', str(e).encode()


# Example usage and testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test the reMarkable parser")
    parser.add_argument("--root", "-r", required=True, help="Path to reMarkable sync folder")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug output")
    parser.add_argument("--list", action="store_true", help="List all documents")
    
    args = parser.parse_args()
    
    # Create parser instance
    rm_parser = RemarkableParser(args.root, debug=args.debug)
    
    if args.list:
        print("Documents in reMarkable:")
        documents_list = rm_parser.list_documents()
        for display_name, doc in documents_list:
            print(display_name)
    else:
        # Get all documents
        documents = rm_parser.get_all_documents()
        print(f"Found {len(documents)} documents")
        
        # Build tree
        root = rm_parser.build_document_tree(documents)
        print(f"Tree has {len(root.children)} top-level items")