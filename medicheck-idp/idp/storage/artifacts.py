"""Stage artifacts: data/artifacts/<doc_id>/<name>.json  (local dev).

Two functions are the whole contract, so swapping to S3 later changes only
this file. Writes are atomic: a crash never leaves a half-written artifact.
"""
from __future__ import annotations

import os
from pathlib import Path
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