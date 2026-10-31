// The dashboard: one page with every fight in the history: your numbers against your opponents',
// how they move over time, and the fights, each opening its own view (src/fightpage.js) in the
// same page, at #fight=<id>. One file, so it works however it's opened: a sandboxed browser (a
// Flatpak) given just this file can't open any other.
'use strict';
const { htmlPage, jsonScript } = require('./page');
const { fightData, FIGHT_TEMPLATE, FIGHT_CSS, FIGHT_JS } = require('./fightpage');

/** Where a fight's view is, in the page. */
const fightLink = id => `#fight=${id}`;

/** What the overview needs of each fight (not the swings and tracks: they're on the fight's page). */
function fightsForPage(entries) {
  const fights = [];
  for (const e of entries) {
    e.fights.forEach((f, i) => {
      const selfIndex = f.players.findIndex(p => p.self);
      const result = selfIndex < 0 || !f.winner ? null : f.winner === f.players[selfIndex].name ? 'win' : 'loss';
      const id = `${e.id}-${i + 1}`;
      fights.push({
        id,
        page: fightLink(id),
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
          bands: p.reach ? p.reach.bands : null, swings: p.swings, attacks: p.attacks, uses: p.uses, accuracy: p.accuracy,
          tries: p.tries, outcomes: p.outcomes, longestCombo: p.longestCombo, resets: p.sprintResets,
        })),
      });
    });
  }
  return fights.sort((a, b) => a.date - b.date);
}

function dashboard(entries, { generated = new Date() } = {}) {
  // Each fight's view data in its own block, read only when that fight is opened.
  const replays = entries.flatMap(e => e.fights.map((_, i) => {
    const d = fightData(e, i, { generated });
    return jsonScript(`replay-${d.id}`, d);
  }));
  return htmlPage({
    title: 'PvP fight analysis',
    data: { generated: generated.getTime(), recordings: entries.length, fights: fightsForPage(entries) },
    body: BODY,
    css: FIGHT_CSS,
    extra: FIGHT_TEMPLATE + '\n' + replays.join('\n'),
    script: JS + FIGHT_JS + ROUTER_JS,
  });
}

const BODY = `<main class="viz-root" id="overview">
  <header>
    <h1>PvP fight analysis</h1>
    <p class="sub" id="summary"></p>
  </header>
  <div class="filters" role="group" aria-label="Filters">
    <label>Server <select id="server"></select></label>
  </div>
  <section class="tiles" id="tiles" aria-label="Headline numbers"></section>
  <section>
    <h2>Your attacks: what you tried, and what landed</h2>
    <p class="note">Every swing, by what you were doing when you swung, and what came of it. You in blue, your opponents in gray.</p>
    <div class="two">
      <div class="card"><h3>Tried, and landed</h3><div id="tries"></div></div>
      <div class="card"><h3>Where the swings went</h3><div id="outcomes"></div></div>
    </div>
  </section>
  <section class="two">
    <div class="card"><h2>How hits land</h2><p class="note">Share of hits by kind.</p><div id="mix"></div></div>
    <div class="card"><h2>Reach at hits</h2><p class="note">Share of hits by distance, from the attacker's eyes to the other's hitbox (3 blocks at most).</p><div id="reach"></div></div>
  </section>
  <section>
    <div class="card">
      <h2>Over time</h2>
      <p class="note"><span id="per"></span> <label>Points <select id="by"><option value="recording">a recording each</option><option value="day">a day each</option></select></label></p>
      <div class="tabs" role="tablist" id="metric-tabs" aria-label="Measure"></div>
      <div id="trend"></div>
    </div>
  </section>
  <section>
    <h2>Fights</h2>
    <p class="note">Newest first. Open a fight for its replay: where you both were, the distance, every swing.</p>
    <div class="table-wrap"><table id="fights"></table></div>
  </section>
  <section>
    <h2>Opponents</h2>
    <p class="note">How the players you fought fight: worth copying what works.</p>
    <div class="table-wrap"><table id="opponents"></table></div>
  </section>
  <footer class="note" id="footer" style="margin-top: 32px"></footer>
</main>
<main class="viz-root" id="fight-view" hidden></main>`;

