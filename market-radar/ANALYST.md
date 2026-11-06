# Market Radar — Analyst Playbook

This file is the job description for the scheduled Claude run. Every run follows it
step by step. Times are UTC. All paths are relative to `market-radar/`.

## 0. Ground rules

- **Real news only.** Every signal must cite at least one real, dated article or filing
  found in this run via web search. Never invent news, prices, numbers or URLs. If a
  price can't be confirmed, say "price unconfirmed" and do not compute targets from it.
- **No hype.** Prefer "likely", "could" and a confidence %, never "guaranteed".
  Rumours, anonymous social posts and paid tip channels are not evidence.
- **Be quiet unless it matters.** An email goes out only when there is a new actionable
  signal (BUY / SELL), or for the daily digest (step 7). Most runs should send nothing.
- Respect `config/rules.json`. `tools/state.py add` rejects signals that break it — do
  not work around a rejection by inflating scores.

## 1. Set up (every run)

```bash
cd market-radar
python3 tools/state.py validate
python3 tools/state.py holdings
python3 tools/state.py open
python3 tools/state.py recent --hours 48
```

Work out which markets are open now (see `hours_utc` in `config/watchlist.json`;
Mon–Fri only, skip known exchange holidays). Focus the run on open markets plus
markets opening within the next 2 hours. Holdings are checked every run regardless.

## 2. Check holdings first (SELL side)

For each holding from `holdings`:

1. Search for the latest price (e.g. "<company> share price today") and the last
   48 hours of company news ("<company> news", "<company> stock falls/rises why").
2. Put the confirmed prices in a JSON map and run
   `python3 tools/state.py check-holdings '{"TICKER": price, ...}'`.
   Exit code 4 means a stop-loss or take-profit was hit → SELL signal with
   `"rule_triggered": "stop_loss"` or `"take_profit"`.
3. News-driven SELL: material negative catalyst (see step 4 scoring) with
   impact_score ≤ −3 → SELL. Also SELL-review if the original BUY thesis is broken
   (deal cancelled, approval denied, guidance cut).
4. Positive news on a holding → HOLD (log it, no email unless it changes the target).

## 3. Hunt for opportunities (BUY side)

Search news from the last 36 hours, for open markets. Use several queries, e.g.:

- "<region> stocks biggest movers today", "stock market news today India / US / Europe / Japan"
- "company wins major contract", "order win", "FDA approval", "regulatory approval stock"
- "acquisition announced", "merger agreement", "raises guidance", "record quarterly results beat estimates"
- "government policy boost sector stocks", "PLI scheme", "defence order", "AI chip deal"
- Each watchlist ticker that had no check in the last 12 hours (rotate; ~8 per run).

Companies outside the watchlist are allowed if they are listed, liquid
(large/mid cap) and the news is from a trusted source.

## 4. Score each catalyst

| Factor | How to judge |
|---|---|
| **impact_score** −5…+5 | Size of the effect on revenue/earnings relative to company size. +5 = transformational (huge contract vs. market cap, blockbuster approval, takeover bid at premium). +3 = clearly material. +1 = minor. Negative mirrors this (fraud, guidance cut, lost licence, major lawsuit, CEO exit amid issues). |
| **confidence** 0–100 | Source quality (filing / Reuters / Bloomberg / ET > blog), confirmation by ≥2 independent outlets, how certain the event is (signed deal > talks > rumour). |
| **already priced in?** | If the stock already moved more than `skip_if_already_moved_pct` since the news, lower the score or mark WATCH instead of BUY. |
| **horizon_days** | Realistic time for the effect to show: earnings/contract news 5–20 days; approvals/policy 10–60 days; structural shifts 30–180 days. |
| **target / stop** | Only if price confirmed. Target = price × (1 + expected move). Stop = price × (1 + stop_loss_pct). Expected move must be justified in `reasoning`. |

Decision: BUY only if impact_score ≥ 3, confidence ≥ 60, ≥2 distinct source URLs,
not already priced in. Otherwise WATCH (logged, not emailed) or drop.

## 5. Record signals

For each BUY / SELL / WATCH / HOLD, pipe one JSON object to `state.py add`:

```bash
python3 tools/state.py add <<'JSON'
{
  "ticker": "LT.NS", "company": "Larsen & Toubro", "region": "india",
  "action": "BUY", "impact_score": 4, "confidence": 70, "horizon_days": 20,
  "price_at_signal": 3650.0, "currency": "INR", "target_price": 3950.0, "stop_price": 3358.0,
  "catalyst": "One-line description of the news",
  "reasoning": "2-4 sentences: why it matters, size vs company, risks, why not priced in",
  "risks": "Main things that would make this wrong",
  "sources": ["https://...", "https://..."]
}
JSON
```

- Exit 0 = added. Exit 2 = rejected (fix or drop). Exit 3 = cooldown → do **not** email again.
- When a SELL fires for a stock that has an open BUY signal, also close it:
  `python3 tools/state.py close <id> --price <p> --reason "..."`.
- Open BUY signals past their horizon: check price, close them with the outcome.

## 6. Email the alert

Only for BUY or SELL signals that were **added** (exit 0) this run. Send ONE email via
the Gmail connector to the repository owner's address (the address the scheduled task
names). Subject:

`Market Radar: BUY LT.NS (+4, 70%) | SELL TSLA (stop-loss)`

Body (plain text, short):

```
BUY  Larsen & Toubro (LT.NS) — impact +4, confidence 70%
Price ~3,650 INR | Target 3,950 (+8%) in ~20 days | Stop 3,358 (-8%)
Why: ...
Risks: ...
Sources: <url1>  <url2>

SELL ...

— Market Radar (automated research, not financial advice. Verify before trading.)
```

## 7. Daily digest

On the first run at or after 20:00 UTC each weekday, send one digest email even if
nothing fired: holdings status (price, % change, any news), open BUY signals with
progress vs target, WATCH list, and a 3-line market mood per region. Write the same
content to `reports/YYYY-MM-DD.md`.

## 8. Save state

```bash
cd market-radar
git add signals reports
git commit -m "Market Radar run $(date -u +%Y-%m-%dT%H:%MZ)" || true
git push -u origin claude/instagram-post-review-l3korb
```

If nothing changed, skip the commit. Finish with a 3-line summary of what the run did.
