"""Stage 5: classify every table and paragraph unit of a structured document.

    rules  ->  accepted labels                         (status: classified)
           ->  escalate: no match / conflict / low confidence
                  ->  LLM labels, validated            (status: classified, or needs_review)
                  ->  no provider / invalid answer     (status: needs_review, rule candidates kept)

`Classifier.classify` is pure (no I/O); `classify_uri` reads a stage-4 JSON and writes the result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from idp.models.llm import LLMProvider
from idp.schemas.classified import (
    Candidate,
    ClassifiedDocument,
    ClassifiedUnit,
    Escalation,
    Evidence,
    Label,
    LLMInfo,
    Summary,
    UnitSource,
    Versions,
)
from idp.schemas.common import LegalStatus
from idp.schemas.structured import StructuredDocument
from idp.stages.classifier.llm_fallback import LLMClassifier, ResponseCache
from idp.stages.classifier.matcher import (
    ParagraphCandidate,
    TableCandidate,
    detect_legal_status,
    match_paragraph,
    match_table,
)
from idp.stages.classifier.resolver import resolve_paragraph, resolve_table
from idp.stages.classifier.taxonomy import Taxonomy, load_taxonomy
from idp.stages.classifier.units import ParagraphUnit, TableUnit, collapse, paragraph_units, table_units
from idp.stages.classifier.usability import build_label, requires_record_split

CLASSIFIER_VERSION = "1.0.0"
PREVIEW_CHARS = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Classifier:
    def __init__(
        self,
        taxonomy: Optional[Taxonomy] = None,
        provider: Optional[LLMProvider] = None,
        cache: Optional[ResponseCache] = None,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.taxonomy = taxonomy or load_taxonomy()
        self.provider = provider
        self.llm = LLMClassifier(self.taxonomy, provider, cache)
        self.clock = clock

    # ------------------------------------------------------------------ document
    def classify(self, document: StructuredDocument) -> ClassifiedDocument:
        settings = self.taxonomy.classification
        units: List[ClassifiedUnit] = [self._table(unit) for unit in table_units(document)]
        units += [self._paragraph(unit) for unit in paragraph_units(document, settings.units, settings.llm.context_chars)]
        versions = self.taxonomy.versions
        return ClassifiedDocument(
            document_id=document.document.document_id,
            document_sha256=document.document.sha256,
            title=document.document.title,
            created_at=self.clock(),
            versions=Versions(
                taxonomy=versions["taxonomy"],
                usability_rules=versions["usability_rules"],
                classification_rules=versions["classification_rules"],
                rules_sha256=self.taxonomy.rules_sha256,
                classifier=CLASSIFIER_VERSION,
            ),
            llm=LLMInfo(provider=self.provider.name, model=self.provider.model, prompt_version=settings.llm.prompt_version)
            if self.provider else None,
            units=units,
            summary=_summary(units),
        )

    # ------------------------------------------------------------------ tables
    def _table(self, unit: TableUnit) -> ClassifiedUnit:
        candidates = match_table(unit, self.taxonomy)
        decision = resolve_table(candidates, self.taxonomy)
        record = ClassifiedUnit(
            unit_id=unit.unit_id,
            kind="table",
            source=UnitSource(pages=unit.pages, table_id=unit.table.table_id, heading_path=list(unit.table.heading_path)),
            text_preview=collapse(unit.text)[:PREVIEW_CHARS],
            status="classified",
            candidates=[Candidate(label=c.label, score=c.score, rule_ids=c.rule_ids, layout_id=c.layout_id) for c in candidates[:5]],
        )
        if decision.accepted:
            best = decision.accepted[0]
            record.labels = [build_label(self.taxonomy, best.label, "table", best.score, "rule", best.rule_ids,
                                         self._table_evidence(best, unit), best.layout_id)]
        else:
            outcome = self.llm.classify_table(unit, candidates, decision.escalate)
            self._apply_outcome(record, outcome, fallback=[], conflict_notes=decision.conflict_notes)
        record.requires_record_split = requires_record_split(self.taxonomy, record.labels, "table")
        return record

    def _table_evidence(self, candidate: TableCandidate, unit: TableUnit) -> List[Evidence]:
        kind = "concept_match" if candidate.method == "concepts" else "header_match"
        evidence = [
            Evidence(kind=kind, text=header, rule_id=candidate.rule_ids[0] if candidate.rule_ids else None,
                     detail={"canonical": name, "header_source": candidate.header_source})
            for name, header in candidate.matched.items()
        ]
        for cue in self.taxonomy.table_cues:
            if cue.id in candidate.cue_ids:
                match = next((m for m in (p.search(unit.context) for p in cue.patterns) if m), None)
                if match:
                    evidence.append(Evidence(kind="context_cue", text=match.group(0), rule_id=cue.id))
        return evidence

    # ------------------------------------------------------------------ paragraphs
    def _paragraph(self, unit: ParagraphUnit) -> ClassifiedUnit:
        settings = self.taxonomy.classification
        record = ClassifiedUnit(
            unit_id=unit.unit_id,
            kind="paragraph",
            source=UnitSource(pages=unit.pages, block_ids=[b.block_id for b in unit.blocks], heading_path=list(unit.heading_path)),
            text_preview=collapse(unit.text)[:PREVIEW_CHARS],
            status="classified",
        )
        if unit.body_chars < settings.units.min_record_chars:
            record.status = "not_a_record"
            return record
        candidates = match_paragraph(unit, self.taxonomy)
        record.candidates = [Candidate(label=c.label, score=c.score, rule_ids=c.rule_ids + c.cue_ids) for c in candidates]
        status, rule_id = detect_legal_status(unit.text, self.taxonomy)
        record.legal_status, record.legal_status_rule_id = LegalStatus(status), rule_id
        decision = resolve_paragraph(candidates, self.taxonomy)
        rule_labels = [self._paragraph_label(c) for c in decision.accepted]
        if not decision.escalate:
            record.labels = rule_labels
        else:
            outcome = self.llm.classify_paragraph(unit, candidates, decision.escalate)
            self._apply_outcome(record, outcome, fallback=rule_labels, conflict_notes=decision.conflict_notes)
            if outcome.legal_status and outcome.labels:
                record.legal_status = LegalStatus(outcome.legal_status)
                record.legal_status_rule_id = f"LLM:{settings.llm.prompt_version}"
        record.requires_record_split = requires_record_split(self.taxonomy, record.labels, "paragraph")
        return record

    def _paragraph_label(self, candidate: ParagraphCandidate) -> Label:
        evidence = [
            Evidence(kind="pattern_match", text=m.text, rule_id=m.rule_id, char_span=m.span, detail={"snippet": m.snippet})
            for m in candidate.matches
        ]
        evidence += [Evidence(kind="context_cue", text=cue_id, rule_id=cue_id) for cue_id in candidate.cue_ids]
        return build_label(self.taxonomy, candidate.label, "paragraph", candidate.score, "rule",
                           candidate.rule_ids + candidate.cue_ids, evidence)

    # ------------------------------------------------------------------ shared
    @staticmethod
    def _apply_outcome(record: ClassifiedUnit, outcome, fallback: List[Label], conflict_notes: List[str]) -> None:
        record.escalation = outcome.escalation
        if outcome.escalation and conflict_notes:
            detail = "; ".join(conflict_notes)
            record.escalation.detail = f"{record.escalation.detail}; {detail}" if record.escalation.detail else detail
        record.review_reasons = list(outcome.review_reasons)
        if outcome.labels:
            record.labels = outcome.labels
        elif not outcome.is_record:
            record.status = "not_a_record"
            return
        else:
            # No usable model answer: keep the rule labels (if any) for the reviewer.
            record.labels = fallback
            record.review_reasons += [f"escalated:{reason}" for reason in (outcome.escalation.reasons if outcome.escalation else [])]
        if record.review_reasons:
            record.status = "needs_review"


def _summary(units: List[ClassifiedUnit]) -> Summary:
    by_status: dict = {}
    by_class: dict = {}
    for unit in units:
        by_status[unit.status] = by_status.get(unit.status, 0) + 1
        for app_class in {label.app_classification for label in unit.labels}:
            by_class[app_class] = by_class.get(app_class, 0) + 1
    return Summary(
        units=len(units),
        by_status=by_status,
        by_app_classification=by_class,
        escalated=sum(1 for unit in units if unit.escalation is not None),
    )


def output_name(input_name: str) -> str:
    """'<doc>.json' / '<doc>.structured.json' -> '<doc>.classified.json'."""
    stem = input_name[:-5] if input_name.lower().endswith(".json") else input_name
    stem = stem[: -len(".structured")] if stem.endswith(".structured") else stem
    return f"{stem}.classified.json"


def classify_uri(classifier: Classifier, input_uri: str, output_dir: str) -> Tuple[str, ClassifiedDocument]:
    """Read one stage-4 JSON (local path or s3://), classify it, write the stage-5 JSON next to `output_dir`."""
    from idp.storage.artifacts import join, read_json, write_json

    document = StructuredDocument.model_validate(read_json(input_uri))
    result = classifier.classify(document)
    target = join(output_dir, output_name(input_uri.replace("\\", "/").rsplit("/", 1)[-1]))
    write_json(target, result.model_dump(mode="json"))
    return target, result
