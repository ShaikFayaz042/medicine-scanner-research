"""Deterministic matching: table headers against layouts, paragraph text against rules, legal status."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence, Tuple

from idp.stages.classifier.taxonomy import CompiledCue, CompiledLayout, Taxonomy, compact
from idp.stages.classifier.units import ParagraphUnit, TableUnit, collapse


# --------------------------------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------------------------------
@dataclass
class TableCandidate:
    label: str
    score: float
    header_score: float = 0.0
    context_bonus: float = 0.0
    layout_id: Optional[str] = None
    method: str = "header"  # header | concepts | context
    matched: Dict[str, str] = field(default_factory=dict)  # canonical -> header text
    cue_ids: List[str] = field(default_factory=list)
    header_source: str = "header_rows"  # or body_row_N when stage 4 delivered no header row

    @property
    def rule_ids(self) -> List[str]:
        ids = [f"HDR:{self.layout_id}"] if self.layout_id else [f"CONCEPTS:{self.label}"] if self.method == "concepts" else []
        return ids + self.cue_ids


def _alias_score(cell: str, alias: str, min_chars: int, fuzzy_min: float) -> float:
    if cell == alias:
        return 1.0
    if len(alias) >= min_chars and alias in cell:
        return 0.85  # "nameofdrugsmedicaldevicecosmetics" contains "nameofdrugs"
    if len(cell) >= min_chars and cell in alias and len(cell) / len(alias) >= 0.6:
        return 0.8   # truncated header: "batchn" in "batchno"
    ratio = SequenceMatcher(None, cell, alias).ratio()
    return ratio * 0.95 if ratio >= fuzzy_min else 0.0


def _best_alias_score(cell: str, aliases, min_chars: int, fuzzy_min: float) -> float:
    return max((_alias_score(cell, alias, min_chars, fuzzy_min) for alias in aliases), default=0.0)


def _is_generic(cell: str, taxonomy: Taxonomy) -> bool:
    return cell in taxonomy.generic_aliases or any(
        len(cell) <= 6 and SequenceMatcher(None, cell, alias).ratio() >= 0.85 for alias in taxonomy.generic_aliases
    )


def _score_layout(cells: List[Tuple[str, str]], layout: CompiledLayout, taxonomy: Taxonomy) -> Optional[TableCandidate]:
    settings = taxonomy.classification.table_matching
    columns = [c for c in layout.columns if not c.generic]
    required = [c for c in columns if not c.optional] or columns
    if not required:
        return None
    pairs: List[Tuple[float, int, str]] = []  # (score, cell index, canonical)
    for index, (raw, cell) in enumerate(cells):
        for column in columns:
            score = _best_alias_score(cell, column.aliases, settings.containment_min_chars, settings.fuzzy_min_ratio)
            if score:
                pairs.append((score, index, column.canonical))
        for aliases, split_into in layout.composites:
            score = _best_alias_score(cell, aliases, settings.containment_min_chars, settings.fuzzy_min_ratio)
            if score:
                pairs.append((score + 0.01, index, "|".join(split_into)))  # prefer the composite reading
    pairs.sort(reverse=True)
    used_cells: set = set()
    matched: Dict[str, Tuple[float, str]] = {}
    for score, index, target in pairs:
        targets = target.split("|")
        if index in used_cells or any(t in matched for t in targets):
            continue
        used_cells.add(index)
        for t in targets:
            matched[t] = (score, cells[index][0])
    required_names = {c.canonical for c in required}
    found = [matched[name][0] for name in required_names if name in matched]
    if len(found) < min(settings.min_matched_columns, len(required_names)):
        return None
    coverage = sum(found) / len(required_names)
    if coverage < settings.min_coverage:
        return None  # two date columns do not make an NSQ table
    precision = len(used_cells) / max(len(cells), 1)
    score = coverage * settings.coverage_weight + precision * (1 - settings.coverage_weight)
    return TableCandidate(
        label=layout.archetype,
        score=round(score, 4),
        header_score=round(score, 4),
        layout_id=layout.layout_id,
        matched={name: header for name, (_, header) in matched.items()},
    )


def _cue_hits(cues: Sequence[CompiledCue], label: str, text: str) -> List[CompiledCue]:
    hits = []
    for cue in cues:
        if cue.label != label:
            continue
        if any(p.search(text) for p in cue.patterns) and not any(p.search(text) for p in cue.exclude):
            hits.append(cue)
    return hits


def _header_candidates(source: str, header: List[str], taxonomy: Taxonomy) -> List[TableCandidate]:
    settings = taxonomy.classification.table_matching
    cells = [(raw, compact(raw)) for raw in header if compact(raw)]
    content_cells = [(raw, cell) for raw, cell in cells if not _is_generic(cell, taxonomy)]
    found: Dict[str, TableCandidate] = {}
    for layout in taxonomy.layouts:
        candidate = _score_layout(content_cells, layout, taxonomy)
        if candidate and candidate.score > found.get(candidate.label, TableCandidate(candidate.label, -1)).score:
            found[candidate.label] = candidate

    # Archetypes without exact columns (AV, AS): how many of their expected concepts the headers show.
    for archetype in taxonomy.tables.values():
        if archetype.matchable or not archetype.expected_concepts or archetype.id in found:
            continue
        known = [c for c in archetype.expected_concepts if c in taxonomy.concept_aliases]
        if not known:
            continue
        matched = {}
        for concept in known:
            for raw, cell in content_cells:
                if _best_alias_score(cell, taxonomy.concept_aliases[concept], settings.containment_min_chars, settings.fuzzy_min_ratio) >= 0.8:
                    matched[concept] = raw
                    break
        if len(matched) >= min(settings.min_matched_columns, len(known)):
            score = len(matched) / len(archetype.expected_concepts) * settings.concept_score_cap
            found[archetype.id] = TableCandidate(archetype.id, round(score, 4), round(score, 4), method="concepts", matched=matched)
    for candidate in found.values():
        candidate.header_source = source
    return list(found.values())


def match_table(unit: TableUnit, taxonomy: Taxonomy) -> List[TableCandidate]:
    """Best candidate per archetype, highest score first."""
    settings = taxonomy.classification
    best: Dict[str, TableCandidate] = {}
    for source, header in unit.header_candidates():
        for candidate in _header_candidates(source, header, taxonomy):
            if candidate.score > best.get(candidate.label, TableCandidate(candidate.label, -1)).score:
                best[candidate.label] = candidate

    # Context cues (title, headings, caption): a bonus for archetypes the headers support; otherwise only
    # a weak nomination that can never be accepted without the LLM.
    for label in {cue.label for cue in taxonomy.table_cues}:
        hits = _cue_hits(taxonomy.table_cues, label, unit.context)
        if not hits:
            continue
        bonus = min(sum(cue.weight for cue in hits), 0.2)
        candidate = best.get(label)
        if candidate and candidate.header_score >= settings.thresholds.table_candidate:
            candidate.context_bonus = bonus
            # Not capped at 1: a perfect header match plus a title cue must still beat a perfect match without one.
            candidate.score = round(candidate.header_score + bonus, 4)
            candidate.cue_ids = [cue.id for cue in hits]
        elif candidate is None:
            best[label] = TableCandidate(label, round(bonus, 4), method="context", context_bonus=bonus, cue_ids=[c.id for c in hits])
    return sorted(best.values(), key=lambda c: c.score, reverse=True)


# --------------------------------------------------------------------------------------------------
# Paragraphs
# --------------------------------------------------------------------------------------------------
@dataclass
class Match:
    rule_id: str
    text: str
    span: Tuple[int, int]
    snippet: str


@dataclass
class ParagraphCandidate:
    label: str
    score: float
    rule_ids: List[str] = field(default_factory=list)
    matches: List[Match] = field(default_factory=list)
    cue_ids: List[str] = field(default_factory=list)
    content_supported: bool = True


def _snippet(text: str, start: int, end: int, width: int = 80) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    return ("…" if left else "") + text[left:right] + ("…" if right < len(text) else "")


def match_paragraph(unit: ParagraphUnit, taxonomy: Taxonomy) -> List[ParagraphCandidate]:
    text = collapse(unit.text)
    fired: Dict[str, ParagraphCandidate] = {}
    for rule in taxonomy.paragraph_rules:
        if any(p.search(text) for p in rule.exclude):
            continue
        hits: List[Match] = []
        for group in rule.require:
            found = next((m for m in (p.search(text) for p in group) if m), None)
            if not found:
                break
            hits.append(Match(rule.id, found.group(0), found.span(), _snippet(text, *found.span())))
        else:
            candidate = fired.setdefault(rule.label, ParagraphCandidate(rule.label, 0.0))
            candidate.score = 1 - (1 - candidate.score) * (1 - rule.weight)
            candidate.rule_ids.append(rule.id)
            candidate.matches.extend(hits)
    for cue in taxonomy.paragraph_cues:
        if not (any(p.search(unit.context) for p in cue.patterns) and not any(p.search(unit.context) for p in cue.exclude)):
            continue
        candidate = fired.get(cue.label)
        if candidate is None:
            fired[cue.label] = ParagraphCandidate(cue.label, cue.weight, cue_ids=[cue.id], content_supported=False)
        elif cue.id not in candidate.cue_ids:
            if candidate.content_supported:
                candidate.score = 1 - (1 - candidate.score) * (1 - cue.weight)
            candidate.cue_ids.append(cue.id)
    for candidate in fired.values():
        candidate.score = round(candidate.score, 4)
    return sorted(fired.values(), key=lambda c: c.score, reverse=True)


def detect_legal_status(text: str, taxonomy: Taxonomy) -> Tuple[str, Optional[str]]:
    """First matching legal-status rule; unclear_from_excerpt when none matches."""
    flat = collapse(text)
    for rule in taxonomy.legal_rules:
        if any(p.search(flat) for p in rule.patterns) and not any(p.search(flat) for p in rule.exclude):
            return rule.status, rule.id
    return taxonomy.rules.usability.missing_legal_status_as, None
