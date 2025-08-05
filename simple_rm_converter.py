#!/usr/bin/env python3
"""
Simple reMarkable file converter - converts all .rm files to SVG and optionally PDF.
"""

import sys
import json
from pathlib import Path
import traceback

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

# Optional PDF conversion
INKSCAPE_AVAILABLE = False
CAIROSVG_AVAILABLE = False
RSVG_CONVERT_AVAILABLE = False

try:
    import subprocess
    import shutil
    
    # Check for rsvg-convert (preferred - matches your original tool)
    RSVG_CONVERT_AVAILABLE = shutil.which('rsvg-convert') is not None
    if RSVG_CONVERT_AVAILABLE:
        print("🔧 Found rsvg-convert for PDF conversion (matches your original rmtool.py)")
    
    # Check if we have Inkscape as backup
    INKSCAPE_AVAILABLE = shutil.which('inkscape') is not None
    if INKSCAPE_AVAILABLE:
        print("🔧 Found Inkscape for PDF conversion (backup option)")
        
except ImportError:
    pass

# Check for cairosvg more carefully (but prefer rsvg-convert)
try:
    import cairosvg
    CAIROSVG_AVAILABLE = True
    print("🔧 Found cairosvg for PDF conversion (backup option)")
except ImportError:
    pass
except OSError as e:
    print(f"⚠️  cairosvg installed but Cairo library missing: {e}")
    print("    Install Cairo system library with: brew install cairo")
except Exception as e:
    print(f"⚠️  cairosvg error: {e}")


def get_document_name(rm_file_path):
    """Get the document name from metadata file if available."""
    metadata_file = rm_file_path.with_suffix('.metadata')
    
    if metadata_file.exists():
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            return metadata.get('visibleName', rm_file_path.stem)
        except Exception as e:
            print(f"⚠️  Could not read metadata for {rm_file_path.name}: {e}")
    
    # If no metadata, use a combination of directory and filename for context
    relative_path = rm_file_path.relative_to(rm_file_path.parents[1] if len(rm_file_path.parents) > 1 else rm_file_path.parent)
    return str(relative_path.with_suffix('')).replace('/', '_')


def safe_filename(name):
    """Convert a string to a safe filename."""
    # Replace problematic characters
    safe_chars = []
    for char in name:
        if char.isalnum() or char in ' -_()[]':
            safe_chars.append(char)
        else:
            safe_chars.append('_')
    
    # Join and clean up
    safe_name = ''.join(safe_chars).strip()
    
    # Remove excessive underscores and spaces
    while '__' in safe_name:
        safe_name = safe_name.replace('__', '_')
    while '  ' in safe_name:
        safe_name = safe_name.replace('  ', ' ')
    
    return safe_name.strip('_').strip()


def svg_to_pdf_rsvg_convert(svg_file, pdf_file):
    """Convert SVG to PDF using rsvg-convert (matches original rmtool.py approach)."""
    try:
        # Get SVG dimensions to maintain aspect ratio
        # For now, use standard reMarkable dimensions
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
            # Write the PDF output to file
            with open(pdf_file, 'wb') as f:
                f.write(result.stdout)
            return True
        else:
            print(f"    ❌ rsvg-convert error: {result.stderr.decode()}")
            return False
            
    except subprocess.TimeoutExpired:
        print("    ❌ rsvg-convert conversion timed out")
        return False
    except Exception as e:
        print(f"    ❌ rsvg-convert conversion failed: {e}")
        return False
    """Convert SVG to PDF using cairosvg."""
    try:
        import cairosvg
        cairosvg.svg2pdf(bytestring=svg_content.encode('utf-8'), write_to=str(pdf_path))
        return True
    except Exception as e:
        print(f"    ❌ cairosvg conversion failed: {e}")
        return False


