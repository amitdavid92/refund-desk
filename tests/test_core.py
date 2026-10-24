import copy
import json
from pathlib import Path

import pytest

from refund_desk.evaluate import evaluate_history
from refund_desk.facts import FACTS
from refund_desk.load import clean, load, parse_amount, parse_date
from refund_desk.rules import latest_policy, load_policy, route, route_batch, validate

ROOT = Path(__file__).resolve().parent.parent
POLICY = load_policy(ROOT / "policy" / "v1.json")


class NothingInText:
    """Stand-in reader that finds no facts in any note: isolates the column rules (D9)."""

    def read_all(self, requests):
        for r in requests:
            r.update(facts={n: False for n in FACTS}, facts_status="read")
        return requests


def row(**over):
    """A clean, auto-approvable request; facts read and empty unless a test says otherwise."""
    base = {
        "request_id": "RF-9001", "requested_at": "2026-08-01", "customer_id": "CU-1",
        "tenure_months": "24", "prior_refunds_12m": "0", "amount_usd": "30",
        "category": "apparel", "payment_method": "card", "stated_reason": "wrong_size",
        "customer_note": "", "support_note": "", "days_since_delivery": "5", "fraud_flag": "no",
    }
    base.update(over)
    return clean(base)


def test_unread_notes_go_to_a_person():
    r = row(customer_note="please refund")
    assert r["facts_status"] == "unread"
    assert route(r, POLICY)["rule_id"] == "text-unread"


# ---------- the line reproduces the analysis (D9) ----------

def test_history_matches_d9():
    m = evaluate_history(ROOT / "data" / "history.csv", POLICY, NothingInText())
    assert (m["train"]["auto"], m["train"]["rows"]) == (73, 198)
    assert m["train"]["auto_bad"] == ["RF-2074"]
    assert m["train"]["auto_humans_disagreed"] == []
    assert (m["holdout"]["auto"], m["holdout"]["rows"]) == (21, 50)
    assert m["holdout"]["auto_bad"] == []


def test_pending_routes_on_columns_alone():
    requests = NothingInText().read_all(load(ROOT / "data" / "pending.csv"))
    by_route = {}
    for r, d in zip(requests, route_batch(requests, POLICY)):
        by_route.setdefault(d["route"], []).append((r["request_id"], d["rule_id"]))
    # Columns alone approve RF-1074 and RF-1075; only reading the text catches them (test_facts.py).
    assert [i for i, _ in by_route["auto_approve"]] == ["RF-1069", "RF-1074", "RF-1075"]
    assert [i for i, _ in by_route["fraud_team"]] == ["RF-1070", "RF-1077"]
    assert [x for x in by_route["reviewer"] if x[0] == "RF-2183"] == [("RF-2183", "duplicate")] * 2


# ---------- cleaning ----------

@pytest.mark.parametrize("raw,expected", [
    ("42", 42.0), (" 42 ", 42.0), ("USD 120.00", 120.0), ("55.00 USD", 55.0),
    ("$1,150.00", 1150.0), ("forty", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_ambiguous_date_is_not_guessed():
    assert parse_date("12/06/2026").isoformat() == "2026-06-12"
    assert parse_date("09/06/2026") is None


@pytest.mark.parametrize("over", [
    {"tenure_months": ""}, {"days_since_delivery": "-2"}, {"fraud_flag": ""},
    {"customer_id": ""}, {"stated_reason": "refund pls"},
])
def test_bad_data_goes_to_a_person(over):
    r = row(**over)
    assert not r["data_complete"] and r["problems"]
    assert route(r, POLICY)["rule_id"] == "data-problem"


def test_flag_spellings():
    assert row(fraud_flag="Y")["fraud_flag"] == "yes"
    assert row(fraud_flag="false")["fraud_flag"] == "no"


# ---------- the engine ----------

def test_auto_and_evidence():
    d = route(row(), POLICY)
    assert d["route"] == "auto_approve" and d["rule_id"] == "auto-small-our-mistake"
    assert {"field": "amount_usd", "value": 30.0} in d["evidence"]


def test_first_match_wins():
    # A fraud flag outranks the auto-approve rule further down the list.
    assert route(row(fraud_flag="yes"), POLICY)["route"] == "fraud_team"


def test_fallback_goes_to_a_person():
    d = route(row(amount_usd="180"), POLICY)
    assert d["route"] == "reviewer" and d["rule_id"] == "no-rule"


def test_missing_value_never_matches():
    r = row()
    r["amount_usd"] = None  # bypass data_complete to test the engine on its own
    r["data_complete"] = True
    assert route(r, POLICY)["route"] == "reviewer"


def test_duplicates_within_seven_days():
    a = row(request_id="RF-1", requested_at="2026-08-01")
    b = row(request_id="RF-2", requested_at="2026-08-06")
    c = row(request_id="RF-3", requested_at="2026-08-20")
    routes = [d["rule_id"] for d in route_batch([a, b, c], POLICY)]
    assert routes == ["duplicate", "duplicate", "auto-small-our-mistake"]


def test_validate_rejects_unsafe_policy():
    p = copy.deepcopy(POLICY)
    p["fallback"]["route"] = "auto_approve"
    with pytest.raises(ValueError, match="fallback"):
        validate(p)
    p = copy.deepcopy(POLICY)
    p["rules"][0]["when"][0]["op"] = "roughly"
    with pytest.raises(ValueError, match="unknown op"):
        validate(p)


def test_latest_policy_sorts_numerically(tmp_path):
    for v in (2, 9, 10):
        (tmp_path / f"v{v}.json").write_text(json.dumps({**POLICY, "version": v}))
    assert latest_policy(tmp_path)["version"] == 10
