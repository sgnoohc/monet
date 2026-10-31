// Follows the players in a recording, packet by packet, and writes down what they do: their
// movement (a sample per move, and a track of where they were and which way they looked), swings
// (with how far each player was), hits (from damage events, which name the attacker), crits
// (the crit animation on the one hit), sweeps (the sweep particles), sounds near them (shields,
// eating, drinking), blocks placed near them, deaths and totems, plus titles and chat for telling
// fights apart.
//
// Positions are as the recording player's game saw them: a little behind the server, by its ping.
'use strict';
const nbt = require('prismarine-nbt');

/** Height of a player's eyes, and of their hitbox, standing and sneaking. */
const EYES = 1.62;
const EYES_SNEAKING = 1.27;
const HEIGHT = 1.8;
const HEIGHT_SNEAKING = 1.5;
const HALF_WIDTH = 0.3;

const SHARED_FLAGS = 0; // bit 1: sneaking, bit 3: sprinting
const LIVING_FLAGS = 8; // bit 0: using an item, bit 1: in the off hand
const HEALTH = 9;

/** Sounds worth knowing about, by what they mean. */
const SOUNDS = {
  'item.shield.block': 'shieldBlock',
  'item.shield.break': 'shieldBreak',
  'entity.generic.eat': 'eat',
  'entity.player.burp': 'ate',
  'entity.generic.drink': 'drink',
  'item.totem.use': 'totem',
  'entity.ender_pearl.throw': 'pearl',
  'item.bucket.empty': 'water',
};
/** A track sample's flags. */
const FLAGS = { onGround: 1, sprinting: 2, sneaking: 4, usingItem: 8, blocking: 16 };
const PLACED = new Set(['cobweb', 'water', 'oak_log', 'cobblestone', 'oak_planks']);

/** Plain text of a chat or title component (prismarine passes some on as NBT). */
function text(c) {
  if (c === undefined || c === null) return '';
  if (c.type !== undefined && c.value !== undefined) c = nbt.simplify(c);
  if (typeof c === 'string') {
    try {
      return text(JSON.parse(c));
    } catch {
      return c;
    }
  }
  if (Array.isArray(c)) return c.map(text).join('');
  if (typeof c !== 'object') return String(c);
  const own = c.text !== undefined ? c.text : c[''] !== undefined ? c[''] : c.translate !== undefined ? c.translate : '';
  return text(own) + (c.extra ? c.extra.map(text).join('') : '');
}

class World {
  constructor(registries) {
    this.reg = registries;
    this.players = new Map(); // entity id → player
    this.names = new Map(); // uuid → name
    this.selfId = null;
    this.selfUuid = null; // the recording player's account, from the login
    this.server = 0; // which server (a proxy's move to another one starts a new count)
    this.events = [];
    /** Everyone seen, by server and entity id (ids start over on each server): { name, self }. */
    this.known = new Map();
    /** By "server:id": [time, x, y, z, yaw (where they look), flags (World.FLAGS)] at every change. */
    this.tracks = new Map();
    /** By "server:id": [time, item in the main hand] at every change. */
    this.held = new Map();
  }

  /** Write down where a player is, which way they look and what they're doing, if it changed. */
  track(time, p) {
    const key = `${this.server}:${p.id}`;
    if (!this.tracks.has(key)) this.tracks.set(key, []);
    const using = p.usingItem ? (p.offHandUse ? p.offHand : p.mainHand) : null;
    const flags = (p.onGround ? FLAGS.onGround : 0) | (p.sprinting ? FLAGS.sprinting : 0) | (p.sneaking ? FLAGS.sneaking : 0)
      | (p.usingItem ? FLAGS.usingItem : 0) | (using === 'shield' ? FLAGS.blocking : 0);
    const yaw = p.look !== null ? p.look : p.yaw;
    const t = this.tracks.get(key);
    const last = t[t.length - 1];
    if (last && last[1] === p.x && last[2] === p.y && last[3] === p.z && last[4] === yaw && last[5] === flags) return;
    if (last && last[0] === time) t.pop();
    t.push([time, p.x, p.y, p.z, yaw, flags]);
  }

  emit(time, type, fields) {
    this.events.push({ time, server: this.server, type, ...fields });
  }

  /** Whose position is nearest (x, y, z), within {@code within} blocks, or null. */
  nearest(x, y, z, within) {
    let best = null;
    let bestD = within;
    for (const p of this.players.values()) {
      const d = Math.hypot(p.x - x, p.y + 1 - y, p.z - z);
      if (d < bestD) {
        bestD = d;
        best = p;
      }
    }
    return best;
  }

