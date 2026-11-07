// Scores a trade-plan pick against real 5-minute bars.
// Rules (deliberately conservative, so the track record is not flattered):
//  - Entry: first bar inside the entry window whose range touches the entry zone.
//    Fill at the bar open if it is inside the zone, otherwise at the zone edge.
//    No zone given = fill at the first bar open in the window.
//  - After entry, each later bar is checked: if stop and target are both touched in
//    the same bar, the stop counts (worst case).
//  - If neither is hit, exit at the first bar at or after exit_by (its open).
const RAW = process.env.RADAR_RAW_BASE ||
  'https://raw.githubusercontent.com/sai1845/sai1845/claude/instagram-post-review-l3korb/market-radar';

const hhmm = d => d.toISOString().slice(11, 16);

async function bars(ticker, range = '1d', interval = '5m') {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=${range}&interval=${interval}&includePrePost=false`;
  const r = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (!r.ok) throw new Error(`Yahoo ${r.status} for ${ticker}`);
  const j = await r.json();
  const res = j.chart && j.chart.result && j.chart.result[0];
  if (!res) throw new Error(`No data for ${ticker}`);
  const m = res.meta, off = (m.gmtoffset || 0) * 1000, q = res.indicators.quote[0] || {};
  const out = [];
  (res.timestamp || []).forEach((t, i) => {
    if (q.open[i] == null || q.close[i] == null) return;
    const local = new Date(t * 1000 + off);
    out.push({ date: local.toISOString().slice(0, 10), time: hhmm(local), o: q.open[i], h: q.high[i], l: q.low[i], c: q.close[i], v: q.volume[i] });
  });
  return {
    meta: { price: m.regularMarketPrice, prevClose: m.chartPreviousClose ?? m.previousClose, currency: m.currency,
            exchange: m.exchangeName, marketTime: m.regularMarketTime, dayHigh: m.regularMarketDayHigh, dayLow: m.regularMarketDayLow,
            localNow: hhmm(new Date(Date.now() + off)), localDate: new Date(Date.now() + off).toISOString().slice(0, 10) },
    bars: out,
  };
}

function simulate(pick, dayBars, opts = {}) {
  const long = pick.direction !== 'SHORT';
  const [ws, we] = pick.entry_window, exitBy = pick.exit_by, z = pick.entry_zone;
  const pct = (exit, entry) => +(((long ? exit / entry : entry / exit) - 1) * 100).toFixed(2);
  const live = opts.live; // day still in progress
  const now = opts.localNow || '23:59';
  if (!dayBars.length) return { status: live ? 'WAITING' : 'NO DATA' };
  let entryIdx = -1, entry = null;
  for (let i = 0; i < dayBars.length; i++) {
    const b = dayBars[i];
    if (b.time < ws) continue;
    if (b.time > we) break;
    if (!z) { entryIdx = i; entry = b.o; break; }
    if (b.l <= z[1] && b.h >= z[0]) { entryIdx = i; entry = Math.min(Math.max(b.o, z[0]), z[1]); break; }
  }
  if (entryIdx < 0) {
    if (live && now <= we) return { status: now < ws ? 'WAITING' : 'WATCHING ENTRY' };
    return { status: 'NOT TRIGGERED', note: 'Price never reached the entry zone in the entry window.' };
  }
  const entryTime = dayBars[entryIdx].time;
  for (let i = entryIdx + 1; i < dayBars.length; i++) {
    const b = dayBars[i];
    if (b.time >= exitBy) return { status: 'TIME EXIT', entry, entryTime, exit: b.o, exitTime: b.time, ret: pct(b.o, entry) };
    const stopHit = long ? b.l <= pick.stop : b.h >= pick.stop;
    const tgtHit = long ? b.h >= pick.target : b.l <= pick.target;
    if (stopHit) return { status: 'STOPPED', entry, entryTime, exit: pick.stop, exitTime: b.time, ret: pct(pick.stop, entry) };
    if (tgtHit) return { status: 'TARGET HIT', entry, entryTime, exit: pick.target, exitTime: b.time, ret: pct(pick.target, entry) };
  }
  const last = dayBars[dayBars.length - 1];
  if (live) return { status: 'IN TRADE', entry, entryTime, last: last.c, lastTime: last.time, ret: pct(last.c, entry) };
  return { status: 'TIME EXIT', entry, entryTime, exit: last.c, exitTime: last.time, ret: pct(last.c, entry), note: 'Exited at the last bar of the day.' };
}

async function raw(path) {
  const r = await fetch(`${RAW}/${path}?t=${Math.floor(Date.now() / 60000)}`, { headers: { 'Cache-Control': 'no-cache' } });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GitHub ${r.status} for ${path}`);
  return r.json();
}

async function scorePlan(plan) {
  const picks = await Promise.all((plan.picks || []).map(async p => {
    try {
      const d = await bars(p.ticker, '1mo', '5m');
      const day = d.bars.filter(b => b.date === plan.date);
      const live = d.meta.localDate === plan.date;
      if (plan.date > d.meta.localDate) return { ...p, quote: d.meta, sim: { status: 'UPCOMING', note: `Plan for ${plan.date}. Entry opens at ${p.entry_window[0]}.` }, dayBars: [] };
      return { ...p, quote: d.meta, sim: simulate(p, day, { live, localNow: d.meta.localNow }), dayBars: day.map(b => [b.time, +b.c.toFixed(2)]) };
    } catch (e) { return { ...p, sim: { status: 'ERROR', note: String(e.message || e) } }; }
  }));
  return { ...plan, picks };
}

function send(res, code, body, maxAge = 0) {
  res.statusCode = code;
  res.setHeader('Content-Type', 'application/json');
  res.setHeader('Cache-Control', `public, s-maxage=${maxAge}, stale-while-revalidate=${maxAge * 2}`);
  res.end(JSON.stringify(body));
}

module.exports = { bars, simulate, raw, scorePlan, send };
