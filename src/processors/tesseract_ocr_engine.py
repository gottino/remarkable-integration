"""
Tesseract OCR Engine for reMarkable Integration.

Alternative OCR engine using pytesseract (Google's Tesseract) instead of EasyOCR.
More lightweight and often has fewer dependency issues.
"""

import os
import logging
import sqlite3
import json
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import time

# Core dependencies
import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageEnhance

# OCR engine
try:
    import pytesseract
    from PIL import Image
    PYTESSERACT_AVAILABLE = True
except (ImportError, ModuleNotFoundError) as e:
    PYTESSERACT_AVAILABLE = False
    import logging
    logging.getLogger(__name__).info(f"pytesseract not available: {e}")

# PDF processing
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except (ImportError, ModuleNotFoundError) as e:
    PDF2IMAGE_AVAILABLE = False
    import logging
    logging.getLogger(__name__).info(f"pdf2image not available: {e}")

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


class TesseractOCREngine:
    """OCR engine for processing PDF files using Tesseract."""
    
    def __init__(
        self, 
        db_connection: Optional[sqlite3.Connection] = None,
        language: str = 'eng',
        confidence_threshold: float = 70.0,
        tesseract_config: str = '--psm 6'
    ):
        """
        Initialize Tesseract OCR engine.
        
        Args:
            db_connection: Optional database connection for storing results
            language: Language code for OCR (default: 'eng' for English)
            confidence_threshold: Minimum confidence for text recognition (0-100)
            tesseract_config: Tesseract configuration string
        """
        self.processor_type = "tesseract_ocr_engine"
        self.db_connection = db_connection
        self.language = language
        self.confidence_threshold = confidence_threshold
        self.tesseract_config = tesseract_config
        
        # Check tesseract availability
        self.tesseract_available = self._check_tesseract()
        
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
        
        logger.info(f"Tesseract OCR Engine initialized (available: {self.is_available()})")
        logger.info(f"  Language: {language}")
        logger.info(f"  Confidence threshold: {confidence_threshold}")
        logger.info(f"  Config: {tesseract_config}")
    
    def _check_tesseract(self) -> bool:
        """Check if Tesseract is available."""
        if not PYTESSERACT_AVAILABLE:
            return False
        
        try:
            # Try to get tesseract version
            version = pytesseract.get_tesseract_version()
            logger.info(f"Tesseract version: {version}")
            return True
        except Exception as e:
            logger.error(f"Tesseract not available: {e}")
            logger.error("To install Tesseract:")
            logger.error("  macOS: brew install tesseract")
            logger.error("  Ubuntu: apt-get install tesseract-ocr")
            logger.error("  Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki")
            logger.error("  Alternative: conda install -c conda-forge tesseract")
            return False
    
    def is_available(self) -> bool:
        """Check if OCR functionality is available."""
        return PYTESSERACT_AVAILABLE and PDF2IMAGE_AVAILABLE and self.tesseract_available
    
    def can_process(self, file_path: str) -> bool:
        """Check if file can be processed by Tesseract OCR engine."""
        if not self.is_available():
            return False
        
        # Check if it's a PDF file
        if file_path.lower().endswith('.pdf'):
            return True
        
        return False
    
    def process_file(self, file_path: str) -> ProcessingResult:
        """
        Process a PDF file and extract text using Tesseract OCR.
        
        Args:
            file_path: Path to the PDF file to process
            
        Returns:
            ProcessingResult with OCR results
        """
        start_time = time.time()
        
        if not self.is_available():
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="Tesseract OCR engine not available"
            )
        
        if not self.can_process(file_path):
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="File cannot be processed by Tesseract OCR engine"
            )
        
        try:
            logger.info(f"Processing PDF with Tesseract OCR: {file_path}")
            
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
            
            logger.info(f"Tesseract OCR completed: {len(all_ocr_results)} text regions from {len(images)} pages")
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=all_ocr_results,
                processing_time_ms=processing_time
            )
            
        except Exception as e:
            logger.error(f"Tesseract OCR processing failed for {file_path}: {e}")
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
        """Perform OCR on the preprocessed image using Tesseract."""
        if not self.tesseract_available:
            logger.error("Tesseract not available")
            return []
        
        try:
            # Get OCR data with bounding boxes and confidence
            ocr_data = pytesseract.image_to_data(
                image,
                lang=self.language,
                config=self.tesseract_config,
                output_type=pytesseract.Output.DICT
            )
            
            ocr_results = []
            
            # Process each detected text element
            for i in range(len(ocr_data['text'])):
                text = ocr_data['text'][i].strip()
                confidence = float(ocr_data['conf'][i])
                
                # Skip empty text or low confidence
                if not text or confidence < self.text_filters['min_confidence']:
                    continue
                
                # Skip single characters if filtering enabled
                if self.text_filters['filter_single_chars'] and len(text) == 1:
                    continue
                
                # Skip very short text
                if len(text) < self.text_filters['min_text_length']:
                    continue
                
                # Get bounding box
                x = float(ocr_data['left'][i])
                y = float(ocr_data['top'][i])
                width = float(ocr_data['width'][i])
                height = float(ocr_data['height'][i])
                
                bounding_box = BoundingBox(x=x, y=y, width=width, height=height)
                
                ocr_result = OCRResult(
                    text=text,
                    confidence=confidence / 100.0,  # Convert to 0-1 range
                    bounding_box=bounding_box,
                    language=self.language
                )
                
                ocr_results.append(ocr_result)
            
            # Merge nearby text regions if enabled
            if self.text_filters['merge_nearby_text']:
                ocr_results = self._merge_nearby_text(ocr_results)
            
            logger.debug(f"Tesseract OCR found {len(ocr_results)} text regions")
            
            return ocr_results
            
        except Exception as e:
            logger.error(f"Error performing Tesseract OCR: {e}")
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
            logger.info(f"Stored {len(ocr_results)} Tesseract OCR results for {source_file}")
            
        except Exception as e:
            logger.error(f"Error storing Tesseract OCR results: {e}")


# Test function
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python tesseract_ocr_engine.py <pdf_file>")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    
    print("Testing Tesseract OCR Engine")
    print("=" * 40)
    
    engine = TesseractOCREngine()
    
    print(f"Engine available: {engine.is_available()}")
    print(f"Can process {pdf_file}: {engine.can_process(pdf_file)}")
    
    if engine.is_available() and engine.can_process(pdf_file):
        print(f"\nProcessing {pdf_file}...")
        result = engine.process_file(pdf_file)
        
        print(f"Success: {result.success}")
        if result.success:
            print(f"Text regions found: {len(result.ocr_results)}")
            print(f"Processing time: {result.processing_time_ms}ms")
            
            if result.ocr_results:
                print("\nFirst few text regions:")
                for i, ocr_result in enumerate(result.ocr_results[:5]):
                    print(f"  {i+1}. '{ocr_result.text}' (confidence: {ocr_result.confidence:.2f})")
        else:
            print(f"Error: {result.error_message}")
    else:
        print("Cannot process file or engine not available")