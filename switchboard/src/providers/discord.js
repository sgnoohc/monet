// Discord via a user token: REST for history/sending, the gateway for live
// messages. READY gives DMs, servers, channels and read state in one payload.
const { EventEmitter } = require('events');
const WebSocket = require('ws');

const API = 'https://discord.com/api/v9';
const GATEWAY = 'wss://gateway.discord.gg/?v=9&encoding=json';
const DISCORD_EPOCH = 1420070400000n;
const VIEW_CHANNEL = 1n << 10n;
const ADMINISTRATOR = 1n << 3n;
const TEXT_TYPES = new Set([0, 5]); // text, announcement
const DM = 1;
const GROUP_DM = 3;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const snowflakeTime = id => (id ? Number((BigInt(id) >> 22n) + DISCORD_EPOCH) : 0);
const makeNonce = () => String((BigInt(Date.now()) - DISCORD_EPOCH) << 22n);
const listEntries = x => (Array.isArray(x) ? x : x?.entries || []);
const userName = u => (u ? u.global_name || u.username : 'Unknown');
const emojiUrl = (id, animated) => `https://cdn.discordapp.com/emojis/${id}.${animated ? 'gif' : 'webp'}?size=96&quality=lossless`;
const MEDIA_EMBEDS = new Set(['gifv', 'image', 'video']);
const avatarUrl = u => (u?.avatar ? `https://cdn.discordapp.com/avatars/${u.id}/${u.avatar}.png?size=64` : null);

class DiscordProvider extends EventEmitter {
  constructor(token, { os = 'Mac OS X' } = {}) {
    super();
    this.os = os;
    this.id = 'discord';
    this.label = 'Discord';
    this.token = token;
    this.convs = new Map();
    this.users = new Map();
    this.readState = new Map();
    this.muted = { guilds: new Set(), channels: new Set() };
    this.me = null;
    this.ws = null;
    this.seq = null;
    this.sessionId = null;
    this.resumeUrl = GATEWAY;
    this.backoff = 1000;
    this.stopped = false;
  }

  connect() {
    this.stopped = false;
    this.emit('status', { state: 'connecting' });
    this.open();
  }

  disconnect() {
    this.stopped = true;
    clearInterval(this.heartbeat);
    const ws = this.ws;
    this.ws = null;
    ws?.close(1000);
  }

  conversations() {
    return [...this.convs.values()];
  }

  open() {
    const ws = new WebSocket(this.sessionId ? this.resumeUrl : GATEWAY);
    this.ws = ws;
    ws.on('message', raw => {
      if (ws === this.ws) this.onPayload(JSON.parse(raw));
    });
    ws.on('close', code => this.onClose(ws, code));
    ws.on('error', () => {}); // a close event always follows
  }

  // Drop the current socket and resume on a new one: used after sleep, when
  // the app comes back to the foreground, and when heartbeats go unanswered.
  reconnect() {
    if (this.stopped) return;
    const old = this.ws;
    this.ws = null;
    clearInterval(this.heartbeat);
    try {
      old?.close(4000);
    } catch {}
    this.open();
  }

