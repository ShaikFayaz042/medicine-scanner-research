"""Shared utilities for the normalization pipeline."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from dateutil import parser as dateparser
except ImportError:
    dateparser = None

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "normalization" / "config"
OUTPUT_DIR = ROOT / "normalization" / "output"
STRUCTURED_RAW = ROOT / "structured_raw"

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_UNIT_STRENGTH_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mg|mcg|ug|g|gm|ml|iu|%)", re.IGNORECASE
)
_BARE_STRENGTH_RE = re.compile(
    r"(?<![a-z0-9])(\d+(?:\.\d+)?)(?![a-z0-9])", re.IGNORECASE
)
_COMPOSITION_RE = re.compile(r"\(([^()]*(?:mg|mcg|g|ml|%|iu|,|&)[^()]*)\)\s*$", re.IGNORECASE)
MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2,
    "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def load_config(name: str) -> dict:
    path = CONFIG_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing config: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_all_configs() -> dict:
    return {
        "field_mapping": load_config("field_mapping"),
        "terminology": load_config("terminology"),
        "status_mapping": load_config("status_mapping"),
        "entity_resolution": load_config("entity_resolution"),
        "schema_contract": load_config("schema_contract"),
    }


def collapse_ws(value: str | None) -> str:
    return _WS.sub(" ", value or "").strip()


def normalize_name(value: str | None) -> str:
    return _NON_ALNUM.sub(" ", (value or "").lower()).strip()


def normalize_search_name(value: str | None) -> str:
    return collapse_ws(normalize_name(value))


def extract_strengths(name: str | None) -> frozenset[str]:
    """Extract distinct numeric tokens used to compare product strengths."""
    if not name:
        return frozenset()
    numbers = {match.group(1) for match in _UNIT_STRENGTH_RE.finditer(name)}
    numbers.update(match.group(1) for match in _BARE_STRENGTH_RE.finditer(name))
    return frozenset(numbers)


_SALT_TOKENS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bdihydrochloride\b", re.I), "dihydrochloride"),
    (re.compile(r"\bhydrochloride\b|\bhcl\b", re.I), "hydrochloride"),
    (re.compile(r"\bhydrobromide\b", re.I), "hydrobromide"),
    (re.compile(r"\bsodium\b", re.I), "sodium"),
    (re.compile(r"\bpotassium\b", re.I), "potassium"),
    (re.compile(r"\bcalcium\b", re.I), "calcium"),
    (re.compile(r"\bmagnesium\b", re.I), "magnesium"),
    (re.compile(r"\bsulphate\b|\bsulfate\b", re.I), "sulphate"),
    (re.compile(r"\bphosphate\b", re.I), "phosphate"),
    (re.compile(r"\bmaleate\b", re.I), "maleate"),
    (re.compile(r"\btartrate\b", re.I), "tartrate"),
    (re.compile(r"\bcitrate\b", re.I), "citrate"),
    (re.compile(r"\bfumarate\b", re.I), "fumarate"),
    (re.compile(r"\bsuccinate\b", re.I), "succinate"),
    (re.compile(r"\bbesylate\b|\bbesilate\b", re.I), "besylate"),
    (re.compile(r"\bmesylate\b|\bmesilate\b", re.I), "mesylate"),
    (re.compile(r"\btosylate\b", re.I), "tosylate"),
    (re.compile(r"\bacetate\b", re.I), "acetate"),
    (re.compile(r"\bnitrate\b", re.I), "nitrate"),
    (re.compile(r"\bchloride\b", re.I), "chloride"),
    (re.compile(r"\bbromide\b", re.I), "bromide"),
    (re.compile(r"\biodide\b", re.I), "iodide"),
    (re.compile(r"\boxide\b", re.I), "oxide"),
]
_SALT_BASE = "__base__"


def extract_salt_forms(name: str | None) -> frozenset[str]:
    if not name:
        return frozenset()
    forms = {token for pattern, token in _SALT_TOKENS if pattern.search(name)}
    return frozenset(forms or {_SALT_BASE})


_RELEASE_CS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bS\.?R\.?\b"), "SR"),
    (re.compile(r"\bI\.?R\.?\b"), "IR"),
    (re.compile(r"\bE\.?R\.?\b"), "ER"),
    (re.compile(r"\bX\.?L\.?\b"), "ER"),
    (re.compile(r"\bC\.?R\.?\b"), "CR"),
    (re.compile(r"\bM\.?R\.?\b"), "MR"),
    (re.compile(r"\bD\.?R\.?\b"), "DR"),
]
_RELEASE_CI: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sustained\s+release", re.I), "SR"),
    (re.compile(r"immediate\s+release", re.I), "IR"),
    (re.compile(r"extended\s+release", re.I), "ER"),
    (re.compile(r"controlled\s+release", re.I), "CR"),
    (re.compile(r"modified\s+release", re.I), "MR"),
    (re.compile(r"delayed\s+release", re.I), "DR"),
    (re.compile(r"prolonged\s+release", re.I), "PR"),
]
_RELEASE_UNSPECIFIED = "__unspecified__"


def extract_release_forms(name: str | None) -> frozenset[str]:
    if not name:
        return frozenset()
    forms = {token for pattern, token in _RELEASE_CS if pattern.search(name)}
    forms.update(token for pattern, token in _RELEASE_CI if pattern.search(name))
    return frozenset(forms or {_RELEASE_UNSPECIFIED})


def make_candidate_key(*parts: str) -> str:
    """Return a deterministic short hash for normalized candidate parts."""
    joined = "|".join((part or "").lower().strip() for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def split_product_and_composition(raw: str | None) -> tuple[str | None, str | None]:
    value = collapse_ws(raw)
    if not value:
        return None, None
    match = _COMPOSITION_RE.search(value)
    if not match:
        return value, None
    name = value[:match.start()].strip()
    return name or value, collapse_ws(match.group(1))


def detect_dosage_form(value: str | None) -> str | None:
    text = collapse_ws(value).lower()
    for form in (
        "extended release tablet", "modified release tablet", "dispersible tablet",
        "film coated tablet", "hard gelatin capsule", "soft gelatin capsule",
        "tablet", "capsule", "injection", "infusion", "suspension", "syrup",
        "solution", "cream", "ointment", "gel", "drops", "powder",
    ):
        if re.search(r"(?<![a-z])" + re.escape(form) + r"(?![a-z])", text):
            return form
    return None


def parse_composition(value: str | None) -> list[dict[str, Any]]:
    text = collapse_ws(value)
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"\s*(?:\+|;|,|\band\b)\s*", text, flags=re.IGNORECASE) if part.strip()]
    rows: list[dict[str, Any]] = []
    for index, part in enumerate(parts, start=1):
        match = re.search(r"^(.*?)(?:\s+)(\d+(?:\.\d+)?)\s*([a-zA-Z%µ]+(?:\s*/\s*[a-zA-Z0-9]+)?)?\s*$", part)
        if match:
            name = collapse_ws(match.group(1))
            strength = float(match.group(2))
            unit = safe_str(match.group(3))
            strength_text = collapse_ws(part[len(match.group(1)):])
        else:
            name, strength, unit, strength_text = part, None, None, None
        rows.append({
            "ingredient_name_raw": name,
            "strength": strength,
            "strength_text": strength_text,
            "unit": unit,
            "basis": None,
            "sequence_no": index,
        })
    return rows


def parse_drug_alert_batch_field(value: str | None) -> dict[str, str | None]:
    text = collapse_ws(value)
    if not text:
        return {"batch_number": None, "mfg_date_raw": None, "expiry_date_raw": None, "manufacturer_name_raw": None}
    batch = re.search(r"(?:batch|b\.?\s*no\.?)\s*[:\-]?\s*([^,;]+)", text, re.IGNORECASE)
    mfg = re.search(r"(?:mfg|mfd|manufactur(?:ing|ed))\s*(?:dt|date|by)?\s*[:\-]?\s*([^,;]+)", text, re.IGNORECASE)
    exp = re.search(r"(?:exp|expiry)\s*(?:dt|date)?\s*[:\-]?\s*([^,;]+)", text, re.IGNORECASE)
    return {
        "batch_number": safe_str(batch.group(1)) if batch else text,
        "mfg_date_raw": safe_str(mfg.group(1)) if mfg else None,
        "expiry_date_raw": safe_str(exp.group(1)) if exp else None,
        "manufacturer_name_raw": safe_str(mfg.group(1)) if mfg and re.search(r"\bby\b", mfg.group(0), re.IGNORECASE) else None,
    }


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = collapse_ws(value)
    else:
        value = collapse_ws(str(value))
    return value or None


def classify_missing(value: Any, applicable: bool) -> str:
    if value:
        return "PRESENT"
    if not applicable:
        return "NOT_APPLICABLE"
    return "EXTRACTION_MISSING"


def parse_date_with_precision(raw: str | None) -> tuple[date | None, str | None]:
    if not raw:
        return None, None
    value = collapse_ws(raw)
    if not value or value.lower() in {"nil", "na", "n/a", "-", "not available"}:
        return None, None
    if re.fullmatch(r"\d{4}", value):
        return None, "YEAR"
    if re.fullmatch(r"\d{1,2}[/\-]\d{4}", value):
        return None, "MONTH"
    month_match = re.fullmatch(r"([A-Za-z]+)[\-\s,/]+(\d{2,4})", value)
    if month_match and month_match.group(1).lower() in MONTH_NAMES:
        return None, "MONTH"
    parsed = None
    if dateparser is not None:
        try:
            parsed = dateparser.parse(value, fuzzy=False, dayfirst=True)
        except (ValueError, OverflowError, TypeError):
            parsed = None
    if parsed is None:
        for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
            try:
                parsed = datetime.strptime(value, pattern)
                break
            except ValueError:
                continue
    return (parsed.date(), "DAY") if parsed else (None, "UNKNOWN")


def make_source_record_id(folder: str, filename: str, record_index: int) -> str:
    return f"{folder}/{filename}#{record_index}"


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_jsonl(rows: Iterable[dict], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _phrase_matches(phrase: str, haystack: str) -> bool:
    """Match phrases without allowing short tokens inside larger words."""
    phrase = phrase.lower()
    if " " in phrase:
        return phrase in haystack
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def resolve_event_mapping(text: str, status_mapping: dict) -> dict | None:
    """Resolve the highest-priority phrase, with '*' treated as fallback only."""
    haystack = collapse_ws(text).lower()
    rules = sorted(
        status_mapping.get("rules", []),
        key=lambda rule: (
            -int(rule.get("priority", 0)),
            -max((len(match) for match in rule.get("match", []) if match != "*"), default=0),
        ),
    )
    fallback = None
    for rule in rules:
        matches = rule.get("match", [])
        if "*" in matches:
            fallback = rule
            continue
        for phrase in matches:
            if phrase and _phrase_matches(phrase, haystack):
                return {
                    "event_type": rule.get("event_type"),
                    "status": rule.get("status"),
                    "legal_status": rule.get("legal_status"),
                    "investigation_status": rule.get("investigation_status"),
                    "scope": rule.get("scope"),
                    "_matched_rule_priority": rule.get("priority"),
                    "_matched_phrase": phrase,
                }
    if fallback is not None:
        return {
            "event_type": fallback.get("event_type"),
            "status": fallback.get("status"),
            "legal_status": fallback.get("legal_status"),
            "investigation_status": fallback.get("investigation_status"),
            "scope": fallback.get("scope"),
            "_matched_rule_priority": fallback.get("priority"),
            "_matched_phrase": "*",
        }
    return None
