
# CDSCO FDC — Research Findings

## Target

`https://cdsco.gov.in/opencms/opencms/en/Drugs/FDC/`

Fixed Dose Combination approvals, prohibitions, restrictions, and
regulatory notices. Relevant to the Medicine Scanner because it tells us
which drug combinations are legally permitted vs. prohibited/restricted
in India.

## Page Structure (Verified)

The page uses Bootstrap tabs. **All four tabs' data is present in the
initial HTML response** — no JavaScript, no XHR, no tab-clicking required.

| Tab (visible)         | HTML container | Table ID      | Rows | Tested             |
| --------------------- | -------------- | ------------- | ---- | ------------------ |
| Alerts                | `#tab1`      | `#example`  | 2    | ✅ 2/2             |
| News                  | `#tab2`      | `#example1` | 10   | ✅ 2/10            |
| Public Notices        | `#tab3`      | `#example2` | 65   | ✅ 1/65            |
| Gazette Notifications | `#tab4`      | `#example3` | 2    | ✅ 2/2             |
| **Total**       |                |               | 79   | **7 tested** |

Coverage statement: **every tab was tested** with at least one real PDF
download. High-value tabs (Gazette, News) were tested more thoroughly.

## HTTP Request

- Result: ✅ Success
- Status: 200
- Size: ~112 KB
- Server: Wish
- Content-Type: text/html;charset=UTF-8
- Problems: None

## HTML Extraction

- Result: ✅ 100% reliable (79/79 rows)
- Data fields: S.No, Title, Release Date, PDF link, PDF size
- PDF link pattern: `/download_file_division.jsp?num_id=<base64>` — identical to Alerts page
- Document ID: Base64-decoded from `num_id`, stable integer
- Problems: None. `html.parser` is sufficient.

## API / XHR

- Result: Not required. All data server-rendered.

## DOM Extraction / Browser Automation

- Result: Not required. All four tabs are in the initial HTML.
- Tab switching is pure CSS (`display: none`) — BeautifulSoup reads
  all four tables regardless.

## PDF Handling — Verified Downloads (7/7 success)

| Tab            | document_id | Declared | Actual    | Storage folder                   |
| -------------- | ----------- | -------- | --------- | -------------------------------- |
| Alerts         | 14567       | 323 KB   | 322.5 KB  | `UploadAlertsFiles/`           |
| Alerts         | 3251        | 198 KB   | 197.4 KB  | `UploadAlertsFiles/`           |
| Gazette        | 14519       | 1466 KB  | 1465.5 KB | `UploadGazette_Notifications/` |
| Gazette        | 3170        | 1964 KB  | 1963.4 KB | `UploadGazette_Notifications/` |
| News           | 14514       | 42 KB    | 41.9 KB   | `UploadNewsFiles/`             |
| News           | 12087       | 272 KB   | 271.4 KB  | `UploadNewsFiles/`             |
| Public Notices | 13292       | 433 KB   | 432.5 KB  | `UploadPublic_NoticesFiles/`   |

All files start with `%PDF-` magic bytes (versions 1.3 – 1.7).
Declared sizes match actual within ~1%.

**Common PDF delivery mechanism:**

1. GET `download_file_division.jsp?num_id=<base64>`
2. Response: 170-byte HTML wrapper containing `<iframe src="...">`
3. Extract iframe src → real PDF URL under `.../UploadCDSCOWeb/2018/<Folder>/<file>.pdf`
4. GET that URL → `application/pdf` bytes

Our existing `pdf_handler.py` (from the CDSCO Alerts MVP) handles this
pattern **without modification**.

## New Document Detection

Identical strategy to CDSCO Alerts page:

1. **Primary:** `document_id` (Base64-decoded from `num_id`) — stable, unique, monotonic
2. **Secondary:** `release_date` watermark (parsed as real `datetime`)
3. **Last resort:** SHA-256 of downloaded PDF

Note: `document_id` appears to be **globally unique across CDSCO** —
an FDC Alerts tab document (14567) and a standalone Alerts page document
share the same folder and ID space. This means a single `document_id`
index deduplicates across all CDSCO sources.

## Recommendation

**Method:** Direct HTTP + BeautifulSoup (same as Alerts page).

**Reason:**

- Server returns complete HTML with all four tabs
- PDF links are present directly in the initial HTML
- No JavaScript rendering required
- Stable document IDs available for dedup
- Same iframe-wrapper PDF resolution as Alerts
- Browser automation would add zero value

**Recommended priority order for the MVP pipeline**
(based on regulatory authority, not row count):

1. **Gazette Notifications** — legal authority. The actual S.O. notifications
   under Section 26A of Drugs & Cosmetics Act that make a drug combination
   illegal. Highest evidence value.
2. **News** — informational summaries. Fast to read, useful for alerts,
   but not the underlying legal instrument.
3. **Public Notices** — regulatory process (FDC regularisation, Kokate
   Committee evaluations). Useful for context, less directly drug-verifying.
4. **Alerts** — legacy process notes from 2014. Low value.

## Comparison to CDSCO Alerts Page

| Aspect                    | Alerts page                               | FDC page                          |
| ------------------------- | ----------------------------------------- | --------------------------------- |
| HTTP fetch                | ✅ 200 OK                                 | ✅ 200 OK                         |
| Server-rendered           | ✅ Yes                                    | ✅ Yes                            |
| Number of tables          | 1                                         | 4 (tabs)                          |
| Rows                      | 300                                       | 79                                |
| PDF link pattern          | `download_file_division.jsp?num_id=...` | Same                              |
| PDF wrapper + iframe      | ✅ Yes                                    | ✅ Yes                            |
| Same`pdf_handler` works | ✅                                        | ✅                                |
| Browser automation needed | ❌ No                                     | ❌ No                             |
| Dedup key                 | `document_id`                           | `document_id` (globally shared) |
| Pagination                | None (300 rows on one page)               | None (79 rows total)              |

## Limitations / Notes

- Some titles contain HTML entity artifacts (e.g. `Ã¢Â€Â˜SUGAMÃ¢Â€Â™`) —
  same as Alerts page; handle at normalization stage.
- Oldest FDC PDFs date back to 2013; newest to 2026.
- CDSCO lists them reverse-chronologically.
- The wrapper HTML is ~170 bytes; the actual PDF is fetched from the
  iframe src. Our resolver handles this with one recursive call.

## MVP Priority

**HIGH.** FDC prohibition and restriction data is directly useful for
verifying whether a scanned medicine contains legally permitted
combinations. Combined with the Alerts page, this gives us two high-value
CDSCO data sources sharing one scraper, one PDF resolver, and one dedup key.

## Files
