from datetime import date
from difflib import SequenceMatcher
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from server.database.medicine_models import (
    MEDICINE_SCHEMA,
    MedicineBatch,
    MedicineIngredient,
    MedicineOrganization,
    MedicineProduct,
    MedicineProductIngredient,
    MedicineRegulatoryDocument,
    MedicineRegulatoryEvent,
    product_organizations,
)
from server.database.mobile_models import Scan, User
import server.deps as server_deps
from server.routes.medicines import MedicineSearchRequest, get_medicine_db, router as medicines_router
import server.routes.scans as scans_module
from server.routes.scans import router as scans_router
from server.services.medicine_service import _build_assessment, _serialize, _serialize_match


@pytest.fixture
def medicine_http_client(request):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_engine = engine.execution_options(schema_translate_map={MEDICINE_SCHEMA: None})

    def word_similarity(query, target):
        query = (query or "").casefold()
        words = (target or "").casefold().split()
        return max(
            (SequenceMatcher(None, query, word).ratio() for word in words),
            default=0,
        )

    if getattr(request, "param", True):
        @event.listens_for(engine, "connect")
        def register_word_similarity(connection, _):
            connection.create_function("word_similarity", 2, word_similarity)

    tables = [
        MedicineOrganization.__table__,
        MedicineIngredient.__table__,
        MedicineProduct.__table__,
        MedicineProductIngredient.__table__,
        MedicineBatch.__table__,
        MedicineRegulatoryDocument.__table__,
        MedicineRegulatoryEvent.__table__,
        product_organizations,
    ]
    MedicineProduct.metadata.create_all(test_engine, tables=tables)
    session = sessionmaker(bind=test_engine)()

    ingredient = MedicineIngredient(id=1, name="Paracetamol", normalized_name="paracetamol")
    organization = MedicineOrganization(id=1, name="Acme Labs", normalized_name="acme labs")
    products = [
        MedicineProduct(
            id=1, product_name="Paracetamol 500 mg Tablet",
            normalized_search_name="paracetamol 500 mg tablet", brand_name="Panadol",
            dosage_form="Tablet", strength="500 mg",
        ),
        MedicineProduct(
            id=2, product_name="Paracetamol 250 mg Suspension",
            normalized_search_name="paracetamol 250 mg suspension", brand_name="Calpol",
            dosage_form="Oral suspension", strength="250 mg",
        ),
        MedicineProduct(
            id=3, product_name="Paracetamol Cream 1%",
            normalized_search_name="paracetamol cream 1%", brand_name="Dermasol",
            dosage_form="Cream", strength="1%",
        ),
        MedicineProduct(
            id=4, product_name="Paracetamol Extended Release",
            normalized_search_name="paracetamol extended release", brand_name="Longa",
            dosage_form="Tablet", strength="650 mg",
        ),
    ]
    session.add_all([ingredient, organization, *products])
    session.flush()
    for product in products:
        session.add(
            MedicineProductIngredient(
                product_id=product.id,
                ingredient_id=ingredient.id,
                strength_text=product.strength,
            )
        )
        session.execute(
            product_organizations.insert().values(
                product_id=product.id,
                organization_id=organization.id,
                role="MANUFACTURER",
            )
        )

    batches = [
        MedicineBatch(id=11, product_id=1, batch_number="B-123"),
        MedicineBatch(id=12, product_id=1, batch_number="B-456"),
        MedicineBatch(id=21, product_id=2, batch_number="C-123"),
    ]
    session.add_all(batches)
    documents = [
        MedicineRegulatoryDocument(
            id=101, source_org="National Regulator", document_type="QUALITY_ALERT",
            title="Batch alert B-123", publication_date=date(2025, 2, 3),
            source_url="https://regulator.example/alert-123", pdf_filename="alert-123.pdf",
        ),
        MedicineRegulatoryDocument(
            id=102, source_org="National Regulator", document_type="QUALITY_ALERT",
            title="Batch alert B-456", publication_date=date(2025, 2, 4),
            source_url="https://regulator.example/alert-456", pdf_filename="alert-456.pdf",
        ),
        MedicineRegulatoryDocument(
            id=103, source_org="National Regulator", document_type="LEGAL_ORDER",
            title="Product prohibition", publication_date=date(2025, 3, 1),
            source_url="https://regulator.example/order-103", pdf_filename="order-103.pdf",
        ),
        MedicineRegulatoryDocument(
            id=104, source_org="National Regulator", document_type="REGISTER",
            title="Approval listing", publication_date=date(2025, 3, 2),
            source_url="https://regulator.example/register-104", pdf_filename="register-104.pdf",
        ),
    ]
    session.add_all(documents)
    session.add_all([
        MedicineRegulatoryEvent(
            id=1001, document_id=101, product_id=1, batch_id=11, scope="BATCH",
            source_record_id="SRC-B123", event_type="QUALITY_FAILURE",
            status="NOT_OF_STANDARD_QUALITY", reason="Dissolution failure",
        ),
        MedicineRegulatoryEvent(
            id=1002, document_id=102, product_id=1, batch_id=12, scope="BATCH",
            source_record_id="SRC-B456", event_type="SPURIOUS",
            status="SPURIOUS", reason="Identity concern",
        ),
        MedicineRegulatoryEvent(
            id=1003, document_id=103, product_id=3, scope="PRODUCT",
            source_record_id="SRC-LEGAL", event_type="LEGAL_ORDER",
            status="PROHIBITED", legal_status="PROHIBITED",
        ),
        MedicineRegulatoryEvent(
            id=1004, document_id=104, product_id=4, scope="PRODUCT",
            source_record_id="SRC-APPROVAL", event_type="APPROVAL",
            status="APPROVED", legal_status="AUTHORIZED",
        ),
    ])
    session.commit()

    app = FastAPI()

    def override_medicine_db():
        yield session

    app.dependency_overrides[get_medicine_db] = override_medicine_db
    app.include_router(medicines_router)
    app.state.medicine_session_factory = sessionmaker(bind=test_engine)
    client = TestClient(app)
    try:
        yield client
    finally:
        session.close()
        engine.dispose()


