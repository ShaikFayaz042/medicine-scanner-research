"""Decide which rule candidates to accept and when to escalate to the LLM.

Escalation reasons (team decision): no rule matched, rules conflict, or the confidence is below the
threshold. Paragraph units may keep several labels; a table gets one archetype.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import List

from idp.stages.classifier.matcher import ParagraphCandidate, TableCandidate
from idp.stages.classifier.taxonomy import Taxonomy

NO_RULE_MATCH = "no_rule_match"
RULE_CONFLICT = "rule_conflict"
LOW_CONFIDENCE = "low_confidence"


@dataclass
class Decision:
    accepted: List = field(default_factory=list)
    escalate: List[str] = field(default_factory=list)
    conflict_notes: List[str] = field(default_factory=list)


def resolve_table(candidates: List[TableCandidate], taxonomy: Taxonomy) -> Decision:
    thresholds = taxonomy.classification.thresholds
    viable = [c for c in candidates if c.score >= thresholds.table_candidate and c.method != "context"]
    if not viable:
        return Decision(escalate=[NO_RULE_MATCH])
    best = viable[0]
    rivals = [c for c in viable[1:] if c.label != best.label and best.score - c.score < thresholds.conflict_margin]
    if rivals:
        notes = [f"{best.label} {best.score:.2f} vs {r.label} {r.score:.2f}" for r in rivals]
        return Decision(escalate=[RULE_CONFLICT], conflict_notes=notes)
    if best.score < thresholds.table_accept:
        return Decision(escalate=[LOW_CONFIDENCE])
    return Decision(accepted=[best])


def resolve_paragraph(candidates: List[ParagraphCandidate], taxonomy: Taxonomy) -> Decision:
    thresholds = taxonomy.classification.thresholds
    if not candidates:
        return Decision(escalate=[NO_RULE_MATCH])
    accepted = [c for c in candidates if c.content_supported and c.score >= thresholds.paragraph_accept]
    if not accepted:
        return Decision(escalate=[LOW_CONFIDENCE])
    labels = {c.label for c in accepted}
    notes = [
        reason for group, reason in taxonomy.conflicts
        for a, b in combinations(sorted(group), 2) if a in labels and b in labels
    ]
    if notes:
        return Decision(accepted=accepted, escalate=[RULE_CONFLICT], conflict_notes=sorted(set(notes)))
    return Decision(accepted=accepted)
