"""
PDF OCR Engine for reMarkable Integration.

Handles optical character recognition of PDF files generated from reMarkable notebooks.
Uses EasyOCR for text recognition and pdf2image for PDF to image conversion.
"""

import os
import logging
import sqlite3
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import json

# Core dependencies
import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageEnhance

# OCR engine
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False

# PDF processing
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False

# Database and events
from ..core.events import get_event_bus, EventType
from ..core.database import DatabaseManager

logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    """Bounding box for text regions."""
    x: float
    y: float
    width: float
    height: float
    
    def to_dict(self) -> Dict[str, float]:
        return {
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height
        }


@dataclass
class OCRResult:
    """Result of OCR processing on a text region."""
    text: str
    confidence: float
    bounding_box: BoundingBox
    language: str
    page_number: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'text': self.text,
            'confidence': self.confidence,
            'bounding_box': self.bounding_box.to_dict(),
            'language': self.language,
            'page_number': self.page_number
        }


@dataclass
class ProcessingResult:
    """Result of OCR processing on a PDF file."""
    success: bool
    file_path: str
    processor_type: str
    ocr_results: List[OCRResult]
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'file_path': self.file_path,
            'processor_type': self.processor_type,
            'ocr_results': [result.to_dict() for result in self.ocr_results],
            'error_message': self.error_message,
            'processing_time_ms': self.processing_time_ms
        }


