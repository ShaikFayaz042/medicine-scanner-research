"""
One-time seed:
  - Fetch top 6 CDSCO alerts
  - SKIP the newest 4 (reserved for the scheduler demo)
  - INSERT and DOWNLOAD only rows 5 and 6

After seeding, the DB contains rows 5-6 only.
When the scheduler runs later, it will detect rows 1-4 as NEW
and download them — that's the automation proof.
"""
from app.database import SessionLocal
from app.models import Document
from app.pdf_handler import download_pdf
from app.scraper import scrape_alerts

# --- Demo configuration ---
FETCH_LIMIT = 6    # fetch top 6 so we can see the full demo window
SKIP_NEWEST = 4    # rows 1-4 are RESERVED for the scheduler to discover


def main():
    print(f"[*] Scraping CDSCO Alerts (top {FETCH_LIMIT})...")
    records = scrape_alerts(limit=FETCH_LIMIT)
    print(f"[+] Got {len(records)} records")

    reserved = records[:SKIP_NEWEST]
    to_seed = records[SKIP_NEWEST:]

    print(f"\n[*] Reserved for scheduler demo (NOT inserted):")
    for r in reserved:
        print(f"    [-] {r['document_id']}  {r['title'][:60]}")

    print(f"\n[*] Seeding now ({len(to_seed)} rows):")
    db = SessionLocal()
    inserted = 0
    skipped = 0
    failed = 0

    try:
        for rec in to_seed:
            existing = (
                db.query(Document)
                .filter(Document.document_id == rec["document_id"])
                .first()
            )
            if existing:
                print(f"    [=] {rec['document_id']} already in DB — skipped")
                skipped += 1
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
            print(f"    [+] {doc.document_id}  {doc.title[:60]}")

            try:
                info = download_pdf(rec["document_id"], rec["pdf_url"])
                doc.local_file_path = info["local_file_path"]
                doc.file_size_bytes = info["file_size_bytes"]
                doc.content_hash = info["content_hash"]
                doc.status = "downloaded"
                db.commit()
                print(f"        PDF: {info['file_size_bytes']:,} bytes  "
                      f"sha256={info['content_hash'][:12]}...")
                inserted += 1
            except Exception as e:
                doc.status = "failed"
                db.commit()
                print(f"        [!] PDF download failed: {e}")
                failed += 1
    finally:
        db.close()

    print(f"\n[+] Seed complete — inserted={inserted}, "
          f"skipped={skipped}, failed={failed}")
    print(f"[+] {len(reserved)} documents reserved for the scheduler demo.")


if __name__ == "__main__":
    main()