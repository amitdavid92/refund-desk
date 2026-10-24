"""The numbers to watch after the line goes live (D7), week by week from decided history.

Three numbers: how much goes through automatically, reviewer minutes, and money lost.
"Lost" is a chargeback or an overturned appeal, plus the $25 chargeback fee (policy note 7).
"""
from collections import Counter, defaultdict
from datetime import timedelta

from .load import dedupe, is_bad_outcome, load, outcome_kind
from .preview import CHARGEBACK_FEE


def lost(r):
    return (r["amount_usd"] or 0) + (CHARGEBACK_FEE if outcome_kind(r) == "chargeback" else 0)


def overview(history_path):
    rows = dedupe(load(history_path))
    weeks = defaultdict(list)
    for r in rows:
        if r["requested_at"]:
            weeks[r["requested_at"] - timedelta(days=r["requested_at"].weekday())].append(r)
    # The newest week is cut off by the end of the sample; leave it out so it doesn't read as a drop.
    starts = sorted(weeks)[:-1]

    series = []
    for start in starts:
        rs = weeks[start]
        auto = [r for r in rs if r["decided_by"] == "auto"]
        people = [r for r in rs if r["decided_by"] != "auto"]
        minutes = [r["review_minutes"] for r in people if r["review_minutes"] is not None]
        bad = [r for r in rs if is_bad_outcome(r)]
        series.append({
            "week": start.isoformat(),
            "auto": len(auto),
            "people": len(people),
            "auto_rate": round(len(auto) / len(rs) * 100),
            "review_minutes": round(sum(minutes) / len(minutes), 1) if minutes else None,
            "lost": round(sum(lost(r) for r in bad), 2),
            "lost_on_auto": round(sum(lost(r) for r in bad if r["decided_by"] == "auto"), 2),
        })

    people = [r for r in rows if r["decided_by"] != "auto"]
    return {
        "weeks": series,
        "totals": {"rows": len(rows), "auto": sum(r["decided_by"] == "auto" for r in rows), "people": len(people)},
        "people_decided": dict(Counter(r["decision"] for r in people if r["decision"])),
    }