def _event(**overrides):
    event = {
        "event_type": "QUALITY_FAILURE",
        "scope": "BATCH",
        "batch_number": "B-123",
        "status": "NOT_OF_STANDARD_QUALITY",
        "legal_status": None,
        "reason": "Dissolution",
    }
    event.update(overrides)
    return event


def test_search_request_requires_at_least_one_non_empty_search_field():
    with pytest.raises(ValidationError):
        MedicineSearchRequest(limit=20)

    request = MedicineSearchRequest(batch_number=" B-123 ", limit=20)
    assert request.batch_number == "B-123"


def test_batch_quality_event_is_yellow_not_red():
    assessment = _build_assessment([_event()])

    assert assessment["indicator"] == "YELLOW"
    assert assessment["template_id"] == "BATCH_QUALITY_ALERT"
    assert "B-123" in assessment["summary"]


def test_only_explicit_prohibition_or_restriction_is_red():
    event = _event(legal_status="PROHIBITED", source={"document_id": 1})
    assessment = _build_assessment([event])

    assert assessment["indicator"] == "RED"
    assert assessment["template_id"] == "LEGAL_RESTRICTION"


def test_conflicting_or_unsupported_legal_status_is_unknown():
    supported_restriction = _event(legal_status="PROHIBITED", source={"document_id": 1})
    uncertain_event = _event(event_type="LEGAL_ORDER", legal_status="STAYED")

    assert _build_assessment([supported_restriction, uncertain_event])["indicator"] == "UNKNOWN"
    assert _build_assessment([_event(legal_status="RESTRICTED")])["indicator"] == "UNKNOWN"


def test_unknown_scope_is_not_assessed_as_green_or_red():
    assessment = _build_assessment([_event(scope="UNMAPPED")])

    assert assessment["indicator"] == "UNKNOWN"


def test_no_events_returns_caveated_green_assessment():
    assessment = _build_assessment([])

    assert assessment["indicator"] == "GREEN"
    assert "does not guarantee" in assessment["summary"]
    assert "authenticity of a physical pack" in assessment["disclaimer"]


