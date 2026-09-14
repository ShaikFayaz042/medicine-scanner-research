"""
Load normalized + canonical data into medicine_scanner schema.

Load order (FK-safe):
  1. regulatory_documents
  2. manufacturers
  3. ingredients
  4. products
  5. product_ingredients
  6. batches
  7. regulatory_events
  8. entity_sources

Idempotency: every INSERT uses ON CONFLICT ... DO UPDATE SET ... RETURNING id,
so re-runs do not duplicate rows and always return the row id.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "normalization" / "output"

import psycopg  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402


SCHEMA = "medicine_scanner"


# --------------------------------------------------------------------------
# Connection
# --------------------------------------------------------------------------

def connect():
    return psycopg.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "cdsco_monitor"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        autocommit=False,
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.open(encoding="utf-8")]


def strip_private(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def srid_to_source_file(srid: str) -> str | None:
    """'nsq/11256_...json#0' -> 'nsq/11256_...json'"""
    if not srid or "#" not in srid:
        return None
    return srid.rpartition("#")[0]


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------

def load_documents(cur, rows: list[dict]) -> dict[str, int]:
    """
    Insert regulatory_documents.
    Returns {source_file_path: db_id} for later event lookup.
    """
    sql = f"""
        INSERT INTO {SCHEMA}.regulatory_documents
            (source_org, source_category, document_type, title,
             publication_date, publication_date_raw, publication_date_precision,
             document_id, source_url, pdf_filename, file_hash,
             raw_text, extraction_method, extraction_status, extraction_confidence)
        VALUES (%(source_org)s, %(source_category)s, %(document_type)s, %(title)s,
                %(publication_date)s, %(publication_date_raw)s, %(publication_date_precision)s,
                %(document_id)s, %(source_url)s, %(pdf_filename)s, %(file_hash)s,
                %(raw_text)s, %(extraction_method)s, %(extraction_status)s,
                %(extraction_confidence)s)
        ON CONFLICT (source_org, document_id, document_type)
        DO UPDATE SET title = EXCLUDED.title
        RETURNING id
    """
    path_to_id: dict[str, int] = {}
    for r in rows:
        params = {
            "source_org": r.get("source_org"),
            "source_category": r.get("source_category"),
            "document_type": r.get("document_type"),
            "title": r.get("title"),
            "publication_date": r.get("publication_date"),
            "publication_date_raw": r.get("publication_date_raw"),
            "publication_date_precision": r.get("publication_date_precision"),
            "document_id": r.get("document_id"),
            "source_url": r.get("source_url"),
            "pdf_filename": r.get("pdf_filename"),
            "file_hash": r.get("file_hash"),
            "raw_text": r.get("raw_text"),
            "extraction_method": r.get("extraction_method"),
            "extraction_status": r.get("extraction_status"),
            "extraction_confidence": r.get("extraction_confidence"),
        }
        cur.execute(sql, params)
        db_id = cur.fetchone()[0]
        sf = r.get("_source_file")
        if sf:
            path_to_id[sf] = db_id
    print(f"[load] documents: {len(rows)}")
    return path_to_id


def load_manufacturers(cur, rows: list[dict]) -> dict[str, int]:
    sql = f"""
        INSERT INTO {SCHEMA}.manufacturers
            (name, normalized_name, address, country, match_status)
        VALUES (%(name)s, %(normalized_name)s, %(address)s, %(country)s, %(match_status)s)
        ON CONFLICT (normalized_name)
        DO UPDATE SET name = EXCLUDED.name
        RETURNING id
    """
    id_map: dict[str, int] = {}
    for r in rows:
        cid = r["canonical_id"]
        params = {
            "name": r.get("canonical_name") or (r.get("representative_row") or {}).get("name"),
            "normalized_name": (r.get("representative_row") or {}).get("normalized_name"),
            "address": (r.get("representative_row") or {}).get("address"),
            "country": (r.get("representative_row") or {}).get("country"),
            "match_status": (r.get("representative_row") or {}).get("match_status") or "UNREVIEWED",
        }
        cur.execute(sql, params)
        id_map[cid] = cur.fetchone()[0]
    print(f"[load] manufacturers: {len(rows)}")
    return id_map


def load_ingredients(cur, rows: list[dict]) -> dict[str, int]:
    sql = f"""
        INSERT INTO {SCHEMA}.ingredients (name, normalized_name)
        VALUES (%(name)s, %(normalized_name)s)
        ON CONFLICT (normalized_name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
    """
    id_map: dict[str, int] = {}
    for r in rows:
        cid = r["canonical_id"]
        rep = r.get("representative_row") or {}
        params = {
            "name": rep.get("name") or r.get("canonical_name"),
            "normalized_name": rep.get("normalized_name"),
        }
        cur.execute(sql, params)
        id_map[cid] = cur.fetchone()[0]
    print(f"[load] ingredients: {len(rows)}")
    return id_map


def load_products(cur, rows: list[dict], mfr_map: dict[str, int]) -> dict[str, int]:
    sql = f"""
        INSERT INTO {SCHEMA}.products
            (product_name, product_name_raw, brand_name, generic_name, dosage_form,
             route, manufacturer_id, marketer_name, importer_name,
             raw_composition, normalized_search_name, match_status)
        VALUES (%(product_name)s, %(product_name_raw)s, %(brand_name)s, %(generic_name)s,
                %(dosage_form)s, %(route)s, %(manufacturer_id)s, %(marketer_name)s,
                %(importer_name)s, %(raw_composition)s, %(normalized_search_name)s,
                %(match_status)s)
        ON CONFLICT (
            normalized_search_name,
            (COALESCE(manufacturer_id, 0)),
            (COALESCE(dosage_form, ''))
        ) DO UPDATE SET
            product_name = EXCLUDED.product_name,
            product_name_raw = EXCLUDED.product_name_raw,
            brand_name = EXCLUDED.brand_name,
            generic_name = EXCLUDED.generic_name,
            dosage_form = EXCLUDED.dosage_form,
            route = EXCLUDED.route,
            marketer_name = EXCLUDED.marketer_name,
            importer_name = EXCLUDED.importer_name,
            raw_composition = EXCLUDED.raw_composition,
            match_status = EXCLUDED.match_status
        RETURNING id
    """
    id_map: dict[str, int] = {}
    for r in rows:
        cid = r["canonical_id"]
        rep = r.get("representative_row") or {}
        mfr_canon = rep.get("manufacturer_candidate_key")
        mfr_db_id = mfr_map.get(mfr_canon) if mfr_canon else None
        params = {
            "product_name": rep.get("product_name") or r.get("canonical_name"),
            "product_name_raw": rep.get("product_name_raw"),
            "brand_name": rep.get("brand_name"),
            "generic_name": rep.get("generic_name"),
            "dosage_form": rep.get("dosage_form"),
            "route": rep.get("route"),
            "manufacturer_id": mfr_db_id,
            "marketer_name": rep.get("marketer_name"),
            "importer_name": rep.get("importer_name"),
            "raw_composition": rep.get("raw_composition"),
            "normalized_search_name": rep.get("normalized_search_name") or "",
            "match_status": rep.get("match_status") or "UNREVIEWED",
        }
        cur.execute(sql, params)
        id_map[cid] = cur.fetchone()[0]
    print(f"[load] products: {len(rows)}")
    return id_map


def load_product_ingredients(cur, rows: list[dict],
                             prod_map: dict[str, int],
                             ing_map: dict[str, int]) -> int:
    sql = f"""
        INSERT INTO {SCHEMA}.product_ingredients
            (product_id, ingredient_id, strength, strength_text, unit,
             basis, dosage_form, sequence_no)
        VALUES (%(product_id)s, %(ingredient_id)s, %(strength)s, %(strength_text)s,
                %(unit)s, %(basis)s, %(dosage_form)s, %(sequence_no)s)
        ON CONFLICT (product_id, ingredient_id, sequence_no) DO NOTHING
    """
    n = 0
    for r in rows:
        pid = prod_map.get(r["canonical_product_id"])
        iid = ing_map.get(r["canonical_ingredient_id"])
        if not pid or not iid:
            continue
        params = {
            "product_id": pid,
            "ingredient_id": iid,
            "strength": r.get("strength"),
            "strength_text": r.get("strength_text"),
            "unit": r.get("unit"),
            "basis": r.get("basis"),
            "dosage_form": None,
            "sequence_no": r.get("sequence_no", 1),
        }
        cur.execute(sql, params)
        n += 1
    print(f"[load] product_ingredients: {n}")
    return n


def load_batches(cur, rows: list[dict],
                 prod_map: dict[str, int],
                 mfr_map: dict[str, int]) -> dict[str, int]:
    sql = f"""
        INSERT INTO {SCHEMA}.batches
            (product_id, manufacturer_id, batch_number,
             mfg_date, mfg_date_raw, mfg_date_precision,
             expiry_date, expiry_date_raw, expiry_date_precision, match_status)
        VALUES (%(product_id)s, %(manufacturer_id)s, %(batch_number)s,
                %(mfg_date)s, %(mfg_date_raw)s, %(mfg_date_precision)s,
                %(expiry_date)s, %(expiry_date_raw)s, %(expiry_date_precision)s,
                %(match_status)s)
        ON CONFLICT (
            product_id,
            (COALESCE(manufacturer_id, 0)),
            batch_number
        ) DO UPDATE SET
            mfg_date = EXCLUDED.mfg_date,
            mfg_date_raw = EXCLUDED.mfg_date_raw,
            mfg_date_precision = EXCLUDED.mfg_date_precision,
            expiry_date = EXCLUDED.expiry_date,
            expiry_date_raw = EXCLUDED.expiry_date_raw,
            expiry_date_precision = EXCLUDED.expiry_date_precision,
            match_status = EXCLUDED.match_status
        RETURNING id
    """
    id_map: dict[str, int] = {}
    for r in rows:
        cid = r["canonical_batch_id"]
        pid = prod_map.get(r["canonical_product_id"])
        if not pid:
            continue
        mfr_id = mfr_map.get(r.get("canonical_manufacturer_id") or "")
        params = {
            "product_id": pid,
            "manufacturer_id": mfr_id,
            "batch_number": r.get("batch_number"),
            "mfg_date": r.get("mfg_date"),
            "mfg_date_raw": r.get("mfg_date_raw"),
            "mfg_date_precision": r.get("mfg_date_precision"),
            "expiry_date": r.get("expiry_date"),
            "expiry_date_raw": r.get("expiry_date_raw"),
            "expiry_date_precision": r.get("expiry_date_precision"),
            "match_status": "UNREVIEWED",
        }
        cur.execute(sql, params)
        id_map[cid] = cur.fetchone()[0]
    print(f"[load] batches: {len(rows)}")
    return id_map


def load_events(cur, rows: list[dict],
                path_to_docid: dict[str, int],
                prod_map: dict[str, int],
                batch_map: dict[str, int]) -> int:
    sql = f"""
        INSERT INTO {SCHEMA}.regulatory_events
            (document_id, product_id, batch_id, scope, event_type, status,
             legal_status, reason, effective_date, investigation_status,
             sample_collected_by, testing_lab, legal_reference,
             additional_data, source_record_id)
        VALUES (%(document_id)s, %(product_id)s, %(batch_id)s, %(scope)s,
                %(event_type)s, %(status)s, %(legal_status)s, %(reason)s,
                %(effective_date)s, %(investigation_status)s,
                %(sample_collected_by)s, %(testing_lab)s, %(legal_reference)s,
                %(additional_data)s, %(source_record_id)s)
        ON CONFLICT (source_record_id) DO NOTHING
    """
    n = 0
    missing_doc = 0
    for r in rows:
        srid = r.get("_source_record_id")
        sf = srid_to_source_file(srid)
        doc_id = path_to_docid.get(sf) if sf else None
        if not doc_id:
            missing_doc += 1
            continue
        pid = prod_map.get(r.get("canonical_product_id") or "")
        bid = batch_map.get(r.get("canonical_batch_id") or "")
        params = {
            "document_id": doc_id,
            "product_id": pid,
            "batch_id": bid,
            "scope": r.get("scope"),
            "event_type": r.get("event_type"),
            "status": r.get("status"),
            "legal_status": r.get("legal_status"),
            "reason": r.get("reason"),
            "effective_date": r.get("effective_date"),
            "investigation_status": r.get("investigation_status"),
            "sample_collected_by": r.get("sample_collected_by"),
            "testing_lab": r.get("testing_lab"),
            "legal_reference": r.get("legal_reference"),
            "additional_data": Jsonb(r.get("additional_data") or {}),
            "source_record_id": srid,
        }
        cur.execute(sql, params)
        n += 1
    print(f"[load] regulatory_events: {n} (missing_doc={missing_doc})")
    return n


def load_entity_sources(cur, rows: list[dict],
                        prod_map: dict[str, int],
                        mfr_map: dict[str, int],
                        ing_map: dict[str, int],
                        batch_map: dict[str, int],
                        path_to_docid: dict[str, int]) -> int:
    sql = f"""
        INSERT INTO {SCHEMA}.entity_sources
            (entity_table, entity_id, source_record_id, document_id)
        VALUES (%(entity_table)s, %(entity_id)s, %(source_record_id)s, %(document_id)s)
        ON CONFLICT (entity_table, entity_id, source_record_id) DO NOTHING
    """
    maps = {
        "products": prod_map,
        "manufacturers": mfr_map,
        "ingredients": ing_map,
        "batches": batch_map,
    }
    n = 0
    skipped = 0
    for r in rows:
        table = r["entity_table"]
        canonical = r["entity_id"]
        db_id = maps.get(table, {}).get(canonical)
        srid = r["source_record_id"]
        sf = srid_to_source_file(srid)
        doc_id = path_to_docid.get(sf) if sf else None
        if not db_id or not doc_id:
            skipped += 1
            continue
        params = {
            "entity_table": table,
            "entity_id": db_id,
            "source_record_id": srid,
            "document_id": doc_id,
        }
        cur.execute(sql, params)
        n += 1
    print(f"[load] entity_sources: {n} (skipped={skipped})")
    return n


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    canonical = OUTPUT_DIR / "canonical"

    docs_path = OUTPUT_DIR / "documents_with_provenance.jsonl"
    if not docs_path.exists():
        docs_path = OUTPUT_DIR / "documents.jsonl"

    documents = load_jsonl(docs_path)
    manufacturers = load_jsonl(canonical / "manufacturers.jsonl")
    ingredients = load_jsonl(canonical / "ingredients.jsonl")
    products = load_jsonl(canonical / "products.jsonl")
    links = load_jsonl(canonical / "product_ingredients.jsonl")
    batches = load_jsonl(canonical / "batches.jsonl")
    events = load_jsonl(OUTPUT_DIR / "events_canonical.jsonl")
    entity_sources = load_jsonl(OUTPUT_DIR / "entity_sources.jsonl")

    print(f"[in] docs={len(documents)} mfr={len(manufacturers)} ing={len(ingredients)} "
          f"products={len(products)} links={len(links)} batches={len(batches)} "
          f"events={len(events)} entity_sources={len(entity_sources)}")

    if args.dry_run:
        print("[dry-run] no DB writes performed.")
        return 0

    conn = connect()
    try:
        with conn.cursor() as cur:
            path_to_docid = load_documents(cur, documents)
            mfr_map = load_manufacturers(cur, manufacturers)
            ing_map = load_ingredients(cur, ingredients)
            prod_map = load_products(cur, products, mfr_map)
            load_product_ingredients(cur, links, prod_map, ing_map)
            batch_map = load_batches(cur, batches, prod_map, mfr_map)
            load_events(cur, events, path_to_docid, prod_map, batch_map)
            load_entity_sources(cur, entity_sources, prod_map, mfr_map,
                                ing_map, batch_map, path_to_docid)
        conn.commit()
        print("[ok] committed.")
    except Exception as e:
        conn.rollback()
        print(f"[error] rolled back: {e}")
        raise
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())