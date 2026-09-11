
# CDSCO Findings

## Target

`https://cdsco.gov.in/opencms/opencms/en/Alerts/`
Monthly alerts, NSQ lists, spurious drug reports, medical device alerts.

## HTTP Request

- Result: ✅ Success
- Status: 200
- Server: Wish (CDN)
- Size: ~150 KB
- Problems: none

## HTML Extraction

- Result: ✅ 100% reliable
- Data available:
  - 300 rows (S.No, Title, Release Date, PDF link, Size)
  - No pagination — all rows in one page
  - PDF link is `/download_file_division.jsp?num_id=<base64>`
- Problems: none. `html.parser` is sufficient; no need for lxml.

## DOM Extraction

- Result: Not required. Data is in the initial HTML.

## Automated Browser

- Result: Not required for Alerts page.

## API Endpoint

- Result: None. Data server-rendered.

## PDF Handling

- PDF discovery: `num_id` (Base64) in link → decodes to internal asset ID
- PDF retrieval: endpoint returns a 170-byte HTML wrapper with an 
- Real PDF URL: `https://cdsco.gov.in/opencms/resources/UploadCDSCOWeb/2018/UploadAlertsFiles/<filename>.pdf`
- Requires: parse iframe src, then GET again
- Text extraction: PDF is text-based (verified on NSQ Jan-2025). No OCR needed for NSQ alerts.
- **Document types vary**: policy circulars (mostly image posters) vs. NSQ alerts (tabular text)

## New Document Detection

Reliable identifiers, in order of preference:

1. `document_id` (from `num_id`, integer, stable) ✅
2. `release_date` + normalized `title` ✅
3. Filename extracted from iframe URL ✅
4. SHA-256 of downloaded PDF (last resort — requires download)

## Recommendation

Preferred pipeline for Alerts page:

1. `requests` → Alerts page
2. BeautifulSoup → parse table → records
3. Detect new records by `document_id`
4. For each new: download wrapper → parse iframe → download real PDF
5. PDF text extraction via PyMuPDF or pdfplumber (see next experiment)
6. Store raw PDF + extracted fields + source URL

## Limitations

- Same PDF can mix text pages and image pages — document-type classification required.
- Column mapping within NSQ tables varies page-by-page.
- Some "PDFs" are posters (image-only) and don't belong in the medicine index.
