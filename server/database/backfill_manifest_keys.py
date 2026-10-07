"""One-off backfill for legacy RunApproval rows whose manifest_key is null.

These rows can be created before the SFN SUCCEEDED handler began deriving the
manifest path. The script sets the expected S3 key for each run_id so the
approve flow can proceed even for older records without retriggering the run.
"""

from __future__ import annotations

from server.config import S3_PREFIX
from server.database.database import SessionLocal
from server.database.models import RunApproval


def _derived_manifest_key(run_id: str) -> str:
    return f"{S3_PREFIX}/processed_files/runs/{run_id}/manifest.json"


def backfill_missing_manifest_keys() -> int:
    db = SessionLocal()
    try:
        rows = db.query(RunApproval).filter(RunApproval.manifest_key.is_(None)).all()
        updated = 0
        for row in rows:
            if not row.run_id:
                continue
            row.manifest_key = _derived_manifest_key(row.run_id)
            updated += 1
        db.commit()
        return updated
    finally:
        db.close()


if __name__ == "__main__":
    count = backfill_missing_manifest_keys()
    print(f"Backfilled {count} RunApproval rows with derived manifest_key values.")
