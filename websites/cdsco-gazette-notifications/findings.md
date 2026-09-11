
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

## Decision: Aggressive Keyword Filter

Gazette is the noisiest CDSCO source. Filter must be stricter than
Public Notices.

**Keep if title contains:**
prohibit, prohibition, banning, ban, restriction of, schedule h1,
debarment, unapproved, spurious, and specific drug names
(nimesulide, chloramphenicol, nitrofurans, etodolac, ketoprofen,
aceclofenac, pregabalin, oseltamivir, zanamivir, chlorpheniramine,
phenylephrine, naproxen, FDC, fixed dose combination).

**Skip if title contains:**
draft, corrigendum, amendment, testing fee, government analyst,
port, airport, national institute, cdl, cdtl, nib, ivri, schedule m,
compounding, jan vishwas, qualification, appointment, extension,
reconstitution, blood product, cosmetics rule, shelf life.

## Value to Medicine Scanner

**HIGH for ~15-20 notices**, mostly:

- Prohibition of FDCs (16, 156, 14 FDCs etc. — single PDF each lists many drugs)
- Specific drug bans (Nimesulide, Etodolac, Ketoprofen, Aceclofenac)
- Schedule H1 inclusions (Pregabalin, Oseltamivir, Zanamivir)
- Debarment of manufacturers (fraud/fabricated documents)
- Antimicrobial prohibition for animal use

**NONE for ~80 notices** — pure regulatory process noise.

## Dedup Strategy

Same as Alerts / FDC / Public Notices:

- Primary key: `document_id` (from `num_id` Base64)
- Secondary: `release_date` watermark
- Tertiary: SHA-256 content hash

## MVP Integration

Reuse `source_category = 'gazette'` in the `documents` table.

Only query scanner against rows where `relevant = true`.

## Recommendation

- ✅ Use existing Pattern A pipeline
- ✅ Aggressive keyword filter (see parse_gazette.py)
- ✅ Download only relevant PDFs
- ❌ Do not build separate scraper — reuse what we have

## Files

websites/cdsco-gazette-notifications/
├── http-requests/
│   ├── gazette_test.py
│   └── output/gazette_page.html
├── html-extraction/
│   ├── parse_gazette.py
│   └── output/
│       ├── gazette_all.json
│       └── gazette_relevant.json
└── findings.md
