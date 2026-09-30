"""Stage 3 summary fields that are not populated by its verdict factory."""

from __future__ import annotations

import re
from typing import Any

from .keywords import (
    BORDERLINE_HIGH,
    BORDERLINE_LOW,
    TOPICAL_HIGH,
    TOPICAL_LOW,
)
from .scorer import compute_topical_score

EVENT_TERMS = (
    "not of standard quality",
    "nsq",
    "substandard",
    "sub-standard",
    "spurious",
    "adulterated",
    "misbranded",
    "falsified",
    "counterfeit",
    "recall",
    "recalled",
    "banned",
    "prohibited",
    "prohibition",
    "withdrawal",
    "withdrawn",
    "suspension",
    "suspended",
    "cancellation",
    "cancelled",
    "drug safety alert",
    "safety alert",
    "safety advisory",
    "adverse drug reaction",
    "adverse drug reaction alert",
    "pharmacovigilance",
    "theft",
    "stolen",
    "falsified version",
    "unapproved fdc",
    "irrational fixed dose combination",
    "irrational fdc",
    "fixed dose combination",
)

_CONTEXT_GATED_TERMS = {
    "fixed dose combination": (
        "unapproved", "irrational", "prohibited", "banned", "withdrawal",
    ),
    "prohibited": ("manufacture", "sale", "distribution", "drug", "fdc"),
    "banned": (
        "drug", "manufacture", "sale", "fdc", "notification", "combination",
    ),
}
_EVENT_TERM_PATTERNS = tuple(
    re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    for term in EVENT_TERMS
    if term not in _CONTEXT_GATED_TERMS
)
_EVENT_TERMS_FOR_PATTERNS = tuple(
    term for term in EVENT_TERMS if term not in _CONTEXT_GATED_TERMS
)
_CONTEXT_GATED_PATTERNS = {
    re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE): tuple(
        re.compile(rf"\b{re.escape(gate)}\b", re.IGNORECASE)
        for gate in gate_terms
    )
    for term, gate_terms in _CONTEXT_GATED_TERMS.items()
}


def _normalized_context_text(text: str, filename: str | None = None) -> str:
    combined = " ".join(part for part in (text, filename) if part)
    if not combined:
        return ""
    normalized = re.sub(r"[_/\\-]+", " ", combined)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.casefold()


def _has_event_context(text: str, filename: str | None = None) -> bool:
    combined = _normalized_context_text(text, filename)
    if not combined:
        return False
    for term_pattern, gate_patterns in _CONTEXT_GATED_PATTERNS.items():
        if term_pattern.search(combined) and any(pattern.search(combined) for pattern in gate_patterns):
            return True
    if any(pattern.search(combined) for pattern in _EVENT_TERM_PATTERNS):
        return True
    if re.search(r"\bunapproved\s+fdc(?:s)?\b", combined) or re.search(
        r"\birrational\s+(?:fixed\s+dose\s+combination|fdc(?:s)?)\b", combined
    ):
        return True
    return _has_pvpi_adr_pair(combined)


def _has_pvpi_adr_pair(text: str) -> bool:
    normalized = text.casefold()
    has_pvpi = "pvpi" in normalized or "pharmacovigilance programme of india" in normalized
    has_adr = bool(re.search(r"\badr\b", normalized)) or "adverse drug reaction" in normalized
    return has_pvpi and has_adr


def _distinct_event_term_count(text: str) -> int:
    matches = sorted(
        (match.start(), match.end(), term)
        for term, pattern in zip(_EVENT_TERMS_FOR_PATTERNS, _EVENT_TERM_PATTERNS)
        for match in pattern.finditer(text)
    )
    matched_terms = set()
    group_end = -1
    group_terms = []
    for start, end, term in matches:
        if group_terms and start >= group_end:
            matched_terms.add(max(group_terms, key=len))
            group_terms = []
        group_terms.append(term)
        group_end = max(group_end, end)
    if group_terms:
        matched_terms.add(max(group_terms, key=len))
    if _has_pvpi_adr_pair(text):
        matched_terms.update(("pvpi", "adr"))
    return len(matched_terms)


def _has_strong_event_evidence(deterministic: dict[str, Any], text: str, filename: str | None = None) -> bool:
    if deterministic.get("table_drug_matches", 0) >= 1:
        return True
    if deterministic.get("table_fdc_matches", 0) >= 1:
        return True
    context_text = _normalized_context_text(text, filename)
    if _has_event_context(text, filename) and (
        deterministic.get("paragraph_batch_matches", 0) >= 1
        or deterministic.get("paragraph_drug_matches", 0) >= 1
        or re.search(r"\b(?:unapproved|irrational)\s+fdc(?:s)?\b", context_text)
    ):
        return True
    return _distinct_event_term_count(context_text) >= 2


def complete_classifier_fields(
    verdict: dict[str, Any], text: str, filename: str | None = None
) -> dict[str, Any]:
    """Populate legacy score fields and keep weak D4 entity hits reviewable."""
    score, matched_keywords = compute_topical_score(text)
    verdict["topical_score"] = round(score, 4)
    verdict["matched_keywords"] = matched_keywords
    if BORDERLINE_LOW <= score <= BORDERLINE_HIGH:
        verdict["score_band"] = "borderline"
    elif score >= TOPICAL_HIGH:
        verdict["score_band"] = "high"
    elif score >= TOPICAL_LOW:
        verdict["score_band"] = "medium"
    else:
        verdict["score_band"] = "low"

    deterministic = verdict.get("deterministic") or {}
    manufacturer_hits = deterministic.get("paragraph_manufacturer_matches", 0)
    batch_hits = deterministic.get("paragraph_batch_matches", 0)
    if (
        deterministic.get("rule_matched") == "D4"
        and manufacturer_hits
        and not batch_hits
        and not _has_event_context(text, filename)
    ):
        verdict["bucket"] = "context-only"
        verdict["bucket_reason"] = "drug_and_manufacturer_without_event_context"
        verdict["is_relevant"] = False
        verdict["needs_review"] = False
        verdict["needs_review_reasons"] = []
        verdict["deterministic"] = deterministic
        return verdict

    strong_evidence = _has_strong_event_evidence(deterministic, text, filename)
    if strong_evidence and verdict.get("bucket") != "event-bearing":
        verdict["bucket"] = "event-bearing"
        verdict["bucket_reason"] = "explicit_drug_safety_event"
        verdict["is_relevant"] = True
        verdict["needs_review"] = False
        verdict["needs_review_reasons"] = []
        if deterministic.get("table_drug_matches", 0) >= 1:
            deterministic["rule_matched"] = "D2"
        elif deterministic.get("table_fdc_matches", 0) >= 1:
            deterministic["rule_matched"] = "D3"
        else:
            deterministic["rule_matched"] = "D4"
    elif deterministic.get("rule_matched") == "D4" and verdict.get("bucket") == "event-bearing":
        verdict["bucket"] = "context-only"
        verdict["bucket_reason"] = "weak_event_signal"
        verdict["is_relevant"] = False
        verdict["needs_review"] = True
        verdict["needs_review_reasons"] = ["weak_event_signal"]
    elif _has_event_context(text, filename) and verdict.get("bucket") == "context-only":
        verdict["needs_review"] = True
        reasons = set(verdict.get("needs_review_reasons") or [])
        reasons.add("weak_event_signal")
        verdict["needs_review_reasons"] = sorted(reasons)

    verdict["deterministic"] = deterministic
    return verdict