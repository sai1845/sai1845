// Latest trade plan, scored against live 5-minute prices.
const { raw, scorePlan, send } = require('../lib/sim');
module.exports = async (req, res) => {
  try {
    const plan = await raw('plans/latest.json');
    if (!plan) return send(res, 200, { empty: true }, 30);
    send(res, 200, await scorePlan(plan), 20);
  } catch (e) { send(res, 500, { error: String(e.message || e) }); }
};
