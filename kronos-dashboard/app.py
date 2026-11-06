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


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "models_loaded": list(svc._loaded)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"Kronos dashboard on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
