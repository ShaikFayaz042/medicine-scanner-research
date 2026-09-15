"""
Light-weight input normalization. Must match how the DB was normalized:
- lowercase
- collapse whitespace
- strip punctuation to spaces
"""
from __future__ import annotations

import re
from typing import Optional

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]+")


def normalize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    s = value.strip().lower()
    if not s:
        return None
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s or None


def normalize_batch(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    s = value.strip().upper()
    return s or None