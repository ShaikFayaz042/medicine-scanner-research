"""Records from documents without tables: gazette prohibitions, recall / falsified / theft alerts, and
circulars that only reference notifications."""

from __future__ import annotations

import re
from typing import Any

from data_processing_service.parser.tables import (
    BATCH_COLUMN,
    EXPIRY_COLUMN,
    MANUFACTURER_COLUMN,
    PRODUCT_COLUMN,
    SERIAL_COLUMN,
    clean_text,
)

NOTIFICATION_COLUMN = "Notification No. & Date"
NOTIFICATION_NUMBER = re.compile(r"\b(S\.\s*O\.|G\.\s*S\.\s*R\.)\s*(\d+)\s*\(\s*E\s*\)", re.I)
NOTIFICATION_RANGE = re.compile(
    r"\b(?:S\.\s*O\.|G\.\s*S\.\s*R\.)\s*\d+\s*\(\s*E\s*\)(?:\s*to\s*(?:S\.\s*O\.|G\.\s*S\.\s*R\.)\s*\d+\s*\(\s*E\s*\))?", re.I
)
LIST_INTRO = re.compile(r"(?:following|as listed below|namely|as under|listed hereunder)[^\n]{0,200}?:\s*-?\s*$", re.I | re.M)
LIST_GROUP = re.compile(r"^\s*(\d{1,3})\s*[.)]\s+(.+?)\s*$")
LIST_ITEM = re.compile(r"^\s*\(?\s*([ivxlc]{1,7}|[a-h])\s*[.)]\s*(.+?)\s*$", re.I)
LIST_END = re.compile(r"^\s*\[?\s*F\.\s*No\.|^\s*(?:Uploaded by|Digitally signed)", re.I)
# "fixed dose combination of A + B", also "Fixed Dose Combination (hereinafter ... FDC) of A + B".
FDC_PHRASE = re.compile(
    r"(?:fixed\s+dose\s+combinations?|FDCs?)(?:\s*\([^)]{0,80}\))?\s+of\s+(.+?\+.+?)"
    r"(?=\s+(?:vide|is|are|for|in|was|cannot|has|which|appeared)\b|\s+with\s+immediate\s+effect"
    r"|[;,.](?:\s|$)|$)",
    re.I | re.S,
)
# "all formulations of fixed dose combinations containing A and B"
FDC_CONTAINING = re.compile(
    r"fixed\s+dose\s+combinations?\s+containing\s+(.+?)(?=\s+(?:in\s+addition|for|vide|is|are)\b|[;,.](?:\s|$)|$)",
    re.I | re.S,
)
# "drug Combikit of Azithromycin, Secnidazole and Fluconazole vide ..."
COMBIKIT = re.compile(r"\bcombi-?kits?\s+of\s+(.+?)(?=\s+vide\b|[;.](?:\s|$)|$)", re.I | re.S)
# Each notification in a gazette starts on its own line: "S.O. 3286(E).—Whereas ..."
# The number may wrap onto the next line ("S.O.449" / "2 (E).").
NOTIFICATION_HEADING = re.compile(r"(?m)^\s*(S\.\s*O\.|G\.\s*S\.\s*R\.)\s*(\d+(?:\s{1,3}\d+)?)\s*\(\s*E\s*\)\s*\.?\s*[—–-]")
# A list written inline after "namely:-": "(i) Ketoprofen and its formulations ... (ii) Aceclofenac ..."
INLINE_LIST = re.compile(r"\bnamely\s*:?\s*[-–—]?\s*[“\"]?(.+?)(?=\[\s*F\.\s*No|$)", re.I | re.S)
INLINE_ITEM = re.compile(r"\(\s*([ivxlc]{1,6}|[a-h])\s*\)\s*(.+?)(?=\(\s*(?:[ivxlc]{1,6}|[a-h])\s*\)|$)", re.I | re.S)
# Ways an alert's subject names its product (tried in order on the body text, then on the title):
#   "Recall of X manufactured by M/s Y", "falsified versions of X manufactured by M/s Y"
#   "theft of X ..., Batch No. 5F0347B of M/s Y", "falsified X ..., B. No. 20G20A"
#   "NSQ X Batch No. TC010915 ...", "recall letter for Product X manufactured in ..."
SUBJECT_PATTERNS = (
    re.compile(r"(?:recall|versions?|theft|counterfeit)\s+of\s+(.+?)\s+(?:manufactured|imported|marketed|mfg\.?|mfd\.?)\s+by\s+M/s", re.I),
    re.compile(r"(?:theft|falsified|counterfeit|spurious)\s+(?:versions?\s+of\s+|of\s+)?(.+?)(?=\s*,?\s*(?:batch\b|b\.\s*no\b)|\s+of\s+M/s|\s+during\b|$)", re.I),
    re.compile(r"\bNSQ\s+(?:of\s+)?(.+?)\s+batch\b", re.I),
    re.compile(r"\bmedical\s+devices?\s+alert\s+(?:for|on)\s+[\"\u201c]?\s*(.+?)(?=\s+of\s+(?:India\s+)?[A-Z][\w.]*\s+(?:Ltd|Limited|Inc|Pvt)\b|$)", re.I),
    re.compile(r"\brecall\s+(?:letter\s+)?(?:of|for)\s+(?:the\s+)?(?:product\s+)?(.+?)(?=\s+(?:manufactured|imported|marketed|mfd)\b|\s*\(?grade\b|$)", re.I),
)
# CDSCO device alerts name the device under a shaded "DEVICE" heading, before "BACKGROUND".
DEVICE_SECTION = re.compile(
    r"^\s*DEVICES?\s*$(.+?)^\s*(?:BACKGROUND|REASON\b|PROBLEM|ISSUE|DESCRIPTION)", re.I | re.M | re.S
)
SUBJECT_MANUFACTURER = re.compile(
    r"(?:manufactured\s+by|mfd\.?\s+by|mfg\.?\s+by|\bof)\s+(M/s\.?\s*[A-Z][^,\n]*?)(?=\s+during\b|\s+dated\b|\s*,|\s*-\s*reg|\s+has\b|\.\s|$)"
)
BATCH_INTRO = re.compile(r"\b(?:batch\s*(?:no|nos|numbers?)?|b\.\s*no)\s*[.:\-]?\s*", re.I)
CODE = re.compile(r"^(?=[A-Z0-9/\-]*\d)[A-Z0-9][A-Z0-9/\-]{3,}$")
EXPIRY_TOKEN = re.compile(r"^(\d{2}/\d{4})[,.;]?$")
REASON_BY_KEYWORD = (
    ("falsified", "Falsified product"),
    ("spurious", "Spurious product"),
    ("counterfeit", "Counterfeit product"),
    ("theft", "Theft during transit"),
    ("recall", "Recall"),
    ("not of standard quality", "Not of standard quality"),
    ("nsq", "Not of standard quality"),
)


