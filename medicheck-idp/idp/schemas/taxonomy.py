"""Pydantic models for the YAML files under rules/, plus cross-file validation.

Loaded at worker start-up: a typo or a dangling reference fails immediately instead of silently never
matching. Entries reject unknown keys (`extra="forbid"`); sections the classifier does not use are kept
loosely typed so other stages can extend them.
"""

from __future__ import annotations

import re
from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from idp.schemas.common import AppClass, LegalStatus, Priority, StrictModel

ColumnsStatus = Literal["complete", "partial", "descriptive_only"]


# --------------------------------------------------------------------------------------------------
# rules/taxonomy/meta.yaml
# --------------------------------------------------------------------------------------------------
class OpenDecision(StrictModel):
    id: str
    title: str
    status: Literal["open", "resolved"]
    owner: str
    detail: str
    current_encoding: str
    affects: List[str] = Field(default_factory=list)


class Meta(BaseModel):
    model_config = ConfigDict(extra="allow")

    taxonomy_version: str
    schema_version: int
    generic_columns: List[str]
    field_vocabulary: dict[str, dict[str, str]]
    open_decisions: List[OpenDecision] = Field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# rules/taxonomy/tables.yaml
# --------------------------------------------------------------------------------------------------
class Column(StrictModel):
    canonical: str
    variants: List[str] = Field(default_factory=list)
    optional: bool = False
    known_values: List[str] = Field(default_factory=list)

    @field_validator("canonical", mode="before")
    @classmethod
    def _as_text(cls, value: Any) -> str:
        # YAML 1.1 reads bare yes/no as booleans; the canonical is always a name.
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)


class CompositeCell(StrictModel):
    header_variants: List[str]
    split_into: List[str]


class Layout(StrictModel):
    layout_id: str
    columns: List[Column] = Field(default_factory=list)
    inherits: Optional[str] = None
    composite_cells: List[CompositeCell] = Field(default_factory=list)
    ambiguous_with: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    notes: Optional[str] = None


class TableArchetype(StrictModel):
    id: str
    name: str
    default_class: AppClass
    priority: Priority
    purpose: Optional[str] = None
    scope_condition: Optional[str] = None
    columns_status: ColumnsStatus
    matchable: bool
    status_values: List[str] = Field(default_factory=list)
    column_description: Optional[str] = None
    expected_concepts: List[str] = Field(default_factory=list)
    layouts: List[Layout] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list)
    notes: Union[List[str], str, None] = None
    decision_refs: List[str] = Field(default_factory=list)


class TablesFile(StrictModel):
    tables: List[TableArchetype]


# --------------------------------------------------------------------------------------------------
# rules/taxonomy/paragraphs.yaml
# --------------------------------------------------------------------------------------------------
class Relation(StrictModel):
    type: Literal["splits_to", "routes_to", "updates_parent", "links_on_effect", "related"]
    targets: List[str]
    when: str


class ParagraphArchetype(StrictModel):
    id: str
    name: str
    archetype: str
    default_class: AppClass
    class_mode: Literal["fixed", "conditional"]
    priority: Priority
    priority_when_deferred: Optional[Priority] = None
    app_use: Optional[str] = None
    maps_to_tables: List[str] = Field(default_factory=list)
    extraction_fields: List[str] = Field(default_factory=list)
    relations: List[Relation] = Field(default_factory=list)
    guardrails: List[str] = Field(default_factory=list)
    decision_refs: List[str] = Field(default_factory=list)
    replaces: List[str] = Field(default_factory=list, description="Retired IDs merged into this one")


class ParagraphsFile(StrictModel):
    paragraphs: List[ParagraphArchetype]


