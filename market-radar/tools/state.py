#!/usr/bin/env python3
"""State helper for Market Radar. Standard library only.

The scheduled analyst uses this to keep a durable record of every signal,
avoid repeating alerts, and check holdings against stop-loss / take-profit.

Commands:
  validate                         Check config, portfolio and signal log.
  recent [--hours N] [--ticker T]  Show signals from the last N hours (default 48).
  add                              Read one signal as JSON on stdin, validate, append.
                                   Exits 3 (and appends nothing) if a cooldown blocks it.
  open                             List BUY signals that are still open.
  close ID --price P --reason R    Close an open BUY signal.
  check-holdings PRICES_JSON       Compare holdings with {"TICKER": price} quotes;
                                   prints stop-loss / take-profit breaches.
  holdings                         Print current holdings.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "config" / "watchlist.json"
RULES = ROOT / "config" / "rules.json"
HOLDINGS = ROOT / "portfolio" / "holdings.json"
LOG = ROOT / "signals" / "log.jsonl"

ACTIONS = {"BUY", "SELL", "HOLD", "WATCH", "CLOSE"}
REQUIRED = {
    "ticker": str,
    "company": str,
    "action": str,
    "impact_score": (int, float),
    "confidence": (int, float),
    "horizon_days": int,
    "catalyst": str,
    "reasoning": str,
    "sources": list,
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def read_log() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for n, line in enumerate(LOG.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"signals/log.jsonl line {n} is not valid JSON: {e}")
    return out


def append_log(entry: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def real_holdings() -> list[dict]:
    rows = load_json(HOLDINGS).get("holdings", [])
    return [h for h in rows if h.get("ticker") and h.get("shares", 0) > 0
            and not h["ticker"].startswith("EXAMPLE")]


def validate_signal(sig: dict, rules: dict) -> list[str]:
    errs = []
    for key, typ in REQUIRED.items():
        if key not in sig:
            errs.append(f"missing field '{key}'")
        elif not isinstance(sig[key], typ) or isinstance(sig[key], bool):
            errs.append(f"field '{key}' has wrong type")
    if errs:
        return errs
    sig["action"] = sig["action"].upper()
    sig["ticker"] = sig["ticker"].upper()
    if sig["action"] not in ACTIONS:
        errs.append(f"action must be one of {sorted(ACTIONS)}")
    if not -5 <= sig["impact_score"] <= 5:
        errs.append("impact_score must be between -5 and 5")
    if not 0 <= sig["confidence"] <= 100:
        errs.append("confidence must be between 0 and 100")
    if sig["horizon_days"] < 1:
        errs.append("horizon_days must be >= 1")
    if not sig["sources"] or not all(isinstance(s, str) and s.startswith("http") for s in sig["sources"]):
        errs.append("sources must be a non-empty list of URLs")
    b, s = rules["buy"], rules["sell"]
    if sig["action"] == "BUY":
        if sig["impact_score"] < b["min_impact_score"]:
            errs.append(f"BUY needs impact_score >= {b['min_impact_score']}")
        if sig["confidence"] < b["min_confidence"]:
            errs.append(f"BUY needs confidence >= {b['min_confidence']}")
        if len(set(sig["sources"])) < b["min_independent_sources"]:
            errs.append(f"BUY needs >= {b['min_independent_sources']} distinct sources")
    if sig["action"] == "SELL" and not sig.get("rule_triggered"):
        if sig["impact_score"] > s["max_impact_score"]:
            errs.append(f"news-based SELL needs impact_score <= {s['max_impact_score']}")
        if sig["confidence"] < s["min_confidence"]:
            errs.append(f"SELL needs confidence >= {s['min_confidence']}")
    return errs


def cmd_validate(_args) -> int:
    problems = []
    wl = load_json(WATCHLIST)
    tickers = [t for r in wl["regions"].values() for t in r["tickers"]]
    if len(tickers) != len(set(tickers)):
        problems.append("watchlist has duplicate tickers")
    rules = load_json(RULES)
    for k in ("buy", "sell", "cooldown_hours_same_ticker_same_action"):
        if k not in rules:
            problems.append(f"rules.json missing '{k}'")
    for h in real_holdings():
        for k in ("ticker", "shares", "buy_price"):
            if k not in h:
                problems.append(f"holding {h} missing '{k}'")
    log = read_log()
    if problems:
        print("\n".join("PROBLEM: " + p for p in problems))
        return 1
    print(f"OK: {len(tickers)} watchlist tickers, {len(real_holdings())} holdings, {len(log)} logged signals")
    return 0


def cmd_recent(args) -> int:
    cutoff = now() - timedelta(hours=args.hours)
    rows = [s for s in read_log() if parse_ts(s["ts"]) >= cutoff]
    if args.ticker:
        rows = [s for s in rows if s["ticker"] == args.ticker.upper()]
    for s in rows:
        print(f"{s['ts']}  {s['id']}  {s['action']:<5} {s['ticker']:<14} score={s.get('impact_score')} "
              f"conf={s.get('confidence')}  {s.get('catalyst', '')[:80]}")
    if not rows:
        print("(no signals in window)")
    return 0


def cmd_add(_args) -> int:
    rules = load_json(RULES)
    try:
        sig = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"REJECTED: stdin is not valid JSON: {e}")
        return 2
    errs = validate_signal(sig, rules)
    if errs:
        print("REJECTED: " + "; ".join(errs))
        return 2
    cooldown = timedelta(hours=rules["cooldown_hours_same_ticker_same_action"])
    for prev in read_log():
        if (prev["ticker"] == sig["ticker"] and prev["action"] == sig["action"]
                and now() - parse_ts(prev["ts"]) < cooldown):
            print(f"COOLDOWN: {sig['action']} {sig['ticker']} already signalled at {prev['ts']} ({prev['id']})")
            return 3
    sig["id"] = sig.get("id") or uuid.uuid4().hex[:8]
    sig["ts"] = now().isoformat(timespec="seconds")
    sig.setdefault("status", "open" if sig["action"] == "BUY" else "info")
    append_log(sig)
    print(f"ADDED {sig['id']} {sig['action']} {sig['ticker']}")
    return 0


def open_buys() -> list[dict]:
    log = read_log()
    closed = {s["closes"] for s in log if s.get("action") == "CLOSE" and s.get("closes")}
    return [s for s in log if s["action"] == "BUY" and s["id"] not in closed]


def cmd_open(_args) -> int:
    rows = open_buys()
    for s in rows:
        exp = parse_ts(s["ts"]) + timedelta(days=s["horizon_days"])
        flag = "  EXPIRED" if exp < now() else ""
        print(f"{s['id']}  {s['ticker']:<14} since {s['ts'][:10]}  entry={s.get('price_at_signal')} "
              f"target={s.get('target_price')}  horizon_ends={exp.date()}{flag}")
    if not rows:
        print("(no open BUY signals)")
    return 0


def cmd_close(args) -> int:
    match = [s for s in open_buys() if s["id"] == args.id]
    if not match:
        print(f"no open BUY signal with id {args.id}")
        return 1
    buy = match[0]
    entry = buy.get("price_at_signal")
    ret = round((args.price / entry - 1) * 100, 2) if entry else None
    append_log({
        "id": uuid.uuid4().hex[:8], "ts": now().isoformat(timespec="seconds"),
        "action": "CLOSE", "closes": buy["id"], "ticker": buy["ticker"],
        "company": buy["company"], "exit_price": args.price, "return_pct": ret,
        "reason": args.reason,
    })
    print(f"CLOSED {buy['id']} {buy['ticker']} return={ret}%")
    return 0


def cmd_check_holdings(args) -> int:
    rules = load_json(RULES)["sell"]
    prices = json.loads(Path(args.prices).read_text()) if Path(args.prices).exists() else json.loads(args.prices)
    hits = 0
    for h in real_holdings():
        p = prices.get(h["ticker"])
        if p is None:
            print(f"NO-PRICE  {h['ticker']}")
            continue
        chg = (p / h["buy_price"] - 1) * 100
        stop = h.get("stop_loss_price") or h["buy_price"] * (1 + rules["stop_loss_pct"] / 100)
        target = h.get("target_price") or h["buy_price"] * (1 + rules["take_profit_default_pct"] / 100)
        status = "OK"
        if p <= stop:
            status, hits = "STOP-LOSS", hits + 1
        elif p >= target:
            status, hits = "TAKE-PROFIT", hits + 1
        print(f"{status:<11} {h['ticker']:<14} price={p} buy={h['buy_price']} change={chg:+.2f}% "
              f"stop={stop:.2f} target={target:.2f}")
    return 4 if hits else 0


def cmd_holdings(_args) -> int:
    rows = real_holdings()
    for h in rows:
        print(f"{h['ticker']:<14} {h['shares']} @ {h['buy_price']}  since {h.get('buy_date')}  {h.get('notes', '')}")
    if not rows:
        print("(no holdings yet - edit portfolio/holdings.json)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate").set_defaults(fn=cmd_validate)
    r = sub.add_parser("recent")
    r.add_argument("--hours", type=float, default=48)
    r.add_argument("--ticker")
    r.set_defaults(fn=cmd_recent)
    sub.add_parser("add").set_defaults(fn=cmd_add)
    sub.add_parser("open").set_defaults(fn=cmd_open)
    c = sub.add_parser("close")
    c.add_argument("id")
    c.add_argument("--price", type=float, required=True)
    c.add_argument("--reason", required=True)
    c.set_defaults(fn=cmd_close)
    ch = sub.add_parser("check-holdings")
    ch.add_argument("prices", help='JSON file path or inline JSON like {"TCS.NS": 4100}')
    ch.set_defaults(fn=cmd_check_holdings)
    sub.add_parser("holdings").set_defaults(fn=cmd_holdings)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
