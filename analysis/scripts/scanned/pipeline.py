import csv
import datetime
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from statistics import median

from . import config as C


@dataclass
class Block:
    text: str
    confidence: float
    bbox: list
    page: int

    def __post_init__(self):
        points = [point for point in self.bbox if isinstance(point, (list, tuple)) and len(point) >= 2]
        if not points:
            raise ValueError("OCR block has no polygon points")
        self.x0 = min(point[0] for point in points)
        self.x1 = max(point[0] for point in points)
        self.y0 = min(point[1] for point in points)
        self.y1 = max(point[1] for point in points)
        self.cx = (self.x0 + self.x1) / 2
        self.cy = (self.y0 + self.y1) / 2
        self.height = max(1.0, self.y1 - self.y0)


def load_blocks(doc):
    metadata = doc.get("extraction_meta") or {}
    if metadata.get("ocr_pages", 0) == 0 and metadata.get("text_pages", 0) > 0:
        return
    for page in doc.get("pages", []):
        if str(page.get("type", "")).casefold() == "text":
            continue
        for item in page.get("ocr_blocks") or []:
            text = str(item.get("text", "")).strip()
            if not text or not item.get("bbox"):
                continue
            try:
                yield Block(
                    text=text,
                    confidence=float(item.get("confidence", 0.0)),
                    bbox=item["bbox"],
                    page=int(page["page"]),
                )
            except (KeyError, TypeError, ValueError):
                continue


def _row_bounds(row):
    return median(block.y0 for block in row), median(block.y1 for block in row)


def group_rows(blocks):
    ordered = sorted(blocks, key=lambda block: (block.cy, block.x0))
    rows = []
    for block in ordered:
        matches = []
        for row in rows[-4:]:
            y0, y1 = _row_bounds(row)
            overlap = max(0.0, min(y1, block.y1) - max(y0, block.y0))
            overlap_ratio = overlap / min(max(1.0, y1 - y0), block.height)
            center_delta = abs(block.cy - median(item.cy for item in row))
            if overlap_ratio >= C.ROW_OVERLAP_RATIO or center_delta <= C.ROW_Y_TOL:
                matches.append((overlap_ratio, -center_delta, row))
        if matches:
            max(matches, key=lambda match: (match[0], match[1]))[2].append(block)
        else:
            rows.append([block])
    for row in rows:
        row.sort(key=lambda block: block.x0)
    return rows


@lru_cache(maxsize=4096)
def _normalize(text):
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(text))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _phrase_hits(text, phrases):
    normalized = f" {_normalize(text)} "
    return {
        phrase
        for phrase in phrases
        if f" {_normalize(phrase)} " in normalized
    }


def _signature_scores(text, signatures):
    normalized = f" {_normalize(text)} "
    return {
        archetype: sum(
            f" {_normalize(phrase)} " in normalized
            for phrase in phrases
        )
        for archetype, phrases in signatures.items()
    }


def _header_score(texts):
    text = " ".join(texts)
    signature_score = max(_signature_scores(text, C.TABLE_SIGNATURES).values(), default=0)
    generic_score = len(_phrase_hits(text, C.TABLE_HEADER_KEYWORDS))
    return max(signature_score, min(generic_score, 5) if generic_score >= 3 else 0)


def _row_has_columns(row):
    if len(row) < C.MIN_TABLE_COLS:
        return False
    ordered = sorted(row, key=lambda block: block.x0)
    return any(right.x0 - left.x1 >= 20 for left, right in zip(ordered, ordered[1:]))


