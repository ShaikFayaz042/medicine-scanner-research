"""OCR behaviour on generated scanned pages (real RapidOCR models; skipped when rapidocr is missing)."""

import io

import pymupdf
import pytest

from data_processing_service.extractor import ocr as page_ocr
from data_processing_service.extractor import run as extractor

pytestmark = pytest.mark.skipif(not page_ocr.ocr_available(), reason="rapidocr is not installed")

ROWS = [
    ("S. No.", "Name of the product", "Batch No."),
    ("1.", "Paracetamol Tablets IP 500 mg", "PCT2401"),
    ("2.", "Insulin Aspart solution for injection", "RR726A8"),
    ("3.", "Cefixime Tablets IP 200 mg", "CFX24118"),
]


def _scanned_pdf(rotate: int = 0, stamp: str | None = None) -> bytes:
    """Draw a ruled table, rasterize it like a scanner, and return an image-only PDF."""
    source = pymupdf.open()
    page = source.new_page(width=595, height=842)
    page.insert_text((60, 80), "Alert on theft of multiple drug products during transit", fontsize=12)
    xs, top, row_height = (50, 100, 380, 545), 120, 30
    for index, row in enumerate(ROWS):
        y = top + index * row_height
        for column, value in enumerate(row):
            page.insert_text((xs[column] + 5, y + 20), value, fontsize=10)
    for index in range(len(ROWS) + 1):
        page.draw_line((xs[0], top + index * row_height), (xs[-1], top + index * row_height))
    for x in xs:
        page.draw_line((x, top), (x, top + len(ROWS) * row_height))
    pix = page.get_pixmap(dpi=200)
    image = pymupdf.Pixmap(pix, 0) if pix.alpha else pix
    scanned = pymupdf.open()
    width, height = (842, 595) if rotate in (90, 270) else (595, 842)
    out = scanned.new_page(width=width, height=height)
    out.insert_image(out.rect, stream=image.tobytes("png"), rotate=rotate)
    if stamp:
        out.insert_text((20, height - 10), stamp, fontsize=7)
    buffer = io.BytesIO()
    scanned.save(buffer)
    return buffer.getvalue()


def _extract(pdf_bytes: bytes) -> dict:
    return extractor._extract_document_from_bytes(pdf_bytes, "src/alerts/scan.pdf", "src")


def test_english_model_keeps_spaces_between_words():
    page = _extract(_scanned_pdf())["pages"][0]

    assert page["method"] == "rapidocr"
    assert "Alert on theft of multiple drug products" in page["text"]
    assert "Paracetamol Tablets IP 500 mg" in page["text"]


def test_scanned_ruled_table_becomes_table_rows():
    payload = _extract(_scanned_pdf())
    page = payload["pages"][0]

    assert page["table_strategy"] == "ocr_grid"
    rows = [row["cells"] for row in page["tables"]]
    assert rows[0] == ["S. No.", "Name of the product", "Batch No."]
    assert rows[1] == ["1.", "Paracetamol Tablets IP 500 mg", "PCT2401"]
    assert rows[2][2] == "RR726A8"
    assert payload["tables"][0]["page"] == 1


def test_sideways_scan_is_rotated_before_reading():
    page = _extract(_scanned_pdf(rotate=90))["pages"][0]

    assert page["ocr"]["rotation"] in (90, 270)
    assert "Paracetamol Tablets IP 500 mg" in page["text"]
    assert any(row["cells"][-1] == "CFX24118" for row in page["tables"])


def test_scan_with_small_text_layer_is_still_ocred():
    page = _extract(_scanned_pdf(stamp="Digitally signed e-Office File No. 29/NSQ/2024"))["pages"][0]

    assert page["method"] == "rapidocr"
    assert page["ocr"]["reason"] == "image_page_with_sparse_text"
    assert "e-Office" in page["text_layer"]
    assert "Paracetamol Tablets IP 500 mg" in page["text"]


def test_ocr_lines_keep_boxes_and_scores_in_pdf_points():
    page = _extract(_scanned_pdf())["pages"][0]
    line = next(line for line in page["ocr"]["lines"] if line["text"] == "PCT2401")

    x0, y0, x1, y1 = line["bbox"]
    assert 380 < x0 < x1 < 545 and 150 < y0 < y1 < 180
    assert 0.5 < line["score"] <= 1.0


def test_ocr_engine_is_created_once(monkeypatch):
    created = []
    original = page_ocr.RapidOCR
    monkeypatch.setattr(page_ocr, "_ENGINE", None)
    monkeypatch.setattr(page_ocr, "RapidOCR", lambda **kwargs: created.append(kwargs) or original(**kwargs))

    _extract(_scanned_pdf())
    _extract(_scanned_pdf())

    assert len(created) == 1
    assert created[0]["params"]["Rec.lang_type"] == page_ocr.LangRec.EN


# --- Tables whose ruling lines are dashed or broken (rebuilt from text positions) --------------------


def _box(text, x0, y0, x1=None, height=30):
    return {"text": text, "bbox": [x0, y0, x1 if x1 is not None else x0 + 12 * len(text), y0 + height], "score": 0.95}


LAYOUT_HEADER = [_box("S.No.", 90, 100), _box("Name of Drug", 220, 100), _box("Batch No.", 520, 100),
                 _box("Reason for failure", 980, 100), _box("Drawn By", 1240, 100)]


