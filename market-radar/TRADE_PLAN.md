# Market Radar — Daily Trade Plan Playbook (NSE intraday)

Two runs per trading day write the plan that the Trade Desk website shows and scores:

| Run | When (IST) | Job |
|---|---|---|
| **Evening** | ~20:30 the day before | Draft tomorrow's plan from today's close, after-hours company news and the US open. `"stage": "evening draft"` |
| **Morning** | ~08:40, before the 09:15 open | Refresh with overnight US close, Asian markets, GIFT Nifty, crude, rupee and any new announcements. Replace the draft. `"stage": "morning final"` |

Paths are relative to `market-radar/`. Tools: `python3 tools/plan.py quote TICKER ...` for real prices
(Yahoo Finance), `python3 tools/plan.py save` to validate and save.

## Rules

1. **Real news only.** Every pick cites at least 2 distinct, dated articles or filings found in this run
   (NSE/BSE announcements, Economic Times, Mint, Business Standard, Moneycontrol, BusinessLine, Reuters,
   Bloomberg, CNBC-TV18). Never invent news, numbers or URLs. No social-media tips.
2. **Real prices only.** Get the last close with `plan.py quote`. Entry zone, target and stop are set
   from that price. If the quote fails, leave the stock out.
3. **At most 6 picks, and zero is allowed.** Only include a stock when there is a fresh (≤ 24 h), material,
   stock-specific catalyst that is likely to move it on the next session and is not already fully priced in.
   A quiet news day = empty `picks` list. Do not pad the list.
4. **Liquid stocks only:** Nifty 100 / F&O names. No small caps, no penny stocks.
5. **Direction:** `LONG` (buy, then sell) by default. `SHORT` only for F&O stocks with clearly negative news.
6. **Levels (defaults; adjust per stock volatility):**
   - `entry_window`: `["09:20", "09:45"]` — skip the opening 5 minutes.
   - `entry_zone`: last close ± a band that allows the expected gap, e.g. `[close×1.000, close×1.012]`
     for a positive catalyst. Never chase a gap larger than the expected move.
   - `target`: 1.5–3% from the zone mid for large caps; must be ≥ 1.5× the distance to the stop.
   - `stop`: 0.8–1.5% beyond the zone.
   - `exit_by`: `"15:10"` — always flat before the close.
7. **Confidence 0–100** reflects source quality, how certain the event is, and how clean the setup is.
   Below 55 = do not include.
8. Add an **avoid** list for stocks with risky news (results today, legal/regulatory trouble) so the
   user knows to stay away.
9. **Learn from the record.** Before choosing, read the last 10 saved plans in `plans/` and note which
   kinds of catalysts worked or failed. Mention it in `notes` when relevant.

## Plan format

```json
{
  "date": "2026-11-09",
  "market": "NSE",
  "timezone": "Asia/Kolkata",
  "stage": "morning final",
  "market_context": {
    "summary": "2-3 sentences: global cues, index mood, key events today.",
    "sources": ["https://...", "https://..."]
  },
  "picks": [
    {
      "ticker": "LT.NS",
      "company": "Larsen & Toubro",
      "direction": "LONG",
      "catalyst": "One line: what happened",
      "reasoning": "2-3 sentences: why it should move tomorrow, size vs company, why not priced in.",
      "confidence": 65,
      "ref_price": 3650.0,
      "entry_window": ["09:20", "09:45"],
      "entry_zone": [3650.0, 3690.0],
      "target": 3760.0,
      "stop": 3615.0,
      "exit_by": "15:10",
      "risk": "Main thing that would make this fail",
      "sources": ["https://...", "https://..."]
    }
  ],
  "avoid": [{ "ticker": "XYZ.NS", "reason": "Results during market hours", "sources": ["https://..."] }],
  "notes": "Optional: lessons from the track record."
}
```

## Save, publish, alert

```bash
python3 tools/plan.py save < /tmp/plan.json      # exit 0 = saved; exit 2 = fix the listed problems
git add plans && git commit -m "Trade plan $(date -u +%F) ($STAGE)" && git push -u origin claude/instagram-post-review-l3korb
```

Then send one alert (Gmail if available, otherwise a push notification), e.g.
`Trade plan for Mon 9 Nov: BUY LT 3650–3690, T 3760, S 3615 · BUY ... · Details: <Trade Desk URL>`.
If there are no picks, say so in one line.
