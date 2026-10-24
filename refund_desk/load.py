"""Read a refund CSV and clean it. Every fix is recorded in `problems`, never hidden.

A value we cannot read becomes None. The rules treat None as "missing" and send the
request to a person (D2): we never guess a value that could move money.
"""
import csv
import re
from datetime import date
from pathlib import Path

REASONS = {"wrong_size", "changed_mind", "arrived_damaged",
           "wrong_item", "never_arrived", "late_delivery"}
REASON_ALIASES = {"late": "late_delivery", "damaged": "arrived_damaged"}
FLAGS = {"yes": "yes", "y": "yes", "true": "yes", "no": "no", "n": "no", "false": "no"}
# Data spans Jun-Sep 2026: an ambiguous DD/MM date is resolved only if one reading lands there.
DATE_MONTHS = range(6, 10)


def parse_amount(raw):
    s = raw.strip()
    m = re.fullmatch(r"(?:\$|USD\s*)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*USD)?", s)
    return float(m.group(1).replace(",", "") + (m.group(2) or "")) if m else None


def parse_date(raw):
    s = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s):
        return date.fromisoformat(s[:10])
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        a, b, y = map(int, m.groups())
        readings = [(d, mo) for d, mo in ((a, b), (b, a)) if mo in DATE_MONTHS and d <= 31]
        if len(readings) == 1:
            d, mo = readings[0]
            return date(y, mo, d)
    return None


def parse_int(raw):
    s = raw.strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def norm_reason(raw):
    s = raw.strip().lower().replace(" ", "_")
    s = REASON_ALIASES.get(s, s)
    return s if s in REASONS else None


def clean(row):
    """One raw CSV row -> one request dict with typed values and a list of problems."""
    problems = []

    def note(col, msg):
        problems.append(f"{col}: {msg}")

    amount = parse_amount(row["amount_usd"])
    if amount is None:
        note("amount_usd", f"cannot read '{row['amount_usd']}'")
    elif not re.fullmatch(r"\d+(\.\d+)?", row["amount_usd"]):
        note("amount_usd", f"read '{row['amount_usd']}' as {amount}")

    requested_at = parse_date(row["requested_at"])
    if requested_at is None:
        note("requested_at", f"cannot read '{row['requested_at']}'")

    tenure = parse_int(row["tenure_months"])
    if tenure is None:
        note("tenure_months", "missing")

    days = parse_int(row["days_since_delivery"])
    if days is None:
        note("days_since_delivery", "missing")
    elif days < 0:
        note("days_since_delivery", f"impossible value {days}")

    flag = FLAGS.get(row["fraud_flag"].strip().lower())
    if flag is None:
        note("fraud_flag", f"cannot read '{row['fraud_flag']}'")

    reason = norm_reason(row["stated_reason"])
    if reason is None:
        note("stated_reason", f"unknown '{row['stated_reason']}'")

    customer_id = row["customer_id"].strip() or None
    if customer_id is None:
        note("customer_id", "missing")

    prior = parse_int(row["prior_refunds_12m"])
    if prior is None:
        note("prior_refunds_12m", "missing")

    return {
        "request_id": row["request_id"].strip(),
        "requested_at": requested_at,
        "customer_id": customer_id,
        "tenure_months": tenure,
        "prior_refunds_12m": prior,
        "amount_usd": amount,
        "category": row["category"].strip().lower(),
        "payment_method": row["payment_method"].strip().lower(),
        "stated_reason": reason,
        "customer_note": row["customer_note"].strip(),
        "support_note": row["support_note"].strip(),
        "days_since_delivery": days,
        "fraud_flag": flag,
        # History-only columns; empty in pending.
        "decision": row.get("decision", "").strip(),
        "decided_by": row.get("decided_by", "").strip(),
        "outcome_note": row.get("outcome_note", "").strip(),
        "review_minutes": parse_int(row.get("review_minutes", "") or ""),
        "problems": problems,
        # Until facts.py reads the notes, text counts as unread and no rule treats it as clean.
        "facts": None if (row["customer_note"].strip() or row["support_note"].strip()) else {},
        "fact_quotes": {},
        "english": "",
        "facts_status": "unread" if (row["customer_note"].strip() or row["support_note"].strip()) else "no_text",
        # Values the rules must never act on: missing, unreadable or impossible.
        "data_complete": all(v is not None for v in (amount, tenure, days, flag, reason, customer_id, prior))
                         and days >= 0,
        "raw": row,
    }


def load(path):
    with open(Path(path), encoding="utf-8", newline="") as f:
        return [clean(r) for r in csv.DictReader(f)]


def dedupe(rows):
    """Collapse rows that are identical in the raw file (history has a few exact copies)."""
    seen, out = set(), []
    for r in rows:
        key = tuple(r["raw"].values())
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def outcome_kind(r):
    """What happened after a historical decision. Used only for evaluation and preview."""
    o = r["outcome_note"].lower()
    if not o:
        return "none"
    if "chargeback" in o:
        return "chargeback"
    if "appeal" in o or "escalated" in o:
        return "appeal_overturned"
    if "fraud team confirmed" in o:
        return "fraud_confirmed"
    return "other"


def is_bad_outcome(r):
    return outcome_kind(r) in ("chargeback", "appeal_overturned")
