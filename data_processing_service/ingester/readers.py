"""Readers and value parsers for normalized ingestion CSVs."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        return value
    return value


def _parse_database_date(value: Any) -> date | None:
    clean = _clean_value(value)
    if not isinstance(clean, str):
        return None
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(clean, date_format).date()
        except ValueError:
            continue
        if parsed.strftime(date_format) == clean:
            return parsed
    return None


def _parse_json_value(value: Any) -> Any:
    clean = _clean_value(value)
    if clean is None:
        return None
    if isinstance(clean, str):
        stripped = clean.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None
    return clean


def _read_csv_rows(csv_path: Path) -> list[dict[str, Any]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return []
        return [
            {key: _clean_value(value) for key, value in row.items()}
            for row in reader
        ]


def _validity_map(folder_path: Path) -> tuple[dict[str, set[str]] | None, bool]:
    manifest_path = folder_path / "normalization_manifest.csv"
    if not manifest_path.exists():
        return None, False

    valid_keys = {
        "source_record_id": set(),
        "organization_key": set(),
        "product_key": set(),
        "batch_key": set(),
        "event_key": set(),
    }
    manifest_rows = _read_csv_rows(manifest_path)
    for row in manifest_rows:
        status = (row.get("validation_status") or "").strip().upper()
        if status != "VALID":
            continue
        for key_column in valid_keys:
            key = (row.get(key_column) or "").strip()
            if key:
                valid_keys[key_column].add(key)
    return valid_keys, True
