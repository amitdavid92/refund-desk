"""Measure a policy against decided history. Same holdout split as analysis/explore.py.

The holdout (20% of request ids, fixed seed) was looked at once, to check the line in D9.
Tune on `train` only; report `holdout` as is.
"""
import random

from .load import dedupe, is_bad_outcome, load
from .rules import route_batch

SEED = 20261020
HOLDOUT_FRACTION = 0.2


def split(history):
    ids = sorted({r["request_id"] for r in history})
    holdout = set(random.Random(SEED).sample(ids, round(len(ids) * HOLDOUT_FRACTION)))
    train = dedupe([r for r in history if r["request_id"] not in holdout])
    held = dedupe([r for r in history if r["request_id"] in holdout])
    return train, held


def evaluate(rows, policy):
    decisions = route_batch(rows, policy)
    auto = [(r, d) for r, d in zip(rows, decisions) if d["route"] == "auto_approve"]
    sent = [(r, d) for r, d in zip(rows, decisions) if d["route"] != "auto_approve"]
    return {
        "rows": len(rows),
        "auto": len(auto),
        "auto_share": len(auto) / len(rows) if rows else 0.0,
        # Approved without a person, but ended in a chargeback or an overturned appeal.
        "auto_bad": [r["request_id"] for r, _ in auto if is_bad_outcome(r)],
        # Approved without a person, but a person had rejected or cut it.
        "auto_humans_disagreed": [r["request_id"] for r, _ in auto
                                  if r["decided_by"] != "auto" and r["decision"] != "approved"],
        "bad_caught": [r["request_id"] for r, _ in sent if is_bad_outcome(r)],
        "reviewer_minutes_saved": sum(r["review_minutes"] or 0 for r, _ in auto),
    }


def evaluate_history(history_path, policy, reader=None):
    train, held = split(load(history_path))
    if reader:
        reader.read_all(train + held)
    return {"train": evaluate(train, policy), "holdout": evaluate(held, policy)}
