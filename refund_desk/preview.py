"""What a policy change would do, before it goes live (D4-A).

Runs the live policy and the draft side by side on decided history and on the pending
batch, and reports only the requests whose route changes.
"""
from .load import dedupe, is_bad_outcome, load, outcome_kind
from .rules import route_batch

CHARGEBACK_FEE = 25  # policy note 7: every chargeback costs the order amount plus $25


def changes(requests, live, draft):
    out = []
    for r, a, b in zip(requests, route_batch(requests, live), route_batch(requests, draft)):
        if a["route"] != b["route"] or a["rule_id"] != b["rule_id"]:
            out.append((r, a, b))
    return out


def row(r, a, b):
    return {
        "request_id": r["request_id"],
        "amount": r["amount_usd"],
        "reason": r["stated_reason"],
        "from": a["route"], "from_rule": a["rule_name"],
        "to": b["route"], "to_rule": b["rule_name"],
        # False when only the rule changes: same route, but a different reason shown to the reviewer.
        "route_changed": a["route"] != b["route"],
        "decision": r["decision"] or None,
        "outcome": r["outcome_note"] or None,
        "bad": is_bad_outcome(r),
    }


def preview(live, draft, history_path, pending_path, reader):
    history = reader.read_all(dedupe(load(history_path)))
    pending = reader.read_all(load(pending_path))

    hist = [row(*c) for c in changes(history, live, draft)]
    pend = [row(*c) for c in changes(pending, live, draft)]
    to_auto = lambda rows: [x for x in rows if x["to"] == "auto_approve" and x["from"] != "auto_approve"]
    from_auto = lambda rows: [x for x in rows if x["from"] == "auto_approve" and x["to"] != "auto_approve"]

    bad = [x for x in to_auto(hist) if x["bad"]]
    lost = sum((x["amount"] or 0) + (CHARGEBACK_FEE if "chargeback" in (x["outcome"] or "") else 0) for x in bad)
    return {
        "pending": {
            "changed": pend,
            "route_changed_count": sum(x["route_changed"] for x in pend),
            "to_auto_count": len(to_auto(pend)),
            "to_auto_money": round(sum(x["amount"] or 0 for x in to_auto(pend)), 2),
        },
        "history": {
            "rows": len(history),
            "changed": hist,
            "route_changed_count": sum(x["route_changed"] for x in hist),
            "to_auto_count": len(to_auto(hist)),
            "to_auto_money": round(sum(x["amount"] or 0 for x in to_auto(hist)), 2),
            "from_auto_count": len(from_auto(hist)),
            # Past cases the draft would have approved without a person, that ended badly.
            "bad_cases": bad,
            "bad_money": round(lost, 2),
            # Approved without a person now, though a person had rejected or cut them.
            "humans_disagreed": [x for x in to_auto(hist) if x["decision"] in ("rejected", "partial")],
            "fraud_confirmed": sum(outcome_kind_of(x) == "fraud_confirmed" for x in to_auto(hist)),
        },
    }


def outcome_kind_of(x):
    return outcome_kind({"outcome_note": x["outcome"] or ""})
