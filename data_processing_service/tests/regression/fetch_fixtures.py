"""Download the golden-set PDFs from cdsco.gov.in into initial_data_ingestion/01_downloads/.

Uses the download helpers in initial_data_ingestion/01_downloads/download_all_sources.py (needs
`requests` and `beautifulsoup4`). Existing files are kept; every file is checked against its sha256.

    python -m data_processing_service.tests.regression.fetch_fixtures
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys

from data_processing_service.tests.regression.harness import REPO_ROOT, load_golden, pdf_path

DOWNLOADER = REPO_ROOT / "initial_data_ingestion" / "01_downloads" / "download_all_sources.py"


def _load_downloader():
    spec = importlib.util.spec_from_file_location("download_all_sources", DOWNLOADER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    downloader = _load_downloader()
    session = downloader.requests.Session()
    session.headers.update(downloader.HEADERS)
    failures = 0
    for document in load_golden():
        path = pdf_path(document)
        source = document["source"]
        if not path.is_file():
            status = downloader.save_wrapped(
                session,
                path.parent.name,
                source["num_id"],
                document["title"],
                downloader.SOURCES[source["listing"]],
                dry_run=False,
            )
        else:
            status = "existing"
        if not path.is_file():
            failures += 1
            print(f"FAILED   {document['file']} ({status})", file=sys.stderr)
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != document["sha256"]:
            failures += 1
            print(f"CHANGED  {document['file']}: sha256 differs from the verified copy", file=sys.stderr)
            continue
        print(f"{status:9}{document['file']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
