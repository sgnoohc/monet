// Fights in a recording, and what each fighter did in them.
//
// A fight is a run of melee hits between the same two players, ending when neither has hit the
// other for GAP_MS (or one of them dies). Its window runs from LEAD_MS before the first hit to a
// second after the last, for movement and clicking.
//
// Every swing in it is put down as a try of some kind, from what the swinger was doing (falling: a
// crit try; sprinting: a sprint hit; going up: too early for a crit; on the ground), and what came
// of it: a hit, a shield, too early (the other was still invulnerable from the last hit), out of
// reach, a miss, or not an attack at all (placing or breaking a block, emptying a bucket).
'use strict';
const { FLAGS } = require('./world');

/**
 * Bumped whenever a fight's numbers would come out differently: saved analyses made with an older
 * version are made again (from the recording, while it's still there).
 */
const ANALYZER_VERSION = 4;
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
/** After a hit, the one hit can't be hurt again for 10 ticks (unless harder). */
const INVULNERABLE_MS = 500;
/**
 * A hit comes back this long after its swing at most: the recording player's own swing is recorded
 * when they click, and the server's answer a ping later. (Others' come in the same tick.)
 */
const SWING_TO_HIT_MS = 300;
/** Survival reach: from the eyes to the hitbox. */
const REACH = 3;
/** Movement tracks, a sample a tick. */
const TRACK_STEP_MS = 50;
const TRIES = ['crit', 'sprint', 'rising', 'ground'];
const OUTCOMES = ['hit', 'blocked', 'early', 'far', 'miss'];
const KINDS = ['crit', 'sprint', 'sweep', 'other'];
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
  const crits = events.filter(e => e.type === 'critAnimation');
  const sweeps = events.filter(e => e.type === 'sweep');
  const kindOf = h => crits.some(c => c.victim === h.victim && Math.abs(c.time - h.time) <= SAME_TICK_MS) ? 'crit'
    : sweeps.some(e => e.player === h.attacker && Math.abs(e.time - h.time) <= SAME_TICK_MS) ? 'sweep'
      : h.a && h.a.sprinting ? 'sprint' : 'other';
  const swings = swingsIn(fight, events, kindOf);
  const side = (me, them) => fighter(world, fight, events, swings, me, them);
  const players = [side(a, b), side(b, a)];
  // The recording player first, if they're in it.
  if (players[1].self) players.reverse();
  const index = id => (id === players[0].id ? 0 : id === players[1].id ? 1 : null);
  // Times from the start of the fight's window.
  const at = t => t - fight.start;
  const key = p => `${fight.server}:${p.id}`;
  return {
    server: fight.server,
    startMs: fight.first,
    durationMs: fight.last - fight.first,
    /** The window: from LEAD_MS before the first hit (its start is time 0 below) to a second after the last. */
    windowStartMs: fight.start,
    windowMs: fight.end - fight.start,
    /** Fight time for rates (CPS, w-taps a minute): its window, a little either side of the hits. */
    seconds: Math.max(1, (fight.end - fight.start) / 1000),
    players,
    winner: fight.result ? players.find(p => p.id !== fight.result.loser).name : null,
    how: fight.result ? fight.result.how : null,
    // Every hit: when, by which of the two (0: the first listed), what kind, from how far.
    timeline: fight.hits.map(h => ({ t: at(h.time), by: index(h.attacker), kind: kindOf(h), reach: h.reach })),
    // Every swing: what it was meant as, what came of it (and as what kind of hit), how far, charged or not.
    swings: swings.map(s => ({ t: at(s.time), by: index(s.by), try: s.try, outcome: s.outcome, kind: s.kind || null,
      reach: s.reach === null ? null : round(s.reach, 2), charged: s.charged })),
    // Where both were, a sample a tick: [x, y, z, yaw, flags (FLAGS)], or null before they were seen.
    tracks: { step: TRACK_STEP_MS, flags: FLAGS, players: players.map(p => sample(world.tracks.get(key(p)) || [], fight.start, fight.end)) },
    held: players.map(p => heldIn(world.held.get(key(p)) || [], fight.start, fight.end).map(([t, item]) => [Math.max(0, at(t)), item])),
    health: players.map(p => events.filter(e => e.type === 'health' && e.player === p.id).map(e => [at(e.time), e.health])),
    blocks: events.filter(e => e.type === 'block').map(e => ({ t: at(e.time), block: e.block, x: e.x, y: e.y, z: e.z, by: index(e.player) })),
  };
}

/** What a swing was meant as, from what the swinger was doing: crits need falling and not sprinting. */
function tryOf(a) {
  if (!a) return 'ground';
  if (a.sprinting) return 'sprint';
  if (!a.onGround) return a.vy < 0 ? 'crit' : 'rising';
  return 'ground';
}

