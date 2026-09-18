"""Unknown medicine -> YELLOW / MEDICINE_NOT_FOUND."""


def test_unknown_medicine(client):
    r = client.post("/api/scan", json={"medicine_name": "XYZ Medicine 999"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["color"] == "YELLOW"
    assert body["result"]["status"] == "MEDICINE_NOT_FOUND"
    assert body["safety"]["assessment"] == "UNKNOWN"


def test_missing_input_rejected(client):
    r = client.post("/api/scan", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "INVALID_INPUT"