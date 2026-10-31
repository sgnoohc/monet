// A fight's view: a replay of where both players were (seen from above, with every hit and swing),
// the distance between them, every swing on a timeline, their health, and the fight's numbers side
// by side. The charts and the replay share one clock: click a chart to go there.
//
// It's part of the overview's page (one file, so it opens from anywhere: a sandboxed browser that
// was given just that file, say). Each fight's data waits in the page, unread, until it's opened.
'use strict';

/** What a fight's view needs: the entry's i-th fight, with its swings and tracks. */
function fightData(entry, i, { generated = new Date() } = {}) {
  const f = entry.fights[i];
  const selfIndex = f.players.findIndex(p => p.self);
  const result = selfIndex < 0 || !f.winner ? null : f.winner === f.players[selfIndex].name ? 'win' : 'loss';
  const names = f.players.map(p => p.name);
  return {
    title: selfIndex >= 0 ? `Fight vs ${names[1 - selfIndex]}` : `${names[0]} vs ${names[1]}`,
    generated: generated.getTime(),
    id: `${entry.id}-${i + 1}`,
    recording: entry.file,
    server: entry.meta.serverName,
    date: entry.meta.date + f.startMs,
    durationMs: f.durationMs,
    windowMs: f.windowMs || null,
    lead: f.windowStartMs !== undefined ? f.startMs - f.windowStartMs : 0,
    result,
    selfIndex,
    winner: f.winner,
    players: f.players,
    timeline: f.timeline || [],
    swings: f.swings || null,
    tracks: f.tracks || null,
    held: f.held || [[], []],
    health: f.health || [[], []],
    blocks: f.blocks || [],
  };
}

/** The view's parts, copied into the page when a fight is opened (ids are looked up within it). */
const FIGHT_TEMPLATE = `<template id="fight-template">
  <p class="note"><a href="#">← All fights</a></p>
  <header>
    <h1 id="title"></h1>
    <p class="sub" id="summary"></p>
  </header>
  <section class="card">
    <h2>Side by side</h2>
    <div class="legend" id="versus-key"></div>
    <div id="versus" class="versus"></div>
  </section>
  <section class="card" id="replay-card">
    <h2>Replay</h2>
    <p class="note">From above, north up. Circles are the players, with a line the way they look; the trail is the last 2 seconds. A hit draws a line from the attacker, in its kind's colour.</p>
    <div class="replay">
      <div class="map-wrap"><svg id="map" role="img" aria-label="Where the players were"></svg></div>
      <div class="panel" id="panel" aria-live="off"></div>
    </div>
    <div class="controls">
      <button id="play" aria-label="Play">▶ Play</button>
      <span id="clock" class="clock"></span>
      <input type="range" id="scrub" min="0" value="0" step="50" aria-label="Time in the fight">
      <label>Speed <select id="speed"><option value="0.1">0.1×</option><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1" selected>1×</option><option value="2">2×</option></select></label>
    </div>
    <p class="note">Space plays and pauses; ← and → step a tick (with Shift, a second); click any chart below to go to that moment.</p>
  </section>
  <section class="card" id="distance-card">
    <h2>Distance</h2>
    <p class="note">From <span class="name-0"></span>'s eyes to <span class="name-1"></span>'s hitbox: what the 3-block reach is measured on. Dots are hits, at their reach.</p>
    <div id="distance"></div>
  </section>
  <section class="card" id="swings-card">
    <h2>Every swing</h2>
    <p class="note">Each player's swings along the fight: the ones that landed in their kind's colour, the rest in gray, shaped by why they didn't land.</p>
    <div id="lanes"></div>
  </section>
  <section class="card" id="health-card" hidden>
    <h2>Health</h2>
    <p class="note">In health points: 20 is full, 1 is half a heart. Yours is exact; your opponent's is what the server sent, if it sent it.</p>
    <div id="health"></div>
  </section>
  <section class="two">
    <div class="card"><h2>Tried, and landed</h2><div id="tries"></div></div>
    <div class="card"><h2>Where the swings went</h2><div id="outcomes"></div></div>
  </section>
  <section class="two">
    <div class="card"><h2>How hits landed</h2><div id="mix"></div></div>
    <div class="card"><h2>Everything measured</h2><div id="everything"></div></div>
  </section>
  <footer class="note" id="footer" style="margin-top: 32px"></footer>
</template>`;