def _header_candidates(rows):
    candidates = []
    index = 0
    while index < len(rows):
        if not _row_has_columns(rows[index]):
            index += 1
            continue
        row_text = [block.text for block in rows[index]]
        if _header_score(row_text) >= 2:
            candidates.append((index, index, row_text))
            index += 1
            continue

        window_rows = [rows[index]]
        next_index = index + 1
        for end in range(index + 1, min(len(rows), index + C.MAX_HEADER_ROWS)):
            previous_bottom = max(block.y1 for block in window_rows[-1])
            next_top = min(block.y0 for block in rows[end])
            row_height = median(block.height for row in window_rows for block in row)
            if next_top - previous_bottom > max(C.ROW_Y_TOL * 3, row_height * 1.5):
                break
            if not _row_has_columns(rows[end]):
                continue
            window_rows.append(rows[end])
            texts = [block.text for row in window_rows for block in row]
            if _header_score(texts) >= 2:
                candidates.append((index, end, texts))
                next_index = end + 1
                break
        index = next_index
    return candidates


def _infer_table_archetype(header):
    scores = _signature_scores(" ".join(header), C.TABLE_SIGNATURES)
    best = max(scores, key=scores.get, default=None)
    return best if best and scores[best] >= 2 else None


def reconstruct_tables(blocks):
    page_blocks = {}
    for block in blocks:
        page_blocks.setdefault(block.page, []).append(block)
    page_rows = {page: group_rows(items) for page, items in page_blocks.items()}
    tables = []
    used = set()
    pages = sorted(page_rows)

    for page_index, page in enumerate(pages):
        rows = page_rows[page]
        for start, end, header in _header_candidates(rows):
            header_blocks = [block for row in rows[start:end + 1] for block in row]
            if not _row_has_columns(header_blocks):
                continue
            table_blocks = list(header_blocks)
            body_started = False
            for row in rows[end + 1:]:
                if _row_has_columns(row):
                    body_started = True
                    table_blocks.extend(row)
                elif body_started:
                    break
            if (not body_started or end >= len(rows) - 3) and page_index + 1 < len(pages):
                next_page = pages[page_index + 1]
                next_rows = page_rows[next_page][:12]
                if next_rows:
                    header_x = sorted(block.x0 for block in header_blocks)
                    first_x = sorted(block.x0 for block in next_rows[0])
                    if max((abs(a - b) for a, b in zip(first_x[:len(header_x)], header_x[:len(first_x)])), default=0) <= 25:
                        for row in next_rows:
                            if _row_has_columns(row):
                                body_started = True
                                table_blocks.extend(row)
                            elif body_started:
                                break

            tables.append({
                "page": page,
                "pages": sorted({block.page for block in table_blocks}),
                "header": header,
                "archetype": _infer_table_archetype(header),
                "confidence": sum(block.confidence for block in header_blocks) / len(header_blocks),
            })
            used.update(id(block) for block in table_blocks)
    return tables, used


def extract_paragraphs(blocks, consumed_ids):
    remaining = [block for block in blocks if id(block) not in consumed_ids]
    page_blocks = {}
    for block in remaining:
        page_blocks.setdefault(block.page, []).append(block)
    paragraphs = []

    for page, blocks_on_page in sorted(page_blocks.items()):
        rows = group_rows(blocks_on_page)
        buffer = []

        def flush():
            if not buffer:
                return
            text = " ".join(block.text for block in buffer).strip()
            if text and not _is_boilerplate(text):
                paragraphs.append({
                    "text": text,
                    "page": page,
                    "confidence": sum(block.confidence for block in buffer) / len(buffer),
                })
            buffer.clear()

        previous_bottom = None
        previous_height = 0.0
        for row in rows:
            text = " ".join(block.text for block in row).strip()
            if not text or _is_boilerplate(text):
                continue
            top = min(block.y0 for block in row)
            bottom = max(block.y1 for block in row)
            height = median(block.height for block in row)
            if previous_bottom is not None and top - previous_bottom > max(C.ROW_Y_TOL * 3, previous_height * 1.3):
                flush()
            if len(text) <= 80 and (text.isupper() or text.endswith(":")):
                flush()
                paragraphs.append({
                    "text": text,
                    "page": page,
                    "confidence": sum(block.confidence for block in row) / len(row),
                })
            else:
                buffer.extend(row)
            previous_bottom = bottom
            previous_height = height
        flush()
    return paragraphs


