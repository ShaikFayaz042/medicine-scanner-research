"""Application service for scanner-oriented medicine identification."""
from server.repositories.medicine_repository import find_product_by_id, search_medicine_products


def _text(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _contains(haystack, needle):
    return bool(haystack and needle and needle.casefold() in haystack.casefold())


def _matching_batches(product, batch_number):
    if not batch_number:
        return []
    return [batch for batch in product.batches if _contains(batch.batch_number, batch_number)]


def _relevant_events(product, batch_number, matching_batches):
    if not batch_number:
        return list(product.regulatory_events)

    matching_batch_ids = {batch.id for batch in matching_batches}
    relevant = []
    for event in product.regulatory_events:
        if event.batch_id is not None:
            if event.batch_id in matching_batch_ids:
                relevant.append(event)
        elif (event.scope or "").upper() != "BATCH":
            relevant.append(event)
    return relevant


def _serialize_event(event):
    document = event.document
    return {
        "event_id": event.id,
        "source_record_id": event.source_record_id,
        "event_type": event.event_type,
        "scope": event.scope,
        "batch_number": event.batch.batch_number if event.batch else None,
        "status": event.status,
        "legal_status": event.legal_status,
        "reason": event.reason,
        "effective_date": _text(event.effective_date),
        "source": {
            "document_id": document.id,
            "source_org": getattr(document, "source_org", None),
            "title": document.title,
            "document_type": document.document_type,
            "publication_date": _text(document.publication_date),
            "source_url": document.source_url,
            "pdf_filename": document.pdf_filename,
        } if document else None,
    }


def _build_assessment(events):
    disclaimer = (
        "This result reflects the regulatory records available in the system. "
        "It does not verify the authenticity of a physical pack and is not medical advice."
    )
    recognized_scopes = {"BATCH", "PRODUCT", "INGREDIENT", "COMBINATION"}

    if not events:
        return {
            "indicator": "GREEN",
            "template_id": "NO_MATCHING_ALERT",
            "summary": (
                "No matching regulatory alert was found for this medicine in the available records. "
                "This does not guarantee that the medicine is safe."
            ),
            "disclaimer": disclaimer,
        }

    if any((event.get("scope") or "").upper() not in recognized_scopes for event in events):
        return {
            "indicator": "UNKNOWN",
            "template_id": "UNCLEAR_EVENT_SCOPE",
            "summary": (
                "A regulatory record was found, but its applicable scope is unclear. "
                "Review the official source record before drawing a conclusion."
            ),
            "disclaimer": disclaimer,
        }

    uncertain_legal_statuses = {"UNKNOWN", "QUASHED", "STAYED", "REVOKED_WITH_CONDITIONS"}
    if any(
        (event.get("legal_status") or "").upper() in uncertain_legal_statuses
        for event in events
    ):
        return {
            "indicator": "UNKNOWN",
            "template_id": "UNCLEAR_LEGAL_STATUS",
            "summary": (
                "A regulatory record was found, but the available legal status does not support "
                "a reliable current conclusion. Review the official source record."
            ),
            "disclaimer": disclaimer,
        }

    if any(
        (event.get("legal_status") or "").upper() in {"PROHIBITED", "RESTRICTED"}
        and not event.get("source")
        for event in events
    ):
        return {
            "indicator": "UNKNOWN",
            "template_id": "UNSUPPORTED_LEGAL_RESTRICTION",
            "summary": (
                "A legal restriction is recorded, but its supporting source is unavailable. "
                "Review the official record before drawing a conclusion."
            ),
            "disclaimer": disclaimer,
        }

    restrictions = [
        event for event in events
        if (event.get("legal_status") or "").upper() in {"PROHIBITED", "RESTRICTED"}
        and event.get("source")
    ]
    if restrictions:
        event = restrictions[0]
        scope = event["scope"].lower()
        batch_text = f" for batch {event['batch_number']}" if event.get("batch_number") else ""
        legal_status = event["legal_status"].lower()
        return {
            "indicator": "RED",
            "template_id": "LEGAL_RESTRICTION",
            "summary": (
                f"An applicable {scope}-level legal {legal_status} is recorded{batch_text}. "
                "Review the official source record for details."
            ),
            "disclaimer": disclaimer,
        }

    concern_types = {
        "QUALITY_FAILURE", "QUALITY_ALERT", "INVESTIGATION", "CAUTION",
        "SPURIOUS", "NSQ", "COUNTERFEIT", "RECALL", "WARNING",
    }
    concern_statuses = {
        "NOT_OF_STANDARD_QUALITY", "SPURIOUS", "NSQ", "UNDER_INVESTIGATION",
        "CAUTION", "RECALLED", "WARNING",
    }
    is_concern = any(
        (item.get("event_type") or "").upper() in concern_types
        or (item.get("status") or "").upper() in concern_statuses
        for item in events
    )
    if not is_concern:
        return {
            "indicator": "UNKNOWN",
            "template_id": "INSUFFICIENT_REGULATORY_EVIDENCE",
            "summary": (
                "A regulatory record was found, but its meaning does not establish a safety conclusion. "
                "Review the official source record."
            ),
            "disclaimer": disclaimer,
        }
    event = next(
        item for item in events
        if (item.get("event_type") or "").upper() in concern_types
        or (item.get("status") or "").upper() in concern_statuses
    )
    scope = event["scope"].lower()
    batch_text = f" for batch {event['batch_number']}" if event.get("batch_number") else ""
    reason_text = f" Reason recorded: {event['reason']}." if event.get("reason") else ""
    is_batch_quality_alert = (
        scope == "batch"
        and (
            (event.get("event_type") or "").upper() in {"QUALITY_FAILURE", "QUALITY_ALERT"}
            or (event.get("status") or "").upper() == "NOT_OF_STANDARD_QUALITY"
        )
    )
    template_id = "BATCH_QUALITY_ALERT" if is_batch_quality_alert else "REGULATORY_CONCERN"
    summary = (
        f"A {scope}-level regulatory concern is recorded{batch_text}."
        f"{reason_text} Review the official source record for details."
    )
    return {
        "indicator": "YELLOW",
        "template_id": template_id,
        "summary": summary,
        "disclaimer": disclaimer,
    }


def _matched_by(product, fields, match_type, matched_batches):
    matched = []
    name_tokens = (fields.get("name") or "").split()
    name_values = {
        "product_name": [product.product_name, product.normalized_search_name],
        "brand_name": [product.brand_name],
        "ingredient": [
            value
            for item in product.ingredients
            for value in (item.ingredient.name, item.ingredient.normalized_name)
        ],
        "strength": [
            value
            for item in product.ingredients
            for value in (item.strength_text,)
        ],
    }
    if name_tokens:
        for token in name_tokens:
            for label, values in name_values.items():
                if any(_contains(value, token) for value in values):
                    matched.append(label)
        if match_type == "FUZZY" and not any(
            label in matched for label in ("product_name", "brand_name", "generic_name")
        ):
            matched.append("product_name")

    if fields.get("manufacturer") and product.manufacturer and _contains(
        product.manufacturer.name, fields["manufacturer"]
    ):
        matched.append("manufacturer")
    if fields.get("ingredient"):
        ingredient_tokens = fields["ingredient"].split()
        if all(
            any(
                _contains(ingredient.name, token)
                or _contains(ingredient.normalized_name, token)
                for ingredient in (item.ingredient for item in product.ingredients)
            )
            for token in ingredient_tokens
        ):
            matched.append("ingredient")
    if fields.get("strength") and any(
        _contains(item.strength_text, fields["strength"])
        for item in product.ingredients
    ) or fields.get("strength") and _contains(getattr(product, "strength", None), fields["strength"]):
        matched.append("strength")
    if fields.get("dosage_form") and _contains(product.dosage_form, fields["dosage_form"]):
        matched.append("dosage_form")
    if matched_batches:
        matched.append("batch_number")
    return list(dict.fromkeys(matched))


def _product_strength(product):
    values = []
    for item in product.ingredients:
        value = item.strength_text
        if value and value not in values:
            values.append(value)
    return ", ".join(values) or getattr(product, "strength", None)


def _serialize_product(product):
    return {
        "name": product.product_name,
        "brand_name": product.brand_name,
        "generic_name": getattr(product, "generic_name", None),
        "dosage_form": product.dosage_form,
        "route": getattr(product, "route", None),
        "strength": _product_strength(product),
        "manufacturer": product.manufacturer.name if product.manufacturer else None,
        "ingredients": [
            {
                "name": item.ingredient.name,
                "strength": None,
                "strength_text": item.strength_text,
                "unit": None,
            }
            for item in product.ingredients
        ],
    }


def _serialize_match(product, relevance, match_type, fields):
    matching_batches = _matching_batches(product, fields.get("batch_number", ""))
    relevant_event_objects = _relevant_events(
        product, fields.get("batch_number", ""), matching_batches
    )
    events = [_serialize_event(event) for event in relevant_event_objects]
    source_references = []
    seen_sources = set()
    for event_object, event in zip(relevant_event_objects, events):
        source = event["source"]
        if not source:
            continue
        reference = {
            "source_record_id": event_object.source_record_id,
            "document_id": source["document_id"],
            "source_org": source["source_org"],
            "title": source["title"],
            "document_type": source["document_type"],
            "publication_date": source["publication_date"],
            "source_url": source["source_url"],
            "pdf_filename": source["pdf_filename"],
        }
        key = (reference["document_id"], reference["source_record_id"])
        if key not in seen_sources:
            seen_sources.add(key)
            source_references.append(reference)

    return {
        "id": product.id,
        "relevance": relevance,
        "match_type": match_type,
        "matched_by": _matched_by(product, fields, match_type, matching_batches),
        "product": _serialize_product(product),
        "assessment": _build_assessment(events),
        "regulatory_events": events,
        "source_references": source_references,
    }


def _serialize(product, fields):
    relevant_event_objects = list(product.regulatory_events)
    events = [_serialize_event(event) for event in relevant_event_objects]
    return {
        "id": product.id,
        "product": _serialize_product(product),
        "assessment": _build_assessment(events),
        "regulatory_events": events,
        "source_references": [
            {
                "source_record_id": event_object.source_record_id,
                "document_id": event["source"]["document_id"],
                "source_org": event["source"]["source_org"],
                "title": event["source"]["title"],
                "document_type": event["source"]["document_type"],
                "publication_date": event["source"]["publication_date"],
                "source_url": event["source"]["source_url"],
                "pdf_filename": event["source"]["pdf_filename"],
            }
            for event_object, event in zip(relevant_event_objects, events)
            if event.get("source")
        ],
        "matched_by": _matched_by(product, fields, "EXACT", []),
    }


def search_medicines(db, fields: dict[str, str], limit: int, query=None):
    query_fields = query or {
        key: fields.get(key) or None
        for key in ("name", "manufacturer", "ingredient", "strength", "dosage_form", "batch_number")
    }
    if not any(value for value in fields.values()):
        return {
            "query": query_fields,
            "search_status": "NO_PRODUCT_MATCH",
            "count": 0,
            "limit": limit,
            "has_more": False,
            "matches": [],
        }

    matches, has_more = search_medicine_products(db, fields, limit)
    serialized_matches = [
        _serialize_match(product, relevance, match_type, fields)
        for product, relevance, match_type in matches
    ]
    return {
        "query": query_fields,
        "search_status": "MATCHED" if serialized_matches else "NO_PRODUCT_MATCH",
        "count": len(serialized_matches),
        "limit": limit,
        "has_more": has_more,
        "matches": serialized_matches,
    }


def get_medicine(db, product_id: int):
    product = find_product_by_id(db, product_id)
    return _serialize(product, {}) if product else None
