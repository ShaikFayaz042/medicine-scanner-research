from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import HAS_PG_TRGM, SCHEMA

T_EVENTS = f"{SCHEMA}.regulatory_events"
T_DOCS = f"{SCHEMA}.regulatory_documents"
T_PRODUCTS = f"{SCHEMA}.products"
T_MFRS = f"{SCHEMA}.manufacturers"
T_BATCHES = f"{SCHEMA}.batches"
T_ING = f"{SCHEMA}.ingredients"
T_PI = f"{SCHEMA}.product_ingredients"
T_ES = f"{SCHEMA}.entity_sources"


def _fetch_docs(db: Session, doc_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    ids = [i for i in {int(x) for x in doc_ids if x is not None}]
    if not ids:
        return {}
    rows = db.execute(
        text(f"SELECT * FROM {T_DOCS} WHERE id = ANY(:ids)"),
        {"ids": ids},
    ).mappings().all()
    return {r["id"]: dict(r) for r in rows}


def _merge_docs(events: List[Dict[str, Any]], docs: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in events:
        d = dict(e)
        doc = docs.get(e.get("document_id")) or {}
        d["doc_id"] = doc.get("id")
        d["doc_source_org"] = doc.get("source_org")
        d["doc_document_type"] = doc.get("document_type")
        d["doc_title"] = doc.get("title")
        d["doc_pdf_filename"] = doc.get("pdf_filename")
        d["doc_publication_date"] = doc.get("publication_date")
        d["doc_source_url"] = doc.get("source_url")
        out.append(d)
    return out


def get_batch(db: Session, product_id: int, batch_number: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(
            f"""
            SELECT b.*, m.name AS manufacturer_name
            FROM {T_BATCHES} b
            LEFT JOIN {T_MFRS} m ON m.id = b.manufacturer_id
            WHERE b.product_id = :pid
              AND UPPER(b.batch_number) = UPPER(:bn)
            ORDER BY b.id
            LIMIT 5
            """
        ),
        {"pid": product_id, "bn": batch_number},
    ).mappings().first()
    return dict(row) if row else None


def _events(db: Session, where_sql: str, params: dict) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(f"SELECT * FROM {T_EVENTS} WHERE {where_sql} ORDER BY id LIMIT 200"),
        params,
    ).mappings().all()
    events = [dict(r) for r in rows]
    docs = _fetch_docs(db, [e.get("document_id") for e in events])
    return _merge_docs(events, docs)


def get_events_by_batch(db: Session, batch_id: int) -> List[Dict[str, Any]]:
    return _events(db, "batch_id = :bid", {"bid": batch_id})


def get_events_by_product(db: Session, product_id: int) -> List[Dict[str, Any]]:
    return _events(
        db,
        "product_id = :pid AND (batch_id IS NULL OR scope IN ('PRODUCT','COMBINATION'))",
        {"pid": product_id},
    )


def get_all_combination_events(db: Session) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(f"SELECT * FROM {T_EVENTS} WHERE scope = 'COMBINATION' ORDER BY id LIMIT 500")
    ).mappings().all()
    events = [dict(r) for r in rows]
    docs = _fetch_docs(db, [e.get("document_id") for e in events])
    return _merge_docs(events, docs)


def get_product_ingredients(db: Session, product_id: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT i.id AS ingredient_id, i.name AS ingredient_name,
                   pi.strength_text, pi.unit, pi.sequence_no
            FROM {T_PI} pi
            JOIN {T_ING} i ON i.id = pi.ingredient_id
            WHERE pi.product_id = :pid
            ORDER BY pi.sequence_no NULLS LAST, i.id
            """
        ),
        {"pid": product_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def find_products_by_ingredient(db: Session, normalized_ingredient: str, threshold: float = 0.5) -> List[Dict[str, Any]]:
    if HAS_PG_TRGM:
        sql = text(
            f"""
            SELECT p.*, m.name AS manufacturer_name, i.name AS ingredient_name,
                   similarity(i.normalized_name, :n) AS score
            FROM {T_ING} i
            JOIN {T_PI} pi ON pi.ingredient_id = i.id
            JOIN {T_PRODUCTS} p ON p.id = pi.product_id
            LEFT JOIN {T_MFRS} m ON m.id = p.manufacturer_id
            WHERE similarity(i.normalized_name, :n) >= :thr
               OR i.normalized_name LIKE :prefix
            ORDER BY score DESC, p.id
            LIMIT 50
            """
        )
        params = {"n": normalized_ingredient, "thr": threshold, "prefix": f"%{normalized_ingredient}%"}
    else:
        sql = text(
            f"""
            SELECT p.*, m.name AS manufacturer_name, i.name AS ingredient_name,
                   0.7 AS score
            FROM {T_ING} i
            JOIN {T_PI} pi ON pi.ingredient_id = i.id
            JOIN {T_PRODUCTS} p ON p.id = pi.product_id
            LEFT JOIN {T_MFRS} m ON m.id = p.manufacturer_id
            WHERE i.normalized_name LIKE :prefix
            ORDER BY p.id
            LIMIT 50
            """
        )
        params = {"prefix": f"%{normalized_ingredient}%"}
    rows = db.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def get_provenance(db: Session, entity_table: str, entity_id: int) -> List[Dict[str, Any]]:
    rows = db.execute(
        text(
            f"""
            SELECT * FROM {T_ES}
            WHERE entity_table = :t AND entity_id = :e
            ORDER BY id LIMIT 25
            """
        ),
        {"t": entity_table, "e": entity_id},
    ).mappings().all()
    return [dict(r) for r in rows]