class PDFOCREngine:
    """OCR engine for processing PDF files generated from reMarkable notebooks."""
    
    def __init__(
        self, 
        db_connection: Optional[sqlite3.Connection] = None,
        language: str = 'en',
        confidence_threshold: float = 0.7,
        enable_gpu: bool = False
    ):
        """
        Initialize PDF OCR engine.
        
        Args:
            db_connection: Optional database connection for storing results
            language: Language code for OCR (default: 'en')
            confidence_threshold: Minimum confidence for text recognition
            enable_gpu: Whether to use GPU acceleration (if available)
        """
        self.processor_type = "pdf_ocr_engine"
        self.db_connection = db_connection
        self.language = language
        self.confidence_threshold = confidence_threshold
        self.enable_gpu = enable_gpu
        
        # Initialize OCR reader
        self.reader = None
        if EASYOCR_AVAILABLE:
            try:
                self.reader = easyocr.Reader(
                    [language], 
                    gpu=enable_gpu and self._check_gpu_availability()
                )
                logger.info(f"EasyOCR initialized with language: {language}, GPU: {enable_gpu}")
            except Exception as e:
                logger.error(f"Failed to initialize EasyOCR: {e}")
                self.reader = None
        else:
            logger.warning("EasyOCR not available - OCR functionality disabled")
        
        # Check pdf2image availability
        if not PDF2IMAGE_AVAILABLE:
            logger.error("pdf2image not available. Install with: pip install pdf2image")
        
        # Image processing settings for reMarkable PDFs
        self.image_settings = {
            'dpi': 300,  # High DPI for better OCR accuracy
            'gaussian_blur_radius': 0.5,  # Slight blur to smooth edges
            'contrast_enhancement': 1.2,  # Increase contrast
            'resize_factor': 1.0,  # Factor to resize image before OCR
        }
        
        # Text filtering settings
        self.text_filters = {
            'min_text_length': 2,  # Minimum characters
            'min_confidence': confidence_threshold,
            'filter_single_chars': True,  # Filter out single character results
            'merge_nearby_text': True,  # Merge text regions that are close
            'merge_distance_threshold': 50,  # Pixel distance for merging
        }
        
        logger.info(f"PDF OCR Engine initialized (available: {self.is_available()})")
    
    def is_available(self) -> bool:
        """Check if OCR functionality is available."""
        return EASYOCR_AVAILABLE and PDF2IMAGE_AVAILABLE and self.reader is not None
    
    def _check_gpu_availability(self) -> bool:
        """Check if GPU is available for OCR processing."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    def can_process(self, file_path: str) -> bool:
        """Check if file can be processed by PDF OCR engine."""
        if not self.is_available():
            return False
        
        # Check if it's a PDF file
        if file_path.lower().endswith('.pdf'):
            return True
        
        return False
    
    def process_file(self, file_path: str) -> ProcessingResult:
        """
        Process a PDF file and extract text using OCR.
        
        Args:
            file_path: Path to the PDF file to process
            
        Returns:
            ProcessingResult with OCR results
        """
        import time
        start_time = time.time()
        
        if not self.is_available():
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="PDF OCR engine not available"
            )
        
        if not self.can_process(file_path):
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="File cannot be processed by PDF OCR engine"
            )
        
        try:
            logger.info(f"Processing PDF with OCR: {file_path}")
            
            # Convert PDF to images
            images = self._pdf_to_images(file_path)
            if not images:
                raise ValueError("Failed to convert PDF to images")
            
            # Process each page
            all_ocr_results = []
            for page_num, image in enumerate(images, 1):
                logger.debug(f"Processing page {page_num}/{len(images)}")
                
                # Preprocess image for better OCR
                processed_image = self._preprocess_image(image)
                
                # Perform OCR on this page
                page_results = self._perform_ocr(processed_image)
                
                # Add page number to results
                for result in page_results:
                    result.page_number = page_num
                
                all_ocr_results.extend(page_results)
            
            # Store results in database if available
            if self.db_connection and all_ocr_results:
                self._store_ocr_results(all_ocr_results, file_path)
            
            # Emit OCR completed event
            event_bus = get_event_bus()
            if event_bus:
                event_bus.emit(EventType.OCR_COMPLETED, {
                    'file_path': file_path,
                    'text_count': len(all_ocr_results),
                    'page_count': len(images),
                    'processor_type': self.processor_type,
                    'total_confidence': sum(r.confidence for r in all_ocr_results) / len(all_ocr_results) if all_ocr_results else 0.0
                })
            
            processing_time = int((time.time() - start_time) * 1000)
            
            logger.info(f"OCR completed: {len(all_ocr_results)} text regions from {len(images)} pages")
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=all_ocr_results,
                processing_time_ms=processing_time
            )
            
        except Exception as e:
            logger.error(f"PDF OCR processing failed for {file_path}: {e}")
            processing_time = int((time.time() - start_time) * 1000)
            
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message=str(e),
                processing_time_ms=processing_time
            )
    
    def _pdf_to_images(self, pdf_path: str) -> List[Image.Image]:
        """Convert PDF file to list of PIL Images."""
        if not PDF2IMAGE_AVAILABLE:
            logger.error("pdf2image not available for PDF to image conversion")
            return []
        
        try:
            # Convert PDF to images with high DPI for better OCR
            images = convert_from_path(
                pdf_path,
                dpi=self.image_settings['dpi'],
                fmt='RGB'
            )
            
            logger.debug(f"Converted PDF to {len(images)} images")
            return images
            
        except Exception as e:
            logger.error(f"Error converting PDF to images: {e}")
            return []
    
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """Preprocess image for better OCR accuracy."""
        try:
            # Resize if needed
            resize_factor = self.image_settings['resize_factor']
            if resize_factor != 1.0:
                new_size = (
                    int(image.width * resize_factor),
                    int(image.height * resize_factor)
                )
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Convert to grayscale for better OCR
            if image.mode != 'L':
                image = ImageOps.grayscale(image)
            
            # Apply slight Gaussian blur to smooth jagged strokes
            blur_radius = self.image_settings['gaussian_blur_radius']
            if blur_radius > 0:
                image = image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            
            # Enhance contrast
            contrast_factor = self.image_settings['contrast_enhancement']
            if contrast_factor != 1.0:
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(contrast_factor)
            
            # Ensure high contrast (black text on white background)
            # Invert if the background appears darker than the text
            image_array = np.array(image)
            if np.mean(image_array) < 128:  # Dark background
                image = ImageOps.invert(image)
            
            return image
            
        except Exception as e:
            logger.error(f"Error preprocessing image: {e}")
            return image
    
    def _perform_ocr(self, image: Image.Image) -> List[OCRResult]:
        """Perform OCR on the preprocessed image."""
        if not self.reader:
            logger.error("OCR reader not initialized")
            return []
        
        try:
            # Convert PIL image to numpy array for EasyOCR
            image_array = np.array(image)
            
            # Perform OCR
            results = self.reader.readtext(image_array)
            
            ocr_results = []
            
            for detection in results:
                # EasyOCR returns: [bbox, text, confidence]
                bbox, text, confidence = detection
                
                if confidence < self.text_filters['min_confidence']:
                    continue
                
                if len(text.strip()) < self.text_filters['min_text_length']:
                    continue
                
                if self.text_filters['filter_single_chars'] and len(text.strip()) == 1:
                    continue
                
                # Calculate bounding box
                x_coords = [point[0] for point in bbox]
                y_coords = [point[1] for point in bbox]
                
                bounding_box = BoundingBox(
                    x=min(x_coords),
                    y=min(y_coords),
                    width=max(x_coords) - min(x_coords),
                    height=max(y_coords) - min(y_coords)
                )
                
                ocr_result = OCRResult(
                    text=text.strip(),
                    confidence=confidence,
                    bounding_box=bounding_box,
                    language=self.language
                )
                
                ocr_results.append(ocr_result)
            
            # Merge nearby text regions if enabled
            if self.text_filters['merge_nearby_text']:
                ocr_results = self._merge_nearby_text(ocr_results)
            
            logger.debug(f"OCR found {len(ocr_results)} text regions")
            
            return ocr_results
            
        except Exception as e:
            logger.error(f"Error performing OCR: {e}")
            return []
    
    def _merge_nearby_text(self, ocr_results: List[OCRResult]) -> List[OCRResult]:
        """Merge OCR results that are spatially close."""
        if len(ocr_results) < 2:
            return ocr_results
        
        threshold = self.text_filters['merge_distance_threshold']
        merged_results = []
        used_indices = set()
        
        for i, result1 in enumerate(ocr_results):
            if i in used_indices:
                continue
            
            # Find nearby results to merge
            group = [result1]
            used_indices.add(i)
            
            for j, result2 in enumerate(ocr_results):
                if j in used_indices or j <= i:
                    continue
                
                # Calculate distance between bounding box centers
                center1_x = result1.bounding_box.x + result1.bounding_box.width / 2
                center1_y = result1.bounding_box.y + result1.bounding_box.height / 2
                
                center2_x = result2.bounding_box.x + result2.bounding_box.width / 2
                center2_y = result2.bounding_box.y + result2.bounding_box.height / 2
                
                distance = ((center1_x - center2_x) ** 2 + (center1_y - center2_y) ** 2) ** 0.5
                
                if distance < threshold:
                    group.append(result2)
                    used_indices.add(j)
            
            # Merge the group
            if len(group) == 1:
                merged_results.append(group[0])
            else:
                merged_result = self._merge_ocr_group(group)
                merged_results.append(merged_result)
        
        logger.debug(f"Merged {len(ocr_results)} results into {len(merged_results)}")
        return merged_results
    
    def _merge_ocr_group(self, group: List[OCRResult]) -> OCRResult:
        """Merge a group of OCR results into one."""
        # Sort by y-coordinate first, then x-coordinate (reading order)
        sorted_group = sorted(group, key=lambda r: (r.bounding_box.y, r.bounding_box.x))
        
        # Combine text
        combined_text = ' '.join(result.text for result in sorted_group)
        
        # Calculate average confidence
        avg_confidence = sum(result.confidence for result in sorted_group) / len(sorted_group)
        
        # Calculate combined bounding box
        min_x = min(result.bounding_box.x for result in sorted_group)
        min_y = min(result.bounding_box.y for result in sorted_group)
        max_x = max(result.bounding_box.x + result.bounding_box.width for result in sorted_group)
        max_y = max(result.bounding_box.y + result.bounding_box.height for result in sorted_group)
        
        combined_bbox = BoundingBox(
            x=min_x,
            y=min_y,
            width=max_x - min_x,
            height=max_y - min_y
        )
        
        return OCRResult(
            text=combined_text,
            confidence=avg_confidence,
            bounding_box=combined_bbox,
            language=sorted_group[0].language,
            page_number=sorted_group[0].page_number
        )
    
    def _store_ocr_results(self, ocr_results: List[OCRResult], source_file: str):
        """Store OCR results in database."""
        if not self.db_connection:
            return
        
        try:
            cursor = self.db_connection.cursor()
            
            # Clear existing OCR results for this source file
            cursor.execute('DELETE FROM ocr_results WHERE source_file = ?', (source_file,))
            
            # Insert new OCR results
            for result in ocr_results:
                cursor.execute('''
                    INSERT INTO ocr_results 
                    (source_file, page_number, text, confidence, language, bounding_box)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    source_file,
                    result.page_number,
                    result.text,
                    result.confidence,
                    result.language,
                    json.dumps(result.bounding_box.to_dict())
                ))
            
            self.db_connection.commit()
            logger.info(f"Stored {len(ocr_results)} OCR results for {source_file}")
            
        except Exception as e:
            logger.error(f"Error storing OCR results: {e}")
    
    def get_ocr_results_for_file(self, source_file: str) -> List[Dict[str, Any]]:
        """Retrieve OCR results for a specific file."""
        if not self.db_connection:
            return []
        
        try:
            cursor = self.db_connection.cursor()
            cursor.execute('''
                SELECT source_file, page_number, text, confidence, language, bounding_box, created_at
                FROM ocr_results 
                WHERE source_file = ?
                ORDER BY page_number, created_at
            ''', (source_file,))
            
            columns = [description[0] for description in cursor.description]
            results = cursor.fetchall()
            
            ocr_results = []
            for row in results:
                result_dict = dict(zip(columns, row))
                
                # Parse bounding box JSON
                if result_dict['bounding_box']:
                    try:
                        result_dict['bounding_box'] = json.loads(result_dict['bounding_box'])
                    except json.JSONDecodeError:
                        result_dict['bounding_box'] = None
                
                ocr_results.append(result_dict)
            
            return ocr_results
            
        except Exception as e:
            logger.error(f"Error retrieving OCR results for {source_file}: {e}")
            return []
    
    def export_ocr_results_to_csv(self, output_path: str, source_file_filter: Optional[str] = None):
        """Export OCR results to CSV file."""
        if not self.db_connection:
            logger.error("No database connection available for export")
            return
        
        try:
            import pandas as pd
            
            query = '''
                SELECT source_file, page_number, text, confidence, language, created_at
                FROM ocr_results
            '''
            params = []
            
            if source_file_filter:
                query += ' WHERE source_file = ?'
                params.append(source_file_filter)
            
            query += ' ORDER BY source_file, page_number, created_at'
            
            df = pd.read_sql_query(query, self.db_connection, params=params)
            df.to_csv(output_path, index=False)
            
            logger.info(f"Exported {len(df)} OCR results to {output_path}")
            
        except Exception as e:
            logger.error(f"Error exporting OCR results to CSV: {e}")
            raise


# Utility functions for standalone usage

def process_directory_with_pdf_ocr(
    directory_path: str, 
    db_manager: Optional[DatabaseManager] = None,
    language: str = 'en',
    confidence_threshold: float = 0.7
) -> Dict[str, int]:
    """
    Process all PDF files in a directory with OCR.
    
    Args:
        directory_path: Directory containing PDF files
        db_manager: Optional database manager
        language: Language for OCR
        confidence_threshold: Minimum confidence threshold
        
    Returns:
        Dictionary mapping file paths to text region counts
    """
    if not db_manager:
        db_manager = DatabaseManager("pdf_ocr_results.db")
    
    results = {}
    
    try:
        with db_manager.get_connection() as conn:
            ocr_engine = PDFOCREngine(
                db_connection=conn,
                language=language,
                confidence_threshold=confidence_threshold
            )
            
            if not ocr_engine.is_available():
                logger.error("PDF OCR engine not available - check EasyOCR and pdf2image installation")
                return results
            
            logger.info(f"Processing directory with PDF OCR: {directory_path}")
            
            # Process PDF files
            for root, _, files in os.walk(directory_path):
                for file_name in files:
                    if file_name.lower().endswith('.pdf'):
                        file_path = os.path.join(root, file_name)
                        
                        logger.info(f"Processing: {file_name}")
                        
                        result = ocr_engine.process_file(file_path)
                        
                        if result.success:
                            text_count = len(result.ocr_results)
                            results[file_path] = text_count
                            logger.info(f"   ✓ Extracted {text_count} text regions")
                        else:
                            logger.error(f"   ✗ Failed: {result.error_message}")
                            results[file_path] = 0
            
        logger.info(f"PDF OCR processing complete: {sum(results.values())} total text regions")
        
    except Exception as e:
        logger.error(f"Error in process_directory_with_pdf_ocr: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return results


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pdf_ocr_engine.py <directory_or_file_path> [--language en] [--confidence 0.7]")
        print("  directory_or_file_path: Directory or PDF file to process")
        print("  --language: OCR language (default: en)")
        print("  --confidence: Minimum confidence threshold (default: 0.7)")
        sys.exit(1)
    
    target_path = sys.argv[1]
    language = 'en'
    confidence = 0.7
    
    # Parse optional arguments
    for i, arg in enumerate(sys.argv[2:], 2):
        if arg == '--language' and i + 1 < len(sys.argv):
            language = sys.argv[i + 1]
        elif arg == '--confidence' and i + 1 < len(sys.argv):
            confidence = float(sys.argv[i + 1])
    
    if os.path.isdir(target_path):
        print("PDF OCR Processing Directory")
        print("=" * 40)
        
        results = process_directory_with_pdf_ocr(target_path, language=language, confidence_threshold=confidence)
        
        total_regions = sum(results.values())
        processed_files = len([count for count in results.values() if count > 0])
        
        print(f"\nPDF OCR processing complete!")
        print(f"   Files processed: {len(results)}")
        print(f"   Files with text: {processed_files}")
        print(f"   Total text regions: {total_regions}")
        
        if total_regions > 0:
            print(f"\nResults by file:")
            for file_path, count in results.items():
                if count > 0:
                    file_name = os.path.basename(file_path)
                    print(f"   {file_name}: {count} text regions")
            
            # Export to CSV
            output_csv = os.path.join(target_path, "pdf_ocr_results.csv")
            try:
                db_manager = DatabaseManager("pdf_ocr_results.db")
                with db_manager.get_connection() as conn:
                    ocr_engine = PDFOCREngine(conn)
                    ocr_engine.export_ocr_results_to_csv(output_csv)
                    print(f"\nPDF OCR results exported to: {output_csv}")
            except Exception as e:
                print(f"Could not export CSV: {e}")
        
    else:
        print("Single PDF file processing not yet implemented")
        print("Use directory processing instead")