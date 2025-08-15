"""
Enhanced Tesseract OCR Engine with improved handwriting recognition.

This enhanced version includes:
1. Better image preprocessing for handwritten text
2. Pattern recognition for common symbols (arrows, bullets, etc.)
3. Text post-processing and correction
4. Multiple Tesseract configurations for better accuracy
"""

import os
import re
import logging
import sqlite3
import json
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import time

# Core dependencies
import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageEnhance, ImageDraw

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

# Import base classes
from .tesseract_ocr_engine import BoundingBox, OCRResult, ProcessingResult

# Database and events
from ..core.events import get_event_bus, EventType
from ..core.database import DatabaseManager

logger = logging.getLogger(__name__)


class EnhancedTesseractOCREngine:
    """Enhanced OCR engine with better handwriting recognition."""
    
    def __init__(
        self, 
        db_connection: Optional[sqlite3.Connection] = None,
        language: str = 'eng',
        confidence_threshold: float = 60.0,  # Lower threshold for handwriting
        use_multiple_configs: bool = True
    ):
        """
        Initialize Enhanced Tesseract OCR engine.
        
        Args:
            db_connection: Optional database connection for storing results
            language: Language code for OCR (default: 'eng' for English)
            confidence_threshold: Minimum confidence for text recognition (0-100)
            use_multiple_configs: Whether to try multiple Tesseract configurations
        """
        self.processor_type = "enhanced_tesseract_ocr_engine"
        self.db_connection = db_connection
        self.language = language
        self.confidence_threshold = confidence_threshold
        self.use_multiple_configs = use_multiple_configs
        
        # Multiple Tesseract configurations for different text types
        self.tesseract_configs = [
            '--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,!?:;-()[]{}\"\'/ ',  # Standard text
            '--psm 8 --oem 3',  # Single word mode
            '--psm 13',  # Raw line, treat as single text line
            '--psm 6 --oem 1',  # LSTM engine only
            '--psm 7 --oem 3',  # Single text line
        ]
        
        # Check tesseract availability
        self.tesseract_available = self._check_tesseract()
        
        if not PDF2IMAGE_AVAILABLE:
            logger.error("pdf2image not available. Install with: pip install pdf2image")
        
        # Enhanced image processing settings for handwriting
        self.image_settings = {
            'dpi': 400,  # Higher DPI for handwriting
            'gaussian_blur_radius': 0.3,  # Minimal blur
            'contrast_enhancement': 1.4,  # Higher contrast
            'resize_factor': 1.2,  # Slightly larger
            'noise_reduction': True,
            'line_enhancement': True,
        }
        
        # Pattern recognition settings
        self.pattern_recognition = {
            'detect_arrows': True,
            'detect_bullets': True,
            'detect_checkboxes': True,
            'common_corrections': True,
        }
        
        # Text filtering settings (more lenient for handwriting)
        self.text_filters = {
            'min_text_length': 1,  # Allow single characters
            'min_confidence': confidence_threshold,
            'filter_single_chars': False,  # Don't filter single chars
            'merge_nearby_text': True,
            'merge_distance_threshold': 30,  # Closer merging for handwriting
        }
        
        # Common OCR corrections for handwriting
        self.common_corrections = {
            # Arrow patterns
            r'\bL\b': '→',  # Single L often means arrow
            r'\bLy\b': '→',  # Ly often means arrow
            r'\bL-\b': '→',
            r'\bL>\b': '→',
            r'\b\|L\b': '|→',
            r'\b\|->\b': '|→',
            r'\b->\b': '→',
            
            # Common handwriting mistakes
            r'\brn\b': 'm',  # rn often confused with m
            r'\bvv\b': 'w',  # vv often confused with w
            r'\bur\b': 'ur',  # keep as is
            r'\b1\b': 'I',   # 1 might be I in context
            r'\b0\b': 'O',   # 0 might be O in context
            
            # Clean up excessive spaces
            r'\s+': ' ',
            r'^\s+|\s+$': '',
        }
        
        logger.info(f"Enhanced Tesseract OCR Engine initialized (available: {self.is_available()})")
        logger.info(f"  Language: {language}")
        logger.info(f"  Confidence threshold: {confidence_threshold}")
        logger.info(f"  Multiple configs: {use_multiple_configs}")
    
    def _check_tesseract(self) -> bool:
        """Check if Tesseract is available."""
        if not PYTESSERACT_AVAILABLE:
            return False
        
        try:
            version = pytesseract.get_tesseract_version()
            logger.info(f"Enhanced Tesseract version: {version}")
            return True
        except Exception as e:
            logger.error(f"Tesseract not available: {e}")
            return False
    
    def is_available(self) -> bool:
        """Check if OCR functionality is available."""
        return PYTESSERACT_AVAILABLE and PDF2IMAGE_AVAILABLE and self.tesseract_available
    
    def can_process(self, file_path: str) -> bool:
        """Check if file can be processed."""
        if not self.is_available():
            return False
        return file_path.lower().endswith('.pdf')
    
    def process_file(self, file_path: str) -> ProcessingResult:
        """Process a PDF file with enhanced OCR."""
        start_time = time.time()
        
        if not self.is_available():
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="Enhanced Tesseract OCR engine not available"
            )
        
        if not self.can_process(file_path):
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="File cannot be processed"
            )
        
        try:
            logger.info(f"Processing PDF with Enhanced Tesseract OCR: {file_path}")
            
            # Convert PDF to images
            images = self._pdf_to_images(file_path)
            if not images:
                raise ValueError("Failed to convert PDF to images")
            
            # Process each page with multiple approaches
            all_ocr_results = []
            for page_num, image in enumerate(images, 1):
                logger.debug(f"Processing page {page_num}/{len(images)} with enhanced OCR")
                
                # Enhanced preprocessing
                processed_image = self._enhanced_preprocess_image(image)
                
                # Perform OCR with multiple configurations
                page_results = self._perform_enhanced_ocr(processed_image)
                
                # Add page number to results
                for result in page_results:
                    result.page_number = page_num
                
                all_ocr_results.extend(page_results)
            
            # Apply post-processing corrections
            all_ocr_results = self._apply_text_corrections(all_ocr_results)
            
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
            
            logger.info(f"Enhanced Tesseract OCR completed: {len(all_ocr_results)} text regions from {len(images)} pages")
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=all_ocr_results,
                processing_time_ms=processing_time
            )
            
        except Exception as e:
            logger.error(f"Enhanced Tesseract OCR processing failed for {file_path}: {e}")
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
            # Convert PDF to images with higher DPI for handwriting
            images = convert_from_path(
                pdf_path,
                dpi=self.image_settings['dpi'],
                fmt='RGB'
            )
            
            logger.debug(f"Converted PDF to {len(images)} images at {self.image_settings['dpi']} DPI")
            return images
            
        except Exception as e:
            logger.error(f"Error converting PDF to images: {e}")
            return []
    
    def _enhanced_preprocess_image(self, image: Image.Image) -> Image.Image:
        """Enhanced preprocessing for handwritten text."""
        try:
            # Resize for better recognition
            resize_factor = self.image_settings['resize_factor']
            if resize_factor != 1.0:
                new_size = (
                    int(image.width * resize_factor),
                    int(image.height * resize_factor)
                )
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Convert to grayscale
            if image.mode != 'L':
                image = ImageOps.grayscale(image)
            
            # Noise reduction
            if self.image_settings['noise_reduction']:
                image = image.filter(ImageFilter.MedianFilter(size=3))
            
            # Minimal blur to smooth pen strokes
            blur_radius = self.image_settings['gaussian_blur_radius']
            if blur_radius > 0:
                image = image.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            
            # Enhance contrast for handwriting
            contrast_factor = self.image_settings['contrast_enhancement']
            if contrast_factor != 1.0:
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(contrast_factor)
            
            # Ensure high contrast (black ink on white paper)
            image_array = np.array(image)
            if np.mean(image_array) < 128:  # Dark background
                image = ImageOps.invert(image)
            
            # Line enhancement for handwriting
            if self.image_settings['line_enhancement']:
                image = self._enhance_handwriting_lines(image)
            
            return image
            
        except Exception as e:
            logger.error(f"Error in enhanced preprocessing: {e}")
            return image
    
    def _enhance_handwriting_lines(self, image: Image.Image) -> Image.Image:
        """Enhance handwritten lines for better recognition."""
        try:
            # Convert to numpy for processing
            img_array = np.array(image)
            
            # Apply morphological operations to enhance lines
            from scipy import ndimage
            
            # Create a small kernel for line enhancement
            kernel = np.array([[0, 1, 0],
                              [1, 1, 1],
                              [0, 1, 0]], dtype=np.uint8)
            
            # Apply closing to connect broken lines
            enhanced = ndimage.binary_closing(img_array < 128, structure=kernel)
            
            # Convert back to PIL Image
            enhanced_img = Image.fromarray((~enhanced * 255).astype(np.uint8), mode='L')
            
            return enhanced_img
            
        except ImportError:
            # If scipy not available, return original
            logger.debug("scipy not available for line enhancement")
            return image
        except Exception as e:
            logger.error(f"Error in line enhancement: {e}")
            return image
    
    def _perform_enhanced_ocr(self, image: Image.Image) -> List[OCRResult]:
        """Perform OCR with multiple configurations and choose best results."""
        if not self.tesseract_available:
            logger.error("Tesseract not available")
            return []
        
        all_results = []
        
        # Try different configurations if enabled
        configs_to_try = self.tesseract_configs if self.use_multiple_configs else [self.tesseract_configs[0]]
        
        for config_idx, config in enumerate(configs_to_try):
            try:
                logger.debug(f"Trying Tesseract config {config_idx + 1}/{len(configs_to_try)}: {config}")
                
                # Get OCR data with bounding boxes and confidence
                ocr_data = pytesseract.image_to_data(
                    image,
                    lang=self.language,
                    config=config,
                    output_type=pytesseract.Output.DICT
                )
                
                config_results = []
                
                # Process each detected text element
                for i in range(len(ocr_data['text'])):
                    text = ocr_data['text'][i].strip()
                    confidence = float(ocr_data['conf'][i])
                    
                    # Skip empty text or very low confidence
                    if not text or confidence < self.text_filters['min_confidence']:
                        continue
                    
                    # Skip very short text unless it might be meaningful
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
                    
                    config_results.append(ocr_result)
                
                all_results.extend(config_results)
                logger.debug(f"Config {config_idx + 1} found {len(config_results)} text regions")
                
            except Exception as e:
                logger.error(f"Error with Tesseract config {config_idx + 1}: {e}")
                continue
        
        # Remove duplicates and choose best results
        if self.use_multiple_configs:
            all_results = self._merge_duplicate_results(all_results)
        
        # Merge nearby text regions if enabled
        if self.text_filters['merge_nearby_text']:
            all_results = self._merge_nearby_text(all_results)
        
        logger.debug(f"Enhanced Tesseract OCR found {len(all_results)} final text regions")
        
        return all_results
    
    def _merge_duplicate_results(self, results: List[OCRResult]) -> List[OCRResult]:
        """Merge duplicate results from different configurations, keeping the best."""
        if len(results) <= 1:
            return results
        
        # Group results by spatial proximity
        groups = []
        used_indices = set()
        
        for i, result1 in enumerate(results):
            if i in used_indices:
                continue
            
            group = [result1]
            used_indices.add(i)
            
            for j, result2 in enumerate(results):
                if j in used_indices or j <= i:
                    continue
                
                # Check if results overlap spatially
                if self._results_overlap(result1, result2):
                    group.append(result2)
                    used_indices.add(j)
            
            groups.append(group)
        
        # For each group, choose the result with highest confidence
        final_results = []
        for group in groups:
            if len(group) == 1:
                final_results.append(group[0])
            else:
                best_result = max(group, key=lambda r: r.confidence)
                final_results.append(best_result)
        
        return final_results
    
    def _results_overlap(self, result1: OCRResult, result2: OCRResult, threshold: float = 0.5) -> bool:
        """Check if two OCR results overlap spatially."""
        bbox1 = result1.bounding_box
        bbox2 = result2.bounding_box
        
        # Calculate intersection
        left = max(bbox1.x, bbox2.x)
        top = max(bbox1.y, bbox2.y)
        right = min(bbox1.x + bbox1.width, bbox2.x + bbox2.width)
        bottom = min(bbox1.y + bbox1.height, bbox2.y + bbox2.height)
        
        if left >= right or top >= bottom:
            return False  # No intersection
        
        intersection_area = (right - left) * (bottom - top)
        area1 = bbox1.width * bbox1.height
        area2 = bbox2.width * bbox2.height
        
        # Check if intersection is significant relative to either box
        overlap_ratio1 = intersection_area / area1 if area1 > 0 else 0
        overlap_ratio2 = intersection_area / area2 if area2 > 0 else 0
        
        return max(overlap_ratio1, overlap_ratio2) > threshold
    
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
    
    def _apply_text_corrections(self, ocr_results: List[OCRResult]) -> List[OCRResult]:
        """Apply pattern recognition and text corrections."""
        corrected_results = []
        
        for result in ocr_results:
            corrected_text = result.text
            
            # Apply common corrections if enabled
            if self.pattern_recognition['common_corrections']:
                for pattern, replacement in self.common_corrections.items():
                    corrected_text = re.sub(pattern, replacement, corrected_text)
            
            # Detect and correct arrow patterns
            if self.pattern_recognition['detect_arrows']:
                corrected_text = self._detect_arrows(corrected_text)
            
            # Detect bullets and checkboxes
            if self.pattern_recognition['detect_bullets']:
                corrected_text = self._detect_bullets(corrected_text)
            
            # Clean up the text
            corrected_text = corrected_text.strip()
            
            # Only include if text is meaningful after corrections
            if corrected_text and len(corrected_text) > 0:
                # Create new result with corrected text
                corrected_result = OCRResult(
                    text=corrected_text,
                    confidence=result.confidence,
                    bounding_box=result.bounding_box,
                    language=result.language,
                    page_number=result.page_number
                )
                corrected_results.append(corrected_result)
        
        logger.debug(f"Applied corrections: {len(ocr_results)} → {len(corrected_results)} results")
        return corrected_results
    
    def _detect_arrows(self, text: str) -> str:
        """Detect and correct arrow patterns in text."""
        # Common arrow misinterpretations
        arrow_patterns = [
            (r'\bL\s*>', '→'),  # L> becomes →
            (r'\bL\s*-', '→'),  # L- becomes →
            (r'\|\s*L', '|→'), # |L becomes |→
            (r'\|\s*-\s*>', '|→'), # |-> becomes |→
            (r'-\s*>', '→'),   # -> becomes →
            (r'=\s*>', '⇒'),   # => becomes ⇒
            (r'<\s*-', '←'),   # <- becomes ←
            (r'<\s*=', '⇐'),   # <= becomes ⇐
        ]
        
        corrected_text = text
        for pattern, replacement in arrow_patterns:
            corrected_text = re.sub(pattern, replacement, corrected_text)
        
        return corrected_text
    
    def _detect_bullets(self, text: str) -> str:
        """Detect and correct bullet point patterns."""
        # Common bullet misinterpretations
        bullet_patterns = [
            (r'^\s*\*\s*', '• '),  # * becomes bullet
            (r'^\s*-\s*', '• '),   # - becomes bullet
            (r'^\s*o\s*', '• '),   # o becomes bullet
            (r'\[\s*\]', '☐'),     # [] becomes checkbox
            (r'\[\s*x\s*\]', '☑'), # [x] becomes checked box
            (r'\[\s*X\s*\]', '☑'), # [X] becomes checked box
        ]
        
        corrected_text = text
        for pattern, replacement in bullet_patterns:
            corrected_text = re.sub(pattern, replacement, corrected_text)
        
        return corrected_text
    
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
            logger.info(f"Stored {len(ocr_results)} Enhanced Tesseract OCR results for {source_file}")
            
        except Exception as e:
            logger.error(f"Error storing Enhanced Tesseract OCR results: {e}")


# Test function
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python enhanced_tesseract_ocr.py <pdf_file>")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    
    print("Testing Enhanced Tesseract OCR Engine")
    print("=" * 50)
    
    engine = EnhancedTesseractOCREngine(confidence_threshold=60.0)
    
    print(f"Engine available: {engine.is_available()}")
    print(f"Can process {pdf_file}: {engine.can_process(pdf_file)}")
    
    if engine.is_available() and engine.can_process(pdf_file):
        print(f"\nProcessing {pdf_file} with enhanced OCR...")
        result = engine.process_file(pdf_file)
        
        print(f"Success: {result.success}")
        if result.success:
            print(f"Text regions found: {len(result.ocr_results)}")
            print(f"Processing time: {result.processing_time_ms}ms")
            
            if result.ocr_results:
                print("\nFirst few text regions:")
                for i, ocr_result in enumerate(result.ocr_results[:10]):
                    print(f"  {i+1}. '{ocr_result.text}' (confidence: {ocr_result.confidence:.2f})")
        else:
            print(f"Error: {result.error_message}")
    else:
        print("Cannot process file or engine not available")