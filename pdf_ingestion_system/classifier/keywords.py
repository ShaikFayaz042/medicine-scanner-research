"""
Topical keyword dictionary for relevance scoring.
Core terms from spec + expanded terms learned from CDSCO corpus.
"""

TOPICAL_KEYWORDS = {
    # --- Core (spec) ---
    "spurious": 5,
    "nsq": 5,
    "not of standard quality": 5,
    "drug alert": 4,
    "recall": 4,
    "prohibited": 4,
    "fdc": 3,
    "fixed dose combination": 3,
    # --- Expanded (corpus learned) ---
    "adulterated": 5,
    "misbranded": 5,
    "substandard": 5,

    "drug alerts": 4,
    "drugs alert": 4,
    "drugs alerts": 4,
    "safety alert": 4,
    "safety alerts": 4,
    "adverse drug reaction": 4,
    "adverse drug reactions": 4,
    "pharmacovigilance": 4,
    "pvpi": 4,
    "banned": 4,
    "banned drug": 4,
    "banned drugs": 4,
    "section 26a": 4,
    "section 10a": 4,

    "fdcs": 3,
    "fixed dose combinations": 3,

    # Record signals (weight 1 - structural, not relevance)
    "batch no": 1,
    "batch nos": 1,
    "batch number": 1,
    "batch numbers": 1,
    "b. no": 1,
    "b.no": 1,
    "lot no": 1,
    "manufacturer": 1,
    "manufacturers": 1,
    "manufactured by": 1,
    "mfd by": 1,
}

# Cap per-keyword contribution to prevent single-keyword domination.
# A doc mentioning "manufacturer" 100 times is not 100x more relevant
# than a doc mentioning it once.
MAX_COUNT_PER_KEYWORD = 5

TOPICAL_MAX_SCORE = 40.0

TOPICAL_LOW = 0.30
TOPICAL_HIGH = 0.60

# Borderline bands that should flag needs_review
BORDERLINE_LOW = 0.28
BORDERLINE_HIGH = 0.32
