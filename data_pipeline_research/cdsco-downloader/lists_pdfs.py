#!/usr/bin/env python3
"""
Generate a manifest of all downloaded PDFs.

Walks the root `downloads/` folder, finds every *.pdf file, and writes
its exact filename into `downloads/pdf_list.txt`, grouped by source
folder, with per-source and grand total counts.

Usage:
    python cdsco-downloader/list_pdfs.py
    python cdsco-downloader/list_pdfs.py --output downloads/my_list.txt
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Make cdsco_utils importable when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdsco_utils as cu  # noqa: E402


def collect_pdfs(root: Path) -> dict[str, list[str]]:
    """
    Return { source_folder_name: [pdf_filename, ...] }
    sorted alphabetically inside each source.
    """
    result: dict[str, list[str]] = {}

    if not root.exists():
        raise SystemExit(f"[!] Downloads root not found: {root}")

    # Each immediate subdirectory of downloads/ is a "source"
    for source_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        pdfs = sorted(
            f.name
            for f in source_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".pdf"
        )
        result[source_dir.name] = pdfs

    return result


def write_manifest(
    sources: dict[str, list[str]],
    out_path: Path,
    root: Path,
) -> None:
    """Write the grouped manifest to a text file."""
    total = sum(len(v) for v in sources.values())

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("CDSCO / IPC — Downloaded PDF Manifest")
    lines.append(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Root      : {root}")
    lines.append(f"Total PDFs: {total}")
    lines.append("=" * 72)
    lines.append("")

    # Summary block
    lines.append("SUMMARY BY SOURCE")
    lines.append("-" * 72)
    for source, pdfs in sources.items():
        lines.append(f"  {source:<20} {len(pdfs):>5} files")
    lines.append("-" * 72)
    lines.append(f"  {'TOTAL':<20} {total:>5} files")
    lines.append("")
    lines.append("")

    # Detailed listing
    lines.append("DETAILED LISTING (exact filenames)")
    lines.append("=" * 72)

    for source, pdfs in sources.items():
        lines.append("")
        lines.append(f"### {source}  ({len(pdfs)} files)")
        lines.append("-" * 72)
        if not pdfs:
            lines.append("  (no PDFs found)")
            continue
        for i, name in enumerate(pdfs, start=1):
            lines.append(f"  {i:>4}. {name}")

    lines.append("")
    lines.append("=" * 72)
    lines.append(f"END OF MANIFEST — {total} PDF(s) across {len(sources)} source(s)")
    lines.append("=" * 72)
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List all downloaded PDFs into a text manifest."
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output path (default: downloads/pdf_list.txt)",
    )
    parser.add_argument(
        "--names-only",
        action="store_true",
        help="Write only filenames, one per line, no grouping or summary.",
    )
    args = parser.parse_args()

    root: Path = cu.DOWNLOADS_ROOT
    out_path = (
        Path(args.output).resolve()
        if args.output
        else root / "pdf_list.txt"
    )

    sources = collect_pdfs(root)
    total = sum(len(v) for v in sources.values())

    if args.names_only:
        # Flat, one-filename-per-line output
        flat = sorted(
            name for pdfs in sources.values() for name in pdfs
        )
        out_path.write_text("\n".join(flat) + "\n", encoding="utf-8")
    else:
        write_manifest(sources, out_path, root)

    # Console summary
    print()
    print(f"[+] Manifest written : {out_path}")
    print(f"[+] Total PDFs       : {total}")
    for source, pdfs in sources.items():
        print(f"      {source:<20} {len(pdfs):>5} files")


if __name__ == "__main__":
    main()