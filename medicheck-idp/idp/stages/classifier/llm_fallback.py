"""LLM fallback for units the rules cannot settle (no match, conflicting labels, low confidence).

Provider-neutral: prompts, the reply schema, validation and caching live here; idp.models.* only send
the request. Every model answer is checked before it is used:

- labels must be real taxonomy IDs from the offered catalogue;
- every label needs an evidence quote that occurs verbatim (whitespace/case-insensitive) in the unit;
- confidence below `llm.min_confidence` keeps the label but sends the unit to review.

The model never sees file names (team decision); it does see the document title, as content.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, ValidationError

from idp.models.llm import LLMError, LLMProvider, LLMRequest
from idp.schemas.classified import Escalation, Evidence, Label
from idp.schemas.common import LegalStatus
from idp.stages.classifier.taxonomy import Taxonomy
from idp.stages.classifier.units import ParagraphUnit, TableUnit, collapse
from idp.stages.classifier.usability import build_label

_QUOTE_NOISE = re.compile(r"[\s\"'“”‘’`…]+")

SYSTEM_PREAMBLE = """You classify one unit of an Indian drug-regulatory document (CDSCO alerts, Gazette notifications, PvPI alerts, public notices) for MediCheck, an app that checks medicines against official findings.

A unit is either a table or a passage of prose. Assign the archetype labels that the TARGET text itself supports, from the catalogue below only.