def _is_boilerplate(text):
    normalized = _normalize(text)
    return (
        ("page" in normalized and " of " in f" {normalized} " and len(normalized) < 25)
        or "printed by the manager" in normalized
        or "published by the controller" in normalized
    )


BATCH_RE = re.compile(r"(?:B\.?\s*No\.?|Batch\s*No\.?|Lot\s*No\.?)\s*[:.]?\s*([A-Za-z0-9\-/]+)", re.I)


def _product_type(text):
    normalized = _normalize(text)
    compact = normalized.replace(" ", "")
    if re.search(r"\bvet\b", normalized) or "veterinary" in normalized or "animal use" in normalized:
        return "veterinary"
    for product_type, hints in C.PRODUCT_HINTS.items():
        if product_type == "veterinary":
            continue
        if any(
            _normalize(hint) in normalized
            or _normalize(hint).replace(" ", "") in compact
            for hint in hints
        ):
            return product_type
    return "medicine"


def _same_window(text, patterns, max_chars=200):
    matches = []
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            return False
        matches.append((match.start(), match.end()))
    start = min(start for start, _ in matches)
    end = max(end for _, end in matches)
    return (end - start) <= max_chars


def _field_signals(text, batch_no=None):
    normalized = _normalize(text)
    product_name_re = r"\b(?:product|drug|medicine|brand)\s+name\b|\b(?:tablet|capsule|injection|syrup|solution|ointment|vaccine)\b"
    batch_re = r"\b(?:batch|lot)\s*(?:no|number)?\b\s*[:.]?\s*[A-Za-z0-9\-/]+"
    manufacturer_re = r"\b(?:m s|manufactured by|manufacturer|manufacturing firm)\b"
    failure_re = r"\b(?:reason for failure|failed|failure|nsq|not of standard quality|spurious|falsified|adulterated|misbranded)\b"
    notification_re = r"(?:S\.?\s*O\.?|G\.?\s*S\.?\s*R\.?)\s*(?:No\.?|No\s*[:.]?)?\s*\d+[A-Za-z0-9\-/]*"
    restriction_re = r"(?:shall not be used|only for|restricted to|not to be used|for use only|restricted to use)"
    action_re = r"\b(?:recall(?:\s+of)?|withdrawn|withdrawal|stop(?:\s+sale|\s+distribution)|safety alert)\b"
    product_ref_re = r"\b(?:product|drug|medicine|brand|formulation)\s+(?:name|details|batch)\b|\b(?:tablet|capsule|injection|syrup|ointment|vaccine)\b"
    specific_batch = bool(re.search(batch_re, normalized) or bool(batch_no))
    specific_product = bool(re.search(product_ref_re, normalized))
    action_verb = bool(re.search(action_re, normalized))
    sentence_matches = []
    sentences = re.split(r"(?<=[.!?])\s+|;\s*", normalized)
    for sentence in sentences:
        if re.search(r"\b(?:suspected\s+drug|drug\s+suspected|suspected\s+medicine)\b", sentence) and re.search(r"\b(?:adverse\s+drug\s+reaction|adverse\s+reaction|adverse\s+effect|reaction\s+reported)\b", sentence):
            sentence_matches.append(sentence)
    return {
        "product_name": bool(re.search(r"\b(?:product|drug|medicine|brand)\b(?:\s+name)?", normalized) or re.search(product_name_re, normalized)),
        "batch_no": bool(batch_no or re.search(batch_re, normalized)),
        "manufacturer": bool(re.search(r"\b(?:mfg|manufactured by|manufacturer|manufacturing firm|manufacture by)\b", normalized) or re.search(manufacturer_re, normalized)),
        "failure_reason": bool(re.search(failure_re, normalized)),
        "notification_no": bool(re.search(notification_re, text, re.I)),
        "operative_prohibition": bool(re.search(r"\b(?:prohibited|prohibition|banned|ban on)\b", normalized)),
        "operative_restriction": bool(re.search(restriction_re, normalized)),
        "restriction_condition": bool(re.search(restriction_re, normalized)),
        "operative_condition": bool(re.search(r"\b(?:conditional|conditions|category c|continued manufacturing|subject to)\b", normalized)),
        "falsified_product_evidence": bool(re.search(r"\b(?:falsified|counterfeit|spurious|adulterated|misbranded)\b", normalized)),
        "current_check_match": bool(batch_no and re.search(r"\b(?:nsq|not of standard quality|adverse drug reaction|prohibited|banned)\b", normalized)),
        "suspected_drug": bool(re.search(r"\b(?:suspected drug|drug suspected|suspected medicine)\b", normalized)),
        "adverse_reaction": bool(re.search(r"\b(?:adverse drug reaction|adverse reaction|adverse effect|reaction reported)\b", normalized)),
        "alert_format": bool(sentence_matches or (
            re.search(r"\b(?:suspected\s+drug|drug\s+suspected|suspected\s+medicine)\b", normalized)
            and re.search(r"\b(?:adverse\s+drug\s+reaction|adverse\s+reaction|adverse\s+effect|reaction\s+reported)\b", normalized)
            and re.search(r"\b(?:reported|date|dated|on\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b", normalized)
        )),
        "specific_batch": specific_batch,
        "specific_product": specific_product,
        "action_verb": action_verb,
        "specific_action": bool(
            (specific_batch and action_verb)
            or (specific_product and action_verb)
            or _same_window(normalized, [r"\b(?:product|drug|medicine|brand)\s+name\b|\b(?:tablet|capsule|injection|syrup|solution|ointment|vaccine)\b", r"\b(?:batch|lot)\s*(?:no|number)?\b\s*[:.]?\s*[A-Za-z0-9\-/]+", action_re], 200)
        ),
    }


