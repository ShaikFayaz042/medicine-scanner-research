
# IPC PvPI Drug Safety Alerts — Research Findings

## Target

`https://www.ipc.gov.in/mandates/pvpi/pvpi-outcome/8-category-en/416-drug-safety-alerts.html`

Site: Indian Pharmacopoeia Commission (IPC), an autonomous institute under
Ministry of Health & Family Welfare. Hosts the Pharmacovigilance Programme
of India (PvPI).

## Page Structure

Joomla-based site. Content is **static HTML** — no JS rendering, no iframe,
no XHR/fetch, no authentication, no CAPTCHA.

Structure:

- One main article page listing year links: `Drug Alerts 2016` … `Drug Alerts 2026`
- One master PDF: `List-of-Drugs-Safety-Alerts-issued-by-PvPI-from-March-2016-to-till-date---27.07.2026.pdf`
- Each year link resolves to either:
  - a Joomla article page (`/mandates/pvpi/pvpi-outcome/8-category-en/<id>-drug-alerts-YYYY.html`), or
  - a Joomla category page (`/mandates/pvpi/pvpi-outcome.html?id=<id>:drug-alerts-YYYY&catid=2`)
- Each year page contains 5–12 direct `.pdf` links under `/images/` or `/PvPI/das/`

PDF links are plain `<a href="....pdf">` — no wrapper, no download endpoint,
no base64 `num_id`. This is fundamentally different from CDSCO sources.

## Data Volume

| Source                               | Count                          |
| ------------------------------------ | ------------------------------ |
| Master PDF (2016–2026, single file) | 1                              |
| Year pages followed                  | 10 (2017–2026)                |
| Individual monthly PDFs extracted    | 84 unique                      |
| Years not auto-followed (2016)       | 1 (regex edge case, see below) |

After 2016 fix: expected **~90 unique PDFs**.

## Relevance Assessment

| Category                             | Relevance                     |
| ------------------------------------ | ----------------------------- |
| Monthly Drug Safety Alert PDFs       | ✅ HIGH                       |
| Master consolidated PDF (2016–2026) | ✅ HIGH — single best source |
| IP Reference Substances lists        | ❌ NONE (sidebar navigation)  |
| Impurity lists                       | ❌ NONE                       |
| Supply order forms                   | ❌ NONE                       |
| Phytopharmaceutical guidance docs    | ❌ NONE                       |
| Prednisone dissolution protocol      | ❌ NONE                       |

**Signal-to-noise ratio: ~95%.** This is by far the cleanest source
researched so far. Almost everything on the page is a Drug Safety Alert.

## Method Selection

**HTTP + HTML extraction.** Evidence:

1. `ipc_test.py` — HTTP 200, 60 KB, `text/html; charset=utf-8`
2. `.pdf (any)` count: 7 static + 10 year links visible in raw HTML
3. No `<iframe>`, no `<table>`, no `download_file_division`, no `num_id=`
4. Year pages also return static HTML with direct PDF hrefs
5. Playwright / Selenium **not needed**

### Extraction pipeline (verified)

1. Fetch main page with plain `requests`
2. Regex-extract:
   - direct `.pdf` hrefs (master PDF)
   - `Drug Alerts YYYY` year links
3. For each year link, fetch the year page
4. Regex-extract `.pdf` hrefs from each year page
5. Filter out non-DSA PDFs (`is_drug_alert()` — checks for `/pvpi/`
   or DSA-related filename patterns; rejects `/images/pdf/File*.pdf`
   reference-substance and form URLs)
6. Merge + dedupe by absolute URL

### Why not a direct PDF URL pattern

Unlike CDSCO (where all PDFs go through `download_file_division.jsp?num_id=`),
IPC exposes raw PDF files at inconsistent paths:

- `/images/pvpi/Drug-Safety-Alert-YYYY.pdf`
- `/images/Drug_Safety_Alert_YYYY.pdf`
- `/images/dsaMMYY.pdf`
- `/PvPI/das/Drug%20Safety%20Alert%20(Month%20YYYY).pdf`
- `/images/Drug-Safety-Alert-June-2021.pdf`

No single pattern covers all. Year-page crawling is the reliable method.

## New-Document Detection Strategy

**Primary: master PDF filename contains the last-update date.**

Example:
`List-of-Drugs-Safety-Alerts-issued-by-PvPI-from-March-2016-to-till-date---27.07.2026.pdf`

- Filename changes when a new alert is published (date suffix updates)
- Detecting a new filename → new alerts exist
- The master PDF itself is the single source of truth for what's new

**Secondary: monthly PDF URLs from year pages**

- Year page for current year is re-crawled periodically
- New PDF filename → new alert
- No stable document ID exists; use **URL as primary key**
- Optional tertiary: SHA-256 content hash (some PDFs are re-uploaded
  with identical content under new filenames)

