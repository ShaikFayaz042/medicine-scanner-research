"""Table extraction and context building logic."""
from __future__ import annotations

import re
from typing import Sequence

from idp.schemas.classification_context import SourceReference, TableContext
from idp.schemas.extraction import Item

_SPACE = re.compile(r"\s+")

def _normalize_cell(value: str) -> str:
    return _SPACE.sub(" ", value).strip().casefold()

def _representative_rows(rows: list[list[str]], limit: int = 3) -> list[list[str]]:
    """Return deterministic first, middle, and last distinct data rows."""
    if limit <= 0 or not rows:
        return []
    indices = sorted({0, len(rows) // 2, len(rows) - 1})
    selected: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for index in indices:
        row = rows[index]
        normalized = tuple(_normalize_cell(cell) for cell in row)
        if any(normalized) and normalized not in seen:
            selected.append(row)
            seen.add(normalized)
        if len(selected) == limit:
            break
    return selected

def extract_tables(
    page_items: Sequence[Item],
    page_number: int,
    page_width: float,
    page_height: float,
    batch_artifact: str,
    item_to_context_table_id: dict[str, str],
    table_headers_cache: dict[str, list[str]],
) -> tuple[list[TableContext], list[str]]:
    """Extract minimal, classification-ready tables with cascading header inheritance."""
    tables: list[TableContext] = []
    warnings: list[str] = []

    for item in page_items:
        if item.type != "table" or item.table is None:
            continue

        table = item.table
        rows = [[(cell or "").strip() for cell in row] for row in table.rows]
        rows = [row for row in rows if any(cell for cell in row)]
        
        headers = [header.strip() for header in table.header_names]
        continuation_of = None
        
        # 1. Handle Continuation & Header Inheritance
        if table.continuation_of:
            continuation_of = item_to_context_table_id.get(table.continuation_of)
            if continuation_of is None:
                warnings.append(f"missing_continuation_target:{item.item_id}")
            elif table.header_external:
                parent_headers = table_headers_cache.get(table.continuation_of)
                if parent_headers:
                    headers = parent_headers
                    # FIX: Do not warn as 'unmerged' if we successfully inherited headers.
                    # It's a successful lightweight link.
                else:
                    warnings.append(f"missing_parent_headers:{continuation_of}")

        # 2. Clean up duplicate headers in row 0 if not external
        if not table.header_external and headers and rows:
            if tuple(map(_normalize_cell, rows[0])) == tuple(map(_normalize_cell, headers)):
                rows = rows[1:]

        # FIX: Cache effective headers (whether original or inherited)
        # so Page 3 can inherit from Page 2.
        if headers:
            table_headers_cache[item.item_id] = headers

        context_table_id = f"T{page_number:03d}_{item.item_id}"
        x0, y0, x1, y1 = item.bbox
        bbox = (x0 * page_width, y0 * page_height, x1 * page_width, y1 * page_height)

        tables.append(TableContext(
            id=context_table_id,
            pages=[page_number],
            headers=headers,
            sample_rows=_representative_rows(rows),
            row_count=table.n_data_rows if table.n_data_rows is not None else table.n_rows,
            column_count=table.n_cols,
            bbox=bbox,
            source_refs=[SourceReference(
                page=page_number,
                artifact=batch_artifact,
                item_id=item.item_id,
                method=item.source.method,
                bbox=bbox,
            )],
            header_external=table.header_external,
            continuation_of=continuation_of,
        ))
        
        item_to_context_table_id[item.item_id] = context_table_id

    return tables, warnings