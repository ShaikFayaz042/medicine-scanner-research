"""Core scraping job — watermark based."""
from datetime import datetime

from automated_scraper_demo.database.database import SessionLocal
from automated_scraper_demo.database.models import Document
from automated_scraper_demo.scraper.pdf_handler import download_pdf
from automated_scraper_demo.scraper.scraper import scrape_alerts


def _parse_cdsco_date(s: str) -> datetime:
    """Parse CDSCO's release_date format 'YYYY-Mon-DD' into a datetime."""
    return datetime.strptime(s, "%Y-%b-%d")


def _get_watermark(db) -> tuple[str | None, datetime | None]:
    rows = db.query(Document.release_date).all()

    parsed_pairs: list[tuple[str, datetime]] = []
    for (raw,) in rows:
        try:
            parsed_pairs.append((raw, _parse_cdsco_date(raw)))
        except (ValueError, TypeError):
            continue

    if not parsed_pairs:
        return None, None

    newest_raw, newest_dt = max(parsed_pairs, key=lambda p: p[1])
    return newest_raw, newest_dt


def run_scraper_job(fetch_limit: int | None = None) -> dict:
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
            exists = (
                db.query(Document)
                .filter(Document.document_id == rec["document_id"])
                .first()
            )
            if exists:
                summary["skipped_existing"] += 1
                continue

            try:
                rec_dt = _parse_cdsco_date(rec["release_date"])
            except (ValueError, TypeError):
                summary["skipped_bad_date"] += 1
                print(f"[JOB]   SKIP bad date: {rec['release_date']!r} (doc {rec['document_id']})")
                continue

            if watermark_dt is not None and rec_dt <= watermark_dt:
                summary["skipped_older"] += 1
                continue

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
            print(f"[JOB]   NEW {doc.document_id}  [{doc.release_date}]  {doc.title[:55]}")

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
    print(f"[JOB] Finished in {duration:.1f}s — new={summary['new']} downloaded={summary['downloaded']} failed={summary['failed']} skipped_existing={summary['skipped_existing']} skipped_older={summary['skipped_older']} skipped_bad_date={summary['skipped_bad_date']}")
    print(f"{'=' * 72}\n")

    return summary