def map_paragraph(paragraph):
    text = paragraph["text"]
    normalized = _normalize(text)
    product_type = _product_type(text)
    scores = _signature_scores(normalized, C.PARA_SIGNATURES)
    archetype = max(scores, key=scores.get, default=None)
    if not archetype or scores[archetype] == 0:
        archetype = None
    if product_type == "veterinary":
        archetype = "P16"
    elif product_type == "device" and any(token in normalized for token in ("alert", "recall", "safety")):
        archetype = "P9"
    elif archetype == "P1" and "who alert" in normalized and scores.get("P6", 0):
        archetype = "P6"

    batch = BATCH_RE.search(text)
    return {
        "archetype": archetype,
        "product_type": product_type,
        "batch_no": batch.group(1) if batch else None,
        "fields": _field_signals(text, batch.group(1) if batch else None),
        "evidence_quote": text[:500],
    }


def map_table(table, document_context=""):
    header_text = " ".join(table["header"])
    return {
        "archetype": table["archetype"],
        "product_type": _product_type(f"{header_text} {document_context}"),
        "batch_no": None,
        "fields": _field_signals(header_text),
        "evidence_quote": header_text[:500],
    }


def _has_field(field, mapped):
    if field == "batch_no":
        return bool(mapped.get("batch_no"))
    if field == "specific_action":
        fields = mapped.get("fields", {})
        return bool(fields.get("specific_action", False))
    return bool(mapped.get("fields", {}).get(field, False))


