#!/usr/bin/env python3
"""Trade-plan helper for Market Radar. Standard library only.

  quote TICKER [TICKER ...]   Latest price, previous close and day range from Yahoo Finance.
  save                        Read one plan as JSON on stdin, validate it, and write
                              plans/<date>.json, plans/latest.json and plans/index.json.
  show [DATE]                 Print a saved plan (default: latest).

A plan is a list of intraday picks for one trading day: when to enter, at what
price zone, the target, the stop, and the time to exit if neither is hit.
The website scores every saved plan against real 5-minute prices.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANS = ROOT / "plans"
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def yahoo(ticker: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        res = json.load(r)["chart"]["result"][0]
    m = res["meta"]
    return {"ticker": ticker, "price": m.get("regularMarketPrice"), "prev_close": m.get("chartPreviousClose"),
            "day_high": m.get("regularMarketDayHigh"), "day_low": m.get("regularMarketDayLow"),
            "currency": m.get("currency"), "exchange": m.get("exchangeName"),
            "as_of": datetime.fromtimestamp(m.get("regularMarketTime", 0), timezone.utc).isoformat()}


def cmd_quote(tickers: list[str]) -> int:
    for t in tickers:
        try:
            print(json.dumps(yahoo(t)))
        except Exception as e:
            print(json.dumps({"ticker": t, "error": str(e)}))
    return 0


def validate(plan: dict) -> list[str]:
    errs = []
    try:
        datetime.strptime(plan.get("date", ""), "%Y-%m-%d")
    except ValueError:
        errs.append("date must be YYYY-MM-DD (the trading day the plan is for)")
    for k in ("market", "timezone", "picks"):
        if k not in plan:
            errs.append(f"missing '{k}'")
    ctx = plan.get("market_context", {})
    if not ctx.get("summary") or not ctx.get("sources"):
        errs.append("market_context needs a summary and at least one source URL")
    if not isinstance(plan.get("picks"), list):
        return errs + ["picks must be a list"]
    if len(plan["picks"]) > 6:
        errs.append("at most 6 picks")
    for i, p in enumerate(plan["picks"]):
        tag = f"pick {i + 1} ({p.get('ticker', '?')})"
        for k in ("ticker", "company", "direction", "catalyst", "reasoning", "confidence",
                  "entry_window", "target", "stop", "exit_by", "sources"):
            if k not in p:
                errs.append(f"{tag}: missing '{k}'")
        if errs:
            continue
        if p["direction"] not in ("LONG", "SHORT"):
            errs.append(f"{tag}: direction must be LONG or SHORT")
        w = p["entry_window"]
        if not (isinstance(w, list) and len(w) == 2 and all(HHMM.match(x) for x in w) and w[0] < w[1]):
            errs.append(f"{tag}: entry_window must be [\"HH:MM\", \"HH:MM\"] in exchange time")
        if not HHMM.match(p["exit_by"]) or (HHMM.match(w[1]) and p["exit_by"] <= w[1]):
            errs.append(f"{tag}: exit_by must be HH:MM after the entry window")
        z = p.get("entry_zone")
        if z is not None and not (isinstance(z, list) and len(z) == 2 and z[0] <= z[1]):
            errs.append(f"{tag}: entry_zone must be [low, high] or null")
        ref = (z[0] + z[1]) / 2 if z else p.get("ref_price")
        if ref:
            long_ = p["direction"] == "LONG"
            if long_ and not (p["stop"] < ref < p["target"]):
                errs.append(f"{tag}: LONG needs stop < entry < target")
            if not long_ and not (p["target"] < ref < p["stop"]):
                errs.append(f"{tag}: SHORT needs target < entry < stop")
        if not (0 <= p["confidence"] <= 100):
            errs.append(f"{tag}: confidence 0-100")
        srcs = p["sources"]
        if not (isinstance(srcs, list) and len(set(srcs)) >= 2 and all(str(s).startswith("http") for s in srcs)):
            errs.append(f"{tag}: needs at least 2 distinct source URLs")
    return errs


def cmd_save() -> int:
    try:
        plan = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"REJECTED: not valid JSON: {e}")
        return 2
    errs = validate(plan)
    if errs:
        print("REJECTED:\n  " + "\n  ".join(errs))
        return 2
    plan.setdefault("generated_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    PLANS.mkdir(parents=True, exist_ok=True)
    body = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    (PLANS / f"{plan['date']}.json").write_text(body, encoding="utf-8")
    (PLANS / "latest.json").write_text(body, encoding="utf-8")
    idx_path = PLANS / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"dates": []}
    idx["dates"] = sorted(set(idx["dates"]) | {plan["date"]}, reverse=True)
    idx["updated_at"] = plan["generated_at"]
    idx_path.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
    print(f"SAVED plan for {plan['date']} with {len(plan['picks'])} picks")
    return 0


def cmd_show(date: str | None) -> int:
    p = PLANS / (f"{date}.json" if date else "latest.json")
    print(p.read_text() if p.exists() else "(no plan saved)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        sys.exit(1)
    if a[0] == "quote":
        sys.exit(cmd_quote(a[1:]))
    if a[0] == "save":
        sys.exit(cmd_save())
    if a[0] == "show":
        sys.exit(cmd_show(a[1] if len(a) > 1 else None))
    print(__doc__)
    sys.exit(1)
