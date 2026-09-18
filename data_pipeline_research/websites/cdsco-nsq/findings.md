
# `websites/cdsco-nsq/findings.md`

```markdown
# CDSCO NSQ / Spurious Drugs — Research Findings

**Date of research:** 2026-09-11
**Researcher:** Fayaz (with AI research partner)
**Status:** ✅ Complete — data source verified, backfilled, ready for MVP integration

---

## 1. Target

**Portal page:**
`https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/`

**Actual data application (behind iframe):**
`https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug`

**Data categories:**
- **NSQ Drugs** — batches that failed quality testing at CDSCO or state labs
- **Spurious Drugs** — batches suspected to be counterfeit

**Why relevant to the Medicine Scanner:**
This is the batch-level drug quality data. For a scanned medicine, if its
name + batch + manufacturer matches a record here, the scanner can flag
it as previously reported NSQ or spurious by CDSCO.

---

## 2. Page Architecture — Two-Layer Wrapper

```

┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 1 — CDSCO OpenCms Portal                                     │
│ URL: https://cdsco.gov.in/opencms/opencms/en/Notifications/nsq-drugs/ │
│ Response: ~95 KB HTML                                              │
│ Content: navigation chrome +  embed                        │
│ Real data: NONE                                                    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  iframe src
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 2 — CDSCOOnline Application                                  │
│ URL: https://cdscoonline.gov.in/CDSCO/viewPublicNSQDrug            │
│ Response: ~30 KB HTML                                              │
│ Content: JavaScript shell, filters, two empty tables               │
│ Real data: NONE (loaded via AJAX)                                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  AJAX JSON calls
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ LAYER 3 — Backend API                                              │
│ Base URL: https://cdscoonline.gov.in                               │
│ Endpoints: /CDSCO/publicNsqDrugTable, /CDSCO/filteredNsqDrugTable, │
│            /CDSCO/viewPublicSpuriousDrugData, etc.                 │
│ Response: JSON with `{iTotalDisplayRecords, iTotalRecords, aaData}`│
│ Real data: HERE ✅                                                 │
└─────────────────────────────────────────────────────────────────────┘

