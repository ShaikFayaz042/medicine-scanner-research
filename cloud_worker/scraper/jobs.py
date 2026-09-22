"""Sequential, source-aware scraper job with independent watermarks."""
from datetime import datetime
from hashlib import sha256
from typing import Any, Callable

from cloud_worker.config import S3_PREFIX, S3_SOURCE_PREFIX
from cloud_worker.database.database import SessionLocal
from cloud_worker.database.models import Document
from cloud_worker.scraper.banned_drugs import scrape_banned_drugs
from cloud_worker.scraper.fdc import scrape_fdc
from cloud_worker.scraper.json_handler import upload_json_artifact
from cloud_worker.scraper.nsq import _fetch_records
from cloud_worker.scraper.pdf_handler import download_pdf
from cloud_worker.scraper.pvpi import scrape_pvpi
from cloud_worker.scraper.scraper import scrape_alerts

SourceScraper = Callable[[int | None], list[dict]]
WORKER_POSITIONS = (1, 2, 3, 4)
PDF_SOURCES: tuple[tuple[str, SourceScraper], ...] = (
    ("cdsco_alerts", lambda limit=None: scrape_alerts(limit=limit, positions=WORKER_POSITIONS)),
    ("cdsco_fdc", lambda limit=None: scrape_fdc(limit=limit, positions=WORKER_POSITIONS)),
    ("cdsco_banned_drugs", lambda limit=None: [scrape_banned_drugs()] if limit != 0 else []),
    ("ipc_pvpi", scrape_pvpi),
)


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    candidates = (text, text.title())
    for candidate in candidates:
        for pattern in (
            "%Y-%b-%d",
            "%Y-%B-%d",
            "%Y-%m-%d",
            "%B-%Y",
            "%b-%Y",
            "%B %Y",
            "%b %Y",
            "%m/%Y",
            "%Y",
        ):
            try:
                return datetime.strptime(candidate, pattern)
            except ValueError:
                continue
    return None


def _record_date(record: dict) -> datetime | None:
    metadata = record.get("metadata", {})
    for key in ("release_date", "dt_reporting_month_year", "reporting_date", "date", "year"):
        parsed = _parse_date(record.get(key) or metadata.get(key))
        if parsed:
            return parsed
    return None


def _previous_period(records: list[dict]) -> tuple[list[dict], tuple[int, int]]:
    """Return all records from the month before the newest API period."""
    periods = {
        (record_date.year, record_date.month)
        for record in records
        if (record_date := _record_date(record)) is not None
    }
    if not periods:
        raise RuntimeError("NSQ records contain no parseable reporting month/year.")

    latest_year, latest_month = max(periods)
    previous_period = (
        latest_year - 1 if latest_month == 1 else latest_year,
        12 if latest_month == 1 else latest_month - 1,
    )


def _latest_period(records: list[dict]) -> tuple[list[dict], tuple[int, int]]:
    """Return all records from the newest API reporting period."""
    periods = {
        (record_date.year, record_date.month)
        for record in records
        if (record_date := _record_date(record)) is not None
    }
    if not periods:
        raise RuntimeError("NSQ records contain no parseable reporting month/year.")
    latest_period = max(periods)
    return (
        [
            record
            for record in records
            if (record_date := _record_date(record)) is not None
            and (record_date.year, record_date.month) == latest_period
        ],
        latest_period,
    )
    return (
        [
            record
            for record in records
            if (record_date := _record_date(record)) is not None
            and (record_date.year, record_date.month) == previous_period
        ],
        previous_period,
    )


def _get_watermark(db, source: str) -> datetime | None:
    dates = [_parse_date(value) for (value,) in db.query(Document.release_date).filter(Document.source == source).all()]
    parsed = [value for value in dates if value is not None]
    return max(parsed) if parsed else None


def _document_id(record: dict) -> int:
    value = record.get("document_id") or record.get("source_key") or record["pdf_url"]
    return int(sha256(str(value).encode("utf-8")).hexdigest()[:15], 16)


def _nsq_document_id(record_type: str, object_key: str) -> int:
    value = f"cdsco_nsq:{record_type}"
    return int(sha256(value.encode("utf-8")).hexdigest()[:15], 16)


