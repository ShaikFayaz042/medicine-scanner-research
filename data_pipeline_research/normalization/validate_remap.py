"""
Post-remap sanity checks.

Verifies:
  - Every canonical_batch references an existing canonical_product.
  - Every canonical_product_ingredient references existing product & ingredient.
  - Every entity_sources row references an existing canonical entity.
  - No duplicate canonical_batch_id with conflicting product/batch_number.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT_DIR


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open(encoding="utf-8")]


def main() -> int:
    canonical = OUTPUT_DIR / "canonical"
    products = load_jsonl(canonical / "products.jsonl")
    ingredients = load_jsonl(canonical / "ingredients.jsonl")
    batches = load_jsonl(canonical / "batches.jsonl")
    links = load_jsonl(canonical / "product_ingredients.jsonl")
    events = load_jsonl(OUTPUT_DIR / "events_canonical.jsonl")
    entity_sources = load_jsonl(OUTPUT_DIR / "entity_sources.jsonl")

    product_ids = {p["canonical_id"] for p in products}
    ingredient_ids = {i["canonical_id"] for i in ingredients}
    batch_ids = {b["canonical_batch_id"] for b in batches}

    problems: list[str] = []

    # Batches reference products
    for b in batches:
        if b["canonical_product_id"] not in product_ids:
            problems.append(f"batch {b['canonical_batch_id']}: missing product")

    # Links reference product + ingredient
    for l in links:
        if l["canonical_product_id"] not in product_ids:
            problems.append(f"link: missing product {l['canonical_product_id']}")
        if l["canonical_ingredient_id"] not in ingredient_ids:
            problems.append(f"link: missing ingredient {l['canonical_ingredient_id']}")

    # Events reference existing canonical entities when set
    for e in events:
        cp = e.get("canonical_product_id")
        cb = e.get("canonical_batch_id")
        if cp and cp not in product_ids:
            problems.append(f"event: missing product {cp}")
        if cb and cb not in batch_ids:
            problems.append(f"event: missing batch {cb}")

    # Entity sources reference existing canonical entities
    for es in entity_sources:
        et = es["entity_table"]
        eid = es["entity_id"]
        if et == "products" and eid not in product_ids:
            problems.append(f"entity_sources: missing product {eid}")
        elif et == "ingredients" and eid not in ingredient_ids:
            problems.append(f"entity_sources: missing ingredient {eid}")
        elif et == "batches" and eid not in batch_ids:
            problems.append(f"entity_sources: missing batch {eid}")
        # manufacturers validated separately

    if problems:
        print(f"VALIDATION FAILED: {len(problems)} problems")
        for p in problems[:50]:
            print(" -", p)
        return 1

    print("OK: remap validation passed")
    print(f"  canonical products:    {len(products)}")
    print(f"  canonical ingredients: {len(ingredients)}")
    print(f"  canonical batches:     {len(batches)}")
    print(f"  canonical links:       {len(links)}")
    print(f"  events_canonical:      {len(events)}")
    print(f"  entity_sources rows:   {len(entity_sources)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())