```

**Key finding:** The real data lives in Layer 3, a plain JSON API. No PDF
parsing, no HTML scraping of the actual records, no browser automation.

---

## 3. HTTP Request Test

| Property | Value |
|---|---|
| Target | Layer 1 portal page |
| Status | 200 OK |
| Size | 95.5 KB |
| Content-Type | text/html;charset=UTF-8 |
| Server | Wish |
| `<table>` elements | 0 |
| `<form>` elements | 0 |
| `<iframe>` elements | **2** (main content is one) |
| `.pdf` occurrences | 1 |
| `download_file_division` occurrences | 225 |
| `num_id=` occurrences | many (in stale commented-out content) |

**Conclusion:** The portal page is a stub. Real content comes from the
iframe.

---

## 4. Iframe HTTP Test

| Property | Value |
|---|---|
| Target | Layer 2 application |
| Status | 200 OK |
| Size | 29.8 KB |
| Content-Type | text/html;charset=UTF-8 |
| Server | **Abhi** (different from Layer 1's "Wish"!) |
| `<table>` elements | 2 (both empty) |
| `<select>` elements | 4 (filter dropdowns) |
| `<input>` elements | 0 |
| `<iframe>` elements | 0 |
| `ajax` occurrences | 7 |
| `datatable` occurrences | 25 |
| Endpoint URLs in inline JS | 7 |

**Server note:** Layer 2 is hosted on a **different server** than Layer 1.
This is important — it means the NSQ data may be resilient to changes on
the main CDSCO portal, and vice versa.

---

## 5. API Endpoints Discovered

All endpoints are `GET`, return JSON, and require no authentication or
cookies beyond a default browser User-Agent.

| Endpoint | Params | Records (default) | Fields |
|---|---|---|---|
| `/CDSCO/publicNsqDrugTable` | none | 239 | 9 |
| `/CDSCO/viewPublicSpuriousDrugData` | none | 1 (current month) | **23** |
| `/CDSCO/reportingYears` | `tab` | list | — |
| `/CDSCO/publicReportingMonths` | `year`, `tab` | list | — |
| `/CDSCO/statesPendingSubmission` | `month` (opt) | 37 | 1 |
| `/CDSCO/filteredNsqDrugTable` | `month`, `source`, `tab` | varies | 9 |
| `/CDSCO/filteredSpuriousDrugTable` | `month`, `source`, `tab` | varies | 13 |

**All response Content-Type:** `application/json;charset=UTF-8`

### Response wrapper format

```json
{
  "iTotalDisplayRecords": 239,
  "iTotalRecords": 239,
  "aaData": [ { ...record... }, { ...record... } ]
}
```

Some endpoints (`reportingYears`, `publicReportingMonths`) return plain
JSON arrays instead of the wrapper.

### Parameter conventions

- `month` format: `Mon-YYYY` (e.g. `Jan-2019`, `Jul-2026`)
- `source` values: `All`, `State`, `CDL`
- `tab` values: `nsq`, `spurious`

---

## 6. Data Schemas

### 6.1 NSQ Drug Record (9 fields)

Returned by both `/publicNsqDrugTable` and `/filteredNsqDrugTable`.

```json
{
  "str_product_name": "Pantoprazole Tablets IP",
  "str_batch_no": "PEP5001",
  "dt_manufacturing_date": "Feb-2025",
  "dt_expiry_date": "Jan-2027",
  "str_manufactured_by": "Finecure Pharmaceuticals Ltd.  PF-5 & 6, Sanand Industrial Estate-II, GIDC, Sanand, District: Ahmedbad",
  "str_nsq_result": "Dissolution test",
  "str_reporting_source": "State Lab",
  "str_reported_by_lab_or_state": "SDT&RL, Bhubaneswar",
  "dt_reporting_month_year": "JUL-2026"
}
```

| Field                            | Meaning                       | Notes                                          |
| -------------------------------- | ----------------------------- | ---------------------------------------------- |
| `str_product_name`             | Medicine name + strength      | Free text, may include brand                   |
| `str_batch_no`                 | Batch number                  | Free text, may contain newlines                |
| `dt_manufacturing_date`        | Mfg date                      | Format`Mon-YYYY` or null                     |
| `dt_expiry_date`               | Expiry date                   | Format`Mon-YYYY` or null                     |
| `str_manufactured_by`          | Manufacturer + full address   | Free text, multi-line                          |
| `str_nsq_result`               | Reason for NSQ classification | Varies from one word ("pH") to multi-paragraph |
| `str_reporting_source`         | "State Lab" or "CDSCO Labs"   | Short enum                                     |
| `str_reported_by_lab_or_state` | Specific testing lab          | Free text                                      |
| `dt_reporting_month_year`      | Reporting period              | Format`MMM-YYYY` (uppercase)                 |

### 6.2 Spurious Drug Record (23 fields, unfiltered only)

Returned by `/viewPublicSpuriousDrugData`.

Includes all NSQ fields plus:

```json
{
  "srno": 1,
  "product_name_from_mst": "Drug",
  "product_name_from_dtl": "Buprenorphine Injection I.P. 2ml",
  "str_dosage_form": "Injection  SVP",
  "num_id": 12377,
  "str_route": "Parentrals",
  "str_nsq_category": "Assay",
  "str_manufacturer_name": "Under Investigation",
  "str_manufacturing_state": "Uttarakhand",
  "num_spurious_flag": 1,
  "str_spurious_manufacturer_name": "Under Investigation",
  "str_spurious_manufactured_by": "Under Investigation",
  "dt_spurious_date": "2026-08-21T17:18:56.343",
  "str_nsq_remarks": "The product is purported to be spurious, however, the same is subject to outcome of investigation.",
  "str_firm_reply": "The actual manufacturer (as per label claim) has informed that the impugned batch of the product has not been manufactured by them and that it is a spurious drug."
}
```

**IMPORTANT — schema mismatch:**

The **filtered** spurious endpoint (`/filteredSpuriousDrugTable`) returns
only **13 of the 23 fields**. Ten enrichment fields are only available
from the unfiltered call, which returns the current month's data only.

| Field                              | Unfiltered | Filtered |
| ---------------------------------- | ---------- | -------- |
| `product_name_from_dtl`          | ✅         | ✅       |
| `str_batch_no`                   | ✅         | ✅       |
| `dt_manufacturing_date`          | ✅         | ✅       |
| `dt_expiry_date`                 | ✅         | ✅       |
| `str_manufactured_by`            | ✅         | ✅       |
| `str_nsq_result`                 | ✅         | ✅       |
| `str_reporting_source`           | ✅         | ✅       |
| `str_reported_by_lab_or_state`   | ✅         | ✅       |
| `dt_reporting_month_year`        | ✅         | ✅       |
| `str_nsq_remarks`                | ✅         | ✅       |
| `str_firm_reply`                 | ✅         | ✅       |
| `str_spurious_manufactured_by`   | ✅         | ✅       |
| `str_spurious_manufacturer_name` | ✅         | ✅       |
| `srno`                           | ✅         | ❌       |
| `product_name_from_mst`          | ✅         | ❌       |
| `str_dosage_form`                | ✅         | ❌       |
| `num_id`                         | ✅         | ❌       |
| `str_route`                      | ✅         | ❌       |
| `str_nsq_category`               | ✅         | ❌       |
| `str_manufacturer_name`          | ✅         | ❌       |
| `str_manufacturing_state`        | ✅         | ❌       |
| `num_spurious_flag`              | ✅         | ❌       |
| `dt_spurious_date`               | ✅         | ❌       |

**Implication for MVP:** Historical spurious records lose enrichment
metadata. Only the current month has the full schema.

---

## 7. Data Availability

The month dropdown is populated dynamically per year per tab. Not every
month/year combination is available.

### 7.1 NSQ Drugs — full history

| Year            | Months with data    |
| --------------- | ------------------- |
| 2019            | 12 (Jan → Dec)     |
| 2020            | 12                  |
| 2021            | 12                  |
| 2022            | 12                  |
| 2023            | 12                  |
| 2024            | 12                  |
| 2025            | 12                  |
| 2026            | 7 (Jan → Jul)      |
| **Total** | **91 months** |

### 7.2 Spurious Drugs — recent only

| Year            | Months with data              |
| --------------- | ----------------------------- |
| 2025            | 7 (Jun → Dec)                |
| 2026            | 6 (Jan → May, Jul — no Jun) |
| **Total** | **13 months**           |

**Interpretation:** The spurious tracking was launched around **June 2025**.
Prior to that, spurious findings were published only as PDFs on the
Alerts page.

---

## 8. Full Backfill Results (Executed 2026-09-11)

**Script:** `websites/cdsco-nsq/api-endpoint/backfill_all.py`

| Dataset         | Months        | Records         | API Calls     | Empty       |
| --------------- | ------------- | --------------- | ------------- | ----------- |
| NSQ             | 91            | **6,406** | 91            | 0           |
| Spurious        | 13            | **47**    | 13            | 0           |
| **Total** | **104** | **6,453** | **104** | **0** |

**Elapsed:** 116.7 seconds (with 0.3s politeness delay between calls)

**Output files:**

```
websites/cdsco-nsq/api-endpoint/output/backfill/
├── nsq_full_history.json         (6,406 records, 3.9 MB)
├── spurious_full_history.json    (47 records, 47 KB)
└── _backfill_summary.json
```

### 8.1 NSQ monthly volume trends

```
2019:  ~33 records/month average
2020:  ~28
2021:  ~29
2022:  ~49
2023:  ~56
2024:  ~72
2025:  ~156
2026:  ~187 (partial year, avg over 7 months)
```

**Observation:** Reporting volume has grown ~5× since 2019. Peak month so
far is **Jul-2026 with 239 records**. This reflects CDSCO's expanded
surveillance program and the new searchable portal (mid-2025).

### 8.2 Spurious monthly volume

Consistently low — 1 to 10 records per month. Total 47 records across
13 months.

---

## 9. num_id Linkage Test — ❌ FAILED

### 9.1 Hypothesis

The `num_id` field in spurious records appeared to be an internal CDSCO
document ID, similar to the IDs used in Alerts/FDC PDF download URLs.
If shared, we could cross-reference spurious records to their source
PDFs.

### 9.2 Test method

For each test case:

1. Take the integer `num_id` (e.g. 12377)
2. Base64-encode it (e.g. `MTIzNzc=`)
3. Call `download_file_division.jsp?num_id={encoded}`
4. Follow the iframe wrapper to the real PDF
5. Check if the PDF content matches the record's product

### 9.3 Test results

| Test                     | num_id | Expected PDF       | Actual PDF                                                 | Match? |
| ------------------------ | ------ | ------------------ | ---------------------------------------------------------- | ------ |
| Control (Alerts)         | 13487  | Circular on GST    | `UploadAlertsFiles/All State...pdf`                      | ✅     |
| Spurious (Buprenorphine) | 12377  | Buprenorphine case | `UploadEthicsRegistration/2031-ICMR-2625-MH-RC-2024.pdf` | ❌     |

### 9.4 Conclusion

Although both IDs live in the same OpenCms numbering system (they both
resolve via the same servlet), the `num_id` field in spurious records
**does NOT point to the record's own source document**.

**Possible explanations:**

- `num_id` is a legacy field or internal reference to unrelated content
- The CDSCO system reuses numeric IDs across different content categories
- The `num_id` may reference the *investigation file*, not the public
  finding

### 9.5 Impact on MVP

**Drop cross-referencing from the design.** We cannot reliably link
spurious API records back to source PDFs via `num_id`.

---

## 10. Legal Caveats — CRITICAL FOR MVP

### 10.1 The "Under Investigation" problem

Almost every spurious record in the backfill contains:

```json
{
  "str_manufactured_by": "Under Investigation",
  "str_nsq_remarks": "The product is purported to be spurious, however, the same is subject to outcome of investigation.",
  "str_firm_reply": "The actual manufacturer (as per label claim) has informed that the impugned batch of the product has not been manufactured by them and that it is a spurious drug."
}
```

### 10.2 Why this matters

Unlike NSQ (where the manufacturer IS publicly named because their own
batch failed quality testing), **spurious findings do not name the
manufacturer until the investigation concludes.**

The reasoning is legally correct: a spurious batch by definition may be
counterfeit — the brand owner whose name appears on the label may not
have made it. Naming them as "manufacturer of a spurious drug" before
investigation would be defamatory.

### 10.3 Product vs manufacturer distinction

Look at this real record carefully:

```
Product (as per label): "Zerodol-SP Tablets" by "Ipca Laboratories Ltd."
str_manufactured_by:    "Under Investigation"
```

The **label claims** Ipca made it. But CDSCO does not confirm Ipca made
it — the batch may be counterfeit. The `str_firm_reply` field even quotes
Ipca (or whoever the label names) saying "we did not manufacture this
batch."

### 10.4 Schema requirement for the MVP

The `drug_alerts` table needs a `legal_status` field:

| Value                            | Meaning                                    | Display guidance                                                 |
| -------------------------------- | ------------------------------------------ | ---------------------------------------------------------------- |
| `nsq_confirmed`                | NSQ batch, manufacturer publicly named     | "This batch failed quality testing. Manufacturer: {name}"        |
| `spurious_under_investigation` | Suspicion only, no manufacturer named      | "This batch is suspected to be spurious. Investigation ongoing." |
| `spurious_confirmed`           | Investigation complete, manufacturer named | "This batch is confirmed spurious. Source: {name}"               |
| `misbranded`                   | Label/composition irregularity             | "This product was misbranded."                                   |

### 10.5 MVP safety principle

The Medicine Scanner MUST NOT present spurious suspicion as fact. Every
spurious record must show:

1. The exact wording from `str_nsq_remarks`
2. The `str_firm_reply` (manufacturer's response, if any)
3. A clear "under investigation" badge
4. A link to the original CDSCO page as source

This aligns with the project's safety principle: "Do not treat absence
of a government record as absolute proof that a medicine is safe" and
"Do not allow an LLM to independently make medical/regulatory decisions."

---

## 11. New Document Detection Strategy

### 11.1 What we have

| Identifier         | Present?                         | Use                 |
| ------------------ | -------------------------------- | ------------------- |
| Stable document ID | ❌                               | Not available       |
| Stable URL         | ❌                               | Same URL every call |
| Release date       | ✅ (`dt_reporting_month_year`) | Watermark           |
| Title              | ✅ (`str_product_name`)        | Composite key       |
| Batch              | ✅ (`str_batch_no`)            | Composite key       |
| Manufacturer       | ✅ (`str_manufactured_by`)     | Composite key       |
| Content hash       | ✅ (SHA-256 of aaData)           | Change detection    |

### 11.2 Recommended strategy

**Primary key:** `(product_name, batch_no, manufactured_by)` tuple.
Unique per record. Combined with `dt_reporting_month_year` for temporal
context.

**Watermark:** `MAX(dt_reporting_month_year)` in our DB. Records newer
than this are candidates for insertion.

**Change detection:** SHA-256 of the sorted `aaData` array. If hash
differs from last poll, diff at row level and insert additions.

### 11.3 Daily polling plan

```
For each run:
  1. GET /CDSCO/publicNsqDrugTable
  2. GET /CDSCO/viewPublicSpuriousDrugData
  3. Compute row-tuple set
  4. INSERT any tuples not already in DB
  5. Log: "X new NSQ, Y new spurious"
