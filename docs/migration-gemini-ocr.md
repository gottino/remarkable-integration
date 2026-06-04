# Migration Plan: Replace Claude Vision OCR with Google Gemini 2.5 Flash

**Status:** Planned — not yet executed
**Author:** drafted 2026-05-27; reworked & verified against codebase 2026-06-04
**Estimated effort:** half a day end-to-end including validation
**Target machine:** any dev machine with the repo checked out

> **Verification note (2026-06-04):** Every file/line reference, the integration
> contract, the DB schema, and the dependency graph below were checked against
> the current `main` (`7babd23`). Corrections from the original draft are marked
> inline with **[verified]** / **[corrected]**.

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
| `src/processors/claude_vision_ocr.py` | 617 **[verified]** | Whole engine: rate limiter, PDF→image, Claude API call, prompt loading, DB write |
| `src/processors/notebook_text_extractor.py` | 4 touchpoints (lines 27, 369, 375/391, 901) **[verified]** | Only production caller — imports `ClaudeVisionOCREngine, OCRResult`, calls `is_available()` and `process_file()` |
| `src/utils/api_keys.py` | generic manager **[corrected]** | **Not Anthropic-specific.** Exposes generic `get_api_key(service)` / `store_api_key(service)` / `remove`, plus thin per-service convenience wrappers (`get_anthropic_api_key`, …) and module-level shims. A `list_stored_keys()` method walks a **hardcoded** service dict. |
| `src/cli/main.py` (lines 190–282) **[verified]** | 4 commands | `config api-key set/get/remove/list`, currently hardcoded to Anthropic (`sk-ant-` check at line 222, `store_anthropic_api_key` at 228, etc.) |
| `config/config.yaml` (line 46) | 1 key | `processing.ocr.claude_prompt_file` **[verified]** |
| `config/prompts/claude_ocr_default.txt` | — | File-based prompt; already nearly provider-agnostic |
| `pyproject.toml` (lines 26, 36, 38) | 3 deps **[corrected]** | `anthropic = "^0.64.0"` (38), `pdf2image = "^1.17.0"` (36), `pillow = "^10.0.0"` (26) — see dependency note below |

**[corrected] There are NO automated tests of the OCR engine.** `tests/manual/test_enhanced_extraction.py` (listed in the original draft) references the *highlight* extractors, not OCR — a grep of `tests/` for `claude_vision_ocr` / `ClaudeVisionOCREngine` / `anthropic` returns nothing. `ClaudeVisionOCREngine` is referenced in exactly **two** files: the engine itself and `notebook_text_extractor.py`. **Consequence:** `poetry run pytest` will *not* catch an OCR regression. The Phase 5 manual smoke test is the only safety net — treat it as mandatory, not optional.

### Dependency note (verified across `src/`)

`from PIL import Image`, `import numpy as np`, and `pdf2image.convert_from_path` are used **only** inside `claude_vision_ocr.py` — no other module in `src/` imports any of them. Therefore, once the Claude engine is deleted in Phase 4, **all three** of `pdf2image`, `pillow`, and `numpy` become removable (the original draft only flagged `pdf2image` and incorrectly guessed `pillow` was used by the SVG/PDF pipeline). Still grep `tests/` and any scripts before the final removal, but `src/` is clean.

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
- They log token usage via `response.usage_metadata.prompt_token_count` / `.candidates_token_count`. Optional but cheap to keep for cost tracking — include it in the new engine's success log line.

### Two database tables — important, was not in the original draft **[corrected]**

There are two distinct tables, and the OCR engine only writes one of them:

1. **`ocr_results`** — written by the engine's `_store_ocr_results()` (`DELETE`+`INSERT` keyed on `source_file`). **This table is never read anywhere** — a repo-wide grep finds only the engine's own write. It is effectively **dead/write-only code.**
2. **`notebook_text_extractions`** — the table whose text is actually consumed downstream (sync, change detection, page-level sync). It is written by **`notebook_text_extractor.py`**, *not* by the OCR engine. The extractor takes the `OCRResult` objects returned from `process_file()` and persists them here itself. Schema (verified, `database.py:227`) has columns `notebook_uuid, notebook_name, page_uuid, page_number, text, confidence, …`.

**Implications for the new engine:**

