# Vision Foundation

This package provides the Phase 1 unified vision toolkit for FIMS.

## Engines

- `ocr.py`: RapidOCR first, with pytesseract fallback when `tesseract` is installed.
- `codes.py`: zxing-cpp and pyzbar for barcode/QR decoding, with OpenCV QR fallback.
- `vlm.py`: Ollama vision client for `qwen2.5vl:7b`, returning JSON-safe outputs.
- `bg.py`: rembg background removal with `birefnet-general` first, then `isnet-general-use`.
- `pdf.py`: PyMuPDF rasterization and text extraction.

## Pipeline

- `scripts.vision.pipeline.analyze_image(path, steps=("ocr","codes","vlm"))`
- `scripts.vision.pipeline.analyze_pdf_page(pdf, page, steps=...)`
- `python -m scripts.vision.cli analyze <path> [--steps ocr,codes,vlm] [--bg] [--json]`

## Phase 2 TODO

- Segmentation and subject extraction
- PDF page to per-product structure splitting
- Spatial-relativity grouping
- PC compute offload

