"""
Deterministic scorers: topical score + entity scan.
Pure functions, no I/O, no model.
"""

import re

from .keywords import (
    TOPICAL_KEYWORDS,
    TOPICAL_MAX_SCORE,
    MAX_COUNT_PER_KEYWORD,
)

WHITESPACE_RE = re.compile(r"\s+")

BATCH_REGEX = re.compile(r"\b[A-Z]{1,4}\d{3,8}[A-Z]?\b")
BATCH_CONTEXT = re.compile(r"batch|b\.?\s*no|lot", re.IGNORECASE)

MANUFACTURER_SUFFIXES = [
    "ltd", "pvt ltd", "pharmaceuticals",
    "pharma", "labs", "laboratories",
]

# Small stub. Replace with real lexicon from DB later.
DRUG_LEXICON_STUB = [
    "paracetamol", "ibuprofen", "nimesulide", "diclofenac", "amoxicillin",
    "azithromycin", "cefixime", "metformin", "atorvastatin", "omeprazole",
    "pantoprazole", "cetirizine", "ambroxol", "dextromethorphan",
    "oxytocin", "etodolac", "sibutramine", "gatifloxacin", "tegaserod",
]


def normalize_text(text):
    """Collapse all whitespace (including newlines) to single spaces."""
    if not text:
        return ""
    return WHITESPACE_RE.sub(" ", text).strip()


def compute_topical_score(text):
    """Return (normalized_score, matched_keywords_dict)."""
    if not text:
        return 0.0, {}

    text_lower = normalize_text(text).lower()
    raw = 0
    matched = {}
    for kw, weight in TOPICAL_KEYWORDS.items():
        count = text_lower.count(kw)
        if count > 0:
            capped = min(count, MAX_COUNT_PER_KEYWORD)
            raw += weight * capped
            matched[kw] = count

    score = min(1.0, raw / TOPICAL_MAX_SCORE)
    return score, matched


def scan_entities(text):
    """Return dict with counts of batch_numbers / manufacturer_names / drug_names."""
    empty = {"batch_numbers": 0, "manufacturer_names": 0, "drug_names": 0}
    if not text:
        return empty

    text_norm = normalize_text(text)
    text_lower = text_norm.lower()

    batch_matches = set()
    for match in BATCH_REGEX.finditer(text_norm):
        start = max(0, match.start() - 50)
        end = min(len(text_norm), match.end() + 50)
        context = text_norm[start:end]
        if BATCH_CONTEXT.search(context):
            batch_matches.add(match.group())

    manufacturer_matches = set()
    for suffix in MANUFACTURER_SUFFIXES:
        pattern = re.compile(
            r"\b\w+\s+" + re.escape(suffix) + r"\b", re.IGNORECASE
        )
        for match in pattern.finditer(text_norm):
            manufacturer_matches.add(match.group().strip())

    drug_matches = set()
    for drug in DRUG_LEXICON_STUB:
        if drug in text_lower:
            drug_matches.add(drug)

    return {
        "batch_numbers": len(batch_matches),
        "manufacturer_names": len(manufacturer_matches),
        "drug_names": len(drug_matches),
    }
