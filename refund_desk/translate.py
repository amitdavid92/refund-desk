"""Turn the manager's sentence into a rule the engine can apply (D4-A).

The LLM proposes one reading, or several when the wording is ambiguous. Every reading is
checked by rules.validate before anyone sees it, so a reading can only use real fields,
real values and real routes. The manager picks a reading, sees the preview, and only then
publishes. The LLM never publishes anything.

Translations are cached by wording in cache/translations.json, so the demo examples work
without an API key.
"""
import hashlib
import json
from pathlib import Path

from .facts import MODEL, RETRYABLE
from .rules import FIELDS, ROUTES, with_rule

PROMPT_VERSION = 2
EXAMPLES = [
    "From now on, stolen-card cases go straight through.",
    "From now on, anything over $300 comes to us.",
]

SYSTEM = """You turn a refund-policy change, written by the Refund Operations Manager, into rules
for a fixed rule engine. You do not decide refunds.

The engine checks rules top to bottom; the first rule whose conditions all hold sets the route.
Routes: auto_approve (refund without a person), reviewer (a person decides), fraud_team.
Default actions for a reviewer (or null): approve, reject, partial, ask.

Return one reading if the wording has one clear meaning. If it could reasonably mean different
things, return each meaning as its own reading, at most 3. Check two kinds of ambiguity:
- which data: when more than one field could carry the meaning (for example an automatic flag
  versus a confirmation written in the notes), give a reading for each field;
- which route: when the words could mean different routes.
data_source describes the fields the reading uses, from the field list below: who sets them and
how reliable they are (for example "the payment provider's automatic risk check, not a
confirmation"). Do not describe the manager's wording.

Each condition has field, op (eq, ne, lt, le, gt, ge, in) and value written as text:
a number as digits, a yes/no fact as true or false, a list for "in" as comma-separated values.
Use only these fields:
{fields}

Current rules, in order (id: name -> route). Locked rules are safety checks; a new rule always
goes below them:
{rules}

insert_before is the id of the existing rule the new rule must be checked before, usually the
rule it overrides. why is one plain sentence shown to the reviewer: for reviewer start with
"Sent to you because", for auto_approve start with "Approved automatically:", for fraud_team
start with "Sent to the fraud team because"."""

SCHEMA = {
    "type": "object",
    "properties": {"readings": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "data_source": {"type": "string"},
            "name": {"type": "string"},
            "conditions": {"type": "array", "items": {
                "type": "object",
                "properties": {"field": {"type": "string"}, "op": {"type": "string"}, "value": {"type": "string"}},
                "required": ["field", "op", "value"]}},
            "route": {"type": "string", "enum": sorted(ROUTES)},
            "default_action": {"type": "string", "enum": ["approve", "reject", "partial", "ask", "none"]},
            "why": {"type": "string"},
            "insert_before": {"type": "string"},
        },
        "required": ["summary", "data_source", "name", "conditions", "route", "default_action", "why", "insert_before"],
    }}},
    "required": ["readings"],
}


def system_prompt(policy):
    fields = "\n".join(f"- {name} ({kind}{': ' + ', '.join(allowed) if allowed else ''}): {meaning}"
                       for name, (kind, allowed, meaning) in FIELDS.items())
    rules = "\n".join(f"- {r['id']}: {r['name']} -> {r['route']}{' (locked)' if r.get('locked') else ''}"
                      for r in policy["rules"])
    return SYSTEM.format(fields=fields, rules=rules)


def coerce(field, op, text):
    kind = FIELDS.get(field, ("text", None, ""))[0]

    def one(v):
        v = v.strip()
        if kind == "number":
            return float(v.lstrip("$").replace(",", ""))
        if kind == "bool":
            return v.lower() == "true"
        return v
    return [one(v) for v in text.split(",")] if op == "in" else one(text)


def to_rule(reading):
    return {
        "name": reading["name"],
        "when": [{"field": c["field"], "op": c["op"], "value": coerce(c["field"], c["op"], c["value"])}
                 for c in reading["conditions"]],
        "route": reading["route"],
        "default_action": None if reading["default_action"] == "none" else reading["default_action"],
        "why": reading["why"],
    }


def check_readings(raw, policy):
    """Keep only readings the engine can apply. Returns (readings, rejected with reasons)."""
    ok, rejected = [], []
    for i, reading in enumerate(raw):
        try:
            rule = to_rule(reading)
            draft = with_rule(policy, rule, reading["insert_before"])
        except (ValueError, KeyError, TypeError) as e:
            rejected.append({"summary": reading.get("summary", ""), "problem": str(e)})
            continue
        placed = next(r for r in draft["rules"] if r not in policy["rules"])
        position = draft["rules"].index(placed)
        ok.append({"id": i, "summary": reading["summary"], "data_source": reading["data_source"],
                   "rule": placed, "insert_before": draft["rules"][position + 1]["id"]
                   if position + 1 < len(draft["rules"]) else None})
    return ok, rejected


def gemini_translator():
    import os
    import time
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)

    def ask(text, policy):
        for attempt in range(6):
            try:
                response = client.models.generate_content(
                    model=MODEL, contents=f"<change>{text}</change>",
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt(policy), temperature=0,
                        response_mime_type="application/json", response_json_schema=SCHEMA))
                return json.loads(response.text)["readings"]
            except Exception as e:
                if not any(c in str(e) for c in RETRYABLE) or "PerDay" in str(e) or attempt == 5:
                    raise
                time.sleep(min(60, 5 * 2 ** attempt))
    return ask


class Translator:
    def __init__(self, cache_path, ask=None):
        self.cache_path = Path(cache_path)
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self.ask = ask

    def key(self, text):
        # By wording only. A cached reading is re-checked against the live rules on every use.
        norm = " ".join(text.lower().split())
        return hashlib.sha256(json.dumps([PROMPT_VERSION, norm]).encode()).hexdigest()[:16]

    def translate(self, text, policy):
        """Returns {"readings": [...], "rejected": [...]} or raises LookupError when it cannot read."""
        key = self.key(text)
        raw = self.cache.get(key, {}).get("raw")
        if raw is None:
            if self.ask is None:
                raise LookupError("Reading new wording needs the LLM (GEMINI_API_KEY). Try one of the examples.")
            raw = self.ask(text, policy)
            self.cache[key] = {"text": text, "model": MODEL, "raw": raw}
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True, ensure_ascii=False))
        readings, rejected = check_readings(raw, policy)
        return {"readings": readings, "rejected": rejected}
