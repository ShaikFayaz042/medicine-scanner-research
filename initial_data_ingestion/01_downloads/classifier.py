"""Classify downloaded PDFs deterministically and write results to the manifest."""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from scripts.classifier_schema import complete_classifier_fields
from scripts.driver import classify_document, load_medicine_lexicons


def _priority_for(verdict: dict) -> str:
	if verdict.get("needs_review") or verdict.get("bucket") == "context-only":
		return "Review"
	if verdict.get("bucket") == "event-bearing":
		return "Important"
	return "Unimportant"


def _classify_pdf(path: Path, source: str, filename: str, products, ingredients) -> dict:
	import pymupdf

	with pymupdf.open(path) as pdf:
		pages = []
		for page in pdf:
			text = page.get_text("text") or ""
			page_type = "text" if text.strip() else "image" if page.get_images(full=True) else "empty"
			pages.append({"text": text, "type": page_type})

	text = "\n".join(page["text"] for page in pages)
	payload = {
		"doc_id": filename,
		"source_name": source,
		"pages": pages,
	}
	verdict = classify_document(payload, products, ingredients)
	verdict = complete_classifier_fields(verdict, text, filename=filename)

	if not text.strip():
		verdict["bucket"] = "needs_review"
		verdict["bucket_reason"] = "no_extractable_text_ocr_required"
		verdict["needs_review"] = True
		verdict["needs_review_reasons"] = [verdict["bucket_reason"]]
		verdict["is_relevant"] = False

	return verdict


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(
		description="Classify local PDFs deterministically and export the results to CSV."
	)
	parser.add_argument("--root", type=Path, default=ROOT, help="Folder containing source subfolders")
	parser.add_argument("--output", type=Path, help="CSV output path (default: <root>/source_files_classified.csv)")
	parser.add_argument("--limit", type=int, default=0, help="Process at most this many PDFs")
	parser.add_argument("--dry-run", action="store_true", help="Classify and report without writing a CSV")
	parser.add_argument("--overwrite", action="store_true", help="Replace the output CSV if it already exists")
	args = parser.parse_args(argv)

	if args.limit < 0:
		parser.error("--limit must be zero or greater")
	root = args.root.resolve()
	if not root.is_dir():
		parser.error(f"PDF source folder not found: {root}")
	output_path = args.output or root / "source_files_classified.csv"
	if not output_path.is_absolute():
		output_path = root / output_path
	output_path = output_path.resolve()
	if not args.dry_run and output_path.exists() and not args.overwrite:
		parser.error(f"Output already exists: {output_path}; choose another --output or pass --overwrite")
	if not args.dry_run and not output_path.parent.is_dir():
		parser.error(f"Output folder does not exist: {output_path.parent}")

	try:
		import pymupdf  # noqa: F401
	except ImportError as exc:
		parser.error(f"Missing dependency {exc.name!r}; install PyMuPDF to classify PDFs.")

	pdf_paths = sorted(
		(
			path for path in root.rglob("*")
			if path.is_file() and path.suffix.casefold() == ".pdf"
		),
		key=lambda path: path.relative_to(root).as_posix().casefold(),
	)
	if args.limit:
		pdf_paths = pdf_paths[:args.limit]
	products, ingredients = load_medicine_lexicons()

	fields = (
		"Source", "File Name", "Priority", "Classification",
		"Classification Reason", "Rule Matched", "Topical Score",
			"Document Type", "Structure", "Page Count", "Text Characters",
	)
	rows = []
	priorities = {"Important": 0, "Review": 0, "Unimportant": 0}
	failed = 0
	for index, file_path in enumerate(pdf_paths, start=1):
		source = file_path.parent.relative_to(root).as_posix()
		filename = file_path.name
		print(f"[{index}/{len(pdf_paths)}] {source}/{filename} ... ", end="", flush=True)
		try:
			verdict = _classify_pdf(file_path, source, filename, products, ingredients)
			classification = verdict["bucket"]
			reason = verdict["bucket_reason"]
			priority = _priority_for(verdict)
		except Exception as exc:
			verdict = {}
			classification = "error"
			reason = f"{type(exc).__name__}: {exc}"
			priority = "Review"
			failed += 1

		print(f"{priority} | {classification} | {reason}", flush=True)
		priorities[priority] += 1
		rows.append({
			"Source": source,
			"File Name": filename,
			"Priority": priority,
			"Classification": classification,
			"Classification Reason": reason,
			"Rule Matched": (verdict.get("deterministic") or {}).get("rule_matched"),
			"Topical Score": verdict.get("topical_score"),
			"Document Type": verdict.get("document_type"),
			"Structure": verdict.get("structure"),
			"Page Count": verdict.get("total_pages"),
			"Text Characters": verdict.get("total_text_chars"),
		})
	if not args.dry_run:
		temporary_path = None
		try:
			with tempfile.NamedTemporaryFile(
				mode="w", encoding="utf-8-sig", newline="", delete=False,
				dir=output_path.parent, prefix=f".{output_path.stem}.", suffix=".tmp",
			) as temporary_file:
				temporary_path = Path(temporary_file.name)
				writer = csv.DictWriter(temporary_file, fieldnames=fields)
				writer.writeheader()
				writer.writerows(rows)
			os.replace(temporary_path, output_path)
		finally:
			if temporary_path and temporary_path.exists():
				temporary_path.unlink()

	action = "Dry run complete" if args.dry_run else f"CSV written to {output_path}"
	print(f"{action}: {len(rows)} PDFs; {priorities}; {failed} errors")
	return 1 if failed else 0


if __name__ == "__main__":
	raise SystemExit(main())
