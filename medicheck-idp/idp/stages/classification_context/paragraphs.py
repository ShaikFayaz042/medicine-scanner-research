"""Paragraph extraction and chunking logic."""
from __future__ import annotations

import re
import textwrap
from typing import Sequence

from idp.schemas.classification_context import (
    DocumentAnchor,
    DocumentAnchors,
    ParagraphContext,
    SourceReference,
)
from idp.schemas.extraction import Item

MAX_CHUNK_CHARS = 2500

_SPACE = re.compile(r"\s+")
_PAGE_NUMBER = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^\s*#{1,6}\s*([^\n]+)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")

_DATE = re.compile(
    r"\b(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|"
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]* \d{1,2},? \d{4})\b",
    re.IGNORECASE,
)
_REFERENCE_PATTERNS = (
    re.compile(r"\bRef(?:erence)?\s*:?\s*([A-Za-z0-9./-]+)", re.IGNORECASE),
    re.compile(r"\bFile\s*No\.?\s*:?\s*([A-Za-z0-9./-]+)", re.IGNORECASE),
    re.compile(r"\b([A-Za-z]+/[A-Za-z]+/\d+/\d+(?:-[A-Za-z]+)?)\b"),
)

def _normalize_cell(value: str) -> str:
    return _SPACE.sub(" ", value).strip().casefold()

def _plain_markdown_line(line: str) -> str:
    line = re.sub(r"</?mark>", "", line, flags=re.IGNORECASE)
    line = re.sub(r"</?u\s*>", "", line, flags=re.IGNORECASE)
    line = re.sub(r"^\s*>\s?", "", line)
    line = re.sub(r"^\s*#{1,6}\s+", "", line)
    line = re.sub(r"[*_`]", "", line)
    return _SPACE.sub(" ", line).strip()

def _table_line_indices(lines: list[str]) -> set[int]:
    indices: set[int] = set()
    for index, line in enumerate(lines):
        if not _TABLE_SEPARATOR.fullmatch(line):
            continue
        start, end = index, index
        while start > 0 and "|" in lines[start - 1]:
            start -= 1
        while end + 1 < len(lines) and "|" in lines[end + 1]:
            end += 1
        indices.update(range(start, end + 1))
    return indices

def _is_bold_short(item: Item) -> bool:
    return (
        item.type == "text_line"
        and bool(item.text)
        and len(item.text) < 80
        and any(segment.bold for segment in item.segments)
    )

def _heading_candidates(items: Sequence[Item]) -> set[str]:
    """Generic visual heading detection (Bold, Short)."""
    candidates = set()
    for item in items:
        if not _is_bold_short(item):
            continue
        text = _SPACE.sub(" ", item.text or "").strip()
        if len(text) >= 80 or text.endswith("."):
            continue
        candidates.add(_normalize_cell(text))
    return candidates

def _paragraph_bbox(
    source_text: str,
    items: Sequence[Item],
    width: float,
    height: float,
) -> tuple[tuple[float, float, float, float] | None, list[str]]:
    """Find the bounding box and source item IDs that make up this chunk."""
    if not source_text or not items or width <= 0 or height <= 0:
        return None, []
    normalized_chunk = _normalize_cell(source_text)
    matched_items = []
    for item in items:
        if item.type != "text_line" or not item.text:
            continue
        if _normalize_cell(item.text) in normalized_chunk:
            matched_items.append(item)
    if not matched_items:
        return None, []
    x0 = min(item.bbox[0] for item in matched_items) * width
    y0 = min(item.bbox[1] for item in matched_items) * height
    x1 = max(item.bbox[2] for item in matched_items) * width
    y1 = max(item.bbox[3] for item in matched_items) * height
    return (x0, y0, x1, y1), [item.item_id for item in matched_items]

