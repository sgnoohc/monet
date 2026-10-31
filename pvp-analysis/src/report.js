// The analysis as Markdown: a section per recording, a table per fight with both fighters side by
// side, then the recording player's totals over every fight.
'use strict';

const fmt = (n, digits = 2) => n === null || n === undefined || Number.isNaN(n) ? '–' : Number(n).toFixed(digits);
const pct = n => n === null || n === undefined ? '–' : `${Math.round(n * 100)}%`;
const time = ms => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;

/** The rows of a fight's table: a label, then how to show it for one fighter. */
const ROWS = [
  ['Hits landed', p => p.hits],
  ['· crits', p => p.crits],
  ['· sprint hits', p => p.sprintHits],
  ['· sweeps', p => p.sweeps],
  ['Hits taken', p => p.hitsTaken],
  ['Reach at hits: mean / median / max', p => p.reach ? `${fmt(p.reach.mean)} / ${fmt(p.reach.median)} / ${fmt(p.reach.max)}` : '–'],
  ['Reach bands', p => p.reach ? p.reach.bands.filter(([, n]) => n).map(([label, n]) => `${label}: ${n}`).join(', ') : '–'],
  ['Swings (CPS average / best second)', p => `${p.swings} (${fmt(p.cps, 1)} / ${p.bestCps})`],
  ['Double clicks', p => p.doubleClicks],
  ['Attacks that landed (of swings that weren\'t block work)', p => `${pct(p.accuracy)} (${p.hits} of ${p.attacks ?? p.swings})`],
  ['· too early / out of reach / missed / shield', p => p.outcomes ? `${p.outcomes.early} / ${p.outcomes.far} / ${p.outcomes.miss} / ${p.outcomes.blocked}` : '–'],
  ['Crit tries (falling): landed / as crits', p => p.tries ? `${p.tries.crit.tries}: ${p.tries.crit.landed} / ${p.tries.crit.as.crit}` : '–'],
  ['Sprint tries: landed / as sprint hits', p => p.tries ? `${p.tries.sprint.tries}: ${p.tries.sprint.landed} / ${p.tries.sprint.as.sprint}` : '–'],
  ['Swings going up / on the ground: landed', p => p.tries ? `${p.tries.rising.tries}: ${p.tries.rising.landed} / ${p.tries.ground.tries}: ${p.tries.ground.landed}` : '–'],
  ['Longest combo (combos of 3+)', p => `${p.longestCombo} (${p.combos})`],
  ['Distance kept: mean / median', p => p.distance ? `${fmt(p.distance.mean)} / ${fmt(p.distance.median)}` : '–'],
  ['Strafing (blocks/s sideways)', p => fmt(p.strafeSpeed)],
  ['Time sprinting', p => pct(p.sprintingShare)],
  ['Jumps', p => p.jumps],
  ['Sprint resets (w-taps)', p => p.sprintResets],
  ['Hits blocked with a shield', p => p.blocked],
  ['Golden apples / potions / pearls / totems', p => `${p.gapples} / ${p.potions} / ${p.pearls} / ${p.totems}`],
  ['Blocks placed', p => Object.entries(p.placed).map(([b, n]) => `${b} ${n}`).join(', ') || '–'],
  ['Lowest health', p => fmt(p.lowestHealth, 1)],
];

function report(analyses) {
  const lines = ['# PvP fight analysis', '',
    `${analyses.length} recording${analyses.length === 1 ? '' : 's'} (${[...new Set(analyses.map(a => a.meta.serverName))].join(', ')}), `
    + `${analyses.reduce((n, a) => n + a.fights.length, 0)} fights. Positions are as the recording player's game saw them `
    + '(a little behind the server); reach is from the attacker\'s eyes to the other\'s hitbox, as the server measures it.', ''];
  for (const a of analyses) {
    const m = a.meta;
    lines.push(`## ${a.file}`, '', `${m.serverName} · ${new Date(m.date).toISOString().replace('T', ' ').slice(0, 16)} UTC · `
      + `${time(m.duration)} · ${a.fights.length} fight${a.fights.length === 1 ? '' : 's'}`, '');
    a.fights.forEach((f, i) => {
      const [p, q] = f.players;
      const result = f.winner ? `${f.winner} won${f.how === 'died' ? ' (the other died)' : ''}` : 'result unknown';
      lines.push(`### Fight ${i + 1}: ${p.name} vs ${q.name} · ${time(f.durationMs)} · ${result}`, '',
        `| | ${p.name}${p.self ? ' (you)' : ''} | ${q.name}${q.self ? ' (you)' : ''} |`, '|---|---|---|');
      for (const [label, show] of ROWS) lines.push(`| ${label} | ${show(p)} | ${show(q)} |`);
      lines.push('');
    });
  }
  lines.push(...totals(analyses));
  return lines.join('\n');
}

/** The recording player's totals over every fight they were in. */
function totals(analyses) {
  const mine = analyses.flatMap(a => a.fights.map(f => ({ me: f.players.find(p => p.self), f }))).filter(x => x.me);
  if (!mine.length) return [];
  const sum = key => mine.reduce((n, x) => n + x.me[key], 0);
  const reaches = mine.filter(x => x.me.reach).map(x => [x.me.reach.mean, x.me.hits]);
  const meanReach = reaches.reduce((s, [r, n]) => s + r * n, 0) / Math.max(1, reaches.reduce((s, [, n]) => s + n, 0));
  const hits = sum('hits');
  const wins = mine.filter(x => x.f.winner === x.me.name).length;
  const decided = mine.filter(x => x.f.winner).length;
  return ['## You, over every fight', '',
    `| | |`, '|---|---|',
    `| Fights (won / decided) | ${mine.length} (${wins} / ${decided}) |`,
    `| Hits landed / taken | ${hits} / ${sum('hitsTaken')} |`,
    `| Crits / sprint hits / sweeps | ${sum('crits')} (${pct(sum('crits') / Math.max(1, hits))}) / ${sum('sprintHits')} (${pct(sum('sprintHits') / Math.max(1, hits))}) / ${sum('sweeps')} (${pct(sum('sweeps') / Math.max(1, hits))}) |`,
    `| Mean reach at hits | ${fmt(meanReach)} |`,
    `| Swings that hit | ${pct(hits / Math.max(1, sum('swings')))} |`,
    `| Longest combo | ${Math.max(...mine.map(x => x.me.longestCombo))} |`,
    ''];
}

module.exports = { report };
