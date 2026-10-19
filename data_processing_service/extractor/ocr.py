"""OCR for scanned PDF pages: English RapidOCR models, orientation handling, reading order, and table
reconstruction from ruling lines.

This module only depends on third-party packages so the extractor Dockerfile can run it on its own
(`python ocr.py`) to download and bake the OCR models into the image.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

import numpy as np

try:  # pragma: no cover - optional dependency
    import cv2
    from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR
except Exception:  # pragma: no cover
    cv2 = None
    RapidOCR = None

OCR_DPI = int(os.getenv("OCR_DPI", "200"))
OCR_MAX_SIDE_LEN = int(os.getenv("OCR_MAX_SIDE_LEN", "3000"))
OCR_MODEL_DIR = os.getenv("OCR_MODEL_DIR") or None
# Fraction of detected text boxes that must be taller than wide before trying 90/270 degree rotations.
VERTICAL_BOX_RATIO = 0.6

_ENGINE = None


def ocr_available() -> bool:
    return RapidOCR is not None and cv2 is not None


def get_engine():
    """Create the OCR engine once per process.

    The recognition model must be English: RapidOCR's default Chinese model drops the spaces between
    English words ("GovernmentofIndia"), which breaks every downstream keyword and name match.
    """
    global _ENGINE
    if _ENGINE is None:
        if not ocr_available():
            raise RuntimeError("rapidocr and opencv are required for OCR")
        params = {
            "Global.max_side_len": OCR_MAX_SIDE_LEN,
            "Global.log_level": "warning",
            "Det.lang_type": LangDet.CH,  # detection model is language agnostic
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
            "Cls.ocr_version": OCRVersion.PPOCRV4,
            "Cls.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.EN,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
        }
        if OCR_MODEL_DIR:
            params["Global.model_root_dir"] = OCR_MODEL_DIR
        _ENGINE = RapidOCR(params=params)
    return _ENGINE


def _run(image: np.ndarray) -> list[dict[str, Any]]:
    result = get_engine()(image)
    boxes = result.boxes if result.boxes is not None else []
    lines = []
    for box, text, score in zip(boxes, result.txts or [], result.scores or []):
        if not str(text).strip():
            continue
        xs, ys = box[:, 0], box[:, 1]
        lines.append({
            "text": str(text).strip(),
            "bbox": [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())],
            "score": round(float(score), 4),
        })
    return lines


def _mostly_vertical(lines: list[dict[str, Any]]) -> bool:
    if len(lines) < 5:
        return False
    vertical = sum(1 for line in lines if (line["bbox"][3] - line["bbox"][1]) > 1.5 * (line["bbox"][2] - line["bbox"][0]))
    return vertical / len(lines) >= VERTICAL_BOX_RATIO


def _quality(lines: list[dict[str, Any]]) -> float:
    return sum(line["score"] * len(line["text"]) for line in lines)


def ocr_image(image: np.ndarray) -> tuple[np.ndarray, list[dict[str, Any]], int]:
    """OCR an RGB page image, rotating it when the text runs sideways.

    Returns the (possibly rotated) image, the recognized lines in that image's pixel coordinates, and
    the clockwise rotation applied in degrees.
    """
    lines = _run(image)
    if not _mostly_vertical(lines):
        return image, lines, 0
    best_image, best_lines, best_rotation = image, lines, 0
    for rotation, turns in ((90, 3), (270, 1)):  # np.rot90 rotates counter-clockwise
        rotated = np.ascontiguousarray(np.rot90(image, turns))
        candidate = _run(rotated)
        if _quality(candidate) > _quality(best_lines):
            best_image, best_lines, best_rotation = rotated, candidate, rotation
    return best_image, best_lines, best_rotation


def reading_order_text(lines: list[dict[str, Any]]) -> str:
    """Join OCR lines top-to-bottom, merging boxes that share a text line left-to-right.

    Boxes join a line only when they overlap it by half their height, so the slightly tilted lines of a
    skewed scan are not merged into one (which scrambled the reading order).
    """
    return "\n".join(
        " ".join(item["text"] for item in sorted(band, key=lambda item: item["bbox"][0]))
        for band in _bands(lines)
    )


def _positions(profile: np.ndarray, threshold: float, min_gap: int = 8) -> list[int]:
    hits = np.where(profile > threshold)[0]
    positions, start = [], None
    for index, value in enumerate(hits):
        start = value if start is None else start
        if index == len(hits) - 1 or hits[index + 1] - value > min_gap:
            positions.append(int((start + value) // 2))
            start = None
    return positions


def grid_lines(image: np.ndarray) -> tuple[list[int], list[int]]:
    """Find the y positions of horizontal rules and the x positions of vertical rules of a ruled table."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    height, width = binary.shape
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, width // 30), 1)))
    profile = horizontal.sum(axis=1) / 255
    ys = _positions(profile, profile.max() * 0.4) if profile.max() else []
    if len(ys) < 3:
        return ys, []
    # Vertical rules are searched only inside the table's vertical span, where faint lines still dominate.
    top, bottom = ys[0], ys[-1]
    band = binary[top:bottom + 1]
    vertical = cv2.morphologyEx(band, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, (bottom - top) // 8))))
    vertical = cv2.dilate(vertical, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)))
    xs = _positions(vertical.sum(axis=0) / 255, (bottom - top) * 0.6)
    return ys, xs


