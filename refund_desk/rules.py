"""Apply a policy to requests. Deterministic: the same policy and request always give the same route.

A policy is an ordered list of rules; the first rule whose conditions all hold decides the route.
No rule matches -> the fallback, which always sends the request to a person (D2).
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .facts import FACTS
from .load import REASONS

ROUTES = {"auto_approve", "reviewer", "fraud_team"}
# Every field a rule may read: name -> (kind, allowed values or None, meaning).
FIELDS = {
    "amount_usd": ("number", None, "Requested refund in US dollars."),
    "stated_reason": ("text", sorted(REASONS), "Reason the customer picked."),
    "tenure_months": ("number", None, "Months since the account was created."),
    "prior_refunds_12m": ("number", None, "Refunds granted to this customer in the last 12 months."),
    "days_since_delivery": ("number", None, "Days between delivery and the request."),
    "fraud_flag": ("text", ["yes", "no"], "Set by the payment provider's automatic risk check. Not a confirmation of fraud."),
    "category": ("text", ["apparel", "home", "electronics"], "Product category."),
    "payment_method": ("text", ["card", "paypal"], "How the order was paid."),
    "data_complete": ("bool", None, "False when a value is missing, unreadable or impossible."),
    "duplicate": ("bool", None, "True when the same request appears more than once in the batch."),
    "facts_status": ("text", ["no_text", "read", "unread"], "Whether the LLM has read the notes."),
    **{f"facts.{name}": ("bool", None, f"Read from the notes by the LLM: {q}") for name, q in FACTS.items()},
}
ACTIONS = {"approve", "reject", "partial", "ask", None}
OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "in": lambda a, b: a in b,
}
DUPLICATE_WINDOW = timedelta(days=7)


def load_policy(path):
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(policy)
    return policy


def version_paths(policy_dir):
    return sorted(Path(policy_dir).glob("v*.json"), key=lambda p: int(p.stem[1:]))


def latest_policy(policy_dir, override=None):
    """The live policy is the highest version in policy/ (D13), unless a file is given."""
    if override:
        return load_policy(override)
    versions = version_paths(policy_dir)
    if not versions:
        raise FileNotFoundError(f"no policy versions in {policy_dir}")
    return load_policy(versions[-1])


def validate(policy):
    """Reject a policy the engine cannot apply exactly. Raises ValueError naming the problem."""
    seen_unlocked = False
    ids = [r["id"] for r in policy["rules"]]
    if len(ids) != len(set(ids)):
        raise ValueError("rule ids must be unique")
    for rule in policy["rules"]:
        validate_rule(rule)
        if not rule["when"]:
            raise ValueError(f"rule {rule['id']}: a rule needs at least one condition")
        if rule.get("locked") and seen_unlocked:
            raise ValueError(f"rule {rule['id']}: safety checks must stay above every other rule")
        seen_unlocked = seen_unlocked or not rule.get("locked")
    validate_rule(policy["fallback"])
    if policy["fallback"]["route"] == "auto_approve":
        raise ValueError("the fallback must send requests to a person")


def validate_rule(rule):
    if rule["route"] not in ROUTES:
        raise ValueError(f"rule {rule['id']}: unknown route {rule['route']!r}")
    if rule["default_action"] not in ACTIONS:
        raise ValueError(f"rule {rule['id']}: unknown action {rule['default_action']!r}")
    for cond in rule.get("when", []):
        if cond["field"] not in FIELDS:
            raise ValueError(f"rule {rule['id']}: unknown field {cond['field']!r}")
        if cond["op"] not in OPS:
            raise ValueError(f"rule {rule['id']}: unknown op {cond['op']!r}")
        kind, allowed, _ = FIELDS[cond["field"]]
        values = cond["value"] if cond["op"] == "in" else [cond["value"]]
        if cond["op"] == "in" and not isinstance(cond["value"], list):
            raise ValueError(f"rule {rule['id']}: 'in' needs a list")
        for v in values:
            ok = {"number": isinstance(v, (int, float)) and not isinstance(v, bool),
                  "bool": isinstance(v, bool),
                  "text": isinstance(v, str) and (allowed is None or v in allowed)}[kind]
            if not ok:
                raise ValueError(f"rule {rule['id']}: {cond['field']} cannot be {v!r}")
        if kind != "number" and cond["op"] in ("lt", "le", "gt", "ge"):
            raise ValueError(f"rule {rule['id']}: {cond['field']} cannot be compared with {cond['op']}")


def with_rule(policy, rule, insert_before):
    """A draft: the live policy with one new rule. It never goes above the locked safety checks."""
    rules = policy["rules"]
    first_open = next(i for i, r in enumerate(rules) if not r.get("locked"))
    ids = [r["id"] for r in rules]
    at = ids.index(insert_before) if insert_before in ids else len(rules)
    rule = {**rule, "id": unique_id(rule.get("id") or rule["name"], ids)}
    rule.pop("locked", None)
    draft = {**policy, "rules": rules[:max(at, first_open)] + [rule] + rules[max(at, first_open):]}
    validate(draft)
    return draft


def unique_id(base, taken):
    slug = "".join(c if c.isalnum() else "-" for c in base.lower()).strip("-")[:40] or "rule"
    out, n = slug, 2
    while out in taken:
        out, n = f"{slug}-{n}", n + 1
    return out


def publish(policy_dir, draft, title, author, changes):
    """Write the draft as the next version. Nothing is overwritten (D6, D13)."""
    versions = version_paths(policy_dir)
    number = int(versions[-1].stem[1:]) + 1 if versions else 1
    new = {**draft, "version": number, "title": title, "author": author,
           "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "changes": changes}
    validate(new)
    path = Path(policy_dir) / f"v{number}.json"
    path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return new


def rollback(policy_dir, version, author):
    """Publish an old version's rules again as a new version."""
    old = load_policy(Path(policy_dir) / f"v{version}.json")
    return publish(policy_dir, old, f"Roll back to v{version}", author,
                   [f"Rules restored from v{version}: {old['title']}"])


