"""
Core scraping job — watermark based.

Called by:
  - manual trigger endpoint (POST /api/scrape-now)
  - APScheduler (phase 5)

Watermark rule:
  * Watermark = the newest release_date in our documents table,
    compared as real datetimes (CDSCO uses "YYYY-Mon-DD" strings,
    which do NOT sort correctly as plain strings).
  * A CDSCO alert is NEW if:
        (a) its document_id isn't in our DB, AND
        (b) its release_date > watermark   (or watermark is None — fresh DB)
  * Everything else is skipped (either already stored, or older than our
    scope of interest).
"""
from datetime import datetime

from app.database import SessionLocal
from app.models import Document
from app.pdf_handler import download_pdf
from app.scraper import scrape_alerts


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_cdsco_date(s: str) -> datetime:
    """
    Parse CDSCO's release_date format 'YYYY-Mon-DD' (e.g. '2025-Oct-08')
    into a datetime. Raises ValueError on malformed input.
    """
    return datetime.strptime(s, "%Y-%b-%d")


def _get_watermark(db) -> tuple[str | None, datetime | None]:
    """
    Return (raw_string, parsed_datetime) of the newest release_date
    currently stored in the DB.

    We compare PARSED datetimes, not raw strings, because alphabetical
    month names ("Apr", "Aug", "Dec", ...) do not sort chronologically.
    """
    rows = db.query(Document.release_date).all()

    parsed_pairs: list[tuple[str, datetime]] = []
    for (raw,) in rows:
        try:
            parsed_pairs.append((raw, _parse_cdsco_date(raw)))
        except (ValueError, TypeError):
            # Bad/legacy date — ignore for watermark purposes.
            continue

    if not parsed_pairs:
        return None, None

    newest_raw, newest_dt = max(parsed_pairs, key=lambda p: p[1])
    return newest_raw, newest_dt


# ---------------------------------------------------------------------------
# Main job
# ---------------------------------------------------------------------------

def run_scraper_job(fetch_limit: int | None = None) -> dict:
    """
    Fetch CDSCO alerts, download only those newer than our watermark.

    Args:
        fetch_limit: optional safety cap on how many rows to read from CDSCO.
                     None = read the whole page (recommended).
    """
    started_at = datetime.utcnow()
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "watermark": None,
        "watermark_parsed": None,
        "scraped": 0,
        "new": 0,
        "downloaded": 0,
        "failed": 0,
        "skipped_existing": 0,
        "skipped_older": 0,
        "skipped_bad_date": 0,
        "new_documents": [],
    }

    print(f"\n{'=' * 72}")
    print(f"[JOB] Started at {started_at.isoformat()}")

    try:
        records = scrape_alerts(limit=fetch_limit)
    except Exception as e:
        print(f"[JOB] Scraper failed: {e}")
        summary["finished_at"] = datetime.utcnow().isoformat()
        summary["error"] = str(e)
        return summary

    summary["scraped"] = len(records)
    print(f"[JOB] Scraped {len(records)} records from CDSCO")

    db = SessionLocal()
    try:
        watermark_str, watermark_dt = _get_watermark(db)
        summary["watermark"] = watermark_str
        summary["watermark_parsed"] = watermark_dt.isoformat() if watermark_dt else None
        print(f"[JOB] Watermark = {watermark_str!r}  (parsed: {watermark_dt})")

        for rec in records:
            # (a) already in DB?
            exists = (
                db.query(Document)
                .filter(Document.document_id == rec["document_id"])
                .first()
            )
            if exists:
                summary["skipped_existing"] += 1
                continue

            # (b) parse the incoming date
            try:
                rec_dt = _parse_cdsco_date(rec["release_date"])
            except (ValueError, TypeError):
                summary["skipped_bad_date"] += 1
                print(f"[JOB]   SKIP bad date: {rec['release_date']!r} "
                      f"(doc {rec['document_id']})")
                continue

            # (c) at/below watermark? -> out of scope
            if watermark_dt is not None and rec_dt <= watermark_dt:
                summary["skipped_older"] += 1
                continue

            # --- NEW ---
            doc = Document(
                document_id=rec["document_id"],
                title=rec["title"],
                release_date=rec["release_date"],
                pdf_url=rec["pdf_url"],
                pdf_size_declared=rec["pdf_size_declared"],
                status="discovered",
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            summary["new"] += 1
            print(f"[JOB]   NEW {doc.document_id}  [{doc.release_date}]  "
                  f"{doc.title[:55]}")

            try:
                info = download_pdf(rec["document_id"], rec["pdf_url"])
                doc.local_file_path = info["local_file_path"]
                doc.file_size_bytes = info["file_size_bytes"]
                doc.content_hash = info["content_hash"]
                doc.status = "downloaded"
                db.commit()

                summary["downloaded"] += 1
                summary["new_documents"].append({
                    "document_id": doc.document_id,
                    "title": doc.title,
                    "release_date": doc.release_date,
                    "file_size_bytes": info["file_size_bytes"],
                })
                print(f"[JOB]       PDF: {info['file_size_bytes']:,} bytes")
            except Exception as e:
                doc.status = "failed"
                db.commit()
                summary["failed"] += 1
                print(f"[JOB]       FAILED: {e}")
    finally:
        db.close()

    finished_at = datetime.utcnow()
    summary["finished_at"] = finished_at.isoformat()
    duration = (finished_at - started_at).total_seconds()
    print(f"[JOB] Finished in {duration:.1f}s — "
          f"new={summary['new']} downloaded={summary['downloaded']} "
          f"failed={summary['failed']} "
          f"skipped_existing={summary['skipped_existing']} "
          f"skipped_older={summary['skipped_older']} "
          f"skipped_bad_date={summary['skipped_bad_date']}")
    print(f"{'=' * 72}\n")

    return summary