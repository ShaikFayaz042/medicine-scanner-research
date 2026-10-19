"""Turn extracted table rows into records.

Handles what real CDSCO tables do: headers spread over several rows with merged parent cells
("Date of" over "Manufacture | Expiry"), full-width section rows ("B. State Laboratories"), headers
repeated on every page, rows continued across page breaks, serial numbers carrying footnote markers,
codes wrapped inside narrow cells, and the 2013-2018 column that packs batch, dates and manufacturer
into one cell. Column names are mapped to one canonical vocabulary so later stages see the same keys
for every layout.
"""

from __future__ import annotations

import re
from typing import Any

SERIAL_COLUMN = "S No"
PRODUCT_COLUMN = "Name of Drugs/medical device/cosmetics"
BATCH_COLUMN = "Batch No"
MFG_DATE_COLUMN = "Date of Manufacture"
EXPIRY_COLUMN = "Date of Expiry"
MANUFACTURER_COLUMN = "Manufactured By"
COMBINED_COLUMN = "Batch No/Date of Manufacture/Date of Expiry/Manufactured By"
CODE_COLUMNS = {BATCH_COLUMN, MFG_DATE_COLUMN, EXPIRY_COLUMN, "Model No"}

# Serial cell: "12", "12.", "12)", a serial followed by a footnote reference ("83. 1#", "118. 1"), or
# trailing stray punctuation from the text layer ("21. .").
SERIAL = re.compile(r"^\s*(\d{1,4})\s*(?:[.)]\s*(?:\d{1,2}\s*#?)?)?[\s.,;:)]*$")
# A bare footnote marker ("3#") in the serial column belongs to the record above, it is not a serial.
FOOTNOTE = re.compile(r"^\s*\d{1,2}\s*#\s*$")
HEADER_TERM = re.compile(
    r"\b(?:s\.?\s*no|sl\.?\s*no|sr\.?\s*no|serial|name|product|drugs?|batch|b\.?\s*no|lot|model|date|"
    r"manufactur\w*|mfg|mfd|expiry|exp|reason|result|drawn|from|remarks?|notification|indications?|"
    r"adverse|reactions?|reported|declared|firm'?s?|reply|response|sample|status|sales|outlets|vaccine|"
    r"devices?|cosmetics|laborator\w*|source|sub-?standard|nsq|action)\b",
    re.I,
)
NOISE_ROW = re.compile(r"^(page\s+\d+\s+of\s+\d+|\d+\s+of\s+\d+)\b|this report is issued|cdsco website", re.I)
SUMMARY_TABLE = re.compile(r"total number of samples|samples declared", re.I)

# (canonical name, predicate on the header reduced to lowercase letters only)
_CANONICAL_COLUMNS: tuple[tuple[str, Any], ...] = (
    (SERIAL_COLUMN, lambda k: k in {"sno", "slno", "srno", "no", "serialno", "snos"} or k.startswith(("sno", "slno", "srno"))),
    (COMBINED_COLUMN, lambda k: "batch" in k and ("manufact" in k or "expiry" in k or "mfg" in k)),
    (BATCH_COLUMN, lambda k: "batch" in k or k in {"bno", "lotno", "lotnumber", "lot"} or k.startswith("bno")),
    (MFG_DATE_COLUMN, lambda k: ("manufact" in k and "date" in k and "by" not in k) or "mfgdate" in k or k == "dmfg"),
    (EXPIRY_COLUMN, lambda k: "expiry" in k or "expdate" in k or k == "dexp"),
    (MANUFACTURER_COLUMN, lambda k: "manufacturedby" in k or k.startswith("manufacturer") or "mfdby" in k),
    (PRODUCT_COLUMN, lambda k: (
        ("nameof" in k or "product" in k or "drugname" in k or "drugsname" in k or "suspecteddrug" in k
         or "productbrand" in k or k.endswith(("vaccinename", "devicename", "brandname")))
        and not any(word in k for word in ("company", "laborator", "manufacturer", "firm"))
    )),
    ("Reason for failure", lambda k: "reasonfor" in k or "nsqresult" in k or "substandardin" in k or k == "result"),
    ("Drawn By", lambda k: "drawnby" in k or "reportingsource" in k or "samplereceived" in k or "sourceofsample" in k),
    ("From", lambda k: k == "from" or k.startswith("fromname") or "reportedby" in k or "declaredby" in k),
    ("Firm's Reply", lambda k: "firmsreply" in k or "responseoforiginal" in k),
    ("Remarks", lambda k: k.startswith("remark")),
    ("Notification No. & Date", lambda k: "notification" in k),
    ("Model No", lambda k: k.startswith("modelno")),
    ("Indication(s)", lambda k: k.startswith("indication")),
    ("Adverse Drug Reactions", lambda k: "adverse" in k),
    ("Sales Outlets", lambda k: "salesoutlet" in k),
    ("Regulatory Action", lambda k: "regulatoryaction" in k),
    ("Status", lambda k: k == "status"),
)

