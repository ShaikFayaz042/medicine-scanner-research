"""Stage 1: PDF profiler. A router, not an extractor.

For every page it answers one question: which engine should extract this page,
and on which regions? It never extracts content and never renders pixels.
Per page it makes three cheap PyMuPDF calls, each exactly once:
    get_text("words")  -> word count, garbled ratio, which images already carry text
    get_image_info()   -> image coverage, DPI, image boxes (no image decoding)
    get_cdrawings()    -> ruled lines (table hint) and blank detection

Policy: when in doubt, OCR. Sending a digital page to OCR only costs money.
Sending a scanned page to PyMuPDF silently loses data.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

import pymupdf
from pydantic import BaseModel, ConfigDict

from idp.schemas.profile import Batch, DocProfile, Engine, PageProfile, PageType
from idp.storage import artifacts

VERSION = "1.1.0"
log = logging.getLogger("idp.profiler")
pymupdf.TOOLS.mupdf_display_errors(False)   # MuPDF repair noise; we count it instead

# U+FFFD, control characters, private-use area: the signature of a broken font encoding
_BAD = re.compile(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f\ue000-\uf8ff]")


class ProfilerConfig(BaseModel):
    """Starting values. Calibrate on 30-50 real PDFs, then freeze."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_file_mb: int = 300
    min_words: int = 20           # fewer native words than this on an image page => scanned
    max_garbled: float = 0.10     # above this the native text layer is not trusted
    scan_img: float = 0.30        # image coverage that makes a low-text page a scan
    blank_img: float = 0.05       # below this (and no text, no drawings) the page is blank
    max_decor_paths: int = 30     # stroke-only pages with <= this many paths can be blank
    min_region: float = 0.08      # an image must cover this much of the page to be an OCR region
    min_region_words: int = 3     # fewer native words than this inside an image => it needs OCR
    ocr_layer_img: float = 0.85   # image page that already has trusted text => flag ocr_layer
    low_dpi: int = 150
    band: float = 0.15            # header/footer band, fraction of page height
    repeat_min_pages: int = 3     # same xref on at least this many pages is decorative
    repeat_frac: float = 0.5      # repeated xref must cover at least this page share
    table_rules: int = 6          # ruled lines/cells needed for table_hint
    rule_min_len: float = 20.0
    batch_size: dict[str, int] = {"pymupdf": 100, "rapidocr": 15, "hybrid": 15}


DEFAULT_CONFIG = ProfilerConfig()


class Sig(NamedTuple):
    """Everything classify() needs. Small on purpose: easy to table-test."""
    words: int
    img: float
    garbled: float
    paths: int
    regions: bool
    ink: int = 0


# --------------------------------------------------------------------------- #
# Decision
# --------------------------------------------------------------------------- #
def classify(s: Sig, c: ProfilerConfig) -> tuple[PageType, Engine]:
    if s.words == 0 and s.img < c.blank_img and s.ink == 0 and s.paths <= c.max_decor_paths:
        return "blank", "skip"
    native = s.words > 0 and s.garbled <= c.max_garbled
    if native and (s.words >= c.min_words or s.img < c.scan_img):
        return ("hybrid", "hybrid") if s.regions else ("digital", "pymupdf")
    return "scanned", "rapidocr"        # no usable text layer: OCR the whole page


def garbled_ratio(text: str) -> float:
    return len(_BAD.findall(text)) / len(text) if text else 0.0


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
def _drawings(page: pymupdf.Page, min_len: float, area: float) -> tuple[int, int, int]:
    """(number of drawing paths, ruled-line count, filled non-white ink-like paths)."""
    paths, rules, ink = page.get_cdrawings(), 0, 0
    for d in paths:
        rect = d.get("rect")
        fill = d.get("fill")
        if rect is not None and fill is not None and fill != (1.0, 1.0, 1.0):
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            if w * h < 0.5 * area:
                ink += 1
        for it in d.get("items", []):
            if it[0] == "l":
                w, h = abs(it[2][0] - it[1][0]), abs(it[2][1] - it[1][1])
                rules += max(w, h) >= min_len and min(w, h) < 1
            elif it[0] == "re":
                w, h = it[1][2] - it[1][0], it[1][3] - it[1][1]
                rules += (max(w, h) >= min_len and min(w, h) < 2) or (w >= min_len and h >= 8)
    return len(paths), rules, ink


