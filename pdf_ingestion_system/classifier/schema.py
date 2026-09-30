"""Stage 3 output contract."""

CLASSIFIER_VERSION = "v3"


def make_verdict(doc_id, source_name, bucket, bucket_reason, deterministic,
                 ocr_pending, total_text_chars, total_pages):
    """Build the Stage 3 v3 output contract."""
    event_bearing = bucket == "event-bearing"
    needs_review = bucket == "needs_review"
    return {
        "doc_id": doc_id,
        "source_name": source_name,
        "bucket": bucket,
        "bucket_reason": bucket_reason,
        "deterministic": deterministic,
        "gliclass": None,
        "ensemble": None,
        "ocr_pending": ocr_pending,
        "total_text_chars": total_text_chars,
        "total_pages": total_pages,
        "stage3_version": CLASSIFIER_VERSION,
        "is_relevant": event_bearing,
        "needs_review": needs_review,
        "needs_review_reasons": [bucket_reason] if needs_review else [],
        "topical_score": 0.0,
        "record_entity_hits": {
            "batch_numbers": deterministic["paragraph_batch_matches"],
            "manufacturer_names": deterministic["paragraph_manufacturer_matches"],
            "drug_names": deterministic["paragraph_drug_matches"],
        },
        "matched_keywords": {},
        "score_band": None,
    }
