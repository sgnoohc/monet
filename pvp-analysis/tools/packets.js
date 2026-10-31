#!/usr/bin/env node
// What's in a recording: how many packets of each kind, by state (and how many couldn't be read).
//
//   node tools/packets.js <recording.mcpr> [packet name, to print the first few of]
'use strict';
const { readReplay } = require('../src/replay');

const [file, show] = process.argv.slice(2);
const replay = readReplay(file);
console.log(JSON.stringify(replay.meta).slice(0, 300));
const counts = {};
let shown = 0;
const failed = {};
for (const p of replay.packets((state, id, e) => {
  const key = `${state}/0x${id.toString(16)}: ${String(e.message).slice(0, 80)}`;
  failed[key] = (failed[key] || 0) + 1;
})) {
  const key = `${p.state}/${p.name}`;
  counts[key] = (counts[key] || 0) + 1;
  if (show && p.name === show && shown++ < 5) console.log(p.time, JSON.stringify(p.params, (k, v) => typeof v === 'bigint' ? v.toString() : v).slice(0, 400));
}
for (const [key, n] of Object.entries(counts).sort((a, b) => b[1] - a[1])) console.log(String(n).padStart(7), key);
for (const [key, n] of Object.entries(failed)) console.log(String(n).padStart(7), 'FAILED', key);
