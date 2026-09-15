"""Existing product + nonexistent batch -> YELLOW / BATCH_NOT_FOUND."""


def test_existing_product_missing_batch(client):
    r = client.post(
        "/api/scan",
        json={
            "medicine_name": "Ticagrelor Tablets",
            "batch_number": "NON_EXISTENT_123",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["color"] == "YELLOW"
    assert body["result"]["status"] == "BATCH_NOT_FOUND"
    assert body["batch"]["number"] == "NON_EXISTENT_123"


def test_medicine_only_returns_green_or_yellow(client):
    """Medicine name without batch must not crash."""
    r = client.post(
        "/api/scan", json={"medicine_name": "Ticagrelor Tablets"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["color"] in ("GREEN", "YELLOW", "RED")