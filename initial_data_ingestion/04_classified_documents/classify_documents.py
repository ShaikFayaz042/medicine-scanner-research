"""Copy downloaded PDFs into their AI-assigned classification folders."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from collections import defaultdict
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOWNLOADS = PIPELINE_ROOT / "01_downloads"
CLASSIFICATION_DIR = PIPELINE_ROOT / "03_ai_classification"
OUTPUT_ROOT = PIPELINE_ROOT / "04_classified_documents"
VALID_CATEGORIES = ("process_queue", "junk", "manual_review")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("classify_documents")


def read_json_classifications(path: Path) -> dict[str, str]:
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, list):
		raise ValueError("classification.json must contain a JSON array")

	classifications = {}
	for record in data:
		if not isinstance(record, dict):
			raise ValueError("Every JSON classification must be an object")
		filename = record.get("filename")
		category = record.get("category")
		if not isinstance(filename, str) or not filename.lower().endswith(".pdf"):
			raise ValueError(f"Invalid PDF filename in classification.json: {filename!r}")
		if category not in VALID_CATEGORIES:
			raise ValueError(f"Invalid category for {filename}: {category!r}")
		if filename in classifications:
			raise ValueError(f"Duplicate filename in classification.json: {filename}")
		classifications[filename] = category
	return classifications


def read_text_classifications(path: Path) -> dict[str, str]:
	headings = {
		"[PROCESS_QUEUE]": "process_queue",
		"[JUNK]": "junk",
		"[MANUAL_REVIEW]": "manual_review",
	}
	classifications = {}
	category = None
	for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
		line = raw_line.strip()
		if not line:
			continue
		if line in headings:
			category = headings[line]
			continue
		if category is None:
			raise ValueError(f"Filename before a category heading on line {line_number}")
		if not line.lower().endswith(".pdf"):
			raise ValueError(f"Expected a PDF filename on line {line_number}: {line}")
		if line in classifications:
			raise ValueError(f"Duplicate filename in classification.txt: {line}")
		classifications[line] = category
	return classifications


def find_pdfs(downloads: Path) -> dict[str, list[Path]]:
	matches = defaultdict(list)
	for pdf_path in downloads.rglob("*.pdf"):
		matches[pdf_path.name].append(pdf_path)
	return matches


def main() -> int:
	parser = argparse.ArgumentParser(description="Copy PDFs according to AI classifications")
	parser.add_argument("--downloads", type=Path, default=DEFAULT_DOWNLOADS, help="PDF downloads directory")
	parser.add_argument("--json", type=Path, default=CLASSIFICATION_DIR / "classification.json", help="Detailed JSON classifications")
	parser.add_argument("--text", type=Path, default=CLASSIFICATION_DIR / "classification.txt", help="Simple text classifications")
	parser.add_argument("--output", type=Path, default=OUTPUT_ROOT, help="Classification output directory")
	parser.add_argument("--dry-run", action="store_true", help="Validate and report without copying PDFs")
	args = parser.parse_args()

	for path in (args.downloads, args.json, args.text):
		if not path.exists():
			parser.error(f"Path does not exist: {path}")

	json_map = read_json_classifications(args.json)
	text_map = read_text_classifications(args.text)
	if json_map != text_map:
		json_only = sorted(set(json_map) - set(text_map))
		text_only = sorted(set(text_map) - set(json_map))
		category_mismatches = sorted(name for name in set(json_map) & set(text_map) if json_map[name] != text_map[name])
		raise ValueError(f"JSON/TXT mismatch; JSON-only={json_only}, TXT-only={text_only}, category-mismatches={category_mismatches}")

	pdfs = find_pdfs(args.downloads)
	missing = sorted(filename for filename in json_map if filename not in pdfs)
	duplicates = {filename: paths for filename, paths in pdfs.items() if filename in json_map and len(paths) > 1}
	if missing:
		log.error("Missing PDFs: %d", len(missing))
		for filename in missing[:20]:
			log.error("  %s", filename)
	if duplicates:
		raise ValueError("Duplicate source PDFs found: " + ", ".join(sorted(duplicates)))
	if missing:
		return 1

	copied = 0
	skipped = 0
	manifest = []
	for filename, category in sorted(json_map.items()):
		source = pdfs[filename][0]
		relative_source = source.relative_to(args.downloads)
		destination = args.output / category / relative_source
		if destination.exists():
			skipped += 1
			status = "EXISTING"
		elif args.dry_run:
			status = "PLANNED"
		else:
			destination.parent.mkdir(parents=True, exist_ok=True)
			shutil.copy2(source, destination)
			copied += 1
			status = "COPIED"
		manifest.append({"filename": filename, "category": category, "source": str(source), "destination": str(destination), "status": status})

	if not args.dry_run:
		manifest_path = args.output / "_classification_manifest.json"
		manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
		log.info("Manifest written: %s", manifest_path)
	log.info("Classifications: %d | Copied: %d | Existing: %d | Dry-run: %s", len(json_map), copied, skipped, args.dry_run)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
