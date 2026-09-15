"""
Map raw regulatory facts (event_type, status, legal_status,
investigation_status) to the UI colour.

IMPORTANT:
- Colours are derived here, never stored in the DB.
- NOT_OF_STANDARD_QUALITY is never automatically mapped to BANNED.
- GREEN means "no matching alert in the checked sources", nothing more.
"""
from __future__ import annotations

from typing import Optional

Color = str  # "RED" | "YELLOW" | "GREEN"

_RED_EVENT_TYPE_TOKENS = (
    "PROHIBIT",
    "BANNED",
    "BAN",
    "SPURIOUS",
    "FALSIFIED",
    "ADULTERAT",
    "RECALL",
    "WITHDRAW",
    "CANCEL",
)

_RED_STATUS_TOKENS = (
    "PROHIBIT",
    "BANNED",
    "SPURIOUS",
    "FALSIFIED",
    "ADULTERAT",
)

# Not falling back to RED for these; they are concerns, not bans.
_YELLOW_EVENT_TYPE_TOKENS = (
    "QUALITY_FAILURE",
    "SAFETY",
    "INVESTIGATION",
    "ALERT",
)

_YELLOW_STATUS_TOKENS = (
    "NOT_OF_STANDARD_QUALITY",
    "NSQ",
    "SUB_STANDARD",
    "SAFETY_ALERT",
    "UNDER_INVESTIGATION",
)

_COLOR_RANK = {"GREEN": 1, "YELLOW": 2, "RED": 3}


def _upper(value: Optional[str]) -> str:
    return (value or "").upper()


def classify_event(
    event_type: Optional[str],
    status: Optional[str],
    legal_status: Optional[str] = None,
    investigation_status: Optional[str] = None,
) -> Color:
    """
    Returns RED, YELLOW, or GREEN for a single regulatory event.
    """
    et = _upper(event_type)
    st = _upper(status)
    ls = _upper(legal_status)
    iv = _upper(investigation_status)

    # RED signals
    if any(tok in et for tok in _RED_EVENT_TYPE_TOKENS):
        # "Suspected/Under investigation" downgrades to YELLOW
        if "UNDER" in iv or "SUSPECT" in iv or "SUSPECT" in st:
            return "YELLOW"
        return "RED"
    if any(tok in st for tok in _RED_STATUS_TOKENS):
        if "SUSPECT" in st or "UNDER" in iv:
            return "YELLOW"
        return "RED"
    if "PROHIBIT" in ls or "BANNED" in ls:
        return "RED"

    # YELLOW signals
    if any(tok in et for tok in _YELLOW_EVENT_TYPE_TOKENS):
        return "YELLOW"
    if any(tok in st for tok in _YELLOW_STATUS_TOKENS):
        return "YELLOW"

    # Unknown but present event -> treat as concern, not green.
    if et or st:
        return "YELLOW"

    return "GREEN"


def color_priority(color: Color) -> int:
    return _COLOR_RANK.get(color, 0)


def severity_for(color: Color) -> str:
    if color == "RED":
        return "HIGH"
    if color == "YELLOW":
        return "MEDIUM"
    return "LOW"


def title_for(color: Color) -> str:
    if color == "RED":
        return "Serious regulatory action found"
    if color == "YELLOW":
        return "Regulatory concern found"
    return "No regulatory alert found"