def test_batch_search_excludes_other_batch_events_and_sources():
    matching_batch = SimpleNamespace(id=1, batch_number="B-123")
    unrelated_batch = SimpleNamespace(id=2, batch_number="B-456")

    def regulatory_event(batch):
        document = SimpleNamespace(
            id=batch.id + 100,
            source_org="Regulator",
            title=f"Alert {batch.batch_number}",
            document_type="REGULATORY_ALERT",
            publication_date=None,
            source_url=f"https://example.test/{batch.batch_number}.pdf",
            pdf_filename=f"{batch.batch_number}.pdf",
        )
        return SimpleNamespace(
            id=batch.id,
            source_record_id=f"source-{batch.id}",
            event_type="QUALITY_FAILURE",
            scope="BATCH",
            batch_id=batch.id,
            batch=batch,
            status="NOT_OF_STANDARD_QUALITY",
            legal_status=None,
            reason="Dissolution",
            effective_date=None,
            document=document,
        )

    product = SimpleNamespace(
        id=9,
        product_name="Paracetamol Tablet",
        normalized_search_name="paracetamol tablet",
        brand_name=None,
        generic_name="Paracetamol",
        dosage_form="Tablet",
        route="Oral",
        manufacturer=None,
        ingredients=[],
        batches=[matching_batch, unrelated_batch],
        regulatory_events=[regulatory_event(matching_batch), regulatory_event(unrelated_batch)],
    )

    result = _serialize_match(
        product,
        100,
        "EXACT",
        {"name": "paracetamol", "batch_number": "B-123"},
    )

    assert result["matched_by"] == ["product_name", "batch_number"]
    assert [event["batch_number"] for event in result["regulatory_events"]] == ["B-123"]
    assert [source["source_record_id"] for source in result["source_references"]] == ["source-1"]
    assert result["assessment"]["indicator"] == "YELLOW"


def test_serialize_product_detail_includes_product_and_assessment_fields():
    product = SimpleNamespace(
        id=9,
        product_name="Paracetamol Tablet",
        normalized_search_name="paracetamol tablet",
        brand_name="Panadol",
        generic_name="Paracetamol",
        dosage_form="Tablet",
        route="Oral",
        manufacturer=SimpleNamespace(name="Acme Labs"),
        ingredients=[
            SimpleNamespace(
                ingredient=SimpleNamespace(name="Paracetamol", normalized_name="paracetamol"),
                strength=500,
                strength_text="500 mg",
                unit="mg",
            )
        ],
        batches=[],
        regulatory_events=[],
    )

    result = _serialize(product, {})

    assert result["id"] == 9
    assert result["product"]["manufacturer"] == "Acme Labs"
    assert result["product"]["name"] == "Paracetamol Tablet"
    assert result["assessment"]["indicator"] == "GREEN"


def test_http_search_exact_partial_ingredient_and_batch_only(medicine_http_client):
    exact = medicine_http_client.post("/api/medicines/search", json={"name": "Panadol"})
    assert exact.status_code == 200
    assert exact.json()["matches"][0]["match_type"] == "EXACT"
    assert exact.json()["matches"][0]["matched_by"] == ["brand_name"]

    partial = medicine_http_client.post("/api/medicines/search", json={"name": "panad"}).json()
    assert partial["count"] == 1
    assert partial["matches"][0]["match_type"] == "PARTIAL"

    ingredient = medicine_http_client.post(
        "/api/medicines/search", json={"ingredient": " Paracetamol "}
    ).json()
    assert ingredient["query"]["ingredient"] == "Paracetamol"
    assert ingredient["count"] == 4
    assert "ingredient" in ingredient["matches"][0]["matched_by"]

    batch = medicine_http_client.post(
        "/api/medicines/search", json={"batch_number": "B-123"}
    ).json()
    assert batch["count"] == 1
    assert batch["matches"][0]["matched_by"] == ["batch_number"]
    assert batch["matches"][0]["product"]["name"] == "Paracetamol 500 mg Tablet"

    manufacturer = medicine_http_client.post(
        "/api/medicines/search", json={"manufacturer": "Acme Labs"}
    ).json()
    assert manufacturer["matches"][0]["matched_by"] == ["manufacturer"]
    partial_manufacturer = medicine_http_client.post(
        "/api/medicines/search", json={"manufacturer": "Acme"}
    ).json()
    assert partial_manufacturer["matches"][0]["match_type"] == "PARTIAL"
    strength = medicine_http_client.post(
        "/api/medicines/search", json={"strength": "500 mg"}
    ).json()
    assert strength["matches"][0]["matched_by"] == ["strength"]
    partial_strength = medicine_http_client.post(
        "/api/medicines/search", json={"strength": "500"}
    ).json()
    assert partial_strength["matches"][0]["match_type"] == "PARTIAL"
    dosage_form = medicine_http_client.post(
        "/api/medicines/search", json={"dosage_form": "susp"}
    ).json()
    assert dosage_form["matches"][0]["matched_by"] == ["dosage_form"]


