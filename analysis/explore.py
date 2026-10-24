"""Exploration of the Windward refund data. Read-only: never modifies the source CSVs.

Run:  python3 analysis/explore.py   (step 2 on all rows, steps 3-4 on the train split only)
Every number in the write-up comes from this output (analysis/explore_output.txt). Standard library only.
"""
import csv
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent / "data"
SEED = 20261020
HOLDOUT_FRACTION = 0.2

ALLOWED = {
    "category": {"apparel", "home", "electronics"},
    "payment_method": {"card", "paypal"},
    "stated_reason": {"wrong_size", "changed_mind", "arrived_damaged",
                      "wrong_item", "never_arrived", "late_delivery"},
    "fraud_flag": {"yes", "no"},
    "decision": {"approved", "rejected", "partial", "pending"},
}


def load(name):
    with open(ROOT / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def section(title):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def ids(rows):
    return ", ".join(r["request_id"] for r in rows)


# ---------- parsing helpers: report what they had to do, never hide it ----------

def parse_amount(raw):
    s = raw.strip()
    m = re.fullmatch(r"(?:\$|USD\s*)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?:\s*USD)?", s)
    return float(m.group(1).replace(",", "") + (m.group(2) or "")) if m else None


def parse_date(raw):
    """Return (date, format). DD/MM vs MM/DD is ambiguous - reported, not guessed silently."""
    s = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s), "iso"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", s):
        return date.fromisoformat(s[:10]), "iso-timestamp"
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        a, b, y = map(int, m.groups())
        # Data spans Jun-Aug 2026 -> month must be 6..9. Pick the reading that lands there.
        readings = [(d, mo) for d, mo in ((a, b), (b, a)) if 6 <= mo <= 9 and d <= 31]
        if len(readings) == 1:
            d, mo = readings[0]
            return date(y, mo, d), "slash-resolved"
        return None, "slash-ambiguous"
    return None, "unparsed"


def norm_flag(raw):
    s = raw.strip().lower()
    return {"yes": "yes", "y": "yes", "true": "yes",
            "no": "no", "n": "no", "false": "no"}.get(s)


def norm_reason(raw):
    s = raw.strip().lower().replace(" ", "_")
    return {"late": "late_delivery", "damaged": "arrived_damaged"}.get(s, s)


# ---------- step 2: data audit (all rows, by design) ----------