def notification_numbers(text: str) -> list[str]:
    numbers = []
    for match in NOTIFICATION_NUMBER.finditer(text):
        prefix = re.sub(r"\s+", "", match.group(1)).upper()
        numbers.append(f"{prefix} {match.group(2)}(E)")
    return list(dict.fromkeys(numbers))


def _list_items(text: str) -> list[tuple[str, str, str]]:
    """Items of the last introduced list: (serial, item, group). The last list is the English one in
    bilingual gazettes."""
    intros = list(LIST_INTRO.finditer(text))
    if not intros:
        return []
    items: list[tuple[str, str, str]] = []
    group_serial, group_name, group_has_items = "", "", False
    for line in text[intros[-1].end():].splitlines():
        if LIST_END.search(line):
            break
        if match := LIST_GROUP.match(line):
            if group_name and not group_has_items:
                items.append((group_serial, group_name, ""))
            group_serial, group_name, group_has_items = match.group(1), clean_text(match.group(2)), False
        elif (match := LIST_ITEM.match(line)) and group_name:
            items.append((f"{group_serial}.{match.group(1).lower()}", clean_text(match.group(2)), group_name))
            group_has_items = True
    if group_name and not group_has_items:
        items.append((group_serial, group_name, ""))
    return items


def _inline_items(text: str) -> list[tuple[str, str, str]]:
    match = INLINE_LIST.search(text)
    if not match:
        return []
    return [
        (item.group(1).lower(), clean_text(item.group(2)).rstrip("”\". "), "")
        for item in INLINE_ITEM.finditer(match.group(1))
    ]


