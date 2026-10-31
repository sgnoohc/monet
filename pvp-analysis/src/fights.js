// Fights in a recording, and what each fighter did in them.
//
// A fight is a run of melee hits between the same two players, ending when neither has hit the
// other for GAP_MS (or one of them dies). Its window runs from LEAD_MS before the first hit to a
// second after the last, for movement and clicking.
'use strict';

/**
 * Bumped whenever a fight's numbers would come out differently: saved analyses made with an older
 * version are made again (from the recording, while it's still there).
 */
const ANALYZER_VERSION = 3;
const GAP_MS = 15000;
/**
 * Hits from further than this aren't melee, whatever the damage source says (a server allows 3 blocks
 * and 3 more for lag): Quake Arena's guns, say. They're left out.
 */
const MELEE_REACH = 6;
const LEAD_MS = 3000;
/** Things in the same tick: a damage event and its crit animation, two clicks of a double click. */
const SAME_TICK_MS = 60;
const DOUBLE_CLICK_MS = 60;
/** Reach bands, by their upper edge, as in PvP Practice's duel summaries. */
const BANDS = [[2, 'under 2'], [2.5, '2–2.5'], [2.75, '2.5–2.75'], [3, '2.75–3'], [Infinity, '3+']];

function fightsIn(world) {
  const hits = world.events.filter(e => e.type === 'damage' && e.melee && e.attacker !== null && e.attacker !== e.victim
    && e.reach <= MELEE_REACH);
  const deaths = world.events.filter(e => e.type === 'death');
  const open = new Map(); // "server:a:b" (a < b) → fight
  const fights = [];
  for (const hit of hits) {
    const [a, b] = [hit.attacker, hit.victim].sort((x, y) => x - y);
    const key = `${hit.server}:${a}:${b}`;
    let fight = open.get(key);
    const died = fight && deaths.some(d => d.server === hit.server && fight.ids.includes(d.player) && d.time > fight.last && d.time <= hit.time);
    if (!fight || hit.time - fight.last > GAP_MS || died) {
      fight = { server: hit.server, ids: [a, b], first: hit.time, last: hit.time, hits: [] };
      open.set(key, fight);
      fights.push(fight);
    }
    fight.hits.push(hit);
    fight.last = hit.time;
  }
  for (const fight of fights) {
    fight.start = fight.first - LEAD_MS;
    fight.end = fight.last + 1000;
    const after = world.events.filter(e => e.server === fight.server && e.time >= fight.first && e.time <= fight.last + 10000);
    const death = after.find(e => e.type === 'death' && fight.ids.includes(e.player));
    fight.result = death ? { loser: death.player, how: 'died' } : resultFromTitles(world, fight, after);
  }
  return fights.map(f => describe(world, f));
}

/** The recording player's own result, from a VICTORY / DEFEAT title soon after the last hit. */
function resultFromTitles(world, fight, after) {
  const self = fight.ids.find(id => world.who(fight.server, id).self);
  if (self === undefined) return null;
  const other = fight.ids.find(id => id !== self);
  for (const e of after) {
    if (e.type !== 'title' || e.time < fight.last) continue;
    if (/victory|you win|won/i.test(e.text)) return { loser: other, how: 'title' };
    if (/defeat|you lose|lost/i.test(e.text)) return { loser: self, how: 'title' };
  }
  return null;
}

function describe(world, fight) {
  const events = world.events.filter(e => e.server === fight.server && e.time >= fight.start && e.time <= fight.end);
  const [a, b] = fight.ids;
  const side = (me, them) => fighter(world, fight, events, me, them);
  const players = [side(a, b), side(b, a)];
  // The recording player first, if they're in it.
  if (players[1].self) players.reverse();
  const crits = events.filter(e => e.type === 'critAnimation');
  const sweeps = events.filter(e => e.type === 'sweep');
  // Every hit: when (from the first), by which of the two (0: the first listed), what kind, from how far.
  const timeline = fight.hits.map(h => {
    const by = players[0].id === h.attacker ? 0 : 1;
    const crit = crits.some(c => c.victim === h.victim && Math.abs(c.time - h.time) <= SAME_TICK_MS);
    const sweep = sweeps.some(e => e.player === h.attacker && Math.abs(e.time - h.time) <= SAME_TICK_MS);
    const kind = crit ? 'crit' : sweep ? 'sweep' : h.a && h.a.sprinting ? 'sprint' : 'other';
    return { t: h.time - fight.first, by, kind, reach: h.reach };
  });
  return {
    server: fight.server,
    startMs: fight.first,
    durationMs: fight.last - fight.first,
    /** Fight time for rates (CPS, w-taps a minute): its window, a little either side of the hits. */
    seconds: Math.max(1, (fight.end - fight.start) / 1000),
    players,
    winner: fight.result ? players.find(p => p.id !== fight.result.loser).name : null,
    how: fight.result ? fight.result.how : null,
    timeline,
  };
}

