"""Validate source_record_id values against structured_raw records."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUT_DIR, STRUCTURED_RAW  # noqa: E402

TARGET_FILES = ["events.jsonl", "products.jsonl", "manufacturers.jsonl", "batches.jsonl", "ingredients.jsonl"]
SOURCE_ID_RE = re.compile(r"^(?P<folder>[^/]+)/(?P<filename>[^/]+\.json)#(?P<index>\d+)$")


def main() -> int:
    problems: list[str] = []
    cache: dict[Path, list] = {}
    for name in TARGET_FILES:
        path = OUTPUT_DIR / name
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                row = json.loads(line)
                source_ids = []
                if row.get("source_record_id"):
                    source_ids.append(row["source_record_id"])
                source_ids.extend(row.get("source_record_ids", []))
                for source_id in source_ids:
                    match = SOURCE_ID_RE.fullmatch(source_id)
                    if not match:
                        problems.append(f"{name}:{line_number}: malformed source_record_id: {source_id}")
                        continue
                    source_path = STRUCTURED_RAW / match.group("folder") / match.group("filename")
                    if not source_path.exists():
                        problems.append(f"{name}:{line_number}: missing file: {source_id}")
                        continue
                    if source_path not in cache:
                        try:
                            payload = json.loads(source_path.read_text(encoding="utf-8"))
                            cache[source_path] = payload.get("records") or []
                        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                            problems.append(f"{name}:{line_number}: invalid JSON {source_path}: {exc}")
                            cache[source_path] = []
                    index = int(match.group("index"))
                    if index >= len(cache[source_path]):
                        problems.append(f"{name}:{line_number}: index out of range: {source_id}")

    if problems:
        print(f"VALIDATION FAILED: {len(problems)} problems")
        for problem in problems[:50]:
            print(" -", problem)
        return 1
    print("OK: all source_record_id values resolve to structured_raw records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
