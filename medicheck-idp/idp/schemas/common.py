"""Types shared by every stage contract."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Tuple

from pydantic import BaseModel, ConfigDict

AppClass = Literal["usable", "future_usable", "non_usable"]
Priority = Literal["P0", "P1", "P2", "P3"]
# x0, y0, x1, y1 in PDF points, origin top-left (PyMuPDF convention).
BBox = Tuple[float, float, float, float]
# Where a piece of text came from: the PDF text layer, OCR, or both.
ContentOrigin = Literal["text_layer", "ocr", "mixed"]


class LegalStatus(str, Enum):
    """Legal status of a passage. Keys of `legal_status_display` in rules/usability_rules.yaml."""

    final_or_effective_explicitly_stated = "final_or_effective_explicitly_stated"
    draft_or_proposed_explicitly_stated = "draft_or_proposed_explicitly_stated"
    administrative_or_informational = "administrative_or_informational"
    banned = "banned"
    repealed = "repealed"
    rescinded = "rescinded"
    superseded = "superseded"
    corrected = "corrected"
    unclear_from_excerpt = "unclear_from_excerpt"


class StrictModel(BaseModel):
    """Contract models reject unknown fields, so a misspelt key fails loudly instead of being dropped."""

    model_config = ConfigDict(extra="forbid")
