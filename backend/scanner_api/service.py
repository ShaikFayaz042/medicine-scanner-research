"""
Main business flow for /api/scan.

Read-only. Deterministic. Never invents dates or legal references.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.scanner_api import matching, queries, rules
from backend.scanner_api.matching import ProductCandidate
from backend.scanner_api.schemas import (
    BatchBlock,
    CandidateItem,
    GovernmentStatementBlock,
    MatchBlock,
    MatchItem,
    MedicineBlock,
    RegulatoryBlock,
    ResultBlock,
    SafetyBlock,
    ScanRequest,
    ScanResponse,
    SourceBlock,
)
from backend.utils.normalization import normalize_batch, normalize_text


# --------------------------------------------------------------------- utils


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _summary_for(ev: Dict[str, Any]) -> str:
    status = (ev.get("status") or "").upper()
    et = (ev.get("event_type") or "").upper()
    reason = ev.get("reason")
    action = ev.get("action")

    if status == "NOT_OF_STANDARD_QUALITY" or "QUALITY_FAILURE" in et:
        base = "The referenced batch was reported as not of standard quality."
    elif "SPURIOUS" in status or "FALSIFIED" in status:
        base = "The referenced product was reported as spurious or falsified."
    elif "PROHIBIT" in status or "BANNED" in status or "PROHIBIT" in et:
        base = "The referenced product or combination was prohibited by a regulatory notification."
    elif "RECALL" in et or "RECALL" in status:
        base = "The referenced product or batch was recalled."
    elif et or status:
        base = "A regulatory event was recorded for this product or batch."
    else:
        base = "A regulatory record was found."

    if reason:
        base += f" Reason: {reason}."
    elif action:
        base += f" Action: {action}."
    return base


def _build_match_item(ev: Dict[str, Any]) -> MatchItem:
    regulatory = RegulatoryBlock(
        event_type=ev.get("event_type"),
        status=ev.get("status"),
        scope=ev.get("scope"),
        action=ev.get("action"),
        reason=ev.get("reason"),
        legal_status=ev.get("legal_status"),
        effective_date=_iso(ev.get("effective_date")),
        investigation_status=ev.get("investigation_status"),
        legal_reference=ev.get("legal_reference"),
    )
    gov = GovernmentStatementBlock(
        authority=ev.get("doc_source_org"),   # <-- was source_org
        summary=_summary_for(ev),
        reference=ev.get("legal_reference"),
    )
    source = SourceBlock(
        document_id=ev.get("doc_id") or ev.get("document_id"),
        document_type=ev.get("doc_document_type"),
        title=ev.get("doc_title"),
        publication_date=_iso(ev.get("doc_publication_date")),
        pdf_filename=ev.get("doc_pdf_filename"),
        pdf_url=ev.get("doc_source_url"),
    )
    return MatchItem(regulatory=regulatory, government_statement=gov, source=source)

# --------------------------------------------------------------------- branches


def _invalid_input_response() -> ScanResponse:
    return ScanResponse(
        result=ResultBlock(
            color="YELLOW",
            status="INVALID_INPUT",
            severity="LOW",
            title="No identifying input provided",
        ),
        match=MatchBlock(type="NONE", confidence=0.0),
        safety=SafetyBlock(
            assessment="UNKNOWN",
            message="Provide medicine_name, barcode, or active_ingredient.",
        ),
    )


def _not_found_response(normalized: str) -> ScanResponse:
    return ScanResponse(
        result=ResultBlock(
            color="YELLOW",
            status="MEDICINE_NOT_FOUND",
            severity="MEDIUM",
            title="Medicine could not be identified",
        ),
        match=MatchBlock(type="NONE", confidence=0.0),
        safety=SafetyBlock(
            assessment="UNKNOWN",
            message="No matching product was found in the regulatory database.",
        ),
    )


def _multiple_response(
    candidates: List[ProductCandidate], confidence: float = 0.0
) -> ScanResponse:
    return ScanResponse(
        result=ResultBlock(
            color="YELLOW",
            status="MULTIPLE_MATCHES",
            severity="MEDIUM",
            title="Multiple product candidates found",
        ),
        match=MatchBlock(type="MULTIPLE", confidence=confidence),
        candidates=[
            CandidateItem(
                product_id=c.product_id,
                name=c.product_name,
                manufacturer=c.manufacturer_name,
                score=round(c.score, 4),
            )
            for c in candidates[:10]
        ],
        safety=SafetyBlock(
            assessment="UNKNOWN",
            message="Multiple products matched the input. Please select the correct one.",
        ),
    )


def _batch_not_found_response(
    product: ProductCandidate,
    batch_number: str,
    match_type: str,
    confidence: float,
    product_events: Optional[List[Dict[str, Any]]] = None,
) -> ScanResponse:
    """
    Product found but batch not found -> YELLOW / BATCH_NOT_FOUND.

    If product-level events exist (e.g. combination or product-wide alerts)
    we still surface them so the UI can show the regulatory concern.
    """
    matches: List[MatchItem] = []
    worst = "GREEN"
    for ev in product_events or []:
        c = rules.classify_event(
            ev.get("event_type"),
            ev.get("status"),
            ev.get("legal_status"),
            ev.get("investigation_status"),
        )
        if rules.color_priority(c) > rules.color_priority(worst):
            worst = c
        matches.append(_build_match_item(ev))

    color = "YELLOW" if worst == "GREEN" else worst
    return ScanResponse(
        result=ResultBlock(
            color=color,
            status="BATCH_NOT_FOUND",
            severity=rules.severity_for(color),
            title="Batch could not be verified",
        ),
        match=MatchBlock(type=match_type, confidence=confidence),
        medicine=MedicineBlock(
            id=product.product_id,
            name=product.product_name,
            manufacturer=product.manufacturer_name,
        ),
        batch=BatchBlock(number=batch_number),
        matches=matches,
        safety=SafetyBlock(
            assessment="UNKNOWN",
            message=(
                "The product was identified but the specified batch was not "
                "found in the regulatory database. This does not confirm the "
                "batch is safe."
            ),
        ),
    )


# --------------------------------------------------------------------- main flow


def _medicine_search(db: Session, req: ScanRequest) -> ScanResponse:
    normalized = normalize_text(req.medicine_name)
    if not normalized:
        return _invalid_input_response()

    # 1. exact
    exact = matching.exact_products(db, normalized)
    if exact:
        match_type, candidates = matching.decide_match_type(exact)
    else:
        fuzzy = matching.fuzzy_products(db, normalized, threshold=matching.FUZZY_LOW)
        match_type, candidates = matching.decide_match_type(fuzzy)

    if match_type == "NONE":
        return _not_found_response(normalized)

    if match_type == "MULTIPLE":
        return _multiple_response(
            candidates,
            confidence=candidates[0].score if candidates else 0.0,
        )

    product = candidates[0]
    confidence = product.score if match_type == "FUZZY" else 1.0

    # 2. batch
    batch_number = normalize_batch(req.batch_number)
    batch_row: Optional[Dict[str, Any]] = None
    if batch_number:
        batch_row = queries.get_batch(db, product.product_id, batch_number)
        if not batch_row:
            product_events = queries.get_events_by_product(db, product.product_id)
            return _batch_not_found_response(
                product, batch_number, match_type, confidence, product_events
            )

    # 3. events
    if batch_row:
        events = queries.get_events_by_batch(db, batch_row["id"])
        if not events:
            events = queries.get_events_by_product(db, product.product_id)
    else:
        events = queries.get_events_by_product(db, product.product_id)

    # 4. manufacturer fallback
    manufacturer = (
        product.manufacturer_name
        or (batch_row.get("manufacturer_name") if batch_row else None)
    )

    # 5. worst colour
    worst_color = "GREEN"
    for ev in events:
        c = rules.classify_event(
            ev.get("event_type"),
            ev.get("status"),
            ev.get("legal_status"),
            ev.get("investigation_status"),
        )
        if rules.color_priority(c) > rules.color_priority(worst_color):
            worst_color = c

    match_items = [_build_match_item(ev) for ev in events]

    if worst_color == "GREEN":
        result = ResultBlock(
            color="GREEN",
            status="NO_REGULATORY_ALERT_FOUND",
            severity="LOW",
            title=rules.title_for("GREEN"),
        )
        safety = SafetyBlock(
            assessment="NOT_PROVEN_SAFE",
            message=(
                "No matching regulatory alert was found in the checked "
                "sources. This does not confirm that the medicine is "
                "medically safe."
            ),
        )
    else:
        primary_status = (
            (match_items[0].regulatory.status if match_items else None)
            or "REGULATORY_CONCERN"
        )
        result = ResultBlock(
            color=worst_color,
            status=primary_status,
            severity=rules.severity_for(worst_color),
            title=rules.title_for(worst_color),
        )
        safety = SafetyBlock(
            assessment=(
                "REGULATORY_ACTION" if worst_color == "RED" else "REGULATORY_CONCERN"
            ),
            message=(
                "A serious regulatory action was reported for this product. "
                "This is not a medical safety assessment."
                if worst_color == "RED"
                else "A regulatory quality or safety concern was reported. "
                "This result is not a medical safety assessment."
            ),
        )

    return ScanResponse(
        result=result,
        match=MatchBlock(type=match_type, confidence=round(confidence, 4)),
        medicine=MedicineBlock(
            id=product.product_id,
            name=product.product_name,
            manufacturer=manufacturer,
        ),
        batch=BatchBlock(
            id=batch_row["id"] if batch_row else None,
            number=batch_row["batch_number"] if batch_row else (batch_number or None),
            manufacturing_date=(
                _iso(batch_row.get("manufacturing_date")) if batch_row else None
            ),
            expiry_date=_iso(batch_row.get("expiry_date")) if batch_row else None,
        ),
        matches=match_items,
        safety=safety,
    )


def _composition_search(db: Session, req: ScanRequest) -> ScanResponse:
    """
    FDC / composition branch. Does not require a commercial product ID.
    Handles scope='COMBINATION' events where product_id IS NULL.
    """
    normalized_ing = normalize_text(req.active_ingredient or req.medicine_name)
    if not normalized_ing:
        return _invalid_input_response()

    # 1. all combination events
    combo_events = queries.get_all_combination_events(db)

    matched: List[Dict[str, Any]] = []
    ing_tokens = [t for t in normalized_ing.split() if len(t) >= 3]

    for ev in combo_events:
        haystack = " ".join(
            str(x)
            for x in (
                ev.get("additional_data"),
                ev.get("reason"),
                ev.get("action"),
                ev.get("legal_reference"),
            )
            if x
        ).lower()
        if all(tok in haystack for tok in ing_tokens) and ing_tokens:
            matched.append(ev)

    if not matched:
        # Fall back to ingredient -> product lookup path
        products = queries.find_products_by_ingredient(db, normalized_ing)
        if not products:
            return _not_found_response(normalized_ing)
        # Simplest presentation: report the products as candidates.
        cands = [
            CandidateItem(
                product_id=r["id"],
                name=r["product_name"],
                manufacturer=r.get("manufacturer_name"),
                score=float(r.get("score") or 0.0),
            )
            for r in products[:10]
        ]
        return ScanResponse(
            result=ResultBlock(
                color="YELLOW",
                status="COMPOSITION_MATCH",
                severity="MEDIUM",
                title="Products matching composition",
            ),
            match=MatchBlock(type="FUZZY", confidence=cands[0].score if cands else 0.0),
            candidates=cands,
            safety=SafetyBlock(
                assessment="UNKNOWN",
                message="Composition matched products; check each product for regulatory events.",
            ),
        )

    worst = "GREEN"
    for ev in matched:
        c = rules.classify_event(
            ev.get("event_type"),
            ev.get("status"),
            ev.get("legal_status"),
            ev.get("investigation_status"),
        )
        if rules.color_priority(c) > rules.color_priority(worst):
            worst = c

    match_items = [_build_match_item(ev) for ev in matched]

    return ScanResponse(
        result=ResultBlock(
            color=worst if worst != "GREEN" else "YELLOW",
            status=(match_items[0].regulatory.status if match_items else "COMBINATION_MATCH"),
            severity=rules.severity_for(worst if worst != "GREEN" else "YELLOW"),
            title="Combination regulatory action found",
        ),
        match=MatchBlock(type="FUZZY", confidence=0.9),
        matches=match_items,
        safety=SafetyBlock(
            assessment="REGULATORY_CONCERN",
            message="A regulatory record exists for this drug combination.",
        ),
    )


def run_scan(db: Session, req: ScanRequest) -> ScanResponse:
    if not (req.medicine_name or req.barcode or req.active_ingredient):
        return _invalid_input_response()

    # Composition-only: no commercial name given.
    if req.active_ingredient and not req.medicine_name:
        return _composition_search(db, req)

    primary = _medicine_search(db, req)

    # Also run composition branch when both were supplied and merge
    # any additional combination-scope matches into the response.
    if req.active_ingredient and req.medicine_name:
        try:
            comp = _composition_search(db, req)
        except Exception:
            comp = None

        if comp and comp.matches:
            existing_keys = {
                (m.source.document_id, m.regulatory.event_type, m.regulatory.reason)
                for m in primary.matches
            }
            for m in comp.matches:
                key = (
                    m.source.document_id,
                    m.regulatory.event_type,
                    m.regulatory.reason,
                )
                if key not in existing_keys:
                    primary.matches.append(m)
                    existing_keys.add(key)

            # Recompute colour from the union of matches.
            worst = "GREEN"
            for m in primary.matches:
                c = rules.classify_event(
                    m.regulatory.event_type,
                    m.regulatory.status,
                    m.regulatory.legal_status,
                    m.regulatory.investigation_status,
                )
                if rules.color_priority(c) > rules.color_priority(worst):
                    worst = c
            if rules.color_priority(worst) > rules.color_priority(primary.result.color):
                primary.result.color = worst
                primary.result.severity = rules.severity_for(worst)
                primary.result.title = rules.title_for(worst)

    return primary