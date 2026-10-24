#!/usr/bin/env python3
import argparse
import re
import unicodedata
from pathlib import Path

import pymupdf4llm
from langdetect import DetectorFactory, LangDetectException, detect

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "paragraph_files"
DEFAULT_OUTPUT = SCRIPT_DIR / "pymupdf4llm_all"

ASCII_LETTER_RATIO_THRESHOLD = 0.85
LANGUAGE_DETECTION_MIN_LETTERS = 80
DetectorFactory.seed = 0


def keep_english_text(text: str) -> str:
    """Keep English blocks and remove text written in other scripts."""
    filtered_blocks = []
    for block in re.split(r"\n\s*\n", text):
        filtered_lines = []
        for line in block.splitlines():
            letters = [character for character in line if character.isalpha()]
            if letters:
                ascii_ratio = sum(character.isascii() for character in letters) / len(letters)
                if ascii_ratio < ASCII_LETTER_RATIO_THRESHOLD:
                    continue

            ascii_line = unicodedata.normalize("NFKD", line).encode("ascii", "ignore").decode("ascii")
            if ascii_line.strip():
                filtered_lines.append(ascii_line)

        filtered_block = "\n".join(filtered_lines)
        letter_count = sum(character.isalpha() for character in filtered_block)
        if letter_count >= LANGUAGE_DETECTION_MIN_LETTERS:
            try:
                if detect(filtered_block) != "en":
                    continue
            except LangDetectException:
                pass

        if filtered_block:
            filtered_blocks.append(filtered_block)

    return "\n\n".join(filtered_blocks)


def process_pdf(pdf_path: Path, output_dir: Path, use_ocr: bool = False) -> dict:
    """Extract Markdown and plain text from one PDF using PyMuPDF4LLM."""
    try:
        md_text = keep_english_text(
            pymupdf4llm.to_markdown(str(pdf_path), use_ocr=use_ocr)
        )
        md_file = output_dir / f"{pdf_path.stem}.md"
        md_file.write_text(md_text, encoding="utf-8")

        txt_text = keep_english_text(
            pymupdf4llm.to_text(str(pdf_path), use_ocr=use_ocr)
        )
        txt_file = output_dir / f"{pdf_path.stem}.txt"
        txt_file.write_text(txt_text, encoding="utf-8")

        return {
            "file": pdf_path.name,
            "status": "SUCCESS",
            "md_size": len(md_text),
            "txt_size": len(txt_text),
        }
    except Exception as exc:
        return {"file": pdf_path.name, "status": "FAILED", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract PDFs to Markdown and text using PyMuPDF4LLM."
    )
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT,
        help=f"PDF file or folder containing PDFs (default: {DEFAULT_INPUT})."
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Folder for Markdown and text outputs (default: {DEFAULT_OUTPUT})."
    )
    parser.add_argument(
        "--ocr", action="store_true", help="Enable OCR for scanned/image-based pages."
    )
    args = parser.parse_args()

    if args.input.is_file():
        if args.input.suffix.casefold() != ".pdf":
            parser.error(f"Input file is not a PDF: {args.input}")
        pdf_files = [args.input]
    elif args.input.is_dir():
        pdf_files = sorted(args.input.rglob("*.pdf"))
    else:
        parser.error(f"Input file or folder does not exist: {args.input}")

    if not pdf_files:
        print("No PDF files found in the input directory.")
        return 0

    args.output.mkdir(parents=True, exist_ok=True)
    print(f"Found {len(pdf_files)} PDF file(s). Starting extraction...\n")

    results = []
    for idx, pdf_file in enumerate(pdf_files, start=1):
        print(f"[{idx}/{len(pdf_files)}] Processing: {pdf_file.name}")
        output_dir = args.output
        if args.input.is_dir():
            output_dir = args.output / pdf_file.relative_to(args.input).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        result = process_pdf(pdf_file, output_dir, use_ocr=args.ocr)
        results.append(result)

        if result["status"] == "SUCCESS":
            print(
                f"  -> SUCCESS (MD: {result['md_size']} chars | "
                f"TXT: {result['txt_size']} chars)"
            )
        else:
            print(f"  -> FAILED: {result['error']}")

    success = sum(1 for result in results if result["status"] == "SUCCESS")
    failed = len(results) - success
    print("\n--- Processing Complete ---")
    print(f"Success: {success}")
    print(f"Failed:  {failed}")
    print(f"Output directory: {args.output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
