#!/usr/bin/env python3
"""Extract text from text PDFs and package scanned/mixed PDFs for Kaggle OCR."""

from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import fitz

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TYPE_ROOT = PIPELINE_ROOT / "05_type_classification"
DEFAULT_OUTPUT_ROOT = PIPELINE_ROOT / "07_raw_extraction_output"
VALID_CATEGORIES = ("text", "scanned", "mixed")


def collect_pdfs(root: Path, category: str) -> list[Path]:
    folder = root / category
    if not folder.exists():
        return []
    return sorted(folder.rglob("*.pdf"))


def extract_text_from_pdf(pdf_path: Path) -> str:
    text_parts: list[str] = []
    doc = fitz.open(pdf_path)
    try:
        for page_number, page in enumerate(doc, start=1):
            page_text = page.get_text("text").strip()
            if not page_text:
                continue
            text_parts.append(f"--- Page {page_number} ---\n{page_text}")
    finally:
        doc.close()
    return "\n\n".join(text_parts)


def write_text_output(pdf_path: Path, output_dir: Path, dry_run: bool) -> Path:
    target = output_dir / "text" / f"{pdf_path.stem}.txt"
    if dry_run:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    text = extract_text_from_pdf(pdf_path)
    target.write_text(text, encoding="utf-8")
    return target


def bundle_for_kaggle(pdf_paths: list[Path], output_dir: Path, category: str, dry_run: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / category / f"{category}_for_kaggle.zip"
    if dry_run:
        return zip_path
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for pdf_path in pdf_paths:
            arcname = pdf_path.relative_to(pdf_path.parents[0].parent.parent if False else pdf_path.parent)
            try:
                arcname = pdf_path.relative_to(pdf_path.parents[1])
            except ValueError:
                arcname = pdf_path.name
            zf.write(pdf_path, arcname=arcname.as_posix())
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract text PDFs locally and bundle scanned or mixed PDFs for Kaggle OCR processing."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_TYPE_ROOT,
        help="Directory containing the stage-5 type buckets (text, scanned, mixed).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory for the raw extraction outputs and Kaggle bundles.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview the outputs without writing files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing extracted text files and zip bundles")
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"Input directory does not exist: {args.input}")

    output_root = args.output
    output_root.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(args.input),
        "output_root": str(output_root),
        "categories": {},
    }

    text_count = 0
    for pdf_path in collect_pdfs(args.input, "text"):
        target = output_root / "text" / f"{pdf_path.stem}.txt"
        if target.exists() and not args.force and not args.dry_run:
            text_count += 1
            continue
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(extract_text_from_pdf(pdf_path), encoding="utf-8")
        text_count += 1
        manifest["categories"].setdefault("text", {"files": []})["files"].append({
            "source": str(pdf_path),
            "target": str(target),
            "status": "PLANNED" if args.dry_run else "EXTRACTED",
        })

    for category in ("scanned", "mixed"):
        pdfs = collect_pdfs(args.input, category)
        bundle_path = output_root / category / f"{category}_for_kaggle.zip"
        if not args.dry_run and bundle_path.exists() and not args.force:
            bundle_status = "EXISTING"
        elif args.dry_run:
            bundle_status = "PLANNED"
        else:
            bundle_status = "BUNDLED"
            if not args.dry_run:
                bundle_path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                    for pdf_path in pdfs:
                        zf.write(pdf_path, arcname=pdf_path.name)
        manifest["categories"][category] = {
            "pdf_count": len(pdfs),
            "bundle": str(bundle_path),
            "status": bundle_status,
        }

    if not args.dry_run:
        manifest_path = output_root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    for category in VALID_CATEGORIES:
        pdf_count = len(collect_pdfs(args.input, category))
        print(f"{category}: {pdf_count} PDFs")

    print(f"Output root: {output_root}")
    if args.dry_run:
        print("Dry run only: no files were written.")
    else:
        print(f"Manifest: {output_root / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
