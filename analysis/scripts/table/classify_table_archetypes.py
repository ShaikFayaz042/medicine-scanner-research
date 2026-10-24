"""Assign table archetypes to table-structured PDFs — fully self-contained.

V3 upgrades (based on schema analysis):
  1) text strategy dropped — only `lines` (kills Hindi OCR garbage at source)
  2) used_headers set — same header can't match 2 required groups (fixes U bug)
  3) Table-level gate — rejects high-junk, non-ASCII, fragment tables
  4) Header detection — ASCII + avg-len + keyword scoring (kills row-as-header)
  5) Text fallback — ASCII gate + threshold 0.7 + min token 6
  6) pdfplumber fallback — ASCII + junk gated
  7) AR/A force override retained
  8) header_row + first_row retained
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    import pymupdf
except ImportError:
    pymupdf = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


SCRIPT_DIR = Path(__file__).resolve().parent
INGESTION_DIR = SCRIPT_DIR.parent
DEFAULT_CSV = SCRIPT_DIR / "full_corpus_classified.csv"
DEFAULT_DOWNLOADS_ROOT = SCRIPT_DIR
DEFAULT_OUTPUT = SCRIPT_DIR / "table_types_assigned.csv"

STRONG_CONTEXT_TYPES = {"AR", "AC", "AU", "AT", "AV", "C", "A", "K"}
FORCE_CONTEXT_TYPES = {"AR", "A"}

NON_WORDS = re.compile(r"[^a-z0-9]+")
WHITESPACE = re.compile(r"\s+")
SERIAL_VALUE = re.compile(r"\d+\s*[.)]?")
NUMBER_ONLY = re.compile(r"[\d.\-/]+")

ROW_SEP = " | "

# Keywords commonly present in real English table headers
HEADER_KEYWORDS = {
    "no", "name", "batch", "date", "mfg", "exp", "reason", "drawn",
    "from", "nsq", "result", "reported", "device", "intended", "use",
    "risk", "class", "file", "company", "product", "regulatory",
    "status", "subject", "content", "page", "lot", "strength",
    "notification", "manufacturer", "remarks", "reply", "category",
    "testing", "facility", "vaccine", "strain", "indication",
    "month", "day", "study", "duration",
}


# ============================================================
# ARCHETYPE DEFINITIONS (unchanged from V2)
# ============================================================
ARCHETYPE_DEFS: dict[str, dict[str, Any]] = {
    "A": {
        "name": "CDSCO Monthly Drug Alert / NSQ List",
        "priority": "P0",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "s.n o", "sr. no", "sl. no", "s. no"),
            ("name of drugs", "name of drug", "product name", "product/drug name", "name of the drug",
             "drug name", "drugs name", "name of the drugs", "name of drugs/medical device/cosmetics",
             "name of the drug/ medical device/ cosmetic"),
            ("batch no", "batch no.", "batch number", "b.no", "b. no", "b.no.",
             "b.no, d/m, d/e", "batch no./date of manufacture/date of expiry/manufactured by"),
            ("reason for failure", "reasons for failure", "reason of failure",
             "reason for failure with", "reason for failure/report no",
             "reason for failure with report", "reasons for failure with"),
        ],
        "optional": [
            ("date of manufacture", "manufacturing date", "mfg date", "mfg dt",
             "date of manufa cture", "date of manufactur e", "date of manufactu re",
             "date of manuf acture", "date of manufa - cture"),
            ("date of expiry", "expiry date", "exp date", "exp dt"),
            ("manufactured by", "mfg by", "mfd by", "manufacturer", "manufactured by as per label"),
            ("drawn by", "drawn by (from state/cdsco zone)", "drawn by (from state/cds co zone)"),
            ("from", "from (name of laboratory)", "from name of laboratory",
             "from (name of the laboratory)"),
            ("remarks",), ("sample received from",), ("declared by",),
            ("firm reply", "firm's reply", "firms reply"),
        ],
    },
    "B": {
        "name": "State NSQ Alert",
        "priority": "P0",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "s. n."),
            ("product/drug name", "product name", "drug name", "name of drugs", "name of drug",
             "vaccine name", "product/dru g name", "product/dr ug name"),
            ("batch no", "batch no.", "batch number", "b.no"),
            ("nsq result", "nsq results"),
            ("reported by state laboratory", "reported by cdsco laboratory",
             "reported by cdsco / state lab", "reported by",
             "reported by state laboratory.", "reported by cdsco lab"),
        ],
        "optional": [
            ("manufacturing date", "date of manufacture", "mfg date", "mfg dt",
             "manufact uring date", "manufactu ring date"),
            ("expiry date", "date of expiry", "exp date"),
            ("manufactured by", "mfg by", "mfd by", "manufacturer"),
        ],
    },
    "C": {
        "name": "Spurious Drug List",
        "priority": "P0",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "s. no.", "s. no"),
            ("name of drugs", "name of drug", "product name", "drug name", "name of the drug",
             "product/drug name", "name of drugs/medical device/cosmetics"),
            ("batch no", "batch no.", "batch number", "b.no", "b. no."),
            ("firm's reply", "firm reply", "firms reply", "firms's reply", "firms’s reply",
             "firm’s reply", "firm's reply.", "firm`s reply"),
        ],
        "optional": [
            ("reason for failure", "reasons for failure", "reason of failure"),
            ("drawn by", "drawn by (from state/cdsco zone)"),
            ("from", "from (name of laboratory)", "from name of laboratory"),
            ("remarks",),
            ("date of manufacture", "manufacturing date", "mfg date"),
            ("date of expiry", "expiry date", "exp date"),
            ("manufactured by", "mfg by", "manufacturer"),
        ],
    },
    "D": {
        "name": "Medical Device Risk Classification",
        "priority": "P2",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "s. no.", "s. no"),
            ("device name", "medical device name", "name of the medical device",
             "name of the medical devices", "name of product", "notified category",
             "medical device name ", "device name "),
            ("intended use", "inteded use", "intended uses", "intended use "),
        ],
        "optional": [
            ("risk class", "risk classification", "risk", "classification india as per first schedule"),
            ("notified category",), ("general intended use",),
        ],
    },
    "E": {
        "name": "NOC / Clarification Register",
        "priority": "P1",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "s. no", "s. no."),
            ("file no", "file . no", "file nos", "file no."),
            ("name of the company", "name of company", "company address",
             "name of the company and address"),
            ("product name",),
            ("regulatory status",),
        ],
        "optional": [("intended use",), ("date of issue",)],
    },
    "F": {
        "name": "Laboratory / Testing Facility List",
        "priority": "P2",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "s. no", "s. no."),
            ("category of in vitro diagnostics", "category",
             "category of in vitro diagnostics medical devices"),
            ("name of testing facility", "name of testing facility ", "name of laboratory"),
        ],
        "optional": [],
    },
    "G": {
        "name": "Gazette Fee Schedule",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no"),
            ("subject", "particulars"),
            ("rupees", "fee", "in rupees", "in rupees (inr) except where specified in dollars ($)"),
        ],
        "optional": [("rule", "section"), ("type of test", "name of test", "test/analysis")],
    },
    "H": {
        "name": "Contents / Index",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "s. no", "s. no."),
            ("content", "contents", "contents/particulars", "title", "topic", "topics",
             "subject", "chapter", "preface"),
            ("page no", "page number", "page", "page no.", "page no"),
        ],
        "optional": [],
    },
    "I": {
        "name": "Checklist / Form table",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "sl. no."),
            ("documents", "item", "particulars", "content", "contents/particulars", "details"),
            ("yes",),
            ("no",),
        ],
        "optional": [("na",), ("remark", "remarks")],
    },
    "J": {
        "name": "Veterinary Vaccine List",
        "priority": "P2",
        "required": [
            ("s no", "sr no", "sl no", "serial no"),
            ("name of vaccine", "name of the vaccine", "name of veterinary vaccine",
             "name of veterinary vaccine, inactivated i.p", "vaccine name"),
            ("strain", "name of the strain", "strain name"),
        ],
        "optional": [
            ("permission no", "permission number"),
            ("indication", "indication(s)", "indications"),
            ("dosage form", "dosage form & presentation"),
            ("source of the strain", "source of strain"),
            ("manufacturer", "name of the manufacturer",
             "name of the importer/manufacturer with address",
             "name of the importer/ manufacturer with address"),
        ],
    },
    "K": {
        "name": "FDC Prohibition / Rationalisation List",
        "priority": "P0",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "sr.no",
             "s. no", "s. no."),
            ("name of fdc", "drugs name", "drug name", "name of the fdc"),
            ("notification no", "notification no. & date", "notification"),
        ],
        "optional": [
            ("strength", "strength of fdc"), ("dosage form",), ("date of noc",),
            ("date of central government approval",),
            ("final recommedation", "final recommendation"),
        ],
    },
    "L": {
        "name": "Abbreviations / Glossary",
        "priority": "P3",
        "required": [
            ("abbreviation", "abbr", "abbreviation(s)"),
            ("full form", "expansion", "description", "meaning", "definition"),
        ],
        "optional": [],
    },
    "M": {
        "name": "COVID / PCR Kit Approval",
        "priority": "P2",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s. no.", "s. no"),
            ("name of the firm", "name of firm", "company name", "manufacturer name"),
            ("type of kit", "kit type"),
            ("country", "country of origin"),
        ],
        "optional": [],
    },
    "N": {
        "name": "Committee Meeting Schedule",
        "priority": "P3",
        "required": [("month",), ("tentative dates", "tentative dates of sec", "date"), ("day",)],
        "optional": [],
    },
    "O": {
        "name": "BABE Study Centre Approval",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s.no.", "s.no"),
            ("address of bio analytical centre", "address of bioanalytical laboratory",
             "address of bio analytical centre"),
            ("valid upto", "valid up to", "valid upto."),
        ],
        "optional": [
            ("file no", "file nos", "registration no", "file no."),
            ("address of clinical centre", "name & address of the firm clinical facility"),
            ("date of issue",),
        ],
    },
    "P": {
        "name": "Government Analyst / Committee Member notification",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "sl.no", "serial number",
             "sl. no", "sl. no."),
            ("name of government analyst", "name of the government analyst",
             "name, designation of the government analyst",
             "name and designation of the government analyst",
             "name of the government analyst ", "name"),
        ],
        "optional": [
            ("name of laboratory", "laboratory"),
            ("class of drugs", "classes of drugs"),
            ("medical device", "medical device(s)", "category of medical device"),
        ],
    },
    "Q": {
        "name": "Stability Study Design tables",
        "priority": "P3",
        "required": [
            ("study", "study type"),
            ("study conditions", "study condition", "storage conditions"),
            ("duration of study", "duration", "shelf life"),
        ],
        "optional": [],
    },
    "R": {
        "name": "SAE / PSUR Reporting summary",
        "priority": "P2",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n"),
            ("serious adverse event", "serious adverse events", "sae"),
            ("number of the sae reported", "number of sae"),
            ("total units sold", "total units"),
            ("lot/batch no", "lot/batch no.", "lot /batch no", "lot/batch number"),
        ],
        "optional": [("duration",), ("from",), ("to",)],
    },
    "S": {
        "name": "Cleanroom / ISO Class Requirements",
        "priority": "P3",
        "required": [
            ("name of device", "device name"),
            ("type of operation",),
            ("iso class", "iso class (at rest)", "iso"),
        ],
        "optional": [],
    },
    "T": {
        "name": "Exemption / Condition-Criteria tables",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n"),
            ("class of medical devices", "class of drugs", "class"),
            ("extent and conditions", "extent and conditions of exemptions", "conditions"),
        ],
        "optional": [],
    },
    "U": {
        "name": "BIS / IS Standard Reference",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "sl. no"),
            ("is no", "is no.", "standard number", "is number",
             "no. year and title", "no. , year and title"),
        ],
        "optional": [
            ("title", "title of the indian standards", "standard title"),
            ("no. and year of the amendment",),
            ("date of establishment of the amendment",),
            ("date till which the standard",),
        ],
    },
    "V": {
        "name": "Treasury Challan / Payment Form",
        "priority": "P3",
        "required": [("tendered", "by whom tendered"), ("head of account",), ("amount",)],
        "optional": [
            ("name", "name (designation) and address of the person"),
            ("remittance", "full particular of the remittance"),
            ("accounts officer",), ("order to bank", "order to the bank"),
        ],
    },
    "W": {
        "name": "Application Questionnaire / Evaluation Form",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n"),
            ("item", "particulars", "items", "purpose"),
            ("response", "details", "documents", "information"),
        ],
        "optional": [("fees",), ("as per schedule",)],
    },
    "Y": {
        "name": "Comparative Study Results",
        "priority": "P3",
        "required": [("test", "test(s) conducted", "parameter")],
        "optional": [
            ("specification", "test rbc"), ("study a", "study b"),
            ("study conducted by searpharm", "present study"),
            ("data",), ("failed in assay",),
        ],
    },
    "Z": {
        "name": "PvPI Drug Safety Alert List",
        "priority": "P1",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s. no."),
            ("issue date",),
            ("suspected drugs", "suspected drug"),
            ("adverse drug reactions", "adverse drug reaction"),
        ],
        "optional": [("indication", "indication(s)")],
    },
    "AE": {
        "name": "Reference Product List for BE Studies",
        "priority": "P1",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "sr. no"),
            ("name of drug", "drug name"),
            ("bcs", "bcs (class ii/iv)"),
            ("product",),
            ("name of drug/ company/trade name", "name of drug/company/trade name/manufacturer"),
        ],
        "optional": [],
    },
    "AQ": {
        "name": "WHO / Fraudulent Drug Alert Product Identification",
        "priority": "P1",
        "required": [("product name",), ("stated",)],
        "optional": [],
    },
    "AR": {
        "name": "Banned Drugs List",
        "priority": "P0",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no", "s n", "s.n", "sr. no"),
            ("drugs name", "drug name"),
            ("notification", "notification no", "notification no. & date"),
        ],
        "optional": [],
    },
    "AS": {
        "name": "Medical Device Alert",
        "priority": "P2",
        "required": [("medical device", "device name", "product name", "product name, brand name")],
        "optional": [
            ("issue date", "date", "dated", "issue"),
            ("batch", "batch no", "batch no."),
            ("mfg date", "manufacturing date", "date of manufacture"),
            ("exp date", "expiry date", "date of expiry"),
        ],
    },
    "AT": {
        "name": "Approved Products for Marketing",
        "priority": "P1",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no"),
            ("name of drug", "drug name"),
            ("indication",),
            ("date of issue",),
        ],
        "optional": [],
    },
    "AU": {
        "name": "Registration Certificate Holder Register",
        "priority": "P1",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no"),
            ("indian agent", "indian agent/importer"),
            ("legal manufacturer",),
            ("reg. no", "reg. no.", "registration no"),
            ("validity",),
        ],
        "optional": [("category",)],
    },
    "AV": {
        "name": "Product Recall / Safety Alert",
        "priority": "P1",
        "required": [
            ("batch", "batch no", "batch no."),
            ("mfg date", "mfg date,", "manufacturing date"),
            ("exp date", "expiry date"),
        ],
        "optional": [],
    },
    "AC": {
        "name": "NLEM Data Tables",
        "priority": "P2",
        "required": [
            ("drug name", "drug", "drug name and strength", "name of drug",
             "name of drug strength", "drug name strength"),
        ],
        "optional": [
            ("therapeutic category", "therapeutic cat"),
            ("recommendations", "recommendations of experts"),
            ("section",), ("in nlem", "in nlem 2015", "in nlem 2022"),
        ],
    },
    "AD": {
        "name": "State-wise Sample Testing Statistics",
        "priority": "P3",
        "required": [
            ("samples drawn", "total no. of samples drawn", "samples tested",
             "samples drawn by cdsco"),
            ("tested", "total number of samples tested", "no. of sample tested",
             "no. of samples tested"),
            ("nsq", "not of standard quality", "no. of sample declared as nsq",
             "number of samples declared as not of standard quality"),
        ],
        "optional": [
            ("standard quality", "no. of samples declared as of standard quality",
             "number of samples declared as of standard quality"),
            ("steps taken", "steps taken on not of standard quality drugs"),
            ("state", "state zone"),
        ],
    },
    "AG": {
        "name": "Cost / Budget Breakdown",
        "priority": "P3",
        "required": [("component",), ("rate",), ("total", "total cost", "total price")],
        "optional": [("category",), ("no. of", "number of")],
    },
    "AH": {
        "name": "Timeline / Milestone / Schedule",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no"),
            ("particular", "milestone", "project", "application type"),
            ("timelines", "timeline", "timeline (as per rule in days)", "maximum marks"),
        ],
        "optional": [],
    },
    "AJ": {
        "name": "Post-Approval Change (PAC) Matrix",
        "priority": "P3",
        "required": [
            ("description of change",),
            ("conditions to be fulfilled", "conditions to fulfil"),
            ("supporting data", "supporting"),
            ("reporting category",),
        ],
        "optional": [],
    },
    "AL": {
        "name": "Feedback / Rating Scale",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no"),
            ("details",),
            ("excellent", "very good", "good"),
        ],
        "optional": [],
    },
    "AN": {
        "name": "IVD Performance Requirement Table",
        "priority": "P3",
        "required": [
            ("product", "product name"), ("technology",),
            ("specification", "specification/criteria", "criteria"), ("reference",),
        ],
        "optional": [],
    },
    "AO": {
        "name": "Contact Directory",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no"),
            ("ministry", "state", "department"),
            ("activity", "name of laboratory", "laboratory"),
        ],
        "optional": [],
    },
    "AP": {
        "name": "Inspection Non-Compliance Observations",
        "priority": "P3",
        "required": [
            ("s no", "sr no", "sl no", "serial no", "s.no"),
            ("checklist category",),
            ("non-compliance", "non compliance", "non compliance observed"),
        ],
        "optional": [],
    },
}

PRIORITY_TIERS: dict[str, str] = {k: v["priority"] for k, v in ARCHETYPE_DEFS.items()}
UNCLASSIFIED = ("UNCLASSIFIED", "Unclassified - not in supplied archetypes")


# ============================================================
# CELL NORMALIZATION
# ============================================================
def normalize_cell(value: Any) -> str:
    normalized = NON_WORDS.sub(" ", str(value or "").casefold())
    return WHITESPACE.sub(" ", normalized).strip()


def clean_cell(value: Any) -> str:
    return WHITESPACE.sub(" ", str(value or "")).strip()


# ============================================================
# NEW V3 HELPERS: junk / ascii / table gate
# ============================================================
def _is_junk_cell(cell: str) -> bool:
    """Empty, punctuation-only, single-char, or pure-number cells."""
    c = clean_cell(cell)
    if not c:
        return True
    if len(c) == 1:
        return True
    if not any(ch.isalnum() for ch in c):
        return True
    if NUMBER_ONLY.fullmatch(c):
        return True
    return False


def _ascii_ratio(text: str) -> float:
    if not text:
        return 1.0
    return sum(1 for ch in text if ord(ch) < 128) / len(text)


def _junk_ratio(rows: list[list], max_rows: int = 10) -> float:
    total = 0
    junk = 0
    for r in rows[:max_rows]:
        for c in r:
            total += 1
            if _is_junk_cell(c):
                junk += 1
    return junk / max(total, 1)


def _table_passes_gate(table: list[list[Any]]) -> bool:
    """Table-level gate: reject non-English, high-junk, fragment tables."""
    if not table or len(table) < 3:
        return False

    if _junk_ratio(table, 10) > 0.5:
        return False

    # Must have at least one plausible English header candidate
    header_valid = False
    for row in table[:12]:
        cells = [clean_cell(c) for c in row if not _is_junk_cell(clean_cell(c))]
        if len(cells) < 2:
            continue
        if _ascii_ratio(" ".join(cells)) < 0.85:
            continue
        avg_len = sum(len(c) for c in cells) / len(cells)
        if avg_len < 3:
            continue
        header_valid = True
        break

    if not header_valid:
        return False

    # At least 2 data rows with 2+ non-junk cells
    qualifying = sum(
        1 for r in table[1:50]
        if sum(1 for c in r if not _is_junk_cell(clean_cell(c))) >= 2
    )
    if qualifying < 2:
        return False

    return True


# ============================================================
# FUZZY MATCH
# ============================================================
def _fuzzy_col_match(header: str, expected: str) -> bool:
    a = normalize_cell(header)
    b = normalize_cell(expected)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) <= 4 or len(b) <= 4:
        return False
    if b in a or a in b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.78


def _match_column_group(header_cells: list[str], alternatives: tuple[str, ...]) -> bool:
    for header in header_cells:
        for alt in alternatives:
            if _fuzzy_col_match(header, alt):
                return True
    return False


# ============================================================
# V3 FIX: _score_archetype with used_headers
# ============================================================
def _score_archetype(header_cells: list[str], archetype_def: dict[str, Any]) -> dict[str, Any] | None:
    required = archetype_def.get("required", [])
    optional = archetype_def.get("optional", [])
    if not required:
        return None

    matched_required = 0
    matched_optional = 0
    matched_cols: list[str] = []
    used_headers: set[str] = set()  # <-- NEW: prevent same header matching multiple groups

    for group in required:
        for header in header_cells:
            if header in used_headers:
                continue
            if _match_column_group([header], group):
                matched_required += 1
                matched_cols.append(header)
                used_headers.add(header)
                break

    for group in optional:
        for header in header_cells:
            if header in used_headers:
                continue
            if _match_column_group([header], group):
                matched_optional += 1
                used_headers.add(header)
                break

    req_ratio = matched_required / len(required)
    opt_ratio = (matched_optional / len(optional)) if optional else 0.0

    if req_ratio < 0.75 or matched_required < 2:
        return None

    score = req_ratio * 0.85 + opt_ratio * 0.15
    return {
        "score": round(score, 3),
        "req_ratio": round(req_ratio, 3),
        "opt_ratio": round(opt_ratio, 3),
        "matched_required": matched_required,
        "total_required": len(required),
        "matched_optional": matched_optional,
        "matched_columns": matched_cols,
    }


def _classify_headers(header_cells: list[str]) -> tuple[str, dict[str, Any]] | None:
    if len(header_cells) < 2:
        return None
    if _ascii_ratio(" ".join(header_cells)) < 0.85:
        return None

    best_letter: str | None = None
    best_score: float = 0.0
    best_detail: dict[str, Any] | None = None
    best_req_ratio = 0.0

    for letter, defn in ARCHETYPE_DEFS.items():
        result = _score_archetype(header_cells, defn)
        if not result:
            continue
        score = result["score"]
        req_ratio = result["req_ratio"]
        if (
            req_ratio > best_req_ratio
            or (req_ratio == best_req_ratio and score > best_score)
            or (
                req_ratio == best_req_ratio
                and score == best_score
                and best_detail
                and result["matched_required"] > best_detail["matched_required"]
            )
        ):
            best_letter = letter
            best_score = score
            best_req_ratio = req_ratio
            best_detail = result

    if not best_letter or not best_detail:
        return None
    return best_letter, best_detail


# ============================================================
# V3 FIX: header detection with keyword scoring
# ============================================================
def _find_header_and_first_row(
    table: list[list[Any]],
) -> tuple[list[str], list[str], list[str], int] | None:
    if not table:
        return None

    best_score = -1.0
    best_idx: int | None = None

    for idx, row in enumerate(table[:12]):
        cells = [clean_cell(c) for c in row if not _is_junk_cell(clean_cell(c))]
        if len(cells) < 2:
            continue

        text = " ".join(cells)
        if _ascii_ratio(text) < 0.85:
            continue

        avg_len = sum(len(c) for c in cells) / len(cells)
        if avg_len < 3:
            continue

        keyword_hits = sum(
            1 for c in cells
            if any(kw in c.lower() for kw in HEADER_KEYWORDS)
        )

        # Penalize rows whose first cell is a serial number (data row signal)
        serial_penalty = 20 if SERIAL_VALUE.fullmatch(cells[0]) else 0

        score = keyword_hits * 10 + len(cells) * 2 + min(avg_len, 20) * 0.1 - serial_penalty
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_idx is None:
        return None

    header_filtered = [clean_cell(c) for c in table[best_idx] if c and str(c).strip()]
    while header_filtered and not header_filtered[-1]:
        header_filtered.pop()

    header_raw = [clean_cell(c) for c in table[best_idx]]
    while header_raw and not header_raw[-1]:
        header_raw.pop()

    first_row_raw: list[str] = []
    if best_idx + 1 < len(table):
        first_row_raw = [clean_cell(c) for c in table[best_idx + 1]]
        while first_row_raw and not first_row_raw[-1]:
            first_row_raw.pop()

    return header_filtered, header_raw, first_row_raw, best_idx


def _best_table_match(
    tables: list[list[list[Any]]],
) -> tuple[str, dict[str, Any], list[str], list[str]] | None:
    best_letter: str | None = None
    best_detail: dict[str, Any] | None = None
    best_score: float = 0.0
    best_header_raw: list[str] = []
    best_first_row_raw: list[str] = []

    for table in tables:
        # V3: table-level gate before scoring
        if not _table_passes_gate(table):
            continue

        found = _find_header_and_first_row(table)
        if not found:
            continue
        header_filtered, header_raw, first_row_raw, _ = found
        if not header_filtered or len(header_filtered) < 2:
            continue
        result = _classify_headers(header_filtered)
        if not result:
            continue
        letter, detail = result
        if detail["score"] > best_score:
            best_letter = letter
            best_detail = detail
            best_score = detail["score"]
            best_header_raw = header_raw
            best_first_row_raw = first_row_raw

    if not best_letter or not best_detail:
        return None
    return best_letter, best_detail, best_header_raw, best_first_row_raw


# ============================================================
# V3 FIX: only `lines` strategy for pymupdf
# ============================================================
def _extract_tables(pdf_path: Path, sample_pages: int) -> list[list[list[str]]]:
    extracted: list[list[list[str]]] = []
    if pymupdf is not None:
        try:
            with pymupdf.open(pdf_path) as doc:
                pages = list(doc)[:sample_pages] if sample_pages > 0 else list(doc)
                for page in pages:
                    seen: set[tuple] = set()
                    page_tables: list[list[list[str]]] = []
                    # V3: ONLY lines strategy (text strategy = Hindi garbage)
                    try:
                        tables = page.find_tables(strategy="lines").tables
                    except Exception:
                        tables = []
                    for tbl in tables:
                        try:
                            rows = tbl.extract()
                        except Exception:
                            continue
                        sig = tuple(tuple(clean_cell(c) for c in r) for r in rows or [])
                        if rows and sig not in seen:
                            seen.add(sig)
                            page_tables.append(rows)
                    extracted.extend(page_tables)
        except Exception as e:
            print(f"WARNING: PyMuPDF failed for {pdf_path.name}: {e}", file=sys.stderr)

    if extracted:
        return extracted

    if pdfplumber is not None:
        try:
            with pdfplumber.open(str(pdf_path)) as doc:
                pages = doc.pages[:sample_pages] if sample_pages > 0 else doc.pages
                for page in pages:
                    try:
                        tables = page.extract_tables()
                    except Exception:
                        continue
                    for tbl in tables or []:
                        if tbl and len(tbl) >= 2:
                            extracted.append([[clean_cell(c) for c in r] for r in tbl])
        except Exception as e:
            print(f"WARNING: pdfplumber failed for {pdf_path.name}: {e}", file=sys.stderr)
    return extracted


# ============================================================
# V3 FIX: pdfplumber verify with ASCII + junk gate
# ============================================================
def _pdfplumber_verify_table(
    pdf_path: Path, sample_pages: int
) -> tuple[bool, list[list[str]] | None]:
    if pdfplumber is None:
        return True, None

    best_table: list[list[str]] | None = None
    try:
        with pdfplumber.open(str(pdf_path)) as doc:
            pages = doc.pages[:sample_pages] if sample_pages > 0 else doc.pages
            for page in pages:
                try:
                    tables = page.extract_tables()
                except Exception:
                    continue
                for tbl in tables or []:
                    if not tbl or len(tbl) < 2:
                        continue

                    # V3: ASCII gate on first few rows
                    sample_text = " ".join(
                        str(c) for r in tbl[:5] for c in r if c
                    )
                    if _ascii_ratio(sample_text) < 0.7:
                        continue

                    # V3: junk gate
                    if _junk_ratio(tbl, 10) > 0.6:
                        continue

                    non_empty_rows = sum(
                        1
                        for r in tbl
                        if r and sum(1 for c in r if c and str(c).strip()) >= 2
                    )
                    if non_empty_rows < 2:
                        continue

                    has_header_like = False
                    for r in tbl[:5]:
                        if not r:
                            continue
                        cells = [clean_cell(c) for c in r if c and str(c).strip()]
                        if len(cells) < 2:
                            continue
                        non_numeric = sum(1 for c in cells if not NUMBER_ONLY.fullmatch(c))
                        if non_numeric >= max(2, len(cells) // 2):
                            has_header_like = True
                            break
                    if not has_header_like:
                        continue

                    if best_table is None or len(tbl) > len(best_table):
                        best_table = [[clean_cell(c) for c in r] for r in tbl]
    except Exception as e:
        print(f"WARNING: pdfplumber verify failed for {pdf_path.name}: {e}", file=sys.stderr)
        return True, None

    return best_table is not None, best_table


# ============================================================
# TEXT EXTRACTION
# ============================================================
def _extract_text(pdf_path: Path) -> str:
    if pymupdf is None:
        return ""
    try:
        with pymupdf.open(pdf_path) as doc:
            return "\n".join(page.get_text() or "" for page in doc)
    except Exception:
        return ""


# ============================================================
# DOCUMENT CONTEXT (unchanged)
# ============================================================
def _match_document_context(source: str, filename: str) -> dict[str, Any] | None:
    stem = normalize_cell(Path(filename).stem)
    title = normalize_cell(f"{source} {Path(filename).stem}")
    archetype = None

    if "banned drugs" in title or "drugs banned" in title or "banneddrugs" in title:
        archetype = "AR"
    elif "countrywide survey" in title and "spurious drugs" in title:
        archetype = "C"
    elif "spurious" in title and "drug" in title and "list" in title:
        archetype = "C"
    elif "nsq" in title and "vaccine" in title and "state" not in title:
        archetype = "A"
    elif re.search(r"\balert\b", stem) and "medical device" in stem:
        archetype = "AS"
    elif (
        re.search(r"\bdrugs? alert\b", stem)
        and ("list" in stem or "month" in stem)
        and "state" not in stem
        and "nsq" not in stem
        and "spurious" not in stem
    ):
        archetype = "A"
    elif "approved for marketing" in title:
        archetype = "AT"
    elif "rc holders" in title and "rc issued" in title:
        archetype = "AU"
    elif "recall" in title:
        archetype = "AV"
    elif "nlem" in title or "national list of essential medicines" in title:
        archetype = "AC"
    elif "ba be" in title and "study centre" in title:
        archetype = "O"
    elif "fdc" in title and (
        "prohibit" in title
        or "rational" in title
        or "banned" in title
        or "restrict" in title
        or ("permitted" in title and "manufacturing" in title)
    ):
        archetype = "K"
    elif (
        "laborator" in title
        and "list" in title
        and "performance evaluation" in title
        and ("ivd" in title or "in vitro diagnostic" in title)
    ):
        archetype = "F"

    if archetype is None:
        return None
    return {
        "type": archetype,
        "group": ARCHETYPE_DEFS[archetype]["name"],
        "confidence": 0.95,
        "matched_columns": "",
        "header_row": "",
        "first_row": "",
        "match_method": "document_context",
        "match_count": 1,
    }


def _is_non_record_document(filename: str) -> bool:
    stem = normalize_cell(Path(filename).stem)
    return (
        "inviting comments" in stem
        and "evaluation" in stem
        and "protocol" in stem
    ) or (
        "guidance document" in stem
        and "disposal" in stem
        and "expired unused drugs" in stem
    )


# ============================================================
# CLASSIFICATION
# ============================================================
def _safe_child(root: Path, *parts: str) -> Path:
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"Input path escapes configured root: {candidate}")
    return candidate


def _result_fields(match: dict[str, Any], tables_analyzed: int = 0) -> dict[str, Any]:
    return {
        "table_type": match["type"],
        "table_group": match["group"],
        "table_label": match["group"],
        "table_priority": PRIORITY_TIERS.get(match["type"], "UNKNOWN"),
        "confidence": match["confidence"],
        "matched_columns": match["matched_columns"],
        "header_row": match.get("header_row", ""),
        "first_row": match.get("first_row", ""),
        "extraction_status": match["extraction_status"],
        "match_method": match.get("match_method", "document_context"),
        "tables_analyzed": tables_analyzed,
    }


def _unmatched(label: str, status: str, tables_analyzed: int = 0) -> dict[str, Any]:
    return {
        "table_type": UNCLASSIFIED[0],
        "table_group": UNCLASSIFIED[1],
        "table_label": label,
        "table_priority": "UNKNOWN",
        "confidence": 0.0,
        "matched_columns": "",
        "header_row": "",
        "first_row": "",
        "extraction_status": status,
        "match_method": "none",
        "tables_analyzed": tables_analyzed,
    }


# ============================================================
# V3 FIX: text fallback with ASCII gate + stricter thresholds
# ============================================================
def _match_text(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    # V3: reject Hindi / Devanagari-heavy documents
    if _ascii_ratio(text) < 0.85:
        return None

    normalized = f" {normalize_cell(text)} "
    candidates: list[tuple[float, int, str, list[str]]] = []
    for letter, defn in ARCHETYPE_DEFS.items():
        matched: list[str] = []
        for group in defn.get("required", []):
            for alt in group:
                alt_norm = normalize_cell(alt)
                # V3: skip short generic tokens (was 5, now 6)
                if len(alt_norm) < 6:
                    continue
                if f" {alt_norm} " in normalized:
                    matched.append(alt)
                    break
        if len(matched) >= 2:
            ratio = len(matched) / max(len(defn["required"]), 1)
            # V3: raise threshold 0.6 -> 0.7
            if ratio >= 0.7:
                candidates.append((ratio, len(matched), letter, matched))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    ratio, count, letter, matched = candidates[0]
    return {
        "type": letter,
        "group": ARCHETYPE_DEFS[letter]["name"],
        "confidence": round(ratio, 3),
        "matched_columns": "; ".join(matched),
        "header_row": "",
        "first_row": "",
        "match_method": "text_fallback",
        "match_count": count,
    }


def classify_document(
    row: dict[str, str],
    downloads_root: Path,
    sample_pages: int,
) -> dict[str, Any]:
    source = (row.get("Source") or "").strip()
    filename = (row.get("File Name") or "").strip()
    if not source or not filename:
        return _unmatched("Missing source or file name", "INVALID_CSV_ROW")

    pdf_path = _safe_child(downloads_root, source, filename)
    if not pdf_path.is_file():
        return _unmatched("PDF not found", "MISSING_PDF")

    try:
        page_count = int(row.get("Page Count", 0) or 0)
    except (ValueError, TypeError):
        page_count = 0

    context_match = _match_document_context(source, filename)

    pdfplumber_has_table, pdfplumber_best = _pdfplumber_verify_table(
        pdf_path, sample_pages
    )

    tables = _extract_tables(pdf_path, sample_pages)
    tables_analyzed = len(tables)
    match = _best_table_match(tables)
    used_fullscan = False

    if not match and pdfplumber_has_table and pdfplumber_best:
        match = _best_table_match([pdfplumber_best])

    if not match and sample_pages > 0:
        norm_name = normalize_cell(filename)
        should_retry = (
            "merged existing medical devices risk classification" in norm_name
            or page_count <= 2
        )
        if should_retry:
            tables = _extract_tables(pdf_path, 0)
            tables_analyzed = len(tables)
            match = _best_table_match(tables)
            if match:
                used_fullscan = True

    structured_result: dict[str, Any] | None = None
    if match:
        best_letter, best_detail, best_header_raw, best_first_row_raw = match
        structured_result = {
            "type": best_letter,
            "group": ARCHETYPE_DEFS[best_letter]["name"],
            "confidence": best_detail["score"],
            "matched_columns": "; ".join(best_detail["matched_columns"]),
            "header_row": ROW_SEP.join(best_header_raw),
            "first_row": ROW_SEP.join(best_first_row_raw),
            "match_method": "column_match_fullscan" if used_fullscan else "column_match",
            "match_count": best_detail["matched_required"],
        }

    # FORCE CONTEXT — AR / A always win
    if context_match and context_match["type"] in FORCE_CONTEXT_TYPES:
        if structured_result:
            context_match["matched_columns"] = structured_result["matched_columns"]
            context_match["header_row"] = structured_result["header_row"]
            context_match["first_row"] = structured_result["first_row"]
            context_match["match_method"] = "context_force"
            context_match["extraction_status"] = "OK_CONTEXT_FORCE"
        else:
            context_match["extraction_status"] = "OK_DOCUMENT_CONTEXT"
        return _result_fields(context_match, tables_analyzed)

    if structured_result:
        if (
            context_match
            and context_match["type"] != structured_result["type"]
            and page_count > 50
            and context_match["type"] in STRONG_CONTEXT_TYPES
        ):
            resolved = dict(context_match)
            resolved["matched_columns"] = structured_result["matched_columns"]
            resolved["header_row"] = structured_result["header_row"]
            resolved["first_row"] = structured_result["first_row"]
            resolved["match_method"] = "context_over_table"
            resolved["extraction_status"] = "OK_CONTEXT_OVERRIDE"
            return _result_fields(resolved, tables_analyzed)

        structured_result["extraction_status"] = "OK_COLUMN_MATCH"
        return _result_fields(structured_result, tables_analyzed)

    if context_match:
        context_match["extraction_status"] = "OK_DOCUMENT_CONTEXT"
        return _result_fields(context_match, tables_analyzed)

    if pdfplumber_has_table and not _is_non_record_document(filename):
        text = _extract_text(pdf_path)
        text_result = _match_text(text)
        if text_result:
            text_result["extraction_status"] = "OK_TEXT_FALLBACK"
            return _result_fields(text_result, tables_analyzed)

    if _is_non_record_document(filename):
        status = "NO_RECORD_TABLE"
    elif not pdfplumber_has_table:
        status = "NO_REAL_TABLE"
    elif tables:
        status = "UNKNOWN_NO_MATCH"
    else:
        status = "NO_TEXT_OR_TABLES"
    return _unmatched("No confident table-type match", status, tables_analyzed)


# ============================================================
# CLI
# ============================================================
def run(args: argparse.Namespace) -> int:
    with args.csv.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"Source", "File Name", "Structure"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
        fieldnames = list(reader.fieldnames or [])
        rows = [r for r in reader if (r.get("Structure") or "").strip().casefold() == "table"]

    if args.limit:
        rows = rows[: args.limit]

    new_cols = [
        "table_type", "table_group", "table_label", "table_priority",
        "confidence", "matched_columns", "header_row", "first_row",
        "extraction_status", "match_method", "tables_analyzed",
    ]
    output_fields = [f for f in fieldnames if f not in new_cols] + new_cols

    print(f"Archetypes defined inline: {len(ARCHETYPE_DEFS)}")
    print(f"Rows with Structure=table: {len(rows)}")
    if args.dry_run:
        print("Dry run — no CSV will be written.")

    results = []
    for i, row in enumerate(rows, start=1):
        result = {**row, **classify_document(row, args.downloads_root, args.sample_pages)}
        results.append(result)
        print(
            f"[{i}/{len(rows)}] type={result['table_type']} "
            f"group={result['table_group']} "
            f"method={result['match_method']} "
            f"{row.get('Source','')}/{row.get('File Name','')}"
        )

    if not args.dry_run:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_fields)
            writer.writeheader()
            writer.writerows(results)
        print(f"Wrote {len(results)} rows to {args.output}")

    counts = Counter(r["table_group"] for r in results)
    if counts:
        print("Table groups:")
        for group, count in counts.most_common():
            print(f"  {group}: {count}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Classify table-structured PDFs by matching PDF table columns "
                    "against inline archetype column signatures."
    )
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--downloads-root", type=Path, default=DEFAULT_DOWNLOADS_ROOT)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--sample-pages", type=int, default=10,
                   help="Max PDF pages for initial table scan; 0 = all.")
    p.add_argument("--limit", type=int, default=0, help="Process only first N rows.")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    args.csv = args.csv.resolve()
    args.downloads_root = args.downloads_root.resolve()
    args.output = args.output.resolve()
    if args.sample_pages < 0:
        p.error("--sample-pages must be >= 0")
    if args.limit < 0:
        p.error("--limit must be >= 0")
    return args


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())