from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refund_desk.api import create_app
from refund_desk.facts import FACTS

ROOT = Path(__file__).resolve().parent.parent


def model_says(**yes):
    """Fake batch model: every request gets the same answer; quotes are verified per request."""
    def ask(requests):
        out = {n: {"value": n in yes, "quote": yes.get(n, "")} for n in FACTS}
        return [{**out, "english": ""} for _ in requests], {"model": "fake"}
    return ask


@pytest.fixture
def client(tmp_path):
    app = create_app(cache_path=tmp_path / "facts.json", decisions_path=tmp_path / "decisions.jsonl",
                     ask=model_says(refund_elsewhere="me devolvieron el dinero"), translate_ask=None)
    return TestClient(app)


def test_queue_counts_and_duplicate_keys(client):
    q = client.get("/api/queue").json()
    assert q["counts"]["all"] == 21
    keys = [i["key"] for i in q["items"]]
    assert "RF-2183-1" in keys and "RF-2183-2" in keys


def test_case_shows_rule_and_quote(client):
    c = client.get("/api/case/RF-1074").json()
    assert c["rule_id"] == "refund-elsewhere" and c["route"] == "reviewer"
    assert c["quotes"] == ["me devolvieron el dinero"]
    assert c["default_action"] == "ask"


def test_going_against_the_rule_needs_a_reason(client):
    r = client.post("/api/case/RF-1074/decision", json={"action": "approve"})
    assert r.status_code == 422 and "reason" in r.json()["detail"]
    r = client.post("/api/case/RF-1074/decision", json={"action": "approve", "reason": "Store refund was for a different order"})
    assert r.status_code == 200 and r.json()["recorded"]["against_rule"]
    assert client.post("/api/case/RF-1074/decision", json={"action": "reject"}).status_code == 409


def test_following_the_rule_needs_no_reason(client):
    r = client.post("/api/case/RF-1074/decision", json={"action": "ask", "ask_for": "The store receipt"})
    assert r.status_code == 200 and not r.json()["recorded"]["against_rule"]


def test_partial_amount_is_bounded(client):
    key = next(i["key"] for i in client.get("/api/queue").json()["items"]
               if i["route"] == "reviewer" and i["amount"] and i["key"] != "RF-1074")
    amount = client.get(f"/api/case/{key}").json()["amount"]
    base = {"action": "partial", "reason": "cosmetic only, keeps the item"}
    assert client.post(f"/api/case/{key}/decision", json={**base, "amount": amount}).status_code == 422
    assert client.post(f"/api/case/{key}/decision", json={**base, "amount": amount / 2}).status_code == 200


def test_reviewer_cannot_decide_fraud_cases(client):
    assert client.post("/api/case/RF-1070/decision", json={"action": "approve", "reason": "looks fine to me"}).status_code == 422


def test_decisions_survive_a_restart(tmp_path):
    kw = dict(cache_path=tmp_path / "f.json", decisions_path=tmp_path / "d.jsonl", ask=model_says(), translate_ask=None)
    TestClient(create_app(**kw)).post("/api/case/RF-1071/decision", json={"action": "ask", "ask_for": "A photo"})
    q = TestClient(create_app(**kw)).get("/api/queue").json()
    assert next(i for i in q["items"] if i["key"] == "RF-1071")["decided"]["action"] == "ask"


def test_screens_are_served(client):
    assert "Refund Desk" in client.get("/").text


def test_overview_weeks_from_history(client):
    o = client.get("/api/overview").json()
    assert o["totals"]["rows"] == o["totals"]["auto"] + o["totals"]["people"]
    w = o["weeks"][0]
    assert w["week"] == "2026-06-01" and w["auto"] + w["people"] > 0
    # Lost money counts the $25 chargeback fee (policy note 7).
    assert any(x["lost_on_auto"] > 0 for x in o["weeks"])
