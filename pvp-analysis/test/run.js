#!/usr/bin/env node
// Tests: the reader, on a small recording written here with minecraft-protocol's own encoder; and
// the tracker and fight numbers, on a fight made up packet by packet, where every number is known.
//
//   node test/run.js
'use strict';
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const mc = require('minecraft-protocol');
const { readReplay } = require('../src/replay');
const { World } = require('../src/world');
const { fightsIn } = require('../src/fights');
const { report } = require('../src/report');
const { dashboard, fightsForPage } = require('../src/dashboard');
const { fightData } = require('../src/fightpage');
const { History } = require('../src/history');

const VERSION = '1.21.11';
const reg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'data', `registries-${VERSION}.json`), 'utf8'));
let failures = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name}\n  ${e.message.split('\n').join('\n  ')}`);
  }
}

/** A zip of stored (uncompressed) entries. */
function zip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, data] of Object.entries(entries)) {
    const nameBuf = Buffer.from(name);
    const crc = zlib.crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, nameBuf, data);
    centrals.push(central, nameBuf);
    offset += 30 + nameBuf.length + data.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(entries).length, 8);
  end.writeUInt16LE(Object.keys(entries).length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

test('reader: a recording\'s packets come back in order, through login, configuration and play', () => {
  const packets = [
    [100, mc.states.LOGIN, 'success', { uuid: '35497583-a717-3a98-8afd-930a1bae6575', username: 'Tester', properties: [] }],
    [150, mc.states.CONFIGURATION, 'finish_configuration', {}],
    [200, mc.states.PLAY, 'animation', { entityId: 7, animation: 0 }],
    [250, mc.states.PLAY, 'damage_event', { entityId: 8, sourceTypeId: 34, sourceCauseId: 8, sourceDirectId: 8, sourcePosition: undefined }],
  ];
  const chunks = [];
  for (const [time, state, name, params] of packets) {
    const buf = mc.createSerializer({ state, isServer: true, version: VERSION }).createPacketBuffer({ name, params });
    const head = Buffer.alloc(8);
    head.writeInt32BE(time, 0);
    head.writeInt32BE(buf.length, 4);
    chunks.push(head, buf);
  }
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pvp-analysis-')), 'test.mcpr');
  fs.writeFileSync(file, zip({
    'metaData.json': Buffer.from(JSON.stringify({ serverName: 'test', mcversion: VERSION, duration: 300, date: 0 })),
    'recording.tmcpr': Buffer.concat(chunks),
  }));
  const replay = readReplay(file);
  const read = [...replay.packets()];
  fs.rmSync(path.dirname(file), { recursive: true });
  assert.deepStrictEqual(read.map(p => [p.time, p.name]), packets.map(([t, , n]) => [t, n]));
  assert.strictEqual(read[0].params.username, 'Tester');
  assert.deepStrictEqual([read[3].params.entityId, read[3].params.sourceCauseId], [8, 8]);
});

// A made-up fight. Alice (the recording player, entity 1) and Bob (2) stand 3 blocks apart along x:
// from Alice's eyes (x 0.5) to the front of Bob's hitbox (x 3.2) is 2.7.
function fight() {
  const w = new World(reg);
  const player = reg.entity_type.indexOf('player');
  let t = 1000;
  const p = (name, params, dt = 50) => {
    t += dt;
    w.handle({ time: t, name, params });
  };
  p('login', { entityId: 1 }, 0);
  p('player_info', { data: [{ uuid: 'a', player: { name: 'Alice' } }, { uuid: 'b', player: { name: 'Bob' } }] }, 0);
  p('spawn_entity', { entityId: 1, objectUUID: 'a', type: player, x: 0.5, y: 64, z: 0.5 }, 0);
  p('spawn_entity', { entityId: 2, objectUUID: 'b', type: player, x: 3.5, y: 64, z: 0.5 }, 0);
  // Alice, sprinting, swings and hits: her eyes at x 0.5, Bob's hitbox from x 3.2: reach 2.7.
  p('entity_metadata', { entityId: 1, metadata: [{ key: 0, value: 0x08 }] });
  p('animation', { entityId: 1, animation: 0 });
  p('damage_event', { entityId: 2, sourceTypeId: 34, sourceCauseId: 2, sourceDirectId: 2 }, 0);
  // A double click: a second swing 40 ms later.
  p('animation', { entityId: 1, animation: 0 }, 40);
  p('entity_metadata', { entityId: 1, metadata: [{ key: 0, value: 0 }] });
  // She jumps (not sprinting) and crits on the way down, from 0.5 closer: reach 2.2.
  p('rel_entity_move', { entityId: 1, dX: 0.5 * 4096, dY: 0.42 * 4096, dZ: 0, onGround: false }, 500);
  p('rel_entity_move', { entityId: 1, dX: 0, dY: -0.42 * 4096, dZ: 0, onGround: false });
  p('animation', { entityId: 1, animation: 0 });
  p('damage_event', { entityId: 2, sourceTypeId: 34, sourceCauseId: 2, sourceDirectId: 2 }, 0);
  p('animation', { entityId: 2, animation: 4 }, 0);
  // Bob hits back once (a sweep), then Alice three times in a row, then Bob dies.
  p('animation', { entityId: 2, animation: 0 }, 600);
  p('damage_event', { entityId: 1, sourceTypeId: 34, sourceCauseId: 3, sourceDirectId: 3 }, 0);
  p('world_particles', { x: 3.5, y: 65, z: 0.5, particle: { type: 'sweep_attack' } }, 0);
  for (let i = 0; i < 3; i++) {
    p('animation', { entityId: 1, animation: 0 }, 600);
    p('damage_event', { entityId: 2, sourceTypeId: 34, sourceCauseId: 2, sourceDirectId: 2 }, 0);
  }
  p('entity_status', { entityId: 2, entityStatus: 3 }, 100);
  return w;
}

test('fights: one fight, Alice won (Bob died)', () => {
  const fights = fightsIn(fight());
  assert.strictEqual(fights.length, 1);
  assert.strictEqual(fights[0].winner, 'Alice');
  assert.deepStrictEqual(fights[0].players.map(p => p.name), ['Alice', 'Bob'], 'the recording player first');
});

test('fights: hits, crits, sprint hits, sweeps, taken', () => {
  const [alice, bob] = fightsIn(fight())[0].players;
  assert.deepStrictEqual([alice.hits, alice.crits, alice.sprintHits, alice.sweeps, alice.hitsTaken], [5, 1, 1, 0, 1]);
  assert.deepStrictEqual([bob.hits, bob.crits, bob.sprintHits, bob.sweeps, bob.hitsTaken], [1, 0, 0, 1, 5]);
});

test('fights: reach at each hit, from the attacker\'s eyes to the hitbox', () => {
  const [alice] = fightsIn(fight())[0].players;
  // 2.7 for the first hit, then 2.2 for the rest (she moved 0.5 closer).
  assert.ok(Math.abs(alice.reach.max - 2.7) < 1e-9, `max ${alice.reach.max}`);
  assert.ok(Math.abs(alice.reach.median - 2.2) < 1e-9, `median ${alice.reach.median}`);
  assert.deepStrictEqual(alice.reach.bands.filter(([, n]) => n), [['2–2.5', 4], ['2.5–2.75', 1]]);
});

test('fights: swings, double clicks, combos, jumps', () => {
  const [alice] = fightsIn(fight())[0].players;
  assert.deepStrictEqual([alice.swings, alice.doubleClicks, alice.longestCombo, alice.combos, alice.jumps], [6, 1, 3, 1, 1]);
});

test('report: a table per fight, and the recording player\'s totals', () => {
  const md = report([{ file: 'test.mcpr', meta: { serverName: 'test', date: 0, duration: 4000 }, fights: fightsIn(fight()) }]);
  assert.ok(md.includes('### Fight 1: Alice vs Bob'), md);
  assert.ok(md.includes('| Hits landed | 5 | 1 |'), md);
  assert.ok(md.includes('## You, over every fight'), md);
});

test('fights: a timeline of every hit, by whom, what kind, from how far', () => {
  const f = fightsIn(fight())[0];
  assert.deepStrictEqual(f.timeline.map(h => [h.by, h.kind]),
    [[0, 'sprint'], [0, 'crit'], [1, 'sweep'], [0, 'other'], [0, 'other'], [0, 'other']]);
  assert.strictEqual(f.timeline[0].t, 3000, 'from the start of the window, 3 s before the first hit');
  assert.ok(Math.abs(f.timeline[0].reach - 2.7) < 1e-9);
  assert.ok(f.seconds >= f.durationMs / 1000);
});

test('fights: every swing, what it was meant as and what came of it', () => {
  const f = fightsIn(fight())[0];
  const [alice, bob] = f.players;
  // Alice: a sprint hit, then a double click 40 ms later (Bob still invulnerable: too early), a crit
  // from a jump, then three more hits while she's still in the air as far as the recording knows.
  assert.deepStrictEqual(f.swings.filter(s => s.by === 0).map(s => [s.try, s.outcome, s.kind]), [
    ['sprint', 'hit', 'sprint'], ['sprint', 'early', null], ['crit', 'hit', 'crit'],
    ['crit', 'hit', 'other'], ['crit', 'hit', 'other'], ['crit', 'hit', 'other']]);
  assert.strictEqual(f.swings[1].charged, false, 'a click 40 ms after the last isn\'t charged');
  assert.deepStrictEqual(alice.outcomes, { hit: 5, blocked: 0, early: 1, far: 0, miss: 0 });
  assert.deepStrictEqual([alice.tries.sprint.tries, alice.tries.sprint.landed, alice.tries.crit.tries, alice.tries.crit.as.crit], [2, 1, 4, 1]);
  assert.strictEqual(alice.accuracy, 5 / 6);
  assert.deepStrictEqual([bob.tries.ground.tries, bob.tries.ground.as.sweep], [1, 1]);
});

test('fights: where both were, a sample a tick, from the start of the window', () => {
  const f = fightsIn(fight())[0];
  const { step, players } = f.tracks;
  assert.strictEqual(step, 50);
  assert.strictEqual(players[0].length, Math.floor(f.windowMs / step) + 1);
  const atFirstHit = players[0][Math.floor(f.timeline[0].t / step)];
  assert.deepStrictEqual(atFirstHit.slice(0, 3), [0.5, 64, 0.5]);
  assert.ok(atFirstHit[4] & f.tracks.flags.sprinting, 'sprinting at her first hit');
});

test('history: kept per recording, by session; read back oldest first', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pvp-history-'));
  const h = new History(dir);
  const later = { serverName: 'pvphq', date: 2000, duration: 10 };
  const earlier = { serverName: 'pvphq', date: 1000, duration: 10 };
  assert.strictEqual(History.idFor(later), History.idFor({ ...later }), 'same session, same id');
  assert.notStrictEqual(History.idFor(later), History.idFor(earlier));
  h.put({ id: History.idFor(later), meta: later, fights: [] });
  h.put({ id: History.idFor(earlier), meta: earlier, fights: [] });
  assert.strictEqual(h.get('missing'), null);
  assert.deepStrictEqual(new History(dir).all().map(e => e.meta.date), [1000, 2000]);
  assert.deepStrictEqual(fs.readdirSync(dir).filter(f => f.endsWith('.tmp')), []);
  fs.rmSync(dir, { recursive: true });
});

test('world: the recording player by account, when the server sends them under another id than the login\'s', () => {
  const w = new World(reg);
  const player = reg.entity_type.indexOf('player');
  w.handle({ time: 0, name: 'success', params: { uuid: 'a', username: 'Alice' } });
  w.handle({ time: 1, name: 'login', params: { entityId: -291 } });
  w.handle({ time: 2, name: 'player_info', params: { data: [{ uuid: 'a', player: { name: 'Alice' } }] } });
  w.handle({ time: 3, name: 'spawn_entity', params: { entityId: 290, objectUUID: 'a', type: player, x: 0, y: 64, z: 0 } });
  assert.deepStrictEqual(w.who(w.server, 290), { name: 'Alice', self: true });
  assert.strictEqual(w.selfId, 290);
});

test('dashboard: one page, the fights in it, names that can\'t break out of it', () => {
  const fights = fightsIn(fight());
  fights[0].players[1].name = '</script><b>Bob';
  const entry = { id: 'x', file: 'test.mcpr', meta: { serverName: 'test', date: 5000, duration: 4000 }, added: 7, fights };
  const page = dashboard([entry], { generated: new Date(7) });
  assert.ok(page.startsWith('<!doctype html>'));
  assert.strictEqual(page.split('</script>').length - 1, 3, 'only the page\'s own scripts end: its data, a fight\'s, its script');
  assert.ok(!/<script[^>]+src=/.test(page), 'no outside scripts');
  const json = page.match(/<script type="application\/json" id="data">(.*?)<\/script>/s)[1];
  const data = JSON.parse(json);
  assert.strictEqual(data.fights.length, 1);
  assert.strictEqual(data.fights[0].players[1].name, '</script><b>Bob');
  const [f] = fightsForPage([entry]);
  assert.deepStrictEqual([f.result, f.selfIndex, f.date, f.added, f.page], ['win', 0, 5000 + fights[0].startMs, 7, '#fight=x-1']);
  assert.ok(!('tracks' in f) && !('swings' in f), 'the overview\'s list leaves the replays to the fights\' own data');
  const replay = JSON.parse(page.match(/<script type="application\/json" id="replay-x-1">(.*?)<\/script>/s)[1]);
  assert.strictEqual(replay.players[1].name, '</script><b>Bob', 'each fight\'s replay is in the page too');
  assert.ok(page.includes('<template id="fight-template">'));
});

test('fight view: what a fight\'s replay needs', () => {
  const fights = fightsIn(fight());
  const entry = { id: 'x', file: 'test.mcpr', meta: { serverName: 'test', date: 5000, duration: 4000 }, fights };
  const data = fightData(entry, 0);
  assert.deepStrictEqual([data.title, data.id, data.result, data.lead, data.swings.length, data.tracks.players.length],
    ['Fight vs Bob', 'x-1', 'win', 3000, 7, 2]);
});

console.log(failures ? `\n${failures} failed` : '\nall passed');
process.exit(failures ? 1 : 0);
