# analysis/scripts/scanned/config.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCANNED_JSON_DIR = ROOT / "scanned_json"
EXISTING_CSV     = ROOT / "csv" / "classfied_scanned_only.csv"
OUT_PARTS        = ROOT / "csv" / "classfied_scanned_parts.csv"
OUT_DOCS         = ROOT / "csv" / "classfied_scanned_docs.csv"
OUT_AUDIT        = ROOT / "csv" / "audit_report.csv"

# ---- geometry / thresholds ----
ROW_Y_TOL      = 8
ROW_OVERLAP_RATIO = 0.35
MAX_HEADER_ROWS = 5
MIN_TABLE_ROWS = 1
MIN_TABLE_COLS = 2
LOW_CONF       = 0.55   # OCR confidence below this triggers a review flag

# ---- table archetype signatures (matched against reconstructed header text) ----
TABLE_SIGNATURES = {
    "A": {"s no", "sr no", "sl no", "batch no", "mfg date", "date of manufacture", "exp date", "manufactured by", "reason for failure", "drawn by", "name of drugs"},
    "B": {"nsq result", "reported by state", "manufacturing date", "expiry date", "batch no", "manufactured by", "product name", "drug name"},
    "C": {"spurious", "section 17b", "firm reply", "remarks", "drawn by", "batch no", "name of drugs"},
    "D": {"device name", "intended use", "risk class", "risk classification"},
    "E": {"file no", "company address", "product name", "intended use", "regulatory status", "date of issue"},
    "F": {"category", "name of facility", "testing facility", "laboratory"},
    "G": {"rule no", "subject", "fee inr", "fee usd"},
    "H": {"title", "page no", "contents", "index"},
    "I": {"checklist", "yes", "no", "na", "item"},
    "J": {"vaccine", "strain", "dosage form", "indication", "permission no"},
    "K": {"fdc", "fixed dose combination", "strength", "dosage form", "notification no"},
    "L": {"abbreviation", "abbr", "full form"},
    "M": {"name of firm", "type of kit", "pcr", "country"},
    "N": {"month", "tentative dates", "day", "meeting schedule"},
    "O": {"babe", "study centre", "centre address", "valid upto"},
    "P": {"designation", "laboratory", "class of drugs", "government analyst"},
    "Q": {"storage condition", "shelf life", "testing interval", "stability"},
    "R": {"sae", "psur", "duration from", "duration to", "units sold"},
    "S": {"cleanroom", "iso class", "type of operation"},
    "T": {"extent and conditions", "criteria", "class of device"},
    "U": {"is no", "standard no", "amendment no", "date established"},
    "V": {"tendered by", "particulars", "amount rs", "head of account"},
    "W": {"questionnaire", "item particulars", "response", "evaluation form"},
    "X": {"healthcare prof", "domestic mfr", "importer", "govt program"},
    "Y": {"parameter", "study a", "study b", "specification"},
    "Z": {"suspected drug", "indication", "adverse drug reaction", "issue date"},
    "AA": {"acceptance criteria", "min samples", "type of assay"},
    "AB": {"designation", "institution", "committee member", "staff roster"},
    "AC": {"nlem", "essential medicine", "therapeutic category", "level of healthcare"},
    "AD": {"state zone", "total drawn", "total tested", "standard quality"},
    "AE": {"bcs class", "reference product", "company trade name"},
    "AF": {"pi name", "site address", "site type", "iec name"},
    "AG": {"category", "component", "rate", "total cost"},
    "AH": {"particular", "timeline days", "milestone"},
    "AI": {"equipment", "frequency", "calibration"},
    "AJ": {"description of change", "conditions to fulfil", "supporting data", "reporting category"},
    "AK": {"supplier", "kit batch no", "first time validation", "last validation details"},
    "AL": {"excellent", "very good", "fair", "poor", "rating scale"},
    "AM": {"product brand", "brand name", "pack size", "actual manufacturer"},
    "AN": {"technology", "specification criteria", "reference"},
    "AO": {"ministry or state", "activity or lab name", "contact directory"},
    "AP": {"checklist category", "non compliance observed"},
    "AQ": {"stated value", "actual value", "falsified", "product name"},
    "AR": {"drug name", "notification no", "banned", "prohibited"},
    "AS": {"device alert", "device name", "issue", "recommended action"},
    "AT": {"approved products", "indication", "date of issue"},
    "AU": {"registration certificate", "holder", "validity", "importer"},
    "AV": {"recall", "part no", "lot no", "serial number", "serial numbers", "model number", "model numbers", "remote controller", "description", "batch"},
}

TABLE_HEADER_KEYWORDS = {
    "s no", "sr no", "sl no", "name", "product", "drug", "batch", "lot",
    "date", "manufacturer", "description", "serial number", "model number",
    "quantity", "strength", "dosage form", "indication", "status", "reason",
}

# fallback: scan row text for these tokens
TABLE_ROW_TOKENS = {
    "C":  ["spurious", "section 17b"],
    "K":  ["fdc", "fixed dose"],
    "Z":  ["adverse drug reaction"],
    "AR": ["banned"],
    "AV": ["recall", "part no", "lot no", "serial number", "model number"],
}

