"""
Freeze CSV exports by computing SHA-256, row count, size, and header.
Writes _FREEZE.json next to the CSVs. Use --verify to detect drift later.

Usage:
    python scripts/freeze_csv.py --freeze --version 0.1.0
    python scripts/freeze_csv.py --verify
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    ROOT / "structured_raw" / "csv",
    ROOT / "downloads" / "nsq_json" / "csv",
]
FREEZE_FILE = "_FREEZE.json"


def sha256_of(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def csv_meta(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            header = []
        row_count = sum(1 for _ in reader)
    return {"header": header, "row_count": row_count}


def describe_csv(path: Path) -> dict:
    meta = csv_meta(path)
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "row_count": meta["row_count"],
        "header": meta["header"],
    }


def scan_dir(dir_path: Path) -> dict:
    if not dir_path.exists():
        return {"dir": str(dir_path.relative_to(ROOT)), "exists": False, "files": []}
    files = [describe_csv(p) for p in sorted(dir_path.glob("*.csv"))]
    return {
        "dir": str(dir_path.relative_to(ROOT)),
        "exists": True,
        "file_count": len(files),
        "files": files,
    }


def do_freeze(version: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    for target in TARGETS:
        if not target.exists():
            print(f"[skip] missing dir: {target}")
            continue
        payload = {
            "frozen_version": version,
            "frozen_at": now,
            "tool": "scripts/freeze_csv.py",
            **scan_dir(target),
        }
        out = target / FREEZE_FILE
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[freeze] {out}  ({payload['file_count']} files)")
    return 0


def do_verify() -> int:
    problems: list[str] = []
    for target in TARGETS:
        manifest_path = target / FREEZE_FILE
        if not manifest_path.exists():
            problems.append(f"NO_MANIFEST: {manifest_path}")
            continue
        frozen = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = {f["name"]: f for f in frozen.get("files", [])}
        current = {f["name"]: f for f in scan_dir(target)["files"]}
        for name, exp in expected.items():
            cur = current.get(name)
            if cur is None:
                problems.append(f"MISSING: {target.name}/{name}")
                continue
            if cur["sha256"] != exp["sha256"]:
                problems.append(
                    f"CHANGED: {target.name}/{name} "
                    f"(rows {exp['row_count']} -> {cur['row_count']})"
                )
            if cur["header"] != exp["header"]:
                problems.append(f"HEADER_CHANGED: {target.name}/{name}")
        for name in current:
            if name not in expected:
                problems.append(f"NEW_FILE: {target.name}/{name}")

    if problems:
        print("CSV DRIFT DETECTED:")
        for p in problems:
            print("  -", p)
        return 1
    print("OK: all CSVs match their frozen manifests.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--version", default="0.1.0")
    args = ap.parse_args()
    if args.freeze == args.verify:
        ap.error("Pass exactly one of --freeze or --verify")
    return do_freeze(args.version) if args.freeze else do_verify()


if __name__ == "__main__":
    sys.exit(main())