```

Two API calls per day. Negligible load on CDSCO.

---

## 12. Recommendation

### 12.1 Method

**Direct HTTP JSON API** — preferred over any scraping approach.

### 12.2 Why

- ✅ Structured data with 9–23 fields per record
- ✅ No PDF parsing, no OCR, no HTML scraping
- ✅ Single HTTP request per month
- ✅ ~100 API calls pulls the entire 8-year history
- ✅ Same code works for NSQ and Spurious tabs
- ✅ Historical access verified from 2019 (NSQ) and mid-2025 (Spurious)
- ✅ No authentication, no cookies, no rate limit issues
- ✅ Zero failures across 104 backfill calls

### 12.3 Compared to other methods

| Method                          | Tested? | Works?     | Kept?               |
| ------------------------------- | ------- | ---------- | ------------------- |
| HTTP request                    | ✅      | ✅         | ✅                  |
| HTML extraction                 | ✅      | Not needed | ❌                  |
| DOM extraction                  | N/A     | Not needed | ❌                  |
| Browser automation (Playwright) | N/A     | Not needed | ❌                  |
| API endpoint                    | ✅      | ✅         | ✅**Primary** |
| PDF parsing                     | N/A     | Not needed | ❌                  |

### 12.4 MVP integration plan

1. **Initial seed:** Run full backfill once → 6,453 records in DB
2. **Daily poll:** Two API calls per day → insert new records only
3. **Query path:** When user scans medicine, look up by
   `(product_name, batch_no, manufacturer)` in `drug_alerts` table
4. **Display:** Show NSQ/spurious status with appropriate legal caveat
   and source link

---

## 13. MVP Priority

**HIGHEST.** This is the primary query-able batch-level data source
across all CDSCO pages researched so far.

Contrast with other sources:

| Source                   | Data type                          | Queryable per-batch?               |
| ------------------------ | ---------------------------------- | ---------------------------------- |
| Alerts                   | Documents (PDFs)                   | No — narrative documents          |
| FDC                      | Documents (PDFs)                   | No — regulatory decisions         |
| Banned Drugs             | 444 entries in one PDF             | Partially — ingredient-level bans |
| **NSQ + Spurious** | **6,453 structured records** | **✅ Yes — batch-level**    |

This is the only source that answers: *"Is this exact product + batch
combination a known quality concern?"*

---

## 14. Limitations & Known Issues

### 14.1 Data quality

- Source typos exist: `Pantoprazol`, `Rabepra zole`, mid-word line breaks
- Free-text `str_nsq_result` ranges from one word to multi-paragraph
- Some records have `null` dates when source says "Not Mentioned"
- Mixed categories: NSQ, MISBRANDED, Spurious — all in one stream
- `str_manufactured_by` often embeds full postal address

**Handle at normalization stage, not extraction.**

### 14.2 Schema inconsistency

- Filtered spurious endpoint returns 13 fields
- Unfiltered spurious endpoint returns 23 fields
- Only current month available with full schema

**Mitigation:** For historical spurious records, accept the reduced
schema. For current-month records, use the richer unfiltered endpoint.

### 14.3 num_id not usable

Verified that `num_id` does not link spurious records to source PDFs.
Do not rely on it.

### 14.4 Legal interpretation

The Medicine Scanner must not present spurious suspicion as fact.
Design must include legal status field and appropriate UI treatment.

### 14.5 External dependency

Layer 2 lives on `cdscoonline.gov.in` (different server from main
CDSCO portal). If this server goes down or the URL structure changes,
the API is lost. Monitor health.

---

## 15. Files

```
websites/cdsco-nsq/
├── findings.md                          ← this document
├── http-requests/
│   ├── nsq_test.py                      (portal page test)
│   ├── nsq_iframe_test.py               (iframe discovery)
│   └── output/
│       ├── nsq_page.html
│       ├── nsq_iframe_page.html
│       ├── nsq_response_metadata.txt
│       └── nsq_iframe_metadata.txt
├── api-endpoint/
│   ├── probe_api.py                     (initial 5 endpoint probes)
│   ├── discover_months.py               (manifest of available months)
│   ├── verify_num_id_linkage.py         (linkage test — failed)
│   ├── backfill_all.py                  (full backfill script)
│   └── output/
│       ├── CDSCO_publicNsqDrugTable.json            (239 records)
│       ├── CDSCO_viewPublicSpuriousDrugData.json    (1 record, 23 fields)
│       ├── CDSCO_reportingYears.json
│       ├── CDSCO_publicReportingMonths.json
│       ├── CDSCO_statesPendingSubmission.json
│       ├── _available_months.json                    (manifest)
│       ├── _num_id_linkage_test.json                 (test results)
│       ├── numid_13487.pdf                           (control PDF)
│       ├── numid_12377.pdf                           (unrelated PDF)
│       └── backfill/
│           ├── nsq_full_history.json                 (6,406 records, 3.9 MB)
│           ├── spurious_full_history.json            (47 records, 47 KB)
│           └── _backfill_summary.json
```

---

## 16. Open Questions

1. **Will the API remain stable?** Monitor weekly for the first month
   of production use.
2. **Does the unfiltered spurious endpoint ever return more than one
   month of data?** Observed: it returns the current month only. Could
   change.
3. **Are there any months with data that the manifest missed?** The
   manifest was derived from `/publicReportingMonths`, which is the same
   source the frontend uses. Trustworthy but worth spot-checking.
4. **What does `num_id` actually reference?** Investigated but not
   resolved. May be internal investigation file number, may be legacy.
   Not blocking for MVP.
5. **Are there duplicate records across months?** Initial scan of
   `nsq_full_history.json` shows some products appear in multiple months
   (e.g. "Ferrous Ascorbate & Folic Acid Tablets IP" by "Healer's Lab"
   with batches FAM-677, FAM-656, FAM-629, FAM-649, FAM-628 — all
   reported in JUL-2026). This is legitimate (multiple failing batches
   from the same manufacturer), not a bug. The dedup key must include
   batch number.

---

## 17. Summary — One-Paragraph Answer

The NSQ page on CDSCO is a **two-layer wrapper** (portal + iframe) that
hides a **plain JSON API** on a different server. We discovered all 7
API endpoints, documented both schemas (NSQ: 9 fields, Spurious: 23
fields), verified historical data back to 2019, executed a **complete
backfill of 6,453 records across 104 API calls in under 2 minutes**, and
tested a cross-reference hypothesis (`num_id` linkage) that turned out
to be invalid. The API requires **no authentication, no browser
automation, and no PDF parsing** — pure HTTP + JSON. The critical legal
caveat is that most spurious records name the manufacturer as "Under
Investigation," so the MVP must have a `legal_status` field to avoid
presenting suspicion as fact. This is the **highest-value data source**
discovered across all CDSCO pages researched so far.