Rules:
- Use several labels only when the unit contains several distinct records or statements (e.g. a notification that prohibits some FDCs and restricts others: P3 and P3b).
- Decide from the operative wording. Never infer legal effect from the title, a heading, or the fact that a medicine is mentioned.
- A product-specific action (prohibition, restriction, conditional permission, advisory) is labelled by its action even when it is only proposed; record the proposal in legal_status (draft_or_proposed_explicitly_stated). P29 is only for rule changes or policy proposals that name no product-specific action.
- A PvPI adverse-reaction alert is not a recall or a prohibition. WHO-origin falsified-product alerts are P6, not P1. Aggregate or brand-level survey findings are P19, never a batch finding.
- Procedures, forms, checklists, meetings, appointments and informational notices take their non-usable labels.
- is_record is false only for fragments with no content of their own (letterheads, addresses, salutations, signatures, page marks, tables of contents with no data); then return no labels.
- evidence_quote must be copied exactly from the TARGET (not from the context or hints), one short span (under 300 characters) that shows why the label applies.
- confidence: high = the wording is explicit; medium = clear but indirect; low = a reasonable guess.
"""

TABLE_NOTE = """For tables, return exactly one label: the archetype whose columns and content this table holds. Use NU for an administrative, procedural or technical table that fits none of the listed archetypes."""


class ReplyLabel(BaseModel):
    label: str
    evidence_quote: str = ""
    confidence: str = "low"


class Reply(BaseModel):
    is_record: bool = True
    labels: List[ReplyLabel] = []
    legal_status: Optional[str] = None


class ResponseCache(Protocol):
    def get(self, key: str) -> Optional[Dict[str, Any]]: ...

    def put(self, key: str, value: Dict[str, Any]) -> None: ...


class FileCache:
    """One JSON file per answer. Point it at a mounted volume or sync it to S3 between runs."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        path = self.directory / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def put(self, key: str, value: Dict[str, Any]) -> None:
        (self.directory / f"{key}.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@dataclass
class LLMOutcome:
    labels: List[Label] = field(default_factory=list)
    legal_status: Optional[str] = None
    is_record: bool = True
    escalation: Optional[Escalation] = None
    review_reasons: List[str] = field(default_factory=list)


def _normalise_for_quote(text: str) -> str:
    return _QUOTE_NOISE.sub(" ", text).strip().lower()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[TRUNCATED]"


class LLMClassifier:
    def __init__(self, taxonomy: Taxonomy, provider: Optional[LLMProvider], cache: Optional[ResponseCache] = None) -> None:
        self.taxonomy = taxonomy
        self.provider = provider
        self.cache = cache
        self.settings = taxonomy.classification.llm
        self.table_labels = [
            t.id for t in taxonomy.tables.values() if t.default_class != "non_usable" or t.id == "NU"
        ]
        self.paragraph_labels = list(taxonomy.paragraphs)

    # ---------------------------------------------------------------- prompts
    def _table_catalogue(self) -> str:
        lines = []
        for label in self.table_labels:
            table = self.taxonomy.tables[label]
            columns = sorted({c.canonical for layout in table.layouts for c in layout.columns if c.canonical not in ("sno", "sl_no", "serial_no")})
            described = ", ".join(columns) or (table.column_description or "")
            lines.append(f"- {label}: {table.name} [{table.default_class}]. Columns: {described}")
        return "\n".join(lines)

    def _paragraph_catalogue(self) -> str:
        return "\n".join(
            f"- {p.id}: {p.name} [{p.default_class}]. {p.archetype}" for p in self.taxonomy.paragraphs.values()
        )

    @staticmethod
    def _hints(candidates: List[Any]) -> str:
        if not candidates:
            return "none"
        return "; ".join(f"{c.label} (score {c.score:.2f}, rules {', '.join(c.rule_ids) or 'context only'})" for c in candidates[:5])

    def _schema(self, labels: List[str], with_legal_status: bool) -> Dict[str, Any]:
        item = {
            "type": "object",
            "additionalProperties": False,
            "required": ["label", "evidence_quote", "confidence"],
            "properties": {
                "label": {"type": "string", "enum": labels},
                "evidence_quote": {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
        }
        schema: Dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["is_record", "labels"],
            "properties": {"is_record": {"type": "boolean"}, "labels": {"type": "array", "items": item}},
        }
        if with_legal_status:
            schema["required"].append("legal_status")
            schema["properties"]["legal_status"] = {"type": "string", "enum": [s.value for s in LegalStatus]}
        return schema

    # ---------------------------------------------------------------- calls
    def classify_table(self, unit: TableUnit, candidates: List[Any], reasons: List[str]) -> LLMOutcome:
        system = SYSTEM_PREAMBLE + "\n" + TABLE_NOTE + "\n\nTable archetypes:\n" + self._table_catalogue()
        user = "\n".join([
            f"Document title: {unit.title or '(none)'}",
            f"Caption / headings above the table: {' / '.join(filter(None, [*unit.table.heading_path, unit.table.caption or ''])) or '(none)'}",
            f"Rule-based hints (may be wrong; decide from the table): {self._hints(candidates)}",
            "",
            "TARGET TABLE (classify this; quote only from it):",
            "Header: " + (" | ".join(unit.header) or "(no header row detected)"),
            f"First {self.settings.table_sample_rows} rows:",
            _clip(unit.body_text(self.settings.table_sample_rows), self.settings.max_unit_chars),
        ])
        return self._run(unit.text + "\n" + unit.context, "table", system, user, self.table_labels, False, reasons)

    def classify_paragraph(self, unit: ParagraphUnit, candidates: List[Any], reasons: List[str]) -> LLMOutcome:
        system = SYSTEM_PREAMBLE + "\nParagraph archetypes:\n" + self._paragraph_catalogue()
        user = "\n".join([
            f"Document title: {unit.title or '(none)'}",
            f"Heading path: {' > '.join(unit.heading_path) or '(none)'}",
            f"Rule-based hints (may be wrong; decide from the text): {self._hints(candidates)}",
            "",
            "Text before (context only, do not quote):",
            unit.previous_text or "(none)",
            "",
            "TARGET (classify this; quote only from it):",
            "<<<",
            _clip(unit.text, self.settings.max_unit_chars),
            ">>>",
            "",
            "Text after (context only, do not quote):",
            unit.next_text or "(none)",
        ])
        return self._run(unit.text, "paragraph", system, user, self.paragraph_labels, True, reasons)

    def _run(self, source_text: str, kind: str, system: str, user: str, labels: List[str], with_legal: bool, reasons: List[str]) -> LLMOutcome:
        if self.provider is None:
            return LLMOutcome(
                escalation=Escalation(reasons=reasons, outcome="unavailable", detail="no LLM provider configured"),
                review_reasons=["llm_unavailable"],
            )
        schema_name = f"medicheck_{kind}_classification"
        request = LLMRequest(system=system, user=user, json_schema=self._schema(labels, with_legal), schema_name=schema_name)
        key = hashlib.sha256(json.dumps(
            [self.provider.name, self.provider.model, self.settings.prompt_version, schema_name, system, user]
        ).encode("utf-8")).hexdigest()
        escalation = Escalation(
            reasons=reasons, provider=self.provider.name, model=self.provider.model,
            prompt_version=self.settings.prompt_version, outcome="accepted",
        )
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            data, escalation.cached = cached["data"], True
        else:
            try:
                response = self.provider.generate_json(request)
            except LLMError as error:
                escalation.outcome, escalation.detail = "error", str(error)[:500]
                return LLMOutcome(escalation=escalation, review_reasons=["llm_error"])
            data = response.data
            if self.cache:
                self.cache.put(key, {"data": data, "provider": response.provider, "model": response.model})
        return self._validate(data, source_text, kind, labels, escalation)

    def _validate(self, data: Dict[str, Any], source_text: str, kind: str, allowed: List[str], escalation: Escalation) -> LLMOutcome:
        try:
            reply = Reply.model_validate(data)
        except ValidationError as error:
            escalation.outcome, escalation.detail = "rejected", f"reply does not match the schema: {error.errors()[:3]}"
            return LLMOutcome(escalation=escalation, review_reasons=["llm_invalid_reply"])
        outcome = LLMOutcome(escalation=escalation, is_record=reply.is_record)
        haystack = _normalise_for_quote(source_text)
        confidence_map = self.settings.confidence_map
        seen: set = set()
        for item in reply.labels:
            if item.label not in allowed:
                outcome.review_reasons.append(f"llm_unknown_label:{item.label}")
                continue
            quote = collapse(item.evidence_quote)
            if not quote or _normalise_for_quote(quote) not in haystack:
                outcome.review_reasons.append(f"llm_quote_not_in_source:{item.label}")
                continue
            if item.label in seen:
                continue
            seen.add(item.label)
            confidence = confidence_map.get(item.confidence, confidence_map["low"])  # type: ignore[call-overload]
            if confidence < self.settings.min_confidence:
                outcome.review_reasons.append(f"llm_low_confidence:{item.label}")
            outcome.labels.append(build_label(
                self.taxonomy, item.label, kind, confidence, "llm", [f"LLM:{self.settings.prompt_version}"],
                [Evidence(kind="llm_quote", text=quote, detail={"confidence": item.confidence})],
            ))
        if kind == "table" and len(outcome.labels) > 1:
            outcome.labels = sorted(outcome.labels, key=lambda label: label.confidence, reverse=True)[:1]
            outcome.review_reasons.append("llm_multiple_table_labels")
        if reply.legal_status is not None:
            if reply.legal_status in {s.value for s in LegalStatus}:
                outcome.legal_status = reply.legal_status
            else:
                outcome.review_reasons.append("llm_unknown_legal_status")
        if reply.is_record and not outcome.labels:
            escalation.outcome = "rejected"
            outcome.review_reasons.append("llm_no_valid_label")
        return outcome