def _doc_repeat_xrefs(doc: pymupdf.Document, c: ProfilerConfig) -> set[int]:
    counts: dict[int, int] = defaultdict(int)
    total = max(doc.page_count, 1)
    for page in doc.pages():
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref")
            if xref is None:
                continue
            try:
                counts[int(xref)] += 1
            except (TypeError, ValueError):
                continue
    return {xref for xref, count in counts.items()
            if count >= c.repeat_min_pages and (count / total) >= c.repeat_frac}


def _is_decorative_image(clipped: pymupdf.Rect, info: dict, repeat_xrefs: set[int], c: ProfilerConfig,
                        bounds: pymupdf.Rect) -> bool:
    xref = info.get("xref")
    if xref is not None:
        try:
            if int(xref) in repeat_xrefs:
                return True
        except (TypeError, ValueError):
            pass
    page_h = max(bounds.height, 1.0)
    return clipped.y1 <= c.band * page_h or clipped.y0 >= (1.0 - c.band) * page_h


def _page(page: pymupdf.Page, c: ProfilerConfig, repeat_xrefs: set[int] | None = None) -> PageProfile:
    area = page.rect.width * page.rect.height
    # Words and image boxes live in UNROTATED space; page.rect and get_pixmap(clip=)
    # use the rotated one. Compare in unrotated space, publish regions in visible space.
    bounds = page.rect * page.derotation_matrix

    words = page.get_text("words")
    garbled = garbled_ratio("".join(w[4] for w in words))

    img_area, big = 0.0, []
    for info in page.get_image_info():
        box = pymupdf.Rect(info["bbox"])
        clipped = box & bounds
        if clipped.is_empty:
            continue
        img_area += clipped.get_area()
        if clipped.get_area() >= c.min_region * area:
            big.append((clipped, box, info))
    img = min(img_area / area, 1.0) if area else 0.0

    # a big image with (almost) no native words inside it still needs OCR
    regions, skipped_regions, dpis = [], [], []
    if big:
        centres = [((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) for w in words]
        for clipped, box, info in big:
            if _is_decorative_image(clipped, info, repeat_xrefs or set(), c, bounds):
                r = clipped * page.rotation_matrix
                skipped_regions.append((round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)))
                continue
            inside = sum(clipped.x0 <= x <= clipped.x1 and clipped.y0 <= y <= clipped.y1 for x, y in centres)
            if inside < c.min_region_words:
                r = clipped * page.rotation_matrix
                regions.append((round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)))
            px = info["width"] * info["height"]
            dpis.append((px / (box.get_area() / 72**2)) ** 0.5 if box.get_area() else 0.0)

    paths = rules = ink = 0
    if words or img < c.blank_img:      # a pure scan needs neither blank check nor table hint
        paths, rules, ink = _drawings(page, c.rule_min_len, area)

    s = Sig(len(words), img, garbled, paths, bool(regions), ink)
    ptype, engine = classify(s, c)
    ocr_routed = engine in ("rapidocr", "hybrid")
    min_dpi = round(min(dpis)) if dpis and ocr_routed else None

    flags = []
    if engine == "pymupdf" and img >= c.ocr_layer_img:
        flags.append("ocr_layer")           # scan that already has a trusted text layer
    if min_dpi is not None and min_dpi < c.low_dpi:
        flags.append("low_dpi")
    if page.rotation:
        flags.append("rotated")
    if skipped_regions:
        flags.append("decor_skipped")
    if engine != "skip" and (
        abs(s.words - c.min_words) <= c.min_words // 4
        or abs(s.img - c.scan_img) <= 0.05
        or abs(s.garbled - c.max_garbled) <= 0.02
    ):
        flags.append("borderline")          # close to a threshold: sample these in review

    return PageProfile(
        n=page.number + 1, type=ptype, engine=engine, words=s.words,
        img=round(img, 3), garbled=round(garbled, 3),
        table_hint=engine != "skip" and rules >= c.table_rules,
        rotation=page.rotation, min_dpi=min_dpi,
        ocr_regions=regions if engine == "hybrid" else [],
        skipped_regions=skipped_regions,
        flags=flags,
    )


