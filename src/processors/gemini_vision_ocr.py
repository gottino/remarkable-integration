"""
Gemini Vision OCR Engine for reMarkable Integration.

Uses Google Gemini's vision capabilities for handwritten text recognition.
Replaces the previous Claude Vision engine: Gemini accepts PDF bytes natively,
so there is no PDF→image conversion and no rate limiter.

The public surface (BoundingBox, OCRResult, ProcessingResult, and the engine's
is_available / can_process / process_file methods) matches the old
ClaudeVisionOCREngine so the only production caller
(notebook_text_extractor.py) needs no behavioural changes.
"""

import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# Gemini SDK
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except (ImportError, ModuleNotFoundError) as e:
    GENAI_AVAILABLE = False
    logging.getLogger(__name__).info(f"google-genai not available: {e}")

# Database and events
from ..core.events import get_event_bus, EventType

# Configuration
from ..utils.config import Config

# API key management
from ..utils.api_keys import get_google_api_key

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
    """Result of OCR processing on a file."""
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


def _strip_wrapping_code_fence(text: str) -> str:
    """Remove a code fence ONLY when it wraps the entire response.

    Gemini sometimes wraps the whole transcription in a ```markdown ... ``` (or
    bare ```) block. We strip that outer wrapper, but we must NOT touch fences
    that are part of the content — in particular the ```mermaid ... ``` diagram
    blocks this prompt asks for. So we only unwrap when the first line is a
    *wrapper* fence (empty / markdown / md / text language tag) and a matching
    closing fence ends the output; embedded mermaid/code fences are preserved.
    """
    stripped = text.strip()
    match = re.match(r'^```([A-Za-z0-9_+-]*)\n(.*)\n```$', stripped, re.DOTALL)
    if match and match.group(1).lower() in ('', 'markdown', 'md', 'text'):
        return match.group(2).strip()
    return stripped


