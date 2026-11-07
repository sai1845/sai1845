// Live index / macro strip and arbitrary tickers: /api/quotes?t=^NSEI,RELIANCE.NS
const { bars, send } = require('../lib/sim');
const DEFAULT = ['^NSEI', '^BSESN', '^NSEBANK', '^GSPC', '^IXIC', 'INR=X', 'BZ=F'];
module.exports = async (req, res) => {
  try {
    const q = new URL(req.url, 'http://x').searchParams.get('t');
    const list = (q ? q.split(',') : DEFAULT).slice(0, 12).map(s => s.trim()).filter(Boolean);
    const out = await Promise.all(list.map(async t => {
      try {
        const { meta } = await bars(t, '1d', '5m');
        const chg = meta.prevClose ? +((meta.price / meta.prevClose - 1) * 100).toFixed(2) : null;
        return { ticker: t, price: meta.price, change_pct: chg, currency: meta.currency, time: meta.marketTime };
      } catch (e) { return { ticker: t, error: String(e.message || e) }; }
    }));
    send(res, 200, { quotes: out, at: new Date().toISOString() }, 15);
  } catch (e) { send(res, 500, { error: String(e.message || e) }); }
};