def _safe_page(page: pymupdf.Page, c: ProfilerConfig, repeat_xrefs: set[int] | None = None) -> PageProfile:
    """One bad page must not sink the document: route it to OCR and say why."""
    try:
        return _page(page, c, repeat_xrefs)
    except Exception:
        log.exception("profile_error page=%d", page.number + 1)
        return PageProfile(n=page.number + 1, type="scanned", engine="rapidocr", words=0,
                           img=0.0, garbled=0.0, table_hint=False, flags=["profile_error"])


# --------------------------------------------------------------------------- #
# Document
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def config_hash(c: ProfilerConfig) -> str:
    return hashlib.sha256(c.model_dump_json().encode()).hexdigest()[:8]


def _batches(pages: list[PageProfile], size: dict[str, int]) -> list[Batch]:
    by_engine: dict[str, list[int]] = defaultdict(list)
    for p in pages:
        if p.engine != "skip":
            by_engine[p.engine].append(p.n)
    out = [Batch(engine=e, pages=ns[i:i + size[e]])
           for e, ns in by_engine.items() for i in range(0, len(ns), size[e])]
    return sorted(out, key=lambda b: b.pages[0])


def _doc_type(counts: dict[str, int]) -> PageType:
    live = counts["digital"] + counts["scanned"] + counts["hybrid"]
    if not live:
        return "blank"
    for t in ("digital", "scanned"):
        if counts[t] >= 0.95 * live:
            return t                                    # type: ignore[return-value]
    return "hybrid"


def profile_pdf(path: str | Path, cfg: ProfilerConfig = DEFAULT_CONFIG,
                doc_id: str | None = None) -> DocProfile:
    """Pure function: one PDF in, one DocProfile out. No storage.

    Bad DATA (corrupt, encrypted, too large, zero pages) returns status="failed": a final
    verdict that retrying cannot change. A missing or unreadable FILE raises OSError: an
    infrastructure error the orchestrator should retry, so it must never become a verdict.
    """
    path, t0 = Path(path), time.perf_counter()
    base = dict(doc_id=doc_id or sha256_file(path), file_name=path.name,
                profiler_version=VERSION, config_hash=config_hash(cfg))

    def fail(reason: str) -> DocProfile:
        log.warning("profile_failed doc=%s reason=%s", base["doc_id"][:12], reason)
        return DocProfile(status="failed", reason=reason, **base)

    if path.stat().st_size > cfg.max_file_mb * 2**20:
        return fail("file_too_large")
    try:
        doc = pymupdf.open(path)
    except Exception:
        return fail("corrupt_or_unreadable")
    with doc:
        if doc.needs_pass:
            return fail("encrypted")
        if not doc.is_pdf:
            return fail("not_a_pdf")
        if doc.page_count == 0:
            return fail("zero_pages")
        repeat_xrefs = _doc_repeat_xrefs(doc, cfg)
        pages = [_safe_page(p, cfg, repeat_xrefs) for p in doc.pages()]

    counts = {t: sum(p.type == t for p in pages) for t in ("digital", "scanned", "hybrid", "blank")}
    prof = DocProfile(status="ok", total_pages=len(pages), doc_type=_doc_type(counts),
                      page_type_counts=counts, batches=_batches(pages, cfg.batch_size),
                      pages=pages, **base)
    log.info("profiled doc=%s pages=%d type=%s counts=%s mupdf_warnings=%d secs=%.2f",
             prof.doc_id[:12], prof.total_pages, prof.doc_type, counts,
             len(pymupdf.TOOLS.mupdf_warnings().splitlines()), time.perf_counter() - t0)
    return prof


def run(pdf_path: str | Path, *, force: bool = False,
        cfg: ProfilerConfig = DEFAULT_CONFIG) -> DocProfile:
    """Idempotent stage entry: same file + same version + same config => reuse the artifact."""
    doc_id = sha256_file(Path(pdf_path))
    cached = None if force else artifacts.load("profile", doc_id, DocProfile)
    if cached and cached.profiler_version == VERSION and cached.config_hash == config_hash(cfg):
        log.info("profile_cached doc=%s", doc_id[:12])
        return cached
    prof = profile_pdf(pdf_path, cfg, doc_id)
    artifacts.save("profile", doc_id, prof)
    return prof