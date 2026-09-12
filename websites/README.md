
# CDSCO / IPC Web Scraping — Master Research Findings

**Research phase:** POC completed for all 7 high-priority sources
**Date:** 2026-09-11
**Method:** Progressive testing — HTTP → HTML → API → browser (only if needed)

---

## 1. Source Inventory

| # | Source                         | URL                                          | Method                    | Rows/PDFs               | MVP Priority      |
| - | ------------------------------ | -------------------------------------------- | ------------------------- | ----------------------- | ----------------- |
| 1 | CDSCO Alerts                   | `/en/Alerts/`                              | HTTP + BS4                | 300 docs                | HIGH              |
| 2 | CDSCO FDC                      | `/en/Drugs/FDC/`                           | HTTP + BS4                | 79 docs (4 tabs)        | HIGH              |
| 3 | CDSCO Public Notices           | `/en/Notifications/Public-Notices/`        | HTTP + BS4               | full extraction        | HIGH              |
| 4 | CDSCO Gazette                  | `/en/Notifications/Gazette-Notifications/` | HTTP + BS4               | full extraction        | HIGH              |
| 5 | CDSCO Banned Drugs             | `/en/BannedDrugs`                          | HTTP + iframe + hash      | 1 PDF, 444 entries      | HIGH              |
| 6 | **CDSCO NSQ + Spurious** | `/en/Notifications/nsq-drugs/`             | **Direct JSON API** | **6,453 records** | **HIGHEST** |
| 7 | IPC PvPI Drug Safety Alerts    | `ipc.gov.in/.../drug-safety-alerts.html`   | HTTP + regex              | 84 PDFs + master        | HIGH              |

**Skipped (decision recorded):** `cdscoonline.gov.in/brandNames` and `/cdscoDrugs` — data duplicated in static PDFs + third-party datasets + ABDM open APIs. Fallback search only.

---

## 2. Method Selection — Evidence-Based

Progression applied to every source. Result:

| Method                    | Used for                       | Never used when            |
| ------------------------- | ------------------------------ | -------------------------- |
| Plain`requests`         | 6 of 7 sources                 | —                         |
| BeautifulSoup             | CDSCO Alerts, FDC, PN, Gazette | —                         |
| Regex extraction          | Gazette, PvPI                  | BS4 sufficient             |
| **Direct JSON API** | **NSQ**                  | —                         |
| iframe + SHA-256          | Banned Drugs                   | —                         |
| Playwright / Selenium     | **0 sources**            | All static-server-rendered |
| Scrapy / proxies / VPS    | **0 sources**            | Not justified              |

**Key learning:** Every CDSCO + IPC source served complete data via plain HTTP. No JS rendering anywhere. Browser automation would have added zero value.

---

## 3. The Two CDSCO Patterns

### Pattern A — Wrapped PDF tables (Alerts, FDC, Public Notices, Gazette)

```
HTML table → row → <a href="download_file_division.jsp?num_id=<base64>">
  → decode base64 → document_id (integer, stable)
  → GET wrapper (170 bytes HTML) → parse <iframe src>
  → GET real PDF under /UploadCDSCOWeb/2018/<Folder>/<file>.pdf
```

- Same `pdf_handler.py` works for all four sources
- `document_id` is **globally unique across CDSCO** — single dedup key
- PN and Gazette are now kept in full during extraction; filtering is deferred to downstream app logic instead of being hardcoded in the scraper

### Pattern B — iframe stub (Banned Drugs)

- 146-byte HTML with one `<iframe src="...pdf">`
- No table, no metadata, no date, no title
- Detection: **SHA-256 content hash only** (URL is stable, no ID exists)

### Pattern C — Two-layer iframe hiding JSON API (NSQ)

```
Portal page (95 KB, iframe) → cdscoonline.gov.in (30 KB, JS shell)
  → 7 JSON endpoints → 6,453 structured records
```

- Different server from main CDSCO portal
- No auth, no cookies, no rate limit
- 104 API calls backfill 8 years of history in < 2 minutes

### Pattern D — Static HTML + year-page crawl (IPC PvPI)

- Joomla site, one master PDF + 10 year links
- Direct `.pdf` hrefs, no wrapper
- Filter: `/pvpi/` path OR `Drug_Safety_Alert*` / `dsa*` filename

---

## 4. New-Document Detection Strategies

| Source                      | Primary Key                                      | Fallback                      |
| --------------------------- | ------------------------------------------------ | ----------------------------- |
| Alerts / FDC / PN / Gazette | `document_id`                                  | release_date + title, SHA-256 |
| Banned Drugs                | SHA-256 content hash                             | File size                     |
| NSQ                         | `(product_name, batch_no, manufacturer)` tuple | SHA-256 of sorted`aaData`   |
| PvPI                        | master PDF filename (contains last-update date)  | URL, SHA-256                  |
| NSQ Spurious                | Same tuple                                       | Reduced schema for historical |

**Watermark strategy:** `MAX(release_date)` or `MAX(dt_reporting_month_year)` in DB — records newer than watermark are candidates.

---

## 5. Critical Findings

### 5.1 NSQ is the highest-value source

Only source that answers: *"Is this exact product + batch a known quality concern?"* — 6,453 batch-level structured records, backfilled to 2019.

### 5.2 Legal caveats are non-negotiable

Two sources carry legal risk:

- **Banned Drugs PDF:** 2016 tranche (~344 FDCs) quashed by Delhi HC, under SC appeal. 2017 tranche (5 FDCs) stayed by Madras HC. 3 bans revoked with conditions.
- **NSQ Spurious records:** Manufacturer usually "Under Investigation." Suspicion ≠ fact.

