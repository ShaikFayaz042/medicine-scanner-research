"""Read and write pipeline artifacts on the local filesystem."""
from __future__ import annotations

import json
import os
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _base_root() -> Path:
    env_root = os.getenv("IDP_DATA_DIR")
    root = Path(env_root).expanduser() if env_root else Path("data")
    if not root.is_absolute():
        root = _project_root() / root
    return root / "artifacts"


def path(name: str, doc_id: str) -> Path:
    return artifact_path(f"{name}.json", doc_id)


def artifact_path(name: str, doc_id: str) -> Path:
    """Resolve a relative side-artifact path while preventing directory traversal."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"invalid artifact name: {name!r}")
    normalized = name.replace("\\", "/")
    windows_path = PureWindowsPath(name)
    parts = normalized.split("/")
    relative = PurePosixPath(normalized)
    if (relative.is_absolute() or windows_path.is_absolute() or windows_path.drive
            or any(part in ("", ".", "..") for part in parts)):
        raise ValueError(f"invalid artifact name: {name!r}")
    root = _base_root() / doc_id
    target = root.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"invalid artifact name: {name!r}")
    return target


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
        return None


def save_bytes(name: str, doc_id: str, value: bytes) -> Path:
    """Write a binary artifact (for example 02_extraction/crops/p003_r1.png).

    FIX: does NOT go through path() — that appends ".json" and with_suffix("") was
    silently dropping the real extension (.png → nothing).
    """
    target = artifact_path(name, doc_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(value)
    tmp.replace(target)
    return target