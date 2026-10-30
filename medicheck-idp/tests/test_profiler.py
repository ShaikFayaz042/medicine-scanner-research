"""Profiler tests. PDFs are generated in code: no binary fixtures in the repo."""
from __future__ import annotations

import pymupdf
import pytest

from idp.schemas.profile import DocProfile
from idp.stages.profiler import service as S
from idp.stages.profiler.service import ProfilerConfig, Sig, classify, garbled_ratio, profile_pdf, run

C = ProfilerConfig()
TEXT = " ".join(f"word{i}" for i in range(80))          # 80 native words


# --------------------------------------------------------------------------- #
# helpers: build small PDFs
# --------------------------------------------------------------------------- #
def _text_page(doc, rect=(40, 40, 555, 300), text=TEXT, **kw):
    page = doc.new_page()                               # A4 595x842
    page.insert_textbox(pymupdf.Rect(*rect), text, fontsize=10, **kw)
    return page


def _raster(dpi=150):
    d = pymupdf.open()
    _text_page(d)
    return d[0].get_pixmap(dpi=dpi)


def _scan_page(doc, dpi=150):
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=_raster(dpi))
    return page


def _hybrid_page(doc):
    page = _text_page(doc)                              # native text on top
    page.insert_image(pymupdf.Rect(40, 400, 555, 760), pixmap=_raster(), keep_proportion=False)  # text-free image below
    return page


def _save(doc, tmp_path, name="t.pdf", **kw):
    p = tmp_path / name
    doc.save(p, **kw)
    return p


def _profile_one(build, tmp_path):
    d = pymupdf.open()
    build(d)
    return profile_pdf(_save(d, tmp_path)).pages[0]


# --------------------------------------------------------------------------- #
# classify(): table-driven, no PDF needed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sig, expected", [
    (Sig(0, 0.00, 0.0, 0, False),   ("blank", "skip")),
    (Sig(0, 0.00, 0.0, 10, False, 0), ("blank", "skip")),
    (Sig(0, 0.00, 0.0, 5, False, 1), ("scanned", "rapidocr")),     # filled vector path is not blank
    (Sig(300, 0.02, 0.0, 0, False), ("digital", "pymupdf")),
    (Sig(300, 0.95, 0.0, 0, False), ("digital", "pymupdf")),     # scan with a trusted OCR layer
    (Sig(300, 0.40, 0.0, 0, True),  ("hybrid", "hybrid")),
    (Sig(0, 0.95, 0.0, 0, False),   ("scanned", "rapidocr")),
    (Sig(300, 0.10, 0.5, 0, False), ("scanned", "rapidocr")),    # garbled layer: re-OCR
    (Sig(10, 0.50, 0.0, 0, False),  ("scanned", "rapidocr")),    # few words + big image
    (Sig(10, 0.05, 0.0, 0, False),  ("digital", "pymupdf")),     # short digital page, e.g. cover
    (Sig(10, 0.20, 0.0, 0, True),   ("hybrid", "hybrid")),
])
def test_classify(sig, expected):
    assert classify(sig, C) == expected


def test_garbled_ratio():
    assert garbled_ratio("") == 0.0
    assert garbled_ratio("abc\ufffd") == 0.25
    assert garbled_ratio("\ue000\ue001ab") == 0.5


# --------------------------------------------------------------------------- #
# page level, on real generated PDFs
# --------------------------------------------------------------------------- #
def test_digital(tmp_path):
    p = _profile_one(_text_page, tmp_path)
    assert (p.type, p.engine, p.words) == ("digital", "pymupdf", 80)
    assert p.ocr_regions == [] and not p.table_hint


def test_scanned(tmp_path):
    p = _profile_one(_scan_page, tmp_path)
    assert (p.type, p.engine, p.words) == ("scanned", "rapidocr", 0)
    assert p.img > 0.95 and p.min_dpi is not None and p.min_dpi >= 140


def test_scanned_low_dpi_flag(tmp_path):
    p = _profile_one(lambda d: _scan_page(d, dpi=72), tmp_path)
    assert p.engine == "rapidocr" and "low_dpi" in p.flags


def test_hybrid_has_region_only_for_the_image(tmp_path):
    p = _profile_one(_hybrid_page, tmp_path)
    assert (p.type, p.engine) == ("hybrid", "hybrid")
    assert len(p.ocr_regions) == 1
    x0, y0, x1, y1 = p.ocr_regions[0]
    assert (x0, y0, x1, y1) == pytest.approx((40, 400, 555, 760), abs=1)


def test_logo_banner_in_top_band_is_skipped_but_page_stays_digital(tmp_path):
    def build(d):
        page = _text_page(d)
        page.insert_image(pymupdf.Rect(60, 20, 540, 120), pixmap=_raster(), keep_proportion=False)
    p = _profile_one(build, tmp_path)
    assert (p.type, p.engine) == ("digital", "pymupdf")
    assert p.skipped_regions and "decor_skipped" in p.flags


def test_vector_stroke_page_is_blank(tmp_path):
    def build(d):
        page = d.new_page()
        for y in range(60, 500, 40):
            page.draw_line((50, y), (500, y))
    p = _profile_one(build, tmp_path)
    assert (p.type, p.engine) == ("blank", "skip")


def test_scan_with_invisible_text_layer_is_trusted(tmp_path):
    def build(d):
        page = _scan_page(d)
        page.insert_textbox(pymupdf.Rect(40, 40, 555, 300), TEXT, fontsize=10, render_mode=3)
    p = _profile_one(build, tmp_path)
    assert (p.engine, p.words) == ("pymupdf", 80)
    assert "ocr_layer" in p.flags