// The overview's own script (after page.js's helpers).
const JS = String.raw`
const BAND_LABELS = ['under 2', '2–2.5', '2.5–2.75', '2.75–3', '3+'];
const YOU = { color: 'var(--you)', keyClass: 'you-bg' };
const THEM = { color: 'var(--them)', keyClass: 'them-bg' };
const side = (f, s) => f.players[s === 'you' ? f.selfIndex : 1 - f.selfIndex];

/** Totals for one side ('you', or 'them': your opponents) over some fights. */
function totals(fights, s) {
  const t = { fights: fights.length, hits: 0, crits: 0, sprint: 0, sweeps: 0, taken: 0, swings: 0, seconds: 0, resets: 0,
    reachSum: 0, reachHits: 0, wins: 0, losses: 0, combo: 0 };
  for (const f of fights) {
    const p = side(f, s);
    t.hits += p.hits; t.crits += p.crits; t.sprint += p.sprintHits; t.sweeps += p.sweeps; t.taken += p.hitsTaken;
    t.swings += p.swings; t.seconds += f.seconds; t.resets += p.resets; t.combo = Math.max(t.combo, p.longestCombo);
    if (ok(p.reachMean)) { t.reachSum += p.reachMean * p.hits; t.reachHits += p.hits; }
    if (f.result === (s === 'you' ? 'win' : 'loss')) t.wins++;
    if (f.result === (s === 'you' ? 'loss' : 'win')) t.losses++;
  }
  const a = attackTotals(fights.map(f => side(f, s)));
  const share = n => t.hits ? n / t.hits : null;
  const ofAttacks = n => a.attacks ? n / a.attacks : null;
  return { ...t, attack: a, critShare: share(t.crits), sprintShare: share(t.sprint), sweepShare: share(t.sweeps),
    reach: t.reachHits ? t.reachSum / t.reachHits : null, accuracy: ofAttacks(a.outcomes.hit),
    early: ofAttacks(a.outcomes.early), far: ofAttacks(a.outcomes.far),
    critTries: a.tries.crit.tries ? a.tries.crit.as.crit / a.tries.crit.tries : null,
    charged: a.attacks ? TRIES.reduce((n, [k]) => n + a.tries[k].charged, 0) / a.attacks : null,
    cps: t.seconds ? t.swings / t.seconds : null, resetsPerMin: t.seconds ? t.resets / (t.seconds / 60) : null,
    hitRatio: t.taken ? t.hits / t.taken : null };
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

const METRICS = [
  { key: 'accuracy', label: 'Attacks that landed', note: 'hits ÷ attacking swings', fmt: pct, good: 'up' },
  { key: 'critShare', label: 'Crits', note: 'share of hits', fmt: pct, good: 'up' },
  { key: 'critTries', label: 'Crit tries that crit', note: 'falling swings that landed as crits', fmt: pct, good: 'up' },
  { key: 'sprintShare', label: 'Sprint hits', note: 'share of hits', fmt: pct, good: 'up' },
  { key: 'sweepShare', label: 'Sweeps', note: 'share of hits: standing hits', fmt: pct, good: 'down' },
  { key: 'early', label: 'Too early', note: 'share of attacks, while they were still invulnerable', fmt: pct, good: 'down' },
  { key: 'far', label: 'Out of reach', note: 'share of attacks, from over 3 blocks', fmt: pct, good: 'down' },
  { key: 'charged', label: 'Fully charged', note: 'share of attacks, after the weapon\'s cooldown', fmt: pct, good: 'up' },
  { key: 'reach', label: 'Mean reach', note: 'blocks, at hits', fmt: v => num(v), good: null },
  { key: 'cps', label: 'CPS', note: 'swings a second, in fights', fmt: v => num(v, 1), good: null },
  { key: 'resetsPerMin', label: 'W-taps', note: 'sprint resets a minute', fmt: v => num(v, 1), good: 'up' },
  { key: 'hitRatio', label: 'Hits landed ÷ taken', note: 'over 1: you out-hit them', fmt: v => num(v), good: 'up' },
];
let metric = METRICS[0];

/** One measure over time, you and your opponents, a point per recording (or day). */
function trendChart(container, m, groups) {
  container.replaceChildren();
  const W = 1100, H = 260, L = 48, R = 56, T = 16, B = 28;
  const you = groups.map(g => totals(g.fights, 'you')[m.key]);
  const them = groups.map(g => totals(g.fights, 'them')[m.key]);
  const values = [...you, ...them].filter(ok);
  if (!values.length) { container.append(el('div', { class: 'empty' }, 'No data for this yet.')); return; }
  // Round ticks: a step of 1, 2, 2.5 or 5 (times a power of ten), about four to the top.
  const lo = 0;
  const top = Math.max(...values, m.fmt === pct ? 0.1 : 0) || 1;
  const p10 = Math.pow(10, Math.floor(Math.log10(top / 4)));
  const tick = [1, 2, 2.5, 5, 10].map(k => k * p10).find(k => k * 4 >= top);
  const hi = Math.ceil(top / tick - 1e-9) * tick;
  const x = i => groups.length === 1 ? L + (W - L - R) / 2 : L + i * (W - L - R) / (groups.length - 1);
  const y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': m.label + ' over time' });
  for (let v = 0; v <= hi + 1e-9; v += tick) {
    s.append(svg('line', { x1: L, x2: W - R, y1: y(v), y2: y(v), stroke: v === 0 ? 'var(--axis)' : 'var(--grid)', 'stroke-width': 1 }));
    s.append(svgText({ x: L - 8, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 11, fill: 'var(--muted)' }, m.fmt === pct ? pct(v) : String(+v.toFixed(2))));
  }
  const room = Math.floor((W - L - R) / (groups[0].tick.length * 6.5 + 16));
  const step = Math.max(1, Math.ceil(groups.length / room));
  groups.forEach((g, i) => {
    if (i % step && i !== groups.length - 1) return;
    s.append(svgText({ x: x(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: 'var(--muted)' }, g.tick));
  });
  const line = (vals, color, label) => {
    let d = '';
    vals.forEach((v, i) => { if (ok(v)) d += (d ? 'L' : 'M') + x(i) + ' ' + y(v); });
    if (d) s.append(svg('path', { d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    vals.forEach((v, i) => { if (ok(v)) s.append(svg('circle', { cx: x(i), cy: y(v), r: 4, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2 })); });
    // The line's name at its end.
    const last = vals.map((v, i) => [v, i]).filter(([v]) => ok(v)).pop();
    if (last) s.append(svgText({ x: x(last[1]) + 10, y: y(last[0]) + 4, 'font-size': 12, 'font-weight': 600, fill: 'var(--text-primary)' }, label));
  };
  line(them, 'var(--them)', 'Them');
  line(you, 'var(--you)', 'You');
  const cross = svg('line', { y1: T, y2: H - B, stroke: 'var(--axis)', 'stroke-width': 1, visibility: 'hidden' });
  s.append(cross);
  const hit = svg('rect', { x: L - 10, y: 0, width: W - L - R + 20, height: H, fill: 'transparent', tabindex: 0 });
  const nearest = evt => {
    const p = s.getBoundingClientRect();
    const px = (evt.clientX - p.left) / p.width * W;
    let best = 0;
    groups.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i; });
    return best;
  };
  const show = (evt, i) => {
    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i)); cross.setAttribute('visibility', 'visible');
    showTip(evt, box => {
      box.append(el('div', { class: 'muted' }, groups[i].title + ' · ' + plural(groups[i].fights.length, 'fight')));
      tipRow(box, m.fmt(you[i]), 'You', 'you-bg');
      tipRow(box, m.fmt(them[i]), 'Opponents', 'them-bg');
    });
  };
  hit.addEventListener('pointermove', evt => show(evt, nearest(evt)));
  hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
  hit.addEventListener('focus', () => { const r = s.getBoundingClientRect(); show({ clientX: r.right - 80, clientY: r.top }, groups.length - 1); });
  hit.addEventListener('blur', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
  s.append(hit);
  const wide = el('div', { class: 'wide' });
  wide.append(s);
  container.append(wide);
  container.append(legend([['You', 'var(--you)', 'you-bg'], ['Your opponents', 'var(--them)', 'them-bg']]));
  container.append(tableView(['When', 'Fights', 'You', 'Opponents'], groups.map((g, i) => [g.title, g.fights.length, m.fmt(you[i]), m.fmt(them[i])])));
}

/** Reach bands: share of each side's hits, side by side. */
function reachChart(container, fights) {
  const sides = [['You', 'you', 'var(--you)'], ['Opponents', 'them', 'var(--them)']];
  const counts = sides.map(([, s]) => {
    const c = BAND_LABELS.map(() => 0);
    for (const f of fights) { const p = side(f, s); if (p.bands) p.bands.forEach(([, n], i) => { c[i] += n; }); }
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
    s.append(svgText({ x: L - 6, y: y(v) + 4, 'text-anchor': 'end', 'font-size': 10, fill: 'var(--muted)' }, pct(v)));
  }
  BAND_LABELS.forEach((label, i) => {
    const cx = L + band * i + band / 2;
    s.append(svgText({ x: cx, y: H - 6, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--muted)' }, label));
    sides.forEach(([name, key, color], k) => {
      const v = shares[k][i];
      const x0 = cx - bw - 1 + k * (bw + 2);
      const h = Math.max(0, y(0) - y(v));
      const r = Math.min(4, h / 2, bw / 2);
      if (h > 0) s.append(svg('path', { fill: color, d: 'M' + x0 + ' ' + y(0) + 'V' + (y(v) + r) + 'Q' + x0 + ' ' + y(v) + ' ' + (x0 + r) + ' ' + y(v)
        + 'H' + (x0 + bw - r) + 'Q' + (x0 + bw) + ' ' + y(v) + ' ' + (x0 + bw) + ' ' + (y(v) + r) + 'V' + y(0) + 'Z' }));
      const hit = svg('rect', { x: x0 - 2, y: T, width: bw + 4, height: H - T - B, fill: 'transparent' });
      readout(hit, box => { box.append(el('div', { class: 'muted' }, label + ' blocks')); tipRow(box, pct(v) + ' (' + counts[k][i] + ')', name, key + '-bg'); });
      s.append(hit);
    });
  });
  container.append(s, legend([['You', 'var(--you)'], ['Opponents', 'var(--them)']]));
  container.append(tableView(['Reach (blocks)', 'You', 'Opponents'], BAND_LABELS.map((b, i) => [b, pct(shares[0][i]) + ' (' + counts[0][i] + ')', pct(shares[1][i]) + ' (' + counts[1][i] + ')'])));
}

function sparkline(values) {
  const W = 120, H = 26;
  const v = values.map(a => ok(a) ? a : null);
  const present = v.filter(a => a !== null);
  const s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, 'aria-hidden': 'true' });
  if (present.length < 2) return s;
  const lo = Math.min(...present), hi = Math.max(...present) === lo ? lo + 1 : Math.max(...present);
  const x = i => 4 + i * (W - 8) / (v.length - 1);
  const y = a => 4 + (H - 8) * (1 - (a - lo) / (hi - lo));
  let d = '';
  v.forEach((a, i) => { if (a !== null) d += (d ? 'L' : 'M') + x(i) + ' ' + y(a); });
  s.append(svg('path', { d, fill: 'none', stroke: 'var(--them)', 'stroke-width': 2, 'stroke-linejoin': 'round' }));
  const last = v.length - 1;
  if (v[last] !== null) s.append(svg('circle', { cx: x(last), cy: y(v[last]), r: 3, fill: 'var(--you)' }));
  return s;
}

const fmtResult = r => r === 'win' ? '✓ Won' : r === 'loss' ? '✗ Lost' : '–';

function render() {
  const server = document.getElementById('server').value;
  const all = DATA.fights.filter(f => server === 'all' || f.server === server);
  const mine = all.filter(f => f.selfIndex >= 0);
  const by = document.getElementById('by').value;
  const days = groupsOf(mine, 'day');
  const groups = groupsOf(mine, by);
  const before = by === 'day' ? 'the day before' : 'the recording before';
  const you = totals(mine, 'you'), them = totals(mine, 'them');
  const servers = [...new Set(all.map(f => f.server))];
  const summary = document.getElementById('summary');
  summary.textContent = plural(mine.length, 'fight') + ' of yours in ' + plural(DATA.recordings, 'recording')
    + (!days.length ? '' : days.length === 1 ? ', on ' + days[0].key : ', ' + days[0].key + ' to ' + days[days.length - 1].key)
    + ' · ' + servers.join(', ');
  const fresh = mine.filter(f => f.added === DATA.generated).length;
  if (fresh) summary.textContent += ' · ' + fresh + ' new this run';

  // Headline tiles: the number over everything, then the latest recording (or day) against the one before.
  const tiles = document.getElementById('tiles');
  tiles.replaceChildren();
  const tile = (label, value, m) => {
    const t = el('div', { class: 'tile' });
    t.append(el('div', { class: 'label' }, label), el('div', { class: 'value' }, value));
    if (m && groups.length >= 2) {
      const a = totals(groups[groups.length - 2].fights, 'you')[m.key];
      const b = totals(groups[groups.length - 1].fights, 'you')[m.key];
      if (ok(a) && ok(b)) {
        const diff = b - a;
        const better = m.good === null ? null : (m.good === 'up') === (diff > 0);
        const same = m.fmt(Math.abs(diff)) === m.fmt(0);
        t.append(el('div', { class: 'delta' + (better === null || same ? '' : better ? ' up' : ' down') },
          same ? 'Same as ' + before : (diff > 0 ? '▲ ' : '▼ ') + m.fmt(Math.abs(diff)) + ' on ' + before));
      }
      t.append(sparkline(groups.map(g => totals(g.fights, 'you')[m.key])));
    }
    tiles.append(t);
  };
  tile('Fights', String(mine.length), null);
  tile('Won', you.wins + you.losses ? you.wins + ' of ' + (you.wins + you.losses) : '–', null);
  for (const key of ['accuracy', 'critShare', 'early', 'hitRatio']) {
    const m = METRICS.find(x => x.key === key);
    tile(m.label, m.fmt(you[key]), m);
  }

  const sides = [{ name: 'You', ...YOU, totals: you.attack }, { name: 'Opponents', ...THEM, totals: them.attack }];
  for (const [id, chart] of [['tries', triesChart], ['outcomes', outcomesChart]]) {
    const c = document.getElementById(id);
    c.replaceChildren();
    chart(c, sides);
  }
  const mix = document.getElementById('mix');
  mix.replaceChildren();
  const counts = t => ({ crit: t.crits, sprint: t.sprint, sweep: t.sweeps, other: Math.max(0, t.hits - t.crits - t.sprint - t.sweeps) });
  mixChart(mix, [{ name: 'You', counts: counts(you) }, { name: 'Opponents', counts: counts(them) }]);
  const reach = document.getElementById('reach');
  reach.replaceChildren();
  reachChart(reach, mine);

  document.getElementById('per').textContent = by === 'day' ? 'Each point is a day of fights.' : 'Each point is a recording: a session of fights.';
  drawTrend = () => trendChart(document.getElementById('trend'), metric, groups);
  drawTrend();

  fightsTable(all);
  opponentsTable(mine);
  document.getElementById('footer').textContent = 'Made ' + new Date(DATA.generated).toLocaleString() + ' from the recordings analysed so far. '
    + 'Positions are as the recording player\'s game saw them: other players\' are a little behind the server.';
}
let drawTrend = () => {};

function fightsTable(fights) {
  const t = document.getElementById('fights');
  t.replaceChildren();
  const head = ['When', 'Server', 'Opponent', 'Result', 'Length', 'Hits', 'Taken', 'Crits', 'Attacks that landed', 'Too early', 'Out of reach', 'Reach', ''];
  const explain = { Hits: 'Hits you landed', Taken: 'Hits you took', Reach: 'Median reach of your hits, in blocks',
    'Attacks that landed': 'Your hits ÷ your attacking swings', 'Too early': 'Your swings while they were still invulnerable',
    'Out of reach': 'Your swings from over 3 blocks' };
  const thead = el('thead');
  const tr = el('tr');
  head.forEach((h, i) => tr.append(el('th', { ...(i < 3 ? { class: 'l' } : {}), ...(explain[h] ? { title: explain[h] } : {}) }, h)));
  thead.append(tr);
  const body = el('tbody');
  for (const f of [...fights].reverse()) {
    const me = f.players[f.selfIndex >= 0 ? f.selfIndex : 0];
    const them = f.players[f.selfIndex >= 0 ? 1 - f.selfIndex : 1];
    const row = el('tr');
    const cells = [when(f.date), f.server, f.selfIndex >= 0 ? them.name : me.name + ' vs ' + them.name + ' (watched)'];
    cells.forEach(c => row.append(el('td', { class: 'l' }, c)));
    if (f.added === DATA.generated) row.firstChild.append(' ', el('span', { class: 'chip' }, 'new'));
    const res = el('td');
    res.append(el('span', { class: 'result ' + (f.result || '') }, fmtResult(f.result)));
    row.append(res);
    const of = (n, d) => d ? pct(n / d) : '–';
    for (const c of [clock(f.durationMs), me.hits, them.hits, me.crits, pct(me.accuracy),
      me.outcomes ? of(me.outcomes.early, me.attacks) : '–', me.outcomes ? of(me.outcomes.far, me.attacks) : '–', num(me.reachMedian)]) {
      row.append(el('td', {}, String(c)));
    }
    const open = el('td');
    open.append(el('a', { href: f.page }, 'Replay ›'));
    row.append(open);
    body.append(row);
  }
  if (!fights.length) { const r = el('tr'); r.append(el('td', { colspan: head.length, class: 'l' }, 'No fights yet.')); body.append(r); }
  t.append(thead, body);
}

function opponentsTable(fights) {
  const by = new Map();
  for (const f of fights) {
    const p = side(f, 'them');
    if (!by.has(p.name)) by.set(p.name, []);
    by.get(p.name).push(f);
  }
  const rows = [...by.entries()].map(([name, fs]) => {
    const o = totals(fs, 'them');
    const wins = fs.filter(f => f.result === 'win').length, decided = fs.filter(f => f.result).length;
    return [name, fs.length, decided ? wins + ' of ' + decided : '–', o.hits, pct(o.accuracy), pct(o.critShare), pct(o.sprintShare),
      pct(o.sweepShare), pct(o.early), num(o.reach), num(o.resetsPerMin, 1), o.combo];
  }).sort((a, b) => b[1] - a[1]);
  const t = document.getElementById('opponents');
  t.replaceWith(Object.assign(table(['Opponent', 'Fights', 'You won', 'Their hits', 'Attacks that landed', 'Crits', 'Sprint hits', 'Sweeps',
    'Too early', 'Mean reach', 'W-taps a minute', 'Longest combo'], rows.length ? rows : [['No opponents yet.']]), { id: 'opponents' }));
}

// Controls: the server, the points over time, the measure over time (each remembered).
const remember = (key, value) => { try { localStorage.setItem('pvp-analysis-' + key, value); } catch (e) {} };
const recall = key => { try { return localStorage.getItem('pvp-analysis-' + key); } catch (e) { return null; } };
const grouping = document.getElementById('by');
grouping.value = new Set(DATA.fights.map(f => day(f.date))).size >= 3 ? 'day' : 'recording';
if (recall('by') === 'day' || recall('by') === 'recording') grouping.value = recall('by');
grouping.addEventListener('change', () => { remember('by', grouping.value); render(); });
const select = document.getElementById('server');
select.append(el('option', { value: 'all' }, 'All servers'));
for (const s of [...new Set(DATA.fights.map(f => f.server))]) select.append(el('option', { value: s }, s));
if ([...select.options].some(o => o.value === recall('server'))) select.value = recall('server');
select.addEventListener('change', () => { remember('server', select.value); render(); });
metric = METRICS.find(m => m.key === recall('metric')) || METRICS[0];
const tabs = document.getElementById('metric-tabs');
for (const m of METRICS) {
  const b = el('button', { role: 'tab', 'aria-selected': String(m === metric), title: m.note }, m.label);
  b.addEventListener('click', () => {
    metric = m;
    remember('metric', m.key);
    for (const other of tabs.children) other.setAttribute('aria-selected', String(other === b));
    drawTrend();
  });
  tabs.append(b);
}
render();
`;

// Which view: a fight's at #fight=<id>, the overview otherwise (so Back goes back to it).
const ROUTER_JS = String.raw`
const overviewView = document.getElementById('overview');
const fightView = document.getElementById('fight-view');
let leaveFight = null;
let overviewScroll = 0;
function route() {
  if (leaveFight) { leaveFight(); leaveFight = null; }
  const m = location.hash.match(/^#fight=([\w-]+)$/);
  const data = m && document.getElementById('replay-' + m[1]);
  if (data) {
    if (!overviewView.hidden) overviewScroll = scrollY;
    overviewView.hidden = true;
    fightView.hidden = false;
    fightView.replaceChildren(document.getElementById('fight-template').content.cloneNode(true));
    const fight = JSON.parse(data.textContent);
    document.title = fight.title;
    leaveFight = openFight(fight, fightView);
    scrollTo(0, 0);
  } else {
    fightView.hidden = true;
    fightView.replaceChildren();
    overviewView.hidden = false;
    document.title = 'PvP fight analysis';
    scrollTo(0, overviewScroll);
  }
}
addEventListener('hashchange', route);
route();
`;

module.exports = { dashboard, fightsForPage, fightLink };
