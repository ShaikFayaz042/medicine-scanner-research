"""Stage 3 deterministic event-bearing classifier."""

import re
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from .scorer import BATCH_CONTEXT, BATCH_REGEX, MANUFACTURER_SUFFIXES
from .schema import make_verdict

HEADER_PATTERNS = {
    "drug_name_column": (
        "drug", "product", "medicine", "brand", "formulation", "fdc",
        "fixed dose combination", "name of drug", "name of product",
        "name of drugs", "drugs name", "drug name", "product name", "medicine name",
        "suspected drugs", "suspected drug", "suspected medicine",
        "suspected medicines",
    ),
    "batch_column": ("batch", "b no", "batch no", "batch number", "lot"),
    "manufacturer_column": (
        "manufacturer", "mfg", "mfd", "made by", "manufactured by", "company",
    ),
    "reason_column": ("reason", "reason for failure", "failure reason", "defect"),
    "notification_column": ("notification", "notif no", "s o", "s o no", "gazette"),
    "alert_column": ("alert", "alert reason", "adverse", "adr", "adverse drug reaction"),
    "indication_column": ("indication", "used for", "therapeutic use"),
    "notification_date_column": ("date", "notification date", "issue date", "publication date"),
    "status_column": ("status", "action taken", "decision", "outcome"),
}
_HEADER_CATEGORY_PRIORITY = (
    "drug_name_column",
    "batch_column",
    "manufacturer_column",
    "notification_column",
    "notification_date_column",
    "reason_column",
    "status_column",
    "indication_column",
    "alert_column",
)
REGULATORY_CONTEXT_TERMS = (
    "drug", "medicine", "pharmaceutical", "drugs rules", "medical devices rules",
    "schedule m", "schedule h", "section 26a", "section 10a", "cdsco",
    "drug controller", "gazette notification",
)
EVENT_KEYWORDS = (
    "nsq", "spurious", "recall", "banned", "prohibited", "theft", "stolen",
    "falsified", "cancellation", "cancelled", "substandard", "sub-standard",
    "adulterated", "misbranded",
)
DOCUMENT_TYPE_HINTS = {
    "guideline": ("guidance", "guideline", "guidelines"),
    "sop": ("sop", "standard operating procedure"),
    "circular": ("circular",),
    "notice": ("notice",),
    "meeting": ("meeting", "agenda", "minutes"),
    "appointment": ("appointment",),
    "order": ("order",),
    "advisory": ("advisory",),
}
NOTIFICATION_PATTERN = re.compile(
    r"\bS\s*\.\s*O\s*\.?\s*\d+", re.I
)
WORD_RE = re.compile(r"[a-z0-9]+")
NUMBER_UNITS = {
    "billion", "cfu", "g", "gm", "iu", "kg", "l", "mcg", "meq", "mg",
    "million", "ml", "mmol", "mol", "ng", "unit", "units", "ug", "wv",
}
OCR_BATCH_PATTERN = re.compile(
    r"\b(?=[A-Z0-9]{6,12}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]+\b"
)
OCR_BATCH_HEADING = re.compile(r"\b(?:batch|lot)\s*(?:no|number)?\b", re.I)
OCR_PRODUCT_HEADING = re.compile(
    r"\b(?:name of (?:the )?(?:product|drug|fdc)|product name|drug name)\b", re.I
)
OCR_PRODUCT_DETAIL_TERMS = (
    "injection", "tablet", "capsule", "syrup", "solution", "suspension",
    "mg", "mcg", "microgram", "iu",
)


def normalize_text(value):
    return " ".join(WORD_RE.findall(str(value or "").casefold()))


