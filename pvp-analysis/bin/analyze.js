#!/usr/bin/env node
// Analyse the fights in Replay Mod recordings, adding them to the history, then write the reports
// from the whole history: a dashboard (index.html), a Markdown report, and the numbers as JSON.
//
//   node bin/analyze.js [recording.mcpr | folder ...] [--server pvphq] [--out reports] [--force]
//
// Each recording is analysed once and kept in history/ (so its fights stay in the reports, and in
// the trends, after the recording is deleted); a run only reads recordings it hasn't seen, or ones
// analysed by an older version of the analysis. --force reads them all again.
//
// --server: only recordings on servers whose address has this in it (repeat it for more: say, your
// sparring server and PvPHQ, leaving out Quake Arena's gauntlet fights). The default is config.json's
// "servers", if there is one; with neither, every server.
// With no recordings given: config.json's "folders", or else Replay Mod's replay_recordings in every
// Prism Launcher instance and in the vanilla launcher's game folder, on Linux, macOS or Windows (just
// the recordings themselves, not Replay Mod's working folders inside them). Copies of the same
// recording (same server, start and length) are only read once.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');
const { readReplay } = require('../src/replay');
const { World } = require('../src/world');
const { fightsIn, ANALYZER_VERSION } = require('../src/fights');
const { report } = require('../src/report');
const { dashboard } = require('../src/dashboard');
const { History } = require('../src/history');

const root = path.join(__dirname, '..');
const config = readConfig(path.join(root, 'config.json'));
const args = process.argv.slice(2);
const option = name => {
  const values = [];
  for (let i; (i = args.indexOf(name)) >= 0;) values.push(args.splice(i, 2)[1]);
  return values;
};
const flag = name => {
  const i = args.indexOf(name);
  return i >= 0 && args.splice(i, 1).length > 0;
};
const out = option('--out')[0] || path.join(root, 'reports');
const historyDir = option('--history')[0] || path.join(root, 'history');
const given = option('--server');
const servers = (given.length ? given : config.servers || []).map(s => String(s).toLowerCase());
const force = flag('--force');
const inputs = args.length ? args : (config.folders || []).map(f => f.replace(/^~(?=$|\/)/, os.homedir())).concat(config.folders ? [] : defaultFolders());

function readConfig(file) {
  if (!fs.existsSync(file)) return {};
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (e) {
    console.error(`config.json: ${e.message}`);
    process.exit(1);
  }
}

/** Where Replay Mod saves recordings: in each Prism Launcher instance, and the vanilla launcher's game folder. */
function defaultFolders() {
  const home = os.homedir();
  const data = process.platform === 'win32' ? process.env.APPDATA || path.join(home, 'AppData', 'Roaming')
    : process.platform === 'darwin' ? path.join(home, 'Library', 'Application Support')
    : process.env.XDG_DATA_HOME || path.join(home, '.local', 'share');
  const games = [
    process.platform === 'win32' ? path.join(data, '.minecraft')
      : process.platform === 'darwin' ? path.join(data, 'minecraft')
      : path.join(home, '.minecraft'),
  ];
  const prism = [path.join(data, 'PrismLauncher'), path.join(home, '.var', 'app', 'org.prismlauncher.PrismLauncher', 'data', 'PrismLauncher')];
  for (const launcher of prism) {
    const instances = path.join(launcher, 'instances');
    if (!fs.existsSync(instances)) continue;
    for (const i of fs.readdirSync(instances)) games.push(path.join(instances, i, 'minecraft'), path.join(instances, i, '.minecraft'));
  }
  return games.map(g => path.join(g, 'replay_recordings')).filter(d => fs.existsSync(d));
}

function recordings(input) {
  if (!fs.existsSync(input)) {
    console.error(`${input}: not found`);
    return [];
  }
  if (fs.statSync(input).isDirectory()) {
    return fs.readdirSync(input).filter(f => f.endsWith('.mcpr')).sort().map(f => path.join(input, f));
  }
  return [input];
}

const registries = {};
function registriesFor(version) {
  if (!registries[version]) {
    const file = path.join(root, 'data', `registries-${version}.json`);
    if (!fs.existsSync(file)) throw new Error(`No ids for Minecraft ${version}: run tools/make-registries.sh with its server jar`);
    registries[version] = JSON.parse(fs.readFileSync(file, 'utf8'));
  }
  return registries[version];
}

const onServer = serverName => !servers.length || servers.some(s => String(serverName).toLowerCase().includes(s));

if (!inputs.length) console.error('No recordings found: give a recording or a folder, or set "folders" in config.json.');
const history = new History(historyDir);
const runAt = Date.now();
const seen = new Set();
let added = 0, updated = 0, kept = 0;
for (const file of inputs.flatMap(recordings)) {
  try {
    const replay = readReplay(file);
    const id = History.idFor(replay.meta);
    if (seen.has(id) || !onServer(replay.meta.serverName)) continue;
    seen.add(id);
    const before = history.get(id);
    if (before && before.analyzer === ANALYZER_VERSION && !force) {
      kept++;
      continue;
    }
    const world = new World(registriesFor(replay.version));
    for (const packet of replay.packets()) world.handle(packet);
    const fights = fightsIn(world);
    history.put({
      id,
      analyzer: ANALYZER_VERSION,
      file: path.basename(file),
      meta: replay.meta,
      // When it first went into the history (kept when it's analysed again), and when it last was.
      added: before ? before.added : runAt,
      analyzed: runAt,
      fights,
    });
    if (before) updated++;
    else added++;
    console.log(`${before ? 'again' : 'new  '} ${path.basename(file)}: ${replay.meta.serverName}, ${fights.length} fight${fights.length === 1 ? '' : 's'}`);
  } catch (e) {
    console.error(`${file}: ${e.message}`);
  }
}

// The reports: everything in the history (on the chosen servers), recordings deleted since included:
// the dashboard (every fight's replay in it), the Markdown report and the numbers.
const entries = history.all().filter(e => onServer(e.meta.serverName));
const fightCount = entries.reduce((n, e) => n + e.fights.length, 0);
fs.mkdirSync(out, { recursive: true });
const write = (name, text) => {
  const temp = path.join(out, `${name}.tmp`);
  fs.writeFileSync(temp, text);
  fs.renameSync(temp, path.join(out, name));
};
write('index.html', dashboard(entries, { generated: new Date(runAt) }));
// (Fights' views are in index.html now: no more pages of their own, which a sandboxed browser couldn't open.)
const oldPages = path.join(out, 'fights');
if (fs.existsSync(oldPages)) {
  for (const f of fs.readdirSync(oldPages)) if (/^[0-9a-f]+-\d+\.html$/.test(f)) fs.rmSync(path.join(oldPages, f));
  if (!fs.readdirSync(oldPages).length) fs.rmdirSync(oldPages);
}
write('report.md', report(entries));
write('fights.json', JSON.stringify(entries, null, 2));
console.log(`${added} new recording${added === 1 ? '' : 's'}, ${updated} analysed again, ${kept} already in the history`
  + ` (${historyDir}): ${entries.length} recording${entries.length === 1 ? '' : 's'}, ${fightCount} fight${fightCount === 1 ? '' : 's'} in the reports.`);
console.log(`Dashboard: ${pathToFileURL(path.resolve(out, 'index.html')).href}`);
