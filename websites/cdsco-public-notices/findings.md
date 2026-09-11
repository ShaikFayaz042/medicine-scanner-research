
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

## Decision: Keyword-Filtered Extraction

Do NOT scrape all notices. Apply a title-keyword filter:

**Keep if title contains:** alert, cancellation, prohibit, unapproved,
safety, theft, recall, spurious, NSQ, misbranded, adulterated, impurity,
side effect, adverse, prescribing information.

**Skip if title contains:** ethics committee, cosmetic, IVD, medical device,
SUGAM, e-RaktKosh, clinical research organisation, visitor, RTI, CPIO,
tender, vacancy, blood centre, radiotherapy, radiology, spectacle.

## Value to Medicine Scanner

**HIGH for ~15 notices per view**, mostly:

- Drug theft alerts (e.g. insulin batch)
- Cancellation orders naming manufacturers
- Unapproved drug/FDC enforcement
- Prescribing Information (PIL) updates for safety signals
- Prohibitions (e.g. Chloramphenicol/Nitrofurans)

**NONE for ~85 notices** — administrative content irrelevant to a scanner.

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
relevant -- boolean, derived from title keyword filter

text

Only query the scanner against rows where `relevant = true` for
Public Notices.

## Recommendation

- ✅ Use the existing Pattern A pipeline
- ✅ Add a keyword filter (see parse_pn.py)
- ✅ Download only relevant PDFs (skip cosmetics/devices)
- ❌ Do not build a separate scraper — reuse what we have

## Files

websites/cdsco-public-notices/
├── http-requests/
│ ├── pn_test.py
│ └── output/pn_page.html
├── html-extraction/
│ ├── parse_pn.py
│ └── output/
│ ├── pn_all.json (all ~100 notices)
│ └── pn_relevant.json (~15 filtered)
└── findings.md