def normalize_lexicon_name(value):
    """Remove standalone numbering and repair spaces inside compact name codes."""
    tokens = normalize_text(value).split()
    merged = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isdigit() and index + 1 < len(tokens):
            following = tokens[index + 1]
            if re.match(r"\d+[a-z]", following) or following in NUMBER_UNITS:
                token += following
                index += 1

        if (len(token) == 1 and token.isalpha() and index + 1 < len(tokens)):
            following = tokens[index + 1]
            if (len(following) == 1 and following.isalpha()) or re.fullmatch(r"[a-z]+\d+", following):
                token += following
                index += 1
                while (len(token) > 1 and token[-1].isalpha()
                       and index + 1 < len(tokens)
                       and len(tokens[index + 1]) == 1
                       and tokens[index + 1].isalpha()):
                    token += tokens[index + 1]
                    index += 1

        if not token.isdigit():
            merged.append(token)
        index += 1
    return " ".join(merged)


def _table_cells(table):
    cells = table.get("cells", []) if isinstance(table, dict) else table
    return [[str(value or "").strip() for value in row] for row in cells or []]


def _document_tables(stage2_doc):
    tables = stage2_doc.get("tables") or []
    if tables:
        return tables
    return [table for page in stage2_doc.get("pages", []) for table in page.get("tables", [])]


def _header_category(value):
    normalized = normalize_text(value)
    if not normalized:
        return None
    best_category = None
    best_score = 84
    for category in _HEADER_CATEGORY_PRIORITY:
        for pattern in HEADER_PATTERNS.get(category, ()):
            candidate = normalize_text(pattern)
            if normalized == candidate:
                score = 200 + len(candidate)
            elif re.search(
                    r"(?<!\w)" + re.escape(candidate) + r"(?!\w)", normalized
                ):
                score = 100 + len(candidate)
            elif len(normalized) <= 64 and len(normalized) >= 8 and len(candidate) >= 8:
                score = fuzz.ratio(normalized, candidate)
            else:
                continue
            if score > best_score:
                best_category = category
                best_score = score
    return best_category


def _header_scan_window(rows):
    nonempty_count = sum(1 for row in rows if any(cell for cell in row))
    if nonempty_count <= 5:
        return nonempty_count
    if nonempty_count <= 20:
        return 5
    return 8


def _looks_like_data_row(row):
    first = next((str(cell).strip() for cell in row if str(cell).strip()), "")
    return bool(re.match(r"^\d+[.)]?$", first))


def _first_data_row_has_anchor(rows):
    first_row = next((row for row in rows if any(row)), [])
    return _looks_like_data_row(first_row)


def _valid_header_candidate(row):
    nonempty = [str(cell).strip() for cell in row if str(cell).strip()]
    if len(nonempty) < 2:
        return False
    if any(len(str(cell)) >= 100 for cell in row):
        return False
    if any(re.match(r"^\d+[.)]?$", str(cell).strip()) for cell in nonempty):
        return False
    return True


def _detect_table_headers(tables):
    results = []
    last_good_header = None
    for table_index, table in enumerate(tables):
        rows = _table_cells(table)
        nonempty = [(index, row) for index, row in enumerate(rows) if any(cell for cell in row)]
        if not nonempty:
            results.append({
                "table_index": table_index,
                "page": table.get("page") if isinstance(table, dict) else None,
                "header_row": None,
                "header_rows_skipped": 0,
                "columns": {},
                "header_values": [],
            })
            continue

        searchable = [entry for entry in nonempty if not _looks_like_data_row(entry[1])]
        candidates = []
        for offset, (row_index, row) in enumerate(searchable):
            if offset >= _header_scan_window(rows):
                break
            if not _valid_header_candidate(row):
                continue
            columns = {}
            for column_index, value in enumerate(row):
                category = _header_category(value)
                if category:
                    columns.setdefault(category, column_index)
            candidates.append((len(columns), offset, row_index, columns, row_index + 1, row))
            if offset > 0:
                previous = searchable[offset - 1][1]
                merged_columns = {}
                for column_index in range(max(len(previous), len(row))):
                    parts = [
                        cells[column_index] for cells in (previous, row)
                        if column_index < len(cells) and cells[column_index]
                    ]
                    category = _header_category(" ".join(parts))
                    if category:
                        merged_columns.setdefault(category, column_index)
                candidates.append((len(merged_columns), offset, row_index,
                                   merged_columns, row_index + 1, row))
        if candidates:
            _, _, header_row, columns, header_rows_skipped, header_values = max(
                candidates, key=lambda item: (item[0], -item[4], -item[1])
            )
        else:
            columns = {}
            header_row = None
            header_rows_skipped = 0
            header_values = []

        if columns:
            header_map = {key: [index] for key, index in columns.items()}
            last_good_header = {
                "columns": header_map,
                "header_values": header_values,
            }
            results.append({
                "table_index": table_index,
                "page": table.get("page") if isinstance(table, dict) else None,
                "header_row": header_row,
                "header_rows_skipped": header_rows_skipped,
                "columns": header_map,
                "header_values": header_values,
            })
        elif last_good_header and _first_data_row_has_anchor(rows):
            results.append({
                "table_index": table_index,
                "page": table.get("page") if isinstance(table, dict) else None,
                "header_row": None,
                "header_rows_skipped": 0,
                "columns": dict(last_good_header["columns"]),
                "header_values": last_good_header["header_values"],
                "header_inherited_from_previous": True,
            })
        else:
            results.append({
                "table_index": table_index,
                "page": table.get("page") if isinstance(table, dict) else None,
                "header_row": None,
                "header_rows_skipped": 0,
                "columns": {},
                "header_values": [],
            })
    return results


