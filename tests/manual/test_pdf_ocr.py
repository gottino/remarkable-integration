#!/usr/bin/env python3
"""
Simple test script to verify PDF OCR functionality.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.processors.pdf_ocr_engine import PDFOCREngine
from src.core.database import DatabaseManager

def test_pdf_ocr_engine():
    """Test the PDF OCR engine initialization and basic functionality."""
    
    print("Testing PDF OCR Engine")
    print("=" * 40)
    
    # Test initialization
    try:
        db_manager = DatabaseManager("test_pdf_ocr.db")
        
        with db_manager.get_connection() as conn:
            pdf_ocr_engine = PDFOCREngine(conn)
            
            print(f"PDF OCR Engine initialized")
            print(f"Available: {pdf_ocr_engine.is_available()}")
            print(f"Processor type: {pdf_ocr_engine.processor_type}")
            
            # Test can_process method
            test_files = [
                "test.pdf",
                "test.txt", 
                "test.rm",
                "test.PDF"
            ]
            
            print("\nFile processing capability:")
            for file_path in test_files:
                can_process = pdf_ocr_engine.can_process(file_path)
                print(f"  {file_path}: {'✓' if can_process else '✗'}")
            
            # Test with actual PDF if available
            pdf_file = "/Users/gabriele/Documents/Development/remarkable-integration/test_data/pdfs/Todos.pdf"
            if Path(pdf_file).exists():
                print(f"\nTesting with actual PDF file:")
                print(f"  Can process {Path(pdf_file).name}: {'✓' if pdf_ocr_engine.can_process(pdf_file) else '✗'}")
                
                # Attempt to process (will fail due to missing dependencies but should handle gracefully)
                print(f"\nAttempting to process PDF (expected to fail gracefully):")
                result = pdf_ocr_engine.process_file(pdf_file)
                print(f"  Success: {result.success}")
                print(f"  Error: {result.error_message}")
                print(f"  Processing time: {result.processing_time_ms}ms")
            
    except Exception as e:
        print(f"Error during testing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_pdf_ocr_engine()