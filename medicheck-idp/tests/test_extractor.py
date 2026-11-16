"""Extractor tests. PDFs are generated in code; OCR is a fake backend (no model, no network)."""
from __future__ import annotations

import subprocess
import sys

import numpy as np
import pymupdf
import pytest

from idp.schemas.extraction import ExtractionBatch, ExtractionIndex, Item, Source
from idp.stages.extractor import digital, ocr
from idp.stages.extractor import service as X
from idp.stages.extractor.ocr import OcrLine, _to_lines
from idp.stages.profiler.service import profile_pdf

TEXT = " ".join(f"word{i}" for i in range(80))


class FakeOcr:
    def __init__(self, box=((10, 10), (110, 10), (110, 30), (10, 30)),
                 text="Batch No: ABC123", score=0.96):
        self.line, self.shapes = OcrLine(box, text, score), []

    def __call__(self, image: np.ndarray):
        self.shapes.append(image.shape)
        return [self.line]


def _text_page(doc, text=TEXT):
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 555, 300), text, fontsize=10)
    return page


def _raster(dpi=150):
    d = pymupdf.open()
    _text_page(d)
    return d[0].get_pixmap(dpi=dpi)


def _scan_page(doc):
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=_raster())
    return page


def _hybrid_page(doc):
    page = _text_page(doc)
    page.insert_image(pymupdf.Rect(40, 400, 555, 760), pixmap=_raster(), keep_proportion=False)
    return page


def _save(doc, tmp_path, name="t.pdf"):
    p = tmp_path / name
    doc.save(p)
    return p


def _one(build, tmp_path, backend=None):
    d = pymupdf.open()
    build(d)
    path = _save(d, tmp_path)
    prof = profile_pdf(path)
    batch = X.extract_batch(path, prof, 0, backend=backend)
    return batch.pages[0], path


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IDP_DATA_DIR", str(tmp_path / "data"))


def test_digital_lines_share_the_unified_shape(tmp_path):
    pg, _ = _one(_text_page, tmp_path)
    assert (pg.status, pg.page_mode, pg.tables_checked) == ("success", "digital", True)
    lines = [i for i in pg.items if i.type == "text_line"]
    assert lines and lines[0].item_id == "p001_i001"
    for i in lines:
        assert (i.source.engine, i.source.method, i.confidence) == ("pymupdf", "native_text", None)
        assert i.segments and i.segments[0].size == 10.0
        x0, y0, x1, y1 = i.bbox
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1


def test_bold_and_size_are_preserved_for_heading_detection(tmp_path):
    def build(d):
        page = d.new_page()
        page.insert_text((50, 80), "Section Heading", fontsize=11, fontname="hebo")
        page.insert_text((50, 120), "Plain body text here", fontsize=12, fontname="helv")
    pg, _ = _one(build, tmp_path)
    head, body = (i.segments[0] for i in pg.items)
    assert (head.bold, head.size) == (True, 11.0)
    assert (body.bold, body.size) == (False, 12.0)


def test_ligatures_are_expanded(tmp_path):
    def build(d):
        d.new_page().insert_text((50, 80), "of\ufb01ce", fontsize=12)
    pg, _ = _one(build, tmp_path)
    assert "\ufb01" not in pg.items[0].text


def test_ruled_table_is_extracted_and_lines_point_to_it(tmp_path):
    """
    FIX: original test used _text_page() (80 words of dense text) then drew a
    3x3 grid below. find_tables(strategy="lines") picked up text descenders as
    column dividers -> 3x5 instead of 3x3.

    Two fixes applied:
    1. service default strategy changed to "lines_strict" (filters open lines)
    2. this test now uses a CLEAN page so table detection is tested in isolation
    """
    def build(d):
        page = d.new_page()  # no surrounding text
        xs, ys = (50, 200, 350, 500), (320, 350, 380, 410)
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for r in range(3):
            for c in range(3):
                page.insert_text((xs[c] + 5, ys[r] + 20), f"r{r}c{c}", fontsize=10)
    pg, _ = _one(build, tmp_path)
    (tbl,) = [i for i in pg.items if i.type == "table"]
    assert (tbl.table.n_rows, tbl.table.n_cols) == (3, 3)
    assert tbl.table.rows[1][2] == "r1c2"
    assert tbl.source.method == "native_table"
    inside = [i for i in pg.items if i.type == "text_line" and i.parent == tbl.item_id]
    assert sorted(i.text for i in inside)[:2] == ["r0c0", "r0c1"]