const FIGHT_CSS = `
.replay { display: grid; grid-template-columns: minmax(0, 3fr) minmax(220px, 2fr); gap: 16px; align-items: start; }
.map-wrap { background: var(--map); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
#map { display: block; width: 100%; height: auto; touch-action: none; }
#map text { paint-order: stroke; stroke: var(--map); stroke-width: 3px; stroke-linejoin: round; }
.panel { font-size: 13px; }
.panel .big { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
.panel .who { border-top: 1px solid var(--grid); padding: 10px 0; }
.panel .who .name { font-weight: 600; display: flex; align-items: center; gap: 6px; }
.panel .states { display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0; min-height: 18px; }
.panel .muted { color: var(--text-secondary); }
.panel .event { border-top: 1px solid var(--grid); padding-top: 10px; min-height: 40px; }
.controls { display: flex; gap: 12px; align-items: center; margin-top: 12px; flex-wrap: wrap; }
.controls input[type=range] { flex: 1; min-width: 160px; accent-color: var(--you); }
.clock { font-variant-numeric: tabular-nums; min-width: 92px; color: var(--text-secondary); }
.versus { display: grid; grid-template-columns: 56px minmax(0, 1fr) minmax(120px, auto) minmax(0, 1fr) 56px; align-items: center; gap: 4px 10px; font-size: 13px; margin-top: 8px; }
.versus .v { font-variant-numeric: tabular-nums; }
.versus .v.l { text-align: right; } .versus .label { text-align: center; color: var(--text-secondary); }
.versus .half { height: 10px; display: flex; }
.versus .half.l { justify-content: flex-end; }
.versus .half i { display: block; height: 100%; border-radius: 4px 0 0 4px; }
.versus .half.r i { border-radius: 0 4px 4px 0; }
.legend svg { display: inline-block; width: 12px; height: 12px; flex: none; }
@media (max-width: 760px) { .replay { grid-template-columns: 1fr; } }
`;