- The Gemini engine does **not** need to touch `notebook_text_extractions` — that path is unchanged and lives in the (untouched) extractor. The contract is purely "return correct `OCRResult` objects."
- Because nothing reads `ocr_results`, you have a choice for the new engine:
  - **(simpler, recommended)** Drop `_store_ocr_results` and the `db_connection` write path entirely — the engine just returns `OCRResult`s. Fewer lines, removes dead code. The `db_connection` constructor param can stay (ignored) to preserve the call signature, or be dropped since the only caller passes it positionally-by-keyword (see contract below).
  - **(safest parity)** Copy `_store_ocr_results` verbatim to keep byte-for-byte behavior. Choose this only if you want zero behavioral delta for now.
- Phase 5.2's validation deletes from `notebook_text_extractions` (the right table — it has a `page_number` column, verified) to trigger re-extraction. Deleting from `ocr_results` would do nothing.

---

## Implementation phases

Each phase is a clean commit point. Run `poetry run pytest` and a quick manual OCR call between phases.

### Phase 1 — Dependencies and API key management (no behavior change)

**1.1 `pyproject.toml`** — **[corrected: ADD only; do not remove anything yet]**

- **Add** `google-genai = "^1.0.0"` (verify latest stable version on PyPI; the reference impl uses `from google import genai`).
- **Do NOT remove `anthropic`, `pdf2image`, `pillow`, or `numpy` in this phase.** They are still imported by `claude_vision_ocr.py`, which the extractor keeps importing until Phase 3 and which is not deleted until Phase 4. Removing the Claude deps here would leave OCR broken across Phases 1–2, contradicting the "each phase is a clean, working commit" goal. All Claude-side dependency removal happens in **Phase 4**, mirroring how the Anthropic *key methods* are also kept until Phase 4.
- Run `poetry lock && poetry install` to pull in `google-genai`.

> Rationale for the reorder: the original draft removed `anthropic` here, but the
> import in `notebook_text_extractor.py:27` and the engine file both survive until
> Phases 3–4. `claude_vision_ocr.py` guards its `import anthropic` in a
> `try/except ImportError` (lines 34–40), so a removed dep wouldn't crash on
> import — but `is_available()` would silently return `False` and OCR would
> stop working with no error until Gemini is wired in. Keep Claude fully
> functional until Gemini is proven in Phase 3.