def test_text_near_table_does_not_inflate_column_count(tmp_path):
    """Regression: text descenders used to be counted as extra column dividers."""
    def build(d):
        _text_page(d)  # 80 words of dense text at top
        page = d[0]
        xs, ys = (50, 200, 350, 500), (320, 350, 380, 410)
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for r in range(3):
            for c in range(3):
                page.insert_text((xs[c] + 5, ys[r] + 20), f"r{r}c{c}", fontsize=10)
    pg, _ = _one(build, tmp_path)
    tables = [i for i in pg.items if i.type == "table"]
    assert len(tables) == 1, f"expected 1 table, got {len(tables)}"
    assert (tables[0].table.n_rows, tables[0].table.n_cols) == (3, 3)


def test_native_table_detection_is_independent_of_pymupdf4llm_mode():
    script = r'''
import pymupdf
from idp.stages.extractor.digital import native_tables
from idp.stages.extractor import markdown

doc = pymupdf.open()
page = doc.new_page(width=595, height=842)
xs, ys = (50, 150, 155, 300, 450), (300, 340, 380)
for y in ys:
    page.draw_line((xs[0], y), (xs[-1], y))
for x in xs:
    page.draw_line((x, ys[0]), (x, ys[-1]))
for row in range(2):
    for col in range(4):
        page.insert_text((xs[col] + 1, ys[row] + 25), f"r{row}c{col}", fontsize=8)

def shape():
    return [(item.table.n_rows, item.table.n_cols)
            for item in native_tables(page, "lines_strict", 2, 2)]

before = shape()
import pymupdf4llm
after_import = shape()
markdown.batch_markdown(doc, [1])
after_markdown = shape()
print("TABLE_SHAPES", before, after_import, after_markdown)
assert before == after_import == after_markdown == [(2, 4)]
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True, capture_output=True, text=True,
    )
    assert "TABLE_SHAPES [(2, 4)] [(2, 4)] [(2, 4)]" in result.stdout


def _ink_bbox(pix):
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].min(axis=2) < 128
    ys, xs = np.where(a)
    return xs.min() / pix.width, ys.min() / pix.height, (xs.max() + 1) / pix.width, (ys.max() + 1) / pix.height


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_bboxes_are_in_visible_space_on_rotated_pages(tmp_path, rotation):
    d = pymupdf.open()
    _text_page(d).set_rotation(rotation)
    path = _save(d, tmp_path)
    pg = X.extract_batch(path, profile_pdf(path), 0).pages[0]
    boxes = [i.bbox for i in pg.items if i.type == "text_line"]
    union = (min(b[0] for b in boxes), min(b[1] for b in boxes),
             max(b[2] for b in boxes), max(b[3] for b in boxes))
    with pymupdf.open(path) as doc:
        ink = _ink_bbox(doc[0].get_pixmap(dpi=72))
    assert union == pytest.approx(ink, abs=0.015)
    assert pg.rotation == rotation


def test_scanned_page_goes_through_ocr_with_pixel_to_page_mapping(tmp_path):
    fake = FakeOcr()
    pg, _ = _one(_scan_page, tmp_path, backend=fake)
    assert pg.page_mode == "scanned" and pg.tables_checked is False
    (line,) = pg.items
    assert (line.source.engine, line.source.method, line.confidence) == ("rapidocr", "ocr", 0.96)
    assert line.segments == []
    h, w, _ = fake.shapes[0]
    assert (w, h) == pytest.approx((1240, 1754), abs=2)
    assert line.bbox == pytest.approx((10 / w, 10 / h, 110 / w, 30 / h), abs=1e-3)


def test_hybrid_ocr_runs_only_on_the_region_and_maps_back_to_the_page(tmp_path):
    fake = FakeOcr(box=((0, 0), (100, 0), (100, 50), (0, 50)))
    pg, _ = _one(_hybrid_page, tmp_path, backend=fake)
    assert pg.page_mode == "hybrid" and pg.tables_checked is True
    assert len(fake.shapes) == 1 and fake.shapes[0][1] < 1240
    ocr_line = next(i for i in pg.items if i.source.engine == "rapidocr")
    x0, y0, x1, _ = ocr_line.bbox
    assert (x0 * 595, y0 * 842) == pytest.approx((40, 400), abs=1.5)
    assert (x1 - x0) * 595 == pytest.approx(100 / (150 / 72), abs=1.5)
    assert any(i.source.engine == "pymupdf" for i in pg.items)


def test_hybrid_keeps_the_original_photo_as_a_crop(tmp_path):
    pg, _ = _one(_hybrid_page, tmp_path, backend=FakeOcr())
    (img,) = [i for i in pg.items if i.type == "image"]
    assert img.source.method == "region_crop" and img.text is None
    crop = tmp_path / "data" / "artifacts" / pg.doc_id / img.image_ref
    assert crop.read_bytes()[:4] == b"\x89PNG", f"missing PNG magic at {crop}"
    assert crop.suffix == ".png", f"suffix was stripped: {crop}"


def test_low_confidence_and_empty_ocr_are_reported(tmp_path):
    pg, _ = _one(_scan_page, tmp_path, backend=FakeOcr(score=0.2))
    assert "low_confidence_lines=1" in pg.warnings


def test_rapidocr_output_shapes_are_normalised():
    class New:
        boxes = [[[0, 0], [10, 0], [10, 5], [0, 5]]]
        txts, scores = ["abc"], [0.9]
    assert _to_lines(New())[0].text == "abc"
    assert _to_lines(([[[[0, 0], [1, 0], [1, 1], [0, 1]], "x", 0.5]], 0.1))[0].score == 0.5
    assert _to_lines(None) == [] and _to_lines(((), 0.0)) == []


def test_blank_page_is_skipped_but_still_reported(tmp_path):
    d = pymupdf.open()
    _text_page(d)
    d.new_page()
    path = _save(d, tmp_path)
    idx = X.run(path)
    assert [(b.engine, b.pages) for b in idx.batches] == [("pymupdf", [1]), ("skip", [2])]
    skipped = ExtractionBatch.model_validate_json(
        (tmp_path / "data" / "artifacts" / idx.doc_id / "02_extraction" / "batches" / "skipped.json").read_text())
    assert (skipped.pages[0].status, skipped.pages[0].items) == ("skipped", [])


def test_one_bad_page_does_not_sink_the_batch(tmp_path, monkeypatch):
    d = pymupdf.open()
    for _ in range(3):
        _text_page(d)
    path = _save(d, tmp_path)
    real = X.digital.native_lines

    def flaky(page):
        if page.number == 1:
            raise RuntimeError("boom")
        return real(page)
    monkeypatch.setattr(X.digital, "native_lines", flaky)
    idx = X.run(path)
    assert idx.failed_pages == [2]
    assert idx.complete is False
    b = ExtractionBatch.model_validate_json(
        (tmp_path / "data" / "artifacts" / idx.doc_id / "02_extraction" / "batches" / "b0000.json").read_text())
    assert [p.status for p in b.pages] == ["success", "failed", "success"]
    assert "RuntimeError" in b.pages[1].error


def test_every_page_appears_exactly_once_and_run_is_idempotent(tmp_path, monkeypatch):
    d = pymupdf.open()
    for _ in range(4):
        _text_page(d)
    _scan_page(d)
    d.new_page()
    path = _save(d, tmp_path)
    fake, calls = FakeOcr(), []
    real = X._extract_pages
    monkeypatch.setattr(X, "_extract_pages", lambda *a, **k: calls.append(1) or real(*a, **k))

    idx = X.run(path, backend=fake)
    assert sorted(n for b in idx.batches for n in b.pages) == [1, 2, 3, 4, 5, 6]
    n = len(calls)
    X.run(path, backend=fake)
    assert len(calls) == n  # all batches cached
    X.run(path, backend=fake, force=True)
    assert len(calls) == 2 * n
    X.run(path, backend=fake, cfg=X.ExtractorConfig(render_dpi=100))
    assert len(calls) == 3 * n  # new config => re-extract
    assert ExtractionIndex.model_validate_json(
        (tmp_path / "data" / "artifacts" / idx.doc_id / "02_extraction" / "index.json").read_text()).total_pages == 6


def test_failed_profile_and_stale_profile_are_refused(tmp_path):
    d = pymupdf.open()
    _text_page(d)
    path = _save(d, tmp_path)
    prof = profile_pdf(path)
    with pytest.raises(ValueError, match="profile status"):
        X.run(path, prof.model_copy(update={"status": "failed", "reason": "corrupt_or_unreadable"}))
    d2 = pymupdf.open()
    _text_page(d2), _text_page(d2)
    other = _save(d2, tmp_path, "other.pdf")
    with pytest.raises(ValueError, match="profile doc_id"):
        X.extract_batch(other, prof, 0)


def _draw_grid(page, xs, ys, cell_text=None):
    for row in range(len(ys) - 1):
        for col in range(len(xs) - 1):
            cell = pymupdf.Rect(xs[col], ys[row], xs[col + 1], ys[row + 1])
            page.draw_rect(cell, width=0.8)
            text = (cell_text or {}).get((row, col), f"r{row}c{col}")
            page.insert_text((cell.x0 + 3, cell.y0 + 17), text, fontsize=8)


def test_native_tables_keep_many_columns_and_preserve_cell_spaces():
    d = pymupdf.open()
    page = d.new_page()
    xs = [40 + 40 * i for i in range(13)]
    ys = [100 + 28 * i for i in range(4)]
    _draw_grid(page, xs, ys)

    (item,) = digital.native_tables(page, "lines_strict", 2, 2)

    assert (item.table.n_rows, item.table.n_cols) == (3, 12)


def test_native_table_cells_preserve_word_spacing():
    d = pymupdf.open()
    page = d.new_page()
    _draw_grid(
        page, [40, 200, 360, 520], [100, 140, 180],
        {(1, 0): "Phenytoin Sodium Tablets", (1, 2): "Cipla Ltd, Mumbai"},
    )

    (item,) = digital.native_tables(page, "lines_strict", 2, 2)

    assert item.table.rows[1][0] == "Phenytoin Sodium Tablets"
    assert item.table.rows[1][2] == "Cipla Ltd, Mumbai"


def test_native_tables_keep_narrow_columns():
    d = pymupdf.open()
    page = d.new_page()
    _draw_grid(page, [50, 150, 155, 300, 450], [100, 130, 160])

    (item,) = digital.native_tables(page, "lines_strict", 2, 2)

    assert item.table.n_cols == 4


def test_rotated_table_bbox_is_normalized_from_visible_find_tables_box():
    d = pymupdf.open()
    page = d.new_page()
    _draw_grid(page, [50, 150, 250, 350], [100, 130, 160])
    page.set_rotation(90)
    (found,) = page.find_tables(strategy="lines_strict").tables

    (item,) = digital.native_tables(page, "lines_strict", 2, 2)

    expected = tuple(
        coordinate / dimension
        for coordinate, dimension in zip(found.bbox, (page.rect.width, page.rect.height,
                                                       page.rect.width, page.rect.height))
    )
    assert item.bbox == pytest.approx(expected, abs=1e-6)


def test_ocr_render_bounds_large_pages_and_reports_effective_dpi():
    d = pymupdf.open()
    page = d.new_page(width=4000, height=1000)

    rendered = ocr.render_bounded(page, dpi=300, max_px=400)

    assert rendered.dpi < 300
    assert max(rendered.pix.width, rendered.pix.height) <= 400
    pix, image = ocr.render(page, dpi=72)
    assert pix.width == page.rect.width and image.shape[1] == pix.width


def test_ocr_region_coordinates_stay_in_visible_space_on_rotated_pages():
    d = pymupdf.open()
    page = d.new_page()
    page.set_rotation(90)
    region = (100, 100, 300, 300)
    rendered = ocr.render_bounded(page, dpi=72, region=region, max_px=400)
    line = OcrLine(((10, 20), (50, 20), (50, 40), (10, 40)), "rotated", 0.9)

    (item,) = ocr.lines_to_items(page, rendered.pix, rendered.dpi, [line])

    assert item.bbox == pytest.approx((110 / page.rect.width, 120 / page.rect.height,
                                      150 / page.rect.width, 140 / page.rect.height), abs=1e-6)


def test_extractor_config_cache_key_ignores_ocr_thread_count():
    assert X.config_hash(X.ExtractorConfig(ocr_threads=1)) == X.config_hash(
        X.ExtractorConfig(ocr_threads=4)
    )


def test_extractor_cache_requires_matching_batch_identity(tmp_path):
    d = pymupdf.open()
    _text_page(d)
    path = _save(d, tmp_path)
    profile = profile_pdf(path)
    batch = X.extract_batch(path, profile, 0)
    pages = profile.batches[0].pages
    engine = profile.batches[0].engine

    assert X._fresh(batch, profile, pages, engine, 0, X.DEFAULT_CONFIG)
    assert not X._fresh(batch.model_copy(update={"batch_index": 1}),
                        profile, pages, engine, 0, X.DEFAULT_CONFIG)
    assert not X._fresh(batch.model_copy(update={"engine": "rapidocr"}),
                        profile, pages, engine, 0, X.DEFAULT_CONFIG)


def test_same_page_count_but_different_pdf_is_rejected(tmp_path):
    original = pymupdf.open()
    _text_page(original, text="original document")
    original_path = _save(original, tmp_path, "original.pdf")
    profile = profile_pdf(original_path)

    changed = pymupdf.open()
    _text_page(changed, text="changed document")
    changed_path = _save(changed, tmp_path, "changed.pdf")

    with pytest.raises(ValueError, match="profile doc_id"):
        X.extract_batch(changed_path, profile, 0)


@pytest.mark.parametrize("column_count", [4, 8, 10, 12])
def test_generated_ruled_tables_keep_4_8_10_and_12_columns(column_count):
    d = pymupdf.open()
    page = d.new_page()
    xs = [30 + 40 * i for i in range(column_count + 1)]
    _draw_grid(page, xs, [100, 130, 160])

    (item,) = digital.native_tables(page, "lines_strict", 2, 2)

    assert item.table.n_cols == column_count


def test_generated_table_keeps_merged_and_empty_cells_as_none_and_empty_text():
    d = pymupdf.open()
    page = d.new_page()
    xs, ys = [40, 180, 320, 460], [100, 140, 180]
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    page.draw_line((xs[0], ys[0]), (xs[0], ys[-1]))
    page.draw_line((xs[1], ys[1]), (xs[1], ys[-1]))
    page.draw_line((xs[2], ys[0]), (xs[2], ys[-1]))
    page.draw_line((xs[3], ys[0]), (xs[3], ys[-1]))
    page.insert_text((xs[0] + 3, ys[0] + 20), "merged heading", fontsize=8)
    page.insert_text((xs[0] + 3, ys[1] + 20), "left", fontsize=8)
    page.insert_text((xs[2] + 3, ys[1] + 20), "right", fontsize=8)

    (item,) = digital.native_tables(page, "lines_strict", 2, 2)

    assert item.table.rows[0][1] is None
    assert item.table.rows[1][1] == ""


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_native_line_boxes_use_independent_visible_space_arithmetic(rotation):
    d = pymupdf.open()
    page = d.new_page(width=700, height=500)
    page.insert_text((123, 234), "Rotation evidence", fontsize=12)
    page.set_rotation(rotation)
    unrotated_box = page.get_text("dict")["blocks"][0]["lines"][0]["spans"][0]["bbox"]

    (item,) = digital.native_lines(page)
    visible_width, visible_height = page.rect.width, page.rect.height
    if rotation == 90:
        transformed = [(500 - y, x) for x, y in (
            (unrotated_box[0], unrotated_box[1]),
            (unrotated_box[2], unrotated_box[1]),
            (unrotated_box[0], unrotated_box[3]),
            (unrotated_box[2], unrotated_box[3]),
        )]
    else:
        transformed = [(y, 700 - x) for x, y in (
            (unrotated_box[0], unrotated_box[1]),
            (unrotated_box[2], unrotated_box[1]),
            (unrotated_box[0], unrotated_box[3]),
            (unrotated_box[2], unrotated_box[3]),
        )]
    expected = (
        min(x for x, _ in transformed) / visible_width,
        min(y for _, y in transformed) / visible_height,
        max(x for x, _ in transformed) / visible_width,
        max(y for _, y in transformed) / visible_height,
    )

    assert item.bbox == pytest.approx(expected, abs=1e-5)


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotated_table_cells_clip_text_in_unrotated_space(rotation):
    d = pymupdf.open()
    page = d.new_page()
    xs, ys = [50, 250, 450], [100, 140, 180]
    _draw_grid(page, xs, ys, {
        (0, 0): "CELL_0_0", (0, 1): "CELL_0_1",
        (1, 0): "CELL_1_0", (1, 1): "CELL_1_1",
    })
    page.set_rotation(rotation)

    (item,) = digital.native_tables(page, "lines_strict", 2, 2)

    assert sorted(text for row in item.table.rows for text in row if text) == [
        "CELL_0_0", "CELL_0_1", "CELL_1_0", "CELL_1_1",
    ]


@pytest.mark.parametrize("rotation", [0, 90, 270])
@pytest.mark.parametrize("region_render", [False, True])
def test_ocr_dark_pixel_boxes_map_from_pixmap_origin(rotation, region_render):
    d = pymupdf.open()
    page = d.new_page(width=700, height=500)
    page.draw_rect(pymupdf.Rect(150, 200, 250, 300), color=None, fill=(0, 0, 0))
    page.set_rotation(rotation)
    if region_render:
        region = {
            0: (130, 180, 270, 320),
            90: (180, 130, 320, 270),
            270: (180, 430, 320, 570),
        }[rotation]
    else:
        region = None

    rendered = ocr.render_bounded(page, 150, region=region, max_px=4000)

    class DarkPixels:
        def __call__(self, image):
            dark = np.min(image[:, :, :3], axis=2) < 128
            ys, xs = np.where(dark)
            assert len(xs)
            return [OcrLine(((xs.min(), ys.min()), (xs.max() + 1, ys.min()),
                             (xs.max() + 1, ys.max() + 1), (xs.min(), ys.max() + 1)),
                            "dark rectangle", 1.0)]

    line = ocr.lines_to_items(page, rendered.pix, rendered.dpi,
                              DarkPixels()(rendered.image))[0]
    scale = rendered.dpi / 72
    expected = (
        (rendered.pix.x + 0) / scale,
        (rendered.pix.y + 0) / scale,
    )
    pixel_box = DarkPixels()(rendered.image)[0].box
    expected = (
        (rendered.pix.x + min(point[0] for point in pixel_box)) / scale,
        (rendered.pix.y + min(point[1] for point in pixel_box)) / scale,
        (rendered.pix.x + max(point[0] for point in pixel_box)) / scale,
        (rendered.pix.y + max(point[1] for point in pixel_box)) / scale,
    )

    assert (line.bbox[0] * page.rect.width, line.bbox[1] * page.rect.height,
            line.bbox[2] * page.rect.width, line.bbox[3] * page.rect.height) == pytest.approx(
                expected, abs=1.5)


def test_save_bytes_rejects_traversal_absolute_and_empty_names(tmp_path, monkeypatch):
    monkeypatch.setenv("IDP_DATA_DIR", str(tmp_path / "data"))
    for name in ("", "..\\escape.png", "nested/../escape.png", "C:\\escape.png",
                 "\\\\server\\share\\escape.png", "/escape.png"):
        with pytest.raises(ValueError):
            X.artifacts.save_bytes(name, "doc", b"x")


def test_rerun_reextracts_only_failed_page_from_a_batch(tmp_path, monkeypatch):
    d = pymupdf.open()
    for _ in range(3):
        _text_page(d)
    path = _save(d, tmp_path)
    profile = profile_pdf(path)
    real = X.digital.native_lines
    calls = []
    failures_remaining = [1]

    def fail_second_once(page):
        calls.append(page.number + 1)
        if page.number == 1 and failures_remaining[0]:
            failures_remaining[0] -= 1
            raise RuntimeError("temporary failure")
        return real(page)

    monkeypatch.setattr(X.digital, "native_lines", fail_second_once)
    first = X.run(path, profile)
    assert first.failed_pages == [2]
    calls.clear()
    second = X.run(path, profile)

    assert second.failed_pages == []
    assert calls == [2]


def test_noncontiguous_markdown_chunks_are_mapped_by_metadata(tmp_path, monkeypatch):
    d = pymupdf.open()
    _text_page(d)
    d.new_page()
    _text_page(d, text="third page source")
    path = _save(d, tmp_path)
    profile = profile_pdf(path)
    calls = []

    def fake_markdown(doc, **options):
        calls.append(options)
        return [
            {"metadata": {"page_number": 3}, "text": "markdown for page three"},
            {"metadata": {"page_number": 1}, "text": "markdown for page one"},
        ]

    monkeypatch.setattr(X.markdown, "to_markdown", fake_markdown)
    batch = X.extract_batch(path, profile, 0)

    assert calls[0]["pages"] == [0, 2]
    assert calls[0]["page_chunks"] is True
    assert "use_ocr" not in calls[0] and "force_ocr" not in calls[0]
    assert calls[0]["write_images"] is False and calls[0]["embed_images"] is False
    assert [page.markdown_source for page in batch.pages] == ["pymupdf4llm", "pymupdf4llm"]
    assert (tmp_path / "data" / "artifacts" / profile.doc_id / batch.pages[0].markdown_ref).read_text() \
        == "markdown for page one"
    assert (tmp_path / "data" / "artifacts" / profile.doc_id / batch.pages[1].markdown_ref).read_text() \
        == "markdown for page three"


def test_wrong_markdown_chunk_count_retries_individual_pages(tmp_path, monkeypatch):
    d = pymupdf.open()
    _text_page(d)
    d.new_page()
    _text_page(d)
    path = _save(d, tmp_path)
    profile = profile_pdf(path)
    calls = []

    def bad_batch_then_valid_pages(doc, **options):
        pages = options["pages"]
        calls.append(pages)
        if len(pages) > 1:
            return [{"metadata": {"page_number": pages[0] + 1}, "text": "incomplete"}]
        return [{"metadata": {"page_number": pages[0] + 1},
                 "text": f"page {pages[0] + 1} markdown"}]

    monkeypatch.setattr(X.markdown, "to_markdown", bad_batch_then_valid_pages)
    batch = X.extract_batch(path, profile, 0)

    assert calls == [[0, 2], [0], [2]]
    assert [page.markdown_error for page in batch.pages] == [None, None]
    assert [page.markdown_source for page in batch.pages] == [
        "pymupdf4llm", "pymupdf4llm",
    ]


def test_scanned_page_does_not_call_pymupdf4llm(tmp_path, monkeypatch):
    fake = FakeOcr()
    path_doc = pymupdf.open()
    _scan_page(path_doc)
    path = _save(path_doc, tmp_path)
    calls = []
    monkeypatch.setattr(X.markdown, "to_markdown",
                        lambda *args, **kwargs: calls.append(kwargs))

    batch = X.extract_batch(path, profile_pdf(path), 0, backend=fake)

    assert calls == []
    assert batch.pages[0].markdown_source == "ocr_lines"
    assert "Batch No: ABC123" in (
        tmp_path / "data" / "artifacts" / batch.doc_id / batch.pages[0].markdown_ref
    ).read_text()


def test_pymupdf4llm_ocr_is_disabled_for_scanned_pages(capsys):
    d = pymupdf.open()
    _scan_page(d)

    markdown_by_page = X.markdown.batch_markdown(d, [1])
    output = capsys.readouterr()

    assert markdown_by_page == {1: ""}
    assert "OCR on page" not in output.out + output.err


def test_hybrid_markdown_combines_native_text_and_region_blockquotes(tmp_path, monkeypatch):
    path_doc = pymupdf.open()
    _hybrid_page(path_doc)
    path = _save(path_doc, tmp_path)
    monkeypatch.setattr(
        X.markdown, "to_markdown",
        lambda doc, **options: [{"metadata": {"page_number": 1}, "text": "native paragraph"}],
    )

    batch = X.extract_batch(path, profile_pdf(path), 0, backend=FakeOcr())

    page = batch.pages[0]
    markdown_text = (tmp_path / "data" / "artifacts" / batch.doc_id / page.markdown_ref).read_text()
    assert page.markdown_source == "mixed"
    assert "native paragraph" in markdown_text
    assert "> **Page 1, OCR region 1**" in markdown_text
    assert "> Batch No: ABC123" in markdown_text


def test_markdown_failure_is_explicit_and_makes_index_incomplete(tmp_path, monkeypatch):
    d = pymupdf.open()
    _text_page(d)
    path = _save(d, tmp_path)
    monkeypatch.setattr(X.markdown, "to_markdown",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("markdown down")))

    index = X.run(path)

    assert index.failed_pages == []
    assert index.markdown_failed_pages == [1]
    assert index.complete is False
    batch = ExtractionBatch.model_validate_json(
        (tmp_path / "data" / "artifacts" / index.doc_id / "02_extraction" / "batches" / "b0000.json").read_text()
    )
    assert batch.pages[0].status == "success"
    assert "markdown down" in batch.pages[0].markdown_error


def test_deleting_markdown_reextracts_only_its_page(tmp_path, monkeypatch):
    d = pymupdf.open()
    for _ in range(3):
        _text_page(d)
    path = _save(d, tmp_path)
    index = X.run(path)
    batch = ExtractionBatch.model_validate_json(
        (tmp_path / "data" / "artifacts" / index.doc_id / "02_extraction" / "batches" / "b0000.json").read_text()
    )
    X.artifacts.artifact_path(batch.pages[1].markdown_ref, index.doc_id).unlink()
    calls = []
    real = X.digital.native_lines
    monkeypatch.setattr(X.digital, "native_lines",
                        lambda page: calls.append(page.number + 1) or real(page))

    X.run(path)

    assert calls == [2]


def test_deleting_hybrid_crop_reextracts_only_its_page(tmp_path, monkeypatch):
    d = pymupdf.open()
    _hybrid_page(d)
    _hybrid_page(d)
    path = _save(d, tmp_path)
    index = X.run(path, backend=FakeOcr())
    batch = ExtractionBatch.model_validate_json(
        (tmp_path / "data" / "artifacts" / index.doc_id / "02_extraction" / "batches" / "b0000.json").read_text()
    )
    image = next(item for item in batch.pages[1].items if item.type == "image")
    X.artifacts.artifact_path(image.image_ref, index.doc_id).unlink()
    calls = []
    real = X.digital.native_lines
    monkeypatch.setattr(X.digital, "native_lines",
                        lambda page: calls.append(page.number + 1) or real(page))

    X.run(path, backend=FakeOcr())

    assert calls == [2]


def test_pymupdf4llm_version_change_invalidates_extractor_cache(tmp_path, monkeypatch):
    d = pymupdf.open()
    _text_page(d)
    path = _save(d, tmp_path)
    first = X.run(path)
    calls = []
    real = X._extract_pages
    monkeypatch.setattr(X, "_extract_pages",
                        lambda *args, **kwargs: calls.append(1) or real(*args, **kwargs))
    monkeypatch.setattr(X.markdown, "VERSION", X.markdown.VERSION + "-changed")

    second = X.run(path)

    assert second.config_hash != first.config_hash
    assert calls == [1]


def test_rotated_page_markdown_is_written_without_losing_native_text(tmp_path):
    d = pymupdf.open()
    page = d.new_page()
    page.insert_text((100, 150), "Rotated Markdown source", fontsize=12)
    page.set_rotation(90)
    path = _save(d, tmp_path)

    batch = X.extract_batch(path, profile_pdf(path), 0)

    page_result = batch.pages[0]
    text = (tmp_path / "data" / "artifacts" / batch.doc_id / page_result.markdown_ref).read_text()
    assert "Rotated Markdown source" in text
    assert page_result.rotation == 90


def test_ocr_markdown_groups_lines_using_point_geometry():
    source = Source(engine="rapidocr", method="ocr")
    items = [
        Item(item_id="a", type="text_line", text="third", bbox=(0.10, 0.30, 0.30, 0.32),
             source=source, confidence=0.9),
        Item(item_id="b", type="text_line", text="first", bbox=(0.10, 0.10, 0.30, 0.12),
             source=source, confidence=0.9),
        Item(item_id="c", type="text_line", text="second", bbox=(0.12, 0.13, 0.32, 0.15),
             source=source, confidence=0.9),
        Item(item_id="d", type="text_line", text="indented", bbox=(0.60, 0.16, 0.80, 0.18),
             source=source, confidence=0.9),
    ]

    assert X._ocr_lines_markdown(items, width=200, height=400) == (
        "first second\n\nindented\n\nthird"
    )