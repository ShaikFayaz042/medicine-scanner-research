"""Verified real record: Ticagrelor Tablets / MT230087 -> YELLOW / NSQ."""


def test_ticagrelor_real_record(client):
    r = client.post(
        "/api/scan",
        json={"medicine_name": "Ticagrelor Tablets", "batch_number": "MT230087"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["result"]["color"] == "YELLOW"
    assert body["result"]["status"] == "NOT_OF_STANDARD_QUALITY"
    assert body["result"]["severity"] == "MEDIUM"

    # Must NOT be classified as banned / red.
    assert body["result"]["color"] != "RED"
    assert "BANNED" not in (body["result"].get("status") or "")

    assert body["batch"]["number"] == "MT230087"

    regs = [m["regulatory"] for m in body["matches"]]
    assert any(
        r["event_type"] == "QUALITY_FAILURE"
        and r["status"] == "NOT_OF_STANDARD_QUALITY"
        and r["scope"] == "BATCH"
        and (r["reason"] or "").lower() == "dissolution"
        for r in regs
    ), regs

    assert body["match"]["type"] in ("EXACT", "FUZZY")
    assert body["match"]["confidence"] > 0.5

    # Source block must be populated from regulatory_documents
    src = body["matches"][0]["source"]
    assert src["document_id"] is not None
    assert src["pdf_filename"]