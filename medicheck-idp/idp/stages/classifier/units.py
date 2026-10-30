"""Turn a structured document (stage 4 contract) into classification units.

- Tables: one unit per logical table (stage 4 already merged tables that span pages).
- Paragraphs: blocks grouped either by heading ("section") or into fixed-size chunks ("chunk"), chosen
  in rules/classification_rules.yaml. Groups are split at block boundaries when longer than
  max_unit_chars, and fragments shorter than min_record_chars (a lone heading, "Sir,", a signature) are
  merged into the following group, or the previous one at the end of the document, so they do not
  become units of their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from idp.schemas.structured import Block, StructuredDocument, Table
from idp.schemas.taxonomy import UnitSettings

_SPACES = re.compile(r"\s+")


def collapse(text: str) -> str:
    return _SPACES.sub(" ", text or "").strip()


@dataclass
class TableUnit:
    unit_id: str
    table: Table
    header: List[str]
    context: str
    title: str

    @property
    def pages(self) -> List[int]:
        return list(self.table.pages)

    def header_candidates(self, body_rows: int = 3) -> List[tuple]:
        """(source, cells) to match: the delivered header, or, when stage 4 found none, the first body rows
        (a section row such as 'NCT of DELHI' can push the real header down)."""
        if self.header:
            return [("header_rows", self.header)]
        return [(f"body_row_{index}", [collapse(c) for c in row.cells]) for index, row in enumerate(self.table.rows[:body_rows])]

    def body_text(self, max_rows: Optional[int] = None) -> str:
        rows = self.table.rows if max_rows is None else self.table.rows[:max_rows]
        return "\n".join(" | ".join(collapse(cell) for cell in row.cells) for row in rows)

    @property
    def text(self) -> str:
        """Header plus every row: what an evidence quote for a table must come from."""
        return "\n".join(filter(None, [" | ".join(self.header), self.body_text()]))


@dataclass
class ParagraphUnit:
    unit_id: str
    blocks: List[Block]
    pages: List[int]
    heading_path: List[str]
    title: str
    previous_text: str = ""
    next_text: str = ""
    text: str = field(init=False)

    def __post_init__(self) -> None:
        self.text = "\n".join(collapse(block.text) for block in self.blocks if collapse(block.text))

    @property
    def body_chars(self) -> int:
        """Characters outside headings: a lone heading is not a record."""
        return sum(len(collapse(b.text)) for b in self.blocks if b.type != "heading")

    @property
    def context(self) -> str:
        return " / ".join([self.title, *self.heading_path]).strip(" /")


def merge_header_rows(header_rows: List[List[str]]) -> List[str]:
    """Stack multi-row headers into one name per column ("Date of" + "Expiry" -> "Date of Expiry")."""
    width = max((len(row) for row in header_rows), default=0)
    merged = []
    for index in range(width):
        parts = [collapse(row[index]) for row in header_rows if index < len(row) and collapse(row[index])]
        merged.append(" ".join(dict.fromkeys(parts)))
    return merged


def _section_rows(table: Table, limit: int = 3) -> List[str]:
    """Full-width rows at the top of the body ('B. STATE LABORATORIES'): context, not data."""
    rows = []
    for row in table.rows[:limit]:
        filled = [collapse(cell) for cell in row.cells if collapse(cell)]
        if len(filled) == 1 and len(row.cells) > 1:
            rows.append(filled[0])
    return rows


def table_units(document: StructuredDocument) -> List[TableUnit]:
    title = document.document.title or ""
    units = []
    for table in document.tables:
        context = " / ".join(filter(None, [title, *table.heading_path, table.caption or "", *_section_rows(table)]))
        units.append(TableUnit(f"table:{table.table_id}", table, merge_header_rows(table.header_rows), context, title))
    return units


@dataclass
class _Placed:
    block: Block
    page: int
    heading_path: List[str]
    section: int


def _placed_blocks(document: StructuredDocument, settings: UnitSettings) -> List[_Placed]:
    allowed = {language.lower() for language in settings.languages}
    skip = set(settings.skip_block_types)
    placed: List[_Placed] = []
    path: List[tuple] = []  # (level, text)
    section = 0
    for page in sorted(document.pages, key=lambda p: p.page_number):
        for block in page.blocks:
            if block.type in skip or not collapse(block.text):
                continue
            if block.language and allowed and block.language.lower() not in allowed:
                continue
            if block.type == "heading":
                level = block.level or 1
                path = [entry for entry in path if entry[0] < level] + [(level, collapse(block.text))]
                section += 1
            placed.append(_Placed(block, page.page_number, [text for _, text in path], section))
    return placed


def _group(placed: List[_Placed], settings: UnitSettings) -> List[List[_Placed]]:
    groups: List[List[_Placed]] = []
    current: List[_Placed] = []
    size = 0
    for item in placed:
        length = len(collapse(item.block.text))
        if settings.paragraph_strategy == "section":
            new_group = bool(current) and (item.section != current[-1].section or size + length > settings.max_unit_chars)
        else:
            new_group = bool(current) and size + length > settings.chunk_target_chars
        if new_group:
            groups.append(current)
            current, size = [], 0
        current.append(item)
        size += length
    if current:
        groups.append(current)
    return _merge_fragments(groups, settings)


def _merge_fragments(groups: List[List[_Placed]], settings: UnitSettings) -> List[List[_Placed]]:
    """Fold groups too short to be a record into the following group (the previous one at the end)."""

    def body(group: List[_Placed]) -> int:
        return sum(len(collapse(p.block.text)) for p in group if p.block.type != "heading")

    merged: List[List[_Placed]] = []
    pending: List[_Placed] = []
    for group in groups:
        group = pending + group
        pending = []
        if body(group) < settings.min_record_chars:
            pending = group
            continue
        merged.append(group)
    if pending:
        if merged:
            merged[-1].extend(pending)
        else:
            merged.append(pending)  # the whole document is one fragment: a not_a_record unit
    return merged


def paragraph_units(document: StructuredDocument, settings: UnitSettings, context_chars: int) -> List[ParagraphUnit]:
    title = document.document.title or ""
    groups = _group(_placed_blocks(document, settings), settings)
    units = [
        ParagraphUnit(
            unit_id=f"para:{index:04d}",
            blocks=[p.block for p in group],
            pages=sorted({p.page for p in group}),
            heading_path=group[0].heading_path,
            title=title,
        )
        for index, group in enumerate(groups, start=1)
    ]
    for index, unit in enumerate(units):
        if index > 0:
            unit.previous_text = units[index - 1].text[-context_chars:]
        if index + 1 < len(units):
            unit.next_text = units[index + 1].text[:context_chars]
    return units
