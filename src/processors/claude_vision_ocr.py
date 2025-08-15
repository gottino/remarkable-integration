"""
Claude Vision OCR Engine for reMarkable Integration.

Uses Claude's vision capabilities for superior handwritten text recognition.
This should provide much better results than traditional OCR engines.
"""

import os
import logging
import sqlite3
import json
import base64
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path
import time

# Core dependencies
import numpy as np
from PIL import Image

# PDF processing
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except (ImportError, ModuleNotFoundError) as e:
    PDF2IMAGE_AVAILABLE = False
    import logging
    logging.getLogger(__name__).info(f"pdf2image not available: {e}")

# Claude API
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except (ImportError, ModuleNotFoundError) as e:
    ANTHROPIC_AVAILABLE = False
    import logging
    logging.getLogger(__name__).info(f"anthropic not available: {e}")

# Import base classes for compatibility
from .tesseract_ocr_engine import BoundingBox, OCRResult, ProcessingResult

# Database and events
from ..core.events import get_event_bus, EventType
from ..core.database import DatabaseManager

logger = logging.getLogger(__name__)


class ClaudeVisionOCREngine:
    """OCR engine using Claude's vision capabilities for handwritten text."""
    
    def __init__(
        self, 
        db_connection: Optional[sqlite3.Connection] = None,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
        confidence_threshold: float = 0.8
    ):
        """
        Initialize Claude Vision OCR engine.
        
        Args:
            db_connection: Optional database connection for storing results
            api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var)
            model: Claude model to use for OCR
            confidence_threshold: Confidence threshold (0-1)
        """
        self.processor_type = "claude_vision_ocr_engine"
        self.db_connection = db_connection
        self.model = model
        self.confidence_threshold = confidence_threshold
        
        # Initialize Claude client
        self.client = None
        if ANTHROPIC_AVAILABLE:
            try:
                api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
                if api_key:
                    # Try with custom httpx client that handles SSL issues
                    import httpx
                    
                    # Create custom client that can handle SSL issues
                    custom_client = httpx.Client(
                        verify=False,  # Disable SSL verification for corporate environments
                        timeout=30.0
                    )
                    
                    self.client = anthropic.Anthropic(
                        api_key=api_key,
                        http_client=custom_client
                    )
                    logger.info(f"Claude Vision OCR initialized with model: {model} (SSL verification disabled)")
                else:
                    logger.error("No Anthropic API key found. Set ANTHROPIC_API_KEY environment variable.")
            except Exception as e:
                logger.error(f"Failed to initialize Claude client: {e}")
                # Fallback: try without custom client
                try:
                    self.client = anthropic.Anthropic(api_key=api_key)
                    logger.info(f"Claude Vision OCR initialized with model: {model} (fallback mode)")
                except Exception as e2:
                    logger.error(f"Fallback client also failed: {e2}")
                    self.client = None
        
        if not PDF2IMAGE_AVAILABLE:
            logger.error("pdf2image not available. Install with: pip install pdf2image")
        
        # Image processing settings
        self.image_settings = {
            'dpi': 300,  # Good quality for Claude
            'format': 'PNG',  # PNG for best quality
            'max_size': (1568, 1568),  # Claude's max image size
            'quality': 95,
        }
        
        # OCR prompt for handwritten text with markdown and date extraction
        self.ocr_prompt = """Please transcribe all handwritten text from this image in Markdown format.

Instructions:
- Extract ALL visible handwritten text, including notes, arrows, symbols, and annotations
- Format the output as clean Markdown with proper structure
- Use ## for main headings, ### for subheadings
- For arrows, use → ← ↑ ↓ symbols
- For bullet points, use proper Markdown bullets (- or *)
- For checkboxes, use - [ ] for empty and - [x] for checked
- Use **bold** for emphasis where appropriate
- Use `code` for any technical terms or special notation
- Maintain line breaks and logical structure

IMPORTANT - Date Detection:
Look specifically in the UPPER RIGHT CORNER for a date in format dd-mm-yyyy that might be surrounded by a "lying L" or bracket-like shape (⌐ or similar). This is crucial for organizing the content chronologically.

If you find a date in the upper right corner:
- Start your transcription with: "**Date: dd-mm-yyyy**"
- Then add a horizontal rule: "---"
- Then proceed with the content

Output Format:
1. If date found: **Date: dd-mm-yyyy**\n---\n[content]
2. If no date: Just the content in Markdown format

Return only the formatted Markdown text, no explanations."""
        
        logger.info(f"Claude Vision OCR Engine initialized (available: {self.is_available()})")
    
    def is_available(self) -> bool:
        """Check if Claude Vision OCR is available."""
        return ANTHROPIC_AVAILABLE and PDF2IMAGE_AVAILABLE and self.client is not None
    
    def can_process(self, file_path: str) -> bool:
        """Check if file can be processed."""
        if not self.is_available():
            return False
        return file_path.lower().endswith('.pdf')
    
    def process_file(self, file_path: str) -> ProcessingResult:
        """Process a PDF file using Claude Vision OCR."""
        start_time = time.time()
        
        if not self.is_available():
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="Claude Vision OCR engine not available"
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
            logger.info(f"Processing PDF with Claude Vision OCR: {file_path}")
            
            # Convert PDF to images
            images = self._pdf_to_images(file_path)
            if not images:
                raise ValueError("Failed to convert PDF to images")
            
            # Process each page with Claude
            all_ocr_results = []
            for page_num, image in enumerate(images, 1):
                logger.debug(f"Processing page {page_num}/{len(images)} with Claude Vision")
                
                # Prepare image for Claude
                processed_image = self._prepare_image_for_claude(image)
                
                # Get transcription from Claude
                page_text = self._transcribe_with_claude(processed_image)
                
                if page_text and page_text.strip():
                    # Create OCR result (Claude doesn't provide bounding boxes)
                    # We'll create a single result for the entire page
                    page_result = OCRResult(
                        text=page_text.strip(),
                        confidence=self.confidence_threshold,  # Claude is generally high confidence
                        bounding_box=BoundingBox(x=0, y=0, width=image.width, height=image.height),
                        language='en',
                        page_number=page_num
                    )
                    all_ocr_results.append(page_result)
                    logger.debug(f"Page {page_num}: extracted {len(page_text)} characters")
                else:
                    logger.warning(f"Page {page_num}: no text extracted")
            
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
            
            logger.info(f"Claude Vision OCR completed: {len(all_ocr_results)} pages processed")
            
            return ProcessingResult(
                success=True,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=all_ocr_results,
                processing_time_ms=processing_time
            )
            
        except Exception as e:
            logger.error(f"Claude Vision OCR processing failed for {file_path}: {e}")
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
            # Convert PDF to images
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
    
    def _prepare_image_for_claude(self, image: Image.Image) -> str:
        """Prepare image for Claude API (resize and encode as base64)."""
        try:
            # Resize if too large for Claude
            max_size = self.image_settings['max_size']
            if image.width > max_size[0] or image.height > max_size[1]:
                image.thumbnail(max_size, Image.Resampling.LANCZOS)
                logger.debug(f"Resized image to {image.size}")
            
            # Convert to PNG bytes
            import io
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='PNG', quality=self.image_settings['quality'])
            img_byte_arr = img_byte_arr.getvalue()
            
            # Encode to base64
            img_base64 = base64.b64encode(img_byte_arr).decode('utf-8')
            
            return img_base64
            
        except Exception as e:
            logger.error(f"Error preparing image for Claude: {e}")
            raise
    
    def _transcribe_with_claude(self, image_base64: str) -> Optional[str]:
        """Send image to Claude for transcription."""
        if not self.client:
            logger.error("Claude client not initialized")
            return None
        
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": self.ocr_prompt
                            }
                        ]
                    }
                ]
            )
            
            if message.content and len(message.content) > 0:
                # Extract text from Claude's response
                response_text = message.content[0].text if hasattr(message.content[0], 'text') else str(message.content[0])
                logger.debug(f"Claude transcription: {len(response_text)} characters")
                return response_text
            else:
                logger.warning("Claude returned empty response")
                return None
                
        except Exception as e:
            logger.error(f"Error calling Claude API: {e}")
            return None
    
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
            logger.info(f"Stored {len(ocr_results)} Claude Vision OCR results for {source_file}")
            
        except Exception as e:
            logger.error(f"Error storing Claude Vision OCR results: {e}")


# Test function
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python claude_vision_ocr.py <pdf_file>")
        print("Make sure to set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    
    print("Testing Claude Vision OCR Engine")
    print("=" * 50)
    
    engine = ClaudeVisionOCREngine()
    
    print(f"Engine available: {engine.is_available()}")
    print(f"Can process {pdf_file}: {engine.can_process(pdf_file)}")
    
    if engine.is_available() and engine.can_process(pdf_file):
        print(f"\nProcessing {pdf_file} with Claude Vision...")
        result = engine.process_file(pdf_file)
        
        print(f"Success: {result.success}")
        if result.success:
            print(f"Pages processed: {len(result.ocr_results)}")
            print(f"Processing time: {result.processing_time_ms}ms")
            
            if result.ocr_results:
                print("\nTranscribed text:")
                for i, ocr_result in enumerate(result.ocr_results):
                    print(f"\n--- Page {i+1} ---")
                    print(ocr_result.text)
        else:
            print(f"Error: {result.error_message}")
    else:
        print("Cannot process file or engine not available")
        if not os.getenv('ANTHROPIC_API_KEY'):
            print("Tip: Set ANTHROPIC_API_KEY environment variable")