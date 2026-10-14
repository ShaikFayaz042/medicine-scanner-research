"""Re-detect document type and structure for PDFs listed in the classifier CSV."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pymupdf

ROOT = Path(__file__).resolve().parent
IMAGE_SCAN_COVERAGE = 0.55


def _rect_union_area(rectangles: list[tuple[float, float, float, float]]) -> float:
    if not rectangles:
        return 0.0

    x_edges = sorted({coordinate for rect in rectangles for coordinate in (rect[0], rect[2])})
    area = 0.0
    for left, right in zip(x_edges, x_edges[1:]):
        if right <= left:
            continue
        intervals = sorted(
            (top, bottom)
            for x0, top, x1, bottom in rectangles
            if x0 < right and x1 > left and bottom > top
        )
        covered_y = 0.0
        if intervals:
            top, bottom = intervals[0]
            for next_top, next_bottom in intervals[1:]:
                if next_top <= bottom:
                    bottom = max(bottom, next_bottom)
                else:
                    covered_y += bottom - top
                    top, bottom = next_top, next_bottom
            covered_y += bottom - top
        area += (right - left) * covered_y
    return area


def _image_coverage(page: pymupdf.Page) -> float:
    page_rect = page.rect
    page_area = max(page_rect.width * page_rect.height, 1.0)
    rectangles = []
    for image in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = image.get("bbox", (0, 0, 0, 0))
        x0, y0 = max(x0, page_rect.x0), max(y0, page_rect.y0)
        x1, y1 = min(x1, page_rect.x1), min(y1, page_rect.y1)
        if x1 > x0 and y1 > y0:
            rectangles.append((x0, y0, x1, y1))
    return min(1.0, _rect_union_area(rectangles) / page_area)


def _table_bbox_is_valid(table: Any) -> bool:
    try:
        rows = table.extract()
    except Exception:
        return False
    populated_rows = [
        [str(cell or "").strip() for cell in row]
        for row in rows or []
        if any(str(cell or "").strip() for cell in row)
    ]
    if len(populated_rows) < 2:
        return False
    width = max((len(row) for row in populated_rows), default=0)
    if width < 2:
        return False
    multi_cell_rows = sum(sum(bool(cell) for cell in row) >= 2 for row in populated_rows)
    return multi_cell_rows >= 2


def _has_vector_grid(page: pymupdf.Page) -> bool:
    horizontal = set()
    vertical = set()
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] == "l":
                start, end = item[1], item[2]
                if abs(start.y - end.y) <= 1.5 and abs(start.x - end.x) >= 25:
                    horizontal.add(round((start.y + end.y) / 2))
                elif abs(start.x - end.x) <= 1.5 and abs(start.y - end.y) >= 12:
                    vertical.add(round((start.x + end.x) / 2))
            elif item[0] == "re":
                rectangle = item[1]
                horizontal.update((round(rectangle.y0), round(rectangle.y1)))
                vertical.update((round(rectangle.x0), round(rectangle.x1)))
    return len(horizontal) >= 2 and len(vertical) >= 2


def _text_table_clip(page: pymupdf.Page) -> pymupdf.Rect | None:
    lines = defaultdict(list)
    for word in page.get_text("words"):
        if len(word) >= 8:
            lines[(word[5], word[6])].append(word)

    candidates = []
    for words in lines.values():
        words.sort(key=lambda word: word[0])
        starts = [words[0][0]] if words else []
        previous_right = words[0][2] if words else 0
        for word in words[1:]:
            if word[0] - previous_right >= 18:
                starts.append(word[0])
            previous_right = max(previous_right, word[2])
        if len(starts) >= 2:
            candidates.append((starts[:2], words))

    aligned_rows = []
    for starts, words in candidates:
        for other_starts, other_words in candidates:
            if other_words is words:
                continue
            if all(abs(left - right) <= 14 for left, right in zip(starts, other_starts)):
                aligned_rows.extend((words, other_words))
                break
    unique_rows = {id(words): words for words in aligned_rows}.values()
    rows = list(unique_rows)
    if len(rows) < 3:
        return None

    x0 = min(word[0] for words in rows for word in words)
    y0 = min(word[1] for words in rows for word in words)
    x1 = max(word[2] for words in rows for word in words)
    y1 = max(word[3] for words in rows for word in words)
    if y1 - y0 < 24:
        return None
    page_rect = page.rect
    return pymupdf.Rect(page_rect.x0, max(page_rect.y0, y0 - 6), page_rect.x1, min(page_rect.y1, y1 + 6))


def _find_table_rectangles(page: pymupdf.Page) -> list[tuple[float, float, float, float]]:
    clip = None
    strategy = "lines"
    if not _has_vector_grid(page):
        clip = _text_table_clip(page)
        if clip is None:
            return []
        strategy = "text"

    try:
        finder = page.find_tables(strategy=strategy, clip=clip)
    except Exception:
        return []
    rectangles = []
    for table in finder.tables:
        if not _table_bbox_is_valid(table):
            continue
        try:
            x0, y0, x1, y1 = table.bbox
        except (AttributeError, TypeError, ValueError):
            continue
        rectangles.append((x0, y0, x1, y1))
    return rectangles


def _block_is_in_table(
    block: tuple[Any, ...], table_rectangles: list[tuple[float, float, float, float]]
) -> bool:
    x0, y0, x1, y1 = map(float, block[:4])
    block_area = max((x1 - x0) * (y1 - y0), 1.0)
    for tx0, ty0, tx1, ty1 in table_rectangles:
        intersection_width = max(0.0, min(x1, tx1) - max(x0, tx0))
        intersection_height = max(0.0, min(y1, ty1) - max(y0, ty0))
        if intersection_width * intersection_height / block_area >= 0.35:
            return True
    return False


def inspect_pdf(path: Path) -> dict[str, str]:
    with pymupdf.open(path) as document:
        if document.needs_pass:
            raise ValueError("PDF requires a password")

        scanned_pages = 0
        has_table = False
        has_paragraph = False
        page_count = len(document)
        if page_count == 0:
            raise ValueError("PDF has no pages")

        for page in document:
            image_coverage = _image_coverage(page)
            if image_coverage >= IMAGE_SCAN_COVERAGE:
                scanned_pages += 1
                table_rectangles = []
            else:
                table_rectangles = _find_table_rectangles(page)
            has_table = has_table or bool(table_rectangles)
            for block in page.get_text("blocks"):
                if len(block) < 5 or not str(block[4]).strip():
                    continue
                if not _block_is_in_table(block, table_rectangles):
                    has_paragraph = True

    is_scanned = scanned_pages / page_count >= 0.5
    if is_scanned:
        structure = "unknown"
    elif has_table:
        structure = "table"
    else:
        structure = "para"
    return {
        "document_type": "scanned" if is_scanned else "digital",
        "structure": structure,
    }


def _csv_pdf_index(root: Path) -> dict[tuple[str, str], Path]:
    index = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            continue
        relative = path.relative_to(root)
        key = (relative.parent.as_posix(), relative.name)
        index[key] = path
    return index


def _row_pdf_key(row: dict[str, str]) -> tuple[str, str]:
    source = str(row.get("Source") or "").replace("\\", "/").strip("/")
    filename = str(row.get("File Name") or "").strip()
    return source, filename


def _write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8-sig",
            newline="",
            delete=False,
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            writer = csv.DictWriter(temporary_file, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-detect digital/scanned type and table/paragraph structure in a classifier CSV."
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="Root containing source folders and PDFs")
    parser.add_argument("--csv", type=Path, default=ROOT / "full_corpus_classified.csv", help="CSV to update")
    parser.add_argument("--limit", type=int, default=0, help="Optional row limit for a trial run")
    parser.add_argument("--dry-run", action="store_true", help="Inspect PDFs without writing the CSV")
    args = parser.parse_args(argv)

    if args.limit < 0:
        parser.error("--limit must be zero or greater")
    root = args.root.resolve()
    csv_path = args.csv if args.csv.is_absolute() else root / args.csv
    csv_path = csv_path.resolve()
    if not root.is_dir():
        parser.error(f"PDF root not found: {root}")
    if not csv_path.is_file():
        parser.error(f"CSV not found: {csv_path}")

    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames:
            parser.error("CSV has no header row")
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    profile_columns = {
        "document_type": "Document Type",
        "structure": "Structure",
    }
    for field in profile_columns.values():
        if field not in fieldnames:
            fieldnames.append(field)
    work_rows = rows[: args.limit] if args.limit else rows
    pdf_index = _csv_pdf_index(root)
    profile_counts: Counter[tuple[str, str]] = Counter()
    missing = 0
    failed = 0

    for index, row in enumerate(work_rows, start=1):
        key = _row_pdf_key(row)
        label = f"{key[0]}/{key[1]}"
        print(f"[{index}/{len(work_rows)}] {label} ...", end=" ", flush=True)
        path = pdf_index.get(key)
        if path is None:
            missing += 1
            print("MISSING", flush=True)
            continue
        try:
            profile = inspect_pdf(path)
        except Exception as exc:
            failed += 1
            print(f"ERROR: {exc}", flush=True)
            continue
        row.update({profile_columns[key]: value for key, value in profile.items()})
        profile_counts[(profile["document_type"], profile["structure"])] += 1
        print(
            f"{profile['document_type']} | {profile['structure']}",
            flush=True,
        )

    if not args.dry_run:
        _write_csv_atomic(csv_path, fieldnames, rows)

    action = "Dry run; CSV unchanged" if args.dry_run else f"Updated {csv_path}"
    print(f"{action}: {len(work_rows)} rows checked; {dict(profile_counts)}")
    print(f"Missing PDFs: {missing}; failed PDFs: {failed}")
    return 1 if failed or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