/** How long a weapon takes to charge (its attack speed), for telling full swings from spam. */
function cooldownMs(item) {
  if (!item) return 250;
  if (/_sword$/.test(item)) return 625;
  if (/^(wooden|stone)_axe$/.test(item)) return 1250;
  if (item === 'iron_axe') return 1111;
  if (/_axe$/.test(item)) return 1000;
  if (/_pickaxe$/.test(item)) return 833;
  if (/_shovel$/.test(item)) return 1000;
  if (item === 'trident') return 909;
  if (item === 'mace') return 1667;
  return 250;
}

/** The fight's swings, both fighters', each with its hit (or why it didn't hit). */
function swingsIn(fight, events, kindOf) {
  const [a, b] = fight.ids;
  const other = id => (id === a ? b : a);
  const swings = events.filter(e => e.type === 'swing' && fight.ids.includes(e.player)).map(e => {
    const near = (e.near || []).find(n => n.id === other(e.player));
    return { time: e.time, by: e.player, a: e.a, reach: near ? near.reach : null, hit: null };
  });
  // Each hit to its swing: the attacker's nearest one, from a ping before to the same tick.
  for (const h of fight.hits) {
    let best = null;
    for (const s of swings) {
      const d = h.time - s.time;
      if (s.by !== h.attacker || s.hit || d < -SAME_TICK_MS || d > SWING_TO_HIT_MS) continue;
      if (!best || Math.abs(d) < Math.abs(h.time - best.time)) best = s;
    }
    if (best) best.hit = h;
    else swings.push({ time: h.time, by: h.attacker, a: h.a, reach: h.reach, hit: h }); // its swing wasn't seen
  }
  swings.sort((x, y) => x.time - y.time);
  const hurt = events.filter(e => e.type === 'damage');
  const last = new Map();
  for (const s of swings) {
    const them = other(s.by);
    const previous = last.get(s.by);
    last.set(s.by, s.time);
    s.try = tryOf(s.a);
    s.charged = previous === undefined ? true : s.time - previous >= 0.9 * cooldownMs(s.a && s.a.mainHand);
    if (s.hit) {
      s.outcome = 'hit';
      s.kind = kindOf(s.hit);
      if (s.reach === null) s.reach = s.hit.reach;
      continue;
    }
    const around = (type, who) => events.some(e => e.type === type && e.player === who && Math.abs(e.time - s.time) <= 150);
    if (around('block', s.by) || around('blockWork', s.by) || around('water', s.by)) s.outcome = 'use';
    else if (around('shieldBlock', them)) s.outcome = 'blocked';
    else if (s.reach === null || s.reach > REACH) s.outcome = 'far';
    else if (hurt.some(e => e.victim === them && e.time < s.time && s.time - e.time < INVULNERABLE_MS)) s.outcome = 'early';
    else s.outcome = 'miss';
  }
  return swings;
}

/** A track's state every TRACK_STEP_MS from start to end: [x, y, z, yaw, flags], or null before it starts. */
function sample(track, start, end) {
  const out = [];
  let i = -1;
  for (let t = start; t <= end; t += TRACK_STEP_MS) {
    while (i + 1 < track.length && track[i + 1][0] <= t) i++;
    const s = track[i];
    out.push(s ? [round(s[1], 2), round(s[2], 2), round(s[3], 2), Math.round(s[4]), s[5]] : null);
  }
  return out;
}

/** What was held from start to end: the item at the start, then each change. */
function heldIn(held, start, end) {
  const before = held.filter(([t]) => t <= start).pop();
  return (before ? [before] : []).concat(held.filter(([t]) => t > start && t <= end));
}

function round(v, places) {
  const f = 10 ** places;
  return Math.round(v * f) / f;
}

function fighter(world, fight, events, allSwings, me, them) {
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

  // Tries and what came of them, of the swings that were attacks.
  const attacks = allSwings.filter(s => s.by === me && s.outcome !== 'use');
  const tries = {};
  for (const t of TRIES) {
    const ts = attacks.filter(s => s.try === t);
    const landed = ts.filter(s => s.outcome === 'hit');
    tries[t] = { tries: ts.length, landed: landed.length, charged: ts.filter(s => s.charged).length,
      as: Object.fromEntries(KINDS.map(k => [k, landed.filter(s => s.kind === k).length])) };
  }
  const outcomes = Object.fromEntries(OUTCOMES.map(o => [o, attacks.filter(s => s.outcome === o).length]));

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
    attacks: attacks.length,
    uses: allSwings.filter(s => s.by === me && s.outcome === 'use').length,
    accuracy: attacks.length ? mine.length / attacks.length : null,
    tries,
    outcomes,
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

module.exports = { fightsIn, BANDS, TRIES, OUTCOMES, KINDS, ANALYZER_VERSION };