# --------------------------------------------------------------------------------------------------
# rules/usability_rules.yaml   (only the sections the classifier reads are typed strictly)
# --------------------------------------------------------------------------------------------------
class ParagraphGate(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    applies_to: List[str]
    direct_use: Literal["direct", "conditional", "none"]
    require_fields: List[str] = Field(default_factory=list)


class RecordRule(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    action: str
    applies_to_tables: List[str] = Field(default_factory=list)
    applies_to_paragraphs: List[str] = Field(default_factory=list)


class UsabilityRules(BaseModel):
    model_config = ConfigDict(extra="allow")

    rules_version: str
    paragraph_gates: List[ParagraphGate]
    record_rules: List[RecordRule]
    legal_status_display: dict[str, dict[str, Any]]
    missing_legal_status_as: str


# --------------------------------------------------------------------------------------------------
# rules/classification_rules.yaml   (how the classifier MATCHES; owned by stage 5)
# --------------------------------------------------------------------------------------------------
class UnitSettings(StrictModel):
    paragraph_strategy: Literal["section", "chunk"]
    min_record_chars: int = Field(ge=0, description="Shorter units are headings/fragments: not_a_record")
    max_unit_chars: int = Field(ge=200)
    chunk_target_chars: int = Field(ge=200)
    skip_block_types: List[str]
    languages: List[str] = Field(description="Blocks in other languages are skipped; blocks without a language are kept")


class Thresholds(StrictModel):
    table_accept: float = Field(ge=0, le=1)
    table_candidate: float = Field(ge=0, le=1)
    paragraph_accept: float = Field(ge=0, le=1)
    paragraph_candidate: float = Field(ge=0, le=1)
    conflict_margin: float = Field(ge=0, le=1)


class ContextCue(StrictModel):
    id: str
    label: str
    patterns: List[str] = Field(min_length=1, description="Any pattern matching the context adds the weight once")
    exclude: List[str] = Field(default_factory=list)
    weight: float = Field(gt=0, le=1)


class TableMatching(StrictModel):
    fuzzy_min_ratio: float = Field(ge=0.5, le=1)
    containment_min_chars: int = Field(ge=3)
    min_matched_columns: int = Field(ge=1)
    min_coverage: float = Field(ge=0, le=1, description="Share of a layout's required columns that must be found")
    coverage_weight: float = Field(ge=0, le=1)
    concept_score_cap: float = Field(ge=0, le=1, description="Max score from expected_concepts (descriptive-only archetypes)")
    context_cues: List[ContextCue]


class ParagraphRule(StrictModel):
    id: str
    label: str
    weight: float = Field(gt=0, le=1)
    require: List[List[str]] = Field(min_length=1, description="Every group must match at least one of its patterns")
    exclude: List[str] = Field(default_factory=list, description="Any match vetoes the rule")
    note: Optional[str] = None


class LegalStatusRule(StrictModel):
    id: str
    status: LegalStatus
    patterns: List[str] = Field(min_length=1)
    exclude: List[str] = Field(default_factory=list)


class Conflict(StrictModel):
    labels: List[str] = Field(min_length=2)
    reason: str


class LLMSettings(StrictModel):
    prompt_version: str
    max_unit_chars: int = Field(ge=500)
    context_chars: int = Field(ge=0)
    table_sample_rows: int = Field(ge=1)
    confidence_map: dict[Literal["high", "medium", "low"], float]
    min_confidence: float = Field(ge=0, le=1, description="LLM labels below this go to review")


class ClassificationRules(StrictModel):
    classification_rules_version: str
    units: UnitSettings
    thresholds: Thresholds
    table_matching: TableMatching
    paragraph_rules: List[ParagraphRule]
    paragraph_context_cues: List[ContextCue] = Field(default_factory=list)
    legal_status_rules: List[LegalStatusRule]
    conflicts: List[Conflict] = Field(default_factory=list)
    llm: LLMSettings


# --------------------------------------------------------------------------------------------------
# Cross-file validation
# --------------------------------------------------------------------------------------------------
class RuleSet(BaseModel):
    """Every rule file, validated together."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    meta: Meta
    tables: TablesFile
    paragraphs: ParagraphsFile
    usability: UsabilityRules
    classification: ClassificationRules

    @model_validator(mode="after")
    def _cross_check(self) -> "RuleSet":
        problems: List[str] = []
        table_ids = [t.id for t in self.tables.tables]
        paragraph_ids = [p.id for p in self.paragraphs.paragraphs]
        decision_ids = {d.id for d in self.meta.open_decisions}
        retired = {old for p in self.paragraphs.paragraphs for old in p.replaces}
        _duplicates("table archetype", table_ids, problems)
        _duplicates("paragraph archetype", paragraph_ids, problems)
        layout_ids: List[str] = []
        for table in self.tables.tables:
            for layout in table.layouts:
                layout_ids.append(layout.layout_id)
                if not layout.layout_id.startswith(f"{table.id}."):
                    problems.append(f"layout {layout.layout_id} must start with '{table.id}.'")
            local = {layout.layout_id for layout in table.layouts}
            for layout in table.layouts:
                if layout.inherits and layout.inherits not in local:
                    problems.append(f"{layout.layout_id} inherits {layout.inherits}, not a layout of {table.id}")
                if not layout.columns and not layout.inherits:
                    problems.append(f"{layout.layout_id} has no columns")
            if table.matchable and not table.layouts:
                problems.append(f"table {table.id} is matchable but has no layouts")
            problems.extend(f"table {table.id}: unknown decision {ref}" for ref in table.decision_refs if ref not in decision_ids)
        _duplicates("layout", layout_ids, problems)
        for table in self.tables.tables:
            for layout in table.layouts:
                problems.extend(
                    f"{layout.layout_id}: ambiguous_with unknown layout {other}"
                    for other in layout.ambiguous_with if other not in layout_ids
                )
        vocabulary = set(self.meta.field_vocabulary)
        for paragraph in self.paragraphs.paragraphs:
            problems.extend(f"{paragraph.id}: maps_to_tables unknown {t}" for t in paragraph.maps_to_tables if t not in table_ids)
            problems.extend(f"{paragraph.id}: unknown field {f}" for f in paragraph.extraction_fields if f not in vocabulary)
            for relation in paragraph.relations:
                problems.extend(f"{paragraph.id}: relation to unknown {t}" for t in relation.targets if t not in paragraph_ids)
            problems.extend(f"{paragraph.id}: unknown decision {ref}" for ref in paragraph.decision_refs if ref not in decision_ids)
            problems.extend(f"{paragraph.id}: replaces an active ID {old}" for old in paragraph.replaces if old in paragraph_ids)
        coverage: dict[str, int] = {}
        for gate in self.usability.paragraph_gates:
            for target in gate.applies_to:
                if target not in paragraph_ids:
                    problems.append(f"gate {gate.id}: unknown paragraph {target}")
                coverage[target] = coverage.get(target, 0) + 1
        problems.extend(f"{p} is covered by {coverage.get(p, 0)} gates, expected 1" for p in paragraph_ids if coverage.get(p, 0) != 1)
        for rule in self.usability.record_rules:
            problems.extend(f"{rule.id}: unknown table {t}" for t in rule.applies_to_tables if t not in table_ids)
            problems.extend(f"{rule.id}: unknown paragraph {p}" for p in rule.applies_to_paragraphs if p not in paragraph_ids)
        legal_keys = set(self.usability.legal_status_display)
        enum_values = {status.value for status in LegalStatus}
        if legal_keys != enum_values:
            problems.append(f"legal_status_display keys {sorted(legal_keys ^ enum_values)} differ from the LegalStatus enum")
        classification = self.classification
        for cue in classification.table_matching.context_cues:
            if cue.label not in table_ids:
                problems.append(f"table cue {cue.id}: unknown table {cue.label}")
        for rule in classification.paragraph_rules:
            if rule.label not in paragraph_ids:
                problems.append(f"paragraph rule {rule.id}: unknown paragraph {rule.label}" + (" (retired)" if rule.label in retired else ""))
        for cue in classification.paragraph_context_cues:
            if cue.label not in paragraph_ids:
                problems.append(f"paragraph cue {cue.id}: unknown paragraph {cue.label}")
        problems.extend(f"no paragraph rule produces {p}" for p in paragraph_ids if not any(r.label == p for r in classification.paragraph_rules))
        known_labels = set(table_ids) | set(paragraph_ids)
        for conflict in classification.conflicts:
            problems.extend(f"conflict lists unknown label {label}" for label in conflict.labels if label not in known_labels)
        rule_ids = [r.id for r in classification.paragraph_rules] + [c.id for c in classification.table_matching.context_cues]
        rule_ids += [c.id for c in classification.paragraph_context_cues] + [r.id for r in classification.legal_status_rules]
        _duplicates("classification rule id", rule_ids, problems)
        for pattern in _all_patterns(classification):
            try:
                re.compile(pattern)
            except re.error as error:
                problems.append(f"invalid regex {pattern!r}: {error}")
        if problems:
            raise ValueError("rule files are inconsistent:\n  - " + "\n  - ".join(problems))
        return self


def _duplicates(kind: str, values: List[str], problems: List[str]) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            problems.append(f"duplicate {kind} {value}")
        seen.add(value)


def _all_patterns(rules: ClassificationRules) -> List[str]:
    patterns: List[str] = []
    for cue in rules.table_matching.context_cues + rules.paragraph_context_cues:
        patterns += cue.patterns + cue.exclude
    for rule in rules.paragraph_rules:
        patterns += [p for group in rule.require for p in group] + rule.exclude
    for rule in rules.legal_status_rules:
        patterns += rule.patterns + rule.exclude
    return patterns