def _normalize_lexicons(products, ingredients):
    names = set()
    for entry in list(products or []) + list(ingredients or []):
        row_mapping = getattr(entry, "_mapping", None)
        if row_mapping is not None:
            entry = row_mapping
        if isinstance(entry, Mapping):
            values = (
                entry.get("product_name"), entry.get("brand_name"),
                entry.get("normalized_name"), entry.get("normalized_search_name"),
                entry.get("ingredient_name"), entry.get("name"),
            )
        elif isinstance(entry, (tuple, list)):
            values = entry
        else:
            values = (entry,)
        names.update(normalize_text(value) for value in values if normalize_text(value))
    return names


@lru_cache(maxsize=4)
def _lexicon_pattern(lexicon):
    if not lexicon:
        return None
    alternatives = "|".join(
        re.escape(name) for name in sorted(lexicon, key=len, reverse=True)
    )
    return re.compile(r"(?<!\w)(?:" + alternatives + r")(?!\w)")


def load_medicine_lexicons():
    """Load the checked-in, normalized and globally deduplicated medicine names."""
    lexicon_path = Path(__file__).resolve().parents[1] / "data" / "medicine_lexicon.json"
    with lexicon_path.open("r", encoding="utf-8") as source:
        names = json.load(source).get("names")
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError(f"Invalid medicine lexicon resource: {lexicon_path}")
    if len(names) != len(set(names)):
        raise ValueError(f"Medicine lexicon contains duplicate names: {lexicon_path}")
    return names, []


def _known_name_match(value, lexicon, pattern=None):
    normalized = normalize_text(value)
    if not normalized:
        return None
    if normalized in lexicon:
        return normalized
    embedded = pattern or _lexicon_pattern(frozenset(lexicon))
    match = embedded.search(normalized) if embedded else None
    if match:
        return match.group()
    if not lexicon:
        return None
    match = process.extractOne(
        normalized, lexicon, scorer=fuzz.token_sort_ratio, score_cutoff=85
    )
    return match[0] if match else None


def _match_paragraph_drugs(text, lexicon, pattern=None):
    normalized_text = normalize_text(text)
    pattern = pattern or _lexicon_pattern(frozenset(lexicon))
    matches = {match.group() for match in pattern.finditer(normalized_text)} if pattern else set()
    if matches or not lexicon:
        return matches
    for line in text.splitlines():
        candidate = normalize_text(line)
        if candidate and len(candidate) <= 1200:
            match = process.extractOne(
                candidate, lexicon, scorer=fuzz.token_sort_ratio, score_cutoff=85
            )
            if match:
                matches.add(match[0])
    return matches


