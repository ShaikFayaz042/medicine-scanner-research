from __future__ import annotations

import hashlib

from idp.stages.manifest import run


def test_manifest_uses_content_hash_and_preserves_first_upload_time(tmp_path, monkeypatch):
    monkeypatch.setenv("IDP_DATA_DIR", str(tmp_path / "data"))
    source = tmp_path / "input.pdf"
    content = b"generated PDF bytes for manifest"
    source.write_bytes(content)

    first = run(source)
    saved = tmp_path / "data" / "artifacts" / first.doc_id / "00_manifest" / "document_manifest.json"
    second = run(source)

    assert first.doc_id == hashlib.sha256(content).hexdigest()
    assert first.sha256 == first.doc_id
    assert first.file_name == source.name
    assert first.size_bytes == len(content)
    assert first.upload_time.utcoffset().total_seconds() == 0
    assert second.upload_time == first.upload_time
    assert saved.exists()
