"""Stage 5 output contract: the classification of every unit of one structured document.

A unit is either one logical table or one paragraph unit (a heading section or a fixed-size chunk of
blocks). Every unit is recorded, including non-usable and unclassifiable ones; stage 6 filters.

Per INV-14 (rules/usability_rules.yaml) app_classification, priority and legal_status are independent
fields. `direct_match_ready` is NOT decided here: it needs the fields extracted by the parser, so the
classifier only lists the gate that will decide it (`gate_ids`).
"""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import Field

from idp.schemas.common import AppClass, LegalStatus, Priority, StrictModel

SCHEMA_VERSION = "1.0"

UnitKind = Literal["table", "paragraph"]
UnitStatus = Literal["classified", "needs_review", "not_a_record"]
Method = Literal["rule", "llm"]


class Evidence(StrictModel):
    kind: Literal["header_match", "concept_match", "pattern_match", "context_cue", "llm_quote"]
    text: str = Field(description="The matched header, pattern match or quoted wording, copied from the source")
    rule_id: Optional[str] = None
    char_span: Optional[tuple[int, int]] = Field(
        default=None, description="Offsets into the unit text with whitespace collapsed to single spaces, paragraphs only"
    )
    detail: dict[str, Any] = Field(default_factory=dict)


class Label(StrictModel):
    label: str = Field(description="Archetype ID: A-AV / NU for tables, P-series for paragraphs")
    name: str
    app_classification: AppClass
    class_mode: Literal["fixed", "conditional"] = "fixed"
    priority: Priority
    confidence: float = Field(ge=0, le=1)
    method: Method
    rule_ids: List[str] = Field(default_factory=list, description="Classification rules that produced this label")
    layout_id: Optional[str] = Field(default=None, description="Matched table layout, tables only")
    evidence: List[Evidence] = Field(default_factory=list)
    gate_ids: List[str] = Field(default_factory=list, description="Usability gates that decide direct-match readiness later")
    record_rule_ids: List[str] = Field(default_factory=list, description="Record-level rules the parser must apply")


class Candidate(StrictModel):
    """A label the rules proposed, kept for audit whether or not it was accepted."""

    label: str
    score: float
    rule_ids: List[str] = Field(default_factory=list)
    layout_id: Optional[str] = None


class Escalation(StrictModel):
    reasons: List[str] = Field(description="Why the unit went to the model: no_rule_match, rule_conflict, low_confidence")
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None
    cached: bool = False
    outcome: Literal["accepted", "rejected", "unavailable", "error"]
    detail: Optional[str] = None


class UnitSource(StrictModel):
    pages: List[int]
    table_id: Optional[str] = None
    block_ids: List[str] = Field(default_factory=list)
    heading_path: List[str] = Field(default_factory=list)


class ClassifiedUnit(StrictModel):
    unit_id: str
    kind: UnitKind
    source: UnitSource
    text_preview: str = Field(description="First characters of the unit text, for reviewers")
    status: UnitStatus
    labels: List[Label] = Field(default_factory=list)
    legal_status: Optional[LegalStatus] = Field(default=None, description="Paragraph units only")
    legal_status_rule_id: Optional[str] = None
    requires_record_split: bool = Field(default=False, description="True when a record rule must be applied row by row in parsing")
    candidates: List[Candidate] = Field(default_factory=list)
    escalation: Optional[Escalation] = None
    review_reasons: List[str] = Field(default_factory=list)


class Versions(StrictModel):
    taxonomy: str
    usability_rules: str
    classification_rules: str
    rules_sha256: str = Field(description="Hash of every rule file, so an output can be traced to exact rules")
    classifier: str


class LLMInfo(StrictModel):
    provider: str
    model: str
    prompt_version: str


class Summary(StrictModel):
    units: int
    by_status: dict[str, int]
    by_app_classification: dict[str, int]
    escalated: int


class ClassifiedDocument(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    document_id: str
    document_sha256: str
    title: Optional[str] = None
    created_at: str
    versions: Versions
    llm: Optional[LLMInfo] = None
    units: List[ClassifiedUnit]
    summary: Summary
