"""CSV serialization helpers for local and S3 outputs."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def rows_to_csv_bytes(
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def write_csv_file(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rows_to_csv_bytes(rows, fieldnames))