  /** From the attacker's eyes to the nearest point of the victim's hitbox: reach, as the server measures it. */
  static reach(attacker, victim) {
    const ex = attacker.x;
    const ey = attacker.y + (attacker.sneaking ? EYES_SNEAKING : EYES);
    const ez = attacker.z;
    const top = victim.y + (victim.sneaking ? HEIGHT_SNEAKING : HEIGHT);
    const gap = (lo, hi, v) => Math.max(lo - v, 0, v - hi);
    return Math.hypot(gap(victim.x - HALF_WIDTH, victim.x + HALF_WIDTH, ex), gap(victim.y, top, ey), gap(victim.z - HALF_WIDTH, victim.z + HALF_WIDTH, ez));
  }

  /** What one player looks like now, for an event. */
  static snapshot(p) {
    return {
      id: p.id, name: p.name, x: p.x, y: p.y, z: p.z, yaw: p.yaw, onGround: p.onGround, sprinting: p.sprinting,
      sneaking: p.sneaking, vy: p.vy, health: p.health, mainHand: p.mainHand, usingItem: p.usingItem,
    };
  }

  handle({ time, name, params }) {
    switch (name) {
      case 'success':
        this.selfUuid = params.uuid;
        return;
      case 'login':
        // A new server (a proxy moved the player): entity ids start over.
        this.server++;
        this.players.clear();
        this.selfId = params.entityId;
        return;
      case 'respawn':
        this.players.clear();
        return;
      case 'player_info':
        for (const d of params.data || []) if (d.player && d.player.name) this.names.set(d.uuid, d.player.name);
        return;
      case 'spawn_entity': {
        if (this.reg.entity_type[params.type] !== 'player') return;
        // The recording player, by account: some servers (PvPHQ) log you in with one entity id and
        // then send everything about you under another (Replay Mod records your spawn with that one).
        if (this.selfUuid && params.objectUUID === this.selfUuid) this.selfId = params.entityId;
        const p = {
          id: params.entityId, uuid: params.objectUUID, name: this.names.get(params.objectUUID) || params.objectUUID,
          self: params.entityId === this.selfId, x: params.x, y: params.y, z: params.z, yaw: 0, look: null, pitch: 0, vy: 0,
          onGround: true, sprinting: false, sneaking: false, usingItem: false, offHandUse: false, health: null,
          mainHand: null, offHand: null,
        };
        this.players.set(p.id, p);
        this.known.set(`${this.server}:${p.id}`, { name: p.name, self: p.self });
        this.track(time, p);
        return;
      }
      case 'entity_destroy':
        for (const id of params.entityIds) this.players.delete(id);
        return;
      case 'rel_entity_move':
      case 'entity_move_look': {
        const p = this.players.get(params.entityId);
        if (!p) return;
        this.move(time, p, p.x + params.dX / 4096, p.y + params.dY / 4096, p.z + params.dZ / 4096, params.onGround,
          name === 'entity_move_look' ? params.yaw : null);
        return;
      }
      case 'entity_look': {
        const p = this.players.get(params.entityId);
        if (!p) return;
        p.yaw = params.yaw * 360 / 256;
        this.track(time, p);
        return;
      }
      case 'entity_head_rotation': {
        // Where a player looks (their body turns after their head).
        const p = this.players.get(params.entityId);
        if (!p) return;
        p.look = params.headYaw * 360 / 256;
        this.track(time, p);
        return;
      }
      case 'sync_entity_position':
      case 'entity_teleport': {
        const p = this.players.get(params.entityId);
        if (p) this.move(time, p, params.x, params.y, params.z, params.onGround, null, params.yaw);
        return;
      }
      case 'entity_metadata': {
        const p = this.players.get(params.entityId);
        if (!p) return;
        for (const m of params.metadata) {
          if (m.key === SHARED_FLAGS) {
            const sprinting = (m.value & 0x08) !== 0;
            if (sprinting !== p.sprinting) this.emit(time, sprinting ? 'sprintStart' : 'sprintStop', { player: p.id });
            p.sprinting = sprinting;
            p.sneaking = (m.value & 0x02) !== 0;
          } else if (m.key === LIVING_FLAGS) {
            p.usingItem = (m.value & 0x01) !== 0;
            p.offHandUse = (m.value & 0x02) !== 0;
          } else if (m.key === HEALTH) {
            p.health = m.value;
            this.emit(time, 'health', { player: p.id, health: m.value });
          }
        }
        this.track(time, p);
        return;
      }
      case 'update_health': {
        const p = this.players.get(this.selfId);
        if (p) {
          p.health = params.health;
          this.emit(time, 'health', { player: p.id, health: params.health });
        }
        return;
      }
      case 'entity_equipment': {
        const p = this.players.get(params.entityId);
        if (!p) return;
        for (const e of params.equipments) {
          const item = e.item && e.item.itemCount > 0 ? this.reg.item[e.item.itemId] : null;
          if (e.slot === 0) p.mainHand = item;
          else if (e.slot === 1) p.offHand = item;
        }
        const key = `${this.server}:${p.id}`;
        if (!this.held.has(key)) this.held.set(key, []);
        const held = this.held.get(key);
        if (!held.length || held[held.length - 1][1] !== p.mainHand) held.push([time, p.mainHand]);
        return;
      }
      case 'animation': {
        const p = this.players.get(params.entityId);
        if (!p) return;
        if (params.animation === 0) {
          // How far everyone near was, from this player's eyes, and what the player was doing.
          const near = [];
          for (const o of this.players.values()) if (o !== p && Math.hypot(o.x - p.x, o.z - p.z) < 10) near.push({ id: o.id, reach: World.reach(p, o) });
          this.emit(time, 'swing', { player: p.id, a: World.snapshot(p), near });
        }
        else if (params.animation === 4) this.emit(time, 'critAnimation', { victim: p.id });
        return;
      }
      case 'damage_event': {
        const victim = this.players.get(params.entityId);
        // The attacker's id is sent one higher (0: nobody).
        const attacker = this.players.get(params.sourceCauseId - 1);
        if (!victim) return;
        const direct = params.sourceDirectId === params.sourceCauseId;
        this.emit(time, 'damage', {
          victim: victim.id, attacker: attacker ? attacker.id : null, melee: !!attacker && direct,
          reach: attacker && direct ? World.reach(attacker, victim) : null,
          a: attacker ? World.snapshot(attacker) : null, v: World.snapshot(victim),
        });
        return;
      }
      case 'entity_status': {
        const p = this.players.get(params.entityId);
        if (!p) return;
        if (params.entityStatus === 3) this.emit(time, 'death', { player: p.id });
        else if (params.entityStatus === 35) this.emit(time, 'totem', { player: p.id });
        return;
      }
      case 'world_particles': {
        // (minecraft-protocol names particles itself; its table agrees with the server's for this one.)
        const type = params.particle && params.particle.type;
        const particle = typeof type === 'number' ? this.reg.particle_type[type] : type;
        if (particle !== 'sweep_attack') return;
        const p = this.nearest(params.x, params.y, params.z, 3);
        if (p) this.emit(time, 'sweep', { player: p.id });
        return;
      }
      case 'sound_effect': {
        const sound = params.sound && params.sound.soundId !== undefined ? this.reg.sound_event[params.sound.soundId]
          : params.sound && params.sound.data ? String(params.sound.data.soundName).replace(/^minecraft:/, '') : null;
        const kind = SOUNDS[sound];
        if (!kind) return;
        const p = this.nearest(params.x / 8, params.y / 8, params.z / 8, 2);
        if (p) this.emit(time, kind, { player: p.id });
        return;
      }
      case 'block_change': {
        const block = this.blockName(params.type);
        if (!PLACED.has(block)) return;
        const { x, y, z } = params.location;
        const p = this.nearest(x + 0.5, y + 0.5, z + 0.5, 6);
        this.emit(time, 'block', { block, x, y, z, player: p ? p.id : null });
        return;
      }
      case 'acknowledge_player_digging':
        // The server answering the recording player's placing or breaking a block (its arm swings too).
        if (this.selfId !== null) this.emit(time, 'blockWork', { player: this.selfId });
        return;
      case 'block_break_animation':
        // Someone breaking a block (a cobweb, say): the animation names them.
        if (this.players.has(params.entityId)) this.emit(time, 'blockWork', { player: params.entityId });
        return;
      case 'set_title_text':
        this.emit(time, 'title', { text: text(params.text) });
        return;
      case 'system_chat':
        if (!params.isActionBar) this.emit(time, 'chat', { text: text(params.content) });
        return;
      default:
    }
  }

  move(time, p, x, y, z, onGround, yaw256, yawDegrees) {
    const vy = y - p.y;
    if (p.onGround && !onGround && vy > 0.2) this.emit(time, 'jump', { player: p.id });
    p.vy = vy;
    p.x = x;
    p.y = y;
    p.z = z;
    p.onGround = onGround;
    if (yaw256 !== null && yaw256 !== undefined) p.yaw = yaw256 * 360 / 256;
    if (yawDegrees !== undefined) p.yaw = yawDegrees;
    this.emit(time, 'pos', { player: p.id, x, y, z, onGround, sprinting: p.sprinting });
    this.track(time, p);
  }

  blockName(state) {
    const blocks = this.reg.block_states;
    let lo = 0;
    let hi = blocks.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (state < blocks[mid][0]) hi = mid - 1;
      else if (state > blocks[mid][1]) lo = mid + 1;
      else return blocks[mid][2];
    }
    return null;
  }

  /** Who an entity id was on a server: { name, self }. */
  who(server, id) {
    return this.known.get(`${server}:${id}`) || { name: `entity ${id}`, self: false };
  }
}

module.exports = { World, FLAGS, text };
