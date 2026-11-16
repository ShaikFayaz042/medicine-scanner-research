"""Turn classifier context paragraphs and tables into classification units."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from idp.schemas.classification_context import (
    ClassificationContext,
    ParagraphContext,
    SourceReference,
    TableContext,
)
from idp.schemas.taxonomy import UnitSettings

_SPACES = re.compile(r"\s+")


def collapse(text: str) -> str:
    return _SPACES.sub(" ", text or "").strip()


def _unique_refs(references: list[SourceReference]) -> list[SourceReference]:
    unique: dict[tuple, SourceReference] = {}
    for reference in references:
        key = (reference.page, reference.artifact, reference.item_id, reference.method)
        unique[key] = reference
    return list(unique.values())


@dataclass
class TableUnit:
    unit_id: str
    table: TableContext
    context: str
    title: str

    @property
    def pages(self) -> List[int]:
        return self.table.pages

    @property
    def header(self) -> List[str]:
        return self.table.headers

    @property
    def source_refs(self) -> List[SourceReference]:
        return self.table.source_refs

    @property
    def heading_path(self) -> List[str]:
        return []

    def header_candidates(self, body_rows: int = 3) -> List[tuple]:
        """Use sampled rows as header candidates when extraction found no header."""
        if self.header:
            return [("header_rows", self.header)]
        return [
            (f"body_row_{index}", [collapse(cell) for cell in row])
            for index, row in enumerate(self.table.sample_rows[:body_rows])
        ]

    def body_text(self, max_rows: Optional[int] = None) -> str:
        rows = self.table.sample_rows
        if max_rows is not None:
            rows = rows[:max_rows]
        return "\n".join(" | ".join(collapse(cell) for cell in row) for row in rows)

    @property
    def text(self) -> str:
        return "\n".join(filter(None, [" | ".join(self.header), self.body_text()]))


@dataclass
class ParagraphUnit:
    unit_id: str
    paragraphs: List[ParagraphContext]
    pages: List[int]
    heading_path: List[str]
    title: str
    previous_text: str = ""
    next_text: str = ""

    @property
    def context_ids(self) -> List[str]:
        return [paragraph.id for paragraph in self.paragraphs]

    @property
    def source_refs(self) -> List[SourceReference]:
        return _unique_refs([
            reference for paragraph in self.paragraphs for reference in paragraph.source_refs
        ])

    @property
    def text(self) -> str:
        return "\n".join(collapse(paragraph.content) for paragraph in self.paragraphs)

    @property
    def body_chars(self) -> int:
        return sum(len(collapse(paragraph.content)) for paragraph in self.paragraphs)

    @property
    def context(self) -> str:
        return " / ".join([self.title, *self.heading_path]).strip(" /")


def table_units(document: ClassificationContext) -> List[TableUnit]:
    title = document.source_metadata.get("title", "")
    units = []
    for table in document.tables:
        section_rows = [
            collapse(next(cell for cell in row if collapse(cell)))
            for row in table.sample_rows[:3]
            if len([cell for cell in row if collapse(cell)]) == 1 and len(row) > 1
        ]
        context = " / ".join(filter(None, [title, *section_rows]))
        units.append(TableUnit(
            unit_id=f"table:{table.id}",
            table=table,
            context=context,
            title=title,
        ))
    return units


def _paragraph_groups(
    paragraphs: List[ParagraphContext], settings: UnitSettings,
) -> List[List[ParagraphContext]]:
    groups: List[List[ParagraphContext]] = []
    current: List[ParagraphContext] = []
    size = 0

    for paragraph in paragraphs:
        length = len(collapse(paragraph.content))
        if settings.paragraph_strategy == "section":
            new_group = bool(current) and (
                paragraph.section_path != current[-1].section_path
                or size + length > settings.max_unit_chars
            )
        else:
            new_group = bool(current) and size + length > settings.chunk_target_chars
        if new_group:
            groups.append(current)
            current, size = [], 0
        current.append(paragraph)
        size += length

    if current:
        groups.append(current)

    merged: List[List[ParagraphContext]] = []
    pending: List[ParagraphContext] = []
    for group in groups:
        group = pending + group
        pending = []
        body_chars = sum(len(collapse(paragraph.content)) for paragraph in group)
        if body_chars < settings.min_record_chars:
            pending = group
            continue
        merged.append(group)
    if pending:
        if merged:
            merged[-1].extend(pending)
        else:
            merged.append(pending)
    return merged


def paragraph_units(
    document: ClassificationContext, settings: UnitSettings, context_chars: int,
) -> List[ParagraphUnit]:
    title = document.source_metadata.get("title", "")
    groups = _paragraph_groups(document.paragraphs, settings)
    units = [
        ParagraphUnit(
            unit_id=f"para:{index:04d}",
            paragraphs=group,
            pages=sorted({page for paragraph in group for page in paragraph.pages}),
            heading_path=list(group[0].section_path),
            title=title,
        )
        for index, group in enumerate(groups, start=1)
    ]
    for index, unit in enumerate(units):
        if index > 0:
            unit.previous_text = units[index - 1].text[-context_chars:] if context_chars else ""
        if index + 1 < len(units) and context_chars:
            unit.next_text = units[index + 1].text[:context_chars]
    return units
