// What the dashboard's pages share: the page itself (one self-contained HTML file: no outside
// scripts, works offline), the colours and type, and the script helpers and charts both use.
//
// Charts follow one set of rules: the recording player ("you") in the accent colour, opponents in
// a quiet gray; one measure per chart (never two scales); hit kinds in three validated categorical
// colours plus gray for the rest, always with a legend; hover readouts; a table under every chart;
// light and dark modes.
'use strict';

/** Data in a page, as JSON (with "<" escaped, so nothing in it can end the script). */
function jsonScript(id, data) {
  return `<script type="application/json" id="${id}">${JSON.stringify(data).replace(/</g, '\\u003c')}</script>`;
}

/** A page: its body, more CSS, more in the page (data, templates), its data and its script. */
function htmlPage({ title, body, css = '', extra = '', data, script }) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>${CSS}${css}</style>
</head>
<body>
${body}
${extra}
<div class="tooltip" id="tooltip" role="status" hidden></div>
${jsonScript('data', data)}
<script>${COMMON_JS}${script}</script>
</body>
</html>
`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

const TOKENS_LIGHT = `
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10); --wash: rgba(11,11,11,0.04);
  --you: #2a78d6; --them: #a8a7a0; --them-strong: #6b6a64; --crit: #2a78d6; --sprint: #eb6834; --sweep: #1baf7a; --other: #b5b4ad;
  --good: #006300; --bad: #d03b3b; --map: #f3f3ef;`;
const TOKENS_DARK = `
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10); --wash: rgba(255,255,255,0.05);
  --you: #3987e5; --them: #6b6a64; --them-strong: #a8a7a0; --crit: #3987e5; --sprint: #d95926; --sweep: #199e70; --other: #5c5b56;
  --good: #0ca30c; --bad: #e66767; --map: #141413;`;

const CSS = `
:root {${TOKENS_LIGHT}
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {${TOKENS_DARK}
  }
}
:root[data-theme="dark"] {${TOKENS_DARK}
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text-primary); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 24px 16px 48px; }
a { color: var(--you); }
h1 { font-size: 24px; margin: 0 0 4px; font-weight: 600; }
h2 { font-size: 16px; margin: 0 0 4px; font-weight: 600; }
h3 { font-size: 13px; margin: 0 0 6px; font-weight: 600; color: var(--text-secondary); }
section { margin-top: 28px; }
.sub, .note { color: var(--text-secondary); margin: 0 0 12px; }
.note { font-size: 13px; }
.filters { display: flex; gap: 16px; margin-top: 16px; align-items: center; flex-wrap: wrap; }
select, button { font: inherit; color: var(--text-primary); background: var(--surface-1); border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; }
label select { margin-left: 6px; }
button { cursor: pointer; }
button:hover { background: var(--wash); }
.card, .tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }
.tile .label { color: var(--text-secondary); font-size: 13px; }
.tile .value { font-size: 26px; font-weight: 600; margin: 2px 0; }
.tile .delta { font-size: 12px; color: var(--text-secondary); }
.tile .delta.up { color: var(--good); } .tile .delta.down { color: var(--bad); }
.tile svg { display: block; margin-top: 6px; }
.two { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px; }
.card svg { display: block; width: 100%; height: auto; overflow: visible; }
.key { display: inline-flex; align-items: center; gap: 6px; margin-right: 12px; color: var(--text-secondary); }
.key i, .tt-key { display: inline-block; width: 14px; height: 2px; border-radius: 1px; flex: none; }
.key i.dot, .tt-key.dot { width: 10px; height: 10px; border-radius: 3px; }
.you-bg { background: var(--you); } .them-bg { background: var(--them); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 2px; margin: 8px 0 0; font-size: 13px; color: var(--text-secondary); align-items: center; }
details { margin-top: 8px; font-size: 13px; color: var(--text-secondary); }
summary { cursor: pointer; }
.table-wrap { overflow-x: auto; background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--grid); white-space: nowrap; font-variant-numeric: tabular-nums; }
th:first-child, td:first-child, th.l, td.l { text-align: left; }
th { color: var(--text-secondary); font-weight: 600; }
.result { display: inline-flex; align-items: center; gap: 4px; }
.result.win { color: var(--good); } .result.loss { color: var(--bad); }
.chip { display: inline-block; font-size: 11px; line-height: 16px; padding: 0 6px; border-radius: 8px; border: 1px solid var(--border); color: var(--text-secondary); }
.tooltip { position: fixed; pointer-events: none; z-index: 10; background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.15); max-width: 280px; }
.tooltip .row { display: flex; align-items: center; gap: 6px; }
.tooltip strong { font-weight: 600; }
.tooltip .muted { color: var(--text-secondary); }
.empty { color: var(--text-secondary); padding: 12px 0; }
/* Charts along time: on a narrow screen, scroll sideways rather than shrink past reading. */
.wide { overflow-x: auto; }
@media (max-width: 760px) { .wide > svg { min-width: 720px; } }
.tabs { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 10px; }
.tabs button { font-size: 13px; padding: 3px 10px; border-radius: 14px; color: var(--text-secondary); }
.tabs button[aria-selected="true"] { background: var(--text-primary); color: var(--surface-1); border-color: var(--text-primary); }
/* Tried-and-landed: a row per kind of try, a cell per measure, a bar each for you and them. */
.bars { display: grid; grid-template-columns: minmax(130px, 1.3fr) repeat(var(--cols), minmax(90px, 1fr)); gap: 0 14px; font-size: 13px; }
.bars .head { color: var(--text-secondary); font-weight: 600; padding: 0 0 6px; }
.bars .name { padding: 8px 0; border-top: 1px solid var(--grid); }
.bars .name small { display: block; color: var(--text-secondary); font-size: 12px; }
.bars .cell { padding: 8px 0; border-top: 1px solid var(--grid); display: flex; flex-direction: column; gap: 4px; justify-content: center; }
.bar { display: flex; align-items: center; gap: 6px; height: 12px; }
.bar .track { flex: 1; height: 8px; border-radius: 4px; background: var(--wash); overflow: hidden; }
.bar .fill { height: 100%; border-radius: 0 4px 4px 0; min-width: 0; }
.bar .num { width: 36px; text-align: right; font-variant-numeric: tabular-nums; color: var(--text-secondary); font-size: 12px; }
.bar .num.strong { color: var(--text-primary); font-weight: 600; }
@media (max-width: 560px) {
  main { padding: 16px 16px 40px; } .tile .value { font-size: 22px; }
  .bars { grid-template-columns: minmax(100px, 1fr) repeat(var(--cols), minmax(70px, 1fr)); gap: 0 8px; }
}
`;