def _paragraph_entities(text, lexicon, lexicon_pattern=None):
    drugs = _match_paragraph_drugs(text, lexicon, lexicon_pattern)
    batches = set()
    for match in BATCH_REGEX.finditer(text):
        context = text[max(0, match.start() - 50):match.end() + 50]
        if BATCH_CONTEXT.search(context):
            batches.add(match.group().casefold())
    manufacturers = set()
    for suffix in MANUFACTURER_SUFFIXES:
        pattern = re.compile(
            r"\b[\w&.'-]+(?:\s+[\w&.'-]+){0,5}\s+" + re.escape(suffix) + r"\b", re.I
        )
        manufacturers.update(match.group().strip() for match in pattern.finditer(text))
    return drugs, batches, manufacturers


def _normalize_ocr_token_boundaries(text):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text or "")


def _ocr_batch_matches(text):
    if not OCR_BATCH_HEADING.search(text or ""):
        return set()
    return {match.group().casefold() for match in OCR_BATCH_PATTERN.finditer(text or "")}


def _has_scanned_product_details(text, drug_matches):
    generic_matches = {
        "drug", "drugs", "india", "medicine", "medicines", "product",
        "products", "pharma", "pharmaceutical", "pharmaceuticals",
    }
    if any(match.casefold() not in generic_matches for match in drug_matches):
        return True

    normalized = normalize_text(_normalize_ocr_token_boundaries(text)).casefold()
    compact = normalized.replace(" ", "")
    has_product_heading = bool(OCR_PRODUCT_HEADING.search(normalized)) or bool(
        re.search(r"(?:nameof(?:the)?(?:product|drug|fdc)|productname|drugname)", compact)
    )
    if not has_product_heading:
        return False

    detail_count = sum(compact.count(term) for term in OCR_PRODUCT_DETAIL_TERMS)
    return detail_count >= 2


def _document_type_hint(stage2_doc):
    filename = normalize_text(Path(str(stage2_doc.get("doc_id", ""))).name)
    for hint, patterns in DOCUMENT_TYPE_HINTS.items():
        if any(
            re.search(r"(?<!\w)" + re.escape(normalize_text(pattern)) + r"(?!\w)", filename)
            for pattern in patterns
        ):
            return hint
    return None


def _empty_deterministic(table_count):
    return {
        "rule_matched": None,
        "table_count": table_count,
        "table_header_map": [],
        "table_drug_matches": 0,
        "table_fdc_matches": 0,
        "paragraph_drug_matches": 0,
        "paragraph_batch_matches": 0,
        "paragraph_manufacturer_matches": 0,
        "regulatory_context_hits": [],
        "document_type_hint": None,
    }


def _d5_should_fire(context_hits, table_header_map, paragraph_drug_matches, document_type_hint):
    if any(table.get("columns") for table in table_header_map):
        return False
    if document_type_hint:
        return True
    distinct_context_hits = set(context_hits)
    if len(distinct_context_hits) >= 2:
        return True
    return len(distinct_context_hits) == 1 and paragraph_drug_matches >= 2


