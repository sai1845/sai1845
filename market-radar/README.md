# Market Radar

An autonomous, news-driven stock research assistant for India (NSE/BSE), the US
(NYSE/NASDAQ) and major European & Asian exchanges.

Every hour on market days a scheduled Claude session:

1. Reads your holdings and checks their latest price and news → **SELL** alerts on
   stop-loss, take-profit, or serious negative news.
2. Searches the web for fresh business news (big contracts, approvals, M&A,
   guidance raises, policy changes) → **BUY** alerts when a catalyst is material,
   confirmed by trusted sources and not already priced in.
3. Records every signal in `signals/log.jsonl` (so it never repeats itself) and
   emails you only when there is something new to act on.
4. After the US close, sends a daily digest and saves it to `reports/`.

> ⚠️ This is automated research, not financial advice. News-based signals are often
> wrong, and nobody can reliably predict short-term prices. Check every alert yourself,
> size positions carefully, and never invest money you can't afford to lose.

## Files

| Path | What it is | You edit it? |
|---|---|---|
| `portfolio/holdings.json` | Stocks you own (ticker, shares, buy price, optional target/stop) | **Yes** — keep it current |
| `config/watchlist.json` | Companies always monitored, per region | Optional |
| `config/rules.json` | Thresholds: min score/confidence for BUY, stop-loss %, cooldown | Optional |
| `ANALYST.md` | Step-by-step playbook the scheduled Claude run follows | Optional |
| `tools/state.py` | Signal log, cooldown/dedupe, stop-loss checks (stdlib Python) | No |
| `signals/log.jsonl` | Every signal ever issued, with sources | No (auto) |
| `reports/` | Daily digests | No (auto) |

## Adding your stocks

Edit `portfolio/holdings.json` (on GitHub you can do this from your phone) and replace
the example row, e.g.:

```json
{ "ticker": "TCS.NS", "name": "Tata Consultancy Services", "shares": 10,
  "buy_price": 4050, "buy_date": "2026-10-20", "target_price": null,
  "stop_loss_price": null, "notes": "" }
```

Tickers use Yahoo Finance format: `.NS` NSE, `.BO` BSE, plain for US, `.L` London,
`.DE` Xetra, `.PA` Paris, `.AS` Amsterdam, `.T` Tokyo, `.HK` Hong Kong.

## Signal scoring (short version)

- **impact_score** −5…+5: how much the news changes the company's earnings outlook.
- **confidence** 0–100: source quality, independent confirmation, certainty of the event.
- **BUY** needs score ≥ 3, confidence ≥ 60, two sources, and no big move already.
- **SELL** on stop-loss (default −8%), take-profit (default +15% or your target),
  or news with score ≤ −3.

## Manual commands

```bash
cd market-radar
python3 tools/state.py validate          # check files
python3 tools/state.py holdings          # your stocks
python3 tools/state.py open              # open BUY ideas
python3 tools/state.py recent --hours 72 # recent signals
```