# ---- paragraph archetype signatures (any >=1 hit → candidate) ----
PARA_SIGNATURES = {
    "P1":  ["spurious", "falsified", "adulterated", "misbranded"],
    "P2":  ["nsq", "not of standard quality", "failed test"],
    "P3":  ["prohibited", "prohibition", "section 26a"],
    "P3b": ["restricted", "restriction"],
    "P3c": ["category c", "18-month", "conditional permission", "continued manufacturing"],
    "P4":  ["banned", "prohibited for manufacture"],
    "P5":  ["recall", "field safety notice"],
    "P6":  ["who alert", "falsified", "international authority"],
    "P7":  ["pvpi", "adverse drug reaction", "adr", "suspected drug"],
    "P8":  ["warning", "advisory", "labelling", "labeling"],
    "P9":  ["medical device alert", "device recall", "device safety"],
    "P10": ["approved products", "approved for marketing", "market authorization"],
    "P11": ["registration certificate", "certificate holder", "importer register"],
    "P12": ["noc", "clarification", "not regulated", "regulatory status"],
    "P13": ["reference product", "bioequivalence study", "bcs class"],
    "P14": ["nlem", "essential medicines", "essential medicine"],
    "P15": ["testing facility", "laboratory list", "laboratory listing"],
    "P16": ["veterinary", "animal use"],
    "P17": ["ivd", "pcr kit", "diagnostic kit approval"],
    "P18": ["sae", "psur", "pharmacovigilance analytics"],
    "P19": ["country-wide survey", "aggregate findings", "sample counts"],
    "P20": ["application", "submission", "checklist", "babe"],
    "P21": ["babe centre", "study centre approval", "centre address"],
    "P22": ["faq", "public awareness", "general guidance"],
    "P23": ["expert committee", "committee report", "recommendation"],
    "P24": ["meeting", "minutes", "agenda", "participants"],
    "P25": ["enforcement", "prosecution", "compounding"],
    "P26": ["gazette", "appointment", "roster", "debarment", "port", "fee"],
    "P27": ["corrigendum", "correction to", "erratum"],
    "P28": ["public notice", "circular", "press note"],
    "P29": ["amendment", "draft", "proposed", "notification", "s.o."],
    "P30": ["historical", "emergency", "expired", "repealed"],
}

# ---- class maps ----
TABLE_CLASS = {
    "A": ("Usable", "P0"), "B": ("Usable", "P0"), "C": ("Usable", "P0"),
    "K": ("Usable", "P0"), "AR": ("Usable", "P0"),
    "Z": ("Usable", "P1"), "AQ": ("Usable", "P1"), "AV": ("Usable", "P1"),
    "D": ("Future-usable", "P2"), "E": ("Future-usable", "P2"),
    "F": ("Future-usable", "P2"), "J": ("Future-usable", "P2"),
    "M": ("Future-usable", "P2"), "R": ("Future-usable", "P2"),
    "AC": ("Future-usable", "P2"), "AE": ("Future-usable", "P2"),
    "AM": ("Future-usable", "P2"), "AS": ("Future-usable", "P2"),
    "AT": ("Future-usable", "P2"), "AU": ("Future-usable", "P2"),
}
TABLE_CLASS.update({
    archetype: ("Non-usable", "P3")
    for archetype in TABLE_SIGNATURES
    if archetype not in TABLE_CLASS
})
PARA_CLASS = {
    "P1": ("Usable", "P0"), "P2": ("Usable", "P0"),
    "P3": ("Usable", "P0"), "P3b": ("Usable", "P0"), "P3c": ("Usable", "P0"),
    "P4": ("Usable", "P0"), "P7": ("Usable", "P1"),
    "P5": ("Usable", "P1"), "P6": ("Usable", "P1"),
    "P8": ("Future-usable", "P2"), "P9": ("Future-usable", "P2"),
    "P10": ("Future-usable", "P2"), "P11": ("Future-usable", "P2"),
    "P12": ("Future-usable", "P2"), "P13": ("Future-usable", "P2"),
    "P14": ("Future-usable", "P2"), "P15": ("Future-usable", "P2"),
    "P16": ("Future-usable", "P2"), "P17": ("Future-usable", "P2"),
    "P18": ("Future-usable", "P2"), "P19": ("Future-usable", "P2"),
    "P29": ("Future-usable", "P2"), "P30": ("Future-usable", "P2"),
    "P20": ("Non-usable", "P3"), "P21": ("Non-usable", "P3"),
    "P22": ("Non-usable", "P3"), "P23": ("Non-usable", "P3"),
    "P24": ("Non-usable", "P3"), "P25": ("Non-usable", "P3"),
    "P26": ("Non-usable", "P3"), "P27": ("Non-usable", "P3"),
    "P28": ("Non-usable", "P3"),
}

# ---- product-type hints (normalized substring match) ----
PRODUCT_HINTS = {
    "veterinary": ["vet", "veterinary", "animal use", "animal-use", "veterinary product"],
    "device": ["medical device", "device alert", "guidewire", "catheter", "infusion pump", "remote controller", "controller", "stent", "ivd", "diagnostic kit", "device recall"],
    "cosmetic": ["cosmetic"],
}

# ---- required fields per P-series (from paragraph_taxonomy_for_app.md) ----
REQUIRED_FIELDS = {
    "P1": ["product_name", "batch_no", "manufacturer", "failure_reason"],
    "P2": ["product_name", "batch_no", "manufacturer", "failure_reason"],
    "P3": ["product_name", "notification_no", "operative_prohibition"],
    "P3b": ["product_name", "restriction_condition"],
    "P3c": ["operative_condition"],
    "P4": ["product_name", "notification_no", "operative_prohibition"],
    "P5": ["specific_action"],
    "P6": ["specific_action"],
    "P7": ["suspected_drug", "adverse_reaction", "alert_format"],
}

# columns appended to the existing CSV (existing columns untouched)
ROLLUP_COLUMNS = [
    "paragraph_taxonomy_ids", "table_taxonomy_ids", "usable_count",
    "future_count", "non_usable_count", "rollup_label", "review_status",
]