def _notification_items(text: str) -> list[tuple[str, str, str]]:
    """Prohibited items of one notification: (serial, item, group)."""
    items = _list_items(text) or _inline_items(text)
    if items:
        return items
    for pattern in (FDC_PHRASE, FDC_CONTAINING, COMBIKIT):
        if match := pattern.search(text):
            return [("1", clean_text(match.group(1)), "")]
    return []


def _heading_number(heading: re.Match[str]) -> str:
    prefix = re.sub(r"\s+", "", heading.group(1)).upper()
    return f"{prefix} {re.sub(r'[^0-9]', '', heading.group(2))}(E)"


def parse_notification(text: str) -> list[dict[str, Any]]:
    """Prohibited items of a gazette: each notification's listed items, else its named fixed-dose combination.

    A gazette can hold many notifications (S.O. 3285(E) to S.O. 3440(E) bans one FDC each); every one
    becomes its own record.
    """
    headings = list(NOTIFICATION_HEADING.finditer(text))
    if len(headings) >= 2:
        segments = [
            (_heading_number(heading),
             text[heading.start(): headings[index + 1].start() if index + 1 < len(headings) else len(text)])
            for index, heading in enumerate(headings)
        ]
    else:
        numbers = notification_numbers(text)
        segments = [(numbers[0] if numbers else "", text)]

    records = []
    for position, (notification, segment) in enumerate(segments, start=1):
        for serial, item, group in _notification_items(segment):
            record = {
                SERIAL_COLUMN: f"{position}.{serial}" if len(segments) > 1 and serial != "1" else (str(position) if len(segments) > 1 else serial),
                PRODUCT_COLUMN: item,
                NOTIFICATION_COLUMN: notification,
            }
            if group:
                record["Category"] = group
            records.append(record)
    return records


def _batches_after(text: str) -> list[tuple[str, str]]:
    """Batch codes (and expiry when given as "ED: 04/2024") listed after each "batch no." mention."""
    found: dict[str, str] = {}
    for intro in BATCH_INTRO.finditer(text):
        tokens = re.split(r"[\s,]+", text[intro.end():intro.end() + 400])
        index = 0
        while index < len(tokens):
            token = tokens[index].strip(".;:")
            if not token or token.lower() in {"and", "&", "no", "no."}:
                index += 1
                continue
            if CODE.match(token) and not EXPIRY_TOKEN.match(token):
                expiry = ""
                if index + 2 < len(tokens) and tokens[index + 1].upper().startswith("ED"):
                    if date := EXPIRY_TOKEN.match(tokens[index + 2]):
                        expiry = date.group(1)
                        index += 2
                found.setdefault(token, expiry)
                index += 1
                continue
            break
    return list(found.items())


LOT_CODE = re.compile(r"^(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{4,19}$")


def _batches_in_column(text: str) -> list[tuple[str, str]]:
    """Batch codes listed under a "Batch No." column header of a table flattened into text.

    Takes letter+digit codes (T5A010AA) from the rows after the header; product codes (1504384),
    quantities and words are skipped. Stops at the first prose line (six or more words, no code).
    """
    lines = text.splitlines()
    for start, line in enumerate(lines):
        if not re.search(r"\bbatch\s*no\b", line, re.I):
            continue
        found = []
        for row in lines[start + 1:start + 40]:
            codes = [token for token in re.split(r"[\s,;]+", row.strip(".;: ")) if LOT_CODE.match(token)]
            if not codes and len(row.split()) >= 6:
                break
            found.extend(codes)
        if found:
            return [(code, "") for code in dict.fromkeys(found)]
    return []