// Script helpers and charts both pages use (plain JavaScript, run in the browser).
const COMMON_JS = String.raw`
'use strict';
const DATA = JSON.parse(document.getElementById('data').textContent);
const SVG = 'http://www.w3.org/2000/svg';
const KINDS = [['crit', 'Crits'], ['sprint', 'Sprint hits'], ['sweep', 'Sweeps'], ['other', 'Other hits']];
const KIND_NAMES = { crit: 'Crit', sprint: 'Sprint hit', sweep: 'Sweep', other: 'Other hit' };
/** Kinds of try: what the swinger was doing when they swung. */
const TRIES = [
  ['crit', 'Crit tries', 'falling, not sprinting', 'crit'],
  ['sprint', 'Sprint hits', 'sprinting', 'sprint'],
  ['rising', 'Going up', 'mid-jump, too early to crit', null],
  ['ground', 'On the ground', 'standing or walking', null],
];
/** What came of an attack. */
const OUTCOMES = [
  ['hit', 'Landed', 'the hit counted'],
  ['early', 'Too early', 'they were still invulnerable from the last hit (half a second)'],
  ['far', 'Out of reach', 'more than 3 blocks from the eyes to their hitbox'],
  ['miss', 'Missed', 'in reach, not too early, no hit: aim, or lag'],
  ['blocked', 'Shield', 'blocked by their shield'],
];
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
const svgText = (attrs, text) => { const t = svg('text', attrs); t.textContent = text; return t; };
const ok = v => v !== null && v !== undefined && isFinite(v);
const pct = v => !ok(v) ? '–' : Math.round(v * 100) + '%';
const num = (v, d = 2) => !ok(v) ? '–' : v.toFixed(d);
const day = ms => { const d = new Date(ms); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };
const shortDay = key => { const [, m, d] = key.split('-'); return Number(m) + '/' + Number(d); };
const clock = ms => Math.floor(ms / 60000) + ':' + String(Math.floor(ms / 1000) % 60).padStart(2, '0');
const clockTenths = ms => clock(ms) + '.' + Math.floor(ms / 100) % 10;
const when = ms => new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const plural = (n, word) => n + ' ' + word + (n === 1 ? '' : 's');

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
const tipRow = (box, value, label, keyClass, color) => {
  const row = el('div', { class: 'row' });
  if (keyClass || color) { const k = el('i', { class: 'tt-key ' + (keyClass || '') }); if (color) k.style.background = color; row.append(k); }
  row.append(el('strong', {}, value), el('span', { class: 'muted' }, label));
  box.append(row);
};
/** Hover and keyboard focus both show a mark's readout. */
function readout(node, build) {
  const show = evt => showTip(evt, build);
  node.addEventListener('pointermove', show);
  node.addEventListener('pointerleave', hideTip);
  node.setAttribute('tabindex', '0');
  node.addEventListener('focus', () => { const r = node.getBoundingClientRect(); show({ clientX: r.right, clientY: r.top }); });
  node.addEventListener('blur', hideTip);
}

function niceMax(v) {
  if (v <= 0) return 1;
  if (v <= 1 && v > 0.1) return Math.ceil(v * 10) / 10;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

function table(head, rows, leftColumns = 1) {
  const t = el('table');
  const thead = el('thead');
  const tr = el('tr');
  head.forEach((h, i) => tr.append(el('th', i < leftColumns ? { class: 'l' } : {}, h)));
  thead.append(tr);
  const body = el('tbody');
  for (const r of rows) { const row = el('tr'); r.forEach((c, i) => row.append(el('td', i < leftColumns ? { class: 'l' } : {}, String(c)))); body.append(row); }
  t.append(thead, body);
  return t;
}
function tableView(head, rows) {
  const d = el('details');
  d.append(el('summary', {}, 'Show as a table'), table(head, rows));
  return d;
}
function legend(items) {
  const l = el('div', { class: 'legend' });
  for (const [label, color, cls] of items) {
    const k = el('span', { class: 'key' });
    const i = el('i', { class: cls || 'dot' });
    if (color) i.style.background = color;
    k.append(i, document.createTextNode(label));
    l.append(k);
  }
  return l;
}
const kindLegend = () => legend(KINDS.map(([k, label]) => [label, 'var(--' + k + ')']));

/** Add up what each side tried and what came of it, over some fighters' numbers. */
function attackTotals(players) {
  const t = { attacks: 0, uses: 0, outcomes: {}, tries: {} };
  for (const [o] of OUTCOMES) t.outcomes[o] = 0;
  for (const [k] of TRIES) t.tries[k] = { tries: 0, landed: 0, charged: 0, as: { crit: 0, sprint: 0, sweep: 0, other: 0 } };
  for (const p of players) {
    if (!p.outcomes) continue;
    t.attacks += p.attacks; t.uses += p.uses;
    for (const [o] of OUTCOMES) t.outcomes[o] += p.outcomes[o] || 0;
    for (const [k] of TRIES) {
      const a = p.tries[k], b = t.tries[k];
      b.tries += a.tries; b.landed += a.landed; b.charged += a.charged;
      for (const kind in a.as) b.as[kind] += a.as[kind];
    }
  }
  return t;
}

/** One small bar: a share, with its number; the tooltip has the counts. */
function bar(value, color, strong, tip) {
  const b = el('div', { class: 'bar' });
  const track = el('div', { class: 'track' });
  const fill = el('div', { class: 'fill' });
  fill.style.width = ok(value) ? Math.max(0, Math.min(1, value)) * 100 + '%' : '0';
  fill.style.background = color;
  track.append(fill);
  b.append(track, el('span', { class: 'num' + (strong ? ' strong' : '') }, pct(value)));
  if (tip) readout(b, tip);
  return b;
}

/**
 * What each side tried, and what landed: a row per kind of try; how much of their attacking it was,
 * how much of it was fully charged, how much landed, and how much landed as meant (a crit try as a crit).
 * sides: [{ name, color, keyClass, totals }].
 */
function triesChart(container, sides) {
  const cols = [
    ['Share of attacks', (t, k) => [t.tries[k].tries, t.attacks]],
    ['Fully charged', (t, k) => [t.tries[k].charged, t.tries[k].tries]],
    ['Landed', (t, k) => [t.tries[k].landed, t.tries[k].tries]],
    ['Landed as meant', (t, k, meant) => meant ? [t.tries[k].as[meant], t.tries[k].tries] : null],
  ];
  const grid = el('div', { class: 'bars' });
  grid.style.setProperty('--cols', cols.length);
  grid.append(el('div', { class: 'head' }, ''));
  for (const [label] of cols) grid.append(el('div', { class: 'head' }, label));
  const rows = [];
  for (const [k, label, hint, meant] of TRIES) {
    const name = el('div', { class: 'name' }, label);
    name.append(el('small', {}, hint));
    grid.append(name);
    const row = [label];
    for (const [colLabel, get] of cols) {
      const cell = el('div', { class: 'cell' });
      const parts = [];
      for (const s of sides) {
        const r = get(s.totals, k, meant);
        if (!r) { cell.append(el('span', { class: 'note' }, s === sides[0] ? '–' : '')); parts.push('–'); continue; }
        const [n, of] = r;
        const v = of ? n / of : null;
        cell.append(bar(v, s.color, s === sides[0], box => {
          box.append(el('div', { class: 'muted' }, label + ': ' + colLabel.toLowerCase()));
          tipRow(box, pct(v), n + ' of ' + of, null, s.color);
          box.append(el('div', { class: 'muted' }, s.name));
        }));
        parts.push(pct(v) + ' (' + n + '/' + of + ')');
      }
      grid.append(cell);
      row.push(parts.join(' · '));
    }
    rows.push(row);
  }
  container.append(grid);
  container.append(legend(sides.map(s => [s.name, s.color])));
  container.append(tableView(['Try', ...cols.map(c => c[0] + ' (' + sides.map(s => s.name).join(' · ') + ')')], rows));
}

/** Where the attacking swings went: a bar per outcome, for each side, as a share of its attacks. */
function outcomesChart(container, sides) {
  const grid = el('div', { class: 'bars' });
  grid.style.setProperty('--cols', 1);
  grid.append(el('div', { class: 'head' }, ''), el('div', { class: 'head' }, 'Share of attacking swings'));
  const rows = [];
  for (const [o, label, hint] of OUTCOMES) {
    const name = el('div', { class: 'name' }, label);
    name.append(el('small', {}, hint));
    grid.append(name);
    const cell = el('div', { class: 'cell' });
    const row = [label];
    for (const s of sides) {
      const n = s.totals.outcomes[o], of = s.totals.attacks;
      const v = of ? n / of : null;
      cell.append(bar(v, s.color, s === sides[0], box => {
        box.append(el('div', { class: 'muted' }, label));
        tipRow(box, pct(v), n + ' of ' + plural(of, 'attack'), null, s.color);
        box.append(el('div', { class: 'muted' }, s.name));
      }));
      row.push(pct(v) + ' (' + n + ')');
    }
    grid.append(cell);
    rows.push(row);
  }
  container.append(grid);
  container.append(legend(sides.map(s => [s.name, s.color])));
  const uses = sides.map(s => s.name + ': ' + s.totals.uses).join(', ');
  container.append(el('p', { class: 'note' }, 'Swings that were placing or breaking blocks aren\'t counted as attacks (' + uses + ').'));
  container.append(tableView(['Outcome', ...sides.map(s => s.name)], rows));
}

/** Hit kinds as a 100% bar for each side, labelled where they fit. sides: [{ name, counts: {kind: n} }]. */
function mixChart(container, sides) {
  const W = 480, rowH = 28, gap = 14, L = 84, T = 4;
  const H = T + sides.length * (rowH + gap);
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Hits by kind' });
  sides.forEach(({ name, counts }, r) => {
    const total = KINDS.reduce((n, [k]) => n + (counts[k] || 0), 0);
    const yy = T + r * (rowH + gap);
    s.append(svgText({ x: 0, y: yy + rowH / 2 + 4, 'font-size': 12, fill: 'var(--text-secondary)' }, name + (total ? '' : ' (no hits)')));
    if (!total) return;
    let xx = L;
    for (const [kind, kindLabel] of KINDS) {
      const w = (counts[kind] || 0) / total * (W - L);
      if (w <= 0) continue;
      const seg = svg('rect', { x: xx, y: yy, width: Math.max(0, w - 2), height: rowH, rx: 4, fill: 'var(--' + kind + ')' });
      const share = Math.round(counts[kind] / total * 100) + '%';
      readout(seg, box => tipRow(box, share + ' (' + counts[kind] + ')', name + ': ' + kindLabel.toLowerCase(), null, 'var(--' + kind + ')'));
      s.append(seg);
      if (w > 40) s.append(svgText({ x: xx + 8, y: yy + rowH / 2 + 4, 'font-size': 12, 'font-weight': 600, fill: kind === 'other' ? 'var(--text-primary)' : '#ffffff', 'pointer-events': 'none' }, share));
      xx += w;
    }
  });
  container.append(s, kindLegend());
  container.append(tableView(['', 'Hits', ...KINDS.map(k => k[1])], sides.map(({ name, counts }) =>
    [name, KINDS.reduce((n, [k]) => n + (counts[k] || 0), 0), ...KINDS.map(([k]) => counts[k] || 0)])));
}
`;

module.exports = { htmlPage, jsonScript, escapeHtml, CSS, COMMON_JS };