def test_http_search_typo_uses_fuzzy_match_and_lower_relevance(medicine_http_client):
    response = medicine_http_client.post(
        "/api/medicines/search", json={"name": "Paracetmol"}
    ).json()

    assert response["count"] == 4
    assert all(match["match_type"] == "FUZZY" for match in response["matches"])
    assert all(60 < match["relevance"] < 80 for match in response["matches"])


@pytest.mark.parametrize("medicine_http_client", [False], indirect=True)
def test_search_falls_back_when_fuzzy_function_is_unavailable(medicine_http_client):
    response = medicine_http_client.post(
        "/api/medicines/search",
        json={"name": "Paracetamol", "batch_number": "B-123"},
    )

    assert response.status_code == 200
    match = response.json()["matches"][0]
    assert match["product"]["name"] == "Paracetamol 500 mg Tablet"
    assert [event["batch_number"] for event in match["regulatory_events"]] == ["B-123"]


def test_http_search_filters_batch_alerts_and_serializes_official_sources(medicine_http_client):
    matched = medicine_http_client.post(
        "/api/medicines/search",
        json={"name": "Panadol", "batch_number": "B-123"},
    ).json()["matches"][0]

    assert matched["assessment"]["indicator"] == "YELLOW"
    assert [event["batch_number"] for event in matched["regulatory_events"]] == ["B-123"]
    assert [source["source_record_id"] for source in matched["source_references"]] == ["SRC-B123"]
    source = matched["source_references"][0]
    assert source["document_id"] == 101
    assert source["source_org"] == "National Regulator"
    assert source["document_type"] == "QUALITY_ALERT"
    assert source["publication_date"] == "2025-02-03"
    assert source["source_url"] == "https://regulator.example/alert-123"
    assert source["pdf_filename"] == "alert-123.pdf"
    assert matched["regulatory_events"][0]["event_id"] == 1001

    spurious = medicine_http_client.post(
        "/api/medicines/search",
        json={"name": "Panadol", "batch_number": "B-456"},
    ).json()["matches"][0]
    assert spurious["assessment"]["indicator"] == "YELLOW"
    assert spurious["regulatory_events"][0]["event_type"] == "SPURIOUS"

    mismatch = medicine_http_client.post(
        "/api/medicines/search",
        json={"name": "Panadol", "batch_number": "B-999"},
    ).json()
    assert mismatch["search_status"] == "NO_PRODUCT_MATCH"
    assert mismatch["count"] == 0
    assert mismatch["has_more"] is False
    assert mismatch["matches"] == []


def test_http_assessment_rules_and_unmatched_never_green(medicine_http_client):
    green = medicine_http_client.post(
        "/api/medicines/search", json={"name": "Paracetamol 250 mg Suspension"}
    ).json()["matches"][0]
    red = medicine_http_client.post(
        "/api/medicines/search", json={"name": "Paracetamol Cream 1%"}
    ).json()["matches"][0]
    unknown = medicine_http_client.post(
        "/api/medicines/search", json={"name": "Paracetamol Extended Release"}
    ).json()["matches"][0]
    unmatched = medicine_http_client.post(
        "/api/medicines/search", json={"name": "No Such Product"}
    ).json()

    assert green["assessment"]["indicator"] == "GREEN"
    assert "does not guarantee" in green["assessment"]["summary"]
    assert red["assessment"]["indicator"] == "RED"
    assert red["source_references"][0]["source_record_id"] == "SRC-LEGAL"
    assert unknown["assessment"]["indicator"] == "UNKNOWN"
    assert unknown["assessment"]["template_id"] == "INSUFFICIENT_REGULATORY_EVIDENCE"
    assert unmatched["search_status"] == "NO_PRODUCT_MATCH"
    assert unmatched["count"] == 0
    assert unmatched["has_more"] is False
    assert unmatched["matches"] == []


