# CDSCO Banned Drugs — Research Findings

## Target

`https://cdsco.gov.in/opencms/opencms/en/BannedDrugs`

Complete list of drugs and FDCs prohibited for manufacture and sale
in India under Section 26A of the Drugs & Cosmetics Act, 1940.

## Page Structure (Verified)

The page returns a **146-byte HTML stub** containing a single `<iframe>`:

```html
<iframe src='/opencms/resources/UploadCDSCOWeb/2018/UploadAlertsFiles/banneddrugs_1.pdf'
        width='100%' height='100%' target='_blank'></iframe>
```


There is no table, no navigation, no metadata. Just a pointer to one PDF.

HTTP Request
Result: ✅ Success

Status: 200

Size: 146 bytes (the page itself)

Content-Type: text/html;charset=UTF-8

Server: Wish

HTML Extraction
Result: ✅ Trivial

Data available: single  pointing to the PDF

No table, no rows, no pagination

API / XHR
Not required. Static HTML.

DOM Extraction / Browser Automation
Not required.

PDF Handling — Verified Downloads
URL	Status	Size	SHA-256
banneddrugs_1.pdf	✅ 200	504,075 bytes	8b2fad16e4752afc...
banneddrugs.pdf	✅ 200	504,075 bytes	8b2fad16e4752afc... (identical)
banneddrugs_2.pdf	❌ 404	—	—
banneddrugs_3.pdf	❌ 404	—	—
banneddrugs_4.pdf	❌ 404	—	—
Key findings:

Only ONE PDF exists. The _1 suffix is a naming convention.

The no-suffix filename (banneddrugs.pdf) resolves to the SAME content.

The iframe references _1; either URL retrieves the same bytes.

PDF is text-based — extractable via PyMuPDF / pdfplumber. No OCR needed.

28 pages, ~444 numbered entries

PDF Content Structure
Header: "LIST OF DRUGS PROHIBITED FOR MANUFACTURE AND SALE THROUGH
GAZETTE NOTIFICATIONS UNDER SECTION 26A OF DRUGS & COSMETICS ACT 1940"

Per-entry structure:

text
Sr. No. | Drug/Combination Name | GSR/S.O. Notification Number | Date
Coverage: prohibitions from 1983 to 2016, organized chronologically:

1983 (GSR 578(E) — foundational tranche, 12 entries)

1988-1995 (assorted GSRs)

2003-2013 (assorted GSRs)

10.03.2016 (S.O. 705(E) → 1048(E) — massive tranche, ~344 FDCs)

08.06.2017 (S.O. 1851(E) → 1855(E) — 5 FDCs)

⚠️ Legal Caveats (CRITICAL for medicine verification)
The PDF itself contains three critical caveats that MUST be preserved:

1. 2016 tranche quashed
   "***The Notification from S.O.Nos 705 (E) to 1048 (E) dated 10.03.2016
   were quashed by Hon'ble Delhi High Court vide its order dated 01.12.2016.
   Union of India had challenged the order of Delhi High court before the
   Supreme Court by way of SLP."

→ The largest tranche (~344 FDCs) is under Supreme Court appeal.
Status: LEGALLY UNCERTAIN.

2. 2017 tranche stayed
   "Presently stayed by the Honble High Court of Madras."

→ Entries 440-444 (S.O. 1851-1855(E)) are court-stayed.

3. Three bans revoked with conditions
   Dextropropoxyphene (#92) — revoked 2017, allowed for cancer pain only, ≤300mg/day

Analgin (#94) — initial suspension revoked, allowed with conditions

Pioglitazone (#95) — initial suspension revoked, allowed with conditions

New Document Detection
Method	Works?
document_id	❌ Does not exist
URL comparison	❌ URL is stable
Title	❌ No title on the page
Release date	❌ No date on the page
SHA-256 content hash	✅ Primary detection method
File size	⚠️ Weak fallback
Strategy:

Fetch /BannedDrugs

Extract iframe src → PDF URL

Download → compute SHA-256

Compare against last-known hash in DB

If different → new list published → update record

Recommendation
Method: HTTP Request + iframe extraction + SHA-256 change detection

Why:

The page serves only an iframe stub. No HTML parsing needed beyond one tag.

The PDF content is text-based. No OCR.

Content hash is the only viable dedup key because there is no document_id, no date, no title.

Same pdf_handler.py pattern from Alerts/FDC works; just a different resolver path.

Limitations / Notes
Only one record. Not a list of documents. The database schema needs a
different record type from Alerts/FDC — one that tracks a single stable
document and its content hash, not a list of many.

Legal status is nuanced. Entries exist but may be court-quashed or stayed.
The medicine scanner MUST NOT present the raw list as authoritative without
the caveats.

~444 entries with mixed level-of-detail (ingredient bans vs. FDC bans vs.
"any formulation containing X").

Requires PDF text extraction (fitz or pdfplumber) to consume programmatically.

MVP Priority
HIGH — this is the authoritative "is this drug banned?" list.
BUT: The legal caveats mean we cannot present it naively. The normalization
stage must carry a legal_status field per entry:

prohibited (currently in force)

stayed (court-stayed)

quashed (struck down, under appeal)

revoked_with_conditions (allowed with specific conditions)

Files
text
websites/cdsco-banned-drugs/
├── http-requests/
│   ├── banned_test.py
│   ├── homepage_links.py
│   └── output/
│       ├── banned_page.html
│       ├── banned_response_metadata.txt
│       ├── homepage.html
│       └── banned_links.json
├── pdf-download/
│   ├── download_banned.py
│   └── output/
│       ├── banneddrugs_1.pdf
│       ├── banneddrugs.pdf
│       └── _download_summary.json
└── findings.md