def _record(serial, top, product, batch, reason, drawn):
    lines = [_box(product, 220, top), _box(batch, 520, top), _box(reason, 980, top), _box(drawn, 1240, top)]
    return ([_box(serial, 100, top)] if serial else []) + lines + [_box("Mfg dt: 07/2020", 520, top + 40)]


def test_layout_table_rows_start_at_each_serial_number():
    lines = LAYOUT_HEADER + _record("1.", 200, "Sestil AD Tablets", "B. No.: CST-75", "Assay", "CDSCO Hyderabad") \
        + _record("2.", 320, "Alusil Tablets", "B. No.: ACT801", "Dissolution", "CDSCO Hyderabad")

    table, columns, body_top = page_ocr.table_from_layout(lines)

    assert table[0] == ["S.No.", "Name of Drug", "Batch No.", "Reason for failure", "Drawn By"]
    assert table[1] == ["1.", "Sestil AD Tablets", "B. No.: CST-75\nMfg dt: 07/2020", "Assay", "CDSCO Hyderabad"]
    assert table[2][0] == "2." and table[2][1] == "Alusil Tablets"
    assert len(columns) == 5 and body_top == 130


def test_first_data_row_without_a_read_serial_is_not_swallowed_into_the_header():
    lines = LAYOUT_HEADER + _record("", 200, "Sestil AD Tablets", "B. No.: CST-75", "Assay", "CDSCO") \
        + _record("2.", 320, "Alusil Tablets", "B. No.: ACT801", "Dissolution", "CDSCO")

    _, _, body_top = page_ocr.table_from_layout(lines)
    table, _, _ = page_ocr.table_from_layout(lines, extra_serials=[_box("1.", 100, 200)])

    assert body_top == 130
    assert [row[0] for row in table[1:]] == ["1.", "2."]
    assert table[1][2].startswith("B. No.: CST-75")


def test_data_row_full_of_header_words_is_not_taken_as_a_header():
    previous_page = [dict(column) for column in page_ocr.table_from_layout(
        LAYOUT_HEADER + _record("1.", 200, "X", "B. No.: A1", "Assay", "CDSCO"))[1]]
    lines = _record("28.", 100, "Lorazepam Injection IP 2 mg/ml", "B. No.: KLLO0002 Mfg dt: 02/2020",
                    "Assay of Lorazepam", "Drug Control Department") \
        + _record("29.", 300, "Maxobal Injection", "B. No.: HL-403A", "Particulate Matter", "Drug Control")

    table, columns, _ = page_ocr.table_from_layout(lines, previous_page)

    assert columns == previous_page
    assert [row[0] for row in table] == ["28.", "29."]


def test_continuation_page_uses_previous_columns_and_keeps_text_above_the_first_serial():
    _, columns, _ = page_ocr.table_from_layout(LAYOUT_HEADER + _record("1.", 200, "X", "B. No.: A1", "Assay", "CDSCO"))
    lines = [_box("Haryana.", 520, 20)] + _record("5.", 100, "Atorvastatin Tablets", "B. No.: AVBT802", "Dissolution", "CDSCO")

    table, _, _ = page_ocr.table_from_layout(lines, columns)

    assert table[0] == ["", "", "Haryana.", "", ""]
    assert table[1][0] == "5."


def test_stray_ones_from_ruling_fragments_are_not_serials():
    candidates = [_box("2.", 100, 100), _box("1", 100, 160), _box("3.", 100, 300), _box("3", 100, 305),
                  _box("1", 100, 400), _box("4", 100, 500)]

    assert [line["text"] for line in page_ocr._sequential_serials(candidates)] == ["2.", "3.", "4"]


def _dashed_table_pdf() -> bytes:
    """A scan whose table is drawn with dashed rules and small serial numbers, like the 2021 drug alert lists."""
    rows = [("S.No.", "Name of Drug", "Batch No.", "Reason for failure", "Drawn By"),
            ("1.", "Sestil AD Tablets", "CST-75", "Assay", "CDSCO Hyderabad"),
            ("2.", "Alusil Tablets", "ACT801", "Dissolution", "CDSCO Hyderabad"),
            ("3.", "Belitra 200 Capsules", "AC20084", "Dissolution", "CDSCO Hyderabad")]
    source = pymupdf.open()
    page = source.new_page(width=595, height=842)
    xs, top, row_height = (40, 80, 230, 330, 450, 560), 100, 60
    for index, row in enumerate(rows):
        for column, value in enumerate(row):
            page.insert_text((xs[column] + 5, top + index * row_height + 20), value, fontsize=10 if column else 8)
    for index in range(len(rows) + 1):
        page.draw_line((xs[0], top + index * row_height), (xs[-1], top + index * row_height), dashes="[3 6] 0")
    for x in xs:
        page.draw_line((x, top), (x, top + len(rows) * row_height), dashes="[3 6] 0")
    image = page.get_pixmap(dpi=200)
    scanned = pymupdf.open()
    out = scanned.new_page(width=595, height=842)
    out.insert_image(out.rect, stream=image.tobytes("png"))
    return scanned.tobytes()


def test_scanned_table_with_dashed_rules_is_rebuilt_from_text_positions():
    page = _extract(_dashed_table_pdf())["pages"][0]

    rows = [row["cells"] for row in page["tables"]]
    assert page["table_strategy"] == "ocr_layout"
    assert [row[0].rstrip(".") for row in rows[1:]] == ["1", "2", "3"]
    assert rows[2][1:3] == ["Alusil Tablets", "ACT801"]
    assert page["ocr"]["layout"] and len(page["ocr"]["layout"]) == 5
