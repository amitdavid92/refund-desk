"""Web server: the reviewer queue and case API, plus the static screens in web/.

Run: refund-desk serve   (http://localhost:8000)
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .facts import FACTS, FactReader, gemini_client
from .load import load
from .overview import overview
from .preview import preview
from .rules import latest_policy, publish, rollback, route_batch, versions, with_rule
from .translate import EXAMPLES, Translator, gemini_translator

ROOT = Path(__file__).resolve().parent.parent
ACTIONS = ("approve", "reject", "partial", "ask")
MIN_REASON = 8


class Desk:
    """Routed requests for one input file, plus the reviewer decisions recorded on them."""

    def __init__(self, requests_path, policy_dir, cache_path, decisions_path, ask=None):
        self.policy_dir = policy_dir
        self.policy = latest_policy(policy_dir)
        try:
            self.requests = FactReader(cache_path, ask).read_all(load(requests_path))
        except Exception as e:  # LLM down or out of quota: serve from the cache, unread goes to a person
            print(f"LLM unavailable ({str(e)[:80]}); using the cache only")
            self.requests = FactReader(cache_path, None).read_all(load(requests_path))
        self.routes = route_batch(self.requests, self.policy)
        self.keys = case_keys(self.requests)
        self.decisions_path = Path(decisions_path)
        self.decided = {}
        if self.decisions_path.exists():
            for line in self.decisions_path.read_text().splitlines():
                d = json.loads(line)
                self.decided[d["key"]] = d

    def reload_policy(self):
        """After a publish or rollback, open cases are routed by the new live version."""
        self.policy = latest_policy(self.policy_dir)
        self.routes = route_batch(self.requests, self.policy)

    def cases(self):
        return zip(self.keys, self.requests, self.routes)

    def find(self, key):
        for k, r, d in self.cases():
            if k == key:
                return r, d
        raise HTTPException(404, f"no case {key}")

    def record(self, key, entry):
        self.decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with self.decisions_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
        self.decided[key] = entry


def case_keys(requests):
    """request_id is not unique (RF-2183 arrives twice), so a case key adds a counter."""
    totals, seen, keys = Counter(r["request_id"] for r in requests), Counter(), []
    for r in requests:
        seen[r["request_id"]] += 1
        rid = r["request_id"]
        keys.append(rid if totals[rid] == 1 else f"{rid}-{seen[rid]}")
    return keys


def summary(key, r, d, decided):
    return {
        "key": key,
        "request_id": r["request_id"],
        "amount": r["amount_usd"],
        "reason": r["stated_reason"],
        "requested_at": r["requested_at"].isoformat() if r["requested_at"] else None,
        "route": d["route"],
        "rule_id": d["rule_id"],
        "rule_name": d["rule_name"],
        "why": d["why"],
        "quotes": [e["quote"] for e in d["evidence"] if e.get("quote")],
        "evidence": d["evidence"],
        "problems": r["problems"],
        "customer_note": r["customer_note"],
        "support_note": r["support_note"],
        "decided": decided.get(key),
    }


def detail(key, r, d, decided):
    return {
        **summary(key, r, d, decided),
        "customer_id": r["customer_id"],
        "english": r["english"],
        "facts_status": r["facts_status"],
        # Every "yes" the LLM gave, with the words behind it. They feed rules; they never decide.
        "facts": [{"name": n, "question": FACTS[n], **r["fact_quotes"].get(n, {})}
                  for n, v in (r["facts"] or {}).items() if v],
        "default_action": d["default_action"],
        "rule_id": d["rule_id"],
        "policy_version": d["policy_version"],
        "order": {
            "category": r["category"], "payment_method": r["payment_method"],
            "days_since_delivery": r["days_since_delivery"], "fraud_flag": r["fraud_flag"],
        },
        "customer": {"tenure_months": r["tenure_months"], "prior_refunds_12m": r["prior_refunds_12m"]},
    }


class Decision(BaseModel):
    action: str
    reason: str = ""
    amount: float | None = None
    ask_for: str = ""
    reviewer: str = "Demo reviewer"


def check(decision, r, d):
    """The rules a decision must follow (D5). Returns an error message or None."""
    if d["route"] != "reviewer":
        return "This case is not with a reviewer."
    if decision.action not in ACTIONS:
        return f"Unknown action {decision.action!r}."
    if decision.action == "partial":
        if decision.amount is None or not 0 < decision.amount < (r["amount_usd"] or 0):
            return f"A partial refund must be more than $0 and less than ${r['amount_usd']:.2f}."
    if decision.action == "ask" and not decision.ask_for.strip():
        return "Say what to ask the customer for."
    against_rule = d["default_action"] is not None and decision.action != d["default_action"]
    if against_rule and len(decision.reason.strip()) < MIN_REASON:
        return "This differs from the rule default, so a short reason is required."
    return None


class Change(BaseModel):
    text: str


class Draft(BaseModel):
    rule: dict
    insert_before: str | None = None
    text: str = ""
    summary: str = ""
    author: str = "Refund Operations Manager"


class Rollback(BaseModel):
    version: int
    author: str = "Refund Operations Manager"


def version_summary(p):
    return {k: p[k] for k in ("version", "title", "author", "created_at", "changes")}


def create_app(requests_path=ROOT / "data" / "pending.csv", policy_dir=ROOT / "policy",
               cache_path=ROOT / "cache" / "facts.json", decisions_path=ROOT / "state" / "decisions.jsonl",
               history_path=ROOT / "data" / "history.csv",
               translations_path=ROOT / "cache" / "translations.json",
               ask="auto", translate_ask="auto"):
    ask = gemini_client() if ask == "auto" else ask
    desk = Desk(requests_path, policy_dir, cache_path, decisions_path, ask)
    translator = Translator(translations_path, gemini_translator() if translate_ask == "auto" else translate_ask)
    # Preview reads history and pending from the cache only: it must be quick and never spend quota.
    preview_reader = FactReader(cache_path, None)
    app = FastAPI(title="Refund Desk")

    def draft_of(body):
        try:
            return with_rule(desk.policy, body.rule, body.insert_before)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(422, f"This rule cannot be applied: {e}")

    @app.get("/api/overview")
    def overview_numbers():
        return overview(history_path)

    @app.get("/api/policy")
    def policy():
        return {"live": desk.policy, "versions": [version_summary(p) for p in versions(policy_dir)],
                "examples": EXAMPLES}

    @app.post("/api/policy/translate")
    def translate(body: Change):
        if not body.text.strip():
            raise HTTPException(422, "Write the change first.")
        try:
            return translator.translate(body.text, desk.policy)
        except LookupError as e:
            raise HTTPException(503, str(e))

    @app.post("/api/policy/preview")
    def preview_change(body: Draft):
        return preview(desk.policy, draft_of(body), history_path, requests_path, preview_reader)

    @app.post("/api/policy/publish")
    def publish_change(body: Draft):
        draft = draft_of(body)
        rule = next(r for r in draft["rules"] if r not in desk.policy["rules"])
        new = publish(policy_dir, draft, body.text.strip() or rule["name"], body.author,
                      [f"Added rule '{rule['name']}': {body.summary or rule['why']}"])
        desk.reload_policy()
        return version_summary(new)

    @app.post("/api/policy/rollback")
    def rollback_to(body: Rollback):
        try:
            new = rollback(policy_dir, body.version, body.author)
        except FileNotFoundError:
            raise HTTPException(404, f"no version {body.version}")
        desk.reload_policy()
        return version_summary(new)

    @app.get("/api/queue")
    def queue():
        items = [summary(k, r, d, desk.decided) for k, r, d in desk.cases()]
        open_reviewer = [i for i in items if i["route"] == "reviewer" and not i["decided"]]
        return {
            "policy_version": desk.policy["version"],
            "counts": {"all": len(items), **Counter(i["route"] for i in items),
                       "open": len(open_reviewer)},
            "items": items,
        }

    @app.get("/api/case/{key}")
    def case(key: str):
        r, d = desk.find(key)
        return detail(key, r, d, desk.decided)

    @app.post("/api/case/{key}/decision")
    def decide(key: str, decision: Decision):
        r, d = desk.find(key)
        if key in desk.decided:
            raise HTTPException(409, "This case was already decided.")
        error = check(decision, r, d)
        if error:
            raise HTTPException(422, error)
        entry = {
            "key": key, "request_id": r["request_id"], "action": decision.action,
            "amount": decision.amount if decision.action == "partial" else
                      (r["amount_usd"] if decision.action == "approve" else 0),
            "reason": decision.reason.strip(), "ask_for": decision.ask_for.strip(),
            "rule_id": d["rule_id"], "default_action": d["default_action"],
            "against_rule": d["default_action"] is not None and decision.action != d["default_action"],
            "policy_version": d["policy_version"], "reviewer": decision.reviewer,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        desk.record(key, entry)
        following = [k for k, _, rd in desk.cases() if rd["route"] == "reviewer" and k not in desk.decided]
        return {"recorded": entry, "next": following[0] if following else None}

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app