def classify(mapped, kind, confidence):
    archetype = mapped["archetype"]
    flags = []
    if archetype is None:
        return "Non-usable", "P3", ["unmapped_taxonomy"]
    class_map = C.TABLE_CLASS if kind == "table" else C.PARA_CLASS
    classification, priority = class_map.get(archetype, ("Non-usable", "P3"))

    required = []
    if kind == "table" and archetype in {"A", "B", "C"}:
        required = ["product_name", "batch_no", "manufacturer", "failure_reason"]
    elif kind == "table" and archetype in {"K", "AR"}:
        required = ["product_name", "notification_no", "operative_prohibition"]
    elif kind == "table" and archetype == "AQ":
        required = ["product_name", "falsified_product_evidence"]
    elif kind == "table" and archetype == "Z":
        required = ["suspected_drug", "adverse_reaction", "alert_format"]
    elif kind != "table":
        required = C.REQUIRED_FIELDS.get(archetype, [])

    if archetype in {"P1", "P2"}:
        fields = mapped.get("fields", {})
        has_windowed_failure = bool(
            fields.get("product_name")
            and fields.get("batch_no")
            and fields.get("manufacturer")
            and fields.get("failure_reason")
            and _same_window(
                _normalize(mapped.get("evidence_quote", "")),
                [
                    r"\b(?:product|drug|medicine|brand)\s+name\b|\b(?:tablet|capsule|injection|syrup|solution|ointment|vaccine)\b",
                    r"\b(?:batch|lot)\s*(?:no|number)?\b\s*[:.]?\s*[A-Za-z0-9\-/]+",
                    r"\b(?:m s|manufactured by|manufacturer|manufacturing firm)\b",
                    r"\b(?:reason for failure|failed|failure|nsq|not of standard quality|spurious|falsified|adulterated|misbranded)\b",
                ],
                200,
            )
        )
        if not has_windowed_failure:
            classification, priority = "Future-usable", "P2"
            flags.append("missing:product_name,batch_no,manufacturer,failure_reason_window")
    elif archetype in {"P5", "P6"}:
        specific_batch = bool(mapped.get("fields", {}).get("specific_batch", False))
        specific_product = bool(mapped.get("fields", {}).get("specific_product", False))
        action_verb = bool(mapped.get("fields", {}).get("action_verb", False))
        if not ((specific_batch or specific_product) and action_verb):
            classification, priority = "Future-usable", "P2"
            flags.append("missing:specific_action")
    else:
        missing = [field for field in required if not _has_field(field, mapped)]
        if missing:
            classification, priority = "Future-usable", "P2"
            flags.append("missing:" + ",".join(missing))

    if mapped["product_type"] in {"veterinary", "device", "cosmetic"} and classification == "Usable":
        classification, priority = "Future-usable", "P2"
        flags.append(f"out_of_medicine_scope:{mapped['product_type']}")
    if confidence < C.LOW_CONF:
        flags.append("low_ocr_confidence")
        if classification == "Usable":
            classification, priority = "Future-usable", "P2"
            flags.append("deferred_pending_ocr_review")
    if classification == "Usable":
        flags.append("evidence_review_required")
    return classification, priority, flags


def _document_identity(doc):
    source = str(doc.get("source_name") or "").strip()
    doc_id = str(doc.get("doc_id") or "")
    file_name = Path(doc_id.replace("\\", "/")).name or str(doc.get("file_name") or "")
    return source, file_name


def _make_part(doc, page, pages, kind, mapped, classification, priority, flags, confidence):
    source, file_name = _document_identity(doc)
    return {
        "doc_id": doc.get("doc_id", ""),
        "source_name": source,
        "file_name": file_name,
        "page": page,
        "pages": ",".join(str(number) for number in pages),
        "part_type": kind,
        "archetype": mapped["archetype"] or "",
        "product_type": mapped["product_type"],
        "batch_no": mapped.get("batch_no") or "",
        "app_classification": classification,
        "priority": priority,
        "confidence": round(confidence, 4),
        "evidence_quote": mapped["evidence_quote"],
        "review_flags": ";".join(flags),
    }