def _seed_pdf_source(db, source: str, scraper: SourceScraper, limit: int | None, summary: dict) -> None:
    records = scraper(limit=limit)
    watermark = _get_watermark(db, source)
    summary["sources"][source] = {
        "scraped": len(records),
        "watermark": watermark.isoformat() if watermark else None,
    }

    for record in records:
        document_id = _document_id(record)
        metadata = record.get("metadata", {})
        fields = {
            "source": record.get("source", source),
            "source_key": record.get("source_key"),
            "document_type": record.get("document_type"),
            "source_metadata": metadata,
            "title": record.get("title") or record["pdf_url"].rsplit("/", 1)[-1],
            "release_date": record.get("release_date") or metadata.get("year") or "unknown",
            "pdf_url": record["pdf_url"],
            "pdf_size_declared": record.get("pdf_size_declared"),
        }
        row = db.query(Document).filter(Document.document_id == document_id).first()
        if row and row.s3_object_key and row.file_size_bytes:
            summary["skipped_existing"] += 1
            continue
        record_date = _record_date(record)
        if row is None and watermark and record_date and record_date <= watermark:
            summary["skipped_older"] += 1
            continue
        if row is None:
            row = Document(document_id=document_id, status="discovered", **fields)
            db.add(row)
        else:
            for key, value in fields.items():
                setattr(row, key, value)
            row.status = "discovered"
        db.commit()
        try:
            info = download_pdf(
                document_id,
                fields["pdf_url"],
                source_name=fields["source"],
                filename=metadata.get("filename"),
            )
            row.s3_object_key = info["s3_object_key"]
            row.file_size_bytes = info["file_size_bytes"]
            row.content_hash = info["content_hash"]
            row.status = "downloaded"
            db.commit()
            summary["downloaded"] += 1
        except Exception as exc:
            row.status = "failed"
            row.source_metadata = {**(row.source_metadata or {}), "last_error": str(exc)}
            db.commit()
            summary["failed"] += 1


def _seed_nsq(db, summary: dict) -> None:
    for record_type in ("nsq", "spurious"):
        records = _fetch_records(record_type)
        filtered, selected_period = _latest_period(records)
        selected_year, selected_month = selected_period
        reporting_period = f"{selected_year:04d}-{selected_month:02d}"
        filename = f"{record_type}_{reporting_period}"
        key = f"cdsco_nsq:{record_type}:{reporting_period}"
        object_key = "/".join(
            part.strip("/")
            for part in (S3_PREFIX, S3_SOURCE_PREFIX, "nsq", f"{filename}.json")
            if part
        )
        document_id = _nsq_document_id(record_type, object_key)
        row = db.query(Document).filter(Document.document_id == document_id).first()
        artifact = upload_json_artifact(
            "nsq",
            filename,
            {
                "source": "cdsco_nsq",
                "record_type": record_type,
                "reporting_period": reporting_period,
                "aaData": filtered,
            },
        )
        values = {
            "source": "cdsco_nsq",
            "source_key": key,
            "document_type": "NSQ_FILE" if record_type == "nsq" else "SPURIOUS_FILE",
            "source_metadata": {
                "record_type": record_type,
                "record_count": len(filtered),
                "reporting_period": reporting_period,
            },
            "title": f"{filename}.json",
            "release_date": f"{selected_year:04d}-{selected_month:02d}-01",
            "pdf_url": artifact["s3_object_key"],
            "s3_object_key": artifact["s3_object_key"],
            "file_size_bytes": artifact["file_size_bytes"],
            "content_hash": artifact["content_hash"],
            "status": "downloaded",
        }
        if row is None:
            db.add(Document(document_id=document_id, **values))
        else:
            for key_name, value in values.items():
                setattr(row, key_name, value)
        db.commit()
        summary["nsq_json"][record_type] = {"records": len(filtered), **artifact}


def run_scraper_job(fetch_limit: int | None = None) -> dict:
    """Run all sources in sequence with source-specific watermarks."""
    summary = {
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "sources": {},
        "downloaded": 0,
        "failed": 0,
        "skipped_existing": 0,
        "skipped_older": 0,
        "nsq_json": {},
    }
    db = SessionLocal()
    try:
        for source, scraper in PDF_SOURCES:
            try:
                _seed_pdf_source(db, source, scraper, fetch_limit, summary)
            except Exception as exc:
                summary["sources"][source] = {"error": str(exc)}
        try:
            _seed_nsq(db, summary)
        except Exception as exc:
            summary["nsq_json_error"] = str(exc)
    finally:
        db.close()
    summary["finished_at"] = datetime.utcnow().isoformat()
    return summary