_COMBINED_LABELS = (
    (BATCH_COLUMN, re.compile(r"\b(?:B\.?\s*No|Batch\s*No)\b\.?", re.I)),
    (MFG_DATE_COLUMN, re.compile(r"(?:\bD\s*/\s*Mfg|\bMfg\.?\s*(?:dt|date))\b\.?", re.I)),
    (EXPIRY_COLUMN, re.compile(r"(?:\bD\s*/\s*Exp|\bExp\.?\s*(?:dt|date))\b\.?", re.I)),
    (MANUFACTURER_COLUMN, re.compile(r"\b(?:Mfd|Mfg)\.?\s*By\b\.?|\bManufactured\s+by\b", re.I)),
)
_LABEL_SEPARATORS = " \t\n:;,.-–—�"


def clean_text(value: Any) -> str:
    """Collapse cell text; a hyphen at a line break joins the word ("Gastro-\\nResistant")."""
    text = str(value or "").replace("�", "-")
    text = re.sub(r"-\s*\n\s*", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_code(value: Any) -> str:
    """Codes wrap inside narrow columns ("LMT240\\n263"); a line break between code characters is not a space."""
    text = re.sub(r"(?<=[A-Za-z0-9/\-])\s*\n\s*(?=[A-Za-z0-9/\-])", "", str(value or ""))
    return clean_text(text)


def is_serial(value: Any) -> bool:
    return bool(SERIAL.match(clean_text(value)))


def _header_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower().replace("the ", ""))


def canonical_column(name: str) -> str | None:
    key = _header_key(name)
    if not key:
        return None
    return next((canonical for canonical, matches in _CANONICAL_COLUMNS if matches(key)), None)


def is_header_row(row: list[Any]) -> bool:
    cells = [clean_text(cell) for cell in row if clean_text(cell)]
    # Header cells can be long ("Sales Outlets Involved in Distribution of Spurious Drugs (Name and
    # address...)"); what separates headers from data rows is that most cells are header vocabulary.
    if len(cells) < 2 or is_serial(cells[0]) or any(len(cell) > 250 for cell in cells):
        return False
    hits = sum(1 for cell in cells if HEADER_TERM.search(cell))
    return hits >= 2 and hits >= 0.6 * len(cells)


def _is_header_continuation(row: list[Any]) -> bool:
    cells = [clean_text(cell) for cell in row if clean_text(cell)]
    if not cells or is_serial(row[0] if row else "") or any(len(cell) > 40 for cell in cells):
        return False
    # Continuation rows hold header words or short word fragments ("uring", "Expiry"); codes and numbers
    # ("ES483", "12") mean the data has started.
    headerish = sum(
        1 for cell in cells
        if HEADER_TERM.search(cell) or (len(cell.split()) <= 2 and not re.search(r"\d", cell))
    )
    return headerish >= 0.5 * len(cells)


def _merge_header(block: list[list[Any]]) -> list[str]:
    """Merge header rows column-wise, copying a merged parent label onto the columns it spans."""
    width = max(len(row) for row in block)
    levels = [[clean_text(row[index]) if index < len(row) else "" for index in range(width)] for row in block]
    for upper in levels[:-1]:
        for column in range(1, width):
            if not upper[column] and upper[column - 1] and levels[-1][column] and levels[-1][column - 1]:
                upper[column] = upper[column - 1]
    names = []
    for column in range(width):
        parts = list(dict.fromkeys(level[column] for level in levels if level[column]))
        names.append(" ".join(parts))
    return names


def canonical_header(names: list[str]) -> list[str]:
    header, used = [], set()
    for index, name in enumerate(names):
        canonical = canonical_column(name)
        if canonical and canonical not in used:
            used.add(canonical)
            header.append(canonical)
        else:
            header.append(name or f"Column_{index + 1}")
    return header


def _find_header(rows: list[list[Any]]) -> tuple[int, int] | None:
    start = next((index for index, row in enumerate(rows[:8]) if is_header_row(row)), None)
    if start is None:
        return None
    end = start
    while end + 1 < len(rows) and end - start < 3 and _is_header_continuation(rows[end + 1]):
        end += 1
    return start, end


def split_combined(value: str) -> dict[str, str]:
    """Split "B. No.: X, Mfg dt: 11/2017, Exp dt: 10/2019, Mfd by: M/s ..." into its four fields."""
    positions = []
    for column, pattern in _COMBINED_LABELS:
        match = pattern.search(value)
        if match:
            positions.append((match.start(), match.end(), column))
    positions.sort()
    fields: dict[str, str] = {}
    for index, (_, end, column) in enumerate(positions):
        stop = positions[index + 1][0] if index + 1 < len(positions) else len(value)
        # Separators are dropped after a label; at the end only commas go, so "Ltd." keeps its full stop.
        text = value[end:stop].lstrip(_LABEL_SEPARATORS).rstrip().rstrip(",;").rstrip()
        if text:
            fields[column] = clean_code(text) if column in CODE_COLUMNS else clean_text(text)
    return fields


def _cell_value(raw: Any, column: str) -> str:
    return clean_code(raw) if column in CODE_COLUMNS else clean_text(raw)


