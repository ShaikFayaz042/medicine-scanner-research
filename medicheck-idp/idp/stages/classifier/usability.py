"""Attach taxonomy facts (class, priority, gates, record rules) to an accepted label.

The classifier only records WHICH gate and record rules apply. Whether a record is ready for direct
matching needs the parsed fields, so stage 7/8 decides it (INV-14: the fields are independent).
P5/P6 are `class_mode: conditional`: they keep their safe default class (future_usable) here and are
promoted later only if their gate passes.
"""

from __future__ import annotations

from typing import List, Optional

from idp.schemas.classified import Evidence, Label
from idp.stages.classifier.taxonomy import SPLIT_ACTIONS, Taxonomy


def build_label(
    taxonomy: Taxonomy,
    label_id: str,
    kind: str,
    confidence: float,
    method: str,
    rule_ids: List[str],
    evidence: List[Evidence],
    layout_id: Optional[str] = None,
) -> Label:
    if kind == "table":
        archetype = taxonomy.tables[label_id]
        class_mode, gates = "fixed", []
    else:
        archetype = taxonomy.paragraphs[label_id]
        class_mode, gates = archetype.class_mode, taxonomy.gate_ids(label_id)
    return Label(
        label=label_id,
        name=archetype.name,
        app_classification=archetype.default_class,
        class_mode=class_mode,
        priority=archetype.priority,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        method=method,
        rule_ids=rule_ids,
        layout_id=layout_id,
        evidence=evidence,
        gate_ids=gates,
        record_rule_ids=[rule_id for rule_id, _ in taxonomy.record_rules(label_id, kind)],
    )


def requires_record_split(taxonomy: Taxonomy, labels: List[Label], kind: str) -> bool:
    """True when a record rule must be applied row by row (mixed products, C split, K statuses)."""
    return any(action in SPLIT_ACTIONS for label in labels for _, action in taxonomy.record_rules(label.label, kind))
