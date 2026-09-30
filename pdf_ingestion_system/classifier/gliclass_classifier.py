"""GLiClass inference and verdict enrichment used by S3 classification."""

from __future__ import annotations

import time
from typing import Any

MODEL_ID = "knowledgator/gliclass-small-v1.0"
PIPELINE_TYPE = "single-label"
DEVICE = "cpu"
FULL_TEXT_LIMIT_CHARS = 4000
SAMPLE_CHUNK_CHARS = 800
SAMPLE_POINTS = 5
SAMPLE_SEPARATOR = "\n[...sample...]\n"
UNIFORM_SCORE_THRESHOLD = 0.34
THRESHOLD = 0.0

RELEVANCE_LABELS = [
    "regulatory drug alert or notification",
    "administrative or procedural notice",
    "general guidance or policy document",
]
RELEVANT_LABELS = {"regulatory drug alert or notification"}
CLASSIFIER_VERSION = "gliclass-small-v1.0-singlelabel-multipoint-v4"

_PIPELINE = None


def load_classifier():
    """Load GLiClass once and cache the pipeline for the full run."""
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE

    print(f"Loading GLiClass: {MODEL_ID} (device={DEVICE})")
    started = time.time()

    import torch
    from gliclass import GLiClassModel, ZeroShotClassificationPipeline
    from transformers import AutoTokenizer

    model = GLiClassModel.from_pretrained(MODEL_ID)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    _PIPELINE = ZeroShotClassificationPipeline(
        model,
        tokenizer,
        max_length=512,
        classification_type=PIPELINE_TYPE,
        device=torch.device(DEVICE),
        progress_bar=False,
    )
    print(f"  loaded in {time.time() - started:.1f}s")
    return _PIPELINE


def classify_text(text):
    """Classify one document's text and return a normalized result."""
    if not text or len(text.strip()) < 20:
        return None

    pipeline = load_classifier()
    samples = text.split(SAMPLE_SEPARATOR)
    try:
        result = pipeline(
            samples,
            RELEVANCE_LABELS,
            threshold=THRESHOLD,
            batch_size=min(8, len(samples)),
            return_hierarchical=True,
        )
    except Exception as exc:
        return {
            "scores": {},
            "top_label": None,
            "top_score": 0.0,
            "verdict": "error",
            "error": str(exc)[:200],
            "method": CLASSIFIER_VERSION,
        }

    if not result:
        return {
            "scores": {},
            "top_label": None,
            "top_score": 0.0,
            "verdict": "unknown",
            "method": CLASSIFIER_VERSION,
        }

    averaged_scores = {
        label: sum(float(sample.get(label, 0.0)) for sample in result) / len(result)
        for label in RELEVANCE_LABELS
    }
    pairs = sorted(averaged_scores.items(), key=lambda pair: -pair[1])
    top_label, top_score = pairs[0]
    uniform = top_score <= UNIFORM_SCORE_THRESHOLD
    return {
        "scores": {label: round(score, 4) for label, score in pairs},
        "top_label": top_label,
        "top_score": round(top_score, 4),
        "sample_count": len(result),
        "sample_top_labels": [max(sample, key=sample.get) for sample in result],
        "verdict": (
            "needs_review" if uniform
            else "relevant" if top_label in RELEVANT_LABELS
            else "not_relevant"
        ),
        "reason": "gliclass_uniform" if uniform else None,
        "method": CLASSIFIER_VERSION,
    }


def build_sample_text(full_text):
    """Sample the head, evenly spaced sections, and tail of long documents."""
    if len(full_text) <= FULL_TEXT_LIMIT_CHARS:
        return full_text

    chunk_size = min(SAMPLE_CHUNK_CHARS, len(full_text))
    final_start = len(full_text) - chunk_size
    positions = sorted({
        round(index * final_start / (SAMPLE_POINTS - 1))
        for index in range(SAMPLE_POINTS)
    })
    return SAMPLE_SEPARATOR.join(
        full_text[position:position + chunk_size] for position in positions
    )


def format_score(value):
    """Format a model score, including skipped results."""
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "n/a"


def enrich_verdict(verdict, text_map, filter_buckets=None):
    """Add GLiClass output to one deterministic verdict."""
    deterministic_bucket = verdict.get("bucket", "unimportant")
    if deterministic_bucket == "event-bearing":
        verdict["gliclass"] = {
            "top_label": None,
            "top_score": None,
            "verdict": None,
            "skipped": True,
            "reason": "deterministic_event_signal",
            "method": CLASSIFIER_VERSION,
        }
    elif filter_buckets is not None and deterministic_bucket not in filter_buckets:
        verdict["gliclass"] = {
            "top_label": None,
            "top_score": None,
            "verdict": None,
            "skipped": True,
            "reason": "bucket_filtered",
            "method": CLASSIFIER_VERSION,
        }
    else:
        text = text_map.get(verdict.get("doc_id"))
        verdict["gliclass"] = classify_text(text) or {
            "top_label": None,
            "top_score": None,
            "verdict": None,
            "skipped": True,
            "reason": "no_text",
            "method": CLASSIFIER_VERSION,
        }

    final_bucket, ensemble_reason = decide_ensemble_verdict(
        deterministic_bucket, verdict["gliclass"]
    )
    verdict["ensemble"] = {
        "final_verdict": final_bucket,
        "reason": ensemble_reason,
        "verdict": final_bucket,
        "gliclass_verdict": verdict["gliclass"].get("verdict"),
        "gliclass_confidence": verdict["gliclass"].get("top_score"),
    }
    verdict["bucket"] = final_bucket
    verdict["bucket_reason"] = ensemble_reason
    verdict["needs_review"] = final_bucket == "needs_review"
    verdict["needs_review_reasons"] = [ensemble_reason] if verdict["needs_review"] else []
    verdict["is_relevant"] = final_bucket == "event-bearing"
    return verdict


def decide_ensemble_verdict(deterministic_bucket, gliclass_block):
    """Return the final bucket and reason under the v2 ensemble thresholds."""
    if deterministic_bucket == "event-bearing":
        return "event-bearing", "deterministic_event_signal"
    confirmation_reason = (
        "context_confirmed" if deterministic_bucket == "context-only" else "unimportant"
    )
    if not gliclass_block or gliclass_block.get("skipped"):
        return deterministic_bucket, confirmation_reason

    glc_verdict = gliclass_block.get("verdict")
    confidence = float(gliclass_block.get("top_score") or 0.0)
    if glc_verdict == "relevant":
        if confidence >= 0.70:
            reason = (
                "context_override_model_strong"
                if deterministic_bucket == "context-only"
                else "unimportant_override_model_strong"
            )
            return "event-bearing", reason
        if confidence >= 0.50:
            reason = (
                "context_model_uncertain"
                if deterministic_bucket == "context-only"
                else "unimportant_model_uncertain"
            )
            return "needs_review", reason
    return deterministic_bucket, confirmation_reason


def summarize_glc_decision(deterministic_bucket, gliclass_block, final_bucket):
    """Return auditable GLiClass fire, rescue, confirmation, and override flags."""
    fired = bool(gliclass_block) and not gliclass_block.get("skipped")
    return {
        "fired": fired,
        "rescued": fired and deterministic_bucket == "context-only" and final_bucket == "event-bearing",
        "confirmed": fired and final_bucket == deterministic_bucket,
        "overrode_to_unimportant": fired and deterministic_bucket != "unimportant" and final_bucket == "unimportant",
        "confirmed_unimportant": fired and deterministic_bucket == "unimportant" and final_bucket == "unimportant",
    }