def table_from_grid(image: np.ndarray, lines: list[dict[str, Any]]) -> list[list[str]]:
    """Place OCR lines into the cells of a ruled table; returns rows of cell strings ([] when no grid)."""
    ys, xs = grid_lines(image)
    if len(ys) < 3 or len(xs) < 3:
        return []
    grid: list[list[list[tuple[float, float, str]]]] = [[[] for _ in range(len(xs) - 1)] for _ in range(len(ys) - 1)]
    for line in lines:
        x0, y0, x1, y1 = line["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        row = next((i for i in range(len(ys) - 1) if ys[i] <= cy < ys[i + 1]), None)
        col = next((j for j in range(len(xs) - 1) if xs[j] <= cx < xs[j + 1]), None)
        if row is not None and col is not None:
            grid[row][col].append((cy, cx, line["text"]))
    rows = [["\n".join(text for _, _, text in sorted(cell)) for cell in row] for row in grid]
    keep = [index for index in range(len(xs) - 1) if any(row[index] for row in rows)]
    rows = [[row[index] for index in keep] for row in rows if any(row)]
    return rows if len(rows) >= 2 and len(keep) >= 2 else []


HEADER_WORD = re.compile(
    r"\b(?:s\.?\s*no|sl\.?\s*no|sr\.?\s*no|name|product|drugs?|batch|b\.?\s*no|lot|model|date|manufactur\w*|"
    r"mfg|expiry|reason|result|drawn|from|remarks?|reported|firm|reply|status|serial|quantity|units?)\b",
    re.I,
)
# A dashed rule fragment may lead the number: "'2.", "i3."
SERIAL_TEXT = re.compile(r"^\s*[|Iil!:;'`\u00b7]?\s*(\d{1,3})\s*[.)]?\s*$")
TABLE_END = re.compile(r"^\s*(?:note\b|based on\b|copy to\b|the drugs that fail|\(?further\b|yours faithfully)", re.I)
# Fragments of dashed ruling lines read as text: a lone "I" / "|", or a mark glued to a cell's edge.
RULE_GLYPHS = re.compile(r"^[\s|Il!\ufffd:;'`_\-]{1,3}$")
RULE_EDGE = re.compile(r"^[\s|\ufffd:;'`\u00b7]+|[\s|\ufffd]+$")


def _bands(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group OCR boxes into horizontal bands of boxes that overlap vertically."""
    bands: list[list[dict[str, Any]]] = []
    for line in sorted(lines, key=lambda item: item["bbox"][1]):
        y0, y1 = line["bbox"][1], line["bbox"][3]
        if bands:
            top = min(item["bbox"][1] for item in bands[-1])
            bottom = max(item["bbox"][3] for item in bands[-1])
            overlap = min(bottom, y1) - max(top, y0)
            if overlap > 0.5 * min(y1 - y0, bottom - top):
                bands[-1].append(line)
                continue
        bands.append([line])
    return bands


def _columns_from_header(header_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge header boxes that share horizontal space into columns (multi-line header cells)."""
    columns: list[dict[str, Any]] = []
    for line in sorted(header_lines, key=lambda item: item["bbox"][0]):
        x0, _, x1, _ = line["bbox"]
        for column in columns:
            if min(column["x1"], x1) - max(column["x0"], x0) > 0.3 * min(x1 - x0, column["x1"] - column["x0"]):
                column["x0"], column["x1"] = min(column["x0"], x0), max(column["x1"], x1)
                column["parts"].append(line)
                break
        else:
            columns.append({"x0": x0, "x1": x1, "parts": [line]})
    for column in columns:
        column["name"] = " ".join(part["text"] for part in sorted(column["parts"], key=lambda item: (item["bbox"][1], item["bbox"][0])))
        del column["parts"]
    return sorted(columns, key=lambda column: column["x0"])


def _column_index(columns: list[dict[str, Any]], x: float) -> int:
    """Nearest column by the midpoints between neighbouring column centres."""
    centers = [(column["x0"] + column["x1"]) / 2 for column in columns]
    for index in range(len(centers) - 1):
        if x < (centers[index] + centers[index + 1]) / 2:
            return index
    return len(centers) - 1


def _sequential_serials(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep serial numbers that continue the sequence top to bottom (n, n+1, ...).

    Ruling-line fragments read as stray "1"s; requiring each serial to follow the previous one drops
    them. The first serial on a page may be any number written with a full stop ("17.").
    """
    kept: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda line: line["bbox"][1]):
        value = int(SERIAL_TEXT.match(candidate["text"]).group(1))
        dotted = bool(re.search(r"[.)]", candidate["text"]))
        if kept:
            previous = int(SERIAL_TEXT.match(kept[-1]["text"]).group(1))
            if value == previous and abs(candidate["bbox"][1] - kept[-1]["bbox"][1]) < 20:
                continue  # the same serial read twice
            if value != previous + 1:
                continue
        elif not dotted:
            continue
        kept.append(candidate)
    return kept


def serial_strip_lines(image: np.ndarray, column: dict[str, Any], top: float) -> list[dict[str, Any]]:
    """OCR the serial-number column again, enlarged 2x: small isolated numbers ("1.") are often missed
    by detection on the full page. Returns serial boxes in full-page pixel coordinates."""
    x0, x1 = max(0, int(column["x0"]) - 4), int(column["x1"]) + 4
    strip = image[int(top):, x0:x1]
    if strip.size == 0:
        return []
    enlarged = cv2.copyMakeBorder(cv2.resize(strip, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
                                  0, 0, 40, 40, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    found = []
    for line in _run(enlarged):
        if SERIAL_TEXT.match(line["text"]):
            sx0, sy0, sx1, sy1 = line["bbox"]
            found.append(dict(line, bbox=[x0 + (sx0 - 40) / 2, top + sy0 / 2, x0 + (sx1 - 40) / 2, top + sy1 / 2]))
    return found


def table_from_layout(
    lines: list[dict[str, Any]],
    layout: list[dict[str, Any]] | None = None,
    extra_serials: list[dict[str, Any]] | None = None,
) -> tuple[list[list[str]], list[dict[str, Any]] | None, float]:
    """Rebuild a table from text positions when its ruling lines are broken, dashed or missing.

    Columns come from the header row's boxes (or from `layout`, the previous page's columns, on
    continuation pages without a header); rows start at each serial number in the first column, taken
    from the page OCR plus `extra_serials` (a second pass over the serial column). Returns the rows (header
    first when one was found), the column layout, and the y where the table body starts.
    """
    bands = _bands(lines)
    header_index = next(
        (index for index, band in enumerate(bands)
         if len(band) >= 3 and sum(1 for line in band if HEADER_WORD.search(line["text"])) >= 3
         and sum(char.isdigit() for line in band for char in line["text"]) <= 2),  # data rows carry batches/dates
        None,
    )
    if header_index is not None:
        header_lines, end = list(bands[header_index]), header_index + 1
        while end < len(bands) and end - header_index <= 3:
            band = bands[end]
            if any(char.isdigit() for line in band for char in line["text"]) or any(len(line["text"]) > 40 for line in band):
                break  # the first data row, even when its serial number was not read
            header_lines.extend(band)
            end += 1
        columns = _columns_from_header(header_lines)
        body = [line for band in bands[end:] for line in band]
        body_top = max(line["bbox"][3] for line in header_lines)
    elif layout:
        columns, body, body_top = layout, [line for band in bands for line in band], 0.0
    else:
        return [], None, 0.0
    if len(columns) < 3 or not body:
        return [], None, 0.0

    first_column_end = (columns[0]["x1"] + columns[1]["x0"]) / 2

    def is_serial_box(line: dict[str, Any]) -> bool:
        return bool(SERIAL_TEXT.match(line["text"])) and (line["bbox"][0] + line["bbox"][2]) / 2 < first_column_end

    anchors = _sequential_serials([line for line in body if is_serial_box(line)] + list(extra_serials or []))
    if not anchors:
        return [], columns, body_top
    content = [line for line in body if not is_serial_box(line) and not RULE_GLYPHS.match(line["text"])]
    heights = sorted(line["bbox"][3] - line["bbox"][1] for line in content or body)  # not the rule fragments
    line_height = heights[len(heights) // 2]
    starts = [anchor["bbox"][1] - 0.5 * line_height for anchor in anchors]

    rows: dict[int, list[list[tuple[float, float, str]]]] = {}
    last_bottom = None
    for line in sorted(content, key=lambda item: item["bbox"][1]):
        x0, y0, x1, y1 = line["bbox"]
        if TABLE_END.match(line["text"]) and y0 > starts[-1]:
            break
        if last_bottom is not None and y0 > starts[-1] and y0 - last_bottom > 3 * line_height:
            break  # a large gap after the last row: the table has ended
        row = sum(1 for start in starts if start <= (y0 + y1) / 2) - 1  # -1: text before the first serial
        cells = rows.setdefault(row, [[] for _ in columns])
        cells[_column_index(columns, (x0 + x1) / 2)].append((y0, x0, RULE_EDGE.sub("", line["text"])))
        last_bottom = max(last_bottom or 0, y1)

    table = [[column["name"] for column in columns]] if header_index is not None else []
    if -1 in rows:
        continuation = ["\n".join(text for _, _, text in sorted(cell)) for cell in rows[-1]]
        continuation[0] = ""  # continuation of the previous page's last record
        table.append(continuation)
    for index, anchor in enumerate(anchors):
        cells = ["\n".join(text for _, _, text in sorted(cell)) for cell in rows.get(index, [[] for _ in columns])]
        cells[0] = f"{SERIAL_TEXT.match(anchor['text']).group(1)}."
        table.append(cells)
    return table, columns, body_top


def ocr_page(page: Any, dpi: int = OCR_DPI, layout: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """OCR one PyMuPDF page: reading-order text, lines in PDF points, table rows, and rotation.

    Tables come from ruling lines when the grid is intact, otherwise from text positions. `layout` is the
    column layout returned for the previous page (PDF points), used when this page has no header row.
    """
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), colorspace=pymupdf.csRGB, alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    image, lines, rotation = ocr_image(image)
    scale = 72 / dpi
    pixel_layout = [dict(column, x0=column["x0"] / scale, x1=column["x1"] / scale) for column in layout] if layout else None
    table, method, columns = table_from_grid(image, lines), "ocr_grid", None
    layout_table, layout_columns, body_top = table_from_layout(lines, pixel_layout)
    grid_width = max((len(row) for row in table), default=0)
    if layout_columns and (not table or grid_width < len(layout_columns)):
        # No grid, or ruling lines that merged columns: rebuild from text positions instead.
        serials = serial_strip_lines(image, layout_columns[0], body_top)
        if serials:
            layout_table, layout_columns, _ = table_from_layout(lines, pixel_layout, extra_serials=serials)
        if layout_table or not table:
            table, method, columns = layout_table, "ocr_layout", layout_columns
    return {
        "text": reading_order_text(lines),
        "lines": [dict(line, bbox=[round(value * scale, 1) for value in line["bbox"]]) for line in lines],
        "table": table,
        "table_method": method if table else "none",
        "layout": [dict(column, x0=column["x0"] * scale, x1=column["x1"] * scale) for column in columns] if columns else None,
        "rotation": rotation,
        "mean_score": round(sum(line["score"] for line in lines) / len(lines), 4) if lines else 0.0,
    }


def warm_up() -> None:
    """Load (and on first use download) every OCR model, e.g. while building the Docker image."""
    blank = np.full((64, 256, 3), 255, dtype=np.uint8)
    cv2.putText(blank, "Batch No 1234", (5, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    get_engine()(blank)
    print("OCR models ready", file=sys.stderr)


if __name__ == "__main__":
    warm_up()