def extract_paragraphs(
    markdown: str,
    page_number: int,
    artifact: str,
    source_method: str,
    start_index: int,
    items: Sequence[Item],
    page_width: float,
    page_height: float,
) -> tuple[list[ParagraphContext], int]:
    """Split markdown into structure-aware blocks and create ParagraphContexts."""
    
    # 1. Filter out tables and page numbers
    lines = markdown.splitlines()
    table_indices = _table_line_indices(lines)
    clean_markdown_lines = []
    excluded_count = 0
    
    for i, line in enumerate(lines):
        if i in table_indices:
            continue
        if _PAGE_NUMBER.fullmatch(line.strip()):
            excluded_count += 1
            continue
        clean_markdown_lines.append(line)
        
    clean_markdown = "\n".join(clean_markdown_lines)
    
    # 2. Split into blocks by blank lines
    blocks = [b.strip() for b in re.split(r"\n[ \t]*\n+", clean_markdown) if b.strip()]
    
    # 3. Detect headings
    heading_candidates = _heading_candidates(items)
    normalized_markdown = _normalize_cell(
        " ".join(_plain_markdown_line(line) for line in markdown.splitlines())
    )
    missing_headings = sorted(
        (
            (item.text.strip(), item.bbox[1])
            for item in items
            if _is_bold_short(item)
            and _normalize_cell(item.text or "") in heading_candidates
            and _normalize_cell(item.text or "") not in normalized_markdown
        ),
        key=lambda heading: heading[1],
    )

    chunks = []
    current_section = []
    current_text_parts = []
    next_missing_heading = 0
    
    def flush_chunk():
        if not current_text_parts:
            return
        text = " ".join(current_text_parts).strip()
        if not text:
            return
            
        chunk_id = f"C{start_index + len(chunks):04d}"
        bbox, matched_item_ids = _paragraph_bbox(text, items, page_width, page_height)
        
        date_match = _DATE.search(text)
        date_candidates = [date_match.group(1)] if date_match else []
        file_no_candidates = [
            m.group(1) for pattern in _REFERENCE_PATTERNS 
            if (m := pattern.search(text))
        ][:1]

        chunks.append(ParagraphContext(
            id=chunk_id,
            pages=[page_number],
            section=current_section[-1] if current_section else None,
            section_path=current_section.copy(),
            content=text,
            bbox=bbox,
            source_refs=[SourceReference(
                page=page_number,
                artifact=artifact,
                item_id=",".join(matched_item_ids) or None,
                method=source_method,
                bbox=bbox,
            )],
            date_candidates=date_candidates,
            file_no_candidates=file_no_candidates,
        ))
        current_text_parts.clear()

    # 4. Build chunks
    for block in blocks:
        plain_text = _plain_markdown_line(block)
        if not plain_text:
            continue

        markdown_heading = _HEADING.match(block)
        if markdown_heading:
            flush_chunk()
            heading = _plain_markdown_line(markdown_heading.group(1))
            current_section = [heading] if heading else []
            block = block[markdown_heading.end():].strip()
            if not block:
                continue
            plain_text = _plain_markdown_line(block)
            if not plain_text:
                continue

        normalized_block = _normalize_cell(plain_text)
        block_items = [
            item for item in items
            if item.type == "text_line"
            and item.text
            and _normalize_cell(item.text) in normalized_block
        ]
        block_y = min((item.bbox[1] for item in block_items), default=None)
        while (
            block_y is not None
            and next_missing_heading < len(missing_headings)
            and missing_headings[next_missing_heading][1] < block_y
        ):
            flush_chunk()
            current_section = [missing_headings[next_missing_heading][0]]
            next_missing_heading += 1
            
        # If block is a bold visual heading
        if normalized_block in heading_candidates:
            flush_chunk()
            current_section = [plain_text] # Reset section path (assuming 1 level for simplicity)
            continue
            
        # Check size limit
        current_len = sum(len(t) for t in current_text_parts)
        if current_text_parts and current_len + len(plain_text) > MAX_CHUNK_CHARS:
            flush_chunk()
            
        current_text_parts.append(plain_text)
        
    flush_chunk()
    return chunks, excluded_count

def build_document_anchors(paragraphs: Sequence[ParagraphContext]) -> DocumentAnchors:
    """Extract document-level metadata from the first available chunks."""
    if not paragraphs:
        return DocumentAnchors()

    # Search for date and file number across the first 3 chunks (covers letterhead + subject)
    date_anchor = None
    file_anchor = None
    
    for p in paragraphs[:3]:
        search_text = p.content + " " + " ".join(p.section_path)
        if not date_anchor:
            date_match = _DATE.search(search_text)
            if date_match:
                date_anchor = DocumentAnchor(
                    value=date_match.group(1),
                    paragraph_ids=[p.id],
                    evidence=f"date text in {p.id}",
                )
        if not file_anchor:
            file_match = next(
                (match for pattern in _REFERENCE_PATTERNS if (match := pattern.search(search_text))),
                None,
            )
            if file_match:
                file_anchor = DocumentAnchor(
                    value=file_match.group(1),
                    paragraph_ids=[p.id],
                    evidence=f"reference text in {p.id}",
                )
                
    return DocumentAnchors(date=date_anchor, file_no=file_anchor)