// The view's script (after page.js's helpers): openFight(F, root) draws fight F into root, and
// returns what to call when leaving it.
const FIGHT_JS = String.raw`
function openFight(F, root) {
const $ = id => root.querySelector('#' + id);
$('title').textContent = F.title;
const P = F.players;
const me = F.selfIndex >= 0 ? F.selfIndex : 0;
const COLORS = ['var(--you)', 'var(--them-strong)'];
const name = i => (F.selfIndex === i ? 'You' : P[i].name);
const FL = F.tracks ? F.tracks.flags : { onGround: 1, sprinting: 2, sneaking: 4, usingItem: 8, blocking: 16 };
const END = F.windowMs || (F.timeline.length ? F.timeline[F.timeline.length - 1].t + 1000 : 1000);
const TRY_NAMES = Object.fromEntries(TRIES.map(([k, label]) => [k, label]));
const TRY_PHRASES = { crit: 'falling: a crit try', sprint: 'sprinting', rising: 'going up in a jump', ground: 'on the ground' };
const OUTCOME_NAMES = Object.fromEntries(OUTCOMES.map(([k, label]) => [k, label]));
OUTCOME_NAMES.use = 'Placing or breaking a block';
root.querySelectorAll('.name-0').forEach(n => { n.textContent = name(0) === 'You' ? 'your' : P[0].name; });
root.querySelectorAll('.name-1').forEach(n => { n.textContent = P[1].name; });

// ---------------------------------------------------------------- the summary and side by side

(() => {
  const res = F.result === 'win' ? 'won' : F.result === 'loss' ? 'lost' : F.winner ? F.winner + ' won' : 'no result recorded';
  $('summary').textContent = F.server + ' · ' + new Date(F.date).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    + ' · ' + clock(F.durationMs) + ' from the first hit to the last · ' + (F.result ? 'You ' : '') + res;
  $('versus-key').append(...legend([[name(0), COLORS[0]], [name(1), COLORS[1]]]).childNodes);
  const v = $('versus');
  const of = (p, o) => p.outcomes ? p.outcomes[o] : null;
  const rows = [
    ['Hits', p => p.hits], ['Crits', p => p.crits], ['Sprint hits', p => p.sprintHits], ['Sweeps', p => p.sweeps],
    ['Attacks (swings)', p => ok(p.attacks) ? p.attacks : p.swings], ['Attacks that landed', p => p.accuracy, pct, 1],
    ['Too early', p => of(p, 'early')], ['Out of reach', p => of(p, 'far')], ['Missed in reach', p => of(p, 'miss')],
    ['Mean reach (blocks)', p => p.reach ? p.reach.mean : null, x => num(x)], ['Longest combo', p => p.longestCombo],
    ['Best clicks in a second', p => p.bestCps], ['W-taps', p => p.sprintResets], ['Jumps', p => p.jumps],
    ['Golden apples', p => p.gapples], ['Blocks placed', p => Object.values(p.placed || {}).reduce((a, b) => a + b, 0)],
  ];
  for (const [label, get, fmt = x => (ok(x) ? String(Math.round(x * 100) / 100) : '–'), max] of rows) {
    const a = get(P[0]), b = get(P[1]);
    const top = max || Math.max(ok(a) ? a : 0, ok(b) ? b : 0) || 1;
    const half = (val, side, color) => {
      const h = el('div', { class: 'half ' + side });
      const i = el('i');
      i.style.width = (ok(val) ? Math.max(0, val) / top * 100 : 0) + '%';
      i.style.background = color;
      h.append(i);
      return h;
    };
    v.append(el('div', { class: 'v l' }, fmt(a)), half(a, 'l', COLORS[0]), el('div', { class: 'label' }, label), half(b, 'r', COLORS[1]), el('div', { class: 'v' }, fmt(b)));
  }
})();

// ---------------------------------------------------------------- where everyone was, at any time

const STEP = F.tracks ? F.tracks.step : 50;
const T = F.tracks ? F.tracks.players : [[], []];
/** A player's state at time t (ms from the window's start), between samples: { x, y, z, yaw, flags } or null. */
function stateAt(i, t) {
  const s = T[i];
  const k = Math.max(0, Math.min(s.length - 1, Math.floor(t / STEP)));
  const a = s[k];
  if (!a) return null;
  const b = s[k + 1] || a;
  const f = Math.max(0, Math.min(1, t / STEP - k));
  let dyaw = ((b[3] - a[3]) % 360 + 540) % 360 - 180;
  return { x: a[0] + (b[0] - a[0]) * f, y: a[1] + (b[1] - a[1]) * f, z: a[2] + (b[2] - a[2]) * f, yaw: a[3] + dyaw * f, flags: a[4] };
}
const has = (s, flag) => s && (s.flags & FL[flag]) !== 0;
/** From one player's eyes to the other's hitbox: reach, as the server measures it. */
function reachOf(a, b) {
  if (!a || !b) return null;
  const ey = a.y + (has(a, 'sneaking') ? 1.27 : 1.62);
  const top = b.y + (has(b, 'sneaking') ? 1.5 : 1.8);
  const gap = (lo, hi, v) => Math.max(lo - v, 0, v - hi);
  return Math.hypot(gap(b.x - 0.3, b.x + 0.3, a.x), gap(b.y, top, ey), gap(b.z - 0.3, b.z + 0.3, a.z));
}
/** How high above where they last stood: for "in the air". */
function heightAt(i, t) {
  const s = T[i];
  let k = Math.min(s.length - 1, Math.floor(t / STEP));
  const now = stateAt(i, t);
  for (; k >= 0; k--) if (s[k] && (s[k][4] & FL.onGround)) return now ? now.y - s[k][1] : null;
  return null;
}
const lastBefore = (list, t) => { let v = null; for (const e of list) { if (e[0] > t) break; v = e[1]; } return v; };
const itemName = item => item ? item.replace(/_/g, ' ') : 'nothing';

// ---------------------------------------------------------------- the replay

const map = $('map');
let draw = () => {};
if (!F.tracks || !T[0].some(Boolean)) {
  $('replay-card').replaceChildren(el('h2', {}, 'Replay'),
    el('p', { class: 'note' }, 'This fight was analysed before positions were kept. Run the analysis again with --force while its recording is still there.'));
} else {
  // The whole area they were in, square, with a margin; and a view that follows the two of them.
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const s of T) for (const p of s) if (p) { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); z0 = Math.min(z0, p[2]); z1 = Math.max(z1, p[2]); }
  const whole = { cx: (x0 + x1) / 2, cz: (z0 + z1) / 2, side: Math.max(x1 - x0, z1 - z0, 6) + 4 };
  const S = 600;
  map.setAttribute('viewBox', '0 0 ' + S + ' ' + S);
  /** Where to look at time t: the middle of the two, wide enough for both and room around, averaged over a second so it doesn't shake. */
  function followView(t) {
    let sx = 0, sz = 0, n = 0, apart = 0, pairs = 0;
    for (let tt = t - 500; tt <= t + 500; tt += 100) {
      const c = Math.max(0, Math.min(END, tt));
      const pts = [stateAt(0, c), stateAt(1, c)].filter(Boolean);
      if (!pts.length) continue;
      sx += pts.reduce((a, p) => a + p.x, 0) / pts.length; sz += pts.reduce((a, p) => a + p.z, 0) / pts.length; n++;
      if (pts.length === 2) { apart += Math.hypot(pts[0].x - pts[1].x, pts[0].z - pts[1].z); pairs++; }
    }
    if (!n) return whole;
    return { cx: sx / n, cz: sz / n, side: Math.min(whole.side, Math.max(14, (pairs ? apart / pairs : 0) * 1.6 + 8)) };
  }
  let mode = 'follow';
  try { if (localStorage.getItem('pvp-analysis-map') === 'whole') mode = 'whole'; } catch (e) {}

  // The world, in blocks (x east, z south), scaled and moved as one; lines keep their width.
  const world = svg('g');
  const thin = { 'vector-effect': 'non-scaling-stroke', fill: 'none' };
  const grids = [1, 5, 10].map(every => {
    const g = svg('g');
    const pad = 20;
    for (let gx = Math.floor((x0 - pad) / every) * every; gx <= x1 + pad; gx += every) g.append(svg('line', { x1: gx, x2: gx, y1: z0 - pad, y2: z1 + pad, stroke: 'var(--grid)', ...thin }));
    for (let gz = Math.floor((z0 - pad) / every) * every; gz <= z1 + pad; gz += every) g.append(svg('line', { y1: gz, y2: gz, x1: x0 - pad, x2: x1 + pad, stroke: 'var(--grid)', ...thin }));
    world.append(g);
    return [every, g];
  });
  // The whole fight's paths, faint, for where they went overall.
  T.forEach((s, i) => world.append(svg('polyline', { points: s.filter(Boolean).map(p => p[0] + ',' + p[2]).join(' '), stroke: COLORS[i], 'stroke-width': 1, opacity: 0.2, ...thin })));
  // Blocks placed, shown from when they were placed.
  const blockNodes = F.blocks.map(b => {
    const g = svg('g', { visibility: 'hidden' });
    g.append(svg('rect', { x: b.x, y: b.z, width: 1, height: 1, stroke: 'var(--muted)', ...thin, fill: b.block === 'water' ? 'var(--you)' : 'none', 'fill-opacity': 0.2 }));
    if (b.block === 'cobweb') g.append(svg('path', { d: 'M' + b.x + ' ' + b.z + 'l1 1m0 -1l-1 1', stroke: 'var(--muted)', ...thin }));
    world.append(g);
    return [b, g];
  });
  const trails = [0, 1].map(i => { const t = svg('polyline', { stroke: COLORS[i], 'stroke-width': 2, 'stroke-linejoin': 'round', opacity: 0.6, ...thin }); world.append(t); return t; });
  map.append(world);
  // On top, in screen units: hits and swings, the players, the scale.
  const effects = svg('g');
  map.append(effects);
  const figures = [0, 1].map(i => {
    const g = svg('g');
    const shield = svg('line', { stroke: 'var(--text-secondary)', 'stroke-width': 4, 'stroke-linecap': 'round', visibility: 'hidden' });
    const look = svg('line', { stroke: COLORS[i], 'stroke-width': 2, 'stroke-linecap': 'round' });
    const body = svg('circle', { fill: COLORS[i], stroke: 'var(--surface-1)', 'stroke-width': 2 });
    const label = svgText({ 'font-size': 12, 'font-weight': 600, 'text-anchor': 'middle', fill: 'var(--text-primary)' }, name(i));
    g.append(look, shield, body, label);
    map.append(g);
    return { g, shield, look, body, label };
  });
  const scaleBar = svg('line', { x1: 12, y1: S - 14, y2: S - 14, stroke: 'var(--text-secondary)', 'stroke-width': 2 });
  const scaleText = svgText({ x: 12, y: S - 20, 'font-size': 11, fill: 'var(--text-secondary)' }, '');
  map.append(scaleBar, scaleText, svgText({ x: S - 12, y: 20, 'font-size': 11, 'text-anchor': 'end', fill: 'var(--text-secondary)' }, '↑ north'));

  // Follow, or the whole area.
  const modes = el('div', { class: 'tabs', role: 'group', 'aria-label': 'Map view' });
  for (const [m, label] of [['follow', 'Follow the fight'], ['whole', 'Whole area']]) {
    const b = el('button', { 'aria-pressed': String(mode === m), 'aria-selected': String(mode === m) }, label);
    b.addEventListener('click', () => {
      mode = m;
      try { localStorage.setItem('pvp-analysis-map', m); } catch (e) {}
      for (const o of modes.children) { o.setAttribute('aria-pressed', String(o === b)); o.setAttribute('aria-selected', String(o === b)); }
      draw(time);
    });
    modes.append(b);
  }
  root.querySelector('.replay').before(modes);

  draw = t => {
    const view = mode === 'follow' ? followView(t) : whole;
    const px = S / view.side;
    const X = x => (x - view.cx) * px + S / 2, Z = z => (z - view.cz) * px + S / 2;
    world.setAttribute('transform', 'translate(' + S / 2 + ' ' + S / 2 + ') scale(' + px + ') translate(' + -view.cx + ' ' + -view.cz + ')');
    const every = px >= 14 ? 1 : px >= 4 ? 5 : 10;
    for (const [e, g] of grids) g.setAttribute('visibility', e === every ? 'visible' : 'hidden');
    scaleBar.setAttribute('x2', 12 + every * px);
    scaleText.textContent = plural(every, 'block');
    const r = Math.max(6, 0.3 * px);
    const now = [stateAt(0, t), stateAt(1, t)];
    now.forEach((s, i) => {
      const fig = figures[i];
      fig.g.setAttribute('visibility', s ? 'visible' : 'hidden');
      if (!s) return;
      const x = X(s.x), z = Z(s.z);
      const dx = -Math.sin(s.yaw * Math.PI / 180), dz = Math.cos(s.yaw * Math.PI / 180);
      const len = Math.max(18, 1.2 * px);
      fig.look.setAttribute('x1', x); fig.look.setAttribute('y1', z);
      fig.look.setAttribute('x2', x + dx * len); fig.look.setAttribute('y2', z + dz * len);
      fig.body.setAttribute('cx', x); fig.body.setAttribute('cy', z); fig.body.setAttribute('r', r);
      // In the air: a hollow ring; on the ground: filled.
      const air = !has(s, 'onGround');
      fig.body.setAttribute('fill', air ? 'var(--map)' : COLORS[i]);
      fig.body.setAttribute('stroke', air ? COLORS[i] : 'var(--surface-1)');
      fig.body.setAttribute('stroke-width', air ? 3 : 2);
      fig.label.setAttribute('x', x); fig.label.setAttribute('y', z - r - 8);
      const blocking = has(s, 'blocking');
      fig.shield.setAttribute('visibility', blocking ? 'visible' : 'hidden');
      if (blocking) {
        const w = Math.max(8, 0.4 * px), ax = x + dx * (r + 5), az = z + dz * (r + 5);
        fig.shield.setAttribute('x1', ax - dz * w); fig.shield.setAttribute('y1', az + dx * w);
        fig.shield.setAttribute('x2', ax + dz * w); fig.shield.setAttribute('y2', az - dx * w);
      }
      const pts = [];
      for (let tt = Math.max(0, t - 2000); tt <= t; tt += STEP) { const p = stateAt(i, tt); if (p) pts.push(p.x.toFixed(2) + ',' + p.z.toFixed(2)); }
      pts.push(s.x.toFixed(2) + ',' + s.z.toFixed(2));
      trails[i].setAttribute('points', pts.join(' '));
    });
    for (const [b, g] of blockNodes) g.setAttribute('visibility', b.t <= t ? 'visible' : 'hidden');
    // Hits in the last 0.6 s: a line from the attacker to the one hit, and a ring; swings that didn't land: a small gray ring.
    effects.replaceChildren();
    for (const s of F.swings || F.timeline.map(h => ({ ...h, outcome: 'hit' }))) {
      const age = t - s.t;
      if (age < 0 || age > 600 || s.by === null) continue;
      const a = stateAt(s.by, s.t), v = stateAt(1 - s.by, s.t);
      if (!a) continue;
      const fade = 1 - age / 600;
      if (s.outcome === 'hit' && v) {
        const color = 'var(--' + (s.kind || 'other') + ')';
        effects.append(svg('line', { x1: X(a.x), y1: Z(a.z), x2: X(v.x), y2: Z(v.z), stroke: color, 'stroke-width': 3, 'stroke-linecap': 'round', opacity: fade }));
        effects.append(svg('circle', { cx: X(v.x), cy: Z(v.z), r: r + 4 + age / 40, fill: 'none', stroke: color, 'stroke-width': 3, opacity: fade }));
        if (age < 450) effects.append(svgText({ x: (X(a.x) + X(v.x)) / 2, y: (Z(a.z) + Z(v.z)) / 2 - 10, 'font-size': 12, 'font-weight': 600, 'text-anchor': 'middle', fill: 'var(--text-primary)', opacity: fade },
          (KIND_NAMES[s.kind] || 'Hit') + (ok(s.reach) ? ' ' + num(s.reach) : '')));
      } else if (s.outcome !== 'use' && age < 300) {
        effects.append(svg('circle', { cx: X(a.x), cy: Z(a.z), r: r + 2 + age / 30, fill: 'none', stroke: 'var(--muted)', 'stroke-width': 1.5, opacity: 1 - age / 300 }));
      }
    }
  };
}

// The panel beside the map: the time, the distance, each player's state, the last thing that happened.
const panel = $('panel');
const pTime = el('div', { class: 'muted' });
const pDist = el('div', { class: 'big' });
const pDistNote = el('div', { class: 'muted' });
const who = [0, 1].map(i => {
  const box = el('div', { class: 'who' });
  const n = el('div', { class: 'name' });
  const key = el('i', { class: 'tt-key dot' });
  key.style.background = COLORS[i];
  n.append(key, document.createTextNode(name(i) === 'You' ? 'You (' + P[i].name + ')' : P[i].name));
  const states = el('div', { class: 'states' });
  const line = el('div', { class: 'muted' });
  box.append(n, states, line);
  panel.append(box);
  return { states, line };
});
const pEvent = el('div', { class: 'event' });
panel.prepend(pTime, pDist, pDistNote);
panel.append(pEvent);

function describeAt(t) {
  const now = [stateAt(0, t), stateAt(1, t)];
  pTime.textContent = clockTenths(t) + ' of ' + clockTenths(END) + (t < F.lead ? ' · before the first hit' : '');
  const d = reachOf(now[0], now[1]);
  pDist.textContent = ok(d) ? num(d) + ' blocks' : '–';
  pDistNote.textContent = ok(d) ? (d <= 3 ? 'in reach' : 'out of reach') + ' (from ' + (F.selfIndex === 0 ? 'your' : P[0].name + '\'s') + ' eyes to ' + P[1].name + '\'s hitbox)' : '';
  now.forEach((s, i) => {
    const chips = [];
    if (s) {
      if (has(s, 'sprinting')) chips.push('Sprinting');
      if (!has(s, 'onGround')) { const h = heightAt(i, t); chips.push('In the air' + (ok(h) && h > 0.05 ? ' +' + h.toFixed(1) : '')); }
      if (has(s, 'sneaking')) chips.push('Sneaking');
      if (has(s, 'blocking')) chips.push('Shield up');
      else if (has(s, 'usingItem')) chips.push('Using an item');
    }
    who[i].states.replaceChildren(...chips.map(c => el('span', { class: 'chip' }, c)));
    // (What they hold is only known if the server sent their equipment.)
    const held = (F.held[i] || []).length ? 'Holding ' + itemName(lastBefore(F.held[i], t)) : null;
    const hp = lastBefore(F.health[i] || [], t);
    const hits = F.timeline.filter(h => h.by === i && h.t <= t);
    who[i].line.textContent = [held, ok(hp) ? '♥ ' + Math.round(hp * 10) / 10 : null,
      plural(hits.length, 'hit') + ' so far' + (hits.length ? ' (' + hits.filter(h => h.kind === 'crit').length + ' crits)' : '')].filter(Boolean).join(' · ');
  });
  const last = (F.swings || []).filter(s => s.t <= t && s.outcome !== 'use').pop();
  pEvent.replaceChildren();
  if (last) {
    pEvent.append(el('div', { class: 'muted' }, 'Last swing, ' + clockTenths(last.t)));
    const line = el('div');
    line.textContent = name(last.by) + ': ' + (last.outcome === 'hit' ? KIND_NAMES[last.kind] || 'Hit' : OUTCOME_NAMES[last.outcome])
      + (ok(last.reach) ? ' at ' + num(last.reach) + ' blocks' : '') + (last.try ? ' · ' + TRY_PHRASES[last.try] : '')
      + (last.charged === false ? ', not fully charged' : '');
    pEvent.append(line);
  }
}

// ---------------------------------------------------------------- the clock, and the controls

let time = 0, playing = false, speed = 1, lastFrame = null;
const cursors = [];
const scrub = $('scrub');
scrub.max = END;
const clockEl = $('clock');
const playButton = $('play');
function seek(t) {
  time = Math.max(0, Math.min(END, t));
  scrub.value = time;
  clockEl.textContent = clockTenths(time) + ' / ' + clockTenths(END);
  draw(time);
  describeAt(time);
  for (const c of cursors) c(time);
}
function setPlaying(on) {
  playing = on && F.tracks !== null;
  if (playing && time >= END) seek(0);
  playButton.textContent = playing ? '❚❚ Pause' : '▶ Play';
  playButton.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  lastFrame = null;
  if (playing) requestAnimationFrame(frame);
}
function frame(now) {
  if (!playing) return;
  if (lastFrame !== null) seek(time + (now - lastFrame) * speed);
  lastFrame = now;
  if (time >= END) { setPlaying(false); return; }
  requestAnimationFrame(frame);
}
playButton.addEventListener('click', () => setPlaying(!playing));
scrub.addEventListener('input', () => seek(Number(scrub.value)));
$('speed').addEventListener('change', e => { speed = Number(e.target.value); });
const onKey = e => {
  if (['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(document.activeElement.tagName) && e.key === ' ') return;
  if (e.key === ' ') { e.preventDefault(); setPlaying(!playing); }
  else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    if (document.activeElement === scrub) return;
    e.preventDefault();
    setPlaying(false);
    seek(time + (e.key === 'ArrowRight' ? 1 : -1) * (e.shiftKey ? 1000 : STEP));
  }
};
document.addEventListener('keydown', onKey);

// ---------------------------------------------------------------- charts along the fight

/** A chart along the fight's time: x from 0 to END, a cursor at the clock, click to go there. */
function timeChart(container, { height, top = 10, bottom = 24, label }) {
  const W = 1100, L = 110, R = 16;
  const x = t => L + (W - L - R) * t / END;
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + height, role: 'img', 'aria-label': label });
  const ticks = [];
  const every = END > 60000 ? 10000 : END > 20000 ? 5000 : 2000;
  for (let t = 0; t <= END; t += every) ticks.push(t);
  for (const t of ticks) s.append(svgText({ x: x(t), y: height - 6, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--muted)' }, clock(t)));
  // The first hit, for orientation.
  s.append(svg('line', { x1: x(F.lead), x2: x(F.lead), y1: top, y2: height - bottom, stroke: 'var(--axis)', 'stroke-dasharray': '2 3' }));
  const cursor = svg('line', { y1: top - 4, y2: height - bottom, stroke: 'var(--text-primary)', 'stroke-width': 1.5 });
  const marks = svg('g');
  s.append(marks, cursor);
  cursors.push(t => { cursor.setAttribute('x1', x(t)); cursor.setAttribute('x2', x(t)); });
  const toTime = evt => { const p = s.getBoundingClientRect(); return ((evt.clientX - p.left) / p.width * W - L) / (W - L - R) * END; };
  s.addEventListener('click', evt => { setPlaying(false); seek(toTime(evt)); });
  s.style.cursor = 'pointer';
  const wide = el('div', { class: 'wide' });
  wide.append(s);
  container.append(wide);
  return { s, x, W, L, R, marks, toTime };
}

// Distance: your eyes to their hitbox along the fight, the 3-block reach, hits as dots.
(() => {
  const card = $('distance');
  if (!F.tracks) { $('distance-card').hidden = true; return; }
  const H = 220, top = 12, bottom = 26;
  const ds = [];
  for (let t = 0; t <= END; t += STEP) ds.push([t, reachOf(stateAt(0, t), stateAt(1, t))]);
  const known = ds.map(d => d[1]).filter(ok);
  const hi = Math.min(10, niceMax(Math.max(4, ...known)));
  const c = timeChart(card, { height: H, top, bottom, label: 'Distance over the fight' });
  const y = v => top + (H - top - bottom) * (1 - Math.min(v, hi) / hi);
  for (const v of [0, hi / 2, hi]) {
    c.marks.append(svg('line', { x1: c.L, x2: c.W - c.R, y1: y(v), y2: y(v), stroke: v === 0 ? 'var(--axis)' : 'var(--grid)' }));
    c.marks.append(svgText({ x: c.L - 8, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' }, v + (v === hi ? '+ blocks' : '')));
  }
  c.marks.append(svg('line', { x1: c.L, x2: c.W - c.R, y1: y(3), y2: y(3), stroke: 'var(--text-secondary)', 'stroke-dasharray': '6 4' }),
    svgText({ x: c.L - 8, y: y(3) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--text-secondary)' }, 'reach 3'));
  // The line, broken where either player wasn't seen.
  let d = '', pen = false;
  for (const [t, v] of ds) {
    if (ok(v)) { d += (pen ? 'L' : 'M') + c.x(t).toFixed(1) + ' ' + y(v).toFixed(1); pen = true; } else pen = false;
  }
  c.marks.append(svg('path', { d, fill: 'none', stroke: 'var(--text-secondary)', 'stroke-width': 2, 'stroke-linejoin': 'round' }));
  for (const h of F.timeline) {
    if (!ok(h.reach)) continue;
    const dot = svg('circle', { cx: c.x(h.t), cy: y(h.reach), r: 4.5, fill: COLORS[h.by], stroke: 'var(--surface-1)', 'stroke-width': 2 });
    readout(dot, box => { box.append(el('div', { class: 'muted' }, clockTenths(h.t))); tipRow(box, KIND_NAMES[h.kind], 'by ' + name(h.by) + ', ' + num(h.reach) + ' blocks', null, COLORS[h.by]); });
    c.marks.append(dot);
  }
  c.s.addEventListener('pointermove', evt => {
    const t = Math.max(0, Math.min(END, c.toTime(evt)));
    const v = ds[Math.round(t / STEP)];
    showTip(evt, box => { box.append(el('div', { class: 'muted' }, clockTenths(t) + ' · click to go there')); tipRow(box, v && ok(v[1]) ? num(v[1]) + ' blocks' : '–', 'apart'); });
  });
  c.s.addEventListener('pointerleave', hideTip);
  card.append(legend([['Hits by ' + name(0), COLORS[0]], ['Hits by ' + name(1), COLORS[1]], ['Distance', 'var(--text-secondary)', 'line'], ['First hit', 'var(--axis)', 'line']]));
  // Below the 3-block line, how long: the time each was in reach.
  const inReach = ds.filter(([, v]) => ok(v) && v <= 3).length * STEP;
  card.append(el('p', { class: 'note' }, 'In reach (3 blocks or closer) for ' + clockTenths(inReach) + ' of ' + clockTenths(known.length * STEP) + '.'));
  card.append(tableView(['Time', 'Distance (blocks)'], ds.filter((_, i) => i % 10 === 0).map(([t, v]) => [clockTenths(t), num(v)])));
})();

// Every swing: a lane per player; landed in the hit's colour, the rest gray, shaped by why.
(() => {
  const card = $('lanes');
  const swings = F.swings || F.timeline.map(h => ({ ...h, outcome: 'hit', try: null, charged: null }));
  const H = 130, lanes = [36, 82];
  const c = timeChart(card, { height: H, top: 14, bottom: 26, label: 'Swings over the fight' });
  [0, 1].forEach(i => {
    c.marks.append(svgText({ x: 0, y: lanes[i] + 4, 'font-size': 12, fill: 'var(--text-secondary)' }, name(i).length > 14 ? name(i).slice(0, 13) + '…' : name(i)));
    c.marks.append(svg('line', { x1: c.L, x2: c.W - c.R, y1: lanes[i], y2: lanes[i], stroke: 'var(--grid)' }));
  });
  const shape = (o, x, y) => {
    const gray = 'var(--muted)';
    if (o === 'early') return svg('line', { x1: x, x2: x, y1: y - 6, y2: y + 6, stroke: gray, 'stroke-width': 2 });
    if (o === 'far') return svg('circle', { cx: x, cy: y, r: 4, fill: 'none', stroke: gray, 'stroke-width': 1.5 });
    if (o === 'miss') return svg('path', { d: 'M' + (x - 4) + ' ' + (y - 4) + 'l8 8m0 -8l-8 8', stroke: gray, 'stroke-width': 1.5 });
    if (o === 'blocked') return svg('rect', { x: x - 4, y: y - 4, width: 8, height: 8, fill: gray });
    return svg('path', { d: 'M' + x + ' ' + (y - 4) + 'l4 4l-4 4l-4 -4z', fill: 'none', stroke: gray, 'stroke-width': 1 });
  };
  for (const s of swings) {
    if (s.by === null) continue;
    const x = c.x(s.t), y = lanes[s.by];
    const mark = s.outcome === 'hit'
      ? svg('circle', { cx: x, cy: y, r: 5, fill: 'var(--' + (s.kind || 'other') + ')', stroke: 'var(--surface-1)', 'stroke-width': 1.5 })
      : shape(s.outcome, x, y);
    const g = svg('g');
    g.append(mark, svg('rect', { x: x - 5, y: y - 12, width: 10, height: 24, fill: 'transparent' }));
    readout(g, box => {
      box.append(el('div', { class: 'muted' }, clockTenths(s.t) + ' · ' + name(s.by)));
      tipRow(box, s.outcome === 'hit' ? KIND_NAMES[s.kind] || 'Hit' : OUTCOME_NAMES[s.outcome], ok(s.reach) ? num(s.reach) + ' blocks' : '', null, s.outcome === 'hit' ? 'var(--' + (s.kind || 'other') + ')' : 'var(--muted)');
      if (s.try) box.append(el('div', { class: 'muted' }, TRY_NAMES[s.try] + (s.charged === false ? ', not fully charged' : s.charged ? ', fully charged' : '')));
    });
    c.marks.append(g);
  }
  const shapes = el('div', { class: 'legend' });
  for (const [o, label] of [['early', 'Too early'], ['far', 'Out of reach'], ['miss', 'Missed'], ['blocked', 'Shield'], ['use', 'Block placing or breaking']]) {
    const k = el('span', { class: 'key' });
    const icon = svg('svg', { width: 12, height: 12, viewBox: '0 0 12 12', 'aria-hidden': 'true' });
    icon.append(shape(o, 6, 6));
    k.append(icon, document.createTextNode(label));
    shapes.append(k);
  }
  card.append(kindLegend(), shapes);
  card.append(tableView(['Time', 'Who', 'Try', 'Outcome', 'Reach', 'Charged'], swings.filter(s => s.by !== null).map(s =>
    [clockTenths(s.t), name(s.by), TRY_NAMES[s.try] || '–', s.outcome === 'hit' ? KIND_NAMES[s.kind] : OUTCOME_NAMES[s.outcome], num(s.reach), s.charged === null ? '–' : s.charged ? 'yes' : 'no'])));
})();

// Health, where it's known.
(() => {
  const series = F.health.map(h => h.filter(([, v]) => ok(v)));
  if (!series.some(h => h.length)) return;
  $('health-card').hidden = false;
  const card = $('health');
  const H = 160, top = 10, bottom = 26;
  const c = timeChart(card, { height: H, top, bottom, label: 'Health over the fight' });
  const y = v => top + (H - top - bottom) * (1 - Math.min(20, v) / 20);
  for (const v of [0, 10, 20]) {
    c.marks.append(svg('line', { x1: c.L, x2: c.W - c.R, y1: y(v), y2: y(v), stroke: v === 0 ? 'var(--axis)' : 'var(--grid)' }));
    c.marks.append(svgText({ x: c.L - 8, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' }, String(v)));
  }
  const items = [];
  series.forEach((h, i) => {
    if (!h.length) return;
    let d = 'M' + c.x(h[0][0]) + ' ' + y(h[0][1]);
    for (let k = 1; k < h.length; k++) d += 'H' + c.x(h[k][0]) + 'V' + y(h[k][1]);
    d += 'H' + c.x(END);
    c.marks.append(svg('path', { d, fill: 'none', stroke: COLORS[i], 'stroke-width': 2 }));
    items.push([name(i), COLORS[i], 'line']);
  });
  card.append(legend(items));
  card.append(tableView(['Time', 'Who', 'Health'], series.flatMap((h, i) => h.map(([t, v]) => [clockTenths(t), name(i), Math.round(v * 10) / 10])).sort((a, b) => a[0] < b[0] ? -1 : 1)));
})();

// What was tried and what came of it, and the hit kinds, for this fight.
const sides = [0, 1].map(i => ({ name: name(i), color: COLORS[i], totals: attackTotals([P[i]]) }));
if (P[0].tries) {
  triesChart($('tries'), sides);
  outcomesChart($('outcomes'), sides);
} else {
  for (const id of ['tries', 'outcomes']) $(id).append(el('p', { class: 'note' }, 'Not measured for this fight: run the analysis again with --force while its recording is still there.'));
}
mixChart($('mix'), P.map((p, i) => ({ name: name(i), counts: { crit: p.crits, sprint: p.sprintHits, sweep: p.sweeps, other: Math.max(0, p.hits - p.crits - p.sprintHits - p.sweeps) } })));
(() => {
  const rows = [
    ['Hits taken', p => p.hitsTaken], ['Reach: mean / median / longest', p => p.reach ? num(p.reach.mean) + ' / ' + num(p.reach.median) + ' / ' + num(p.reach.max) : '–'],
    ['Swings (best second)', p => p.swings + ' (' + p.bestCps + ')'], ['Clicks a second', p => num(p.cps, 1)], ['Double clicks', p => p.doubleClicks],
    ['Combos of 3+', p => p.combos], ['Distance kept (median)', p => p.distance ? num(p.distance.median) : '–'],
    ['Strafing (blocks/s sideways)', p => num(p.strafeSpeed)], ['Time sprinting', p => pct(p.sprintingShare)], ['Jumps', p => p.jumps],
    ['W-taps', p => p.sprintResets], ['Shield blocks', p => p.blocked],
    ['Golden apples / potions / pearls / totems', p => [p.gapples, p.potions, p.pearls, p.totems].join(' / ')],
    ['Blocks placed', p => Object.entries(p.placed || {}).map(([b, n]) => b.replace(/_/g, ' ') + ' ' + n).join(', ') || '–'],
    ['Lowest health', p => ok(p.lowestHealth) ? Math.round(p.lowestHealth * 10) / 10 : '–'],
  ];
  const wrap = el('div', { class: 'table-wrap' });
  wrap.append(table(['', name(0), name(1)], rows.map(([label, get]) => [label, get(P[0]), get(P[1])])));
  $('everything').append(wrap);
})();
$('footer').textContent = 'Recording ' + F.recording + '. Made ' + new Date(F.generated).toLocaleString()
  + '. Positions are as the recording player\'s game saw them: other players\' are a little behind the server.';

seek(F.tracks ? Math.max(0, F.lead - 1000) : 0);
return () => {
  playing = false;
  document.removeEventListener('keydown', onKey);
  hideTip();
};
}
`;

module.exports = { fightData, FIGHT_TEMPLATE, FIGHT_CSS, FIGHT_JS };
