
# CDSCO Gazette Notifications — Research Findings

## Target

`https://cdsco.gov.in/opencms/opencms/en/Notifications/Gazette-Notifications/`

## Page Structure

Pattern A — same as Alerts / FDC / Public Notices:

- HTML table of wrapped PDFs
- Link format: `download_file_division.jsp?num_id=<base64>`
- Click resolves via iframe → real PDF under
  `UploadCDSCOWeb/2018/<Folder>/...`

## Data Volume

~100 notifications visible (no pagination observed in HTML).

## Relevance Assessment

| Category                                     | Count (approx) | Relevance |
| -------------------------------------------- | -------------- | --------- |
| Prohibitions / bans of drugs or FDCs         | ~12            | ✅ HIGH   |
| Schedule H1 inclusions                       | ~4             | ✅ HIGH   |
| Debarments                                   | ~2             | ✅ HIGH   |
| Draft amendments / fee revisions / ports     | ~60            | ❌ NONE   |
| Government Analyst / laboratory appointments | ~15            | ❌ NONE   |
| Compounding of offences / Jan Vishwas        | ~5             | ⚠️ LOW  |

**Signal-to-noise ratio: ~15-20%.**

## Extraction Policy

This source is now collected without a relevance filter.

The parser saves the full table from the page into `gazette_all.json` and does not discard rows based on title keywords. Filtering is intentionally deferred to downstream analysis or app-level logic instead of being hardcoded in the extraction step.

## Value to Medicine Scanner

The Gazette includes both high-signal regulatory actions and a large amount of administrative/regulatory process noise. Keeping the full set avoids losing potentially important notices that were previously excluded by a keyword filter.

This is especially relevant for:

- Prohibitions of FDCs
- Specific drug bans
- Schedule H1 inclusions
- Debarment notices
- Antimicrobial action items

## Dedup Strategy

Same as Alerts / FDC / Public Notices:

- Primary key: `document_id` (from `num_id` Base64)
- Secondary: `release_date` watermark
- Tertiary: SHA-256 content hash

## MVP Integration

Reuse `source_category = 'gazette'` in the `documents` table.

Do not rely on a `relevant = true` boolean at the extraction layer. The full dataset should remain available for downstream filtering.

## Recommendation

- ✅ Use existing Pattern A pipeline
- ✅ Keep all Gazette records in the extraction output
- ✅ Save full dataset to `gazette_all.json`
- ❌ Do not apply hardcoded keyword filtering in the scraper
- ❌ Do not build a separate scraper — reuse what we have

## Files

websites/cdsco-gazette-notifications/
├── http-requests/
│   ├── gazette_test.py
│   └── output/gazette_page.html
├── html-extraction/
│   ├── parse_gazette.py
│   └── output/
│       └── gazette_all.json
└── findings.md