function fighter(world, fight, events, me, them) {
  const { name, self } = world.who(fight.server, me);
  const mine = fight.hits.filter(h => h.attacker === me);
  const crits = events.filter(e => e.type === 'critAnimation' && e.victim === them);
  const sweeps = events.filter(e => e.type === 'sweep' && e.player === me);
  const isCrit = h => crits.some(c => Math.abs(c.time - h.time) <= SAME_TICK_MS);
  const isSweep = h => sweeps.some(s => Math.abs(s.time - h.time) <= SAME_TICK_MS);
  const reaches = mine.map(h => h.reach).filter(r => r !== null);

  const swings = events.filter(e => e.type === 'swing' && e.player === me).map(e => e.time);
  const seconds = Math.max(1, (fight.end - fight.start) / 1000);
  let best = 0;
  for (let i = 0, j = 0; i < swings.length; i++) {
    while (swings[i] - swings[j] >= 1000) j++;
    best = Math.max(best, i - j + 1);
  }
  let doubles = 0;
  for (let i = 1; i < swings.length; i++) if (swings[i] - swings[i - 1] < DOUBLE_CLICK_MS) doubles++;

  // Combos: hits in a row without being hit back.
  let streak = 0;
  let longest = 0;
  let combos = 0;
  for (const h of fight.hits) {
    if (h.attacker === me) {
      streak++;
      longest = Math.max(longest, streak);
      if (streak === 3) combos++;
    } else {
      streak = 0;
    }
  }

  const movement = moves(events, me, them);
  const count = type => events.filter(e => e.type === type && e.player === me).length;
  const placed = {};
  for (const e of events) if (e.type === 'block' && e.player === me) placed[e.block] = (placed[e.block] || 0) + 1;
  const health = events.filter(e => e.type === 'health' && e.player === me).map(e => e.health);

  return {
    id: me,
    name,
    self,
    hits: mine.length,
    crits: mine.filter(isCrit).length,
    sprintHits: mine.filter(h => h.a && h.a.sprinting && !isCrit(h) && !isSweep(h)).length,
    sweeps: mine.filter(isSweep).length,
    hitsTaken: fight.hits.length - mine.length,
    reach: reaches.length ? {
      mean: mean(reaches), median: median(reaches), max: Math.max(...reaches),
      bands: BANDS.map(([edge, label], i) => [label, reaches.filter(r => r < edge && (i === 0 || r >= BANDS[i - 1][0])).length]),
    } : null,
    swings: swings.length,
    cps: swings.length / seconds,
    bestCps: best,
    doubleClicks: doubles,
    accuracy: swings.length ? mine.length / swings.length : null,
    longestCombo: longest,
    combos,
    ...movement,
    jumps: count('jump'),
    sprintResets: count('sprintStart'),
    gapples: count('ate'),
    potions: count('drink'),
    pearls: count('pearl'),
    totems: count('totem'),
    blocked: count('shieldBlock'),
    placed,
    lowestHealth: health.length ? Math.min(...health) : null,
  };
}

/** Distance kept from the other fighter, how fast they moved sideways to them, time sprinting. */
function moves(events, me, them) {
  let other = null;
  let last = null;
  const distances = [];
  let sideways = 0;
  let sideTime = 0;
  let sprinting = 0;
  let samples = 0;
  for (const e of events) {
    if (e.type !== 'pos') continue;
    if (e.player === them) {
      other = e;
      continue;
    }
    if (e.player !== me) continue;
    samples++;
    if (e.sprinting) sprinting++;
    if (other) {
      const dx = other.x - e.x;
      const dz = other.z - e.z;
      const d = Math.hypot(dx, dz);
      distances.push(d);
      if (last && d > 0.1 && e.time > last.time) {
        // Movement across the line to the other player, in blocks a second.
        const mx = e.x - last.x;
        const mz = e.z - last.z;
        const across = Math.abs((mx * dz - mz * dx) / d);
        const dt = (e.time - last.time) / 1000;
        if (dt < 0.5) {
          sideways += across;
          sideTime += dt;
        }
      }
    }
    last = e;
  }
  return {
    distance: distances.length ? { mean: mean(distances), median: median(distances) } : null,
    strafeSpeed: sideTime > 0 ? sideways / sideTime : null,
    sprintingShare: samples ? sprinting / samples : null,
  };
}

function mean(xs) {
  return xs.reduce((s, x) => s + x, 0) / xs.length;
}

function median(xs) {
  const s = [...xs].sort((x, y) => x - y);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
}

module.exports = { fightsIn, BANDS, ANALYZER_VERSION };
