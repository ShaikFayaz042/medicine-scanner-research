"""Shared records returned by source discovery adapters."""
from typing import Any, TypedDict


class DiscoveredRecord(TypedDict, total=False):
    """Normalized discovery fields shared by document and data sources."""

    source: str
    source_key: str
    document_id: int
    title: str
    release_date: str
    pdf_url: str
    pdf_size_declared: str
    document_type: str
    metadata: dict[str, Any]


def make_data_record(
    *,
    source: str,
    source_key: str,
    record_type: str,
    metadata: dict[str, Any],
) -> DiscoveredRecord:
    """Build a record for a structured source without a downloadable PDF."""
    return {
        "source": source,
        "source_key": source_key,
        "document_type": record_type,
        "metadata": metadata,
    }


def make_document_record(
    *,
    source: str,
    source_key: str,
    document_id: int,
    title: str,
    release_date: str,
    pdf_url: str,
    pdf_size_declared: str,
    document_type: str,
    metadata: dict[str, Any] | None = None,
) -> DiscoveredRecord:
    """Build a record for a downloadable regulatory document."""
    return {
        "source": source,
        "source_key": source_key,
        "document_id": document_id,
        "title": title,
        "release_date": release_date,
        "pdf_url": pdf_url,
        "pdf_size_declared": pdf_size_declared,
        "document_type": document_type,
        "metadata": metadata or {},
    }