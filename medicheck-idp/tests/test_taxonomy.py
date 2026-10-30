"""The rule files load, cross-validate, and reject the mistakes validation exists to catch."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from idp.stages.classifier.taxonomy import DEFAULT_RULES_DIR, RULE_FILES, load_taxonomy


def test_rule_files_load_and_report_versions(taxonomy):
    assert taxonomy.versions == {"taxonomy": "2.1.0", "usability_rules": "2.0.0", "classification_rules": "1.0.0"}
    assert len(taxonomy.rules_sha256) == 64
    assert len(taxonomy.paragraphs) == 31 and "P4" not in taxonomy.paragraphs


def test_approved_taxonomy_changes_are_encoded(taxonomy):
    assert taxonomy.paragraphs["P3"].replaces == ["P4"]                        # DEC-09
    assert "no product-specific operative action" in taxonomy.paragraphs["P29"].archetype  # DEC-10
    nu = taxonomy.tables["NU"]                                                   # DEC-11
    assert (nu.default_class, nu.matchable) == ("non_usable", False)
    assert taxonomy.gate_ids("P3") == ["GATE-P3"]


def test_every_paragraph_label_has_a_gate_and_a_rule(taxonomy):
    for label in taxonomy.paragraphs:
        assert len(taxonomy.gate_ids(label)) == 1, label
        assert any(rule.label == label for rule in taxonomy.paragraph_rules), label


def _copy_rules(tmp_path: Path) -> Path:
    target = tmp_path / "rules"
    shutil.copytree(DEFAULT_RULES_DIR, target)
    return target


def _edit_yaml(path: Path, change) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_rule_pointing_at_an_unknown_label_fails_at_load(tmp_path):
    rules = _copy_rules(tmp_path)
    _edit_yaml(rules / RULE_FILES["classification"], lambda d: d["paragraph_rules"][0].update(label="P4"))

    with pytest.raises(ValueError, match=r"unknown paragraph P4 \(retired\)"):
        load_taxonomy(rules)


def test_invalid_regex_fails_at_load(tmp_path):
    rules = _copy_rules(tmp_path)
    _edit_yaml(rules / RULE_FILES["classification"], lambda d: d["paragraph_rules"][0]["require"][0].append("(unclosed"))

    with pytest.raises(ValueError, match="invalid regex"):
        load_taxonomy(rules)


def test_paragraph_without_a_gate_fails_at_load(tmp_path):
    rules = _copy_rules(tmp_path)
    _edit_yaml(rules / RULE_FILES["usability"], lambda d: d["paragraph_gates"][0]["applies_to"].remove("P1"))

    with pytest.raises(ValueError, match="P1 is covered by 0 gates"):
        load_taxonomy(rules)


def test_misspelt_key_in_a_table_entry_fails_at_load(tmp_path):
    rules = _copy_rules(tmp_path)
    _edit_yaml(rules / RULE_FILES["tables"], lambda d: d["tables"][0].update(defualt_class="usable"))

    with pytest.raises(ValueError, match="defualt_class"):
        load_taxonomy(rules)
