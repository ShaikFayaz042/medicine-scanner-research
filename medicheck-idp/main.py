"""Run the local PDF pipeline: manifest, profiler, extractor, and context builder."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from idp.stages.classification_context import run as run_context_builder
from idp.stages.extractor.service import run as run_extractor
from idp.stages.manifest import run as run_manifest
from idp.stages.profiler.service import run as run_profiler
from idp.storage import artifacts


def main() -> int:
    ap = argparse.ArgumentParser(
        description="MediCheck IDP: process one PDF through classification context",
    )
    ap.add_argument("pdf")
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-run profiler, extractor, and context builder instead of using cached artifacts",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"ERROR: file not found: {args.pdf}")
        return 2

    try:
        manifest = run_manifest(pdf_path)
        prof = run_profiler(pdf_path, force=args.force)
        if prof.status == "failed":
            print(f"FAILED  {prof.file_name}: {prof.reason}")
            return 1

        extraction = run_extractor(pdf_path, profile=prof, force=args.force)
        context = run_context_builder(
            pdf_path,
            force=args.force,
            profile=prof,
            extraction_index=extraction,
        )
    except (OSError, RuntimeError, ValueError) as error:
        logging.getLogger("idp.pipeline").error("pipeline failed: %s", error)
        return 1

    print(f"{prof.file_name}  doc_id={manifest.doc_id[:12]}  pages={prof.total_pages}  type={prof.doc_type}")
    print(f"page types: {prof.page_type_counts}")
    for batch in prof.batches:
        head = ",".join(map(str, batch.pages[:6])) + (",..." if len(batch.pages) > 6 else "")
        print(f"  {batch.engine:9s} {len(batch.pages):4d} pages  {head}")
    flagged = {page.n: page.flags for page in prof.pages if page.flags}
    if flagged:
        print(f"flags: {flagged}")
    print(
        f"extraction: batches={len(extraction.batches)} "
        f"failed_pages={len(extraction.failed_pages)} "
        f"markdown_failed_pages={len(extraction.markdown_failed_pages)}",
    )
    print(f"classification context: paragraphs={len(context.paragraphs)} tables={len(context.tables)}")
    print(f"manifest: {artifacts.path('00_manifest/document_manifest', manifest.doc_id)}")
    print(f"artifact: {artifacts.path('01_profiler/profile', prof.doc_id)}")
    print(f"artifact: {artifacts.path('02_extraction/index', prof.doc_id)}")
    print(f"artifact: {artifacts.path('03_classification_context/classification_context', prof.doc_id)}")
    if not extraction.complete or not context.quality.has_classifiable_content:
        print(f"FAILED  pipeline quality: {context.quality.model_dump(mode='json')}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