class GeminiVisionOCREngine:
    """OCR engine using Google Gemini's vision capabilities for handwritten text."""

    def __init__(
        self,
        db_connection: Optional[sqlite3.Connection] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        confidence_threshold: float = 0.8,
        config: Optional[Config] = None
    ):
        """
        Initialize Gemini Vision OCR engine.

        Args:
            db_connection: Accepted for call-site compatibility but unused. The
                consumed transcription is persisted to notebook_text_extractions
                by notebook_text_extractor.py; the engine only returns results.
            api_key: Google AI API key (falls back to stored key / env var).
            model: Gemini model to use (defaults to config 'processing.ocr.model').
            confidence_threshold: Placeholder confidence (Gemini gives no per-page
                score); stored verbatim, matching the previous engine's convention.
            config: Optional Config instance for loading custom prompts.
        """
        self.processor_type = "gemini_vision_ocr_engine"
        self.db_connection = db_connection  # accepted for signature parity; unused
        self.confidence_threshold = confidence_threshold
        self.config = config or Config()
        self.model = model or self.config.get('processing.ocr.model', 'gemini-2.5-flash')

        # Initialize Gemini client
        self.client = None
        if GENAI_AVAILABLE:
            try:
                api_key = api_key or get_google_api_key()
                if api_key:
                    self.client = genai.Client(api_key=api_key)
                    logger.info(f"Gemini Vision OCR initialized with model: {self.model}")
                else:
                    logger.error(
                        "No Google API key found. Use "
                        "'config api-key set --service google' to configure your API key."
                    )
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self.client = None
        else:
            logger.error("google-genai not available. Install with: poetry add google-genai")

        # Load OCR prompt from config file or use default
        self.ocr_prompt = self._load_prompt()

        logger.info(f"Gemini Vision OCR Engine initialized (available: {self.is_available()})")

    def _load_prompt(self) -> str:
        """Load OCR prompt from config file with fallback to default."""
        try:
            prompt_file = self.config.get('processing.ocr.prompt_file')
            if prompt_file:
                prompt_path = Path(prompt_file)

                # Make relative paths relative to project root
                if not prompt_path.is_absolute():
                    # src/processors/ -> src/ -> project root
                    project_root = Path(__file__).parent.parent.parent
                    prompt_path = project_root / prompt_file

                if prompt_path.exists():
                    prompt_content = prompt_path.read_text(encoding='utf-8')
                    logger.info(f"✓ Loaded OCR prompt from: {prompt_path}")
                    return prompt_content
                else:
                    logger.warning(f"Prompt file not found: {prompt_path}, using default prompt")
            else:
                logger.debug("No prompt_file configured, using default prompt")
        except Exception as e:
            logger.warning(f"Error loading prompt file: {e}, using default prompt")

        logger.info("Using default OCR prompt")
        return self._default_prompt()

    def _default_prompt(self) -> str:
        """Return the default OCR prompt (used only if the prompt file is missing)."""
        return """Please transcribe all handwritten text from this page in Markdown format.
The content is a mix of German and English.

Instructions:
- Extract ALL visible handwritten text, including notes, arrows, symbols, and annotations
- Preserve the layout: line breaks, indentation, and spatial hierarchy as written
- Use ## for main headings, ### for subheadings
- For straight arrows, use → ← ↑ ↓ symbols
- For curved/hooked arrows (↳), use ↳ — these indicate indented sub-points, NOT tasks
- For bullet points, use - (dash), NOT asterisks
- For checkboxes (square boxes □), use - [ ] for empty and - [x] for checked
- Use **bold** for emphasis where appropriate
- Maintain line breaks and logical structure

IMPORTANT - Date Detection:
Look on the RIGHT SIDE of the page for dates in dd-mm-yyyy format (European),
possibly surrounded by a bracket-like shape. If you find one:
- Start your transcription with: "**Date: dd-mm-yyyy**"
- Then a horizontal rule: "---"
- Then the content

Return only the formatted Markdown text, no explanations, no surrounding code fences."""

    def is_available(self) -> bool:
        """Check if Gemini Vision OCR is available."""
        return GENAI_AVAILABLE and self.client is not None

    def can_process(self, file_path: str) -> bool:
        """Check if file can be processed."""
        if not self.is_available():
            return False
        return file_path.lower().endswith('.pdf')

    def process_file(self, file_path: str) -> ProcessingResult:
        """Process a single-page PDF file using Gemini Vision OCR."""
        start_time = time.time()

        if not self.is_available():
            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message="Gemini Vision OCR engine not available"
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
            logger.info(f"Processing PDF with Gemini Vision OCR: {file_path}")

            pdf_bytes = Path(file_path).read_bytes()

            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                    self.ocr_prompt,
                ],
            )

            text = _strip_wrapping_code_fence(response.text or "")

            # Optional token accounting for cost visibility
            input_tokens = output_tokens = 0
            usage = getattr(response, 'usage_metadata', None)
            if usage:
                input_tokens = getattr(usage, 'prompt_token_count', 0) or 0
                output_tokens = getattr(usage, 'candidates_token_count', 0) or 0

            ocr_results: List[OCRResult] = []
            if text:
                # The caller always passes a single-page PDF; the whole document
                # is one page. Bounding box is unused by Gemini (no per-region data).
                ocr_results.append(OCRResult(
                    text=text,
                    confidence=self.confidence_threshold,
                    bounding_box=BoundingBox(x=0, y=0, width=0, height=0),
                    language='en',
                    page_number=1,
                ))
                logger.debug(f"Extracted {len(text)} characters")
            else:
                logger.warning(f"Gemini returned no text for {file_path}")

            # Emit OCR completed event
            event_bus = get_event_bus()
            if event_bus:
                event_bus.emit(EventType.OCR_COMPLETED, {
                    'file_path': file_path,
                    'text_count': len(ocr_results),
                    'page_count': 1,
                    'processor_type': self.processor_type,
                    'total_confidence': self.confidence_threshold if ocr_results else 0.0,
                })

            processing_time = int((time.time() - start_time) * 1000)
            logger.info(
                f"Gemini Vision OCR completed: {len(ocr_results)} page(s), "
                f"{input_tokens} in / {output_tokens} out tokens, {processing_time}ms"
            )

            return ProcessingResult(
                success=True,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=ocr_results,
                processing_time_ms=processing_time
            )

        except Exception as e:
            logger.error(f"Gemini Vision OCR processing failed for {file_path}: {e}")
            processing_time = int((time.time() - start_time) * 1000)

            return ProcessingResult(
                success=False,
                file_path=file_path,
                processor_type=self.processor_type,
                ocr_results=[],
                error_message=str(e),
                processing_time_ms=processing_time
            )


# Test function / smoke test
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.processors.gemini_vision_ocr <pdf_file>")
        print("Make sure a Google API key is configured (config api-key set --service google)")
        print("or set GOOGLE_API_KEY / GEMINI_API_KEY.")
        sys.exit(1)

    pdf_file = sys.argv[1]

    print("Testing Gemini Vision OCR Engine")
    print("=" * 50)

    engine = GeminiVisionOCREngine()

    print(f"Engine available: {engine.is_available()}")
    print(f"Can process {pdf_file}: {engine.can_process(pdf_file)}")

    if engine.is_available() and engine.can_process(pdf_file):
        print(f"\nProcessing {pdf_file} with Gemini Vision...")
        result = engine.process_file(pdf_file)

        print(f"Success: {result.success}")
        if result.success:
            print(f"Pages processed: {len(result.ocr_results)}")
            print(f"Processing time: {result.processing_time_ms}ms")

            for i, ocr_result in enumerate(result.ocr_results):
                print(f"\n--- Page {i + 1} ---")
                print(ocr_result.text)
        else:
            print(f"Error: {result.error_message}")
    else:
        print("Cannot process file or engine not available")
