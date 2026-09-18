"""
Remap candidate entities to canonical entities across the pipeline.

Inputs:
  normalization/output/maps/products.json         candidate_key -> canonical_id
  normalization/output/maps/manufacturers.json    candidate_key -> canonical_id
  normalization/output/maps/ingredients.json      candidate_key -> canonical_id

  normalization/output/batches.jsonl              (candidate-level)
  normalization/output/product_ingredients_candidates.jsonl
  normalization/output/events.jsonl

  normalization/output/canonical/products.jsonl        (for canonical metadata)
  normalization/output/canonical/manufacturers.jsonl
  normalization/output/canonical/ingredients.jsonl

Outputs:
  normalization/output/canonical/batches.jsonl
  normalization/output/canonical/product_ingredients.jsonl
  normalization/output/events_canonical.jsonl
  normalization/output/remap_report.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT_DIR, write_jsonl, utcnow_iso, make_candidate_key


def load_map(name: str) -> dict[str, str]:
    p = OUTPUT_DIR / "maps" / f"{name}.json"
    if not p.exists():
        raise FileNotFoundError(f"missing map: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open(encoding="utf-8")]


# --- Batches -----------------------------------------------------------

def remap_batches(
    batches: list[dict],
    product_map: dict[str, str],
    mfr_map: dict[str, str],
) -> tuple[list[dict], dict]:
    grouped: dict[str, dict] = {}
    unmapped_products = 0
    unmapped_mfrs = 0

    for b in batches:
        pk = b.get("product_candidate_key")
        mk = b.get("manufacturer_candidate_key")

        canonical_pid = product_map.get(pk)
        if not canonical_pid:
            unmapped_products += 1
            continue

        canonical_mid = mfr_map.get(mk) if mk else None
        if mk and not canonical_mid:
            unmapped_mfrs += 1
            # keep the batch but drop mfr linkage

        batch_num_norm = b.get("batch_number_normalized") or ""
        canonical_batch_id = make_candidate_key(
            "batch", canonical_pid, canonical_mid or "", batch_num_norm
        )

        row = grouped.get(canonical_batch_id)
        if row is None:
            row = {
                "canonical_batch_id": canonical_batch_id,
                "canonical_product_id": canonical_pid,
                "canonical_manufacturer_id": canonical_mid,
                "batch_number": b.get("batch_number"),
                "batch_number_normalized": batch_num_norm,
                "mfg_date": b.get("mfg_date"),
                "mfg_date_raw": b.get("mfg_date_raw"),
                "mfg_date_precision": b.get("mfg_date_precision"),
                "expiry_date": b.get("expiry_date"),
                "expiry_date_raw": b.get("expiry_date_raw"),
                "expiry_date_precision": b.get("expiry_date_precision"),
                "source_record_ids": [],
                "_remapped_at": utcnow_iso(),
            }
            grouped[canonical_batch_id] = row

        for sid in b.get("source_record_ids", []):
            if sid not in row["source_record_ids"]:
                row["source_record_ids"].append(sid)

    stats = {
        "input_batches": len(batches),
        "output_canonical_batches": len(grouped),
        "batches_unmapped_product": unmapped_products,
        "batches_unmapped_manufacturer": unmapped_mfrs,
    }
    return list(grouped.values()), stats


# --- Product ingredients -----------------------------------------------

def remap_product_ingredients(
    links: list[dict],
    product_map: dict[str, str],
    ing_map: dict[str, str],
) -> tuple[list[dict], dict]:
    grouped: dict[tuple, dict] = {}
    unmapped_products = 0
    unmapped_ings = 0

    for link in links:
        pk = link.get("product_candidate_key")
        ik = link.get("ingredient_candidate_key")

        canonical_pid = product_map.get(pk)
        canonical_iid = ing_map.get(ik)
        if not canonical_pid:
            unmapped_products += 1
            continue
        if not canonical_iid:
            unmapped_ings += 1
            continue

        seq = link.get("sequence_no", 1)
        key = (canonical_pid, canonical_iid, seq)
        row = grouped.get(key)
        if row is None:
            row = {
                "canonical_product_id": canonical_pid,
                "canonical_ingredient_id": canonical_iid,
                "sequence_no": seq,
                "strength": link.get("strength"),
                "strength_text": link.get("strength_text"),
                "unit": link.get("unit"),
                "basis": link.get("basis"),
                "composition_source": link.get("composition_source"),
                "composition_confidence": link.get("composition_confidence"),
                "source_record_ids": [],
                "_remapped_at": utcnow_iso(),
            }
            grouped[key] = row
        for sid in link.get("source_record_ids", []) or []:
            if sid not in row["source_record_ids"]:
                row["source_record_ids"].append(sid)

    stats = {
        "input_links": len(links),
        "output_canonical_links": len(grouped),
        "links_unmapped_product": unmapped_products,
        "links_unmapped_ingredient": unmapped_ings,
    }
    return list(grouped.values()), stats


# --- Events ------------------------------------------------------------

def _resolve_event_refs(
    ev: dict,
    product_map: dict[str, str],
    mfr_map: dict[str, str],
    batch_lookup: dict[tuple[str, str | None, str], str],
) -> dict:
    """
    For a single event, compute canonical refs where derivable.
    Returns a dict with canonical_product_id, canonical_manufacturer_id, canonical_batch_id
    (any may be None).
    """
    slots = ev.get("_raw_slots") or {}
    doc_type = ev.get("document_type")

    # FDC events are combination-scope; no product/batch
    if doc_type in ("FDC_PROHIBITED", "FDC_NOTIFICATION"):
        return {"canonical_product_id": None,
                "canonical_manufacturer_id": None,
                "canonical_batch_id": None}

    # Product candidate lookup by source_record_id
    # We don't have direct link here; but products.jsonl indexed by source_record_id
    # was already built. Instead, use _raw_slots.product_name_raw + normalized form.
    # Simplest approach: leave product_id resolution to a second pass using
    # products.jsonl source_record_ids.
    return {"canonical_product_id": None,
            "canonical_manufacturer_id": None,
            "canonical_batch_id": None}


def remap_events(
    events: list[dict],
    products: list[dict],
    manufacturers: list[dict],
    product_map: dict[str, str],
    mfr_map: dict[str, str],
    batches_canonical: list[dict],
) -> tuple[list[dict], dict]:
    """
    Build events_canonical.jsonl.

    Product linkage: via products.jsonl source_record_ids -> canonical.
    Manufacturer linkage: via manufacturers.jsonl source_record_ids -> canonical.
    Batch linkage: via batches_canonical.jsonl source_record_ids -> canonical_batch_id.
    """
    # Index source_record_id -> canonical_product_id
    srid_to_product: dict[str, str] = {}
    for p in products:
        cid = product_map.get(p["candidate_key"])
        if not cid:
            continue
        for sid in p.get("source_record_ids", []):
            srid_to_product[sid] = cid

    srid_to_mfr: dict[str, str] = {}
    for m in manufacturers:
        cid = mfr_map.get(m["candidate_key"])
        if not cid:
            continue
        for sid in m.get("source_record_ids", []):
            srid_to_mfr[sid] = cid

    srid_to_batch: dict[str, str] = {}
    for b in batches_canonical:
        for sid in b.get("source_record_ids", []):
            srid_to_batch[sid] = b["canonical_batch_id"]

    out: list[dict] = []
    linked_product = 0
    linked_mfr = 0
    linked_batch = 0

    for ev in events:
        srid = ev.get("source_record_id")
        cp = srid_to_product.get(srid)
        cm = srid_to_mfr.get(srid)
        cb = srid_to_batch.get(srid)

        if cp: linked_product += 1
        if cm: linked_mfr += 1
        if cb: linked_batch += 1

        row = {k: v for k, v in ev.items() if not k.startswith("_")}
        row["canonical_product_id"] = cp
        row["canonical_manufacturer_id"] = cm
        row["canonical_batch_id"] = cb
        row["_source_record_id"] = srid
        out.append(row)

    stats = {
        "input_events": len(events),
        "events_linked_product": linked_product,
        "events_linked_manufacturer": linked_mfr,
        "events_linked_batch": linked_batch,
    }
    return out, stats


# --- main --------------------------------------------------------------

def main() -> int:
    product_map = load_map("products")
    mfr_map = load_map("manufacturers")
    ing_map = load_map("ingredients")
    print(f"[maps] products={len(product_map)} mfr={len(mfr_map)} ing={len(ing_map)}")

    batches = load_jsonl(OUTPUT_DIR / "batches.jsonl")
    links = load_jsonl(OUTPUT_DIR / "product_ingredients_candidates.jsonl")
    events = load_jsonl(OUTPUT_DIR / "events.jsonl")
    products = load_jsonl(OUTPUT_DIR / "products.jsonl")
    manufacturers = load_jsonl(OUTPUT_DIR / "manufacturers.jsonl")

    print(f"[in] batches={len(batches)} links={len(links)} events={len(events)}")

    cbatches, bstats = remap_batches(batches, product_map, mfr_map)
    clinks, lstats = remap_product_ingredients(links, product_map, ing_map)
    cevents, estats = remap_events(
        events, products, manufacturers, product_map, mfr_map, cbatches
    )

    canonical_dir = OUTPUT_DIR / "canonical"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    n1 = write_jsonl(cbatches, canonical_dir / "batches.jsonl")
    n2 = write_jsonl(clinks, canonical_dir / "product_ingredients.jsonl")
    n3 = write_jsonl(cevents, OUTPUT_DIR / "events_canonical.jsonl")

    report = {
        "generated_at": utcnow_iso(),
        "batches": bstats,
        "product_ingredients": lstats,
        "events": estats,
    }
    (OUTPUT_DIR / "remap_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    print(f"[ok] canonical batches: {n1}")
    print(f"[ok] canonical product_ingredients: {n2}")
    print(f"[ok] events_canonical: {n3}")
    print(f"[report] batches: {bstats}")
    print(f"[report] links: {lstats}")
    print(f"[report] events: {estats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())