"""Seed scraped source data through one source-aware workflow."""
import argparse
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
import re

from cloud_worker.scraper.banned_drugs import scrape_banned_drugs
from cloud_worker.scraper.fdc import scrape_fdc
from cloud_worker.scraper.json_handler import upload_json_artifact
from cloud_worker.scraper.nsq import _fetch_records
from cloud_worker.scraper.pdf_handler import download_pdf
from cloud_worker.scraper.pvpi import scrape_pvpi
from cloud_worker.scraper.scraper import scrape_alerts
from server.database.database import SessionLocal
from server.database.models import Document

SourceScraper = Callable[[int | None], list[dict]]
SEED_POSITIONS = (5, 6)


def _reporting_period(value: object) -> tuple[int, int] | None:
    """Parse NSQ reporting periods such as ``AUG-2026`` or ``March 2026``."""
    text = str(value or "").strip().upper()
    for pattern in ("%b-%Y", "%B-%Y", "%b %Y", "%B %Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed.year, parsed.month
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})[/-](\d{4})", text)
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return year, month
    return None


def _previous_reporting_records(records: list[dict]) -> tuple[list[dict], tuple[int, int]]:
    """Exclude the newest NSQ period and retain all records from the prior month."""
    periods = {
        period
        for record in records
        if (period := _reporting_period(record.get("dt_reporting_month_year"))) is not None
    }
    if not periods:
        raise RuntimeError("NSQ records contain no parseable reporting month/year.")

    latest_year, latest_month = max(periods)
    previous_month = latest_month - 1 or 12
    previous_year = latest_year - 1 if latest_month == 1 else latest_year
    selected_period = (previous_year, previous_month)
    return (
        [
            record
            for record in records
            if _reporting_period(record.get("dt_reporting_month_year")) == selected_period
        ],
        selected_period,
    )


def _period_label(period: tuple[int, int]) -> str:
    return f"{period[0]:04d}-{period[1]:02d}"


def _scrape_banned(limit: int | None = None) -> list[dict]:
    """Adapt the single current banned-drugs snapshot to the list contract."""
    return [scrape_banned_drugs()] if limit != 0 else []


SOURCE_SCRAPERS: dict[str, SourceScraper] = {
    "alerts": lambda limit=None: scrape_alerts(limit=limit, positions=SEED_POSITIONS),
    "fdc": lambda limit=None: scrape_fdc(limit=limit, positions=SEED_POSITIONS),
    "banned": _scrape_banned,
    "pvpi": scrape_pvpi,
}


def _legacy_document_id(record: dict) -> int:
    """Create a stable positive key for sources without a CDSCO numeric ID."""
    source_key = record.get("source_key") or record["pdf_url"]
    return int(sha256(source_key.encode("utf-8")).hexdigest()[:15], 16)


def _document_fields(record: dict) -> dict:
    """Map a normalized source record to the legacy documents table fields."""
    metadata = record.get("metadata", {})
    return {
        "document_id": record.get("document_id", _legacy_document_id(record)),
        "source": record.get("source", "unknown"),
        "source_key": record.get("source_key"),
        "document_type": record.get("document_type"),
        "source_metadata": metadata,
        "title": record.get("title") or record["pdf_url"].rsplit("/", 1)[-1],
        "release_date": record.get("release_date") or metadata.get("year") or "unknown",
        "pdf_url": record["pdf_url"],
        "pdf_size_declared": record.get("pdf_size_declared"),
    }


def _upsert_document(record: dict) -> dict:
    """Download one PDF and upsert its legacy Document row."""
    db = SessionLocal()
    try:
        fields = _document_fields(record)
        document_id = fields["document_id"]
        row = db.query(Document).filter(Document.document_id == document_id).first()
        info = download_pdf(
            document_id,
            fields["pdf_url"],
            source_name=record.get("source", "cdsco_alerts"),
            filename=record.get("metadata", {}).get("filename"),
        )
        values = {
            "source": fields["source"],
            "source_key": fields["source_key"],
            "document_type": fields["document_type"],
            "source_metadata": fields["source_metadata"],
            "title": fields["title"],
            "release_date": fields["release_date"],
            "pdf_url": fields["pdf_url"],
            "pdf_size_declared": fields["pdf_size_declared"],
            "s3_object_key": info["s3_object_key"],
            "file_size_bytes": info["file_size_bytes"],
            "content_hash": info["content_hash"],
            "status": "seeded",
        }
        if row is None:
            db.add(Document(document_id=document_id, **values))
        else:
            for key, value in values.items():
                setattr(row, key, value)
        db.commit()
        row = db.query(Document).filter(Document.document_id == document_id).one()
        return {
            "document_id": row.document_id,
            "title": row.title,
            "release_date": row.release_date,
            "s3_object_key": row.s3_object_key,
            "pdf_url": row.pdf_url,
            "status": row.status,
        }
    finally:
        db.close()


def seed_documents(source: str = "alerts", limit: int | None = 2) -> list[dict]:
    """Discover and seed downloadable PDF records for one source."""
    if source not in SOURCE_SCRAPERS:
        raise ValueError(f"Unsupported PDF source: {source}")
    return [_upsert_document(record) for record in SOURCE_SCRAPERS[source](limit=limit)]


def seed_nsq_json() -> dict[str, dict]:
    """Upload NSQ files and register both file rows in documents."""
    uploaded = {}
    for record_type in ("nsq", "spurious"):
        records = _fetch_records(record_type)
        filtered_records, selected_period = _previous_reporting_records(records)
        period_label = _period_label(selected_period)
        filename = f"{record_type}_{period_label}"
        artifact = upload_json_artifact(
            "nsq", filename,
            {
                "source": "cdsco_nsq",
                "record_type": record_type,
                "reporting_period": period_label,
                "aaData": filtered_records,
            },
        )
        db = SessionLocal()
        try:
            document_id = _legacy_document_id(
                {"source_key": f"cdsco_nsq:{record_type}:{period_label}", "pdf_url": artifact["s3_object_key"]}
            )
            values = {
                "source": "cdsco_nsq",
                "source_key": f"cdsco_nsq:{record_type}:{period_label}",
                "document_type": "NSQ_FILE" if record_type == "nsq" else "SPURIOUS_FILE",
                "source_metadata": {
                    "record_count": len(filtered_records),
                    "record_type": record_type,
                    "reporting_period": period_label,
                },
                "title": f"{filename}.json",
                "release_date": "unknown",
                "pdf_url": artifact["s3_object_key"],
                "s3_object_key": artifact["s3_object_key"],
                "file_size_bytes": artifact["file_size_bytes"],
                "content_hash": artifact["content_hash"],
                "status": "seeded",
            }
            row = db.query(Document).filter(Document.document_id == document_id).first()
            if row is None:
                db.add(Document(document_id=document_id, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            db.commit()
        finally:
            db.close()
        uploaded[record_type] = artifact
    return uploaded


def seed_demo_data(source: str = "alerts", limit: int | None = 2):
    """Backward-compatible entry point for the demo seed operation."""
    return seed_documents(source=source, limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed scraper source data.")
    parser.add_argument(
        "--source",
        choices=("alerts", "fdc", "banned", "pvpi", "nsq"),
        default="alerts",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum PDFs to seed; omit to seed every discovered PDF.",
    )
    args = parser.parse_args()
    result = seed_nsq_json() if args.source == "nsq" else seed_documents(args.source, args.limit)
    print(result)


if __name__ == "__main__":
    main()

