
# CDSCO Public Notices — Research Findings

## Target

`https://cdsco.gov.in/opencms/opencms/en/Notifications/Public-Notices/`

## Page Structure

Pattern A — same as Alerts/FDC:

- HTML table of wrapped PDFs
- Link format: `download_file_division.jsp?num_id=<base64>`
- Click resolves via iframe → real PDF under
  `UploadCDSCOWeb/2018/<Folder>/...`

## Data Volume

~100+ notices in the current view (no pagination observed).

## Relevance Assessment

| Category                              | Count (approx) | Relevance |
| ------------------------------------- | -------------- | --------- |
| Drug safety / enforcement actions     | ~15            | ✅ HIGH   |
| Regulatory process (SUGAM, timelines) | ~20            | ⚠️ LOW  |
| Cosmetics / medical devices / admin   | ~65            | ❌ NONE   |

**Signal-to-noise ratio: ~15%.**

## Extraction Policy

This source is now collected without a relevance filter.

The parser saves the full table from the page into `pn_all.json` and does not discard rows based on title keywords. Filtering is intentionally deferred to downstream analysis or app-level logic instead of being hardcoded into the scraper.

## Value to Medicine Scanner

The Public Notices page includes a mixture of meaningful enforcement actions and unrelated administrative/regulatory notices. The full extraction is kept to avoid missing legitimate drug safety or enforcement notices that do not match narrow keyword assumptions.

This matters for:

- drug theft or safety alerts
- manufacturer cancellation orders
- unapproved drug enforcement
- prescribing-information updates
- prohibitions or enforcement actions

## Dedup Strategy

Same as Alerts/FDC:

- Primary key: `document_id` (from `num_id` Base64)
- Secondary: `release_date` watermark
- Tertiary: SHA-256 content hash

## MVP Integration

Add a `source_category` column to the `documents` table:

documents
...
source_category -- 'alerts' | 'fdc' | 'public_notices' | 'banned_drugs'

The full set should remain available for downstream filtering, rather than pre-filtering at the extraction step.

## Recommendation

- ✅ Use the existing Pattern A pipeline
- ✅ Keep all Public Notice records in the extraction output
- ✅ Save full dataset to `pn_all.json`
- ❌ Do not apply hardcoded keyword filtering in the scraper
- ❌ Do not build a separate scraper — reuse what we have

## Files

websites/cdsco-public-notices/
├── http-requests/
│ ├── pn_test.py
│ └── output/pn_page.html
├── html-extraction/
│ ├── parse_pn.py
│ └── output/
│     └── pn_all.json
└── findings.md
