"""Resolve product, manufacturer, and ingredient candidates into canonical clusters."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    OUTPUT_DIR,
    extract_release_forms,
    extract_salt_forms,
    extract_strengths,
    load_config,
    make_candidate_key,
    normalize_search_name,
    utcnow_iso,
    write_jsonl,
)

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    from difflib import SequenceMatcher

    def similarity(left: str, right: str) -> float:
        return SequenceMatcher(None, left or "", right or "").ratio()

    FUZZ_BACKEND = "difflib"
else:
    def similarity(left: str, right: str) -> float:
        return fuzz.token_sort_ratio(left or "", right or "") / 100.0

    FUZZ_BACKEND = "rapidfuzz"

BLOCK_PREFIX_LEN = 6
PRODUCT_MAX_CLUSTER_SIZE = 8
CANONICAL_DIR = OUTPUT_DIR / "canonical"
MAPS_DIR = OUTPUT_DIR / "maps"


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def _block(value: str, length: int = BLOCK_PREFIX_LEN) -> str:
    return (value or "")[:length].lower()


def _block_key(name: str | None) -> str:
    normalized = normalize_search_name(name)
    strength_signature = "|".join(sorted(extract_strengths(name)))
    return f"{normalized[:BLOCK_PREFIX_LEN]}||{strength_signature}"


def _product_auto_rule(left: dict, right: dict, require_same_manufacturer: bool) -> bool:
    left_mfr = left.get("manufacturer_candidate_key")
    right_mfr = right.get("manufacturer_candidate_key")
    if require_same_manufacturer and left_mfr and right_mfr and left_mfr != right_mfr:
        return False
    left_form, right_form = left.get("dosage_form"), right.get("dosage_form")
    if left_form and right_form and left_form != right_form:
        return False
    left_comp, right_comp = left.get("raw_composition"), right.get("raw_composition")
    if left_comp and right_comp and similarity(left_comp, right_comp) < 0.85:
        return False
    left_strength = extract_strengths(left.get("product_name_raw"))
    right_strength = extract_strengths(right.get("product_name_raw"))
    if left_strength != right_strength:
        return False
    left_name = left.get("product_name_raw")
    right_name = right.get("product_name_raw")
    if extract_salt_forms(left_name) != extract_salt_forms(right_name):
        return False
    if extract_release_forms(left_name) != extract_release_forms(right_name):
        return False
    return True


def _split_suspicious_cluster(
    members: list[dict],
    key_field: str,
    name_field: str,
    min_intra: float,
    max_size: int,
) -> list[list[dict]]:
    """Split using complete-linkage compatibility, with a deterministic cap."""
    subclusters: list[list[dict]] = []
    for member in sorted(members, key=lambda row: row[key_field]):
        placed = False
        for group in subclusters:
            if len(group) >= max_size:
                continue
            if all(
                extract_strengths(member.get("product_name_raw")) == extract_strengths(existing.get("product_name_raw"))
                and extract_salt_forms(member.get("product_name_raw")) == extract_salt_forms(existing.get("product_name_raw"))
                and extract_release_forms(member.get("product_name_raw")) == extract_release_forms(existing.get("product_name_raw"))
                and similarity(member.get(name_field, ""), existing.get(name_field, "")) >= min_intra
                for existing in group
            ):
                group.append(member)
                placed = True
                break
        if not placed:
            subclusters.append([member])
    return subclusters


def resolve(
    rows: list[dict],
    name_field: str,
    auto_rule,
    auto_name_sim: float,
    review_sim: float,
    min_intra: float,
    entity_label: str,
    max_cluster_size: int | None = None,
) -> tuple[list[dict], list[dict], list[dict], dict[str, str]]:
    blocks: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        block = _block_key(row.get(name_field)) if entity_label == "product" else _block(row.get(name_field, ""))
        blocks[block].append(row)

    union_find = UnionFind()
    review_log: list[dict] = []
    auto_log: list[dict] = []

    for group in blocks.values():
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                left_key, right_key = left["candidate_key"], right["candidate_key"]
                score = similarity(left.get(name_field, ""), right.get(name_field, ""))
                is_auto = score >= auto_name_sim and auto_rule(left, right)
                entry = {
                    "entity_type": entity_label,
                    "candidate_a": left_key,
                    "candidate_b": right_key,
                    "similarity": round(score, 4),
                    "manufacturer_a": left.get("manufacturer_candidate_key"),
                    "manufacturer_b": right.get("manufacturer_candidate_key"),
                    "action": "AUTO_MERGE" if is_auto else "REVIEW",
                }
                if is_auto:
                    union_find.union(left_key, right_key)
                    auto_log.append(entry)
                elif score >= review_sim and _block(left.get(name_field, ""), 10) == _block(right.get(name_field, ""), 10):
                    review_log.append(entry)

    clusters: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        clusters[union_find.find(row["candidate_key"])].append(row)

    canonical_rows: list[dict] = []
    candidate_map: dict[str, str] = {}
    for members in clusters.values():
        member_keys = sorted(row["candidate_key"] for row in members)
        pair_scores = [
            similarity(left.get(name_field, ""), right.get(name_field, ""))
            for index, left in enumerate(members)
            for right in members[index + 1:]
        ]
        min_similarity = min(pair_scores) if pair_scores else None
        review_required = min_similarity is not None and min_similarity < min_intra
        oversized = max_cluster_size is not None and len(members) > max_cluster_size
        if (review_required or oversized) and len(members) > 1 and max_cluster_size:
            subclusters = _split_suspicious_cluster(
                members, "candidate_key", name_field, min_intra, max_cluster_size
            )
            if len(subclusters) > 1:
                for subcluster in subclusters:
                    subkeys = sorted(row["candidate_key"] for row in subcluster)
                    canonical_id = make_candidate_key(entity_label, *subkeys)
                    for member_key in subkeys:
                        candidate_map[member_key] = canonical_id
                    subpairs = [
                        similarity(left.get(name_field, ""), right.get(name_field, ""))
                        for index, left in enumerate(subcluster)
                        for right in subcluster[index + 1:]
                    ]
                    canonical_rows.append({
                        "canonical_id": canonical_id,
                        "canonical_name": subcluster[0].get(name_field),
                        "representative_row": {key: value for key, value in subcluster[0].items() if not key.startswith("_")},
                        "member_candidate_keys": subkeys,
                        "member_count": len(subkeys),
                        "min_intra_similarity": round(min(subpairs), 4) if subpairs else None,
                        "review_required": False,
                        "source_record_ids": sorted({sid for row in subcluster for sid in row.get("source_record_ids", [])}),
                        "_resolved_at": utcnow_iso(),
                        "_split_from_original": len(member_keys),
                    })
                continue

        canonical_id = make_candidate_key(entity_label, *member_keys)
        for member_key in member_keys:
            candidate_map[member_key] = canonical_id
        canonical_rows.append({
            "canonical_id": canonical_id,
            "canonical_name": members[0].get(name_field),
            "representative_row": {key: value for key, value in members[0].items() if not key.startswith("_")},
            "member_candidate_keys": member_keys,
            "member_count": len(member_keys),
            "min_intra_similarity": round(min_similarity, 4) if min_similarity is not None else None,
            "review_required": review_required,
            "source_record_ids": sorted({sid for row in members for sid in row.get("source_record_ids", [])}),
            "_resolved_at": utcnow_iso(),
        })
    return canonical_rows, review_log, auto_log, candidate_map


def load_rows(path: Path, limit: int) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    return rows[:limit] if limit > 0 else rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0, help="Process only N rows per entity type")
    args = parser.parse_args()
    if args.sample < 0:
        parser.error("--sample must be >= 0")

    products = load_rows(OUTPUT_DIR / "products.jsonl", args.sample)
    manufacturers = load_rows(OUTPUT_DIR / "manufacturers.jsonl", args.sample)
    ingredients = load_rows(OUTPUT_DIR / "ingredients.jsonl", args.sample)
    print(f"[in] products={len(products)} manufacturers={len(manufacturers)} ingredients={len(ingredients)}")

    config = load_config("entity_resolution")
    thresholds = config["thresholds"]
    product_thresholds = thresholds["product"]
    manufacturer_thresholds = thresholds["manufacturer"]
    ingredient_thresholds = thresholds["ingredient"]

    product_result = resolve(
        products,
        "normalized_search_name",
        lambda left, right: _product_auto_rule(
            left, right, product_thresholds["require_same_manufacturer_for_auto"]
        ),
        product_thresholds["auto_name_sim"],
        product_thresholds["review_name_sim"],
        product_thresholds["auto_min_intra_cluster"],
        "product",
        PRODUCT_MAX_CLUSTER_SIZE,
    )
    manufacturer_result = resolve(
        manufacturers,
        "normalized_name",
        lambda _left, _right: manufacturer_thresholds["auto_allowed"],
        1.0,
        manufacturer_thresholds["review_name_sim"],
        1.0,
        "manufacturer",
    )
    ingredient_result = resolve(
        ingredients,
        "normalized_name",
        lambda left, right: ingredient_thresholds["auto_requires_exact_normalized_match"]
        and left.get("normalized_name") == right.get("normalized_name"),
        1.0,
        ingredient_thresholds["review_name_sim"],
        ingredient_thresholds["auto_min_intra_cluster"],
        "ingredient",
    )

    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "products": product_result,
        "manufacturers": manufacturer_result,
        "ingredients": ingredient_result,
    }
    for name, (canonical, _review, _auto, mapping) in results.items():
        write_jsonl(canonical, CANONICAL_DIR / f"{name}.jsonl")
        (MAPS_DIR / f"{name}.json").write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")

    write_jsonl([row for _, (_, review, _, _) in results.items() for row in review], OUTPUT_DIR / "entity_review.jsonl")
    write_jsonl([row for _, (_, _, auto, _) in results.items() for row in auto], OUTPUT_DIR / "entity_auto_merge.jsonl")

    print(f"[summary] fuzzy backend: {FUZZ_BACKEND}")
    for name, (canonical, review, auto, _) in results.items():
        flagged = sum(1 for row in canonical if row["review_required"])
        print(f"[summary] {name}: {len(locals()[name])} -> {len(canonical)} canonical; review_pairs={len(review)} auto_pairs={len(auto)} review_required={flagged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