**Recommended dedup keys (in order):**

1. `pdf_url` (absolute, normalized)
2. `filename` (after `unquote`)
3. SHA-256 hash (only if URL-collision risk emerges)

## Value to Medicine Scanner

**HIGH.** This is the authoritative Indian source for post-marketing
drug safety alerts. Every monthly PDF typically contains:

- Drug name (generic + brand)
- Adverse reaction / safety signal
- Regulatory action (PIL update, warning, restriction)
- Reference to IPC / PvPI recommendation

Directly usable for:

- Medicine scanner warnings when user scans a drug strip
- Cross-reference with CDSCO alerts (many overlap — good for verification)
- PIL (Prescribing Information Leaflet) change tracking

## Data Quality Notes

1. **2016 year link not auto-detected**

   - Structure: `<a href="..."><img .../> Drug Alerts 2016</a>`
   - Inner `<img>` tag breaks the simple regex used in v1/v2
   - Not critical — master PDF covers 2016 fully
   - Fix available: strip inner tags before matching
2. **Filename inconsistency across years**

   - 2017–2022: mixed `Drug_Safety_Alert_*`, `Drugs_safety_Alert_*`, `dsa*`, and `Drug%20Safety%20Alert%20(...)`
   - 2023–2026: mostly consistent `Drug_Safety_Alert_<Month>_<Year>.pdf`
   - Do not rely on filename parsing for date extraction — use URL structure + year-page context
3. **URL percent-encoding**

   - Old PDFs use `%20` for spaces
   - Apply `urllib.parse.unquote` to filenames before storing
4. **No pagination, no rate limiting, no auth**

   - 10 year-page requests, all served without headers tricks
   - Polite crawl is trivial

## Comparison With CDSCO

| Aspect             | CDSCO (Alerts/PN/Gazette)                   | IPC PvPI               |
| ------------------ | ------------------------------------------- | ---------------------- |
| PDF URL pattern    | `download_file_division.jsp?num_id=<b64>` | Direct`.pdf` paths   |
| Stable document ID | Yes (`document_id` from base64)           | No — URL is the key   |
| Master index PDF   | No                                          | Yes                    |
| HTML structure     | `<table id="example">`                    | Joomla article body    |
| Filter needed      | Yes (aggressive)                            | Minimal (mostly clean) |
| JS rendering       | No                                          | No                     |
| Playwright needed  | No                                          | No                     |

Implication: IPC is the **simplest source researched so far**. Reuse the
same `requests` + regex + dedup pattern, no CDSCO-specific plumbing.

## MVP Integration

Add to the `documents` table:

```sql
documents
  ...
  source_category   -- 'cdsco_alerts' | 'cdsco_pn' | 'cdsco_fdc' | 'cdsco_gazette'
                    -- | 'ipc_pvpi_master' | 'ipc_pvpi_monthly'
  relevant          -- true for all DSA PDFs
```


Recommended MVP pipeline:

Phase 1 — Master PDF only

Download List-of-Drugs-Safety-Alerts-issued-by-PvPI-from-March-2016-to-till-date---<date></date>.pdf

Parse the tabular listing inside the PDF

Extract: drug name, alert type, date, regulatory action

This covers 2016–present in one file

Phase 2 — Monthly PDFs

Crawl year pages, download each monthly PDF

Parse per-alert content for richer detail

Useful for cross-referencing and full-text search

New-document detection

On each run, fetch the main page and check the master PDF filename

If date suffix changed → new alert(s) published → re-download master

Optionally, diff year-page URLs against last-seen set

Recommendation
✅ Use plain HTTP + regex extraction — no browser automation

✅ Master PDF is the single highest-value artifact — prioritize it

✅ URL-based dedup — no stable IDs available

✅ Reuse existing extraction pipeline — pattern is simpler than CDSCO

❌ Do not use Playwright — static HTML confirmed

❌ Do not crawl deeper than year pages — no value

❌ Do not store the 6 sidebar/navigation PDFs — filtered out

Evidence Trail
Test	Result	File
HTTP request	200, 60 KB, static HTML	http-requests/output/ipc_page.html
Year link extraction	10 links found (2017–2026)	same
Year page crawl	10 pages followed successfully	printed in parse_ipc_pvpi.py output
PDF extraction	84 unique PDFs	html-extraction/output/ipc_pdfs.json
Master PDF detected	Yes	same
Files
text
websites/ipc-pvpi/
├── http-requests/
│   ├── ipc_test.py
│   └── output/
│       └── ipc_page.html
├── html-extraction/
│   ├── parse_ipc_pvpi.py
│   └── output/
│       └── ipc_pdfs.json
└── findings.md
