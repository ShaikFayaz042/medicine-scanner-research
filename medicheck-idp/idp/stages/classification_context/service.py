"""Stage 3: build lightweight, classifier-only context from extraction artifacts."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from idp.schemas.classification_context import (
    ClassificationContext,
    ContextQuality,
    DocumentProfile,
    ParagraphContext,
    TableContext,
)
from idp.schemas.extraction import ExtractionBatch, ExtractionIndex, PageExtraction
from idp.schemas.profile import DocProfile
from idp.stages.classification_context.paragraphs import build_document_anchors, extract_paragraphs
from idp.stages.classification_context.tables import extract_tables
from idp.stages.extractor.service import run as run_extractor
from idp.stages.profiler.service import run as run_profiler, sha256_file
from idp.storage import artifacts

VERSION = "1.4.0"
log = logging.getLogger("idp.classification_context")
_ARTIFACT = "03_classification_context/classification_context"

def _fingerprint(index: ExtractionIndex, pages: list[PageExtraction], markdown_by_page: dict[int, str]) -> str:
    payload = {
        "index": index.model_dump(mode="json"),
        "pages": [page.model_dump(mode="json") for page in pages],
        "markdown": {
            str(page): hashlib.sha256(text.encode("utf-8")).hexdigest()
            for page, text in sorted(markdown_by_page.items())
        },
        "builder_version": VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def _load_extraction(index: ExtractionIndex, profile: DocProfile) -> list[PageExtraction]:
    if index.doc_id != profile.doc_id:
        raise ValueError("extraction index belongs to a different PDF")
    expected_profile_key = f"{profile.profiler_version}:{profile.config_hash}"
    if index.profile_key != expected_profile_key:
        raise ValueError("extraction index was produced from a different profiler configuration")
    if index.total_pages != profile.total_pages:
        raise ValueError("extraction index page count does not match profiler output")
    
    pages: list[PageExtraction] = []
    for reference in index.batches:
        batch = artifacts.load(reference.artifact, profile.doc_id, ExtractionBatch)
        if batch is None:
            raise FileNotFoundError(f"extraction batch artifact is missing or invalid: {reference.artifact}")
        if (batch.doc_id != profile.doc_id or batch.batch_index != reference.index
                or batch.engine != reference.engine
                or [page.page_number for page in batch.pages] != reference.pages
                or batch.config_hash != index.config_hash
                or batch.profile_key != index.profile_key
                or batch.extractor_version != index.extractor_version):
            raise ValueError(f"extraction batch metadata does not match index: {reference.artifact}")
        pages.extend(batch.pages)

    pages.sort(key=lambda page: page.page_number)
    if [page.page_number for page in pages] != list(range(1, profile.total_pages + 1)):
        raise ValueError("extraction batches must cover every PDF page exactly once")
    return pages

def _read_markdown(doc_id: str, pages: list[PageExtraction]) -> dict[int, str]:
    markdown_by_page: dict[int, str] = {}
    for page in pages:
        if page.status == "failed" or page.markdown_error is not None:
            continue
        if page.markdown_ref is None:
            raise ValueError(f"page {page.page_number} has no Markdown artifact reference")
        path = artifacts.artifact_path(page.markdown_ref, doc_id)
        if not path.is_file():
            raise FileNotFoundError(f"Markdown artifact is missing for page {page.page_number}: {page.markdown_ref}")
        markdown_by_page[page.page_number] = path.read_text(encoding="utf-8")
    return markdown_by_page

def _build_context(
    profile: DocProfile,
    index: ExtractionIndex,
    pages: list[PageExtraction],
    markdown_by_page: dict[int, str],
    *,
    force: bool,
    document_id: str | None,
    title: str | None,
    source: str | None,
    release_date: str | None,
    s3_key: str | None,
) -> ClassificationContext:
    fingerprint = _fingerprint(index, pages, markdown_by_page)
    expected_document_id = document_id or f"sha256:{profile.doc_id}"
    
    source_metadata = {"file_name": profile.file_name}
    source_metadata.update({
        key: value for key, value in {
            "title": title, "source": source, "release_date": release_date, "s3_key": s3_key,
        }.items() if value is not None
    })
    
    cached = artifacts.load(_ARTIFACT, profile.doc_id, ClassificationContext)
    if (not force and cached is not None and cached.document_id == expected_document_id
            and cached.document_sha256 == profile.doc_id
            and cached.source_metadata == source_metadata
            and cached.builder_version == VERSION
            and cached.extraction_fingerprint == fingerprint):
        return cached

    paragraphs: list[ParagraphContext] = []
    tables: list[TableContext] = []
    warnings = [f"page_{page.page_number}:{w}" for page in pages for w in page.warnings]
    warnings.extend(f"page_{page.n}:profile_{f}" for page in profile.pages for f in page.flags)
    
    next_paragraph_index = 1
    item_to_context_table_id: dict[str, str] = {}
    table_headers_cache: dict[str, list[str]] = {}

    for page in pages:
        if page.page_number in markdown_by_page and page.markdown_ref:
            # 1. Extract Paragraphs
            page_paragraphs, excluded_count = extract_paragraphs(
                markdown=markdown_by_page[page.page_number],
                page_number=page.page_number,
                artifact=page.markdown_ref,
                source_method=page.markdown_source,
                start_index=next_paragraph_index,
                items=page.items,
                page_width=page.width,
                page_height=page.height,
            )
            next_paragraph_index += len(page_paragraphs)
            paragraphs.extend(page_paragraphs)
            
            if excluded_count:
                warnings.append(f"header_footer_excluded:{excluded_count} items")

        # 2. Extract Tables
        batch_artifact = next((ref.artifact for ref in index.batches if page.page_number in ref.pages), "unknown")
        page_tables, table_warnings = extract_tables(
            page_items=page.items,
            page_number=page.page_number,
            page_width=page.width,
            page_height=page.height,
            batch_artifact=batch_artifact,
            item_to_context_table_id=item_to_context_table_id,
            table_headers_cache=table_headers_cache,
        )
        tables.extend(page_tables)
        warnings.extend(table_warnings)

    has_classifiable_content = bool(paragraphs or tables)
    if not has_classifiable_content:
        warnings.append("no_classifiable_content")

    context = ClassificationContext(
        document_id=expected_document_id,
        document_sha256=profile.doc_id,
        source_metadata=source_metadata,
        total_pages=profile.total_pages,
        builder_version=VERSION,
        extraction_fingerprint=fingerprint,
        document_profile=DocumentProfile(
            document_type=profile.doc_type or "blank",
            digital_pages=profile.page_type_counts.get("digital", 0),
            scanned_pages=profile.page_type_counts.get("scanned", 0),
            hybrid_pages=profile.page_type_counts.get("hybrid", 0),
            blank_pages=profile.page_type_counts.get("blank", 0),
        ),
        quality=ContextQuality(
            has_classifiable_content=has_classifiable_content,
            warnings=list(dict.fromkeys(warnings)),
            failed_pages=sorted(set(index.failed_pages + index.markdown_failed_pages)),
        ),
        paragraphs=paragraphs,
        tables=tables,
        document_anchors=build_document_anchors(paragraphs),
    )
    
    artifacts.save(_ARTIFACT, profile.doc_id, context)
    log.info("classification_context_built doc=%s paragraphs=%d tables=%d",
             profile.doc_id[:12], len(paragraphs), len(tables))
    return context

def run(
    pdf_path: str | Path,
    *,
    force: bool = False,
    profile: DocProfile | None = None,
    extraction_index: ExtractionIndex | None = None,
    document_id: str | None = None,
    title: str | None = None,
    source: str | None = None,
    release_date: str | None = None,
    s3_key: str | None = None,
) -> ClassificationContext:
    """Ensure profile/extraction artifacts exist and write `classification_context.json`."""
    path = Path(pdf_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"PDF does not exist: {path}")
    doc_id = sha256_file(path)
    profile = profile or run_profiler(path, force=force)
    if profile.doc_id != doc_id or profile.status != "ok":
        raise ValueError(f"invalid profiler artifact for PDF hash {doc_id}: status={profile.status}")
    index = extraction_index or run_extractor(path, profile=profile, force=force)
    pages = _load_extraction(index, profile)
    markdown_by_page = _read_markdown(doc_id, pages)
    
    return _build_context(
        profile, index, pages, markdown_by_page, force=force, document_id=document_id,
        title=title, source=source, release_date=release_date, s3_key=s3_key,
    )

__all__ = ["run"]