def versions(policy_dir):
    return [load_policy(p) for p in reversed(version_paths(policy_dir))]


def field(request, name):
    """Dotted lookup, so rules can read LLM facts as e.g. 'facts.refund_elsewhere'."""
    value = request
    for part in name.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def holds(cond, request):
    value = field(request, cond["field"])
    # Missing never satisfies a condition, except an explicit check for missing.
    if value is None:
        return cond["op"] == "eq" and cond["value"] is None
    try:
        return OPS[cond["op"]](value, cond["value"])
    except TypeError:
        return False


def route(request, policy):
    for rule in policy["rules"]:
        if all(holds(c, request) for c in rule["when"]):
            return decision(request, rule, policy)
    return decision(request, policy["fallback"], policy)


def decision(request, rule, policy):
    return {
        "request_id": request["request_id"],
        "route": rule["route"],
        "rule_id": rule["id"],
        "rule_name": rule["name"],
        "why": rule["why"],
        "default_action": rule["default_action"],
        # The values that made the rule match, so the reviewer sees the evidence, not just the verdict.
        "evidence": [evidence(request, c["field"]) for c in rule.get("when", [])],
        "policy_version": policy["version"],
    }


def evidence(request, name):
    item = {"field": name, "value": field(request, name)}
    if name.startswith("facts."):
        # The exact words the LLM pointed to, so the reviewer can check them (D3).
        item.update(request.get("fact_quotes", {}).get(name.split(".", 1)[1], {}))
    return item


def mark_duplicates(requests):
    """Flag a request that repeats another in the same batch (D10).

    Same request_id with different content, or the same customer with the same reason
    within 7 days. Both copies are flagged: approving either one could pay twice.
    """
    for r in requests:
        r["duplicate"] = False
    for i, a in enumerate(requests):
        for b in requests[i + 1:]:
            same_id = a["request_id"] == b["request_id"] and a["raw"] != b["raw"]
            same_claim = (a["customer_id"] and a["customer_id"] == b["customer_id"]
                          and a["stated_reason"] == b["stated_reason"]
                          and a["requested_at"] and b["requested_at"]
                          and abs(a["requested_at"] - b["requested_at"]) <= DUPLICATE_WINDOW)
            if same_id or same_claim:
                a["duplicate"] = b["duplicate"] = True
    return requests


def route_batch(requests, policy):
    return [route(r, policy) for r in mark_duplicates(requests)]
