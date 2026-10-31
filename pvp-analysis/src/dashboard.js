// The dashboard: one self-contained HTML page (no outside scripts, works offline). The fights go in
// as JSON; the page draws its charts itself, as SVG, and re-draws them all for the server filter.
//
// Charts follow one set of rules: the recording player ("you") in the accent colour, opponents as a
// quiet gray context line; one measure per chart (small multiples, never two scales); hit kinds in
// three validated categorical colours plus gray for the rest, always labelled; hover readouts; a
// table under every chart; light and dark modes.
'use strict';

/** What the page needs of each fight, the recording player's side first. */
function fightsForPage(entries) {
  const fights = [];
  for (const e of entries) {
    e.fights.forEach((f, i) => {
      const selfIndex = f.players.findIndex(p => p.self);
      const result = selfIndex < 0 || !f.winner ? null : f.winner === f.players[selfIndex].name ? 'win' : 'loss';
      fights.push({
        id: `${e.id}-${i + 1}`,
        session: e.id,
        recording: e.file,
        server: e.meta.serverName,
        date: e.meta.date + f.startMs,
        durationMs: f.durationMs,
        seconds: f.seconds || Math.max(1, f.durationMs / 1000),
        added: e.added || null,
        result,
        selfIndex,
        players: f.players.map(p => ({
          name: p.name, hits: p.hits, crits: p.crits, sprintHits: p.sprintHits, sweeps: p.sweeps, hitsTaken: p.hitsTaken,
          reachMean: p.reach ? p.reach.mean : null, reachMedian: p.reach ? p.reach.median : null,
          bands: p.reach ? p.reach.bands : null, swings: p.swings, bestCps: p.bestCps, doubleClicks: p.doubleClicks,
          longestCombo: p.longestCombo, combos: p.combos, distance: p.distance ? p.distance.median : null,
          strafe: p.strafeSpeed, sprinting: p.sprintingShare, jumps: p.jumps, resets: p.sprintResets,
          gapples: p.gapples, potions: p.potions, pearls: p.pearls, totems: p.totems, blocked: p.blocked, placed: p.placed,
        })),
        timeline: f.timeline || [],
      });
    });
  }
  return fights.sort((a, b) => a.date - b.date);
}

function dashboard(entries, { generated = new Date() } = {}) {
  const data = { generated: generated.getTime(), recordings: entries.length, fights: fightsForPage(entries) };
  // Inside <script>, "<" could end it: JSON lets it be written as < instead.
  const json = JSON.stringify(data).replace(/</g, '\\u003c');
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PvP fight analysis</title>
<style>${CSS}</style>
</head>
<body>
<main class="viz-root">
  <header>
    <h1>PvP fight analysis</h1>
    <p class="sub" id="summary"></p>
  </header>
  <div class="filters" role="group" aria-label="Filters">
    <label>Server <select id="server"></select></label>
    <label>Points over time <select id="by"><option value="day">Days</option><option value="recording">Recordings</option></select></label>
  </div>
  <section class="tiles" id="tiles" aria-label="Headline numbers"></section>
  <section>
    <h2>Over time</h2>
    <p class="note"><span id="per">Each point is a day of fights.</span> <span class="key"><i class="line you"></i>You</span> <span class="key"><i class="line them"></i>Your opponents</span></p>
    <div class="grid" id="trends"></div>
  </section>
  <section class="two">
    <div class="card"><h2>How hits land</h2><p class="note">Share of hits by kind.</p><div id="mix"></div></div>
    <div class="card"><h2>Reach at hits</h2><p class="note">Share of hits by distance, from the attacker's eyes to the other's hitbox (3 blocks at most).</p><div id="reach"></div></div>
  </section>
  <section>
    <h2>Fights</h2>
    <p class="note">Newest first. Select a fight for its hit timeline.</p>
    <div class="table-wrap"><table id="fights"></table></div>
  </section>
  <section>
    <h2>Opponents</h2>
    <p class="note">How the players you fought fight: worth copying what works.</p>
    <div class="table-wrap"><table id="opponents"></table></div>
  </section>
  <footer class="note" id="footer"></footer>
</main>
<div class="tooltip" id="tooltip" role="status" hidden></div>
<script type="application/json" id="data">${json}</script>
<script>${JS}</script>
</body>
</html>
`;
}

const CSS = `
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10); --wash: rgba(11,11,11,0.04);
  --you: #2a78d6; --them: #a8a7a0; --crit: #2a78d6; --sprint: #eb6834; --sweep: #1baf7a; --other: #b5b4ad;
  --good: #006300; --bad: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10); --wash: rgba(255,255,255,0.05);
    --you: #3987e5; --them: #6b6a64; --crit: #3987e5; --sprint: #d95926; --sweep: #199e70; --other: #5c5b56;
    --good: #0ca30c; --bad: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10); --wash: rgba(255,255,255,0.05);
  --you: #3987e5; --them: #6b6a64; --crit: #3987e5; --sprint: #d95926; --sweep: #199e70; --other: #5c5b56;
  --good: #0ca30c; --bad: #e66767;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text-primary); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 24px; margin: 0 0 4px; font-weight: 600; }
