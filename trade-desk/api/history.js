// Every saved plan (up to 25 trading days), scored, with a running track record.
const { raw, scorePlan, send } = require('../lib/sim');
module.exports = async (req, res) => {
  try {
    const idx = await raw('plans/index.json');
    const dates = ((idx && idx.dates) || []).slice(0, 25);
    const days = [];
    for (const d of dates) {
      const p = await raw(`plans/${d}.json`);
      if (!p) continue;
      const s = await scorePlan(p);
      days.push({ date: d, picks: s.picks.map(x => ({ ticker: x.ticker, company: x.company, direction: x.direction,
        confidence: x.confidence, catalyst: x.catalyst, sim: x.sim, sources: x.sources })) });
    }
    const done = days.flatMap(d => d.picks).filter(p => ['TARGET HIT', 'STOPPED', 'TIME EXIT'].includes(p.sim.status));
    const wins = done.filter(p => p.sim.ret > 0).length;
    const total = done.reduce((a, p) => a + p.sim.ret, 0);
    send(res, 200, {
      days,
      summary: {
        trades: done.length, wins, losses: done.length - wins,
        win_rate: done.length ? +(wins / done.length * 100).toFixed(1) : null,
        avg_return: done.length ? +(total / done.length).toFixed(2) : null,
        total_return: +total.toFixed(2),
        not_triggered: days.flatMap(d => d.picks).filter(p => p.sim.status === 'NOT TRIGGERED').length,
      },
    }, 300);
  } catch (e) { send(res, 500, { error: String(e.message || e) }); }
};