def classify_document(stage2_doc, products=None, ingredients=None):
    """Apply D1-D8 in order and return the Stage 3 v2 bucket contract."""
    doc_id = stage2_doc.get("doc_id", "unknown")
    source = stage2_doc.get("source_name", "unknown")
    pages = stage2_doc.get("pages", [])
    full_text = "\n".join(page.get("text") or "" for page in pages)
    tables = _document_tables(stage2_doc)
    lexicon = _normalize_lexicons(products, ingredients)
    lexicon_pattern = _lexicon_pattern(frozenset(lexicon))
    deterministic = _empty_deterministic(len(tables))
    deterministic["table_header_map"] = _detect_table_headers(tables)
    deterministic["document_type_hint"] = _document_type_hint(stage2_doc)
    extraction_meta = stage2_doc.get("extraction_meta", {})
    scanned_pages = int(extraction_meta.get("ocr_pages") or 0)
    ocr_text = "\n".join(
        page.get("text") or ""
        for page in pages
        if page.get("method") == "rapidocr" or page.get("type") == "image"
    )
    ocr_pending = (
        scanned_pages > 0
        and extraction_meta.get("text_pages", 0) == 0
        and not extraction_meta.get("stage3_ocr_completed_pages", 0)
    )

    if ocr_pending:
        rule, bucket, reason = "D7", "event-bearing", "deterministic_event_signal"
    else:
        table_matches = set()
        fdc_matches = 0
        for table, header in zip(tables, deterministic["table_header_map"]):
            rows = _table_cells(table)
            columns = header.get("columns", {})
            drug_columns = columns.get("drug_name_column", [])
            if not drug_columns:
                continue
            skip_rows = header.get("header_rows_skipped", 0)
            for row in rows[skip_rows:]:
                for column in drug_columns:
                    if column >= len(row) or not row[column]:
                        continue
                    value = row[column]
                    match = _known_name_match(value, lexicon, lexicon_pattern)
                    normalized = normalize_text(value)
                    if normalized and re.search(r"[a-z]", normalized):
                        table_matches.add(match or "raw:" + normalized)

            headers = " ".join(header.get("header_values", [])).casefold()
            notification_columns = columns.get("notification_column", [])
            has_fdc = "fixed dose combination" in normalize_text(headers) or re.search(r"\bfdc\b", headers)
            if has_fdc and notification_columns:
                for row in rows[skip_rows:]:
                    if any(
                        column < len(row) and NOTIFICATION_PATTERN.search(row[column])
                        for column in notification_columns
                    ):
                        fdc_matches += 1

        deterministic["table_drug_matches"] = len(table_matches)
        deterministic["table_fdc_matches"] = fdc_matches

        if table_matches:
            rule, bucket, reason = "D2", "event-bearing", "deterministic_event_signal"
        elif fdc_matches:
            rule, bucket, reason = "D3", "event-bearing", "deterministic_event_signal"
        else:
            drugs, batches, manufacturers = _paragraph_entities(
                full_text, lexicon, lexicon_pattern
            )
            if scanned_pages:
                normalized_ocr_text = _normalize_ocr_token_boundaries(ocr_text)
                ocr_drugs, ocr_batches, ocr_manufacturers = _paragraph_entities(
                    normalized_ocr_text, lexicon, lexicon_pattern
                )
                drugs.update(ocr_drugs)
                batches.update(ocr_batches)
                batches.update(_ocr_batch_matches(normalized_ocr_text))
                manufacturers.update(ocr_manufacturers)
            deterministic["paragraph_drug_matches"] = len(drugs)
            deterministic["paragraph_batch_matches"] = len(batches)
            deterministic["paragraph_manufacturer_matches"] = len(manufacturers)
            event_terms = [
                term for term in EVENT_KEYWORDS
                if re.search(r"\b" + re.escape(term) + r"\b", full_text, re.I)
            ]
            scanned_drug_details = scanned_pages and _has_scanned_product_details(
                ocr_text, drugs
            )
            if scanned_drug_details and (batches or manufacturers):
                rule, bucket, reason = "D8", "event-bearing", "deterministic_event_signal"
            elif drugs and (batches or manufacturers or event_terms):
                rule, bucket, reason = "D4", "event-bearing", "deterministic_event_signal"
            else:
                normalized_text = normalize_text(full_text)
                context_hits = [
                    term for term in REGULATORY_CONTEXT_TERMS
                    if re.search(
                        r"(?<!\w)" + re.escape(normalize_text(term)) + r"(?!\w)",
                        normalized_text,
                    )
                ]
                deterministic["regulatory_context_hits"] = context_hits
                if _d5_should_fire(
                    context_hits,
                    deterministic["table_header_map"],
                    deterministic["paragraph_drug_matches"],
                    deterministic["document_type_hint"],
                ):
                    rule, bucket, reason = "D5", "context-only", "regulatory_context_detected"
                else:
                    rule, bucket, reason = "D6", "unimportant", "no_regulatory_signal"

    deterministic["rule_matched"] = rule
    return make_verdict(
        doc_id, source, bucket, reason, deterministic, ocr_pending,
        len(full_text), len(pages),
    )
