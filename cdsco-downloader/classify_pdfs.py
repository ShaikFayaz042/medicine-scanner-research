#!/usr/bin/env python3
"""
Classify downloaded PDFs into important/ and unimportant/ subfolders
based on a classification CSV.

CSV columns (case-insensitive, extra spaces tolerated):
    File Name, Classification, webpage source

Classification values: "Important" | "Unimportant"
"webpage source" matches the source folder under downloads/ (e.g. "alerts").

Behaviour:
    downloads/<source>/<file>.pdf
        → downloads/<source>/important/<file>.pdf     (if CSV says Important)
        → downloads/<source>/unimportant/<file>.pdf   (if CSV says Unimportant)

    Non-PDF files (_metadata.json, etc.) are left at the source root.
    Idempotent: safe to re-run. Files already in the right subfolder are skipped.

Usage:
    python cdsco-downloader/classify_pdfs.py path/to/Medicine_PDF_Classification.csv
    python cdsco-downloader/classify_pdfs.py path/to/classify.csv --dry-run
    python cdsco-downloader/classify_pdfs.py path/to/classify.csv --report missing.txt
"""

import argparse
import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# Allow importing cdsco_utils from the same directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdsco_utils as cu  # noqa: E402


VALID_CLASSIFICATIONS = {"important", "unimportant"}


def normalise(s: str) -> str:
    """Strip, collapse whitespace. Case preserved for filenames."""
    return " ".join(s.split()).strip()


def load_csv(csv_path: Path) -> list[dict]:
    """Read classification CSV → list of dicts."""
    if not csv_path.exists():
        raise SystemExit(f"[!] CSV not found: {csv_path}")

    rows: list[dict] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        # Normalise header names (strip, lower)
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]

        required = {"file name", "classification", "webpage source"}
        missing = required - set(reader.fieldnames)
        if missing:
            raise SystemExit(
                f"[!] CSV missing required column(s): {sorted(missing)}\n"
                f"    Found columns: {reader.fieldnames}"
            )

        for i, raw in enumerate(reader, start=2):  # row 2 = first data row
            fname = normalise(raw.get("file name", ""))
            classification = normalise(
                raw.get("classification", "")
            ).lower()
            source = normalise(raw.get("webpage source", "")).lower()

            if not fname:
                continue
            if classification not in VALID_CLASSIFICATIONS:
                print(
                    f"[!] Row {i}: unknown classification "
                    f"{classification!r} — skipping ({fname})"
                )
                continue
            if not source:
                print(
                    f"[!] Row {i}: missing webpage source — skipping ({fname})"
                )
                continue

            rows.append({
                "filename": fname,
                "classification": classification,
                "source": source,
                "row": i,
            })
    return rows


def classify(
    downloads_root: Path,
    rows: list[dict],
    dry_run: bool = False,
) -> dict:
    """Move PDFs into important/ or unimportant/ subfolders."""
    stats = {
        "moved": 0,
        "already_in_place": 0,
        "missing_on_disk": 0,
        "source_folder_missing": 0,
    }
    missing_details: list[str] = []
    source_usage: dict[str, dict[str, int]] = defaultdict(
        lambda: {"important": 0, "unimportant": 0}
    )

    # Pre-create subfolders only for sources we actually touch
    touched_sources = {r["source"] for r in rows}

    for r in rows:
        source = r["source"]
        fname = r["filename"]
        classification = r["classification"]

        source_dir = downloads_root / source
        if not source_dir.is_dir():
            stats["source_folder_missing"] += 1
            missing_details.append(f"SOURCE MISSING: {source}/{fname}")
            continue

        # Possible current locations
        src_flat = source_dir / fname
        src_important = source_dir / "important" / fname
        src_unimportant = source_dir / "unimportant" / fname

        dest_dir = source_dir / classification
        dest = dest_dir / fname

        # Where is the file now?
        if src_important.exists():
            current = src_important
        elif src_unimportant.exists():
            current = src_unimportant
        elif src_flat.exists():
            current = src_flat
        else:
            stats["missing_on_disk"] += 1
            missing_details.append(f"MISSING: {source}/{fname}")
            continue

        # Already in the right place?
        if current == dest:
            stats["already_in_place"] += 1
            source_usage[source][classification] += 1
            continue

        # Move
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(dest))
        stats["moved"] += 1
        source_usage[source][classification] += 1
        print(
            f"  {'[DRY] ' if dry_run else ''}"
            f"{source}/{current.parent.name if current.parent != source_dir else ''}"
            f"{'' if current.parent == source_dir else '/'}"
            f"{fname}  →  {classification}/"
        )

    # Create empty subfolders so the layout is complete
    if not dry_run:
        for source in touched_sources:
            sdir = downloads_root / source
            if sdir.is_dir():
                (sdir / "important").mkdir(exist_ok=True)
                (sdir / "unimportant").mkdir(exist_ok=True)

    return {
        "stats": stats,
        "missing_details": missing_details,
        "source_usage": dict(source_usage),
    }


def write_report(result: dict, out_path: Path) -> None:
    lines = []
    lines.append("=" * 72)
    lines.append("PDF Classification Report")
    lines.append("=" * 72)
    lines.append("")

    lines.append("STATS")
    lines.append("-" * 72)
    for key, val in result["stats"].items():
        lines.append(f"  {key:<25} {val}")

    lines.append("")
    lines.append("PER-SOURCE COUNTS")
    lines.append("-" * 72)
    for source, counts in sorted(result["source_usage"].items()):
        lines.append(
            f"  {source:<20} "
            f"important={counts['important']:>5}  "
            f"unimportant={counts['unimportant']:>5}"
        )

    if result["missing_details"]:
        lines.append("")
        lines.append("NOT FOUND / PROBLEM ROWS")
        lines.append("-" * 72)
        lines.extend(f"  {m}" for m in result["missing_details"])

    lines.append("")
    lines.append("=" * 72)

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split downloaded PDFs into important/ and unimportant/."
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to the classification CSV.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without moving any files.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path to write a text report (e.g. classify_report.txt).",
    )
    args = parser.parse_args()

    downloads_root: Path = cu.DOWNLOADS_ROOT
    if not downloads_root.is_dir():
        raise SystemExit(f"[!] Downloads root not found: {downloads_root}")

    print(f"[*] Downloads root : {downloads_root}")
    print(f"[*] Classification : {args.csv_path}")
    print(f"[*] Dry run        : {args.dry_run}")
    print()

    rows = load_csv(args.csv_path)
    print(f"[*] Loaded {len(rows)} classification rows")
    print()

    result = classify(downloads_root, rows, dry_run=args.dry_run)

    print()
    print("=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for key, val in result["stats"].items():
        print(f"  {key:<25} {val}")

    print()
    print("PER-SOURCE")
    print("-" * 72)
    for source, counts in sorted(result["source_usage"].items()):
        print(
            f"  {source:<20} "
            f"important={counts['important']:>5}  "
            f"unimportant={counts['unimportant']:>5}"
        )

    if result["missing_details"]:
        print()
        print(f"[!] {len(result['missing_details'])} rows could not be located:")
        for m in result["missing_details"][:20]:
            print(f"    {m}")
        if len(result["missing_details"]) > 20:
            print(f"    … and {len(result['missing_details']) - 20} more")

    if args.report:
        write_report(result, args.report)
        print(f"\n[+] Report written: {args.report}")


if __name__ == "__main__":
    main()