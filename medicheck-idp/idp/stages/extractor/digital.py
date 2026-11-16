"""Native text and ruled-table extraction with PyMuPDF."""
from __future__ import annotations

import pymupdf

from idp.schemas.extraction import Item, Segment, Source, Table
from idp.stages.extractor.geometry import normalize, to_unrotated, to_visible

_TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP
_NATIVE_TEXT = Source(engine="pymupdf", method="native_text")
_NATIVE_TABLE = Source(engine="pymupdf", method="native_table")
_BOLD_NAMES = ("bold", "black", "heavy", "semibold", "demibold")
_HEADER_TOKENS = {
    "batch", "mfg date", "manufacturing date", "exp date", "expiry date",
    "lot", "product", "description", "name", "date", "status", "quantity",
    "code", "no", "number",
}


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or any(k in span["font"].lower() for k in _BOLD_NAMES)


def native_lines(page: pymupdf.Page) -> list[Item]:
    items = []
    for block in page.get_text("dict", flags=_TEXT_FLAGS)["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            segs = [Segment(text=s["text"], size=round(s["size"], 2), font=s["font"],
                            bold=_is_bold(s), italic=bool(s["flags"] & 2))
                    for s in line["spans"] if s["text"]]
            text = "".join(s.text for s in segs).strip()
            if not text:
                continue
            items.append(Item(item_id="", type="text_line", text=text, segments=segs,
                              bbox=normalize(page, to_visible(page, line["bbox"])),
                              source=_NATIVE_TEXT, block=block["number"]))
    return items


def _cell_text(page: pymupdf.Page, cell: tuple[float, float, float, float] | None) -> str | None:
    if cell is None:
        return None
    # find_tables() reports visible-space cells; get_text(clip=...) expects unrotated space.
    text = page.get_text("text", clip=to_unrotated(page, cell), flags=_TEXT_FLAGS)
    return " ".join(text.split())


def _looks_like_real_header(names: list[str]) -> bool:
    if not names:
        return False
    hits = sum(
        1 for name in names
        if any(token in (name or "").lower() for token in _HEADER_TOKENS)
    )
    return hits >= max(1, len(names) // 2)


def native_tables(page: pymupdf.Page, strategy: str, min_rows: int, min_cols: int) -> list[Item]:
    """Extract text from each cell without dropping wide or narrow-column tables."""
    items = []
    # PyMuPDF4LLM's layout analyzer caches page layout and can suppress line tables.
    # The JSON table evidence must be independent of that process-global mode.
    for t in page.find_tables(strategy=strategy, use_layout=False).tables:
        if t.row_count < min_rows or t.col_count < min_cols:
            continue
        rows = [[_cell_text(page, cell) for cell in row.cells] for row in t.rows]
        if not any(cell and cell.strip() for row in rows for cell in row):
            continue
        column_cells: list[list[tuple[float, float, float, float]]] = [
            [] for _ in range(t.col_count)
        ]
        for row in t.rows:
            for col_index, cell in enumerate(row.cells):
                if cell is not None:
                    column_cells[col_index].append(normalize(page, cell))
        columns = (
            [(min(box[0] for box in boxes), max(box[2] for box in boxes))
             for boxes in column_cells]
            if all(column_cells) else []
        )
        hdr = t.header
        header_names = [str(name) for name in (hdr.names if hdr else []) if name]
        header_external = bool(hdr.external) if hdr else False
        if header_names and not _looks_like_real_header(header_names):
            header_external = True
            header_names = []
        items.append(Item(
            item_id="", type="table", source=_NATIVE_TABLE,
            # find_tables() already returns visible-space boxes, even on rotated pages.
            bbox=normalize(page, t.bbox),
            table=Table(rows=rows, n_rows=t.row_count, n_cols=t.col_count,
                        header_names=header_names,
                        header_external=header_external,
                        columns=columns)))
    return items