h2 { font-size: 16px; margin: 0 0 4px; font-weight: 600; }
h3 { font-size: 13px; margin: 0 0 6px; font-weight: 600; color: var(--text-secondary); }
section { margin-top: 28px; }
.sub, .note { color: var(--text-secondary); margin: 0 0 12px; }
.note { font-size: 13px; }
.filters { display: flex; gap: 16px; margin-top: 16px; align-items: center; flex-wrap: wrap; }
select { font: inherit; color: var(--text-primary); background: var(--surface-1); border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; margin-left: 6px; }
.card, .tile, .chart { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.tile .label { color: var(--text-secondary); font-size: 13px; }
.tile .value { font-size: 26px; font-weight: 600; margin: 2px 0; }
.tile .delta { font-size: 12px; color: var(--text-secondary); }
.tile .delta.up { color: var(--good); } .tile .delta.down { color: var(--bad); }
.tile svg { display: block; margin-top: 6px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
.chart svg, .card svg { display: block; width: 100%; height: auto; overflow: visible; }
.key { display: inline-flex; align-items: center; gap: 6px; margin-left: 12px; color: var(--text-secondary); }
.key i, .tt-key { display: inline-block; width: 14px; height: 2px; border-radius: 1px; }
.key i.dot { width: 10px; height: 10px; border-radius: 3px; }
.line.you, .tt-key.you { background: var(--you); } .line.them, .tt-key.them { background: var(--them); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 8px 0 0; font-size: 13px; color: var(--text-secondary); }
details { margin-top: 8px; font-size: 13px; color: var(--text-secondary); }
summary { cursor: pointer; }
.table-wrap { overflow-x: auto; background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--grid); white-space: nowrap; font-variant-numeric: tabular-nums; }
th:first-child, td:first-child, th.l, td.l { text-align: left; }
th { color: var(--text-secondary); font-weight: 600; }
tbody tr.fight { cursor: pointer; }
tbody tr.fight:hover, tbody tr.fight:focus { background: var(--wash); outline: none; }
tr.detail > td { text-align: left; white-space: normal; padding: 12px; }
tr.detail table { width: auto; min-width: 50%; margin-top: 6px; }
.result { display: inline-flex; align-items: center; gap: 4px; }
.chip { display: inline-block; font-size: 11px; line-height: 16px; padding: 0 6px; border-radius: 8px; border: 1px solid var(--border); color: var(--text-secondary); }
.result.win { color: var(--good); } .result.loss { color: var(--bad); }
.tooltip { position: fixed; pointer-events: none; z-index: 10; background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.15); max-width: 260px; }
.tooltip .row { display: flex; align-items: center; gap: 6px; }
.tooltip strong { font-weight: 600; }
.tooltip .muted { color: var(--text-secondary); }
footer.note { margin-top: 32px; }
.timeline { width: 100%; max-width: 900px; }
.empty { color: var(--text-secondary); padding: 12px 0; }
@media (max-width: 520px) { main { padding: 16px 16px 40px; } .tile .value { font-size: 22px; } }
`;

// The page's own script (plain JavaScript, run in the browser).
const JS = String.raw`
'use strict';
const DATA = JSON.parse(document.getElementById('data').textContent);
const SVG = 'http://www.w3.org/2000/svg';
const KINDS = [['crit', 'Crits'], ['sprint', 'Sprint hits'], ['sweep', 'Sweeps'], ['other', 'Other hits']];
const BAND_LABELS = ['under 2', '2–2.5', '2.5–2.75', '2.75–3', '3+'];
const tooltip = document.getElementById('tooltip');

