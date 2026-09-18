"""Extract a small text sample from every downloaded PDF.

Only the first, second, and last pages are inspected. pdfplumber is used for
native text extraction; RapidOCR is loaded lazily and used only when a page
has no native text. Existing output files are skipped unless ``--force`` is
provided.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import time
from pathlib import Path

import pdfplumber
from PIL import Image
from tqdm import tqdm


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PIPELINE_ROOT / "01_downloads"
DEFAULT_OUTPUT = PIPELINE_ROOT / "02_light_extraction" / "output"
PAGE_MARKER = "--- Page {page} ---"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("extract_light_pages")


def selected_pages(page_count: int) -> list[int]:
	"""Return zero-based first, second, and last page indexes without duplicates."""
	if page_count <= 0:
		return []
	candidates = [0, 1, page_count - 1]
	return list(dict.fromkeys(page for page in candidates if page < page_count))


def native_page_text(pdf: pdfplumber.pdf.PDF, page_number: int) -> str | None:
	try:
		text = pdf.pages[page_number].extract_text() or ""
		return text.strip() or None
	except Exception as exc:
		log.debug("pdfplumber failed on page %d: %s", page_number + 1, exc)
		return None


class RapidOcrFallback:
	"""Lazy RapidOCR wrapper so text-only PDFs do not initialize OCR models."""

	def __init__(self, dpi: int) -> None:
		self.dpi = dpi
		self._engine = None
		self._pymupdf = None

	def _load(self) -> None:
		if self._engine is not None:
			return
		import numpy as np
		import pymupdf
		from rapidocr import EngineType, RapidOCR

		self._pymupdf = pymupdf
		params = {
			"Det.engine_type": EngineType.ONNXRUNTIME,
			"Cls.engine_type": EngineType.ONNXRUNTIME,
			"Rec.engine_type": EngineType.ONNXRUNTIME,
		}
		self._engine = RapidOCR(params=params)
		self._numpy = np

	def extract(self, pdf_path: Path, page_number: int) -> str | None:
		self._load()
		try:
			document = self._pymupdf.open(str(pdf_path))
			try:
				pixmap = document[page_number].get_pixmap(dpi=self.dpi)
				image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
				image_array = self._numpy.asarray(image)[:, :, ::-1]
				result = self._engine(image_array)
				texts = getattr(result, "txts", None)
				return "\n".join(texts).strip() if texts else None
			finally:
				document.close()
		except Exception as exc:
			log.warning("RapidOCR failed for %s page %d: %s", pdf_path.name, page_number + 1, exc)
			return None


def process_pdf(pdf_path: Path, output_path: Path, ocr: RapidOcrFallback) -> dict:
	started = time.perf_counter()
	page_results = []
	try:
		with pdfplumber.open(pdf_path) as pdf:
			pages = selected_pages(len(pdf.pages))
			for page_number in pages:
				text = native_page_text(pdf, page_number)
				method = "PDFPLUMBER"
				if not text:
					text = ocr.extract(pdf_path, page_number)
					method = "RAPIDOCR" if text else "FAILED"
				if text:
					page_results.append(f"{PAGE_MARKER.format(page=page_number + 1)} [{method}]\n{text}")

		if not page_results:
			return {"status": "FAILED", "pages": len(pages), "error": "No text extracted"}

		output_path.parent.mkdir(parents=True, exist_ok=True)
		output_path.write_text("\n\n".join(page_results) + "\n", encoding="utf-8")
		return {
			"status": "COMPLETE",
			"pages": len(pages),
			"pages_with_text": len(page_results),
			"seconds": round(time.perf_counter() - started, 3),
			"error": None,
		}
	except Exception as exc:
		return {"status": "FAILED", "pages": 0, "error": str(exc)}


def main() -> int:
	parser = argparse.ArgumentParser(description="Extract first, second, and last pages from PDFs")
	parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="PDF input directory")
	parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Text output directory")
	parser.add_argument("--sources", nargs="+", help="Only process these source subfolders")
	parser.add_argument("--limit", type=int, help="Process at most this many PDFs")
	parser.add_argument("--dpi", type=int, default=250, help="Rendering DPI for RapidOCR fallback")
	parser.add_argument("--force", action="store_true", help="Replace existing text outputs")
	args = parser.parse_args()

	if not args.input.exists():
		parser.error(f"Input directory does not exist: {args.input}")
	if args.limit is not None and args.limit < 1:
		parser.error("--limit must be at least 1")

	pdf_files = sorted(args.input.rglob("*.pdf"))
	if args.sources:
		allowed = set(args.sources)
		pdf_files = [path for path in pdf_files if path.relative_to(args.input).parts[0] in allowed]
	if args.limit:
		pdf_files = pdf_files[:args.limit]

	log.info("Input: %s", args.input)
	log.info("Output: %s", args.output)
	log.info("PDFs selected: %d", len(pdf_files))

	ocr = RapidOcrFallback(args.dpi)
	manifest = []
	for pdf_path in tqdm(pdf_files, desc="Light extraction", unit="pdf"):
		relative = pdf_path.relative_to(args.input)
		output_path = (args.output / relative).with_suffix(".txt")
		if output_path.exists() and not args.force:
			manifest.append({"file": str(relative), "status": "SKIPPED_EXISTING"})
			continue
		result = process_pdf(pdf_path, output_path, ocr)
		manifest.append({"file": str(relative), **result})

	args.output.mkdir(parents=True, exist_ok=True)
	(args.output / "_manifest.json").write_text(json.dumps({
		"input": str(args.input),
		"output": str(args.output),
		"page_policy": "first, second, last",
		"records": manifest,
	}, indent=2), encoding="utf-8")

	complete = sum(row["status"] == "COMPLETE" for row in manifest)
	failed = sum(row["status"] == "FAILED" for row in manifest)
	skipped = sum(row["status"] == "SKIPPED_EXISTING" for row in manifest)
	log.info("Complete: %d | Failed: %d | Skipped existing: %d", complete, failed, skipped)
	return 1 if failed else 0


if __name__ == "__main__":
	raise SystemExit(main())
