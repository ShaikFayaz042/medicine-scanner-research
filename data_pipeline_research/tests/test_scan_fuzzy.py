"""Fuzzy / OCR-typo handling. Must not silently auto-select weak matches."""


def test_ocr_typo(client):
    r = client.post(
        "/api/scan",
        json={
            "medicine_name": "Ticagrelor Tabletx",  # typo
            "batch_number": "MT230087",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Either a single confident fuzzy match or a candidate list.
    if body["match"]["type"] == "MULTIPLE":
        assert body["candidates"], "MULTIPLE must return candidates"
    else:
        assert body["match"]["type"] in ("EXACT", "FUZZY")
        assert body["match"]["confidence"] > 0.5
        assert body["medicine"]["name"]


def test_low_confidence_not_auto_picked(client):
    r = client.post("/api/scan", json={"medicine_name": "zzzz qqqq 0000"})
    assert r.status_code == 200
    body = r.json()
    # Should not invent a product.
    assert body["result"]["status"] in ("MEDICINE_NOT_FOUND", "MULTIPLE_MATCHES")