"""Extract commercial ingredients and product_ingredients candidates."""
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    OUTPUT_DIR, write_jsonl, utcnow_iso,
    normalize_search_name, make_candidate_key, collapse_ws,
    parse_composition,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="products.jsonl")
    args = parser.parse_args()
    products_path = OUTPUT_DIR / args.input
    if not products_path.exists():
        print(f"[error] missing {products_path}; run normalize_products.py first")
        return 1
    by_ingredient: dict[str, dict] = {}
    product_ingredients: list[dict] = []
    with products_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            product = json.loads(line)
            composition = product.get("raw_composition")
            if not composition:
                continue
            product_key = product["candidate_key"]
            for ingredient in parse_composition(composition):
                name = ingredient["ingredient_name_raw"]
                normalized = normalize_search_name(name)
                if not normalized:
                    continue
                ingredient_key = make_candidate_key(normalized)
                by_ingredient.setdefault(ingredient_key, {
                    "candidate_key": ingredient_key,
                    "name": collapse_ws(name),
                    "normalized_name": normalized,
                    "source_record_ids": [],
                    "_created_at": utcnow_iso(),
                })
                row = by_ingredient[ingredient_key]
                for srid in product.get("source_record_ids", []):
                    if srid not in row["source_record_ids"]:
                        row["source_record_ids"].append(srid)
                product_ingredients.append({
                    "product_candidate_key": product_key,
                    "ingredient_candidate_key": ingredient_key,
                    "strength": ingredient["strength"],
                    "strength_text": ingredient["strength_text"],
                    "unit": ingredient["unit"],
                    "basis": ingredient["basis"],
                    "sequence_no": ingredient["sequence_no"],
                    "composition_source": product.get("composition_source"),
                    "composition_confidence": product.get("composition_confidence"),
                    "source_record_ids": product.get("source_record_ids", []),
                })

    ingredients_path = OUTPUT_DIR / "ingredients.jsonl"
    links_path = OUTPUT_DIR / "product_ingredients_candidates.jsonl"
    print(f"[ok] wrote {write_jsonl(by_ingredient.values(), ingredients_path)} ingredients -> {ingredients_path}")
    print(f"[ok] wrote {write_jsonl(product_ingredients, links_path)} product_ingredient candidates -> {links_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