  onClose(ws, code) {
    if (ws !== this.ws || this.stopped) return;
    clearInterval(this.heartbeat);
    if (code === 4004) {
      this.stopped = true;
      this.emit('status', { state: 'error', error: 'Discord rejected the token. Paste a fresh one in Settings.' });
      return;
    }
    if (code === 4007 || code === 4009) this.sessionId = null; // session can't be resumed
    this.emit('status', { state: 'connecting', error: 'Reconnecting…' });
    setTimeout(() => {
      if (!this.stopped) this.open();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, 60000);
  }

  sendOp(op, d) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ op, d }));
  }

  onPayload({ op, d, s, t }) {
    if (s != null) this.seq = s;
    switch (op) {
      case 10: // hello
        clearInterval(this.heartbeat);
        this.acked = true;
        this.heartbeat = setInterval(() => {
          if (!this.acked) return this.reconnect(); // no ack since the last beat: the connection is dead
          this.acked = false;
          this.sendOp(1, this.seq);
        }, d.heartbeat_interval);
        if (this.sessionId) {
          this.sendOp(6, { token: this.token, session_id: this.sessionId, seq: this.seq });
        } else {
          this.sendOp(2, {
            token: this.token,
            properties: { os: this.os, browser: 'Switchboard', device: '' },
            presence: { status: 'online', since: 0, activities: [], afk: false },
            compress: false,
          });
        }
        break;
      case 11: // heartbeat ack
        this.acked = true;
        break;
      case 1: // server asked for a heartbeat now
        this.sendOp(1, this.seq);
        break;
      case 7: // reconnect requested; onClose resumes
        this.ws.close(4000);
        break;
      case 9: // invalid session; d says whether it is resumable
        if (!d) this.sessionId = null;
        setTimeout(() => this.ws?.close(4000), 1000 + Math.random() * 4000);
        break;
      case 0:
        this.onDispatch(t, d);
        break;
    }
  }

  onDispatch(t, d) {
    switch (t) {
      case 'READY':
        this.onReady(d);
        break;
      case 'RESUMED':
        this.backoff = 1000;
        this.emit('status', { state: 'connected', user: userName(this.me) });
        break;
      case 'GUILD_CREATE':
        this.addGuild(d);
        this.emitConversations();
        break;
      case 'CHANNEL_CREATE':
        if (d.type === DM || d.type === GROUP_DM) {
          this.addPrivate(d);
          this.emitConversations();
        }
        break;
      case 'MESSAGE_REACTION_ADD':
      case 'MESSAGE_REACTION_REMOVE':
        if (this.convs.has(d.channel_id)) {
          this.emit('reaction', {
            convId: d.channel_id,
            messageId: d.message_id,
            reaction: this.reactionInfo(d.emoji, 1, false),
            mine: d.user_id === this.me?.id,
            delta: t === 'MESSAGE_REACTION_ADD' ? 1 : -1,
          });
        }
        break;
      case 'MESSAGE_CREATE':
        this.onMessage(d);
        break;
    }
  }

  onReady(d) {
    this.backoff = 1000;
    this.sessionId = d.session_id;
    if (d.resume_gateway_url) this.resumeUrl = `${d.resume_gateway_url}/?v=9&encoding=json`;
    this.me = d.user;
    this.users = new Map((d.users || []).map(u => [u.id, u]));
    this.readState = new Map(listEntries(d.read_state).map(r => [r.id, r]));
    this.muted = { guilds: new Set(), channels: new Set() };
    for (const s of listEntries(d.user_guild_settings)) {
      if (s.muted && s.guild_id) this.muted.guilds.add(s.guild_id);
      for (const o of s.channel_overrides || []) if (o.muted) this.muted.channels.add(o.channel_id);
    }
    this.convs.clear();
    for (const c of d.private_channels || []) this.addPrivate(c);
    (d.guilds || []).forEach((g, i) => this.addGuild(g, d.merged_members?.[i]?.[0]?.roles));
    this.emit('status', { state: 'connected', user: userName(d.user) });
    this.emitConversations();
  }

  emitConversations() {
    this.emit('conversations', this.conversations());
  }

  addPrivate(c) {
    const recipients = c.recipients || (c.recipient_ids || []).map(id => this.users.get(id)).filter(Boolean);
    this.putConv(c, {
      title: c.name || recipients.map(userName).join(', ') || 'Direct message',
      subtitle: c.type === DM ? 'Direct message' : 'Group',
      kind: c.type === DM ? 'dm' : 'group',
      avatar: c.type === DM ? avatarUrl(recipients[0]) : null,
      muted: this.muted.channels.has(c.id),
    });
  }

  addGuild(g, memberRoles) {
    if (g.unavailable) return;
    const name = g.name ?? g.properties?.name ?? 'Server';
    const icon = g.icon ?? g.properties?.icon;
    const roles = memberRoles ?? g.members?.find(m => m.user?.id === this.me?.id)?.roles;
    const guildMuted = this.muted.guilds.has(g.id);
    for (const ch of g.channels || []) {
      if (!TEXT_TYPES.has(ch.type) || !ch.last_message_id) continue;
      if (!this.canView(g, ch, roles)) continue;
      this.putConv(ch, {
        title: `#${ch.name}`,
        subtitle: name,
        kind: 'channel',
        avatar: icon ? `https://cdn.discordapp.com/icons/${g.id}/${icon}.png?size=64` : null,
        muted: guildMuted || this.muted.channels.has(ch.id) || this.muted.channels.has(ch.parent_id),
      });
    }
  }

  putConv(c, extra) {
    const rs = this.readState.get(c.id);
    const lastId = c.last_message_id || null;
    this.convs.set(c.id, {
      id: c.id,
      key: `discord:${c.id}`,
      provider: 'discord',
      service: 'discord',
      lastActivity: snowflakeTime(lastId),
      lastMessageId: lastId,
      // No read-state entry means the channel was never opened; don't flag it.
      unread: !extra.muted && !!rs && !!lastId && BigInt(lastId) > BigInt(rs.last_message_id || 0),
      mentions: rs?.mention_count || 0,
      ...extra,
    });
  }

  // Standard Discord permission resolution, limited to VIEW_CHANNEL.
  canView(g, ch, roles) {
    const roleList = g.roles || [];
    if (!roles || !roleList.length || !this.me) return true; // not enough data to decide
    if ((g.owner_id ?? g.properties?.owner_id) === this.me.id) return true;
    const rolePerms = new Map(roleList.map(r => [r.id, BigInt(r.permissions)]));
    let perms = rolePerms.get(g.id) || 0n; // @everyone role id == guild id
    for (const r of roles) perms |= rolePerms.get(r) || 0n;
    if (perms & ADMINISTRATOR) return true;
    const overwrites = ch.permission_overwrites || [];
    const apply = o => {
      if (o) perms = (perms & ~BigInt(o.deny)) | BigInt(o.allow);
    };
    apply(overwrites.find(o => o.id === g.id));
    let allow = 0n;
    let deny = 0n;
    for (const o of overwrites) {
      if (o.type === 0 && o.id !== g.id && roles.includes(o.id)) {
        allow |= BigInt(o.allow);
        deny |= BigInt(o.deny);
      }
    }
    perms = (perms & ~deny) | allow;
    apply(overwrites.find(o => o.type === 1 && o.id === this.me.id));
    return (perms & VIEW_CHANNEL) !== 0n;
  }

  onMessage(m) {
    const conv = this.convs.get(m.channel_id);
    if (!conv) return;
    const message = this.toMessage(m);
    conv.lastActivity = snowflakeTime(m.id);
    conv.lastMessageId = m.id;
    if (!message.isSelf && !conv.muted) {
      conv.unread = true;
      if (message.mentionsMe) conv.mentions += 1;
    }
    this.emit('message', { convId: m.channel_id, message });
  }

  toMessage(m) {
    return {
      id: m.id,
      ts: Date.parse(m.timestamp),
      author: { id: m.author.id, name: m.member?.nick || userName(m.author), avatar: avatarUrl(m.author) },
      isSelf: m.author.id === this.me?.id,
      mentionsMe: !!m.mention_everyone || (m.mentions || []).some(u => u.id === this.me?.id),
      replyTo: m.type === 19 ? this.replyPreview(m.referenced_message) : null,
      text: this.renderText(m),
      customEmoji: this.customEmoji(m.content),
      reactions: (m.reactions || []).map(r => this.reactionInfo(r.emoji, r.count, r.me)),
      attachments: [
        ...(m.attachments || []).map(a => ({
          name: a.filename,
          url: a.url,
          size: a.size,
          isImage: /^image\//.test(a.content_type || ''),
          isVideo: /^video\//.test(a.content_type || ''),
        })),
        // GIFs (Tenor/Giphy links) and image links arrive as embeds.
        ...(m.embeds || []).filter(e => MEDIA_EMBEDS.has(e.type)).map(e => (e.video?.url && e.type !== 'image'
          ? { name: 'GIF', url: e.video.proxy_url || e.video.url, isVideo: true, poster: e.thumbnail?.proxy_url }
          : { name: 'Image', url: e.thumbnail?.proxy_url || e.thumbnail?.url || e.image?.url || e.url, isImage: true })),
      ],
    };
  }

  // name -> image URL for the custom emoji used in a message (shown as :name: in text).
  customEmoji(content) {
    const map = {};
    for (const [, animated, name, id] of (content || '').matchAll(/<(a?):(\w+):(\d+)>/g)) map[name] = emojiUrl(id, !!animated);
    return map;
  }

  reactionInfo(e, count, me) {
    return {
      key: e.id ? `${e.name}:${e.id}` : e.name,
      emoji: e.id ? null : e.name,
      name: e.name,
      imageUrl: e.id ? emojiUrl(e.id, e.animated) : null,
      count,
      me: !!me,
    };
  }

  // Discord sends the replied-to message inline; null means it was deleted.
  replyPreview(ref) {
    if (!ref) return { id: null, author: '', text: 'Original message was deleted' };
    return {
      id: ref.id,
      author: ref.member?.nick || userName(ref.author),
      text: this.renderText(ref) || (ref.attachments?.length ? '📎 Attachment' : ''),
    };
  }

  renderText(m) {
    const names = new Map((m.mentions || []).map(u => [u.id, userName(u)]));
    let text = (m.content || '')
      .replace(/<@!?(\d+)>/g, (_, id) => `@${names.get(id) || 'user'}`)
      .replace(/<#(\d+)>/g, (_, id) => this.convs.get(id)?.title || '#channel')
      .replace(/<@&\d+>/g, '@role')
      .replace(/<a?:(\w+):\d+>/g, ':$1:');
    // A message that is only a GIF/image link shows just the media, as in Discord.
    const media = (m.embeds || []).filter(e => MEDIA_EMBEDS.has(e.type));
    if (media.length && media.some(e => e.url === text.trim())) text = '';
    const textEmbeds = (m.embeds || []).filter(e => !MEDIA_EMBEDS.has(e.type));
    if (!text && textEmbeds.length) {
      text = textEmbeds.map(e => [e.title, e.description, e.url].filter(Boolean).join('\n')).join('\n\n');
    }
    if (!text && m.sticker_items?.length) text = `[sticker: ${m.sticker_items[0].name}]`;
    if (!text && m.type === 7) text = '[joined the server]';
    return text;
  }

  async api(method, path, body) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const res = await fetch(API + path, {
        method,
        headers: { Authorization: this.token, 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (res.status === 429) {
        const j = await res.json().catch(() => ({}));
        await sleep((j.retry_after || 1) * 1000);
        continue;
      }
      if (res.status === 204) return null;
      const j = await res.json().catch(() => null);
      if (!res.ok) throw new Error(j?.message ? `Discord: ${j.message}` : `Discord HTTP ${res.status}`);
      return j;
    }
    throw new Error('Discord is rate limiting; try again shortly');
  }

  async fetchMessages(convId, before) {
    const list = await this.api('GET', `/channels/${convId}/messages?limit=50${before ? `&before=${before}` : ''}`);
    return list.reverse().map(m => this.toMessage(m));
  }

  async send(convId, text) {
    const m = await this.api('POST', `/channels/${convId}/messages`, { content: text, tts: false, nonce: makeNonce() });
    return this.toMessage(m);
  }

  // key: a Unicode emoji or "name:id" for a custom one.
  async react(convId, messageId, key, add) {
    await this.api(add ? 'PUT' : 'DELETE', `/channels/${convId}/messages/${messageId}/reactions/${encodeURIComponent(key)}/@me`);
    const [name, id] = key.split(':');
    return this.reactionInfo(id ? { name, id } : { name: key }, 1, add);
  }

  // Discord's own GIF search (Tenor), as used by its GIF picker.
  // files: [{ name, type, data: Uint8Array }]; text goes along as the message.
  async upload(convId, files, text) {
    const form = new FormData();
    form.append('payload_json', JSON.stringify({
      content: text || '',
      nonce: makeNonce(),
      attachments: files.map((f, i) => ({ id: i, filename: f.name })),
    }));
    files.forEach((f, i) => form.append(`files[${i}]`, new File([f.data], f.name, { type: f.type || 'application/octet-stream' })));
    const res = await fetch(`${API}/channels/${convId}/messages`, { method: 'POST', headers: { Authorization: this.token }, body: form });
    const j = await res.json().catch(() => null);
    if (res.status === 413) throw new Error('Discord: that file is too large (the limit is 10 MB without Nitro)');
    if (!res.ok) throw new Error(j?.message ? `Discord: ${j.message}` : `Discord HTTP ${res.status}`);
    return this.toMessage(j);
  }

  async searchGifs(query) {
    const params = 'media_format=mp4&provider=tenor&locale=en-US';
    const list = query
      ? await this.api('GET', `/gifs/search?q=${encodeURIComponent(query)}&${params}`)
      : await this.api('GET', `/gifs/trending-gifs?${params}`);
    return (Array.isArray(list) ? list : list.gifs || []).map(g => ({ url: g.url, preview: g.src, gif: g.gif_src, width: g.width, height: g.height }));
  }

  async markRead(convId) {
    const conv = this.convs.get(convId);
    if (!conv) return;
    conv.unread = false;
    conv.mentions = 0;
    if (!conv.lastMessageId) return;
    this.readState.set(convId, { id: convId, last_message_id: conv.lastMessageId });
    await this.api('POST', `/channels/${convId}/messages/${conv.lastMessageId}/ack`, { token: null }).catch(() => {});
  }
}

module.exports = DiscordProvider;
