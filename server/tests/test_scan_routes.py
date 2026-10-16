import asyncio
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import server.auth.security as auth_security
import server.deps as deps_module
import server.routes.scans as scans_module
import server.services.extraction as extraction
from server.auth.errors import register_auth_error_handlers
from server.database.mobile_models import Scan, User
from server.routes.scans import router as scans_router


class FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model
        self.filters = []
        self.limit_value = None
        self.offset_value = 0

    def filter(self, criterion):
        self.filters.append(criterion)
        return self

    def order_by(self, column):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def offset(self, value):
        self.offset_value = value
        return self

    def _matches(self, record, criterion):
        if hasattr(criterion, "clauses"):
            return any(self._matches(record, clause) for clause in criterion.clauses)
        left = getattr(criterion, "left", None)
        right = getattr(criterion, "right", None)
        if left is None or right is None:
            return True
        key = getattr(left, "key", "")
        expected = getattr(right, "value", right)
        return getattr(record, key, None) == expected

    def all(self):
        rows = [
            record
            for record in self.session.records.get(self.model, [])
            if all(self._matches(record, criterion) for criterion in self.filters)
        ]
        rows.sort(key=lambda row: getattr(row, "created_at", None) or date.min, reverse=True)
        return rows[self.offset_value : self.offset_value + self.limit_value if self.limit_value is not None else None]

    def first(self):
        rows = self.all()
        return rows[0] if rows else None


class FakeSession:
    def __init__(self):
        self.records = {}
        self.commits = 0

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, record):
        self.records.setdefault(type(record), []).append(record)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def close(self):
        pass

    def rollback(self):
        pass


def make_user(email):
    return User(id=uuid.uuid4(), name="Test User", email=email, password_hash="hash")


def build_client(monkeypatch, user=None, db=None):
    session = db or FakeSession()
    current_user = user or make_user("scanner@example.com")

    def override_db():
        yield session

    def override_user():
        return current_user

    app = FastAPI()
    register_auth_error_handlers(app)
    app.dependency_overrides[deps_module.get_mobile_db] = override_db
    app.dependency_overrides[deps_module.get_current_user] = override_user
    app.include_router(scans_router)
    return TestClient(app, raise_server_exceptions=False), session, current_user