def process_doc(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    blocks = list(load_blocks(doc))
    document_context = " ".join(block.text for block in blocks)
    tables, consumed_ids = reconstruct_tables(blocks)
    paragraphs = extract_paragraphs(blocks, consumed_ids)
    parts = []

    for table in tables:
        mapped = map_table(table, document_context)
        classification, priority, flags = classify(mapped, "table", table["confidence"])
        parts.append(_make_part(
            doc, table["page"], table["pages"], "table", mapped,
            classification, priority, flags, table["confidence"],
        ))
    for paragraph in paragraphs:
        mapped = map_paragraph(paragraph)
        classification, priority, flags = classify(mapped, "paragraph", paragraph["confidence"])
        if mapped["archetype"] is None and len(paragraph["text"]) >= 40:
            continue
        parts.append(_make_part(
            doc, paragraph["page"], [paragraph["page"]], "paragraph", mapped,
            classification, priority, flags, paragraph["confidence"],
        ))
    return doc, parts


def rollup(parts):
    counts = {
        value: sum(part["app_classification"] == value for part in parts)
        for value in ("Usable", "Future-usable", "Non-usable")
    }
    label = "Usable" if counts["Usable"] else (
        "Future-usable" if counts["Future-usable"] else "Non-usable"
    )
    paragraph_ids = sorted({
        part["archetype"] for part in parts
        if part["part_type"] == "paragraph" and part["archetype"]
    })
    table_ids = sorted({
        part["archetype"] for part in parts
        if part["part_type"] == "table" and part["archetype"]
    })
    usable_priorities = [
        part["priority"] for part in parts
        if part["app_classification"] == "Usable" and part["priority"]
    ]
    app_priority = min(usable_priorities, key=lambda value: int(value[1:])) if usable_priorities else ""
    review_status = "Needs review" if any(part["review_flags"] for part in parts) else "Auto-classified"
    has_table = any(part["part_type"] == "table" for part in parts)
    has_paragraph = any(part["part_type"] == "paragraph" for part in parts)
    structure = "mixed" if has_table and has_paragraph else (
        "table" if has_table else "paragraph" if has_paragraph else "no_content"
    )
    return {
        "paragraph_taxonomy_ids": ";".join(paragraph_ids),
        "table_taxonomy_ids": ";".join(table_ids),
        "usable_count": counts["Usable"],
        "future_count": counts["Future-usable"],
        "non_usable_count": counts["Non-usable"],
        "rollup_label": label,
        "review_status": review_status,
        "structure": structure,
        "app_priority": app_priority,
    }


PART_COLUMNS = [
    "doc_id", "source_name", "file_name", "page", "pages", "part_type",
    "archetype", "product_type", "batch_no", "app_classification", "priority",
    "confidence", "evidence_quote", "review_flags",
]
DOC_COLUMNS = [
    "doc_id", "source_name", "file_name", *C.ROLLUP_COLUMNS,
    "structure", "app_priority",
]


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _csv_key(source, file_name):
    normalized_name = Path(str(file_name).replace("\\", "/")).name
    return _normalize(source), _normalize(normalized_name)


def merge_existing(path, doc_rows, dry_run, audit):
    if not path.exists():
        audit.append({"doc_id": str(path), "kind": "missing_csv", "detail": "source classification CSV not found"})
        return

    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        existing = list(reader)
    source_column = next((name for name in columns if name.strip().casefold() == "source"), None)
    name_column = next((name for name in columns if name.strip().casefold() in {"file name", "filename"}), None)
    if not source_column or not name_column:
        audit.append({"doc_id": str(path), "kind": "csv_schema_error", "detail": "required Source and File Name columns were not found"})
        return

    doc_index = {
        _csv_key(row["source_name"], row["file_name"]): row
        for row in doc_rows
    }
    csv_keys = {
        _csv_key(row.get(source_column, ""), row.get(name_column, ""))
        for row in existing
    }
    for column in [*C.ROLLUP_COLUMNS, "Structure", "app_priority"]:
        if column not in columns:
            columns.append(column)

    matched = 0
    for row in existing:
        key = _csv_key(row.get(source_column, ""), row.get(name_column, ""))
        result = doc_index.get(key)
        if result is None:
            audit.append({
                "doc_id": f"{row.get(source_column, '')}/{row.get(name_column, '')}",
                "kind": "unmatched_csv",
                "detail": "CSV row has no matching scanned JSON",
            })
            continue
        matched += 1
        for column in C.ROLLUP_COLUMNS:
            row[column] = result[column]
        row["Structure"] = result["structure"]
        if "app_classification" in columns:
            row["app_classification"] = result["rollup_label"]
        if "app_priority" in columns:
            row["app_priority"] = result["app_priority"]
        if "app_classification_reason" in columns:
            row["app_classification_reason"] = (
                f"Paragraph IDs: {result['paragraph_taxonomy_ids'] or 'none'}; "
                f"table IDs: {result['table_taxonomy_ids'] or 'none'}; "
                f"records (usable/future/non-usable): {result['usable_count']}/"
                f"{result['future_count']}/{result['non_usable_count']}; {result['review_status']}"
            )

    for row in doc_rows:
        if _csv_key(row["source_name"], row["file_name"]) not in csv_keys:
            audit.append({
                "doc_id": row["doc_id"],
                "kind": "unmatched_json",
                "detail": "no CSV row with matching Source and File Name",
            })

    if dry_run:
        print(f"[dry-run] would update {matched} of {len(existing)} CSV rows in {path}")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy(path, path.with_name(f"{path.stem}.backup_{stamp}{path.suffix}"))
    temp_path = path.with_name(f"{path.stem}.tmp{path.suffix}")
    with open(temp_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing)
    temp_path.replace(path)


def write_audit(rows):
    C.OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with open(C.OUT_AUDIT, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["doc_id", "kind", "detail"])
        writer.writeheader()
        writer.writerows(rows)


def run(dry_run=False):
    paths = sorted(C.SCANNED_JSON_DIR.rglob("*.json"))
    if not paths:
        raise FileNotFoundError(f"No scanned JSON files found under {C.SCANNED_JSON_DIR}")

    parts_all = []
    docs = []
    audit = []
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        try:
            doc, parts = process_doc(path)
        except Exception as error:
            audit.append({"doc_id": str(path), "kind": "parse_error", "detail": str(error)})
            print(f"[{index}/{total}] ERROR {path.name}: {error}")
            continue

        source, file_name = _document_identity(doc)
        blocks = list(load_blocks(doc))
        if not blocks:
            audit.append({
                "doc_id": doc.get("doc_id", str(path)),
                "kind": "no_ocr_pages",
                "detail": "no OCR blocks available; text pages skipped",
            })
        for page in doc.get("pages", []):
            if str(page.get("type", "")).casefold() == "text":
                continue
            page_blocks = [block for block in blocks if block.page == int(page.get("page", -1))]
            low_count = sum(block.confidence < C.LOW_CONF for block in page_blocks)
            if low_count:
                audit.append({
                    "doc_id": doc.get("doc_id", str(path)),
                    "kind": "low_confidence_page",
                    "detail": f"page {page.get('page')}: {low_count}/{len(page_blocks)} OCR blocks below {C.LOW_CONF}",
                })

        parts_all.extend(parts)
        rollup_summary = rollup(parts)
        docs.append({
            "doc_id": doc.get("doc_id", str(path)),
            "source_name": source,
            "file_name": file_name,
            **rollup_summary,
        })
        print(f"[{index}/{total}] {path.name} -> {rollup_summary['rollup_label']} | parts={len(parts)} | structure={rollup_summary['structure']}")

    write_csv(C.OUT_PARTS, parts_all, PART_COLUMNS)
    write_csv(C.OUT_DOCS, docs, DOC_COLUMNS)
    merge_existing(C.EXISTING_CSV, docs, dry_run, audit)
    write_audit(audit)
    print(f"{'[dry-run] ' if dry_run else ''}done docs={len(docs)} parts={len(parts_all)} audit={len(audit)}")