SUBJECT_LINE = re.compile(r"\bSub(?:ject)?\s*(?:[:.]\s*-?|-\s*:)\s*(.+?)(?:-\s*reg\b|\n\s*\n|$)", re.I | re.S)


def _clean_product(value: str) -> str:
    product = clean_text(value).strip(" ,;:-\"\u201c\u201d")
    if product.count("(") > product.count(")"):
        product += ")"
    return product


def subject_product(text: str, title: str) -> tuple[str, str] | None:
    """(product, manufacturer) named in an alert's subject: the "Subject:" line, else the title, else the
    opening text. Vague subjects ("theft of its products") are skipped."""
    device = DEVICE_SECTION.search(text)
    if device and 3 <= len(_clean_product(device.group(1))) <= 300:
        return _clean_product(device.group(1)), ""
    subject_line = SUBJECT_LINE.search(text)
    candidates = [subject_line.group(1)] if subject_line else []
    candidates += [title, text[:1500]]
    for candidate in candidates:
        flat = re.sub(r"\s+", " ", candidate or "")
        for pattern in SUBJECT_PATTERNS:
            match = pattern.search(flat)
            if not match:
                continue
            product = _clean_product(match.group(1))
            if not 3 <= len(product) <= 160 or re.match(r"(?:its|their|the|multiple|following)\b", product, re.I):
                continue
            manufacturer = SUBJECT_MANUFACTURER.search(flat[match.start():])
            return product, clean_text(manufacturer.group(1)).rstrip(" .-") if manufacturer else ""
    return None


def _alert_reason(title: str, text: str) -> str:
    """The title's keyword when it names one, else the keyword mentioned first in the text (a recall
    notice may mention counterfeits further down; its own reason comes first)."""
    lowered_title = title.lower()
    for keyword, label in REASON_BY_KEYWORD:
        if keyword in lowered_title:
            return label
    lowered = text.lower()
    positions = [(lowered.find(keyword), label) for keyword, label in REASON_BY_KEYWORD if keyword in lowered]
    return min(positions)[1] if positions else ""


def parse_alert(text: str, title: str) -> list[dict[str, Any]]:
    """One record per batch for recall / falsified / theft / NSQ alerts written as prose."""
    subject = subject_product(text, title)
    if not subject:
        return []
    product, manufacturer = subject
    reason = _alert_reason(title, text)
    # The title often lists the batches too ("... Batch No.TC010915 and Batch No. TC010417 ...").
    batches = _batches_after(f"{title}\n{text}") or _batches_in_column(text) or [("", "")]
    records = []
    for index, (batch, expiry) in enumerate(batches, start=1):
        record = {SERIAL_COLUMN: str(index), PRODUCT_COLUMN: product}
        if manufacturer:
            record[MANUFACTURER_COLUMN] = manufacturer
        if batch:
            record[BATCH_COLUMN] = batch
        if expiry:
            record[EXPIRY_COLUMN] = expiry
        if reason:
            record["Reason for failure"] = reason
        records.append(record)
    return records


GAZETTE_BY_DATE = re.compile(
    r"\bgazette\s+notifications?\s+(?:published\s+)?(?:on|dated)\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I
)


def parse_notice(text: str, title: str) -> list[dict[str, Any]]:
    """Document-level record for circulars that only point at notifications (no products listed)."""
    references = list(dict.fromkeys(re.sub(r"\s+", " ", match.group(0)) for match in NOTIFICATION_RANGE.finditer(text)))
    references.extend(
        f"Gazette notifications dated {match.group(1)}" for match in GAZETTE_BY_DATE.finditer(text)
    )
    if not references:
        return []
    subject = re.search(r"Subject\s*:?-?\s*(.+?)(?:-\s*reg|\n\s*\n|$)", text, re.I | re.S)
    return [{
        SERIAL_COLUMN: "1",
        "Subject": clean_text(subject.group(1)) if subject else clean_text(title),
        NOTIFICATION_COLUMN: "; ".join(references),
    }]
