#!/usr/bin/env python3
"""
Notebook PDF Converter - converts reMarkable notebooks to multi-page PDFs.
Groups all pages from the same notebook into single PDF files.
"""

import sys
import json
import tempfile
from pathlib import Path
import traceback
import subprocess

# Add src to path so we can import our modules
project_root = Path(__file__).parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

try:
    from remarkable_integration.core.rm2svg import RmToSvgConverter
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)

# Check for PDF merging capability
try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
    print("🔧 Found PyPDF2 for PDF merging")
except ImportError:
    PYPDF2_AVAILABLE = False
    print("⚠️  PyPDF2 not available - install with: poetry add PyPDF2")

# Check for rsvg-convert
try:
    import shutil
    RSVG_CONVERT_AVAILABLE = shutil.which('rsvg-convert') is not None
    if RSVG_CONVERT_AVAILABLE:
        print("🔧 Found rsvg-convert for SVG to PDF conversion")
    else:
        print("❌ rsvg-convert not found - needed for PDF generation")
        sys.exit(1)
except ImportError:
    RSVG_CONVERT_AVAILABLE = False


def get_document_name(metadata_file):
    """Get the document name from metadata file."""
    try:
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        return metadata.get('visibleName', metadata_file.stem)
    except Exception as e:
        print(f"⚠️  Could not read metadata for {metadata_file.name}: {e}")
        return metadata_file.stem


def read_content_file(content_file):
    """Read and parse a .content file to get page information."""
    try:
        with open(content_file, 'r', encoding='utf-8') as f:
            content = json.load(f)
        return content
    except Exception as e:
        print(f"⚠️  Could not read content file {content_file}: {e}")
        return None


def safe_filename(name):
    """Convert a string to a safe filename."""
    safe_chars = []
    for char in name:
        if char.isalnum() or char in ' -_()[]':
            safe_chars.append(char)
        else:
            safe_chars.append('_')
    
    safe_name = ''.join(safe_chars).strip()
    
    # Remove excessive underscores and spaces
    while '__' in safe_name:
        safe_name = safe_name.replace('__', '_')
    while '  ' in safe_name:
        safe_name = safe_name.replace('  ', ' ')
    
    return safe_name.strip('_').strip()


def svg_to_pdf_rsvg_convert(svg_file, pdf_file):
    """Convert SVG to PDF using rsvg-convert."""
    try:
        width_mm = 157  # Standard reMarkable page width in mm
        height_mm = 210  # Standard reMarkable page height in mm
        
        command = [
            'rsvg-convert',
            '--format=pdf',
            f'--width={width_mm}mm',
            f'--height={height_mm}mm',
            str(svg_file)
        ]
        
        result = subprocess.run(command, capture_output=True, timeout=30)
        
        if result.returncode == 0:
            with open(pdf_file, 'wb') as f:
                f.write(result.stdout)
            return True
        else:
            print(f"    ❌ rsvg-convert error: {result.stderr.decode()}")
            return False
            
    except Exception as e:
        print(f"    ❌ rsvg-convert conversion failed: {e}")
        return False


def find_notebooks(input_path):
    """Find all notebook documents (not individual pages)."""
    input_path = Path(input_path)
    notebooks = []
    
    # Find all .metadata files
    for metadata_file in input_path.rglob("*.metadata"):
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # Only process DocumentType (not CollectionType folders)
            if metadata.get('type') == 'DocumentType':
                uuid = metadata_file.stem
                doc_name = metadata.get('visibleName', uuid)
                
                # Check if this document has a .content file (indicates it's a notebook)
                content_file = metadata_file.with_suffix('.content')
                if content_file.exists():
                    notebooks.append({
                        'uuid': uuid,
                        'name': doc_name,
                        'metadata_file': metadata_file,
                        'content_file': content_file,
                        'metadata': metadata
                    })
        except Exception as e:
            print(f"⚠️  Error reading {metadata_file}: {e}")
            continue
    
    return notebooks


def convert_notebook_to_pdf(notebook, input_path, output_path, converter):
    """Convert a complete notebook (all pages) to a single PDF."""
    
    uuid = notebook['uuid']
    doc_name = notebook['name']
    content_file = notebook['content_file']
    
    print(f"📖 Converting notebook: {doc_name}")
    
    # Read content file to get page list
    content = read_content_file(content_file)
    if not content:
        print(f"    ❌ Could not read content file")
        return False
    
    # Get page list based on format version
    page_uuid_list = []
    if content.get('formatVersion') == 1:
        page_uuid_list = content.get('pages', [])
    elif content.get('formatVersion') == 2:
        pages = content.get('cPages', {}).get('pages', [])
        page_uuid_list = [page['id'] for page in pages if 'deleted' not in page]
    else:
        print(f"    ⚠️  Unknown format version: {content.get('formatVersion')}")
        return False
    
    if not page_uuid_list:
        print(f"    ⚠️  No pages found in notebook")
        return False
    
    print(f"    📄 Found {len(page_uuid_list)} pages")
    
    # Create temporary directory for page PDFs
    with tempfile.TemporaryDirectory(prefix='notebook_converter_') as tmpdir:
        tmpdir = Path(tmpdir)
        page_pdfs = []
        
        # Convert each page to PDF
        for page_num, page_uuid in enumerate(page_uuid_list, 1):
            # Find the .rm file for this page
            page_rm_file = input_path / uuid / f"{page_uuid}.rm"
            
            if not page_rm_file.exists():
                print(f"    ⚠️  Page {page_num} .rm file not found: {page_rm_file}")
                continue
            
            print(f"    🔄 Converting page {page_num}/{len(page_uuid_list)}")
            
            try:
                # Convert .rm to SVG
                page_svg = tmpdir / f"page_{page_num:03d}.svg"
                converter.convert_file(str(page_rm_file), str(page_svg))
                
                if not page_svg.exists():
                    print(f"    ❌ Failed to create SVG for page {page_num}")
                    continue
                
                # Convert SVG to PDF
                page_pdf = tmpdir / f"page_{page_num:03d}.pdf"
                if svg_to_pdf_rsvg_convert(page_svg, page_pdf):
                    page_pdfs.append(page_pdf)
                else:
                    print(f"    ❌ Failed to create PDF for page {page_num}")
                    
            except Exception as e:
                print(f"    ❌ Error converting page {page_num}: {e}")
                continue
        
        if not page_pdfs:
            print(f"    ❌ No pages successfully converted")
            return False
        
        # Merge all page PDFs into one notebook PDF
        if PYPDF2_AVAILABLE:
            return merge_pdfs_pypdf2(page_pdfs, notebook, output_path)
        else:
            print(f"    ❌ PyPDF2 not available for PDF merging")
            return False


