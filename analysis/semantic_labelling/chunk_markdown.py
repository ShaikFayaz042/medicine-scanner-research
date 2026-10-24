#!/usr/bin/env python3
"""Create structure-aware, size-bounded chunks from Markdown documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")


def split_blocks(markdown: str) -> list[str]:
    """Split Markdown at blank lines while keeping tables and lists intact."""
    return [
        block.strip()
        for block in re.split(r"\n[ \t]*\n+", markdown)
        if block.strip()
    ]


def heading_in_block(block: str) -> tuple[int, str] | None:
    lines = block.splitlines()
    if len(lines) != 1:
        return None
    match = HEADING.match(lines[0])
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def chunk_markdown(markdown: str, max_chars: int = 4000) -> list[dict[str, Any]]:
    """Group Markdown blocks under their heading context up to a soft size target."""
    if max_chars < 1:
        raise ValueError("max_chars must be a positive integer")

    chunks: list[dict[str, Any]] = []
    heading_stack: dict[int, str] = {}
    current_blocks: list[str] = []
    current_headings: list[str] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current_blocks, current_headings, current_chars
        if not current_blocks:
            return
        text = "\n\n".join(current_blocks)
        chunks.append(
            {
                "chunk_index": len(chunks),
                "heading_path": current_headings,
                "block_count": len(current_blocks),
                "char_count": len(text),
                "text": text,
            }
        )
        current_blocks = []
        current_headings = []
        current_chars = 0

    for block in split_blocks(markdown):
        heading = heading_in_block(block)
        if heading:
            level, title = heading
            if level <= 2:
                flush()
            for old_level in [value for value in heading_stack if value >= level]:
                del heading_stack[old_level]
            heading_stack[level] = title

        block_chars = len(block)
        separator_chars = 2 if current_blocks else 0
        if current_blocks and current_chars + separator_chars + block_chars > max_chars:
            flush()

        if not current_blocks:
            current_headings = [heading_stack[level] for level in sorted(heading_stack)]
        current_blocks.append(block)
        current_chars += (2 if len(current_blocks) > 1 else 0) + block_chars

        # Keep unusually long paragraphs or tables atomic, then start a fresh chunk.
        if current_chars >= max_chars:
            flush()

    flush()
    return chunks


def process_file(input_path: Path, output_path: Path, source_name: str, max_chars: int) -> int:
    markdown = input_path.read_text(encoding="utf-8")
    chunks = chunk_markdown(markdown, max_chars=max_chars)
    document_id = f"DOC_{hashlib.sha256(source_name.casefold().encode('utf-8')).hexdigest()[:12]}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as jsonl_file:
        for chunk in chunks:
            heading_path = chunk["heading_path"]
            record = {
                "document_id": document_id,
                "chunk_id": f"{document_id}_C{chunk['chunk_index']:04d}",
                "chunk_index": chunk["chunk_index"],
                "chunking_method": "markdown_structure",
                "max_chars": max_chars,
                "boundary_rules": [
                    "blank_line_blocks",
                    "flush_at_h1_h2",
                    "soft_character_limit",
                ],
                "unit_type": "markdown_section" if heading_path else "document_content",
                "source_file": source_name,
                "page_start": None,
                "page_end": None,
                "heading": heading_path[-1] if heading_path else None,
                "heading_path": heading_path,
                "block_count": chunk["block_count"],
                "char_count": chunk["char_count"],
                "text_markdown": chunk["text"],
            }
            jsonl_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(chunks)


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Group Markdown blocks into heading-aware chunks for downstream processing."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=script_dir / "pymupdf4llm_all",
        help="Markdown file or folder (default: pymupdf4llm_all).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=script_dir / "pymupdf4llm_chunks",
        help="Chunk JSONL output folder (default: pymupdf4llm_chunks).",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=4000,
        help="Soft target size per chunk in characters (default: 4000).",
    )
    args = parser.parse_args()

    if args.max_chars < 1:
        parser.error("--max-chars must be a positive integer")
    if args.input.is_file():
        if args.input.suffix.casefold() != ".md":
            parser.error(f"Input file is not Markdown: {args.input}")
        markdown_files = [(args.input, Path(args.input.name))]
    elif args.input.is_dir():
        markdown_files = [
            (path, path.relative_to(args.input))
            for path in sorted(args.input.rglob("*.md"))
        ]
    else:
        parser.error(f"Input file or folder does not exist: {args.input}")

    if not markdown_files:
        print(f"No Markdown files found in {args.input}")
        return 0

    total_chunks = 0
    failures = 0
    for index, (markdown_file, relative_path) in enumerate(markdown_files, start=1):
        output_path = (args.output / relative_path).with_suffix(".chunks.jsonl")
        try:
            count = process_file(
                markdown_file,
                output_path,
                relative_path.as_posix(),
                args.max_chars,
            )
            total_chunks += count
            print(f"[{index}/{len(markdown_files)}] {relative_path.as_posix()}: {count} chunks")
        except Exception as exc:
            failures += 1
            print(f"[{index}/{len(markdown_files)}] FAILED {relative_path.as_posix()}: {exc}")

    print(f"Processed: {len(markdown_files)}; chunks: {total_chunks}; failed: {failures}")
    print(f"Output directory: {args.output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