def test_blank(tmp_path):
    p = _profile_one(lambda d: d.new_page(), tmp_path)
    assert (p.type, p.engine) == ("blank", "skip")


def test_table_hint_from_ruled_grid(tmp_path):
    def build(d):
        page = _text_page(d)
        for y in (320, 350, 380, 410):
            page.draw_line((50, y), (500, y))
        for x in (50, 200, 350, 500):
            page.draw_line((x, 320), (x, 410))
    assert _profile_one(build, tmp_path).table_hint


def test_rotated_page_region_is_usable_as_clip(tmp_path):
    """Regression: bboxes are unrotated, get_pixmap(clip=) is rotated. Region must be converted."""
    d = pymupdf.open()
    _hybrid_page(d).set_rotation(90)
    path = _save(d, tmp_path)
    p = profile_pdf(path).pages[0]
    assert p.rotation == 90 and "rotated" in p.flags and p.engine == "hybrid"
    with pymupdf.open(path) as doc:
        pix = doc[0].get_pixmap(clip=pymupdf.Rect(*p.ocr_regions[0]), dpi=72)
    assert (pix.width, pix.height) == pytest.approx((360, 515), abs=2)    # 515x360 image seen rotated


# --------------------------------------------------------------------------- #
# document level
# --------------------------------------------------------------------------- #
def _mixed(tmp_path):
    d = pymupdf.open()
    for _ in range(4):
        _text_page(d)
    _scan_page(d)
    d.new_page()
    return _save(d, tmp_path)


def test_batches_cover_every_routable_page_exactly_once(tmp_path):
    prof = profile_pdf(_mixed(tmp_path), ProfilerConfig(batch_size={"pymupdf": 2, "rapidocr": 15, "hybrid": 15}))
    assert prof.status == "ok" and prof.total_pages == 6
    assert prof.page_type_counts == {"digital": 4, "scanned": 1, "hybrid": 0, "blank": 1}
    assert prof.doc_type == "hybrid"                    # 4/5 digital < 95%
    assert [(b.engine, b.pages) for b in prof.batches] == [
        ("pymupdf", [1, 2]), ("pymupdf", [3, 4]), ("rapidocr", [5])]
    routed = sorted(n for b in prof.batches for n in b.pages)
    assert routed == [p.n for p in prof.pages if p.engine != "skip"]


@pytest.mark.parametrize("make, reason", [
    (lambda tmp: (tmp / "x.pdf").write_bytes(b"this is not a pdf") and tmp / "x.pdf", "corrupt_or_unreadable"),
    (lambda tmp: _save(_one_page_doc(), tmp, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                       user_pw="u", owner_pw="o"), "encrypted"),
])
def test_bad_files_fail_cleanly(tmp_path, make, reason):
    prof = profile_pdf(make(tmp_path))
    assert (prof.status, prof.reason) == ("failed", reason)
    assert prof.pages == [] and prof.batches == [] and prof.doc_id


def _one_page_doc():
    d = pymupdf.open()
    _text_page(d)
    return d


def test_oversize_file_fails(tmp_path):
    path = _save(_one_page_doc(), tmp_path)
    assert profile_pdf(path, ProfilerConfig(max_file_mb=0)).reason == "file_too_large"


def test_one_broken_page_does_not_sink_the_document(tmp_path, monkeypatch):
    path = _mixed(tmp_path)
    real = S._page

    def flaky(page, c):
        if page.number == 1:
            raise RuntimeError("boom")
        return real(page, c)
    monkeypatch.setattr(S, "_page", flaky)
    prof = profile_pdf(path)
    assert prof.status == "ok"
    bad = prof.pages[1]
    assert (bad.engine, bad.flags) == ("rapidocr", ["profile_error"])   # safe fallback: OCR it


# --------------------------------------------------------------------------- #
# idempotency
# --------------------------------------------------------------------------- #
def test_run_is_idempotent_and_config_aware(tmp_path, monkeypatch):
    monkeypatch.setenv("IDP_DATA_DIR", str(tmp_path / "data"))
    path = _mixed(tmp_path)
    calls = []
    real = S.profile_pdf
    monkeypatch.setattr(S, "profile_pdf", lambda *a, **k: calls.append(1) or real(*a, **k))

    first = run(path)
    again = run(path)
    assert len(calls) == 1 and again == first                    # second run = cache hit
    run(path, force=True)
    assert len(calls) == 2                                       # force bypasses cache
    run(path, cfg=ProfilerConfig(min_words=25))
    assert len(calls) == 3                                       # new thresholds => re-profile
    assert DocProfile.model_validate_json(
        (tmp_path / "data" / "artifacts" / "profiles" / first.doc_id / "profile.json").read_text()).doc_id == first.doc_id


def test_relative_idp_data_dir_is_resolved_from_project_root(monkeypatch):
    monkeypatch.setenv("IDP_DATA_DIR", "data/scratch")
    p = S.artifacts.path("profile", "abc123")
    assert str(p).endswith("medicheck-idp\\data\\scratch\\artifacts\\profiles\\abc123\\profile.json")


# --------------------------------------------------------------------------- #
# missing file: an infrastructure error, never a "failed" verdict
# --------------------------------------------------------------------------- #
def test_missing_file_raises_instead_of_returning_a_verdict(tmp_path):
    with pytest.raises(FileNotFoundError):
        profile_pdf(tmp_path / "nope.pdf")


def test_cli_missing_file_exits_2_without_traceback(tmp_path, monkeypatch, capsys):
    import main
    monkeypatch.setattr("sys.argv", ["main.py", str(tmp_path / "nope.pdf")])
    assert main.main() == 2
    assert "file not found" in capsys.readouterr().out