def _append(record: dict[str, Any], column: str, raw: Any) -> None:
    value = _cell_value(raw, column)
    if not value:
        return
    previous = record.get(column, "")
    joiner = "" if column in CODE_COLUMNS and previous and re.match(r"[A-Za-z0-9]", value) and len(value) <= 4 else " "
    record[column] = (previous + joiner + value).strip() if previous else value


def _align_to_header(rows: list[list[Any]], header: list[str]) -> tuple[list[list[Any]], list[str]]:
    """Fit a header-less continuation table to the carried header when their widths differ.

    Merged header cells leave placeholder columns ("Column_3") that the next page's table does not
    have, and some extractions add empty columns; dropping either makes the positions line up again.
    """
    width = max(len(row) for row in rows)
    if width == len(header):
        return rows, header
    named = [name for name in header if not name.startswith("Column_")]
    if width == len(named):
        return rows, named
    keep = [index for index in range(width) if any(index < len(row) and clean_text(row[index]) for row in rows)]
    if len(keep) == len(header):
        return [[row[index] if index < len(row) else "" for index in keep] for row in rows], header
    if len(keep) == len(named):
        return [[row[index] if index < len(row) else "" for index in keep] for row in rows], named
    return rows, header


def _record_anchor(header: list[str]) -> tuple[int, bool]:
    """Column whose value starts a new record: the serial number, or (for tables without one, such as
    device recall batch lists) the batch, then the product column."""
    if SERIAL_COLUMN in header:
        return header.index(SERIAL_COLUMN), True
    for column in (BATCH_COLUMN, PRODUCT_COLUMN):
        if column in header:
            return header.index(column), False
    return 0, True


def records_from_tables(
    tables: list[tuple[int, list[list[Any]]]],
    dropped: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build records from (page, rows) tables in document order; returns records and the column names.

    Rows that hold data but cannot be placed (an unreadable serial cell, or data before any record) are
    appended to `dropped` with their page, so callers can report them instead of losing them silently.
    """
    records: list[dict[str, Any]] = []
    header: list[str] | None = None
    current: dict[str, Any] | None = None
    section: str | None = None

    for page, raw_rows in tables:
        rows = [list(row) for row in raw_rows if row]
        if not rows:
            continue
        table_text = " ".join(clean_text(cell) for row in rows for cell in row)
        has_serial_rows = any(row and is_serial(row[0]) for row in rows)
        if SUMMARY_TABLE.search(table_text) and not has_serial_rows:
            continue  # "Total number of samples tested ..." block above the data table
        found = _find_header(rows)
        if found:
            start, end = found
            for row in rows[:start]:
                titles = [clean_text(cell) for cell in row if clean_text(cell)]
                if len(titles) == 1 and clean_text(row[0]) and len(titles[0]) <= 80:
                    section = titles[0]  # section row above the header, e.g. "NCT of DELHI"
            names = canonical_header(_merge_header(rows[start:end + 1]))
            if names != header:
                header, current = names, None
            rows = rows[end + 1:]
        if header is None:
            continue
        table_header = header
        if not found:
            rows, table_header = _align_to_header(rows, header)
        anchor_index, by_serial = _record_anchor(table_header)

        for row in rows:
            cells = [clean_text(cell) for cell in row]
            filled = [index for index, cell in enumerate(cells) if cell]
            if not filled or NOISE_ROW.search(" ".join(cells)):
                continue
            if is_header_row(row):
                continue  # header repeated inside the table body (page breaks, sub-header rows)
            anchor = cells[anchor_index] if anchor_index < len(cells) else ""
            starts_record = is_serial(anchor) if by_serial else bool(anchor) and not FOOTNOTE.match(anchor)
            if starts_record:
                current = {"page_number": page}
                if section:
                    current["Section"] = section
                for index, raw in enumerate(row):
                    column = table_header[index] if index < len(table_header) else f"Column_{index + 1}"
                    value = _cell_value(raw, column)
                    if column == SERIAL_COLUMN and by_serial:
                        value = SERIAL.match(value).group(1)
                    if value:
                        current[column] = value
                records.append(current)
            elif by_serial and filled == [anchor_index] and len(cells[anchor_index]) <= 80:
                section = cells[anchor_index]  # full-width section row, e.g. "NCT of DELHI"
            elif current is not None and (not anchor or FOOTNOTE.match(anchor)):
                for index, raw in enumerate(row):
                    if index != anchor_index:
                        _append(current, table_header[index] if index < len(table_header) else f"Column_{index + 1}", raw)
            elif dropped is not None and len(filled) > 1:
                dropped.append({"page_number": page, "cells": cells})

    for record in records:
        combined = record.pop(COMBINED_COLUMN, None)
        if combined:
            for column, value in split_combined(combined).items():
                record.setdefault(column, value)
            record[COMBINED_COLUMN + " (source)"] = combined

    columns: list[str] = []
    for record in records:
        for key in record:
            if key not in columns and key != "page_number":
                columns.append(key)
    return records, columns