def audit_file_level(name):
    raw = (ROOT / name).read_bytes()
    with open(ROOT / name, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    widths = Counter(len(r) for r in rows)
    print(f"{name}: bytes={len(raw)} bom={raw.startswith(b'\xef\xbb\xbf')} "
          f"crlf={b'\r\n' in raw} rows(incl header)={len(rows)} field-counts={dict(widths)}")


def audit_columns(rows, label):
    print(f"\n--- {label}: {len(rows)} rows ---")
    # duplicates
    by_id = defaultdict(list)
    for r in rows:
        by_id[r["request_id"]].append(r)
    for rid, group in by_id.items():
        if len(group) > 1:
            identical = all(g == group[0] for g in group)
            diff = sorted({k for g in group for k in g if g[k] != group[0][k]})
            print(f"DUP request_id {rid} x{len(group)} identical={identical} differing={diff}")
    bad_id = [r for r in rows if not re.fullmatch(r"RF-[12]\d{3}", r["request_id"])]
    print(f"request_id not matching RF-1xxx/RF-2xxx: {len(bad_id)} {ids(bad_id)}")

    # dates
    fmt = Counter()
    for r in rows:
        d, f = parse_date(r["requested_at"])
        fmt[f] += 1
        if f != "iso":
            print(f"requested_at non-ISO: {r['request_id']} '{r['requested_at']}' -> {d} ({f})")
    print(f"requested_at formats: {dict(fmt)}")

    # amounts
    amt_odd = [(r["request_id"], r["amount_usd"]) for r in rows
               if not re.fullmatch(r"\d+(\.\d+)?", r["amount_usd"])]
    unparsed = [x for x in amt_odd if parse_amount(x[1]) is None]
    print(f"amount_usd not a plain number: {len(amt_odd)} {amt_odd}")
    print(f"amount_usd unparseable even after stripping $/USD/spaces: {unparsed}")
    amts = [parse_amount(r["amount_usd"]) for r in rows if parse_amount(r["amount_usd"]) is not None]
    if amts:
        print(f"amount_usd range: min={min(amts)} max={max(amts)}")

    # categorical columns
    for col, allowed in ALLOWED.items():
        off = Counter(r[col] for r in rows if r[col] not in allowed)
        if off:
            print(f"{col} values outside dictionary: {dict(off)}")

    # missing values
    for col in ["customer_id", "tenure_months", "days_since_delivery", "fraud_flag"]:
        miss = [r for r in rows if not r[col].strip()]
        if miss:
            print(f"{col} empty: {len(miss)} -> {ids(miss)}")

    # ranges
    for col in ["tenure_months", "prior_refunds_12m", "days_since_delivery", "review_minutes"]:
        vals = [(r["request_id"], int(r[col])) for r in rows if r[col].strip().lstrip("-").isdigit()]
        neg = [v for v in vals if v[1] < 0]
        if vals:
            print(f"{col}: min={min(v[1] for v in vals)} max={max(v[1] for v in vals)} negative={neg}")


def audit_history_consistency(hist):
    print("\n--- history: cross-column consistency ---")
    # decided_at vs requested_at
    before = []
    for r in hist:
        d, _ = parse_date(r["requested_at"])
        dec = datetime.strptime(r["decided_at"], "%Y-%m-%d %H:%M").date()
        if d and dec < d:
            before.append((r["request_id"], r["requested_at"], r["decided_at"]))
        if d is None:
            m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", r["requested_at"])
            a, b, y = map(int, m.groups())
            ok = [str(c) for c in (date(y, b, a), date(y, a, b)) if c <= dec]
            print(f"ambiguous {r['request_id']} '{r['requested_at']}' decided {r['decided_at']} "
                  f"-> readings not after decision: {ok}")
    print(f"decided_at earlier than requested_at: {len(before)} {before}")

    # review_minutes blank <=> auto
    auto_with_min = [r for r in hist if r["decided_by"] == "auto" and r["review_minutes"].strip()]
    human_no_min = [r for r in hist if r["decided_by"] != "auto" and not r["review_minutes"].strip()]
    print(f"auto with review_minutes: {len(auto_with_min)} {ids(auto_with_min)}")
    print(f"human without review_minutes: {len(human_no_min)} {ids(human_no_min)}")

    # auto decisions that are not 'approved' (rule is auto-approve)
    auto_not_appr = [r for r in hist if r["decided_by"] == "auto" and r["decision"] != "approved"]
    print(f"auto but not approved: {len(auto_not_appr)} {ids(auto_not_appr)}")

    # partial decisions vs outcome note
    for r in hist:
        if r["decision"] == "partial" or "percent" in r["outcome_note"] or "shipping" in r["outcome_note"]:
            print(f"partial-ish: {r['request_id']} decision={r['decision']} outcome='{r['outcome_note']}'")

    # channel (ID prefix) vs support_note
    for prefix, name in (("RF-1", "web form"), ("RF-2", "support desk")):
        grp = [r for r in hist if r["request_id"].startswith(prefix)]
        with_note = sum(1 for r in grp if r["support_note"].strip())
        auto = sum(1 for r in grp if r["decided_by"] == "auto")
        print(f"{prefix} ({name}): n={len(grp)} support_note filled={with_note} auto={auto}")

    # prior_refunds_12m vs refunds visible in this file for the same customer
    by_cust = defaultdict(list)
    for r in hist:
        if r["customer_id"]:
            by_cust[r["customer_id"]].append(r)
    repeat = {c: g for c, g in by_cust.items() if len(g) > 1}
    print(f"customers appearing more than once: {len(repeat)}")
    for c, g in repeat.items():
        print(f"  {c}: " + "; ".join(
            f"{r['request_id']} {r['requested_at']} prior={r['prior_refunds_12m']} "
            f"${r['amount_usd'].strip()} {r['stated_reason']} -> {r['decision']}" for r in g))

    # fraud flag vs decision/outcome
    print("\nfraud_flag (normalized) x decision x decided_by-is-auto:")
    tab = Counter((norm_flag(r["fraud_flag"]), r["decision"], r["decided_by"] == "auto") for r in hist)
    for k, v in sorted(tab.items(), key=str):
        print(f"  flag={k} decision={k[1]} auto={k[2]}: {v}")

    # outcome notes - all distinct values (needed to judge leakage; full reading is step 3)
    print("\noutcome_note distinct values:")
    for v, n in Counter(r["outcome_note"] for r in hist).most_common():
        print(f"  {n:3d}  '{v}'")


def audit_free_text(rows, label):
    print(f"\n--- {label}: free-text signals ---")
    non_ascii = [(r["request_id"], col, r[col]) for r in rows for col in ("customer_note", "support_note")
                 if r[col] and any(ord(ch) > 127 for ch in r[col])]
    print(f"non-ASCII notes (other languages): {len(non_ascii)}")
    for x in non_ascii:
        print(f"  {x}")
    instr = re.compile(r"system note|pre-?approved|set decision|skip (human )?review|ignore|manager .* (said|approved)", re.I)
    inj = [(r["request_id"], r["customer_note"]) for r in rows if instr.search(r["customer_note"])]
    print(f"customer_note containing instructions / authority claims: {inj}")


def compare_pending(hist, pend):
    print("\n--- pending vs history ---")
    hist_ids = {r["request_id"] for r in hist}
    overlap = [r["request_id"] for r in pend if r["request_id"] in hist_ids]
    print(f"pending request_ids already in history: {overlap}")
    hist_cust = {r["customer_id"] for r in hist}
    cust_overlap = [(r["request_id"], r["customer_id"]) for r in pend if r["customer_id"] in hist_cust]
    print(f"pending customers seen in history: {cust_overlap}")
    for col in ("category", "payment_method", "stated_reason"):
        h = Counter(norm_reason(r[col]) if col == "stated_reason" else r[col].lower() for r in hist)
        p = Counter(norm_reason(r[col]) if col == "stated_reason" else r[col].lower() for r in pend)
        print(f"{col}: history={dict(h)}  pending={dict(p)}")
    hd = [parse_date(r["requested_at"])[0] for r in hist]
    pdts = [parse_date(r["requested_at"])[0] for r in pend]
    print(f"history requested_at: {min(d for d in hd if d)} .. {max(d for d in hd if d)}")
    print(f"pending requested_at: {min(pdts)} .. {max(pdts)}")
    pa = [parse_amount(r["amount_usd"]) for r in pend if parse_amount(r["amount_usd"]) is not None]
    ha = [parse_amount(r["amount_usd"]) for r in hist if parse_amount(r["amount_usd"])]
    print(f"amount > 200: history {sum(a > 200 for a in ha)}/{len(ha)}  pending {sum(a > 200 for a in pa)}/{len(pa)}")
    print(f"never_arrived share: history {sum(norm_reason(r['stated_reason'])=='never_arrived' for r in hist)}/{len(hist)}"
          f"  pending {sum(norm_reason(r['stated_reason'])=='never_arrived' for r in pend)}/{len(pend)}")
    nfd = [r["request_id"] for r in hist + pend
           if re.search(r"northfield|north field|nfd", r["customer_note"] + " " + r["support_note"], re.I)]
    print(f"Northfield / NFD depot mentioned: {nfd}")


def split_history(hist):
    """Deterministic holdout. Steps 3+ use only the train part."""
    unique_ids = sorted({r["request_id"] for r in hist})
    rng = random.Random(SEED)
    holdout = set(rng.sample(unique_ids, round(len(unique_ids) * HOLDOUT_FRACTION)))
    train = [r for r in hist if r["request_id"] not in holdout]
    held = [r for r in hist if r["request_id"] in holdout]
    assert len(train) + len(held) == len(hist)
    return train, held


def step2():
    section("STEP 2 - data audit (all rows)")
    for name in ("history.csv", "pending.csv", "policy_notes.csv", "data_dictionary.csv"):
        audit_file_level(name)
    hist, pend = load("history.csv"), load("pending.csv")
    audit_columns(hist, "history")
    audit_columns(pend, "pending")
    audit_history_consistency(hist)
    audit_free_text(hist, "history")
    audit_free_text(pend, "pending")
    compare_pending(hist, pend)
    train, held = split_history(hist)
    print("\npending rows with notes (audit view):")
    for r in pend:
        print(f"  {r['request_id']} {r['requested_at']} {r['customer_id']} ${r['amount_usd']} "
              f"{r['stated_reason']} flag={r['fraud_flag'] or '<empty>'} days={r['days_since_delivery']} "
              f"prior={r['prior_refunds_12m']} tenure={r['tenure_months']} | cust: {r['customer_note']} | "
              f"support: {r['support_note']}")
    print(f"\nholdout split (seed={SEED}): train={len(train)} rows, holdout={len(held)} rows")


# ---------- steps 3-4: train split only ----------

def train_rows():
    """Train split with exact duplicate rows collapsed (assumption A1)."""
    train, _ = split_history(load("history.csv"))
    seen, out = set(), []
    for r in train:
        key = tuple(r.values())
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def amt(r):
    return parse_amount(r["amount_usd"])


def tenure(r):
    return int(r["tenure_months"]) if r["tenure_months"] else None


def days(r):
    return int(r["days_since_delivery"]) if r["days_since_delivery"] else None


def outcome_kind(r):
    o = r["outcome_note"].lower()
    if not o:
        return "none"
    if "chargeback" in o:
        return "chargeback"
    if "appeal" in o or "escalated" in o:
        return "appeal_overturned"
    if "fraud team confirmed" in o:
        return "fraud_confirmed"
    if "percent" in o or "shipping refunded" in o:
        return "partial_detail"
    if "outside 14" in o:
        return "reject_reason"
    return "other"


def reconstructed_auto_rule(r):
    """Best fit found by exhaustive search over amount/tenure/prior thresholds."""
    if amt(r) > 54 or r["prior_refunds_12m"] != "0":
        return False
    if tenure(r) is not None and tenure(r) < 9:
        return False
    if norm_reason(r["stated_reason"]) == "changed_mind" and (days(r) or 0) > 14:
        return False
    return True


def step3():
    section("STEP 3 - how it works today (train only)")
    t = train_rows()
    auto = [r for r in t if r["decided_by"] == "auto"]
    man = [r for r in t if r["decided_by"] != "auto"]
    print(f"train unique rows={len(t)} auto={len(auto)} manual={len(man)}")

    print("\n-- 3a. existing auto rule --")
    hit = [r for r in auto if reconstructed_auto_rule(r)]
    miss = [r for r in auto if not reconstructed_auto_rule(r)]
    extra = [r for r in man if reconstructed_auto_rule(r)]
    print(f"rule explains auto: {len(hit)}/{len(auto)}  missed auto: {ids(miss)}")
    print(f"manual rows the rule would also take: {len(extra)} {ids(extra)}")
    print(f"auto amount max={max(amt(r) for r in auto)}  "
          f"manual amount just above: {sorted(amt(r) for r in man if amt(r) > 54)[:3]}")
    print(f"auto tenure min={min(tenure(r) for r in auto if tenure(r))}")
    print(f"auto with fraud_flag=yes: {sum(norm_flag(r['fraud_flag']) == 'yes' for r in auto)}; "
          f"flagged requests <= $54 in train: {sum(norm_flag(r['fraud_flag']) == 'yes' and amt(r) <= 54 for r in t)}")
    odd = [r for r in auto if tenure(r) is None or (days(r) is not None and days(r) < 0)]
    print(f"auto despite missing/impossible data: {ids(odd)}")
    dmg = [r for r in auto if norm_reason(r["stated_reason"]) == "arrived_damaged" and amt(r) > 50]
    print(f"auto: damaged over $50 (policy 3 needs a photo): {ids(dmg)}")

    print("\n-- 3b. outcomes --")
    for k, v in sorted(Counter((outcome_kind(r), r["decision"], r["decided_by"] == "auto") for r in t).items()):
        print(f"  {k}: {v}")
    cb = [r for r in t if outcome_kind(r) == "chargeback"]
    ap = [r for r in t if outcome_kind(r) == "appeal_overturned"]
    print(f"chargebacks: {len(cb)} total ${sum(amt(r) for r in cb)} (+$25 each per policy 7) -> {ids(cb)}")
    print(f"appeals overturned: {len(ap)} -> {ids(ap)}")
    bad = cb + ap
    print(f"review minutes on those decisions: {[r['review_minutes'] or 'auto' for r in bad]}")

    print("\n-- 3c. reviewer time --")
    m = lambda r: float(r["review_minutes"])
    print(f"manual minutes total={sum(m(r) for r in man)} median={median(m(r) for r in man)}")
    for lo, hi in ((0, 55), (55, 100), (100, 200), (200, 10**6)):
        g = [r for r in man if lo < amt(r) <= hi]
        print(f"  ${lo}-{hi}: n={len(g)} minutes={sum(m(r) for r in g)} median={median(m(r) for r in g)}")
    for who in sorted({r["decided_by"] for r in man}):
        g = [r for r in man if r["decided_by"] == who]
        print(f"  {who}: n={len(g)} median={median(m(r) for r in g)} "
              f"bad={[r['request_id'] for r in g if r in bad]}")


def step4():
    section("STEP 4 - policy notes vs decisions (train only)")
    t = train_rows()
    reason = lambda r: norm_reason(r["stated_reason"])
    note = lambda r: r["customer_note"] + " | " + r["support_note"]

    p2 = [r for r in t if reason(r) == "changed_mind" and (days(r) or 0) > 14]
    print("P2 changed_mind > 14 days (policy: no exceptions):")
    for r in p2:
        print(f"  {r['request_id']} day {days(r)} -> {r['decision']} by {r['decided_by']}")

    no_photo = re.compile(r"no photo", re.I)
    p3 = [r for r in t if reason(r) == "arrived_damaged" and amt(r) > 50 and r["decision"] == "approved"
          and (no_photo.search(note(r)) or not r["support_note"].strip())]
    print(f"\nP3 damaged > $50 approved with no photo / no support note: {len(p3)}")
    for r in p3:
        print(f"  {r['request_id']} ${amt(r)} {r['decided_by']} | {note(r)} | {r['outcome_note']}")

    sig = re.compile(r"signed|signature|POD|photo of the parcel|locker log", re.I)
    p4 = [r for r in t if reason(r) == "never_arrived" and sig.search(r["support_note"])]
    print(f"\nP4 never_arrived with signature/POD evidence: {len(p4)}")
    for r in p4:
        print(f"  {r['request_id']} ${amt(r)} -> {r['decision']} | {r['support_note']} | {r['outcome_note']}")
    depot = [r for r in t if reason(r) == "never_arrived" and re.search(r"depot|inconclusive|last scan", r["support_note"], re.I)]
    print(f"never_arrived with tracking stuck/inconclusive (no policy covers): {len(depot)} "
          f"decisions={dict(Counter(r['decision'] for r in depot))}")

    fy = [r for r in t if norm_flag(r["fraud_flag"]) == "yes"]
    stolen = [r for r in fy if outcome_kind(r) == "fraud_confirmed"]
    other = [r for r in fy if outcome_kind(r) != "fraud_confirmed"]
    print(f"\nP5 fraud_flag=yes: {len(fy)}; stolen-card confirmed: {len(stolen)} "
          f"decisions={dict(Counter(r['decision'] for r in stolen))}")
    print(f"   flagged but NOT stolen-card: {len(other)} decisions={dict(Counter(r['decision'] for r in other))}")
    for r in other:
        print(f"  {r['request_id']} ${amt(r)} -> {r['decision']} | {r['support_note']} | {r['outcome_note']}")

    print(f"\nP6 decisions by reason: {dict(Counter((reason(r), r['decision']) for r in t if reason(r) in ('wrong_item', 'late_delivery', 'wrong_size')))}")
    for r in t:
        if reason(r) == "wrong_item" and r["decision"] != "approved":
            print(f"  {r['request_id']} -> {r['decision']} | {note(r)} | {r['outcome_note']}")


# ---------- D9: proposed line, and its one-time check on the holdout ----------

def complete(r):
    return (tenure(r) is not None and days(r) is not None and days(r) >= 0
            and norm_flag(r["fraud_flag"]) is not None and bool(r["customer_id"]))


def proposed_line(r):
    """The line (decision D9). True = auto-approve, False = reviewer."""
    if not complete(r) or norm_flag(r["fraud_flag"]) != "no" or r["prior_refunds_12m"] != "0":
        return False
    if tenure(r) < 9:
        return False
    reason = norm_reason(r["stated_reason"])
    if reason in ("wrong_size", "wrong_item"):
        return amt(r) <= 100
    if reason == "changed_mind":
        return days(r) <= 14 and amt(r) <= 100
    if reason == "arrived_damaged":
        return amt(r) <= 50
    return False  # never_arrived, late_delivery


def evaluate_line(rows, label):
    bad = lambda r: outcome_kind(r) in ("chargeback", "appeal_overturned")
    auto = [r for r in rows if proposed_line(r)]
    print(f"{label}: rows={len(rows)} auto={len(auto)} ({100 * len(auto) / len(rows):.0f}%)")
    print(f"  bad outcomes the line would auto-approve: {ids([r for r in auto if bad(r)]) or 'none'}")
    print(f"  auto-approved but humans rejected/partial: "
          f"{[(r['request_id'], r['decision']) for r in auto if r['decision'] != 'approved'] or 'none'}")
    sent = [r for r in rows if not proposed_line(r)]
    print(f"  bad outcomes sent to reviewer (caught): {ids([r for r in sent if bad(r)]) or 'none'}")
    print(f"  today's auto now sent to reviewer: "
          f"{[(r['request_id'], norm_reason(r['stated_reason'])) for r in rows if r['decided_by'] == 'auto' and not proposed_line(r)]}")


def holdout_rows():
    _, held = split_history(load("history.csv"))
    seen, out = set(), []
    for r in held:
        key = tuple(r.values())
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def step5_holdout():
    section("D9 line - train vs one-time holdout check")
    evaluate_line(train_rows(), "train")
    evaluate_line(holdout_rows(), "HOLDOUT")
    pend = load("pending.csv")
    print(f"pending auto under D9: {ids([r for r in pend if proposed_line(r)])}")


if __name__ == "__main__":
    step2()
    step3()
    step4()
    step5_holdout()
