"""Adapters for the S3 extractor payload consumed by Stage 3 rules."""

from __future__ import annotations

from typing import Any


def _rows_from_table(table: Any) -> list[list[str]]:
    cells = table.get("cells", []) if isinstance(table, dict) else table
    if isinstance(cells, dict):
        cells = [cells]
    if not isinstance(cells, list) or not cells:
        return []

    if all(not isinstance(cell, (dict, list, tuple)) for cell in cells):
        return [["" if cell is None else str(cell).strip() for cell in cells]]

    grouped_rows: dict[int, list[list[str]]] = {}
    for row in cells:
        if isinstance(row, dict):
            table_index = int(row.get("table_index", 0)) if str(row.get("table_index", 0)).strip() else 0
            row_cells = row.get("cells", [])
        else:
            table_index = 0
            row_cells = row

        if isinstance(row_cells, (list, tuple)):
            normalized_row = ["" if cell is None else str(cell).strip() for cell in row_cells]
        elif row_cells is not None:
            normalized_row = [str(row_cells).strip()]
        else:
            normalized_row = []

        grouped_rows.setdefault(table_index, []).append(normalized_row)

    rows: list[list[str]] = []
    for table_index in sorted(grouped_rows):
        rows.extend(grouped_rows[table_index])
    return rows


def normalize_extracted_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize both grouped and flattened extractor tables to Stage 3 rows."""
    normalized = dict(payload)
    pages = []
    page_tables: list[dict[str, Any]] = []

    for page in payload.get("pages") or []:
        normalized_page = dict(page)
        rows = []
        for table in page.get("tables") or []:
            rows.extend(_rows_from_table(table))
        normalized_page["tables"] = (
            [{"page": page.get("page"), "cells": rows}] if rows else []
        )
        pages.append(normalized_page)
        if rows:
            page_tables.append({"page": page.get("page"), "cells": rows})

    source_tables = payload.get("tables") or []
    tables = []
    for table in source_tables:
        rows = _rows_from_table(table)
        if rows:
            normalized_table = {"cells": rows}
            if isinstance(table, dict) and table.get("page") is not None:
                normalized_table["page"] = table["page"]
            tables.append(normalized_table)

    normalized["pages"] = pages
    normalized["tables"] = tables or page_tables

    metadata = dict(payload.get("extraction_meta") or {})
    try:
        completed_ocr_pages = int(metadata.get("ocr_pages") or 0)
        already_completed = int(metadata.get("stage3_ocr_completed_pages") or 0)
    except (TypeError, ValueError):
        completed_ocr_pages = already_completed = 0
    if completed_ocr_pages:
        metadata["stage3_ocr_completed_pages"] = max(
            completed_ocr_pages, already_completed
        )
    normalized["extraction_meta"] = metadata
    return normalized


def language_text_from_payload(payload: dict[str, Any]) -> str:
    """Build model input from page text and normalized table rows."""
    chunks = []
    for page in payload.get("pages") or []:
        text = page.get("text") or ""
        if text:
            chunks.append(str(text))
        for table in page.get("tables") or []:
            for row in _rows_from_table(table):
                row_text = " ".join(cell for cell in row if cell)
                if row_text:
                    chunks.append(row_text)

    title = payload.get("pdf_title") or payload.get("title")
    if title:
        chunks.insert(0, str(title))
    return "\n".join(chunks)