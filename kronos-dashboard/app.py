"""Kronos Live Dashboard - Flask server.

Run:  python app.py   (then open http://localhost:7860)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import forecast as fx

app = Flask(__name__)
svc = fx.KronosService()
HERE = Path(__file__).resolve().parent
WATCHLIST = HERE.parent / "market-radar" / "config" / "watchlist.json"

_cache: dict = {}


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def err(msg, code=400):
    if code == 500 and isinstance(msg, ValueError):
        code = 400  # bad input (unknown ticker, too little history), not a server fault
    return jsonify({"error": str(msg)}), code


@app.get("/")
def index():
    return send_from_directory(HERE / "templates", "index.html")


@app.get("/static/plotly.min.js")
def plotly_js():
    import plotly
    return send_from_directory(Path(plotly.__file__).parent / "package_data", "plotly.min.js")


@app.get("/api/watchlist")
def watchlist():
    groups = {}
    try:
        data = json.loads(WATCHLIST.read_text())
        for region, r in data["regions"].items():
            groups[region] = [{"ticker": t, "name": n} for t, n in r["tickers"].items()]
    except Exception:
        groups = {"india": [{"ticker": "HDFCBANK.NS", "name": "HDFC Bank"}, {"ticker": "RELIANCE.NS", "name": "Reliance"}],
                  "us": [{"ticker": "AAPL", "name": "Apple"}, {"ticker": "NVDA", "name": "NVIDIA"}]}
    groups["crypto"] = [{"ticker": "BTC-USD", "name": "Bitcoin"}, {"ticker": "ETH-USD", "name": "Ethereum"}]
    return jsonify(groups)


@app.get("/api/quote")
def quote():
    t = request.args.get("ticker", "").strip().upper()
    if not t:
        return err("ticker is required")
    try:
        return jsonify(cached(("q", t), 15, lambda: fx.fetch_quote(t)))
    except Exception as e:
        return err(e)


def _hist(t, interval):
    return cached(("h", t, interval), 60, lambda: fx.fetch_history(t, interval))


@app.get("/api/history")
def history():
    t = request.args.get("ticker", "").strip().upper()
    interval = request.args.get("interval", "1h")
    bars = int(request.args.get("bars", 300))
    try:
        h = _hist(t, interval).tail(bars)
        return jsonify({"timestamps": [str(x) for x in h["timestamps"]],
                        **{c: [round(float(v), 4) for v in h[c]] for c in ["open", "high", "low", "close", "volume"]}})
    except Exception as e:
        return err(e)


def _params():
    a = request.args
    return (a.get("ticker", "").strip().upper(), a.get("interval", "1h"),
            max(4, min(int(a.get("horizon", 24)), 120)), max(1, min(int(a.get("paths", 5)), 10)),
            a.get("model", "kronos-small"))


@app.get("/api/forecast")
def forecast():
    t, interval, horizon, paths, model = _params()
    if not t:
        return err("ticker is required")
    try:
        h = _hist(t, interval)
        def run():
            started = time.time()
            fc = svc.forecast(h, interval, horizon, paths, model)
            return {"forecast": fc.__dict__, "summary": fx.summarize(float(h["close"].iloc[-1]), fc),
                    "last_bar": str(h["timestamps"].iloc[-1]), "last_close": float(h["close"].iloc[-1]),
                    "model": model, "seconds": round(time.time() - started, 1),
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
        # Re-forecast at most once per minute per setting; a new bar changes the key.
        key = ("f", t, interval, horizon, paths, model, str(h["timestamps"].iloc[-1]))
        return jsonify(cached(key, 60, run))
    except Exception as e:
        return err(e, 500)


@app.get("/api/backtest")
def backtest():
    t, interval, horizon, paths, model = _params()
    try:
        h = _hist(t, interval)
        key = ("b", t, interval, horizon, paths, model, str(h["timestamps"].iloc[-1]))
        return jsonify(cached(key, 300, lambda: fx.backtest(svc, h, interval, horizon, paths, model)))
    except Exception as e:
        return err(e, 500)


# ---------------------------------------------------------------- Market Radar
# The hourly Market Radar task saves its signals and the holdings file to GitHub.
# Read them from GitHub first (so a PC copy stays current without git pull),
# and fall back to the local checkout.
RADAR = HERE.parent / "market-radar"
RAW = os.environ.get("RADAR_RAW_BASE",
                     "https://raw.githubusercontent.com/sai1845/sai1845/claude/instagram-post-review-l3korb/market-radar")
RULES_DEFAULT = {"sell": {"stop_loss_pct": -8, "take_profit_default_pct": 15}}


def _radar_file(rel: str) -> tuple[str, str]:
    import urllib.request
    try:
        req = urllib.request.Request(f"{RAW}/{rel}?t={int(time.time() // 300)}", headers={"User-Agent": "kronos-dashboard"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read().decode("utf-8"), "GitHub"
    except Exception:
        p = RADAR / rel
        return (p.read_text(encoding="utf-8") if p.exists() else ""), "local copy"


def _radar_data() -> dict:
    def load():
        log_txt, src = _radar_file("signals/log.jsonl")
        signals = []
        for line in log_txt.splitlines():
            try:
                signals.append(json.loads(line))
            except Exception:
                pass
        hold_txt, _ = _radar_file("portfolio/holdings.json")
        rules_txt, _ = _radar_file("config/rules.json")
        try:
            holdings = [h for h in json.loads(hold_txt).get("holdings", [])
                        if h.get("shares", 0) > 0 and not str(h.get("ticker", "")).startswith("EXAMPLE")]
        except Exception:
            holdings = []
        try:
            rules = json.loads(rules_txt)
        except Exception:
            rules = RULES_DEFAULT
        closed = {s.get("closes") for s in signals if s.get("action") == "CLOSE"}
        for s in signals:
            if s.get("action") == "BUY":
                s["status"] = "closed" if s.get("id") in closed else "open"
        return {"signals": list(reversed(signals))[:60], "holdings": holdings, "rules": rules.get("sell", {}),
                "source": src, "loaded_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}
    return cached(("radar",), 120, load)


@app.get("/api/radar")
def radar():
    try:
        return jsonify(_radar_data())
    except Exception as e:
        return err(e, 500)


@app.get("/api/portfolio")
def portfolio():
    """Live P&L and stop-loss / take-profit status for each holding."""
    try:
        r = _radar_data()
        sell = r["rules"] or RULES_DEFAULT["sell"]
        rows = []
        for h in r["holdings"]:
            t = h["ticker"].upper()
            row = {"ticker": t, "name": h.get("name", t), "shares": h["shares"], "buy_price": h["buy_price"]}
            try:
                q = cached(("q", t), 15, lambda: fx.fetch_quote(t))
                price = q["price"]
                stop = h.get("stop_loss_price") or h["buy_price"] * (1 + sell.get("stop_loss_pct", -8) / 100)
                target = h.get("target_price") or h["buy_price"] * (1 + sell.get("take_profit_default_pct", 15) / 100)
                status = "STOP-LOSS HIT" if price <= stop else "TARGET HIT" if price >= target else "HOLD"
                row.update(price=price, currency=q.get("currency"), day_pct=q.get("change_pct"),
                           pnl=round((price - h["buy_price"]) * h["shares"], 2),
                           pnl_pct=round((price / h["buy_price"] - 1) * 100, 2),
                           stop=round(stop, 2), target=round(target, 2), status=status)
            except Exception as e:
                row["error"] = str(e)
            rows.append(row)
        return jsonify({"rows": rows, "source": r["source"]})
    except Exception as e:
        return err(e, 500)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "models_loaded": list(svc._loaded)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"Kronos dashboard on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
