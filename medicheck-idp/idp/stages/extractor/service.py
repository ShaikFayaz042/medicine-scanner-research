"""Stage 2: extractor. Executes the profiler's plan; never re-decides it."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
import time
from pathlib import Path
from typing import Literal

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from idp.schemas.extraction import (BatchRef, ExtractionBatch, ExtractionIndex, Item,
                                    PageExtraction, Source, TableGroup)
from idp.schemas.profile import DocProfile, PageProfile
from idp.stages.extractor import digital, markdown, ocr
from idp.stages.extractor.geometry import normalize
from idp.stages.profiler.service import run as run_profiler, sha256_file
from idp.storage import artifacts

VERSION = "1.2.1"
log = logging.getLogger("idp.extractor")
pymupdf.TOOLS.mupdf_display_errors(False)
_CROP = Source(engine="pymupdf", method="region_crop")
_ARTIFACT_PREFIX = "02_extraction"
_PAGE_NUMBER = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_FURNITURE_BAND = 0.15


class ExtractorConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    render_dpi: int = Field(default=150, ge=36, le=600)
    ocr_max_px: int = Field(default=4000, ge=256, le=10000)
    ocr_threads: int = Field(default=2, ge=1, le=64)
    find_tables: bool = True
    # Strict mode avoids treating text strokes as table dividers; use "lines" for open grids.
    table_strategy: Literal["lines", "lines_strict", "text"] = "lines_strict"
    min_table_rows: int = Field(default=2, ge=1)
    min_table_cols: int = Field(default=2, ge=1)
    low_conf: float = Field(default=0.5, ge=0, le=1)


DEFAULT_CONFIG = ExtractorConfig()


def config_hash(c: ExtractorConfig) -> str:
    # Thread count changes throughput only; the Markdown engine and options affect output.
    payload = {
        "config": c.model_dump(exclude={"ocr_threads"}),
        "pymupdf4llm_version": markdown.VERSION,
        "pymupdf4llm_mode": markdown.MODE,
        "markdown_options": markdown.OPTIONS,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:8]


def profile_key(p: DocProfile) -> str:
    return f"{p.profiler_version}:{p.config_hash}"


def _finalize(page_no: int, items: list[Item]) -> list[Item]:
    out = [it.model_copy(update={"item_id": f"p{page_no:03d}_i{k:03d}"})
           for k, it in enumerate(items, 1)]
    for i, it in enumerate(out):
        if it.type == "text_line" and it.text and _PAGE_NUMBER.match(it.text):
            y0 = it.bbox[1]
            if y0 <= _FURNITURE_BAND or y0 >= 1 - _FURNITURE_BAND:
                out[i] = it.model_copy(update={"role": "page_number"})
    tables = [(t.item_id, t.bbox) for t in out if t.type == "table"]
    for i, it in enumerate(out):
        if it.type != "text_line":
            continue
        cx, cy = (it.bbox[0] + it.bbox[2]) / 2, (it.bbox[1] + it.bbox[3]) / 2
        for tid, (x0, y0, x1, y1) in tables:
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                out[i] = it.model_copy(update={"parent": tid})
                break
    return out


def _columns_match(
    columns_a: list[tuple[float, float]],
    columns_b: list[tuple[float, float]],
    page_width_a: float,
    page_width_b: float,
    tolerance_pt: float = 2.0,
) -> bool:
    if (not columns_a or len(columns_a) != len(columns_b)
            or page_width_a <= 0 or page_width_b <= 0):
        return False
    return all(
        abs(x0_a * page_width_a - x0_b * page_width_b) <= tolerance_pt
        and abs(x1_a * page_width_a - x1_b * page_width_b) <= tolerance_pt
        for (x0_a, x1_a), (x0_b, x1_b) in zip(columns_a, columns_b)
    )


def _link_table_continuations(pages: list[PageExtraction]) -> list[TableGroup]:
    page_by_number = {page.page_number: page for page in pages}
    for page in pages:
        reset_items = []
        for item in page.items:
            if item.type == "table" and item.table and item.table.continuation_of is not None:
                table = item.table.model_copy(update={
                    "continuation_of": None,
                    "continuation_confidence": None,
                    "n_data_rows": None,
                })
                item = item.model_copy(update={"table": table})
            reset_items.append(item)
        page.items = reset_items

    groups = []
    for page in sorted(pages, key=lambda extracted: extracted.page_number):
        previous_page = page_by_number.get(page.page_number - 1)
        if previous_page is None:
            continue
        previous_tables = [
            item for item in previous_page.items
            if item.type == "table" and item.table and item.table.header_names
        ]
        updated_items = []
        for item in page.items:
            if item.type != "table" or item.table is None:
                updated_items.append(item)
                continue
            matches = [
                candidate for candidate in previous_tables
                if candidate.table.n_cols == item.table.n_cols
                and _columns_match(
                    candidate.table.columns, item.table.columns,
                    previous_page.width, page.width,
                )
            ]
            if not matches:
                updated_items.append(item)
                continue
            header_table = min(matches, key=lambda candidate: candidate.item_id)
            table = item.table.model_copy(update={
                "header_external": True,
                "continuation_of": header_table.item_id,
                "continuation_confidence": 1.0,
                "n_data_rows": item.table.n_rows,
            })
            updated_items.append(item.model_copy(update={"table": table}))
            group_number = len(groups) + 1
            groups.append(TableGroup(
                group_id=f"TG{group_number:04d}",
                member_table_ids=[header_table.item_id, item.item_id],
                header_source=header_table.item_id,
                pages=[previous_page.page_number, page.page_number],
                confidence=1.0,
            ))
        page.items = updated_items
    return groups


def _needs_ocr(p: PageProfile) -> bool:
    return p.engine == "rapidocr" or (p.engine == "hybrid" and bool(p.ocr_regions))


def _ocr_lines_markdown(items: list[Item], width: float, height: float) -> str:
    lines = []
    for item in items:
        if item.type != "text_line" or item.source.engine != "rapidocr":
            continue
        x0, y0, x1, y1 = item.bbox
        lines.append((y0 * height, x0 * width, y1 * height, item.text or ""))
    lines.sort(key=lambda line: (line[0], line[1]))
    if not lines:
        return ""
    median_height = statistics.median(max(y1 - y0, 0.1) for y0, _, y1, _ in lines)
    paragraphs: list[list[str]] = [[lines[0][3]]]
    previous_y0, previous_x0, previous_y1, _ = lines[0]
    for y0, x0, y1, text in lines[1:]:
        if y0 - previous_y1 > median_height or abs(x0 - previous_x0) > 2 * median_height:
            paragraphs.append([text])
        else:
            paragraphs[-1].append(text)
        previous_y0, previous_x0, previous_y1 = y0, x0, y1
    return "\n\n".join(" ".join(paragraph) for paragraph in paragraphs)


def _hybrid_markdown(native_text: str, regions: list[list[Item]], page_number: int) -> str:
    blocks = [native_text.strip()] if native_text.strip() else []
    for region_number, items in enumerate(regions, 1):
        lines = [item.text for item in items if item.type == "text_line" and item.text]
        quoted = [f"> **Page {page_number}, OCR region {region_number}**"]
        quoted.extend(f"> {line}" for line in lines)
        blocks.append("\n".join(quoted))
    return "\n\n".join(blocks)


def _save_markdown(doc_id: str, page_number: int, text: str) -> tuple[str, str | None]:
    reference = f"{_ARTIFACT_PREFIX}/markdown/p{page_number:03d}.md"
    try:
        artifacts.save_bytes(reference, doc_id, text.encode("utf-8"))
        return reference, None
    except Exception as error:
        log.exception("markdown_write_failed doc=%s page=%d", doc_id[:12], page_number)
        return reference, f"{type(error).__name__}: {error}"


def _extract_page(doc: pymupdf.Document, p: PageProfile, doc_id: str, cfg: ExtractorConfig,
                  backend: ocr.OcrBackend | None, native_markdown: str | None = None,
                  native_markdown_error: str | None = None) -> PageExtraction:
    base = dict(doc_id=doc_id, page_number=p.n, page_mode=p.type, width=0.0, height=0.0,
                rotation=p.rotation)
    t0 = time.perf_counter()
    items: list[Item] = []
    warnings: list[str] = []
    ocr_regions: list[list[Item]] = []
    markdown_error = native_markdown_error
    markdown_text = ""
    markdown_source = "none"
    try:
        page = doc[p.n - 1]
        base.update(width=round(page.rect.width, 2), height=round(page.rect.height, 2),
                    rotation=page.rotation)
        if p.engine == "skip":
            markdown_ref, write_error = _save_markdown(doc_id, p.n, "")
            return PageExtraction(status="skipped", markdown_ref=markdown_ref,
                                  markdown_source="none",
                                  markdown_error=write_error, **base)

        tables_checked = False

        if p.engine in ("pymupdf", "hybrid"):
            items += digital.native_lines(page)
            if cfg.find_tables:
                try:
                    items += digital.native_tables(
                        page, cfg.table_strategy, cfg.min_table_rows, cfg.min_table_cols,
                    )
                    tables_checked = True
                    if p.table_hint and not any(item.type == "table" for item in items):
                        warnings.append("table_hint_but_no_table")
                except Exception:
                    log.exception("find_tables_failed doc=%s page=%d", doc_id[:12], p.n)
                    warnings.append("find_tables_failed")
            elif p.table_hint:
                warnings.append("table_detection_disabled")

        if _needs_ocr(p):
            if backend is None:
                raise RuntimeError("OCR is required for this page but no backend is available")
            if p.engine == "rapidocr":
                rendered = ocr.render_bounded(page, cfg.render_dpi, max_px=cfg.ocr_max_px)
                page_ocr_items = ocr.lines_to_items(page, rendered.pix, rendered.dpi,
                                                    backend(rendered.image))
                items += page_ocr_items
                markdown_text = _ocr_lines_markdown(page_ocr_items, page.rect.width,
                                                    page.rect.height)
                markdown_source = "ocr_lines"
            else:
                for k, region in enumerate(p.ocr_regions, 1):
                    rendered = ocr.render_bounded(
                        page, cfg.render_dpi, region, max_px=cfg.ocr_max_px,
                    )
                    region_items = ocr.lines_to_items(page, rendered.pix, rendered.dpi,
                                                      backend(rendered.image))
                    items += region_items
                    ocr_regions.append(region_items)
                    rel = f"{_ARTIFACT_PREFIX}/crops/p{p.n:03d}_r{k}.png"
                    artifacts.save_bytes(
                        rel, doc_id, rendered.pix.tobytes("png"),
                    )
                    items.append(Item(item_id="", type="image", source=_CROP, image_ref=rel,
                                      bbox=normalize(page, pymupdf.Rect(*region))))
                markdown_text = _hybrid_markdown(native_markdown or "", ocr_regions, p.n)
                markdown_source = "mixed"
        elif p.engine == "hybrid":
            warnings.append("hybrid_without_ocr_regions")

        if p.engine == "pymupdf":
            if native_markdown is not None:
                markdown_text = native_markdown
                markdown_source = "pymupdf4llm"
            elif markdown_error is None:
                markdown_error = "Markdown conversion returned no page result"

        low = sum(1 for i in items if i.confidence is not None and i.confidence < cfg.low_conf)
        if low:
            warnings.append(f"low_confidence_lines={low}")
        if not any(i.type == "text_line" for i in items):
            warnings.append("no_text_found")

        markdown_ref, write_error = _save_markdown(doc_id, p.n, markdown_text)
        markdown_error = markdown_error or write_error
        if markdown_error:
            log.error("markdown_failed doc=%s page=%d error=%s", doc_id[:12], p.n,
                      markdown_error)
        log.info("extract_page doc=%s page=%d engine=%s items=%d markdown_source=%s secs=%.2f",
                 doc_id[:12], p.n, p.engine, len(items), markdown_source,
                 time.perf_counter() - t0)
        return PageExtraction(status="success", items=_finalize(p.n, items),
                              tables_checked=tables_checked, warnings=warnings,
                              markdown_ref=markdown_ref, markdown_source=markdown_source,
                              markdown_error=markdown_error, **base)
    except Exception as e:
        log.exception("extract_error doc=%s page=%d", doc_id[:12], p.n)
        if p.engine == "rapidocr":
            markdown_source = "none"
        elif p.engine == "hybrid":
            markdown_text = _hybrid_markdown(native_markdown or "", ocr_regions, p.n)
            markdown_source = "mixed"
        elif p.engine == "pymupdf" and native_markdown is not None:
            markdown_text = native_markdown
            markdown_source = "pymupdf4llm"
        markdown_ref, write_error = _save_markdown(doc_id, p.n, markdown_text)
        markdown_error = markdown_error or f"{type(e).__name__}: {e}"
        return PageExtraction(status="failed", items=_finalize(p.n, items),
                              warnings=warnings, error=f"{type(e).__name__}: {e}",
                              markdown_ref=markdown_ref, markdown_source=markdown_source,
                              markdown_error=markdown_error or write_error, **base)


def _validate_profile(profile: DocProfile) -> None:
    if profile.status != "ok":
        raise ValueError(f"cannot extract: profile status={profile.status} reason={profile.reason}")
    expected_pages = list(range(1, profile.total_pages + 1))
    actual_pages = sorted(page.n for page in profile.pages)
    if actual_pages != expected_pages:
        raise ValueError("profile pages must cover every document page exactly once")
    by_page = {page.n: page.engine for page in profile.pages}
    assigned: list[int] = []
    for batch in profile.batches:
        for page_number in batch.pages:
            if page_number not in by_page:
                raise ValueError(f"profile batch references unknown page {page_number}")
            if by_page[page_number] != batch.engine:
                raise ValueError(f"profile batch engine does not match page {page_number}")
            assigned.append(page_number)
    expected_batched = {page.n for page in profile.pages if page.engine != "skip"}
    if len(assigned) != len(set(assigned)) or set(assigned) != expected_batched:
        raise ValueError("profile batches must assign each non-skipped page exactly once")


def _check_page_count(profile: DocProfile, doc: pymupdf.Document) -> None:
    if doc.page_count != profile.total_pages:
        raise ValueError(f"profile has {profile.total_pages} pages, PDF has {doc.page_count}")


def _native_markdown_for_batch(doc: pymupdf.Document, pages: list[PageProfile],
                               doc_id: str) -> tuple[dict[int, str], dict[int, str]]:
    page_numbers = [page.n for page in pages if page.engine in ("pymupdf", "hybrid")]
    if not page_numbers:
        return {}, {}
    try:
        return markdown.batch_markdown(doc, page_numbers), {}
    except Exception as batch_error:
        log.warning("markdown_batch_retry doc=%s page=%s error=%s",
                    doc_id[:12], ",".join(map(str, page_numbers)),
                    f"{type(batch_error).__name__}: {batch_error}")

    results: dict[int, str] = {}
    errors: dict[int, str] = {}
    for page_number in page_numbers:
        try:
            results.update(markdown.batch_markdown(doc, [page_number]))
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            errors[page_number] = message
            log.exception("markdown_page_failed doc=%s page=%d", doc_id[:12], page_number)
    return results, errors


def _extract_pages(pdf_path: Path, profile: DocProfile, nums: list[int], engine, index: int,
                   cfg: ExtractorConfig, backend: ocr.OcrBackend | None) -> ExtractionBatch:
    t0 = time.perf_counter()
    _validate_profile(profile)
    by_n = {p.n: p for p in profile.pages}
    plan = [by_n[n] for n in nums]
    with markdown.extraction_lock:
        with pymupdf.open(pdf_path) as markdown_doc:
            _check_page_count(profile, markdown_doc)
            native_results, markdown_errors = _native_markdown_for_batch(
                markdown_doc, plan, profile.doc_id,
            )
        # PyMuPDF4LLM's layout engine changes page rotation state while building
        # its layout; extraction starts from a fresh document to preserve geometry.
        with pymupdf.open(pdf_path) as doc:
            _check_page_count(profile, doc)
            if backend is None and any(_needs_ocr(p) for p in plan):
                backend = ocr.get_backend(cfg.ocr_threads)
            pages = [
                _extract_page(doc, p, profile.doc_id, cfg, backend,
                              native_results.get(p.n), markdown_errors.get(p.n))
                for p in plan
            ]
    table_groups = _link_table_continuations(pages)
    batch = ExtractionBatch(doc_id=profile.doc_id, batch_index=index, engine=engine,
                            extractor_version=VERSION, config_hash=config_hash(cfg),
                            profile_key=profile_key(profile), pages=pages,
                            table_groups=table_groups)
    status_counts = {status: sum(page.status == status for page in pages)
                     for status in ("success", "skipped", "failed")}
    markdown_failed = sum(page.markdown_error is not None for page in pages)
    page_label = ",".join(map(str, nums)) if len(nums) <= 8 else f"{nums[0]}-{nums[-1]}"
    log.info("extract_batch doc=%s page=%s engine=%s pages=%d success=%d skipped=%d "
             "failed=%d markdown_failed=%d secs=%.3f",
             profile.doc_id[:12], page_label, engine, len(pages), status_counts["success"],
             status_counts["skipped"], status_counts["failed"], markdown_failed,
             time.perf_counter() - t0)
    return batch


def extract_batch(pdf_path: str | Path, profile: DocProfile, batch_index: int,
                  cfg: ExtractorConfig = DEFAULT_CONFIG,
                  backend: ocr.OcrBackend | None = None) -> ExtractionBatch:
    _validate_profile(profile)
    if not 0 <= batch_index < len(profile.batches):
        raise ValueError(f"batch_index {batch_index} is outside profile batches")
    if sha256_file(Path(pdf_path)) != profile.doc_id:
        raise ValueError("profile doc_id does not match PDF contents")
    b = profile.batches[batch_index]
    return _extract_pages(Path(pdf_path), profile, b.pages, b.engine, batch_index, cfg, backend)


def _batch_matches(cached: ExtractionBatch | None, profile: DocProfile, nums: list[int],
                   engine: str, index: int, cfg: ExtractorConfig) -> bool:
    return (cached is not None and cached.doc_id == profile.doc_id
            and cached.batch_index == index and cached.engine == engine
            and cached.extractor_version == VERSION
            and cached.config_hash == config_hash(cfg)
            and cached.profile_key == profile_key(profile)
            and len(cached.pages) == len(nums)
            and set(page.page_number for page in cached.pages) == set(nums))


def _page_artifacts_fresh(page: PageExtraction, doc_id: str) -> bool:
    if page.status not in ("success", "skipped") or page.markdown_error is not None:
        return False
    if page.markdown_ref is None:
        return False
    references = [page.markdown_ref]
    references.extend(item.image_ref for item in page.items if item.image_ref is not None)
    try:
        return all(artifacts.artifact_path(reference, doc_id).is_file()
                   for reference in references)
    except ValueError:
        return False


def _fresh(cached: ExtractionBatch | None, profile: DocProfile, nums: list[int],
           engine: str, index: int, cfg: ExtractorConfig) -> bool:
    return (_batch_matches(cached, profile, nums, engine, index, cfg)
            and all(_page_artifacts_fresh(page, profile.doc_id) for page in cached.pages))


def run(pdf_path: str | Path, profile: DocProfile | None = None, *, force: bool = False,
        cfg: ExtractorConfig = DEFAULT_CONFIG,
        backend: ocr.OcrBackend | None = None) -> ExtractionIndex:
    """Idempotent stage entry: batch artifacts are reused while version, config and profile match."""
    pdf_path = Path(pdf_path)
    profile = profile or run_profiler(pdf_path)
    _validate_profile(profile)
    if sha256_file(pdf_path) != profile.doc_id:
        raise ValueError("profile doc_id does not match PDF contents")

    jobs = [(f"{_ARTIFACT_PREFIX}/batches/b{i:04d}", i, b.engine, b.pages)
            for i, b in enumerate(profile.batches)]
    skipped = [p.n for p in profile.pages if p.engine == "skip"]
    if skipped:
        jobs.append((f"{_ARTIFACT_PREFIX}/batches/skipped", -1, "skip", skipped))

    refs, failed, markdown_failed = [], [], []
    for name, idx, engine, nums in jobs:
        cached = None if force else artifacts.load(name, profile.doc_id, ExtractionBatch)
        matching = not force and _batch_matches(cached, profile, nums, engine, idx, cfg)
        reusable = ({page.page_number: page for page in cached.pages
                     if _page_artifacts_fresh(page, profile.doc_id)} if matching else {})
        stale_pages = [number for number in nums if force or number not in reusable]
        if stale_pages:
            extracted = _extract_pages(pdf_path, profile, stale_pages, engine, idx, cfg, backend)
            reusable.update({page.page_number: page for page in extracted.pages})
            batch = ExtractionBatch(
                doc_id=profile.doc_id, batch_index=idx, engine=engine,
                extractor_version=VERSION, config_hash=config_hash(cfg),
                profile_key=profile_key(profile),
                pages=[reusable[number] for number in nums],
                table_groups=_link_table_continuations(
                    [reusable[number] for number in nums]
                ),
            )
            artifacts.save(name, profile.doc_id, batch)
        else:
            batch = cached
            successes = sum(page.status == "success" for page in batch.pages)
            skipped_count = sum(page.status == "skipped" for page in batch.pages)
            log.info("extract_batch_cached doc=%s page=%s engine=%s pages=%d success=%d "
                     "skipped=%d failed=0 markdown_failed=0 secs=0.000",
                     profile.doc_id[:12], ",".join(map(str, nums)), engine, len(nums),
                     successes, skipped_count)
        refs.append(BatchRef(index=idx, engine=engine, pages=nums, artifact=name))
        failed += [p.page_number for p in batch.pages if p.status == "failed"]
        markdown_failed += [p.page_number for p in batch.pages if p.markdown_error is not None]

    index = ExtractionIndex(doc_id=profile.doc_id, extractor_version=VERSION,
                            config_hash=config_hash(cfg), profile_key=profile_key(profile),
                            total_pages=profile.total_pages, batches=refs,
                            failed_pages=sorted(failed),
                            markdown_failed_pages=sorted(markdown_failed),
                            complete=not failed and not markdown_failed)
    artifacts.save(f"{_ARTIFACT_PREFIX}/index", profile.doc_id, index)
    return index