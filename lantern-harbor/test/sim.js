// Plays 400 computer-only games against the rules engine in index.html and checks
// money, ownership, buildings and card decks after every step.
// Run: node lantern-harbor/test/sim.js
const fs = require('fs'), vm = require('vm');
const path = require('path');
const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '..', 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script(?: id="engine")?>([\s\S]*?)<\/script>/g)].map(m => m[1]);
// parse-check UI script
new vm.Script(scripts[1], { filename: 'ui.js' });
const harness = `
const stats = { games: 0, last: 0, tally: 0, turns: [], trades: 0, auctionsWon: 0, offersToHumans: 0, inns: 0, errors: [] };
function check(tag) {
  for (const [i, p] of G.players.entries()) {
    if (!Number.isFinite(p.cash)) throw new Error(tag + ' cash NaN p' + i);
    if (!p.out && p.cash < 0 && G.phase !== 'debt') throw new Error(tag + ' negative cash p' + i + ' ' + p.cash + ' phase ' + G.phase);
  }
  for (const i of PROP_IDX) {
    const pr = G.props[i];
    if (pr.o >= 0 && G.players[pr.o].out) throw new Error(tag + ' prop owned by bankrupt');
    if (pr.h && !ownsSet(pr.o, SP[i].g)) throw new Error(tag + ' house without set');
    if (pr.h && pr.m) throw new Error(tag + ' house on mortgaged');
    if (pr.h === 5) stats.inns++;
  }
  const deckTotal = G.decks.tide.length + G.decks.guild.length + G.players.reduce((s, p) => s + p.pardons.length, 0) + (G.card && DECKS[G.card.deck][G.card.idx].fx.pardon ? 1 : 0);
  if (deckTotal !== 32) throw new Error(tag + ' deck count ' + deckTotal);
}
for (let game = 0; game < 400; game++) {
  const n = 2 + (game % 5);
  newGame({ cash: [1000,1500,2000][game%3], auctions: game % 4 !== 3, pot: game % 2 === 0, speed: 'quick',
    players: Array.from({ length: n }, (_, k) => ({ name: 'P' + k, color: '#000', bot: k % 3 !== 1 })) });
  let steps = 0;
  try {
    while (G.phase !== 'over') {
      if (++steps > 300000) throw new Error('stuck phase ' + G.phase);
      if (G.trade) { stats.offersToHumans++; const o = G.trade; G.trade = null; if (Math.random() < 0.5 && !tradeCheck(o)) { execTrade(o); stats.trades++; } continue; }
      if (G.phase === 'land') resolveLanding();
      else if (G.phase === 'resolving') throw new Error('left in resolving');
      else botStep();
      check('step');
      if (G.turnNo > 3000 && G.phase !== 'over') gameOver('tally');
    }
    stats.games++; stats[G.over.reason]++; stats.turns.push(G.turnNo);
  } catch (e) { stats.errors.push(game + ': ' + e.message); }
}
stats.turns.sort((a,b)=>a-b);
const t = stats.turns;
console.log(JSON.stringify({ games: stats.games, endedByBankruptcy: stats.last, endedByTally: stats.tally,
  medianTurns: t[t.length>>1], p90Turns: t[Math.floor(t.length*0.9)], offersToHumans: stats.offersToHumans,
  errors: stats.errors.slice(0, 8), errorCount: stats.errors.length }, null, 1));
// rent table sample
console.log(SP.filter(s=>s.t==='prop').map(s=>s.name+': '+s.rent.join('/')).slice(0,3).join(' | '));
console.log(SP.filter(s=>s.t==='prop').map(s=>s.name+': '+s.rent.join('/')).slice(-2).join(' | '));
`;
vm.runInNewContext(scripts[0] + harness, { console, Math, JSON, Number, Array, Map, Set, Object, Error });
