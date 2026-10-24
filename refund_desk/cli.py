"""Command line.

  refund-desk route [FILE]   route a CSV with the pending.csv columns (default: data/pending.csv)
  refund-desk evaluate       measure the live policy on history (train and holdout)
  refund-desk extract        read every note in history and pending with the LLM, fill the cache
  refund-desk serve [FILE]   the web app on http://localhost:8000

Notes are read from cache/facts.json. With GEMINI_API_KEY set (in the shell or in .env),
notes missing from the cache are read live and added to it.
"""
import argparse
import os
from pathlib import Path

from .evaluate import evaluate_history
from .facts import FactReader, gemini_client
from .load import load
from .rules import latest_policy, route_batch

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache" / "facts.json"
ROUTE_LABEL = {"auto_approve": "AUTO", "reviewer": "REVIEW", "fraud_team": "FRAUD"}


def load_dotenv(path=ROOT / ".env"):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def cmd_route(args, policy, reader):
    requests = reader.read_all(load(args.file))
    decisions = route_batch(requests, policy)
    print(f"policy v{policy['version']} · {args.file} · {len(requests)} requests\n")
    for r, d in zip(requests, decisions):
        amount = f"${r['amount_usd']:.2f}" if r["amount_usd"] is not None else "?"
        quote = next((e["quote"] for e in d["evidence"] if e.get("quote")), "")
        print(f"{ROUTE_LABEL[d['route']]:6} {r['request_id']}  {amount:>10}  {r['stated_reason'] or '?':15} "
              f"{d['rule_name']}" + (f'  "{quote}"' if quote else ""))
    counts = {k: sum(d["route"] == k for d in decisions) for k in ROUTE_LABEL}
    unread = sum(r["facts_status"] == "unread" for r in requests)
    print(f"\nauto {counts['auto_approve']} · reviewer {counts['reviewer']} · fraud team {counts['fraud_team']}"
          + (f" · {unread} with notes not read (no API key, not in cache)" if unread else ""))


def cmd_evaluate(args, policy, reader):
    print(f"policy v{policy['version']} on {args.history}\n")
    for name, m in evaluate_history(args.history, policy, reader).items():
        print(f"{name}: {m['auto']}/{m['rows']} auto ({m['auto_share']:.0%}), "
              f"{m['reviewer_minutes_saved']} reviewer minutes saved")
        print(f"  auto-approved but ended badly: {', '.join(m['auto_bad']) or 'none'}")
        print(f"  auto-approved but a person had decided otherwise: {', '.join(m['auto_humans_disagreed']) or 'none'}")
        print(f"  bad outcomes sent to a person: {', '.join(m['bad_caught']) or 'none'}")


def cmd_extract(args, policy, reader):
    if reader.ask is None:
        raise SystemExit("extract needs GEMINI_API_KEY (in the shell or in .env)")
    requests = load(ROOT / "data" / "history.csv") + load(ROOT / "data" / "pending.csv")
    before = len(reader.cache)
    reader.read_all(requests)
    dropped = [(e["request_id"], e["dropped"]) for e in reader.cache.values() if e["dropped"]]
    print(f"{len(reader.cache) - before} notes read, {len(reader.cache)} in cache")
    print(f"answers dropped because the quote was not in the notes: {dropped or 'none'}")


def cmd_serve(args, policy, reader):
    import uvicorn

    from .api import create_app
    app = create_app(requests_path=args.file, ask=reader.ask)
    print(f"Refund Desk on http://localhost:{args.port} (policy v{policy['version']}, {args.file.name})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(prog="refund-desk")
    parser.add_argument("--policy", type=Path, help="policy JSON (default: latest in policy/)")
    parser.add_argument("--offline", action="store_true", help="use the cache only, never call the LLM")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("route", help="route requests in a CSV")
    p.add_argument("file", nargs="?", type=Path, default=ROOT / "data" / "pending.csv")
    p.set_defaults(run=cmd_route)
    e = sub.add_parser("evaluate", help="measure the policy on decided history")
    e.add_argument("--history", type=Path, default=ROOT / "data" / "history.csv")
    e.set_defaults(run=cmd_evaluate)
    x = sub.add_parser("extract", help="read all notes with the LLM and fill the cache")
    x.set_defaults(run=cmd_extract)
    s = sub.add_parser("serve", help="start the web app")
    s.add_argument("file", nargs="?", type=Path, default=ROOT / "data" / "pending.csv")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(run=cmd_serve)
    args = parser.parse_args(argv)
    reader = FactReader(CACHE, None if args.offline else gemini_client())
    args.run(args, latest_policy(ROOT / "policy", args.policy), reader)


if __name__ == "__main__":
    main()