def merge_pdfs_pypdf2(page_pdfs, notebook, output_path):
    """Merge multiple page PDFs into one notebook PDF using PyPDF2."""
    try:
        import PyPDF2
        
        # Create output filename
        safe_name = safe_filename(notebook['name'])
        output_file = output_path / f"{safe_name}.pdf"
        
        # Handle filename conflicts
        counter = 1
        original_output_file = output_file
        while output_file.exists():
            output_file = output_path / f"{safe_name}_{counter}.pdf"
            counter += 1
        
        # Merge PDFs
        pdf_writer = PyPDF2.PdfWriter()
        
        for page_pdf in sorted(page_pdfs):  # Sort to ensure correct page order
            try:
                with open(page_pdf, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    for page in pdf_reader.pages:
                        pdf_writer.add_page(page)
            except Exception as e:
                print(f"    ⚠️  Error reading page PDF {page_pdf}: {e}")
                continue
        
        # Write merged PDF
        with open(output_file, 'wb') as f:
            pdf_writer.write(f)
        
        print(f"    ✅ Notebook PDF saved: {output_file.name} ({len(page_pdfs)} pages)")
        return True
        
    except Exception as e:
        print(f"    ❌ Error merging PDFs: {e}")
        return False


def convert_notebooks_to_pdfs(input_path, output_path):
    """Convert all notebooks in input_path to multi-page PDFs in output_path."""
    
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find all notebooks
    print("🔍 Searching for notebooks...")
    notebooks = find_notebooks(input_path)
    
    if not notebooks:
        print("⚠️  No notebooks found")
        return
    
    print(f"📚 Found {len(notebooks)} notebooks")
    print("=" * 60)
    
    # Initialize converter
    converter = RmToSvgConverter()
    
    # Conversion statistics
    stats = {
        'total': len(notebooks),
        'success': 0,
        'failed': 0
    }
    
    # Convert each notebook
    for i, notebook in enumerate(notebooks, 1):
        print(f"[{i}/{len(notebooks)}] Processing notebook: {notebook['name']}")
        
        try:
            if convert_notebook_to_pdf(notebook, input_path, output_path, converter):
                stats['success'] += 1
            else:
                stats['failed'] += 1
                
        except Exception as e:
            print(f"    ❌ Error processing notebook {notebook['name']}: {e}")
            stats['failed'] += 1
        
        print()
    
    # Print summary
    print("📊 Conversion Summary")
    print("=" * 30)
    print(f"Total notebooks: {stats['total']}")
    print(f"Successfully converted: {stats['success']}")
    print(f"Failed: {stats['failed']}")
    
    success_rate = (stats['success'] / stats['total']) * 100 if stats['total'] > 0 else 0
    print(f"Success rate: {success_rate:.1f}%")


def main():
    """Main function."""
    print("🚀 reMarkable Notebook to PDF Converter")
    print("=" * 50)
    
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: python notebook_pdf_converter.py <input_path> [output_path]")
        print()
        print("Arguments:")
        print("  input_path   : Path to directory containing reMarkable files")
        print("  output_path  : Output directory (default: ./notebook_pdfs)")
        print()
        print("This will create one PDF file per notebook, with all pages merged.")
        sys.exit(1)
    
    # Parse arguments
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "./notebook_pdfs"
    
    # Verify input path exists
    if not Path(input_path).exists():
        print(f"❌ Input path does not exist: {input_path}")
        sys.exit(1)
    
    print(f"📂 Input path: {input_path}")
    print(f"📁 Output path: {output_path}")
    print()
    
    if not PYPDF2_AVAILABLE:
        print("❌ PyPDF2 is required for PDF merging")
        print("Install with: poetry add PyPDF2")
        sys.exit(1)
    
    try:
        convert_notebooks_to_pdfs(input_path, output_path)
        print("\n🎉 Conversion completed!")
        
    except KeyboardInterrupt:
        print("\n⏹️  Conversion interrupted by user")
    except Exception as e:
        print(f"\n❌ Conversion failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()