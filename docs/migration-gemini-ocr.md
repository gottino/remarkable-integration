# Migration Plan: Replace Claude Vision OCR with Google Gemini 2.5 Flash

**Status:** Planned — not yet executed
**Author:** drafted 2026-05-27
**Estimated effort:** half a day end-to-end including validation
**Target machine:** any dev machine with the repo checked out

---

## Motivation

The current pipeline uses Anthropic's `claude-haiku-4-5` for handwriting OCR via the Claude Vision API. Validated on the sister project `rmirror-cloud`, Google's `gemini-2.5-flash` produces equal or better OCR quality on handwritten reMarkable pages at meaningfully lower cost. This document describes a full replacement (not a dual-provider abstraction) because:

- We have **one production caller** of the OCR engine, so the cost of an abstraction layer is not justified.
- The prompt is already file-driven and provider-agnostic — only the SDK call needs to change.
- Gemini accepts PDF bytes natively, which lets us delete the entire `pdf2image` → base64 image pipeline.
- Rate limiting becomes unnecessary because Gemini Flash's quotas are an order of magnitude higher and the `google-genai` SDK handles backoff.

Net effect: **~440 fewer lines of code**, one fewer SDK dependency, both prompt and model become file-editable.

---

## Current architecture (what we are replacing)

### Files that touch the OCR engine

| File | Lines | Role |
|---|---|---|
| `src/processors/claude_vision_ocr.py` | 617 | Whole engine: rate limiter, PDF→image, Claude API call, prompt loading, DB write |
| `src/processors/notebook_text_extractor.py` | 4 touchpoints (lines 27, 90, 369, 901) | Only production caller — imports `ClaudeVisionOCREngine, OCRResult`, calls `is_available()` and `process_file()` |
| `src/utils/api_keys.py` | ~5 methods | Anthropic-only key storage helpers |
| `src/cli/main.py` (~lines 210–282) | 4 commands | `config api-key set/get/remove/list`, currently Anthropic-specific |
| `config/config.yaml` (line 46) | 1 key | `processing.ocr.claude_prompt_file` |
| `config/prompts/claude_ocr_default.txt` | — | File-based prompt; already nearly provider-agnostic |
| `pyproject.toml` (line 38) | 1 dep | `anthropic = "^0.64.0"` |
| `tests/manual/test_enhanced_extraction.py` | 1 file | The only test reference |

### How `notebook_text_extractor.py` uses the engine

```python
# line 27
from .claude_vision_ocr import ClaudeVisionOCREngine, OCRResult

# line 90 — in a dataclass field
ocr_results: List[OCRResult]

# lines 369–372 — construction
self.ocr_engine = ClaudeVisionOCREngine(
    db_connection=db_connection,
    confidence_threshold=confidence_threshold,
)

# line 375, 391 — capability check
self.ocr_engine.is_available()

# line 901 — actual call
ocr_result = self.ocr_engine.process_file(str(pdf_file))
```

This is the **entire** integration surface. The new engine must preserve this exact contract.

### Public contract of `ClaudeVisionOCREngine` (to be matched verbatim by the new class)

- Constructor takes `db_connection`, `api_key`, `model`, `confidence_threshold`, `config` (we drop the three `rate_limit_*` params).
- `is_available() -> bool`
- `can_process(file_path: str) -> bool`
- `process_file(pdf_path: str) -> ProcessingResult`

The dataclasses `BoundingBox`, `OCRResult`, `ProcessingResult` are defined inside `claude_vision_ocr.py` today. The new file must export `OCRResult` (imported by `notebook_text_extractor.py`) with the same field shape so no downstream changes are needed.

### Reference implementation

`rmirror-cloud/backend/app/core/ocr_service.py` (~180 lines) is the production reference for the Gemini call. Read it before starting. Key adaptations needed:

