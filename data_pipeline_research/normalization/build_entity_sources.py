"""
Build entity_sources.jsonl staging data.

For every canonical entity, union all source_record_ids from its members,
resolve each to a document_id via documents_with_provenance.jsonl, and
emit one row per (entity_table, canonical_id, source_record_id, document_id).

Output: normalization/output/entity_sources.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT_DIR, write_jsonl, utcnow_iso


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open(encoding="utf-8")]


def build_srid_to_docid(docs: list[dict]) -> dict[str, str]:
    """
    Documents expose:
      document_id (e.g. '12555')
      _source_file (e.g. 'nsq/12555_NSQ_....json')
      _folder
    source_record_id format: '<folder>/<filename>.json#<index>'
    Map: '<folder>/<filename>.json' -> document_id
    """
    out: dict[str, str] = {}
    for d in docs:
        src = d.get("_source_file")
        did = d.get("document_id")
        if src and did:
            out[src] = did
    return out


def srid_to_docid(srid: str, path_to_docid: dict[str, str]) -> str | None:
    if "#" not in srid:
        return None
    path, _, _ = srid.rpartition("#")
    return path_to_docid.get(path)


def emit(entity_table: str, rows: list[dict], canonical_id_field: str,
         path_to_docid: dict[str, str]) -> tuple[list[dict], int]:
    out: list[dict] = []
    missing = 0
    for r in rows:
        cid = r.get(canonical_id_field)
        if not cid:
            continue
        for srid in r.get("source_record_ids", []):
            did = srid_to_docid(srid, path_to_docid)
            if not did:
                missing += 1
                continue
            out.append({
                "entity_table": entity_table,
                "entity_id": cid,          # canonical id (mapped to DB id at load time)
                "source_record_id": srid,
                "document_id_external": did,
                "_created_at": utcnow_iso(),
            })
    return out, missing


def main() -> int:
    canonical = OUTPUT_DIR / "canonical"
    products = load_jsonl(canonical / "products.jsonl")
    manufacturers = load_jsonl(canonical / "manufacturers.jsonl")
    ingredients = load_jsonl(canonical / "ingredients.jsonl")
    batches = load_jsonl(canonical / "batches.jsonl")

    docs_path = OUTPUT_DIR / "documents_with_provenance.jsonl"
    if not docs_path.exists():
        docs_path = OUTPUT_DIR / "documents.jsonl"
    docs = load_jsonl(docs_path)
    print(f"[in] docs={len(docs)} products={len(products)} mfr={len(manufacturers)} "
          f"ing={len(ingredients)} batches={len(batches)}")

    path_to_docid = build_srid_to_docid(docs)

    rows: list[dict] = []
    miss_p = 0
    miss_m = 0
    miss_i = 0
    miss_b = 0

    for table, src, id_field in (
        ("products", products, "canonical_id"),
        ("manufacturers", manufacturers, "canonical_id"),
        ("ingredients", ingredients, "canonical_id"),
        ("batches", batches, "canonical_batch_id"),
    ):
        r, miss = emit(table, src, id_field, path_to_docid)
        rows.extend(r)
        if table == "products": miss_p = miss
        if table == "manufacturers": miss_m = miss
        if table == "ingredients": miss_i = miss
        if table == "batches": miss_b = miss

    out = OUTPUT_DIR / "entity_sources.jsonl"
    n = write_jsonl(rows, out)
    print(f"[ok] wrote {n} entity_sources rows -> {out}")
    print(f"[miss] products={miss_p} manufacturers={miss_m} "
          f"ingredients={miss_i} batches={miss_b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())