"""Measure a policy against decided history. Same holdout split as analysis/explore.py.

The holdout (20% of request ids, fixed seed) was looked at once, to check the line in D9.
Tune on `train` only; report `holdout` as is.
"""
import json
import random
from pathlib import Path

from .facts import FACTS
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


def labeled_requests(labels, data_dir, reader):
    """Each hand label, matched to its request (same id, and same notes where an id repeats)."""
    rows = {src: reader.read_all(dedupe(load(Path(data_dir) / f"{src}.csv"))) for src in ("history", "pending")}
    out = []
    for item in labels["items"]:
        match = item.get("notes_match", {})
        r = next(r for r in rows[item["source"]] if r["request_id"] == item["request_id"]
                 and all(r[col] == text for col, text in match.items()))
        out.append((item, r))
    return out


def evaluate_facts(labels_path, data_dir, policy, reader):
    """How well the LLM reads the notes, against hand labels, and which errors would move a request."""
    labels = json.loads(Path(labels_path).read_text())
    per_fact = {n: {"tp": 0, "fp": 0, "fn": 0} for n in FACTS}
    misses, route_changes = [], []
    pairs = labeled_requests(labels, data_dir, reader)
    for item, r in pairs:
        truth = {n: n in item["true"] for n in FACTS}
        for n in FACTS:
            if n in item.get("ambiguous", []):
                continue
            got = bool((r["facts"] or {}).get(n))
            if got and truth[n]:
                per_fact[n]["tp"] += 1
            elif got != truth[n]:
                per_fact[n]["fp" if got else "fn"] += 1
                misses.append({"request_id": r["request_id"], "fact": n, "model": got, "label": truth[n]})
        # Route the request with the model's facts and with the hand labels: does the error matter?
        as_labeled = {**r, "facts": {n: truth[n] or (n in item.get("ambiguous", []) and bool((r["facts"] or {}).get(n)))
                                     for n in FACTS}, "facts_status": "read"}
        # Separate batches: in one batch the two copies would trip the duplicate rule.
        a, b = route_batch([r], policy)[0], route_batch([as_labeled], policy)[0]
        if a["route"] != b["route"]:
            route_changes.append({"request_id": r["request_id"], "model_route": a["route"], "label_route": b["route"]})
    tp, fp, fn = (sum(m[k] for m in per_fact.values()) for k in ("tp", "fp", "fn"))
    return {
        "notes": len(pairs),
        "precision": tp / (tp + fp) if tp + fp else 1.0,
        "recall": tp / (tp + fn) if tp + fn else 1.0,
        "per_fact": per_fact,
        "misses": misses,
        "route_changes": route_changes,
        "notes_all_right": sum(1 for item, r in pairs
                               if not any(m["request_id"] == r["request_id"] for m in misses)),
    }


def cost_per_note(cache):
    """Average tokens per note from the cached batch usage (each batch's tokens split over its notes)."""
    entries = [e for e in cache.values() if e.get("batch_size")]
    tin = sum(e["batch_tokens_in"] / e["batch_size"] for e in entries) / len(entries)
    tout = sum(e["batch_tokens_out"] / e["batch_size"] for e in entries) / len(entries)
    return {"notes": len(entries), "tokens_in": round(tin), "tokens_out": round(tout),
            "model": sorted({e["model"] for e in entries})}