def svg_to_pdf_inkscape(svg_path, pdf_path):
    """Convert SVG to PDF using Inkscape."""
    try:
        result = subprocess.run([
            'inkscape',
            '--export-type=pdf',
            f'--export-filename={pdf_path}',
            str(svg_path)
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            return True
        else:
            print(f"    ❌ Inkscape error: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print("    ❌ Inkscape conversion timed out")
        return False
    except Exception as e:
        print(f"    ❌ Inkscape conversion failed: {e}")
        return False


def convert_rm_files(input_path, output_path, convert_to_pdf=True):
    """Convert all .rm files in input_path to SVG (and optionally PDF) in output_path."""
    
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find all .rm files recursively
    rm_files = list(input_path.rglob("*.rm"))
    
    if not rm_files:
        print(f"⚠️  No .rm files found in {input_path}")
        return
    
    print(f"📂 Found {len(rm_files)} .rm files (searching recursively)")
    print(f"📁 Output directory: {output_path}")
    
    # Show a sample of found files for debugging
    if rm_files:
        print(f"📄 Sample files found:")
        for rm_file in rm_files[:5]:  # Show first 5 files
            rel_path = rm_file.relative_to(input_path)
            print(f"    {rel_path}")
        if len(rm_files) > 5:
            print(f"    ... and {len(rm_files) - 5} more files")
        print()
    
    if convert_to_pdf:
        if RSVG_CONVERT_AVAILABLE:
            print("🔧 PDF conversion: Using rsvg-convert (same as original rmtool.py)")
        elif CAIROSVG_AVAILABLE:
            print("🔧 PDF conversion: Using cairosvg")
        elif INKSCAPE_AVAILABLE:
            print("🔧 PDF conversion: Using Inkscape")
        else:
            print("⚠️  PDF conversion not available")
            print("    Install rsvg-convert with: brew install librsvg")
            print("    Or install cairosvg with: poetry add cairosvg && brew install cairo")
            print("    Or install Inkscape with: brew install inkscape")
            convert_to_pdf = False
    
    print("=" * 60)
    
    # Initialize converter
    converter = RmToSvgConverter()
    
    # Conversion statistics
    stats = {
        'total': len(rm_files),
        'svg_success': 0,
        'svg_failed': 0,
        'pdf_success': 0,
        'pdf_failed': 0
    }
    
    # Convert each file
    for i, rm_file in enumerate(rm_files, 1):
        rel_path = rm_file.relative_to(input_path)
        print(f"[{i}/{len(rm_files)}] Processing: {rel_path}")
        
        try:
            # Get document name
            doc_name = get_document_name(rm_file)
            safe_name = safe_filename(doc_name)
            
            print(f"    📄 Document name: {doc_name}")
            
            # Convert to SVG
            svg_file = output_path / f"{safe_name}.svg"
            
            # Handle filename conflicts
            counter = 1
            original_svg_file = svg_file
            while svg_file.exists():
                svg_file = output_path / f"{safe_name}_{counter}.svg"
                counter += 1
            
            # Convert using the converter's method
            converter.convert_file(str(rm_file), str(svg_file))
            
            # Check if the file was created successfully
            if svg_file.exists() and svg_file.stat().st_size > 0:
                print(f"    ✅ SVG saved: {svg_file.name}")
                stats['svg_success'] += 1
                
                # For PDF conversion, try methods in order of preference
                if convert_to_pdf:
                    pdf_file = svg_file.with_suffix('.pdf')
                    
                    pdf_success = False
                    
                    # Try rsvg-convert first (matches your original tool)
                    if RSVG_CONVERT_AVAILABLE and not pdf_success:
                        pdf_success = svg_to_pdf_rsvg_convert(svg_file, pdf_file)
                    
                    # Try cairosvg as backup
                    if CAIROSVG_AVAILABLE and not pdf_success:
                        with open(svg_file, 'r', encoding='utf-8') as f:
                            svg_content = f.read()
                        pdf_success = svg_to_pdf_cairosvg(svg_content, pdf_file)
                    
                    # Try Inkscape as final backup
                    if INKSCAPE_AVAILABLE and not pdf_success:
                        pdf_success = svg_to_pdf_inkscape(svg_file, pdf_file)
                    
                    if pdf_success:
                        print(f"    ✅ PDF saved: {pdf_file.name}")
                        stats['pdf_success'] += 1
                    else:
                        stats['pdf_failed'] += 1
            else:
                print(f"    ❌ SVG conversion failed - no output file created")
                stats['svg_failed'] += 1
                
        except Exception as e:
            print(f"    ❌ Error processing {rm_file.name}: {e}")
            stats['svg_failed'] += 1
        
        print()
    
    # Print summary
    print("📊 Conversion Summary")
    print("=" * 30)
    print(f"Total files: {stats['total']}")
    print(f"SVG successful: {stats['svg_success']}")
    print(f"SVG failed: {stats['svg_failed']}")
    
    if convert_to_pdf:
        print(f"PDF successful: {stats['pdf_success']}")
        print(f"PDF failed: {stats['pdf_failed']}")
    
    success_rate = (stats['svg_success'] / stats['total']) * 100 if stats['total'] > 0 else 0
    print(f"Success rate: {success_rate:.1f}%")


def main():
    """Main function."""
    print("🚀 reMarkable File Converter")
    print("=" * 40)
    
    # Check command line arguments
    if len(sys.argv) < 2:
        print("Usage: python simple_rm_converter.py <input_path> [output_path] [--no-pdf]")
        print()
        print("Arguments:")
        print("  input_path   : Path to directory containing .rm files")
        print("  output_path  : Output directory (default: ./test_data/converted_files)")
        print("  --no-pdf     : Skip PDF conversion, only create SVG files")
        print()
        print("Examples:")
        print("  python simple_rm_converter.py '/path/to/remarkable/files'")
        print("  python simple_rm_converter.py '/path/to/files' './output'")
        print("  python simple_rm_converter.py '/path/to/files' './output' --no-pdf")
        sys.exit(1)
    
    # Parse arguments
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else "./test_data/converted_files"
    convert_to_pdf = '--no-pdf' not in sys.argv
    
    # Verify input path exists
    if not Path(input_path).exists():
        print(f"❌ Input path does not exist: {input_path}")
        sys.exit(1)
    
    print(f"📂 Input path: {input_path}")
    print(f"📁 Output path: {output_path}")
    print(f"📄 Convert to PDF: {'Yes' if convert_to_pdf else 'No'}")
    print()
    
    try:
        convert_rm_files(input_path, output_path, convert_to_pdf)
        print("\n🎉 Conversion completed!")
        
    except KeyboardInterrupt:
        print("\n⏹️  Conversion interrupted by user")
    except Exception as e:
        print(f"\n❌ Conversion failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()