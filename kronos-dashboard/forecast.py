"""Data fetching and Kronos forecasting for the dashboard.

- Prices come from Yahoo Finance (yfinance), so any Yahoo ticker works:
  RELIANCE.NS / HDFCBANK.NS (NSE), 500180.BO (BSE), AAPL (US), 7203.T (Tokyo), BTC-USD ...
- Forecasts come from the Kronos foundation model (https://github.com/shiyu-coder/Kronos).
  Several forecast paths are sampled in one batch so the dashboard can show
  an uncertainty band, not just a single line.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
KRONOS_DIR = os.environ.get("KRONOS_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "Kronos"))
sys.path.insert(0, os.path.abspath(KRONOS_DIR))

# interval -> (yfinance period to download, pandas step for daily fallback)
INTERVALS = {
    "5m": "30d",
    "15m": "60d",
    "1h": "180d",
    "1d": "4y",
}
MODELS = {
    "kronos-mini": ("NeoQuasar/Kronos-mini", "NeoQuasar/Kronos-Tokenizer-2k", 2048),
    "kronos-small": ("NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base", 512),
    "kronos-base": ("NeoQuasar/Kronos-base", "NeoQuasar/Kronos-Tokenizer-base", 512),
}


# ---------------------------------------------------------------- data
def fetch_history(ticker: str, interval: str) -> pd.DataFrame:
    """OHLCV history with naive exchange-local timestamps in column 'timestamps'."""
    if interval not in INTERVALS:
        raise ValueError(f"interval must be one of {list(INTERVALS)}")
    raw = yf.Ticker(ticker).history(period=INTERVALS[interval], interval=interval, auto_adjust=False)
    if raw is None or raw.empty:
        raise ValueError(f"No price data for '{ticker}'. Check the symbol (e.g. RELIANCE.NS, AAPL).")
    df = raw.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    tcol = "datetime" if "datetime" in df.columns else "date"
    ts = pd.to_datetime(df[tcol])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    out = pd.DataFrame({
        "timestamps": ts,
        "open": df["open"].astype(float), "high": df["high"].astype(float),
        "low": df["low"].astype(float), "close": df["close"].astype(float),
        "volume": df["volume"].astype(float),
    })
    out = out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    out["amount"] = out["close"] * out["volume"]
    return out


def fetch_quote(ticker: str) -> dict:
    """Latest price, day change and currency. Uses 1-minute bars for freshness."""
    t = yf.Ticker(ticker)
    bars = t.history(period="5d", interval="1m")
    if bars is None or bars.empty:
        bars = t.history(period="5d", interval="1d")
    if bars is None or bars.empty:
        raise ValueError(f"No quote for '{ticker}'.")
    last = bars.iloc[-1]
    last_ts = bars.index[-1]
    day = bars[bars.index.date == last_ts.date()]
    prev_close = None
    try:
        info = t.fast_info
        prev_close = float(info.get("previousClose") or info.get("regularMarketPreviousClose") or 0) or None
        currency = info.get("currency")
    except Exception:
        currency = None
    if prev_close is None:
        daily = t.history(period="10d", interval="1d")
        if len(daily) >= 2:
            prev_close = float(daily["Close"].iloc[-2])
    price = float(last["Close"])
    chg = (price / prev_close - 1) * 100 if prev_close else None
    return {
        "ticker": ticker, "price": round(price, 4), "prev_close": prev_close,
        "change_pct": round(chg, 2) if chg is not None else None,
        "day_high": float(day["High"].max()), "day_low": float(day["Low"].min()),
        "currency": currency, "as_of": str(last_ts), "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }


def future_timestamps(hist: pd.Series, n: int, interval: str) -> pd.Series:
    """Next n bar times that fall inside the instrument's normal trading sessions.

    Session times are learned from the last 20 trading days, so it works for any
    exchange (and for 24/7 crypto). Exchange holidays are not known and are
    treated as trading days.
    """
    last = hist.iloc[-1]
    if interval == "1d":
        weekdays = set(hist.tail(60).dt.weekday)
        out, d = [], last
        while len(out) < n:
            d += pd.Timedelta(days=1)
            if d.weekday() in weekdays:
                out.append(d)
        return pd.Series(out)
    recent = hist[hist >= hist.iloc[-1] - pd.Timedelta(days=30)]
    slots = sorted(set(recent.dt.time))
    weekdays = set(recent.dt.weekday)
    out, day = [], last.normalize()
    later = [s for s in slots if s > last.time()]
    while len(out) < n:
        for s in later:
            out.append(pd.Timestamp.combine(day.date(), s))
            if len(out) == n:
                break
        day += pd.Timedelta(days=1)
        while day.weekday() not in weekdays:
            day += pd.Timedelta(days=1)
        later = slots
    return pd.Series(out)


# ---------------------------------------------------------------- model
@dataclass
class Forecast:
    timestamps: list
    mean: dict          # column -> list
    p10: list
    p90: list
    paths: list         # list of close-price lists, one per sampled path


class KronosService:
    def __init__(self):
        self._lock = threading.Lock()
        self._loaded: dict = {}

    def predictor(self, name: str):
        if name not in MODELS:
            raise ValueError(f"model must be one of {list(MODELS)}")
        with self._lock:
            if name not in self._loaded:
                from model import Kronos, KronosTokenizer, KronosPredictor
                mid, tid, ctx = MODELS[name]
                tok = KronosTokenizer.from_pretrained(tid)
                mdl = Kronos.from_pretrained(mid)
                self._loaded[name] = KronosPredictor(mdl, tok, device="cpu", max_context=ctx)
            return self._loaded[name]

    def forecast(self, hist: pd.DataFrame, interval: str, pred_len: int, paths: int,
                 model: str = "kronos-small", lookback: int = 400, T: float = 1.0, top_p: float = 0.9) -> Forecast:
        pred = self.predictor(model)
        lookback = min(lookback, len(hist), pred.max_context)
        if lookback < 50:
            raise ValueError("Need at least 50 bars of history to forecast.")
        x = hist[["open", "high", "low", "close", "volume", "amount"]].tail(lookback).reset_index(drop=True)
        xt = hist["timestamps"].tail(lookback).reset_index(drop=True)
        yt = future_timestamps(hist["timestamps"], pred_len, interval)
        with self._lock:
            dfs = pred.predict_batch(
                df_list=[x] * paths, x_timestamp_list=[xt] * paths, y_timestamp_list=[yt] * paths,
                pred_len=pred_len, T=T, top_p=top_p, sample_count=1, verbose=False,
            )
        closes = np.stack([d["close"].to_numpy() for d in dfs])
        mean_df = sum(d[["open", "high", "low", "close", "volume"]] for d in dfs) / len(dfs)
        return Forecast(
            timestamps=[str(t) for t in yt],
            mean={c: [round(float(v), 4) for v in mean_df[c]] for c in mean_df.columns},
            p10=[round(float(v), 4) for v in np.percentile(closes, 10, axis=0)],
            p90=[round(float(v), 4) for v in np.percentile(closes, 90, axis=0)],
            paths=[[round(float(v), 4) for v in row] for row in closes],
        )


def summarize(last_close: float, fc: Forecast) -> dict:
    """Plain-language read of the forecast. Not a recommendation."""
    end = fc.mean["close"][-1]
    move = (end / last_close - 1) * 100
    paths_up = sum(1 for p in fc.paths if p[-1] > last_close)
    agree = paths_up / len(fc.paths)
    lean = "UP" if move > 0.3 else "DOWN" if move < -0.3 else "FLAT"
    if lean == "FLAT":
        strength = "no clear direction"
    else:
        share = agree if lean == "UP" else 1 - agree
        strength = "most paths agree" if share >= 0.75 else "paths are split"
    hi = max(fc.mean["high"]); lo = min(fc.mean["low"])
    return {
        "lean": lean, "move_pct": round(move, 2), "end_price": round(end, 4),
        "paths_up": paths_up, "paths_total": len(fc.paths), "strength": strength,
        "range_high": round(hi, 4), "range_low": round(lo, 4),
        "band_end": [fc.p10[-1], fc.p90[-1]],
    }


def backtest(svc: KronosService, hist: pd.DataFrame, interval: str, pred_len: int, paths: int, model: str) -> dict:
    """Hide the last pred_len bars, forecast them, and score against what happened."""
    if len(hist) < pred_len + 60:
        raise ValueError("Not enough history for a backtest at this horizon.")
    past, actual = hist.iloc[:-pred_len].reset_index(drop=True), hist.iloc[-pred_len:].reset_index(drop=True)
    fc = svc.forecast(past, interval, pred_len, paths, model)
    fc.timestamps = [str(t) for t in actual["timestamps"]]  # align to real bar times
    pred = np.array(fc.mean["close"]); real = actual["close"].to_numpy()
    base = past["close"].iloc[-1]
    mape = float(np.mean(np.abs(pred - real) / real) * 100)
    dir_ok = bool(np.sign(pred[-1] - base) == np.sign(real[-1] - base))
    inside = float(np.mean((real >= np.array(fc.p10)) & (real <= np.array(fc.p90))) * 100)
    return {
        "forecast": fc.__dict__, "actual": [round(float(v), 4) for v in real],
        "mape_pct": round(mape, 2), "direction_correct": dir_ok, "inside_band_pct": round(inside, 1),
        "start_close": round(float(base), 4),
    }
