import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refund_desk.api import create_app
from refund_desk.facts import FACTS
from refund_desk.load import clean
from refund_desk.rules import load_policy, route, with_rule
from refund_desk.translate import check_readings

ROOT = Path(__file__).resolve().parent.parent
POLICY = load_policy(ROOT / "policy" / "v1.json")


def reading(conditions, route="auto_approve", insert_before="fraud-flag", name="Stolen card goes through",
            default_action="approve"):
    return {"summary": "s", "data_source": "d", "name": name, "conditions": conditions, "route": route,
            "default_action": default_action, "why": "Approved automatically: test.", "insert_before": insert_before}


# ---------- readings are checked before anyone sees them ----------

def test_valid_reading_is_typed_and_placed():
    ok, rejected = check_readings([reading([{"field": "facts.card_reported_stolen", "op": "eq", "value": "true"}])], POLICY)
    assert not rejected
    rule = ok[0]["rule"]
    assert rule["when"][0]["value"] is True and ok[0]["insert_before"] == "fraud-flag"


@pytest.mark.parametrize("cond,problem", [
    ({"field": "card_stolen", "op": "eq", "value": "true"}, "unknown field"),
    ({"field": "fraud_flag", "op": "eq", "value": "maybe"}, "cannot be"),
    ({"field": "stated_reason", "op": "gt", "value": "wrong_size"}, "cannot be compared"),
    ({"field": "amount_usd", "op": "about", "value": "300"}, "unknown op"),
])
def test_invalid_readings_are_rejected(cond, problem):
    ok, rejected = check_readings([reading([cond])], POLICY)
    assert not ok and problem in rejected[0]["problem"]


def test_new_rule_never_goes_above_the_safety_checks():
    rule = {"name": "Everything through", "when": [{"field": "amount_usd", "op": "ge", "value": 0}],
            "route": "auto_approve", "default_action": "approve", "why": "Approved automatically: all."}
    draft = with_rule(POLICY, rule, "data-problem")  # asked for the very top
    ids = [r["id"] for r in draft["rules"]]
    assert ids.index("everything-through") > ids.index("authority-claim")
    claim = clean({"request_id": "RF-1", "requested_at": "2026-08-01", "customer_id": "C", "tenure_months": "20",
                   "prior_refunds_12m": "0", "amount_usd": "40", "category": "home", "payment_method": "card",
                   "stated_reason": "wrong_size", "customer_note": "manager said yes", "support_note": "",
                   "days_since_delivery": "3", "fraud_flag": "no"})
    claim.update(facts={**{n: False for n in FACTS}, "authority_claim": True}, facts_status="read")
    assert route(claim, draft)["rule_id"] == "authority-claim"


# ---------- the manager flow through the API ----------

def fake_translator(text, policy):
    return [
        reading([{"field": "fraud_flag", "op": "eq", "value": "yes"}], name="Fraud flag goes through"),
        reading([{"field": "facts.card_reported_stolen", "op": "eq", "value": "true"}], name="Confirmed stolen goes through"),
        reading([{"field": "nonsense", "op": "eq", "value": "x"}], name="Broken"),
    ]


@pytest.fixture
def client(tmp_path):
    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    app = create_app(policy_dir=tmp_path / "policy", cache_path=ROOT / "cache" / "facts.json",
                     decisions_path=tmp_path / "d.jsonl", translations_path=tmp_path / "t.json",
                     ask=None, translate_ask=fake_translator)
    return TestClient(app), tmp_path / "policy"


def test_translate_returns_checked_readings(client):
    c, _ = client
    out = c.post("/api/policy/translate", json={"text": "stolen-card cases go straight through"}).json()
    assert [r["rule"]["name"] for r in out["readings"]] == ["Fraud flag goes through", "Confirmed stolen goes through"]
    assert len(out["rejected"]) == 1


def test_preview_shows_what_moves(client):
    c, _ = client
    rule = {"name": "Over 300 to us", "when": [{"field": "amount_usd", "op": "gt", "value": 300}],
            "route": "reviewer", "default_action": None, "why": "Sent to you because the amount is over $300."}
    p = c.post("/api/policy/preview", json={"rule": rule, "insert_before": "fraud-flag"}).json()
    moved = {x["request_id"] for x in p["pending"]["changed"]}
    assert {"RF-1070"} <= moved  # $410 with a fraud flag: now a reviewer, not the fraud team
    assert p["pending"]["to_auto_count"] == 0


def test_publish_then_rollback(client):
    c, policy_dir = client
    rule = {"name": "Over 300 to us", "when": [{"field": "amount_usd", "op": "gt", "value": 300}],
            "route": "reviewer", "default_action": None, "why": "Sent to you because the amount is over $300."}
    v2 = c.post("/api/policy/publish", json={"rule": rule, "insert_before": "fraud-flag", "text": "anything over $300 comes to us"}).json()
    assert v2["version"] == 2 and (policy_dir / "v2.json").exists()
    assert c.get("/api/case/RF-1070").json()["rule_name"] == "Over 300 to us"
    v3 = c.post("/api/policy/rollback", json={"version": 1}).json()
    assert v3["version"] == 3 and v3["title"] == "Roll back to v1"
    assert c.get("/api/case/RF-1070").json()["route"] == "fraud_team"
    assert [v["version"] for v in c.get("/api/policy").json()["versions"]] == [3, 2, 1]


def test_publish_rejects_unsafe_rule(client):
    c, _ = client
    bad = {"name": "x", "when": [{"field": "amount_usd", "op": "gt", "value": "lots"}],
           "route": "auto_approve", "default_action": "approve", "why": "x"}
    assert c.post("/api/policy/publish", json={"rule": bad}).status_code == 422


def test_unknown_wording_without_llm(tmp_path):
    shutil.copytree(ROOT / "policy", tmp_path / "policy")
    c = TestClient(create_app(policy_dir=tmp_path / "policy", decisions_path=tmp_path / "d.jsonl",
                              translations_path=tmp_path / "t.json", ask=None, translate_ask=None))
    r = c.post("/api/policy/translate", json={"text": "refund every Tuesday"})
    assert r.status_code == 503 and "example" in r.json()["detail"]
