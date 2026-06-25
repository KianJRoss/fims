# Build: FIMS unified vision service — FOUNDATION (Phase 1)

Build a reusable, composable vision toolkit under `scripts/vision/` that every other
FIMS task (photo audit, photo sourcing, metadata extraction, catalog PDF ingestion)
will call. This phase builds the FOUNDATION only — the engines + a common result
schema + an orchestrator + a CLI. Segmentation/subject-extraction and PDF-page product
splitting are PHASE 2 — **do NOT build those yet** (leave clear TODO stubs).

## HARD GUARDRAILS (do not violate)
- **READ-ONLY w.r.t. the database and existing media.** This service ANALYZES images and
  returns data. It must NEVER connect to Postgres, NEVER emit INSERT/UPDATE/DELETE, NEVER
  modify `products.image_path`, and NEVER overwrite anything under `media/product_images/`.
  Any files it writes go ONLY under `media/vision_out/`.
- **Stay in scope:** create only files under `scripts/vision/` plus
  `scripts/requirements-vision.txt`. Do not modify other repo files.
- **Build + self-test module by module, in the order below.** After each engine, run its
  self-test and confirm it works before moving on. Paste self-test output at the end.
- **Don't explore the repo broadly.** The only existing file you need to read is
  `scripts/extract_catalog.py` (for the RapidOCR+pytesseract usage pattern).

## Environment / conventions
- Local Ollama at `http://localhost:11434` (env `OLLAMA_HOST`). Vision model:
  `qwen2.5vl:7b` (env `VISION_MODEL`); it is being downloaded separately — if it is not
  yet available, the VLM self-test should SKIP gracefully (print "model not ready"),
  not crash.
- Add deps to `scripts/requirements-vision.txt` and `pip install` them. Expected:
  `rembg`, `onnxruntime`, `pymupdf`, `pyzbar`, `zxing-cpp`, `pillow`, `numpy`.
  (`rapidocr_onnxruntime`, `opencv-python` are already installed.)
- Python 3.13, Windows. Keep imports lazy (import heavy libs inside functions) so importing
  the package is cheap and a missing optional engine degrades gracefully.

## Modules to build (in this order)

### 1. `scripts/vision/result.py` — common schema
Plain dataclasses with `to_dict()`:
- `TextRegion(text: str, bbox: list[float], confidence: float|None)`  (bbox = [x1,y1,x2,y2])
- `Code(kind: str, data: str, bbox: list[float]|None)`  (kind e.g. "QRCODE","EAN13")
- `Subject(bbox: list[float], crop_path: str|None, label: str|None)`  (Phase 2 fills these)
- `Analysis(source: str, width: int, height: int, texts: list[TextRegion],
   codes: list[Code], subjects: list[Subject], vlm: dict, meta: dict)` with
  `to_dict()` and `to_json()`.

### 2. `scripts/vision/engines/ocr.py`
`read_text(image) -> list[TextRegion]`. RapidOCR primary (model the call after
`scripts/extract_catalog.py`: `from rapidocr_onnxruntime import RapidOCR`), pytesseract
fallback ONLY if `shutil.which("tesseract")`. `image` may be a path or a numpy array.
Self-test: run on `media/product_images/1004074.jpg`, assert it finds "BANANA" somewhere.

### 3. `scripts/vision/engines/codes.py`
`read_codes(image) -> list[Code]`. Try `zxing-cpp` and `pyzbar`; merge/dedupe results;
fall back to OpenCV `cv2.QRCodeDetector` for QR. Self-test: generate a QR in-memory
(e.g. via `zxing-cpp` writer or a tiny hand-built one) OR skip generation and just assert
the function runs and returns a list on a product image. Must not crash if a backend lib
is missing.

### 4. `scripts/vision/engines/vlm.py`
Thin Ollama client. `ask_json(image_path, prompt) -> dict` (POST /api/generate with
`format:"json"`, base64 image, robust JSON parse incl. regex fallback). Helpers:
`read_label(image_path) -> str` and `describe(image_path) -> dict`. Model + host from env.
Self-test: if `VISION_MODEL` is pulled, run `read_label` on the banana image and print it;
else print "VLM model not ready, skipping" and return cleanly.

### 5. `scripts/vision/engines/bg.py`
`remove_background(image_path, out_path=None, model=None) -> str` using `rembg`.
Default model `birefnet-general` (env `BG_MODEL`); on failure or if too slow, fall back to
`isnet-general-use`. Writes an RGBA PNG under `media/vision_out/`. Also expose
`alpha_mask(image_path) -> np.ndarray`. Self-test: run on the banana image, assert the
output PNG exists and has an alpha channel. (First run downloads the model — that's fine.)

### 6. `scripts/vision/engines/pdf.py`
PyMuPDF (`fitz`). `rasterize(pdf_path, page, dpi=200) -> PIL.Image` and
`page_count(pdf_path) -> int` and `extract_text(pdf_path, page) -> str`. (Splitting a page
into per-product subjects is PHASE 2 — leave a `# TODO Phase 2` stub.)

### 7. `scripts/vision/pipeline.py`
`analyze_image(path, steps=("ocr","codes","vlm")) -> Analysis`. Runs the requested engines,
loads the image once, fills an `Analysis`. `analyze_pdf_page(pdf, page, steps=...)` rasterizes
then calls analyze_image. Each step wrapped in try/except so one failing engine doesn't sink
the whole analysis (record the error in `meta`).

### 8. `scripts/vision/cli.py`
`python -m scripts.vision.cli analyze <path> [--steps ocr,codes,vlm] [--bg] [--json]`.
Prints the unified Analysis as JSON. `--bg` also runs background removal.

### 9. `scripts/vision/README.md`
Short: what each engine is, the chosen best-in-class tool + why, how to call the pipeline,
and the Phase-2 TODO list (segment/subject-extraction, PDF→per-product structure,
spatial-relativity grouping, PC compute offload).

## Deliverables
All of the above, runnable + idempotent, NO DB writes, outputs only under `media/vision_out/`.
Run every self-test, paste the output, then STOP and summarize. Do NOT start Phase 2.
