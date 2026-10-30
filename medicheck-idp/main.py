"""Local entry point:  python main.py path/to/file.pdf [--force]

Profiles one PDF, writes data/artifacts/<doc_id>/profile.json and prints a summary.
Later stages get chained here (and replaced by Step Functions on AWS).
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from idp.storage import artifacts
from idp.stages.profiler.service import run


def main() -> int:
    ap = argparse.ArgumentParser(description="MediCheck IDP: profile one PDF")
    ap.add_argument("pdf")
    ap.add_argument("--force", action="store_true", help="ignore the cached profile")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if not Path(args.pdf).is_file():
        print(f"ERROR: file not found: {args.pdf}")
        return 2                                 # usage error, distinct from a failed profile (1)
    prof = run(args.pdf, force=args.force)
    if prof.status == "failed":
        print(f"FAILED  {prof.file_name}: {prof.reason}")
        return 1
    print(f"{prof.file_name}  doc_id={prof.doc_id[:12]}  pages={prof.total_pages}  type={prof.doc_type}")
    print(f"page types: {prof.page_type_counts}")
    for b in prof.batches:
        head = ",".join(map(str, b.pages[:6])) + (",..." if len(b.pages) > 6 else "")
        print(f"  {b.engine:9s} {len(b.pages):4d} pages  {head}")
    flagged = {p.n: p.flags for p in prof.pages if p.flags}
    if flagged:
        print(f"flags: {flagged}")
    print(f"artifact: {artifacts.path('profile', prof.doc_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())