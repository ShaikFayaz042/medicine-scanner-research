"""Application service for scanner-oriented medicine identification."""
from server.repositories.medicine_repository import find_product_by_id, find_products


def _text(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _serialize(product, fields):
    name = (fields.get("name") or "").lower()
    normalized = (product.normalized_search_name or "").lower()
    searchable_text = " ".join(
        filter(
            None,
            [
                product.product_name,
                product.brand_name,
                product.normalized_search_name,
                product.strength,
                *(link.ingredient.name for link in product.ingredients),
                *(link.strength_text for link in product.ingredients),
            ],
        )
    ).lower().replace(" ", "")
    tokens = [token.replace(" ", "") for token in name.split() if token]
    matched_tokens = sum(token in searchable_text for token in tokens)
    relevance = round(50 + (40 * matched_tokens / len(tokens))) if tokens else 50
    if name and normalized.replace(" ", "") == name.replace(" ", ""):
        relevance = 100

    return {
        "id": product.id,
        "relevance": relevance,
        "product": {
            "name": product.product_name,
            "brand_name": product.brand_name,
            "generic_name": None,
            "dosage_form": product.dosage_form,
            "route": None,
            "strength": product.strength,
            "manufacturer": product.manufacturer.name if product.manufacturer else None,
            "ingredients": [
                {
                    "name": link.ingredient.name,
                    "strength": None,
                    "strength_text": link.strength_text,
                    "unit": None,
                }
                for link in product.ingredients
            ],
        },
        "regulatory_events": [
            {
                "event_type": event.event_type,
                "status": event.status,
                "legal_status": event.legal_status,
                "reason": event.reason,
                "effective_date": _text(event.effective_date),
                "source": {
                    "document_id": event.document.id,
                    "title": event.document.title,
                    "document_type": event.document.document_type,
                    "publication_date": _text(event.document.publication_date),
                    "source_url": event.document.source_url,
                    "pdf_filename": event.document.pdf_filename,
                } if event.document else None,
            }
            for event in product.regulatory_events
        ],
        "source_references": [
            {
                "source_record_id": event.source_record_id,
                "document_id": event.document.id,
                "title": event.document.title,
                "source_url": event.document.source_url,
                "pdf_filename": event.document.pdf_filename,
            }
            for event in product.regulatory_events
            if event.document
        ],
    }


def search_medicines(db, fields: dict[str, str], limit: int):
    return [_serialize(product, fields) for product in find_products(db, fields, limit)]


def get_medicine(db, product_id: int):
    product = find_product_by_id(db, product_id)
    return _serialize(product, {}) if product else None
