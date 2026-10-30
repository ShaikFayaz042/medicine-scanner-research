"""Load the rule files once and index them for matching."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Tuple

import yaml

from idp.schemas.taxonomy import (
    ClassificationRules,
    Meta,
    ParagraphArchetype,
    ParagraphsFile,
    RuleSet,
    TableArchetype,
    TablesFile,
    UsabilityRules,
)

DEFAULT_RULES_DIR = Path(__file__).resolve().parents[3] / "rules"
RULE_FILES = {
    "meta": "taxonomy/meta.yaml",
    "tables": "taxonomy/tables.yaml",
    "paragraphs": "taxonomy/paragraphs.yaml",
    "usability": "usability_rules.yaml",
    "classification": "classification_rules.yaml",
}
_NON_ALNUM = re.compile(r"[^a-z0-9]")
# Record-rule actions that the parser must apply row by row.
SPLIT_ACTIONS = {"split_by_record_type", "filter_by_product_type", "select_subset", "require_distinct_status"}


def compact(text: str) -> str:
    """Header normal form: lower-case letters and digits only ("S. N o" == "sno")."""
    return _NON_ALNUM.sub("", text.lower())


def _compile(patterns: List[str]) -> List[Pattern[str]]:
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


@dataclass(frozen=True)
class CompiledColumn:
    canonical: str
    aliases: frozenset
    optional: bool
    generic: bool


@dataclass(frozen=True)
class CompiledLayout:
    archetype: str
    layout_id: str
    columns: Tuple[CompiledColumn, ...]
    composites: Tuple[Tuple[frozenset, Tuple[str, ...]], ...]
    ambiguous_with: Tuple[str, ...]

    @property
    def required(self) -> Tuple[CompiledColumn, ...]:
        return tuple(c for c in self.columns if not c.optional and not c.generic)


@dataclass(frozen=True)
class CompiledCue:
    id: str
    label: str
    weight: float
    patterns: Tuple[Pattern[str], ...]
    exclude: Tuple[Pattern[str], ...]


@dataclass(frozen=True)
class CompiledParagraphRule:
    id: str
    label: str
    weight: float
    require: Tuple[Tuple[Pattern[str], ...], ...]
    exclude: Tuple[Pattern[str], ...]


@dataclass(frozen=True)
class CompiledLegalRule:
    id: str
    status: str
    patterns: Tuple[Pattern[str], ...]
    exclude: Tuple[Pattern[str], ...]


@dataclass
class Taxonomy:
    rules: RuleSet
    rules_dir: Path
    rules_sha256: str
    tables: Dict[str, TableArchetype] = field(default_factory=dict)
    paragraphs: Dict[str, ParagraphArchetype] = field(default_factory=dict)
    layouts: List[CompiledLayout] = field(default_factory=list)
    concept_aliases: Dict[str, frozenset] = field(default_factory=dict)
    generic_aliases: frozenset = frozenset()
    table_cues: List[CompiledCue] = field(default_factory=list)
    paragraph_cues: List[CompiledCue] = field(default_factory=list)
    paragraph_rules: List[CompiledParagraphRule] = field(default_factory=list)
    legal_rules: List[CompiledLegalRule] = field(default_factory=list)
    conflicts: List[Tuple[frozenset, str]] = field(default_factory=list)

    @property
    def classification(self) -> ClassificationRules:
        return self.rules.classification

    @property
    def versions(self) -> Dict[str, str]:
        return {
            "taxonomy": self.rules.meta.taxonomy_version,
            "usability_rules": self.rules.usability.rules_version,
            "classification_rules": self.rules.classification.classification_rules_version,
        }

    def gate_ids(self, paragraph_label: str) -> List[str]:
        return [gate.id for gate in self.rules.usability.paragraph_gates if paragraph_label in gate.applies_to]

    def record_rules(self, label: str, kind: str) -> List[Tuple[str, str]]:
        """(rule id, action) of the record rules that apply to a table or paragraph label."""
        rules = []
        for rule in self.rules.usability.record_rules:
            targets = rule.applies_to_tables if kind == "table" else rule.applies_to_paragraphs
            if label in targets:
                rules.append((rule.id, rule.action))
        return rules


def load_rules(rules_dir: Optional[Path] = None) -> Tuple[RuleSet, Path]:
    root = Path(rules_dir) if rules_dir else DEFAULT_RULES_DIR
    data = {name: yaml.safe_load((root / relative).read_text(encoding="utf-8")) for name, relative in RULE_FILES.items()}
    ruleset = RuleSet(
        meta=Meta.model_validate(data["meta"]),
        tables=TablesFile.model_validate(data["tables"]),
        paragraphs=ParagraphsFile.model_validate(data["paragraphs"]),
        usability=UsabilityRules.model_validate(data["usability"]),
        classification=ClassificationRules.model_validate(data["classification"]),
    )
    return ruleset, root


def rules_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in sorted(RULE_FILES.values()):
        digest.update(relative.encode("utf-8"))
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def load_taxonomy(rules_dir: Optional[Path] = None) -> Taxonomy:
    ruleset, root = load_rules(rules_dir)
    taxonomy = Taxonomy(rules=ruleset, rules_dir=root, rules_sha256=rules_sha256(root))
    taxonomy.tables = {t.id: t for t in ruleset.tables.tables}
    taxonomy.paragraphs = {p.id: p for p in ruleset.paragraphs.paragraphs}
    generic = {compact(name) for name in ruleset.meta.generic_columns}
    generic_aliases = set(generic)
    concept_aliases: Dict[str, set] = {}

    for table in ruleset.tables.tables:
        by_id = {layout.layout_id: layout for layout in table.layouts}
        for layout in table.layouts:
            columns = list(by_id[layout.inherits].columns) if layout.inherits else []
            names = {c.canonical for c in layout.columns}
            columns = [c for c in columns if c.canonical not in names] + list(layout.columns)
            compiled = []
            for column in columns:
                aliases = {compact(column.canonical.replace("_", " "))} | {compact(v) for v in column.variants}
                aliases.discard("")
                is_generic = compact(column.canonical) in generic or bool(aliases & generic)
                compiled.append(CompiledColumn(column.canonical, frozenset(aliases), column.optional, is_generic))
                if is_generic:
                    generic_aliases.update(aliases)
                else:
                    concept_aliases.setdefault(column.canonical, set()).update(aliases)
            composites = tuple(
                (frozenset(compact(v) for v in cell.header_variants), tuple(cell.split_into))
                for cell in layout.composite_cells
            )
            if table.matchable:
                taxonomy.layouts.append(
                    CompiledLayout(table.id, layout.layout_id, tuple(compiled), composites, tuple(layout.ambiguous_with))
                )
    taxonomy.concept_aliases = {name: frozenset(aliases) for name, aliases in concept_aliases.items()}
    taxonomy.generic_aliases = frozenset(generic_aliases)

    classification = ruleset.classification
    taxonomy.table_cues = [
        CompiledCue(c.id, c.label, c.weight, tuple(_compile(c.patterns)), tuple(_compile(c.exclude)))
        for c in classification.table_matching.context_cues
    ]
    taxonomy.paragraph_cues = [
        CompiledCue(c.id, c.label, c.weight, tuple(_compile(c.patterns)), tuple(_compile(c.exclude)))
        for c in classification.paragraph_context_cues
    ]
    taxonomy.paragraph_rules = [
        CompiledParagraphRule(
            r.id, r.label, r.weight, tuple(tuple(_compile(group)) for group in r.require), tuple(_compile(r.exclude))
        )
        for r in classification.paragraph_rules
    ]
    taxonomy.legal_rules = [
        CompiledLegalRule(r.id, r.status.value, tuple(_compile(r.patterns)), tuple(_compile(r.exclude)))
        for r in classification.legal_status_rules
    ]
    taxonomy.conflicts = [(frozenset(c.labels), c.reason) for c in classification.conflicts]
    return taxonomy
