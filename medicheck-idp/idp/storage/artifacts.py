"""Read and write pipeline artifacts on the local filesystem.

Profiler artifacts use data/artifacts/profiles/<doc_id>/<name>.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def path(name: str, doc_id: str) -> Path:
    env_root = os.getenv("IDP_DATA_DIR")
    root = Path(env_root).expanduser() if env_root else Path("data")
    if not root.is_absolute():
        root = _project_root() / root
    return root / "artifacts" / "profiles" / doc_id / f"{name}.json"


def _legacy_path(name: str, doc_id: str) -> Path:
    env_root = os.getenv("IDP_DATA_DIR")
    root = Path(env_root).expanduser() if env_root else Path("data")
    if not root.is_absolute():
        root = _project_root() / root
    return root / "artifacts" / doc_id / f"{name}.json"


def _local_path(uri: str | Path) -> Path:
    value = str(uri)
    if value.lower().startswith("s3://"):
        raise ValueError("S3 artifact URIs are not supported; use a local filesystem path.")
    return Path(uri).expanduser()


def join(base: str | Path, name: str | Path) -> str:
    return str(_local_path(base) / _local_path(name))


def read_json(uri: str | Path) -> Any:
    return json.loads(_local_path(uri).read_text(encoding="utf-8-sig"))


def write_json(uri: str | Path, value: Any) -> None:
    target = _local_path(uri)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def list_json(uri: str | Path) -> list[str]:
    """List JSON files under a local directory, or return a single JSON file."""
    target = _local_path(uri)
    if target.is_file():
        return [str(target)]
    return sorted(str(item) for item in target.rglob("*.json"))


def save(name: str, doc_id: str, model: BaseModel) -> Path:
    p = path(name, doc_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(model.model_dump_json(indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


def load(name: str, doc_id: str, cls: type[T]) -> T | None:
    """None if missing or unreadable (a bad cache is a cache miss, not a crash)."""
    p = path(name, doc_id)
    try:
        return cls.model_validate_json(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        legacy = _legacy_path(name, doc_id)
        try:
            return cls.model_validate_json(legacy.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return None