- Their service is `async`; ours is sync (callers run inside `loop.run_in_executor`). Keep the new class sync — the `google-genai` `generate_content` call is sync anyway.
- They send PDF bytes directly via `types.Part.from_bytes(pdf_bytes, "application/pdf")` — **this is the central simplification** that lets us drop `pdf2image`.
- They strip markdown code fences (` ``` `) from Gemini's output. Keep this.
- They use a hardcoded `OCR_PROMPT` constant; **we load from a file** via the existing prompt-loader pattern (see `_load_prompt` in `claude_vision_ocr.py`).

---

## Implementation phases

Each phase is a clean commit point. Run `poetry run pytest` and a quick manual OCR call between phases.

### Phase 1 — Dependencies and API key management (no behavior change)

**1.1 `pyproject.toml`**

- Remove `anthropic = "^0.64.0"`.
- Add `google-genai = "^1.0.0"` (verify latest stable version with `poetry search google-genai` or PyPI).
- Run `poetry lock && poetry install`.
- Decide whether to keep `pdf2image` and `pillow`:
  - `pdf2image` — only used by `claude_vision_ocr.py`. **Safe to drop.**
  - `pillow` — likely used by the SVG/PDF rendering pipeline (`rm_converter` etc.). Grep `from PIL` and `import PIL` before removing.

**1.2 `src/utils/api_keys.py`**

- Add three new methods mirroring the Anthropic ones:
  - `get_google_ai_api_key() -> Optional[str]`
  - `store_google_ai_api_key(api_key: str, method: str = 'auto') -> bool`
  - `remove_google_ai_api_key() -> bool`
- Use keychain entry name `google-ai-api-key`.
- Add a top-level convenience `def get_google_ai_api_key()` mirroring `get_anthropic_api_key()` at the bottom of the file.
- **Keep the Anthropic methods for now** — they get deleted in Phase 4 once we know everything works.

**1.3 `src/cli/main.py` (~lines 210–282)**

Generalize the `config api-key` command group to take a service. Recommended shape:

```bash
poetry run python -m src.cli.main config api-key set --service gemini
poetry run python -m src.cli.main config api-key set --service anthropic   # still works during transition
```

- Add `--service` (default `gemini`) to `set/get/remove`.
- Make the `sk-ant-` prefix check conditional on service. Gemini keys typically start with `AIza`.
- `list` should already work since it walks the keychain entries.

### Phase 2 — Build the new engine

**2.1 Create `src/processors/gemini_vision_ocr.py`**

Mirror the public surface of `claude_vision_ocr.py`. Approximate skeleton (~180 lines):

```python
"""Gemini Vision OCR engine for handwritten text extraction."""
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError as e:
    GENAI_AVAILABLE = False

from ..core.events import EventType, get_event_bus
from ..utils.api_keys import get_google_ai_api_key
from ..utils.config import Config

logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    x: float
    y: float
    width: float
    height: float
    def to_dict(self) -> Dict[str, float]: ...

@dataclass
class OCRResult:
    text: str
    confidence: float
    bounding_box: BoundingBox
    language: str
    page_number: int
    def to_dict(self) -> Dict[str, Any]: ...

@dataclass
class ProcessingResult:
    success: bool
    file_path: str
    processor_type: str
    ocr_results: List[OCRResult]
    error_message: Optional[str] = None
    processing_time_ms: Optional[int] = None
    def to_dict(self) -> Dict[str, Any]: ...


class GeminiVisionOCREngine:
    def __init__(
        self,
        db_connection: Optional[sqlite3.Connection] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        confidence_threshold: float = 0.8,
        config: Optional[Config] = None,
    ):
        self.processor_type = "gemini_vision_ocr_engine"
        self.db_connection = db_connection
        self.confidence_threshold = confidence_threshold
        self.config = config or Config()
        self.model = model or self.config.get('processing.ocr.model', 'gemini-2.5-flash')

        self.client = None
        if GENAI_AVAILABLE:
            api_key = api_key or get_google_ai_api_key()
            if api_key:
                self.client = genai.Client(api_key=api_key)
                logger.info(f"Gemini Vision OCR initialized with model: {self.model}")
            else:
                logger.error("No Google AI API key found. Use 'config api-key set --service gemini' to configure.")

        self.ocr_prompt = self._load_prompt()
        logger.info(f"Gemini Vision OCR Engine initialized (available: {self.is_available()})")

    def _load_prompt(self) -> str: ...        # copy from claude_vision_ocr.py; reads config key 'processing.ocr.prompt_file'
    def is_available(self) -> bool:
        return self.client is not None
    def can_process(self, file_path: str) -> bool: ...   # check .pdf extension and file exists

    def process_file(self, file_path: str) -> ProcessingResult:
        start_time = time.time()
        if not self.is_available():
            return ProcessingResult(success=False, file_path=file_path, processor_type=self.processor_type,
                                    ocr_results=[], error_message="Gemini Vision OCR engine not available")
        if not self.can_process(file_path):
            return ProcessingResult(success=False, file_path=file_path, processor_type=self.processor_type,
                                    ocr_results=[], error_message="File cannot be processed")
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

            text = response.text or ""
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text).strip()

            ocr_results: List[OCRResult] = []
            if text:
                ocr_results.append(OCRResult(
                    text=text,
                    confidence=self.confidence_threshold,
                    bounding_box=BoundingBox(x=0, y=0, width=0, height=0),
                    language='en',
                    page_number=1,
                ))

            if self.db_connection and ocr_results:
                self._store_ocr_results(ocr_results, file_path)

            bus = get_event_bus()
            if bus:
                bus.emit(EventType.OCR_COMPLETED, {
                    'file_path': file_path,
                    'text_count': len(ocr_results),
                    'page_count': 1,
                    'processor_type': self.processor_type,
                    'total_confidence': self.confidence_threshold if ocr_results else 0.0,
                })

            return ProcessingResult(
                success=True, file_path=file_path, processor_type=self.processor_type,
                ocr_results=ocr_results,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            logger.error(f"Gemini Vision OCR processing failed for {file_path}: {e}")
            return ProcessingResult(
                success=False, file_path=file_path, processor_type=self.processor_type,
                ocr_results=[], error_message=str(e),
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

    def _store_ocr_results(self, ocr_results: List[OCRResult], source_file: str):
        # Copy verbatim from claude_vision_ocr.py — same schema, same INSERT.
        ...
```

Notes:

- The `_load_prompt` and `_store_ocr_results` methods can be copied verbatim from `claude_vision_ocr.py` — they have no Claude-specific logic. Only swap the config key name from `processing.ocr.claude_prompt_file` to `processing.ocr.prompt_file`.
- The `_default_prompt()` fallback string in `claude_vision_ocr.py` should also be copied — the prompt content is provider-agnostic.
- Keep the `if __name__ == '__main__':` smoke-test block at the bottom (the existing one accepts a PDF path on the CLI) — used in Phase 5 validation.

**2.2 `config/config.yaml`** — update `processing.ocr`:

```yaml
processing:
  ocr:
    confidence_threshold: 0.7
    enabled: false
    language: en
    provider: gemini                              # NEW — informational
    model: gemini-2.5-flash                       # NEW — file-editable now
    prompt_file: config/prompts/ocr_default.txt   # RENAMED from claude_prompt_file
```

**2.3 Rename the prompt file**

```bash
git mv config/prompts/claude_ocr_default.txt config/prompts/ocr_default.txt
```

Contents stay identical. The prompt's checkbox/arrow/heading rules are provider-agnostic.

### Phase 3 — Wire it in

**3.1 `src/processors/notebook_text_extractor.py`**

```python
# line 27 — change
from .gemini_vision_ocr import GeminiVisionOCREngine, OCRResult

# lines 369–372 — change class name only
self.ocr_engine = GeminiVisionOCREngine(
    db_connection=db_connection,
    confidence_threshold=confidence_threshold,
)
```

Logging string at line 368 (`"Initializing Claude Vision OCR..."`) should be updated to `"Initializing Gemini Vision OCR..."` so logs aren't misleading.

**3.2 Run smoke test** (see Phase 5 step 1) before proceeding.

### Phase 4 — Remove old code

Only proceed after Phase 3 smoke test passes.

**4.1** Delete `src/processors/claude_vision_ocr.py`.

**4.2** Confirm `anthropic` is gone from `pyproject.toml` and `poetry.lock`.

**4.3** Drop `pdf2image` from `pyproject.toml` if not used elsewhere:
```bash
grep -rn "pdf2image\|convert_from_path" src/
```

**4.4** Remove Anthropic methods from `src/utils/api_keys.py`:
- `get_anthropic_api_key`, `store_anthropic_api_key`, `remove_anthropic_api_key`
- The module-level `get_anthropic_api_key()` convenience function
- Any references in `_api_key_manager` initialization

**4.5** Clean up `src/cli/main.py`:
- Remove the `sk-ant-` validation branch entirely (or keep behind `--service anthropic` if you want defensive compatibility — recommended to delete).

**4.6** `tests/manual/test_enhanced_extraction.py` — sweep for `claude_vision_ocr`, `ClaudeVisionOCREngine`, `anthropic`, update or remove obsolete tests.

**4.7** Optionally: manually remove the stored Anthropic key from macOS Keychain via Keychain Access app (search `anthropic-api-key`). Not required — orphaned entries are harmless.

### Phase 5 — Validation

**5.1 Standalone smoke test** — before doing anything in the watcher:

```bash
poetry run python -m src.processors.gemini_vision_ocr /path/to/a/known-page.pdf
```

Pick a PDF from a temp dir during a previous OCR run, or render one fresh. Expected: clean Markdown transcription printed to stdout. Validate:

- Layout preservation (line breaks, indents)
- Checkbox detection (`- [ ]` / `- [x]`)
- Arrow handling (`→`, `↳`)
- Date headers
- No ` ``` ` code fence wrappers leaking through

**5.2 End-to-end via watcher**

1. Pick a notebook that's already fully OCR'd (e.g. Christian).
2. In the DB, delete one page's row:
   ```sql
   DELETE FROM notebook_text_extractions
   WHERE notebook_uuid = '<uuid>' AND page_number = <N>;
   ```
3. Touch the notebook's `.metadata` file (see `docs/watching-system.md` for the directory).
4. Tail the log: expect `Processing PDF with Gemini Vision OCR` and a successful insert.
5. Compare the new text against what was there before (eyeball the diff for major regressions).

**5.3 Failure modes to confirm**

- **No API key:** `is_available()` returns False, watcher logs the warning and doesn't crash.
- **Quota exceeded:** Gemini returns HTTP 429 with `RESOURCE_EXHAUSTED`. The engine should catch, log, and return `ProcessingResult(success=False, ...)` — the watcher must not crash. Test by temporarily setting an obviously wrong API key.
- **Multi-page PDF:** the engine treats the whole document as one page (returns one `OCRResult` with `page_number=1`). In production all PDFs passed in are single-page, but log a warning if you see otherwise.

---

## Risks and open decisions

### R1 — SSL bypass in corporate environments

The current Anthropic client uses `httpx.Client(verify=False)` for corporate networks where the SSL chain breaks (`claude_vision_ocr.py:240`). The `google-genai` SDK uses gRPC + HTTPS internally and doesn't expose `verify=False` cleanly.

**Mitigations to try if the office network rejects calls:**

1. Force REST transport: `genai.Client(api_key=..., http_options={"api_version": "v1"})`
2. Set `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` to the corporate CA bundle path.
3. As a last resort, set `GRPC_VERBOSITY=DEBUG` and inspect what's failing.

**Test this on the affected network before deleting `claude_vision_ocr.py`.** If it can't be made to work, abort Phase 4 and keep the Claude engine as a fallback (this becomes Option B — provider abstraction — instead of Option A).

### R2 — Confidence scores

Gemini doesn't return per-page OCR confidence. We use the placeholder `self.confidence_threshold` (currently 0.7 / 0.8 depending on init). The DB column gets a constant, and any downstream filtering on confidence becomes effectively a yes/no based on that constant. This matches what Claude was doing — same placeholder convention, no behavioral change.

### R3 — Cost/latency profile

Gemini 2.5 Flash is fast (<1s per page typical) and roughly 10–20× cheaper per page than Haiku 4.5 for vision OCR at our input sizes. No rate limiter needed for our volume.

### R4 — API key prefix validation

Gemini keys start with `AIza` (39 chars total). Update the validation in `cli/main.py` accordingly — or drop the prefix check entirely and let the first API call fail naturally with a clearer error.

### R5 — Future provider abstraction

If we ever want to support both providers, the right time is when there's a real second consumer. Don't pre-build it now. The interface this plan establishes (`OCRResult`, `ProcessingResult`, `process_file(pdf) -> ProcessingResult`) is already factory-friendly — a future `OCREngine` Protocol can be added with `Claude*` and `Gemini*` implementations behind a config switch in <50 LoC.

---

## Touch list (final diff summary)

```
modified:   pyproject.toml
modified:   config/config.yaml
modified:   src/cli/main.py
modified:   src/utils/api_keys.py
modified:   src/processors/notebook_text_extractor.py    (2 lines)
modified:   tests/manual/test_enhanced_extraction.py
new file:   src/processors/gemini_vision_ocr.py          (~180 lines)
deleted:    src/processors/claude_vision_ocr.py          (-617 lines)
renamed:    config/prompts/claude_ocr_default.txt -> config/prompts/ocr_default.txt
```

**Net change:** approximately -440 lines, one fewer SDK dependency (`anthropic`), one likely-removable dependency (`pdf2image`), both prompt and model become file-editable from `config/config.yaml`.

---

## Pre-flight checklist (run before starting on the target machine)

- [ ] Confirm you have a Google AI API key (`AIza...`). Get one at https://aistudio.google.com/app/apikey if not.
- [ ] Confirm `poetry run python -m src.cli.main watch` is not currently running (stop the process if so).
- [ ] Take a database backup: `cp data/remarkable_pipeline.db data/remarkable_pipeline.db.pre-gemini-migration`
- [ ] On a corporate network: test SSL connectivity to `generativelanguage.googleapis.com` with a quick `curl -v https://generativelanguage.googleapis.com/v1/models` before committing to Phase 4.
- [ ] Read `rmirror-cloud/backend/app/core/ocr_service.py` end-to-end — it is the reference implementation.

## Post-implementation checklist

- [ ] All five phases committed as separate commits.
- [ ] `poetry run pytest` passes.
- [ ] Smoke test from Phase 5.1 produced clean Markdown output.
- [ ] One re-OCR'd page from Phase 5.2 looks at least as good as the Claude output.
- [ ] Watcher runs for ≥10 minutes without crashing on a fresh notebook touch.
- [ ] `git log --oneline` shows the migration as a tidy series of commits ready for review.