const el = (tag, attrs = {}, text) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
};
const svg = (tag, attrs = {}) => {
  const n = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  return n;
};
const pct = v => v === null || !isFinite(v) ? '–' : Math.round(v * 100) + '%';
const num = (v, d = 2) => v === null || !isFinite(v) ? '–' : v.toFixed(d);
const day = ms => { const d = new Date(ms); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
const shortDay = key => { const [, m, d] = key.split('-'); return Number(m) + '/' + Number(d); };
const clock = ms => Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0');
const when = ms => new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

function showTip(evt, build) {
  tooltip.replaceChildren();
  build(tooltip);
  tooltip.hidden = false;
  const r = tooltip.getBoundingClientRect();
  let x = evt.clientX + 14, y = evt.clientY + 14;
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - 14;
  tooltip.style.left = Math.max(8, x) + 'px';
  tooltip.style.top = Math.max(8, y) + 'px';
}
const hideTip = () => { tooltip.hidden = true; };
const tipRow = (box, value, label, keyClass, style) => {
  const row = el('div', { class: 'row' });
  if (keyClass || style) { const k = el('i', { class: 'tt-key ' + (keyClass || '') }); if (style) k.style.background = style; row.append(k); }
  row.append(el('strong', {}, value), el('span', { class: 'muted' }, label));
  box.append(row);
};

// ---------------------------------------------------------------- numbers over a set of fights

/** Totals for one side ('you', or 'them': your opponents) over some fights. */
function totals(fights, side) {
  const t = { fights: fights.length, hits: 0, crits: 0, sprint: 0, sweeps: 0, taken: 0, swings: 0, seconds: 0, resets: 0,
    reachSum: 0, reachHits: 0, wins: 0, losses: 0, combo: 0 };
  for (const f of fights) {
    const p = f.players[side === 'you' ? f.selfIndex : 1 - f.selfIndex];
    t.hits += p.hits; t.crits += p.crits; t.sprint += p.sprintHits; t.sweeps += p.sweeps; t.taken += p.hitsTaken;
    t.swings += p.swings; t.seconds += f.seconds; t.resets += p.resets; t.combo = Math.max(t.combo, p.longestCombo);
    if (p.reachMean !== null) { t.reachSum += p.reachMean * p.hits; t.reachHits += p.hits; }
    if (f.result === (side === 'you' ? 'win' : 'loss')) t.wins++;
    if (f.result === (side === 'you' ? 'loss' : 'win')) t.losses++;
  }
  const share = n => t.hits ? n / t.hits : null;
  return { ...t, critShare: share(t.crits), sprintShare: share(t.sprint), sweepShare: share(t.sweeps),
    reach: t.reachHits ? t.reachSum / t.reachHits : null, accuracy: t.swings ? t.hits / t.swings : null,
    cps: t.seconds ? t.swings / t.seconds : null, resetsPerMin: t.seconds ? t.resets / (t.seconds / 60) : null,
    hitRatio: t.taken ? t.hits / t.taken : null,
    winRate: t.wins + t.losses ? t.wins / (t.wins + t.losses) : null };
}

/** Fights grouped by day, or by recording (a session), oldest first: [{ key, tick, title, fights }]. */
function groupsOf(fights, by) {
  const groups = new Map();
  for (const f of fights) {
    const k = by === 'recording' ? f.session : day(f.date);
    if (!groups.has(k)) groups.set(k, { key: k, fights: [] });
    groups.get(k).fights.push(f);
  }
  return [...groups.values()].map(g => {
    const first = g.fights[0].date;
    const time = new Date(first).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    return by === 'recording'
      ? { ...g, tick: shortDay(day(first)) + ' ' + time, title: day(first) + ' ' + time + ' (' + g.fights[0].server + ')' }
      : { ...g, tick: shortDay(g.key), title: g.key };
  });
}
const byDay = fights => groupsOf(fights, 'day');

const METRICS = [
  { key: 'critShare', label: 'Crits', note: 'share of hits', fmt: pct, good: 'up' },
  { key: 'sprintShare', label: 'Sprint hits', note: 'share of hits', fmt: pct, good: 'up' },
  { key: 'sweepShare', label: 'Sweeps', note: 'share of hits: standing hits', fmt: pct, good: 'down' },
  { key: 'accuracy', label: 'Swings that hit', note: 'hits ÷ swings', fmt: pct, good: 'up' },
  { key: 'reach', label: 'Mean reach', note: 'blocks, at hits', fmt: v => num(v), good: null },
  { key: 'cps', label: 'CPS', note: 'swings a second, in fights', fmt: v => num(v, 1), good: null },
  { key: 'resetsPerMin', label: 'W-taps', note: 'sprint resets a minute', fmt: v => num(v, 1), good: 'up' },
  { key: 'hitRatio', label: 'Hits landed ÷ taken', note: 'over 1: you out-hit them', fmt: v => num(v), good: 'up' },
];

// ---------------------------------------------------------------- charts

/** A small line chart of one measure over days (or recordings): you, and your opponents behind in gray. */
function trendChart(container, metric, days) {
  const W = 300, H = 150, L = 36, R = 10, T = 10, B = 24;
  const you = days.map(d => totals(d.fights, 'you')[metric.key]);
  const them = days.map(d => totals(d.fights, 'them')[metric.key]);
  const values = [...you, ...them].filter(v => v !== null && isFinite(v));
  const card = el('div', { class: 'chart' });
  card.append(el('h3', {}, metric.label), el('div', { class: 'note' }, metric.note));
  container.append(card);
  if (!values.length) { card.append(el('div', { class: 'empty' }, 'No data yet.')); return; }
  let lo = Math.min(0, ...values), hi = Math.max(...values);
  if (metric.fmt === pct) { lo = 0; hi = Math.max(hi, 0.1); }
  if (hi === lo) hi = lo + 1;
  hi = niceMax(hi);
  const x = i => days.length === 1 ? L + (W - L - R) / 2 : L + i * (W - L - R) / (days.length - 1);
  const y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': metric.label + ' over time' });
  for (const v of [lo, (lo + hi) / 2, hi]) {
    s.append(svg('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: 'var(--grid)', 'stroke-width': 1 }));
    const t = svg('text', { x: L - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 10, fill: 'var(--muted)' });
    t.textContent = metric.fmt === pct ? pct(v) : String(+v.toFixed(2));
    s.append(t);
  }
  const room = Math.floor((W - L - R) / (days[0].tick.length * 6 + 8));
  const ticks = days.length <= room ? days.map((_, i) => i) : days.length === 1 ? [0] : [0, days.length - 1];
  for (const i of ticks) {
    const anchor = days.length > 1 && i === 0 ? 'start' : days.length > 1 && i === days.length - 1 ? 'end' : 'middle';
    const t = svg('text', { x: x(i) + (anchor === 'start' ? -4 : anchor === 'end' ? 4 : 0), y: H - 6, 'text-anchor': anchor, 'font-size': 10, fill: 'var(--muted)' });
    t.textContent = days[i].tick;
    s.append(t);
  }
  const path = (vals, color) => {
    let d = '';
    vals.forEach((v, i) => { if (v === null || !isFinite(v)) return; d += (d ? 'L' : 'M') + x(i) + ' ' + y(v); });
    if (d) s.append(svg('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    vals.forEach((v, i) => { if (v !== null && isFinite(v)) s.append(svg('circle', { cx: x(i), cy: y(v), r: 4, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2 })); });
  };
  path(them, 'var(--them)');
  path(you, 'var(--you)');
  // End label: your latest value.
  const last = you.map((v, i) => [v, i]).filter(([v]) => v !== null && isFinite(v)).pop();
  if (last) {
    const t = svg('text', { x: Math.min(x(last[1]) + 6, W - R), y: y(last[0]) - 8, 'font-size': 11, 'font-weight': 600, fill: 'var(--text-primary)', 'text-anchor': days.length === 1 ? 'middle' : 'end' });
    t.textContent = metric.fmt(last[0]);
    s.append(t);
  }
  // Crosshair readout: the nearest day, both lines.
  const cross = svg('line', { y1: T, y2: H - B, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden' });
  s.append(cross);
  const hit = svg('rect', { x: L - 10, y: 0, width: W - L - R + 20, height: H, fill: 'transparent', tabindex: 0 });
  const nearest = evt => {
    const p = s.getBoundingClientRect();
    const px = (evt.clientX - p.left) / p.width * W;
    let best = 0;
    days.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i; });
    return best;
  };
  const show = (evt, i) => {
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
    showTip(evt, box => {
      box.append(el('div', { class: 'muted' }, days[i].title + ' · ' + days[i].fights.length + ' fight' + (days[i].fights.length === 1 ? '' : 's')));
      tipRow(box, metric.fmt(you[i]), 'You', 'you');
      tipRow(box, metric.fmt(them[i]), 'Opponents', 'them');
    });
  };
  hit.addEventListener('pointermove', evt => show(evt, nearest(evt)));
  hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
  hit.addEventListener('focus', () => { const r = s.getBoundingClientRect(); show({ clientX: r.right, clientY: r.top }, days.length - 1); });
  hit.addEventListener('blur', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
  s.append(hit);
  card.append(s);
  card.append(tableView(['When', 'Fights', 'You', 'Opponents'], days.map((d, i) => [d.title, d.fights.length, metric.fmt(you[i]), metric.fmt(them[i])])));
}

function niceMax(v) {
  if (v <= 1 && v > 0.1) return Math.ceil(v * 10) / 10;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

function tableView(head, rows) {
  const d = el('details');
  d.append(el('summary', {}, 'Show as a table'));
  const t = el('table');
  const tr = el('tr');
  head.forEach((h, i) => tr.append(el('th', i === 0 ? { class: 'l' } : {}, h)));
  t.append(el('thead'));
  t.firstChild.append(tr);
  const body = el('tbody');
  for (const r of rows) { const row = el('tr'); r.forEach((c, i) => row.append(el('td', i === 0 ? { class: 'l' } : {}, String(c)))); body.append(row); }
  t.append(body);
  d.append(t);
  return d;
}

/** Hit kinds as a 100% bar each, for you and your opponents, labelled where they fit. */
function mixChart(container, fights) {
  const rows = [['You', totals(fights, 'you')], ['Opponents', totals(fights, 'them')]];
  const W = 480, rowH = 28, gap = 14, L = 84, T = 4;
  const H = T + rows.length * (rowH + gap);
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Hits by kind' });
  rows.forEach(([name, t], r) => {
    const yy = T + r * (rowH + gap);
    const label = svg('text', { x: 0, y: yy + rowH / 2 + 4, 'font-size': 12, fill: 'var(--text-secondary)' });
    label.textContent = name + (t.hits ? '' : ' (no hits)');
    s.append(label);
    if (!t.hits) return;
    const counts = { crit: t.crits, sprint: t.sprint, sweep: t.sweeps, other: Math.max(0, t.hits - t.crits - t.sprint - t.sweeps) };
    let xx = L;
    const width = W - L;
    for (const [kind, kindLabel] of KINDS) {
      const w = counts[kind] / t.hits * width;
      if (w <= 0) continue;
      const seg = svg('rect', { x: xx, y: yy, width: Math.max(0, w - 2), height: rowH, rx: 4, fill: 'var(--' + kind + ')', tabindex: 0 });
      const share = Math.round(counts[kind] / t.hits * 100) + '%';
      const tip = evt => showTip(evt, box => { tipRow(box, share + ' (' + counts[kind] + ')', name + ': ' + kindLabel.toLowerCase(), null, 'var(--' + kind + ')'); });
      seg.addEventListener('pointermove', tip);
      seg.addEventListener('pointerleave', hideTip);
      seg.addEventListener('focus', () => { const r2 = seg.getBoundingClientRect(); tip({ clientX: r2.left, clientY: r2.bottom }); });
      seg.addEventListener('blur', hideTip);
      s.append(seg);
      if (w > 40) {
        const t2 = svg('text', { x: xx + 8, y: yy + rowH / 2 + 4, 'font-size': 12, 'font-weight': 600, fill: '#0b0b0b', 'pointer-events': 'none' });
        t2.textContent = share;
        s.append(t2);
      }
      xx += w;
    }
  });
  container.append(s);
  const legend = el('div', { class: 'legend' });
  for (const [kind, label] of KINDS) { const k = el('span', { class: 'key' }); const i = el('i', { class: 'dot' }); i.style.background = 'var(--' + kind + ')'; k.append(i, document.createTextNode(label)); legend.append(k); }
  container.append(legend);
  container.append(tableView(['', 'Hits', 'Crits', 'Sprint hits', 'Sweeps', 'Other'], rows.map(([n, t]) =>
    [n, t.hits, t.crits, t.sprint, t.sweeps, Math.max(0, t.hits - t.crits - t.sprint - t.sweeps)])));
}

/** Reach bands: share of each side's hits, side by side. */
function reachChart(container, fights) {
  const sides = [['You', 'you', 'var(--you)'], ['Opponents', 'them', 'var(--them)']];
  const counts = sides.map(([, side]) => {
    const c = BAND_LABELS.map(() => 0);
    for (const f of fights) {
      const p = f.players[side === 'you' ? f.selfIndex : 1 - f.selfIndex];
      if (p.bands) p.bands.forEach(([, n], i) => { c[i] += n; });
    }
    return c;
  });
  const shares = counts.map(c => { const n = c.reduce((a, b) => a + b, 0); return c.map(v => n ? v / n : 0); });
  const W = 480, H = 170, L = 34, B = 24, T = 10, R = 4;
  const hi = niceMax(Math.max(0.1, ...shares.flat()));
  const band = (W - L - R) / BAND_LABELS.length;
  const bw = Math.min(24, band / 3);
  const y = v => T + (H - T - B) * (1 - v / hi);
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Hits by reach' });
  for (const v of [0, hi / 2, hi]) {
    s.append(svg('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: v === 0 ? 'var(--axis)' : 'var(--grid)', 'stroke-width': 1 }));
    const t = svg('text', { x: L - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 10, fill: 'var(--muted)' });
    t.textContent = pct(v);
    s.append(t);
  }
  BAND_LABELS.forEach((label, i) => {
    const cx = L + band * i + band / 2;
    const t = svg('text', { x: cx, y: H - 6, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--muted)' });
    t.textContent = label;
    s.append(t);
    sides.forEach(([name, , color], k) => {
      const v = shares[k][i];
      const x0 = cx - bw - 1 + k * (bw + 2);
      const h = Math.max(0, y(0) - y(v));
      // A column with a rounded top and a square foot.
      const r = Math.min(4, h / 2, bw / 2);
      const d = 'M' + x0 + ' ' + y(0) + 'V' + (y(v) + r) + 'Q' + x0 + ' ' + y(v) + ' ' + (x0 + r) + ' ' + y(v) + 'H' + (x0 + bw - r) + 'Q' + (x0 + bw) + ' ' + y(v) + ' ' + (x0 + bw) + ' ' + (y(v) + r) + 'V' + y(0) + 'Z';
      if (h > 0) s.append(svg('path', { d, fill: color }));
      const hit = svg('rect', { x: x0 - 2, y: T, width: bw + 4, height: H - T - B, fill: 'transparent', tabindex: 0 });
      const tip = evt => showTip(evt, box => { box.append(el('div', { class: 'muted' }, label + ' blocks')); tipRow(box, pct(v) + ' (' + counts[k][i] + ')', name, k ? 'them' : 'you'); });
      hit.addEventListener('pointermove', tip);
      hit.addEventListener('pointerleave', hideTip);
      hit.addEventListener('focus', () => { const r2 = hit.getBoundingClientRect(); tip({ clientX: r2.right, clientY: r2.top }); });
      hit.addEventListener('blur', hideTip);
      s.append(hit);
    });
  });
  container.append(s);
  const legend = el('div', { class: 'legend' });
  sides.forEach(([name, side]) => { const k = el('span', { class: 'key' }); k.append(el('i', { class: 'dot line ' + side }), document.createTextNode(name)); legend.append(k); });
  container.append(legend);
  container.append(tableView(['Reach (blocks)', 'You', 'Opponents'], BAND_LABELS.map((b, i) => [b, pct(shares[0][i]) + ' (' + counts[0][i] + ')', pct(shares[1][i]) + ' (' + counts[1][i] + ')'])));
}

/** A fight's hits along its length: yours above, theirs below, coloured by kind. */
function timelineChart(f) {
  const W = 900, H = 96, L = 110, R = 12, lane = [26, 62];
  const end = Math.max(1000, f.durationMs);
  const x = t => L + (W - L - R) * t / end;
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'timeline', role: 'img', 'aria-label': 'Hits over the fight' });
  [0, 1].forEach(side => {
    const who = f.players[side === 0 ? f.selfIndex >= 0 ? f.selfIndex : 0 : f.selfIndex >= 0 ? 1 - f.selfIndex : 1];
    const t = svg('text', { x: 0, y: lane[side] + 4, 'font-size': 12, fill: 'var(--text-secondary)' });
    t.textContent = who.name.length > 14 ? who.name.slice(0, 13) + '…' : who.name;
    s.append(t);
    s.append(svg('line', { x1: L, x2: W - R, y1: lane[side], y2: lane[side], stroke: 'var(--grid)', 'stroke-width': 1 }));
  });
  for (const v of [0, end / 2, end]) {
    const t = svg('text', { x: x(v), y: H - 4, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--muted)' });
    t.textContent = clock(v);
    s.append(t);
  }
  const selfFirst = f.selfIndex >= 0 ? f.selfIndex : 0;
  for (const h of f.timeline) {
    const side = h.by === selfFirst ? 0 : 1;
    const c = svg('circle', { cx: x(h.t), cy: lane[side], r: 5, fill: 'var(--' + h.kind + ')', stroke: 'var(--surface-1)', 'stroke-width': 2 });
    const hit = svg('circle', { cx: x(h.t), cy: lane[side], r: 12, fill: 'transparent' });
    const name = f.players[h.by].name;
    hit.addEventListener('pointermove', evt => showTip(evt, box => {
      box.append(el('div', { class: 'muted' }, clock(h.t) + ' · ' + name));
      tipRow(box, (KINDS.find(k => k[0] === h.kind) || [, h.kind])[1], h.reach === null ? '' : num(h.reach) + ' blocks', null, 'var(--' + h.kind + ')');
    }));
    hit.addEventListener('pointerleave', hideTip);
    s.append(c, hit);
  }
  return s;
}

// ---------------------------------------------------------------- the page

const fmtResult = r => r === 'win' ? '✓ Won' : r === 'loss' ? '✗ Lost' : '–';

function render() {
  const server = document.getElementById('server').value;
  const all = DATA.fights.filter(f => server === 'all' || f.server === server);
  const mine = all.filter(f => f.selfIndex >= 0);
  const by = document.getElementById('by').value;
  const range = byDay(mine);
  const days = groupsOf(mine, by);
  const before = by === 'day' ? 'the day before' : 'the recording before';
  document.getElementById('per').textContent = by === 'day' ? 'Each point is a day of fights.' : 'Each point is a recording: a session of fights.';
  const you = totals(mine, 'you');
  const servers = [...new Set(all.map(f => f.server))];
  document.getElementById('summary').textContent = mine.length + ' fight' + (mine.length === 1 ? '' : 's') + ' of yours in '
    + DATA.recordings + ' recording' + (DATA.recordings === 1 ? '' : 's') + (!range.length ? '' : range.length === 1 ? ', on ' + range[0].key : ', ' + range[0].key + ' to ' + range[range.length - 1].key)
    + ' · ' + servers.join(', ');
  const fresh = mine.filter(f => f.added === DATA.generated).length;
  if (fresh) document.getElementById('summary').textContent += ' · ' + fresh + ' new this run';

  // Headline tiles: the number over everything, then the latest day (or recording) against the one before.
  const tiles = document.getElementById('tiles');
  tiles.replaceChildren();
  const tile = (label, value, metric) => {
    const t = el('div', { class: 'tile' });
    t.append(el('div', { class: 'label' }, label), el('div', { class: 'value' }, value));
    if (metric && days.length >= 2) {
      const a = totals(days[days.length - 2].fights, 'you')[metric.key];
      const b = totals(days[days.length - 1].fights, 'you')[metric.key];
      if (a !== null && b !== null && isFinite(a) && isFinite(b)) {
        const diff = b - a;
        const better = metric.good === null ? null : (metric.good === 'up') === (diff > 0);
        const d = el('div', { class: 'delta' + (better === null || Math.abs(diff) < 1e-9 ? '' : better ? ' up' : ' down') },
          (diff >= 0 ? '▲ ' : '▼ ') + metric.fmt(Math.abs(diff)) + ' on ' + before);
        t.append(d);
      }
    }
    if (metric && days.length >= 2) t.append(sparkline(days.map(d => totals(d.fights, 'you')[metric.key])));
    tiles.append(t);
  };
  tile('Fights', String(mine.length), null);
  const decided = you.wins + you.losses;
  tile('Won', decided ? you.wins + ' of ' + decided : '–', null);
  for (const key of ['critShare', 'sweepShare', 'accuracy', 'hitRatio']) {
    const m = METRICS.find(x => x.key === key);
    tile(m.label, m.fmt(you[key]), m);
  }

  const trends = document.getElementById('trends');
  trends.replaceChildren();
  if (!days.length) trends.append(el('div', { class: 'empty' }, 'No fights of yours here yet.'));
  else for (const m of METRICS) trendChart(trends, m, days);

  const mix = document.getElementById('mix');
  mix.replaceChildren();
  mixChart(mix, mine);
  const reach = document.getElementById('reach');
  reach.replaceChildren();
  reachChart(reach, mine);

  fightsTable(all);
  opponentsTable(mine);
  document.getElementById('footer').textContent = 'Made ' + new Date(DATA.generated).toLocaleString() + ' from the recordings analysed so far. '
    + 'Positions are as the recording player\'s game saw them: other players\' are a little behind the server.';
}

function sparkline(values) {
  const W = 120, H = 26;
  const v = values.map(a => a === null || !isFinite(a) ? null : a);
  const ok = v.filter(a => a !== null);
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, 'aria-hidden': 'true' });
  if (ok.length < 2) return s;
  const lo = Math.min(...ok), hi = Math.max(...ok) === lo ? lo + 1 : Math.max(...ok);
  const x = i => 4 + i * (W - 8) / (v.length - 1);
  const y = a => 4 + (H - 8) * (1 - (a - lo) / (hi - lo));
  let d = '';
  v.forEach((a, i) => { if (a !== null) d += (d ? 'L' : 'M') + x(i) + ' ' + y(a); });
  s.append(svg('path', { d, fill: 'none', stroke: 'var(--them)', 'stroke-width': 2, 'stroke-linejoin': 'round' }));
  const last = v.length - 1;
  if (v[last] !== null) s.append(svg('circle', { cx: x(last), cy: y(v[last]), r: 3, fill: 'var(--you)' }));
  return s;
}

function fightsTable(fights) {
  const t = document.getElementById('fights');
  t.replaceChildren();
  const head = ['When', 'Server', 'Opponent', 'Result', 'Length', 'Hits', 'Taken', 'Crits', 'Sweeps', 'Reach', 'Accuracy', 'Best combo'];
  const tr = el('tr');
  const explain = { Hits: 'Hits you landed', Taken: 'Hits you took', Reach: 'Median reach of your hits, in blocks', Accuracy: 'Your hits ÷ your swings', 'Best combo': 'Most hits in a row without being hit back' };
  head.forEach((h, i) => tr.append(el('th', { ...(i < 3 ? { class: 'l' } : {}), ...(explain[h] ? { title: explain[h] } : {}) }, h)));
  t.append(el('thead'));
  t.firstChild.append(tr);
  const body = el('tbody');
  for (const f of [...fights].reverse()) {
    const me = f.players[f.selfIndex >= 0 ? f.selfIndex : 0];
    const them = f.players[f.selfIndex >= 0 ? 1 - f.selfIndex : 1];
    const row = el('tr', { class: 'fight', tabindex: 0, 'aria-expanded': 'false' });
    const cells = [when(f.date), f.server, f.selfIndex >= 0 ? them.name : me.name + ' vs ' + them.name + ' (watched)'];
    cells.forEach(c => row.append(el('td', { class: 'l' }, c)));
    if (f.added === DATA.generated) row.firstChild.append(' ', el('span', { class: 'chip' }, 'new'));
    const res = el('td');
    res.append(el('span', { class: 'result ' + (f.result || '') }, fmtResult(f.result)));
    row.append(res);
    for (const c of [clock(f.durationMs), me.hits, them.hits, me.crits, me.sweeps, num(me.reachMedian), pct(me.swings ? me.hits / me.swings : null), me.longestCombo]) {
      row.append(el('td', {}, String(c)));
    }
    const detail = el('tr', { class: 'detail', hidden: '' });
    const cell = el('td', { colspan: head.length });
    detail.append(cell);
    const toggle = () => {
      const open = detail.hidden;
      detail.hidden = !open;
      row.setAttribute('aria-expanded', String(open));
      if (open && !cell.firstChild) {
        cell.append(timelineChart(f));
        const legend = el('div', { class: 'legend' });
        for (const [kind, label] of KINDS) { const k = el('span', { class: 'key' }); const i = el('i', { class: 'dot' }); i.style.background = 'var(--' + kind + ')'; k.append(i, document.createTextNode(label)); legend.append(k); }
        cell.append(legend);
        cell.append(fightDetails(f, me, them));
      }
    };
    row.addEventListener('click', toggle);
    row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    body.append(row, detail);
  }
  if (!fights.length) { const r = el('tr'); r.append(el('td', { colspan: head.length, class: 'l' }, 'No fights yet.')); body.append(r); }
  t.append(body);
}

/** Everything else measured in a fight, both sides. */
function fightDetails(f, me, them) {
  const rows = [
    ['Sprint hits', p => p.sprintHits], ['Hits taken', p => p.hitsTaken], ['Reach: mean / median', p => num(p.reachMean) + ' / ' + num(p.reachMedian)],
    ['Swings (best second)', p => p.swings + ' (' + p.bestCps + ')'], ['Double clicks', p => p.doubleClicks], ['Combos of 3+', p => p.combos],
    ['Distance kept (median)', p => num(p.distance)], ['Strafing (blocks/s sideways)', p => num(p.strafe)], ['Time sprinting', p => pct(p.sprinting)],
    ['Jumps', p => p.jumps], ['W-taps', p => p.resets], ['Shield blocks', p => p.blocked],
    ['Golden apples / potions / pearls / totems', p => p.gapples + ' / ' + p.potions + ' / ' + p.pearls + ' / ' + p.totems],
    ['Blocks placed', p => Object.entries(p.placed || {}).map(([b, n]) => b + ' ' + n).join(', ') || '–'],
  ];
  const d = el('details');
  d.append(el('summary', {}, 'Everything measured'));
  const t = el('table');
  const tr = el('tr');
  tr.append(el('th', { class: 'l' }, ''), el('th', {}, me.name), el('th', {}, them.name));
  t.append(el('thead'));
  t.firstChild.append(tr);
  const body = el('tbody');
  for (const [label, get] of rows) { const r = el('tr'); r.append(el('td', { class: 'l' }, label), el('td', {}, String(get(me))), el('td', {}, String(get(them)))); body.append(r); }
  t.append(body);
  d.append(t);
  d.append(el('div', { class: 'note' }, 'Recording: ' + f.recording));
  return d;
}

function opponentsTable(fights) {
  const by = new Map();
  for (const f of fights) {
    const p = f.players[1 - f.selfIndex];
    if (!by.has(p.name)) by.set(p.name, []);
    by.get(p.name).push(f);
  }
  const t = document.getElementById('opponents');
  t.replaceChildren();
  const head = ['Opponent', 'Fights', 'You won', 'Their hits', 'Crits', 'Sprint hits', 'Sweeps', 'Mean reach', 'Swings that hit', 'W-taps a minute', 'Longest combo'];
  const tr = el('tr');
  head.forEach((h, i) => tr.append(el('th', i === 0 ? { class: 'l' } : {}, h)));
  t.append(el('thead'));
  t.firstChild.append(tr);
  const body = el('tbody');
  const rows = [...by.entries()].map(([name, fs]) => [name, fs, totals(fs, 'them')]).sort((a, b) => b[1].length - a[1].length);
  for (const [name, fs, o] of rows) {
    const r = el('tr');
    const wins = fs.filter(f => f.result === 'win').length, decided = fs.filter(f => f.result).length;
    for (const [i, c] of [name, fs.length, decided ? wins + ' of ' + decided : '–', o.hits, pct(o.critShare), pct(o.sprintShare), pct(o.sweepShare), num(o.reach), pct(o.accuracy), num(o.resetsPerMin, 1), o.combo].entries()) {
      r.append(el('td', i === 0 ? { class: 'l' } : {}, String(c)));
    }
    body.append(r);
  }
  if (!rows.length) { const r = el('tr'); r.append(el('td', { colspan: head.length, class: 'l' }, 'No opponents yet.')); body.append(r); }
  t.append(body);
}

// Points over time: days once there are a few of them, recordings till then (or as last chosen).
const grouping = document.getElementById('by');
grouping.value = new Set(DATA.fights.map(f => day(f.date))).size >= 3 ? 'day' : 'recording';
try { const saved = localStorage.getItem('pvp-analysis-by'); if (saved === 'day' || saved === 'recording') grouping.value = saved; } catch (e) {}
grouping.addEventListener('change', () => { try { localStorage.setItem('pvp-analysis-by', grouping.value); } catch (e) {} render(); });
const select = document.getElementById('server');
select.append(el('option', { value: 'all' }, 'All servers'));
for (const s of [...new Set(DATA.fights.map(f => f.server))]) select.append(el('option', { value: s }, s));
try { const saved = localStorage.getItem('pvp-analysis-server'); if (saved && [...select.options].some(o => o.value === saved)) select.value = saved; } catch (e) {}
select.addEventListener('change', () => { try { localStorage.setItem('pvp-analysis-server', select.value); } catch (e) {} render(); });
render();
`;

module.exports = { dashboard, fightsForPage };