def test_http_search_validation_default_limit_ordering_and_has_more(medicine_http_client):
    blank = medicine_http_client.post("/api/medicines/search", json={"name": "   ", "limit": 20})
    assert blank.status_code == 422
    maximum_lengths = {
        "name": 200,
        "manufacturer": 200,
        "ingredient": 200,
        "strength": 100,
        "dosage_form": 100,
        "batch_number": 100,
    }
    for field, maximum in maximum_lengths.items():
        assert medicine_http_client.post(
            "/api/medicines/search", json={field: "x" * (maximum + 1)}
        ).status_code == 422
    for limit in (0, 101):
        assert medicine_http_client.post(
            "/api/medicines/search", json={"ingredient": "paracetamol", "limit": limit}
        ).status_code == 422

    default_limit = medicine_http_client.post(
        "/api/medicines/search", json={"name": "Panadol"}
    ).json()
    assert default_limit["limit"] == 50

    limited = medicine_http_client.post(
        "/api/medicines/search", json={"ingredient": "paracetamol", "limit": 2}
    ).json()
    assert limited["count"] == 2
    assert limited["has_more"] is True
    assert [item["id"] for item in limited["matches"]] == [2, 1]
    assert limited["matches"][0]["relevance"] >= limited["matches"][1]["relevance"]


def test_http_scan_flows_persist_and_use_shared_search_in_isolated_sessions(
    medicine_http_client, monkeypatch
):
    class MobileSession:
        def __init__(self):
            self.records = []
            self.commits = 0

        def add(self, record):
            self.records.append(record)

        def flush(self):
            pass

        def commit(self):
            self.commits += 1

    mobile_db = MobileSession()
    user = User(
        id=uuid.uuid4(), name="Scanner", email="scanner@example.test", password_hash="hash"
    )
    app = FastAPI()

    def override_mobile_db():
        yield mobile_db

    app.dependency_overrides[server_deps.get_mobile_db] = override_mobile_db
    app.dependency_overrides[server_deps.get_current_user] = lambda: user
    app.include_router(scans_router)

    medicine_session_factory = medicine_http_client.app.state.medicine_session_factory
    medicine_sessions = []
    persisted_scan_counts = []

    class TrackedMedicineSession:
        def __init__(self, session):
            self.session = session
            self.closed = False

        def __getattr__(self, name):
            return getattr(self.session, name)

        def close(self):
            self.closed = True
            self.session.close()

    def open_medicine_session():
        session = TrackedMedicineSession(medicine_session_factory())
        medicine_sessions.append(session)
        persisted_scan_counts.append(mobile_db.commits)
        return session

    monkeypatch.setattr(scans_module, "MedicineSessionLocal", open_medicine_session)
    monkeypatch.setattr(
        scans_module,
        "_decode_barcode",
        lambda raw: {
            "gtin": "00012345678905",
            "batch_number": "B-123",
            "exp_date": "",
            "mfd_date": "",
            "serial": "SERIAL-1",
        },
    )
    client = TestClient(app)

    text_response = client.post(
        "/scans/text",
        json={"rawText": "Panadol 500 mg tablet\nBatch No: B-123"},
    )
    barcode_response = client.post("/scans/barcode", json={"raw": "test-barcode"})
    no_match_response = client.post(
        "/scans/manual", json={"fields": {"batchNumber": "B-999"}}
    )

    assert text_response.status_code == 200
    assert text_response.json()["search_status"] == "MATCHED"
    assert text_response.json()["matches"][0]["product"]["name"] == "Paracetamol 500 mg Tablet"
    assert [event["batch_number"] for event in text_response.json()["matches"][0]["regulatory_events"]] == ["B-123"]
    assert text_response.json()["matches"][0]["assessment"]["indicator"] == "YELLOW"

    assert barcode_response.status_code == 200
    assert barcode_response.json()["search_status"] == "MATCHED"
    assert barcode_response.json()["fields"]["batchNumber"] == "B-123"
    assert barcode_response.json()["gtin"] == "00012345678905"

    assert no_match_response.status_code == 200
    assert no_match_response.json()["search_status"] == "NO_PRODUCT_MATCH"
    assert no_match_response.json()["matches"] == []
    assert no_match_response.json()["count"] == 0
    assert len(mobile_db.records) == 3
    assert mobile_db.commits == 6
    assert mobile_db.records[0].raw_input == "Panadol 500 mg tablet\nBatch No: B-123"
    assert mobile_db.records[1].serial == "SERIAL-1"
    assert mobile_db.records[2].batch_number == "B-999"
    assert len(medicine_sessions) == 3
    assert persisted_scan_counts == [1, 3, 5]
    assert all(session is not mobile_db for session in medicine_sessions)
    assert all(session.closed for session in medicine_sessions)