def test_manual_scan_contract_and_conservative_verdict(monkeypatch):
    monkeypatch.setattr(auth_security, "JWT_SECRET_KEY", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(auth_security, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(auth_security, "ACCESS_TOKEN_TTL_MINUTES", 60)
    client, db, _ = build_client(monkeypatch)
    medicine_db = SimpleNamespace(closed=False, close=lambda: setattr(medicine_db, "closed", True))
    monkeypatch.setattr(scans_module, "MedicineSessionLocal", lambda: medicine_db)
    calls = []

    def shared_search(session, fields, limit, query):
        calls.append((session, fields, limit, query, db.commits))
        return {
            "query": query,
            "search_status": "MATCHED",
            "count": 1,
            "limit": limit,
            "has_more": False,
            "matches": [{
                "id": 1,
                "relevance": 100,
                "match_type": "EXACT",
                "matched_by": ["product_name", "batch_number"],
                "product": {"name": "Acme Pain Relief"},
                "assessment": {
                    "indicator": "YELLOW",
                    "summary": "A batch-level regulatory concern is recorded.",
                },
                "regulatory_events": [],
                "source_references": [],
            }],
        }

    monkeypatch.setattr(scans_module, "search_medicines", shared_search)

    response = client.post(
        "/scans/manual",
        json={"fields": {"name": "", "salt": "", "batchNumber": "ABC-123", "mfdDate": "", "expDate": "", "dose": ""}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unknown"
    assert payload["title"] == "Review regulatory records"
    assert payload["search_status"] == "MATCHED"
    assert payload["matches"][0]["assessment"]["indicator"] == "YELLOW"
    assert calls[0][0] is medicine_db
    assert calls[0][0] is not db
    assert calls[0][1]["batch_number"] == "abc-123"
    assert calls[0][4] == 1
    assert medicine_db.closed
    assert payload["fields"]["batchNumber"] == "ABC-123"
    assert db.commits == 2
    assert db.records[Scan][0].batch_number == "ABC-123"


def test_scan_without_searchable_fields_persists_and_does_not_open_medicine_db(monkeypatch):
    client, db, _ = build_client(monkeypatch)
    opened = []
    monkeypatch.setattr(scans_module, "MedicineSessionLocal", lambda: opened.append(True))

    response = client.post("/scans/manual", json={"fields": {}})

    assert response.status_code == 200
    payload = response.json()
    assert payload["search_status"] == "NO_PRODUCT_MATCH"
    assert payload["count"] == 0
    assert payload["matches"] == []
    assert payload["fields"]["name"] == ""
    assert opened == []
    assert db.commits == 2
    assert len(db.records[Scan]) == 1
    assert db.records[Scan][0].medicine_name == ""


def test_scan_history_is_user_scoped_and_paginated(monkeypatch):
    client, db, user = build_client(monkeypatch)
    other_user = make_user("other@example.com")
    now = date.today()
    db.records[Scan] = [
        SimpleNamespace(id=uuid.uuid4(), user_id=user.id, medicine_name="First", dose="", batch_number="A", created_at=now, status="unknown"),
        SimpleNamespace(id=uuid.uuid4(), user_id=user.id, medicine_name="Second", dose="", batch_number="B", created_at=now, status="unknown"),
        SimpleNamespace(id=uuid.uuid4(), user_id=other_user.id, medicine_name="Private", dose="", batch_number="X", created_at=now, status="unknown"),
    ]

    response = client.get("/scans?limit=1&offset=1")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["batchNumber"] in {"A", "B"}
    assert response.json()[0]["scannedAt"]


def test_scan_result_rechecks_owned_history_entry_and_hides_other_users(monkeypatch):
    client, db, user = build_client(monkeypatch)
    scan_id = uuid.uuid4()
    db.records[Scan] = [
        SimpleNamespace(
            id=scan_id,
            user_id=user.id,
            medicine_name="Panadol",
            salt="Paracetamol",
            batch_number="B-123",
            mfd_date="01/2025",
            exp_date="01/2027",
            dose="500 mg",
            gtin="00012345678905",
            serial="SERIAL-1",
        )
    ]
    medicine_db = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(scans_module, "MedicineSessionLocal", lambda: medicine_db)
    searches = []

    def shared_search(session, fields, limit, query):
        searches.append((fields, query))
        return {
            "query": query,
            "search_status": "MATCHED",
            "count": 1,
            "limit": limit,
            "has_more": False,
            "matches": [{
                "id": 1,
                "relevance": 100,
                "match_type": "EXACT",
                "matched_by": ["product_name", "batch_number"],
                "product": {"name": "Panadol 500 mg Tablet"},
                "assessment": {"indicator": "YELLOW", "summary": "Review this batch."},
                "regulatory_events": [],
                "source_references": [],
            }],
        }

    monkeypatch.setattr(scans_module, "search_medicines", shared_search)

    response = client.get(f"/scans/{scan_id}")

    assert response.status_code == 200
    assert response.json()["matches"][0]["product"]["name"] == "Panadol 500 mg Tablet"
    assert searches[0][0]["batch_number"] == "b-123"
    assert searches[0][1]["ingredient"] == "Paracetamol"

    db.records[Scan][0].user_id = make_user("other@example.com").id
    assert client.get(f"/scans/{scan_id}").status_code == 404


def test_scan_payload_validation_and_error_contract(monkeypatch):
    client, _, _ = build_client(monkeypatch)

    response = client.post("/scans/text", json={"rawText": ""}, headers={"X-Request-ID": "scan-validation-1"})

    assert response.status_code == 422
    assert "detail" in response.json()


def test_text_scan_uses_gemini_field_mapping_and_persists_it(monkeypatch):
    client, db, _ = build_client(monkeypatch)
    monkeypatch.setattr(
        scans_module,
        "MedicineSessionLocal",
        lambda: SimpleNamespace(close=lambda: None),
    )
    raw_text = "Brand label OCR"
    mapped_fields = {
        "name": "MediCure",
        "salt": "Paracetamol",
        "batch_number": "B-321",
        "mfd_date": "01/2025",
        "exp_date": "01/2027",
        "dose": "500 mg",
    }
    calls = []
    async def extract_fields(raw_text):
        calls.append(raw_text)
        return scans_module.MedicineFields(**mapped_fields)

    monkeypatch.setattr(scans_module, "extract_fields", extract_fields)
    monkeypatch.setattr(scans_module, "search_medicines", lambda *args, **kwargs: {
        "query": kwargs.get("query", {}),
        "search_status": "NO_PRODUCT_MATCH",
        "count": 0,
        "limit": 50,
        "has_more": False,
        "matches": [],
    })

    response = client.post("/scans/text", json={"rawText": raw_text})

    assert response.status_code == 200
    assert calls == [raw_text]
    assert response.json()["fields"] == {
        "name": "MediCure",
        "salt": "Paracetamol",
        "batchNumber": "B-321",
        "mfdDate": "01/2025",
        "expDate": "01/2027",
        "dose": "500 mg",
    }
    assert db.records[Scan][0].medicine_name == "MediCure"
    assert db.records[Scan][0].salt == "Paracetamol"


def test_gemini_field_mapping_requires_grounded_output_and_falls_back(monkeypatch):
    monkeypatch.setattr(extraction, "_client", lambda: object())

    async def generate_fields(_, __):
        return SimpleNamespace(
            parsed=extraction._ExtractedFields(
                name="MediCure",
                salt="Invented ingredient",
                batch_number="B-321",
                mfd_date="",
                exp_date="01/2027",
                dose="500 mg",
            )
        )

    monkeypatch.setattr(extraction, "_generate", generate_fields)
    mapped = asyncio.run(
        extraction.extract_fields("MediCure Paracetamol Batch B-321 Exp 01/2027 500 mg")
    )

    assert mapped == scans_module.MedicineFields(
        name="MediCure",
        salt="",
        batch_number="B-321",
        mfd_date="",
        exp_date="01/2027",
        dose="500 mg",
    )


def test_gemini_extraction_returns_rule_fallback_when_unconfigured_or_unavailable(monkeypatch):
    monkeypatch.setattr(extraction, "_client", lambda: None)
    raw_text = "MediCure 500 mg\nBatch No: B-321\nExp 01/2027"
    fallback = asyncio.run(extraction.extract_fields(raw_text))
    assert fallback.name == "MediCure 500 mg"
    assert fallback.batch_number == "B-321"
    assert fallback.exp_date == "01/2027"

    monkeypatch.setattr(extraction, "_client", lambda: object())

    async def fail_generation(_, __):
        raise TimeoutError

    monkeypatch.setattr(extraction, "_generate", fail_generation)
    assert asyncio.run(extraction.extract_fields(raw_text)) == fallback


def test_auth_dependency_rejects_missing_and_invalid_tokens(monkeypatch):
    monkeypatch.setattr(auth_security, "JWT_SECRET_KEY", "0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(auth_security, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(auth_security, "ACCESS_TOKEN_TTL_MINUTES", 60)
    db = FakeSession()

    with pytest.raises(HTTPException) as missing:
        deps_module.get_current_user(None, db)
    assert missing.value.status_code == 401

    credentials = SimpleNamespace(credentials="invalid-token")
    with pytest.raises(HTTPException) as invalid:
        deps_module.get_current_user(credentials, db)
    assert invalid.value.status_code == 401
