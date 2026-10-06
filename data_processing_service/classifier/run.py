"""Stage 3 classification for S3-backed extracted PDFs.

This module applies deterministic rules and GLiClass to extracted JSON from S3
and writes verdicts back to S3.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import boto3

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_processing_service.shared.config import (
    AWS_REGION,
    S3_INPUT_BUCKET,
    S3_OUTPUT_BUCKET,
    S3_OUTPUT_PREFIX,
)
from data_processing_service.classifier.payload import (
    language_text_from_payload,
    normalize_extracted_payload,
)
from data_processing_service.classifier.schema import complete_classifier_fields
from data_processing_service.shared.database import update_classified_documents
from data_processing_service.shared.manifest import result_key, utc_now_iso, write_result
from data_processing_service.classifier.driver import classify_document, load_medicine_lexicons
from data_processing_service.classifier.gliclass import enrich_verdict

DEFAULT_S3_INPUT_BUCKET = S3_INPUT_BUCKET
DEFAULT_S3_INPUT_PREFIX = "medicine-data-storage/processed_files/extracted_json"
DEFAULT_S3_OUTPUT_BUCKET = S3_OUTPUT_BUCKET or S3_INPUT_BUCKET
DEFAULT_S3_OUTPUT_PREFIX = "medicine-data-storage/processed_files/classifier_output"
DEFAULT_AWS_REGION = AWS_REGION


def _relative_from_prefix(key: str, prefix: str) -> str:
    normalized_prefix = prefix.strip("/")
    if not normalized_prefix:
        return key.lstrip("/")
    if key == normalized_prefix:
        return ""
    if key.startswith(normalized_prefix + "/"):
        return key[len(normalized_prefix) + 1 :]
    return key.lstrip("/")


def _input_json_prefix(input_prefix: str) -> str:
    return input_prefix.strip("/")


def collect_s3_json_documents(s3_client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    keys: list[str] = []
    scan_prefix = prefix.strip("/")
    for page in paginator.paginate(Bucket=bucket, Prefix=scan_prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            suffix = PurePosixPath(key).suffix.lower()
            if suffix == ".json":
                keys.append(key)
    return sorted(keys, key=str.casefold)


def collect_extractor_result_keys(
    s3_client: Any,
    bucket: str,
    run_id: str,
) -> list[str]:
    key = result_key(run_id, "extractor")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    payload = json.loads(response["Body"].read().decode("utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Extractor result must be a JSON object")
    if payload.get("run_id") != run_id or payload.get("stage") != "extractor":
        raise ValueError(f"Extractor result does not belong to run {run_id!r}")
    output_keys = payload.get("output_keys")
    if not isinstance(output_keys, list):
        raise ValueError("Extractor result must contain an output_keys array")
    return list(dict.fromkeys(
        key for key in output_keys
        if isinstance(key, str) and PurePosixPath(key).suffix.casefold() == ".json"
    ))


def _prefix_for_extractor_outputs(keys: list[str], fallback: str) -> str:
    prefixes = set()
    for key in keys:
        parts = PurePosixPath(key).parts
        extracted_index = next(
            (index for index in range(len(parts) - 1, -1, -1) if parts[index] == "extracted_json"),
            None,
        )
        if extracted_index is not None:
            prefixes.add(PurePosixPath(*parts[:extracted_index + 1]).as_posix())
    return prefixes.pop() if len(prefixes) == 1 else fallback.strip("/")


def _language_text_from_extracted_payload(payload: dict[str, Any]) -> str:
    normalized = normalize_extracted_payload(payload)
    return language_text_from_payload(normalized)


def _apply_classifier(payload: dict[str, Any], products: Any, ingredients: Any) -> dict[str, Any]:
    normalized = normalize_extracted_payload(payload)
    text = language_text_from_payload(normalized)
    verdict = classify_document(normalized, products, ingredients)
    filename = payload.get("pdf_title") or payload.get("doc_id") or None
    verdict = complete_classifier_fields(verdict, text, filename=filename)
    pending_review = bool(verdict.get("needs_review"))
    pending_review_reasons = set(verdict.get("needs_review_reasons") or [])
    text_map = {verdict.get("doc_id", "unknown"): text}
    enriched = enrich_verdict(verdict, text_map)
    if pending_review:
        enriched["needs_review"] = True
        reasons = set(enriched.get("needs_review_reasons") or [])
        reasons.update(pending_review_reasons)
        enriched["needs_review_reasons"] = sorted(reasons)
    gliclass = enriched.get("gliclass") or {}
    if gliclass.get("verdict") == "needs_review" and not enriched.get("needs_review"):
        reasons = set(enriched.get("needs_review_reasons") or [])
        if enriched.get("bucket") == "event-bearing" or "weak_event_signal" in reasons:
            enriched["needs_review"] = True
            reasons.add("gliclass_uncertain")
            enriched["needs_review_reasons"] = sorted(reasons)
    return enriched


def _strip_source_root_segment(relative: str) -> str:
    cleaned = relative.strip("/")
    if not cleaned:
        return ""
    if cleaned == "source_files":
        return ""
    if cleaned.startswith("source_files/"):
        return cleaned[len("source_files/") :]
    return cleaned


def _safe_title_filename(value: str | None, fallback: str = "document") -> str:
    candidate = str(value or fallback).strip()
    candidate = re.sub(r"[^\w\s.\-]", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" .")
    candidate = re.sub(r"\s+", "_", candidate)
    candidate = candidate[:120] or fallback
    return candidate


def _s3_output_key_for(
    payload: dict[str, Any],
    source_prefix: str,
    output_prefix: str,
    input_key: str | None = None,
) -> str:
    relative_name = _relative_from_prefix(
        input_key or str(payload.get("s3_object_key") or payload.get("doc_id") or ""),
        source_prefix,
    )
    relative_parts = [
        _safe_title_filename(part, fallback="document")
        for part in PurePosixPath(relative_name.replace("\\", "/")).parts
        if part not in {"", ".", "..", "/"}
    ]
    if not relative_parts:
        title = payload.get("pdf_title") or payload.get("title") or payload.get("doc_id")
        relative_parts = [_safe_title_filename(str(title or "document"), "document") + ".json"]
    safe_prefix = output_prefix.strip("/")
    document_path = PurePosixPath("per_doc", *relative_parts)
    return str(PurePosixPath(safe_prefix) / document_path) if safe_prefix else str(document_path)


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def write_classifier_csv_to_s3(s3_client: Any, bucket: str, output_prefix: str, rows: list[dict[str, Any]]) -> str:
    safe_prefix = output_prefix.rstrip("/")
    output_key = f"{safe_prefix}/classification_summary.csv"
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(str(key))
    fieldnames = sorted(fieldnames, key=lambda key: key.lower())

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})

    s3_client.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=buffer.getvalue().encode("utf-8"),
        ContentType="text/csv; charset=utf-8",
    )
    return output_key


def write_classifier_json_to_s3(
    s3_client: Any,
    bucket: str,
    output_key: str,
    verdict: dict[str, Any],
) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=output_key,
        Body=json.dumps(verdict, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply Stage 3 deterministic + GLiClass classification to extracted S3 PDFs."
    )
    parser.add_argument("--bucket", default=DEFAULT_S3_INPUT_BUCKET, help="S3 bucket containing extracted JSON")
    parser.add_argument("--prefix", default=DEFAULT_S3_INPUT_PREFIX, help="S3 prefix for extracted JSON files")
    parser.add_argument("--region", default=DEFAULT_AWS_REGION, help="AWS region")
    parser.add_argument("--s3-output-bucket", default=DEFAULT_S3_OUTPUT_BUCKET, help="Bucket for classified JSON output")
    parser.add_argument("--s3-output-prefix", default=DEFAULT_S3_OUTPUT_PREFIX, help="Base S3 key prefix for verdict output")
    parser.add_argument("--doc-id", help="Process only this exact extracted JSON S3 key")
    parser.add_argument("--run-id", help="Run identifier for the S3 manifest")
    parser.add_argument("--manifest-s3-key", help="S3 key for the pipeline manifest JSON")
    parser.add_argument("--limit", type=int, default=0, help="Optional document limit")
    args = parser.parse_args(argv)
    started_at = utc_now_iso()

    if not args.bucket:
        parser.error("--bucket is required")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    s3_client = boto3.client("s3", region_name=args.region)
    input_prefix = _input_json_prefix(args.prefix)
    manifest_mode = bool(args.manifest_s3_key and args.run_id)
    if manifest_mode:
        documents = collect_extractor_result_keys(s3_client, args.bucket, args.run_id)
        input_prefix = _prefix_for_extractor_outputs(documents, input_prefix)
    else:
        documents = collect_s3_json_documents(s3_client, args.bucket, input_prefix)
    if args.doc_id:
        documents = [key for key in documents if key == args.doc_id]
    if args.limit:
        documents = documents[:args.limit]
    if args.doc_id and not documents:
        print(f"No matching extracted JSON object: {args.doc_id}", file=sys.stderr)
        return 1

    products, ingredients = load_medicine_lexicons()

    classified_keys: list[str] = []
    output_keys: list[str] = []
    classification_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    failed = 0
    for index, s3_key in enumerate(documents, start=1):
        try:
            response = s3_client.get_object(Bucket=args.bucket, Key=s3_key)
            payload = json.loads(response["Body"].read().decode("utf-8"))
            source_key = payload.get("s3_object_key") or s3_key
            verdict = _apply_classifier(payload, products, ingredients)
            verdict["s3_object_key"] = source_key
            output_json_key = _s3_output_key_for(
                payload, input_prefix, args.s3_output_prefix, input_key=s3_key
            )
            verdict["classifier_output_key"] = output_json_key
            write_classifier_json_to_s3(
                s3_client, args.s3_output_bucket, output_json_key, verdict
            )
            output_keys.append(output_json_key)
            classification_rows.append(verdict)
            classified_keys.append(source_key)
            print(f"Classified {index}/{len(documents)}: {s3_key}")
        except Exception as exc:
            failed += 1
            errors.append(f"{s3_key}: {exc}")
            print(f"ERROR classifying {s3_key}: {exc}", file=sys.stderr)

    output_key = write_classifier_csv_to_s3(s3_client, args.s3_output_bucket, args.s3_output_prefix, classification_rows)
    print(f"Classification CSV written to s3://{args.s3_output_bucket}/{output_key}")
    update_classified_documents(classified_keys)
    print(f"Classification complete: {len(classified_keys)}/{len(documents)} documents")
    if args.run_id and args.bucket:
        write_result(
            s3_client,
            args.bucket,
            args.run_id,
            "classifier",
            {
                "schema_version": 1,
                "stage": "classifier",
                "run_id": args.run_id,
                "started_at": started_at,
                "finished_at": utc_now_iso(),
                "status": "failure" if failed else "success",
                "input_keys": documents,
                "output_keys": [*output_keys, output_key],
                "error": "; ".join(errors) or None,
            },
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
