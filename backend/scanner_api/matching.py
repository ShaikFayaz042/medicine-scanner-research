from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.database import HAS_PG_TRGM, SCHEMA

FUZZY_LOW = 0.40
FUZZY_HIGH = 0.80
FUZZY_GAP = 0.08

T_PRODUCTS = f"{SCHEMA}.products"
T_MFRS = f"{SCHEMA}.manufacturers"


@dataclass
class ProductCandidate:
    product_id: int
    product_name: str
    normalized_search_name: str
    manufacturer_id: Optional[int]
    manufacturer_name: Optional[str]
    score: float


def exact_products(db: Session, normalized_name: str) -> List[ProductCandidate]:
    rows = db.execute(
        text(
            f"""
            SELECT p.id, p.product_name, p.normalized_search_name,
                   p.manufacturer_id, m.name AS manufacturer_name
            FROM {T_PRODUCTS} p
            LEFT JOIN {T_MFRS} m ON m.id = p.manufacturer_id
            WHERE p.normalized_search_name = :n
            ORDER BY p.id LIMIT 25
            """
        ),
        {"n": normalized_name},
    ).mappings().all()
    return [
        ProductCandidate(
            product_id=r["id"],
            product_name=r["product_name"] or "",
            normalized_search_name=r["normalized_search_name"] or "",
            manufacturer_id=r["manufacturer_id"],
            manufacturer_name=r["manufacturer_name"],
            score=1.0,
        )
        for r in rows
    ]


def fuzzy_products(db: Session, normalized_name: str, threshold: float = FUZZY_LOW) -> List[ProductCandidate]:
    if HAS_PG_TRGM:
        rows = db.execute(
            text(
                f"""
                SELECT p.id, p.product_name, p.normalized_search_name,
                       p.manufacturer_id, m.name AS manufacturer_name,
                       GREATEST(
                           similarity(p.normalized_search_name, :n),
                           word_similarity(:n, p.normalized_search_name)
                       ) AS score
                FROM {T_PRODUCTS} p
                LEFT JOIN {T_MFRS} m ON m.id = p.manufacturer_id
                WHERE similarity(p.normalized_search_name, :n) >= :thr
                   OR word_similarity(:n, p.normalized_search_name) >= :thr
                ORDER BY score DESC, p.id LIMIT 25
                """
            ),
            {"n": normalized_name, "thr": threshold},
        ).mappings().all()
        return [
            ProductCandidate(
                product_id=r["id"],
                product_name=r["product_name"] or "",
                normalized_search_name=r["normalized_search_name"] or "",
                manufacturer_id=r["manufacturer_id"],
                manufacturer_name=r["manufacturer_name"],
                score=float(r["score"]) if r["score"] is not None else 0.0,
            )
            for r in rows
        ]

    # ---- Fallback path (no pg_trgm) ----
    tokens = [t for t in normalized_name.split() if len(t) >= 3] or [normalized_name]
    like_clauses = " OR ".join(f"p.normalized_search_name LIKE :tok{i}" for i in range(len(tokens)))
    params = {f"tok{i}": f"%{t}%" for i, t in enumerate(tokens)}
    rows = db.execute(
        text(
            f"""
            SELECT p.id, p.product_name, p.normalized_search_name,
                   p.manufacturer_id, m.name AS manufacturer_name
            FROM {T_PRODUCTS} p
            LEFT JOIN {T_MFRS} m ON m.id = p.manufacturer_id
            WHERE {like_clauses}
            LIMIT 200
            """
        ),
        params,
    ).mappings().all()

    out: List[ProductCandidate] = []
    for r in rows:
        s = SequenceMatcher(None, normalized_name, r["normalized_search_name"] or "").ratio()
        if s < threshold:
            continue
        out.append(
            ProductCandidate(
                product_id=r["id"],
                product_name=r["product_name"] or "",
                normalized_search_name=r["normalized_search_name"] or "",
                manufacturer_id=r["manufacturer_id"],
                manufacturer_name=r["manufacturer_name"],
                score=s,
            )
        )
    out.sort(key=lambda c: (-c.score, c.product_id))
    return out[:25]


def decide_match_type(candidates: List[ProductCandidate]):
    if not candidates:
        return "NONE", []
    exact = [c for c in candidates if c.score >= 0.999]
    if len(exact) == 1 and len(candidates) == 1:
        return "EXACT", [exact[0]]
    if len(exact) > 1:
        return "MULTIPLE", candidates
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    if top.score >= FUZZY_HIGH and (second is None or (top.score - second.score) >= FUZZY_GAP):
        return "FUZZY", [top]
    if len(candidates) == 1:
        return "FUZZY", candidates
    return "MULTIPLE", candidates