**Schema requirement:**

```sql
drug_alerts
  ...
  legal_status  -- 'prohibited' | 'stayed' | 'quashed'
                -- | 'revoked_with_conditions'
                -- | 'nsq_confirmed'
                -- | 'spurious_under_investigation'
                -- | 'spurious_confirmed'
                -- | 'misbranded'
```

**UI rule:** Never present spurious suspicion as fact. Always show verbatim `str_nsq_remarks` + source link.

### 5.3 `num_id` in NSQ spurious records is NOT a document link

Tested: `num_id=12377` (Buprenorphine) resolves to an unrelated ethics PDF. Cross-referencing spurious records → source PDFs is impossible. Drop from design.

### 5.4 Schema inconsistency in NSQ Spurious

- Filtered endpoint: 13 fields
- Unfiltered endpoint: 23 fields (only current month)
- Historical spurious records lose 10 enrichment fields. Acceptable.

---

## 6. Data Volume Summary

| Category                                  | Count           |
| ----------------------------------------- | --------------- |
| Total documents (PDFs)                    | ~700            |
| Total structured records (NSQ + Spurious) | **6,453** |
| Sources with stable document IDs          | 4               |
| Sources needing SHA-256 only              | 1               |
| Sources with JSON API                     | 1               |
| Sources with extraction-time filtering     | 2               |
| Notes                                     | IPC PDF URL filter + NSQ API filtered endpoints |
| Sources needing year-crawl                | 1               |

---

## 7. MVP Integration Plan

### Single unified pipeline

```
requests (plain HTTP)
  → source-specific extractor
    (Pattern A / B / C / D)
  → filter (if applicable)
  → normalize → documents table + drug_alerts table
  → dedup by source-specific key
  → PDF text extraction (PyMuPDF, only for Pattern A/B/D)
```

### Recommended priority order

1. **NSQ + Spurious** — highest query value, structured, batch-level
2. **Banned Drugs** — ingredient-level legal prohibitions
3. **IPC PvPI master PDF** — post-marketing safety signals
4. **CDSCO Alerts** — regulatory narrative documents
5. **CDSCO FDC** — combination approval/prohibition context
6. **CDSCO Gazette** — legal instruments (Section 26A)
7. **CDSCO Public Notices** — enforcement actions

### Polling cadence

| Source                               | Frequency               | Cost           |
| ------------------------------------ | ----------------------- | -------------- |
| NSQ + Spurious                       | Daily                   | 2 API calls    |
| Alerts / FDC / PN / Gazette / Banned | Weekly                  | ~10 HTTP calls |
| PvPI master PDF                      | Weekly (filename check) | 1 HTTP call    |

---

## 8. Rules Verified — Nothing Violated

| Rule                          | Status                                   |
| ----------------------------- | ---------------------------------------- |
| Test simplest method first    | ✅ Every source started with`requests` |
| Prefer direct HTTP            | ✅ 7/7                                   |
| Prefer direct API             | ✅ NSQ uses JSON API                     |
| BeautifulSoup for static HTML | ✅ 4 sources                             |
| Playwright only if required   | ✅ Never required                        |
| No Scrapy                     | ✅ Not justified                         |
| No proxies                    | ✅ Not required                          |
| No CAPTCHA bypass             | ✅ None encountered                      |
| No auth bypass                | ✅ All public                            |
| No production infra built     | ✅ Research only                         |
| Evidence for every conclusion | ✅ All in findings + JSON outputs        |

---

## 9. Repository Structure

```
websites/
├── cdsco/                    # Alerts (original research)
├── cdsco-fdc/
├── cdsco-public-notices/
├── cdsco-gazette-notifications/
├── cdsco-banned-drugs/
├── cdsco-nsq/                # highest-value, API-based
├── ipc-pvpi/
└── MASTER_FINDINGS.md        # this file
```

Each folder contains:

- `http-requests/` — first test
- `html-extraction/` or `api-endpoint/` — extractor + sample output
- `pdf-download/` — where applicable
- `findings.md` — source-specific notes

---

## 10. Open Items (None Blocking)

- [ ] PvPI 2016 year link extraction (regex edge case)
- [ ] `findings.md` for FDC, Banned Drugs (already drafted)
- [ ] Banned Drugs → `legal_status` normalization rules
- [ ] NSQ spurious → historical schema gap (accept reduced)
- [ ] ABDM Drug Registry API — evaluate when stable (future source)

---

## 11. One-Paragraph Answer

* [ ] All 7 target sources were tested progressively and resolved without browser automation. CDSCO's Alerts, FDC, Public Notices, and Gazette share a single wrapped-PDF pattern (`num_id` → iframe → real PDF) with a globally unique `document_id`; Public Notices and Gazette are now kept in full during extraction and filtered only downstream as needed. Banned Drugs is a single hash-tracked PDF carrying critical legal caveats (2016 tranche quashed, 2017 tranche stayed). NSQ hides a clean public JSON API on a separate server (`cdscoonline.gov.in`) yielding **6,453 structured batch-level records** backfilled to 2019 in under 2 minutes — the highest-value source for the scanner. IPC PvPI exposes 84 direct monthly Drug Safety Alert PDFs plus one master PDF covering 2016–present. Dedup keys vary by pattern (document_id / SHA-256 / product-batch-manufacturer tuple / master-PDF filename). The MVP must carry a `legal_status` field so spurious and quashed entries are never presented as authoritative fact. Nothing in the research phase justified Playwright, Selenium, Scrapy, proxies, or a VPS.
