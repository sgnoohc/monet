// Reads a Replay Mod recording (.mcpr): its metadata, and the packets the server sent, decoded.
//
// recording.tmcpr is a run of [int32 time in ms][int32 length][packet: varint id, then its fields],
// starting at login. The connection's state decides what an id means: login, then configuration,
// then play; a proxy moving the player to another server sends start_configuration, and it's
// configuration again until finish_configuration.
'use strict';
const mc = require('minecraft-protocol');
const { readZip } = require('./zip');

function readReplay(file) {
  const zip = readZip(file);
  if (!zip['metaData.json'] || !zip['recording.tmcpr']) throw new Error(`${file} isn't a Replay Mod recording`);
  const meta = JSON.parse(zip['metaData.json']().toString('utf8'));
  const version = meta.mcversion;
  if (!mc.supportedVersions.includes(version) && !mc.supportedVersions.some(v => version.startsWith(v))) {
    throw new Error(`${file}: Minecraft ${version} isn't supported by minecraft-protocol`);
  }
  return { meta, version, packets: onError => packets(zip['recording.tmcpr'](), version, onError) };
}

/**
 * The recording's packets, in order: { time (ms), state, name, params }. One that can't be decoded
 * is left out, after onError(state, id, error) if given.
 */
function* packets(data, version, onError) {
  const parsers = {};
  const parser = state => parsers[state]
    || (parsers[state] = mc.createDeserializer({ state, isServer: false, version, noErrorLogging: true }));
  let state = mc.states.LOGIN;
  let off = 0;
  while (off + 8 <= data.length) {
    const time = data.readInt32BE(off);
    const length = data.readInt32BE(off + 4);
    off += 8;
    const buf = data.subarray(off, off + length);
    off += length;
    let packet;
    try {
      packet = parser(state).parsePacketBuffer(buf).data;
    } catch (e) {
      if (onError) onError(state, buf.length ? buf[0] : -1, e);
      continue;
    }
    yield { time, state, name: packet.name, params: packet.params };
    if (state === mc.states.LOGIN && packet.name === 'success') state = mc.states.CONFIGURATION;
    else if (state === mc.states.CONFIGURATION && packet.name === 'finish_configuration') state = mc.states.PLAY;
    else if (state === mc.states.PLAY && packet.name === 'start_configuration') state = mc.states.CONFIGURATION;
  }
}

module.exports = { readReplay };
