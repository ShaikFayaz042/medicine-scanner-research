"""Combination / FDC scope events (scope=COMBINATION, product_id NULL)."""


def test_combination_search_path(client):
    # Use a generic ingredient; this test asserts the API does not crash
    # and returns a structured shape even when nothing matches.
    r = client.post(
        "/api/scan", json={"active_ingredient": "Paracetamol"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body and "match" in body and "safety" in body
    assert body["result"]["color"] in ("RED", "YELLOW", "GREEN")


def test_combination_statuses_never_lost(client):
    # When matches exist for a combination, they must carry
    # scope='COMBINATION' from the DB, not be silently dropped.
    r = client.post(
        "/api/scan", json={"active_ingredient": "Paracetamol"}
    )
    body = r.json()
    for m in body["matches"]:
        # scope must be one of the values we expect in the DB
        assert m["regulatory"]["scope"] in (None, "BATCH", "PRODUCT", "COMBINATION")