**1.2 `src/utils/api_keys.py`** — **[corrected: it's a generic manager, less work than the draft implied]**

The manager already does the heavy lifting generically via `get_api_key(service)` / `store_api_key(service, …)` / `remove`. The keychain username is derived as `f"{service}_api_key"` (see `_get_from_keychain`), so the *only* thing that defines a "service" is the string you pass.

**Pick one canonical service string and use it everywhere.** This plan uses **`google`** (so the keychain entry becomes `google_api_key`, and the `google-genai` SDK also natively reads the `GOOGLE_API_KEY` env var as a free fallback). The original draft mixed `gemini`, `google-ai-api-key`, and `get_google_ai_api_key` — don't; inconsistency causes silent keychain misses.

Concretely:

- Add convenience wrappers mirroring the existing Anthropic ones (each is a one-liner over the generic methods):
  - `get_google_api_key(self) -> Optional[str]` → `return self.get_api_key('google', interactive_setup=False)`
  - `store_google_api_key(self, api_key, method='auto') -> bool` → `return self.store_api_key('google', api_key, method)`
  - `remove_google_api_key(self) -> bool` → mirror `remove_anthropic_api_key`
- Add a **module-level** `def get_google_api_key()` at the bottom, mirroring `get_anthropic_api_key()` (line 449). This is the symbol the new engine imports.
- **[corrected] Add `'google'` to the hardcoded `services` dict in `list_stored_keys()`** (around line 186): `'google': ['GOOGLE_API_KEY', 'GEMINI_API_KEY']`. The original draft claimed `config api-key list` "already works since it walks the keychain" — it does **not**; it iterates a hardcoded `{anthropic, readwise, notion}` dict, so without this edit a stored Google key never shows up in `list`.
- **Keep the Anthropic methods for now** — they get deleted in Phase 4 once everything works.

**1.3 `src/cli/main.py` (lines 190–282)** **[verified line range]**

Generalize the `config api-key` command group to take a service. **Use the same canonical service string as 1.2 (`google`).**

```bash
poetry run python -m src.cli.main config api-key set --service google
poetry run python -m src.cli.main config api-key set --service anthropic   # still works during transition
```

- Add `--service` (default `google`) to `set/get/remove`. Today these call `store_anthropic_api_key` / `get_anthropic_api_key` / `remove_anthropic_api_key` directly (lines 228, 241, 263) — dispatch on `--service` to the matching generic/convenience method instead.
- Make the `sk-ant-` prefix check (line 222) conditional on `--service`. Google keys start with `AIza`. Simplest: only warn for `anthropic`, skip the prefix check for `google` (or drop it entirely and let the first API call fail with a clearer error — see R4).
- `list` (line 269) needs no change here **once `'google'` is added to the `services` dict in 1.2** — it just prints whatever `list_stored_keys()` returns.

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
from ..utils.api_keys import get_google_api_key   # canonical name from Phase 1.2
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
            api_key = api_key or get_google_api_key()
            if api_key:
                self.client = genai.Client(api_key=api_key)
                logger.info(f"Gemini Vision OCR initialized with model: {self.model}")
            else:
                logger.error("No Google API key found. Use 'config api-key set --service google' to configure.")

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

- `_load_prompt` can be copied verbatim from `claude_vision_ocr.py` (it has no Claude-specific logic) — just swap the config key from `processing.ocr.claude_prompt_file` to `processing.ocr.prompt_file`.
- **`_store_ocr_results` / `db_connection` — your call (see "Two database tables" above).** Recommended: **omit it** — nothing reads the `ocr_results` table, so the engine only needs to return correct `OCRResult`s; the consumed text is written by the (untouched) extractor into `notebook_text_extractions`. The skeleton above keeps the `db_connection` param + write path for parity; delete it if you take the simpler route. If you keep it, copy `_store_ocr_results` verbatim (same `ocr_results` schema, same INSERT).
- The `_default_prompt()` fallback string in `claude_vision_ocr.py` should also be copied — the prompt content is provider-agnostic. (The reference impl's `OCR_PROMPT` is a good cross-check; the file-based `config/prompts/ocr_default.txt` is the source of truth at runtime.)
- Keep the `if __name__ == '__main__':` smoke-test block at the bottom (the existing one accepts a PDF path on the CLI) — used in Phase 5 validation.
- `confidence` has no real meaning for Gemini (no per-page score) — set it to `self.confidence_threshold` exactly as Claude did, so the `notebook_text_extractions.confidence` column keeps the same placeholder convention (see R2).

**2.2 `config/config.yaml`** — update `processing.ocr`:

```yaml
processing:
  ocr:
    confidence_threshold: 0.7
    enabled: false                                # NOTE: dead flag — grep shows nothing reads
                                                  # processing.ocr.enabled. OCR runs regardless.
                                                  # Leave as-is; don't expect flipping it to gate anything.
    language: en
    provider: gemini                              # NEW — informational
    model: gemini-2.5-flash                       # NEW — file-editable now (engine reads
                                                  # processing.ocr.model with this default)
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

**4.2 Remove the now-orphaned dependencies from `pyproject.toml`** (deferred here from Phase 1.1). After deleting the engine, these have no remaining importer in `src/`:
- `anthropic = "^0.64.0"`
- `pdf2image = "^1.17.0"`
- `pillow = "^10.0.0"`
- `numpy` (if it's a direct dep — confirm it's not pulled in transitively/used elsewhere first)

Re-verify before removing, then re-lock:
```bash
grep -rn "import anthropic\|from anthropic" src/
grep -rn "pdf2image\|convert_from_path" src/
grep -rn "from PIL\|import PIL" src/
grep -rn "import numpy\|from numpy" src/
# all four should return nothing but the (now-deleted) engine; also glance at tests/ and scripts/
poetry lock && poetry install
```

**4.3** Remove Anthropic helpers from `src/utils/api_keys.py` (the generic core stays):
- `get_anthropic_api_key`, `store_anthropic_api_key`, `remove_anthropic_api_key` (convenience wrappers)
- The module-level `get_anthropic_api_key()` shim (line 449)
- The `'anthropic'` entry in the `list_stored_keys()` services dict
- **Do not touch** `get_api_key` / `store_api_key` / `_get_from_keychain` etc. — those are generic and still used by readwise/notion/google.

**4.4** Clean up `src/cli/main.py`:
- Remove the `sk-ant-` validation branch (line 222), or keep it behind `--service anthropic` for defensive compatibility — recommended to delete since the Anthropic methods are gone.

**4.5 Tests — [corrected]:** there is **nothing to sweep.** No test references the OCR engine (`tests/manual/test_enhanced_extraction.py` is about highlight extraction, not OCR). Just confirm `grep -rn "claude_vision_ocr\|ClaudeVisionOCREngine" tests/ scripts/` is empty. The original draft's step to edit that test file was based on a misidentification — skip it.

**4.6** Optionally: manually remove the stored Anthropic key from macOS Keychain via Keychain Access app (search `anthropic_api_key`). Not required — orphaned entries are harmless.

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
2. In the DB, delete one page's row — **`notebook_text_extractions` is the correct table** (it has a `page_number` column, verified; `ocr_results` is the dead one and deleting from it does nothing):
   ```sql
   DELETE FROM notebook_text_extractions
   WHERE notebook_uuid = '<uuid>' AND page_number = <N>;
   ```
3. Touch the notebook's `.metadata` file (see `docs/watching-system.md` for the directory).
4. Tail the log: expect the line `Processing PDF with Gemini Vision OCR` (make sure you updated the log string in Phase 3.1 — otherwise it'll still say "Claude") and a successful re-insert of the deleted row.
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
modified:   pyproject.toml                               (Phase 1: +google-genai; Phase 4: -anthropic -pdf2image -pillow -numpy)
modified:   config/config.yaml                            (provider/model keys, prompt_file rename)
modified:   src/cli/main.py                               (--service dispatch, conditional prefix check)
modified:   src/utils/api_keys.py                         (+google wrappers & module shim, +google in list dict; -anthropic helpers in Phase 4)
modified:   src/processors/notebook_text_extractor.py     (2 lines: import + class name; +1 log string)
new file:   src/processors/gemini_vision_ocr.py           (~150–180 lines, depending on whether _store_ocr_results is kept)
deleted:    src/processors/claude_vision_ocr.py           (-617 lines)
renamed:    config/prompts/claude_ocr_default.txt -> config/prompts/ocr_default.txt
```

**[corrected] `tests/manual/test_enhanced_extraction.py` is NOT in this diff** — it doesn't reference the OCR engine.

**Net change:** approximately **-440 to -480 lines**, **three** fewer dependencies (`anthropic`, `pdf2image`, `pillow`, plus likely `numpy` — all verified used only by the deleted engine), and both prompt and model become file-editable from `config/config.yaml`.

---

## Pre-flight checklist (run before starting on the target machine)

- [ ] Confirm you have a Google API key (`AIza...`). Get one at https://aistudio.google.com/app/apikey if not.
- [ ] Decide and stick to the canonical service string **`google`** (keychain `google_api_key`, env `GOOGLE_API_KEY`) across `api_keys.py`, `cli/main.py`, and the engine.
- [ ] Confirm `poetry run python -m src.cli.main watch` is not currently running (stop the process if so).
- [ ] Take a database backup: `cp data/remarkable_pipeline.db data/remarkable_pipeline.db.pre-gemini-migration`
- [ ] On a corporate network: test SSL connectivity to `generativelanguage.googleapis.com` with a quick `curl -v https://generativelanguage.googleapis.com/v1/models` before committing to Phase 4.
- [ ] Read the reference implementation end-to-end — **verified present** at `../rmirror-cloud/backend/app/core/ocr_service.py` (sibling of this repo, ~178 lines). Its `_call_vision_api` is the exact call shape to copy.

## Post-implementation checklist

- [ ] All five phases committed as separate commits.
- [ ] `poetry run pytest` passes.
- [ ] Smoke test from Phase 5.1 produced clean Markdown output.
- [ ] One re-OCR'd page from Phase 5.2 looks at least as good as the Claude output.
- [ ] Watcher runs for ≥10 minutes without crashing on a fresh notebook touch.
- [ ] `git log --oneline` shows the migration as a tidy series of commits ready for review.
