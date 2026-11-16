"""RapidOCR backend and image-to-extraction-item conversion."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from typing import Any, Callable

import numpy as np
import pymupdf

from idp.stages.extractor.geometry import normalize


@dataclass(frozen=True)
class OcrLine:
	box: tuple[tuple[float, float], ...]
	text: str
	score: float


OcrBackend = Callable[[np.ndarray], Any]

@dataclass(frozen=True)
class Rendered:
    pix: pymupdf.Pixmap
    image: np.ndarray
    dpi: int


def _render(page: pymupdf.Page, dpi: int,
            region: tuple[float, float, float, float] | None,
            max_px: int | None) -> Rendered:
    """Render in visible page space; optionally cap the longest side in pixels."""
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    if max_px is not None and max_px <= 0:
        raise ValueError("max_px must be positive")
    if region is None:
        clip = page.rect
    else:
        if len(region) != 4 or not all(math.isfinite(value) for value in region):
            raise ValueError(f"OCR region must contain four finite coordinates: {region!r}")
        clip = pymupdf.Rect(region) & page.rect
    if clip.is_empty or clip.width <= 0 or clip.height <= 0:
        raise ValueError(f"OCR region is outside the visible page: {region!r}")
    longest_pt = max(clip.width, clip.height)
    effective_dpi = dpi if max_px is None else min(dpi, max(1, int(max_px * 72 / longest_pt)))
    pix = page.get_pixmap(dpi=effective_dpi, clip=clip, colorspace=pymupdf.csRGB, alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return Rendered(pix=pix, image=image[:, :, :3].copy(), dpi=effective_dpi)


def render(page: pymupdf.Page, dpi: int,
           region: tuple[float, float, float, float] | None = None) -> tuple[pymupdf.Pixmap, np.ndarray]:
    """Render a page or visible-space region to RGB, preserving the original tuple API."""
    rendered = _render(page, dpi, region, None)
    return rendered.pix, rendered.image


def render_bounded(page: pymupdf.Page, dpi: int,
                   region: tuple[float, float, float, float] | None = None,
                   max_px: int = 4000) -> Rendered:
    """Render with a maximum longest side and report the effective DPI for coordinate mapping."""
    return _render(page, dpi, region, max_px)


@lru_cache(maxsize=4)
def get_backend(threads: int = 2) -> OcrBackend:
	"""Create and reuse a CPU RapidOCR engine configured with a bounded thread count."""
	if threads < 1:
		raise ValueError("threads must be positive")
	from rapidocr import RapidOCR

	return RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": threads})


def _line_from_parts(box: Any, text: Any, score: Any) -> OcrLine | None:
	if text is None:
		return None
	text = str(text).strip()
	if not text:
		return None
	try:
		points = np.asarray(box, dtype=float).reshape(-1, 2)
		confidence = float(score)
	except (TypeError, ValueError):
		return None
	if len(points) < 4 or not np.isfinite(points).all() or not math.isfinite(confidence):
		return None
	if not 0.0 <= confidence <= 1.0:
		return None
	return OcrLine(tuple((float(x), float(y)) for x, y in points[:4]), text, confidence)


def _to_lines(result: Any) -> list[OcrLine]:
	"""Normalize RapidOCR's result object and legacy list-of-tuples output."""
	if result is None:
		return []

	if all(hasattr(result, name) for name in ("boxes", "txts", "scores")):
		boxes, texts, scores = result.boxes, result.txts, result.scores
		boxes = boxes if boxes is not None else []
		texts = texts if texts is not None else []
		scores = scores if scores is not None else []
		if not (len(boxes) == len(texts) == len(scores)):
			raise ValueError("RapidOCR boxes, texts, and scores have different lengths")
		return [line for parts in zip(boxes, texts, scores)
				if (line := _line_from_parts(*parts)) is not None]

	if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], (int, float)):
		result = result[0]
	if result is None:
		return []
	if isinstance(result, (list, tuple)) and len(result) >= 3:
		first = result[0]
		try:
			if np.asarray(first).shape == (4, 2) and isinstance(result[1], str):
				result = [result]
		except (TypeError, ValueError):
			pass

	lines = []
	for raw in result:
		if isinstance(raw, OcrLine):
			lines.append(raw)
		elif isinstance(raw, (list, tuple)) and len(raw) >= 3:
			line = _line_from_parts(raw[0], raw[1], raw[2])
			if line is not None:
				lines.append(line)
	return lines


def lines_to_items(page: pymupdf.Page, pix: pymupdf.Pixmap, dpi: int,
                   result: Any) -> list[Any]:
	"""Convert OCR pixel boxes into normalized visible-page extraction items."""
	from idp.schemas.extraction import Item, Source

	if dpi <= 0:
		raise ValueError("dpi must be positive")
	scale = dpi / 72
	origin_x, origin_y = pix.x / scale, pix.y / scale
	source = Source(engine="rapidocr", method="ocr")
	items = []
	for line in _to_lines(result):
		xs = [point[0] for point in line.box]
		ys = [point[1] for point in line.box]
		bbox = normalize(page, (
			origin_x + min(xs) / scale,
			origin_y + min(ys) / scale,
			origin_x + max(xs) / scale,
			origin_y + max(ys) / scale,
		))
		if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
			continue
		items.append(Item(item_id="", type="text_line", text=line.text, segments=[], bbox=bbox,
						  source=source, confidence=line.score))
	return items
