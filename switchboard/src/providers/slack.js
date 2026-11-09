// Slack via a user token (xoxp) from the user's own Slack app, plus an
// app-level token (xapp) for Socket Mode live events. Slack has no bulk
// unread API, so recent activity is filled in gradually in the background
// and cached between launches.
const { EventEmitter } = require('events');
const WebSocket = require('ws');
const { replaceShortcodes, shortcodeToEmoji, nameForEmoji } = require('../emoji');

const API = 'https://slack.com/api/';
const AUTH_ERRORS = new Set(['invalid_auth', 'not_authed', 'token_revoked', 'token_expired', 'account_inactive']);
const SHOWN_SUBTYPES = new Set(['bot_message', 'file_share', 'thread_broadcast', 'me_message']);

const sleep = ms => new Promise(r => setTimeout(r, ms));
const tsToMs = ts => Math.round(parseFloat(ts) * 1000);
const escapeText = t => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

class SlackProvider extends EventEmitter {
  constructor({ teamId, teamName, userToken, appToken, cache }) {
    super();
    this.id = `slack-${teamId}`;
    this.label = teamName;
    this.teamName = teamName;
    this.userToken = userToken;
    this.appToken = appToken;
    this.cache = cache;
    const saved = cache.load() || {};
    this.users = new Map(Object.entries(saved.users || {})); // id -> { name, avatar }
    this.latest = new Map(Object.entries(saved.latest || {})); // conversation id -> latest message ts
    this.raw = new Map();
    this.convs = new Map();
    this.backoff = 1000;
    this.stopped = false;
  }

  conversations() {
    return [...this.convs.values()];
  }

  async call(method, params = {}, token = this.userToken) {
    const body = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null) body.set(k, v);
    for (let attempt = 0; attempt < 5; attempt++) {
      const res = await fetch(API + method, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
      });
      if (res.status === 429) {
        await sleep((Number(res.headers.get('retry-after')) || 5) * 1000);
        continue;
      }
      const j = await res.json();
      if (!j.ok) {
        const err = new Error(`Slack: ${j.error}`);
        err.auth = AUTH_ERRORS.has(j.error);
        throw err;
      }
      return j;
    }
    throw new Error('Slack is rate limiting; try again shortly');
  }

  async connect() {
    this.stopped = false;
    this.emit('status', { state: 'connecting' });
    try {
      const auth = await this.call('auth.test');
      this.me = auth.user_id;
      this.myName = auth.user;
      await this.ensureUsers([this.me]);
      await this.loadConversations();
      if (this.stopped) return;
      this.emit('status', { state: 'connected', user: auth.user });
      this.openSocket();
      this.background();
    } catch (err) {
      this.emit('status', { state: 'error', error: err.message });
      if (!err.auth && !this.stopped) this.retry = setTimeout(() => this.connect(), this.nextBackoff());
    }
  }

  disconnect() {
    this.stopped = true;
    clearTimeout(this.retry);
    clearTimeout(this.saveTimer);
    clearTimeout(this.emitTimer);
    const ws = this.ws;
    this.ws = null;
    ws?.close();
    this.saveCache();
  }

  nextBackoff() {
    const b = this.backoff;
    this.backoff = Math.min(b * 2, 60000);
    return b;
  }

  async loadConversations() {
    const list = [];
    let cursor;
    do {
      const r = await this.call('users.conversations', {
        types: 'public_channel,private_channel,mpim,im',
        exclude_archived: 'true',
        limit: '200',
        cursor,
      });
      list.push(...r.channels);
      cursor = r.response_metadata?.next_cursor;
    } while (cursor);
    this.raw = new Map(list.map(c => [c.id, c]));
    const prev = this.convs;
    this.convs = new Map();
    for (const c of list) this.putConv(c, prev.get(c.id));
    this.emit('conversations', this.conversations());
  }

  putConv(c, prev = this.convs.get(c.id)) {
    let title = `#${c.name}`;
    let subtitle = this.teamName;
    let kind = 'channel';
    if (c.is_im) {
      title = this.users.get(c.user)?.name || 'Direct message';
      subtitle = 'Direct message';
      kind = 'dm';
    } else if (c.is_mpim) {
      // mpdm-alice--bob--carol-1
      const names = c.name.replace(/^mpdm-/, '').replace(/-\d+$/, '').split('--').filter(n => n !== this.myName);
      title = names.join(', ') || 'Group';
      subtitle = 'Group';
      kind = 'group';
    }
    const latest = this.latest.get(c.id);
    this.convs.set(c.id, {
      id: c.id,
      key: `${this.id}:${c.id}`,
      provider: this.id,
      service: 'slack',
      title,
      subtitle,
      kind,
      avatar: c.is_im ? this.users.get(c.user)?.avatar || null : null,
      muted: false,
      lastActivity: latest ? tsToMs(latest) : (c.created || 0) * 1000,
      unread: prev?.unread || false,
      unreadCount: prev?.unreadCount || 0,
      mentions: prev?.mentions || 0,
    });
  }

  // Name DMs, then fill in recent activity and unread state, gently enough
  // to stay inside Slack's per-method rate limits.
  async background() {
    const rank = c => (c.is_im ? 0 : c.is_mpim ? 1 : 2);
    for (const c of this.raw.values()) {
      if (this.stopped) return;
      if (c.is_im && !this.users.has(c.user)) {
        await this.ensureUsers([c.user]);
        this.putConv(c);
        this.emitSoon();
      }
    }
    for (const c of [...this.raw.values()].sort((a, b) => rank(a) - rank(b))) {
      if (this.stopped) return;
      try {
        const [info, hist] = await Promise.all([
          this.call('conversations.info', { channel: c.id }),
          this.call('conversations.history', { channel: c.id, limit: '1' }),
        ]);
        const conv = this.convs.get(c.id);
        const top = hist.messages?.[0];
        if (conv && top) {
          this.latest.set(c.id, top.ts);
          conv.lastActivity = tsToMs(top.ts);
          const lastRead = info.channel?.last_read;
          if (!conv.unread) conv.unread = !!lastRead && parseFloat(top.ts) > parseFloat(lastRead) && top.user !== this.me;
          if (conv.unread) conv.unreadCount = Math.max(conv.unreadCount, await this.countSince(c.id, lastRead, info.channel));
          this.emitSoon();
        }
      } catch (err) {
        if (err.auth) return;
      }
      await sleep(1300);
    }
    this.saveCache();
  }

  // Slack reports the count for some conversations; otherwise count the
  // messages since the last-read mark (up to 100).
  async countSince(channel, lastRead, info) {
    if (typeof info?.unread_count_display === 'number') return info.unread_count_display;
    if (!lastRead) return 0;
    try {
      const hist = await this.call('conversations.history', { channel, oldest: lastRead, limit: '100' });
      return (hist.messages || []).filter(m => m.user !== this.me
        && (!m.subtype || SHOWN_SUBTYPES.has(m.subtype))
        && (!m.thread_ts || m.thread_ts === m.ts || m.subtype === 'thread_broadcast')).length;
    } catch {
      return 0;
    }
  }

  async ensureUsers(ids) {
    const missing = [...new Set(ids)].filter(id => id && !this.users.has(id));
    for (let i = 0; i < missing.length; i += 8) {
      await Promise.all(missing.slice(i, i + 8).map(async id => {
        try {
          const { user: u } = await this.call('users.info', { user: id });
          this.users.set(id, {
            name: u.profile?.display_name || u.real_name || u.name,
            avatar: u.profile?.image_72 || null,
          });
        } catch {}
      }));
    }
    if (missing.length) this.saveCacheSoon();
  }

  async openSocket() {
    let url;
    try {
      ({ url } = await this.call('apps.connections.open', {}, this.appToken));
    } catch (err) {
      this.emit('status', { state: 'error', error: `Live updates are off: ${err.message}. Check the app-level token.` });
      if (!err.auth && !this.stopped) this.retry = setTimeout(() => this.openSocket(), this.nextBackoff());
      return;
    }
    if (this.stopped) return;
    const ws = new WebSocket(url);
    this.ws = ws;
    ws.on('message', raw => {
      let m;
      try {
        m = JSON.parse(raw);
      } catch {
        return;
      }
      if (m.envelope_id) ws.send(JSON.stringify({ envelope_id: m.envelope_id })); // ack within 3s
      if (m.type === 'hello') this.backoff = 1000;
      else if (m.type === 'disconnect') ws.close();
      else if (m.type === 'events_api') this.onEvent(m.payload?.event).catch(() => {});
    });
    ws.on('close', () => {
      if (ws !== this.ws || this.stopped) return;
      this.retry = setTimeout(() => this.openSocket(), this.nextBackoff());
    });
    ws.on('error', () => {});
  }

  async onEvent(ev) {
    if ((ev?.type === 'reaction_added' || ev?.type === 'reaction_removed') && ev.item?.type === 'message') {
      if (!this.convs.has(ev.item.channel)) return;
      this.emit('reaction', {
        convId: ev.item.channel,
        messageId: ev.item.ts,
        reaction: this.reactionInfo(ev.reaction, 1, false),
        mine: ev.user === this.me,
        delta: ev.type === 'reaction_added' ? 1 : -1,
      });
      return;
    }
    if (ev?.type !== 'message') return;
    if (ev.subtype && !SHOWN_SUBTYPES.has(ev.subtype)) return; // edits, deletes, joins
    if (ev.thread_ts && ev.thread_ts !== ev.ts && ev.subtype !== 'thread_broadcast') return; // thread replies
    if (!this.convs.has(ev.channel)) await this.loadConversations();
    const conv = this.convs.get(ev.channel);
    if (!conv) return;
    await this.ensureUsers([ev.user, ...this.mentionedIds(ev.text)]);
    const message = this.toMessage(ev);
    this.latest.set(ev.channel, ev.ts);
    conv.lastActivity = message.ts;
    if (!message.isSelf && !conv.muted) {
      conv.unread = true;
      conv.unreadCount += 1;
      if (message.mentionsMe) conv.mentions += 1;
    }
    this.emit('message', { convId: ev.channel, message });
    this.saveCacheSoon();
  }

  mentionedIds(text) {
    return [...(text || '').matchAll(/<@([UW][A-Z0-9]+)/g)].map(m => m[1]);
  }

  toMessage(m) {
    const u = this.users.get(m.user);
    const replies = m.reply_count ? `\n💬 ${m.reply_count} ${m.reply_count === 1 ? 'reply' : 'replies'} in thread` : '';
    return {
      id: m.ts,
      ts: tsToMs(m.ts),
      author: {
        id: m.user || m.bot_id || 'unknown',
        name: u?.name || m.user_profile?.display_name || m.user_profile?.real_name || m.bot_profile?.name || m.username || 'Unknown',
        avatar: u?.avatar || m.user_profile?.image_72 || m.bot_profile?.icons?.image_72 || null,
      },
      isSelf: m.user === this.me,
      mentionsMe: (m.text || '').includes(`<@${this.me}>`),
      system: !!m.subtype && !SHOWN_SUBTYPES.has(m.subtype),
      text: this.renderText(m.text || '') + replies,
      reactions: (m.reactions || []).map(r => this.reactionInfo(r.name, r.count, r.users?.includes(this.me))),
      attachments: [
        // Slack files need the token to fetch: ref/thumbRef go through fetchMedia.
        ...(m.files || []).map(f => ({
          name: f.name || f.title || 'file',
          size: f.size,
          ref: f.url_private,
          thumbRef: f.thumb_480 || f.thumb_360 || null,
          url: f.permalink,
          isImage: /^image\//.test(f.mimetype || ''),
        })),
        // Unfurled links to images and GIFs
        ...(m.attachments || []).filter(a => a.image_url).map(a => ({ name: a.title || 'Image', url: a.image_url, isImage: true })),
      ],
    };
  }

  renderText(t) {
    return t
      .replace(/<@([UW][A-Z0-9]+)(?:\|([^>]+))?>/g, (_, id, label) => `@${label || this.users.get(id)?.name || 'user'}`)
      .replace(/<#([CG][A-Z0-9]+)(?:\|([^>]*))?>/g, (_, id, label) => (label ? `#${label}` : this.convs.get(id)?.title || '#channel'))
      .replace(/<!(here|channel|everyone)(?:\|[^>]*)?>/g, '@$1')
      .replace(/<!subteam\^[A-Z0-9]+(?:\|([^>]+))?>/g, (_, label) => label || '@group')
      .replace(/<!date\^\d+\^[^|>]*\|([^>]+)>/g, '$1')
      .replace(/<mailto:[^|>]+\|([^>]+)>/g, '$1')
      .replace(/<(https?:[^|>]+)\|([^>]+)>/g, (_, url, label) => (label === url ? url : `${label} (${url})`))
      .replace(/<(https?:[^>]+)>/g, '$1')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&')
      .replace(/:([\w+-]+(?:::skin-tone-\d)?):/g, match => replaceShortcodes(match));
  }

  async fetchMessages(convId, before) {
    const r = await this.call('conversations.history', {
      channel: convId,
      limit: '50',
      latest: before,
      inclusive: before ? 'false' : undefined,
    });
    const msgs = r.messages.reverse();
    await this.ensureUsers(msgs.flatMap(m => [m.user, ...this.mentionedIds(m.text)]));
    if (!before && msgs.length) this.latest.set(convId, msgs[msgs.length - 1].ts);
    return msgs.map(m => this.toMessage(m));
  }

  async send(convId, text) {
    const r = await this.call('chat.postMessage', { channel: convId, text: escapeText(text) });
    this.latest.set(convId, r.ts);
    return this.toMessage({ ...r.message, user: r.message.user || this.me });
  }

  reactionInfo(name, count, me) {
    return { key: name, emoji: shortcodeToEmoji(name), name, imageUrl: null, count, me: !!me };
  }

  // value: a reaction key (emoji name) or a Unicode emoji from the quick picker.
  async react(convId, ts, value, add) {
    const name = nameForEmoji(value);
    try {
      await this.call(add ? 'reactions.add' : 'reactions.remove', { channel: convId, timestamp: ts, name });
    } catch (err) {
      if (/missing_scope/.test(err.message)) {
        throw new Error('Your Slack app needs reaction permissions: update it with the new manifest from Settings and reinstall it.');
      }
      throw err;
    }
    return this.reactionInfo(name, 1, add);
  }

  reconnect() {
    if (this.stopped) return;
    const old = this.ws;
    this.ws = null;
    try {
      old?.close();
    } catch {}
    clearTimeout(this.retry);
    this.openSocket();
  }

  async fetchMedia(ref) {
    if (!/^https:\/\/([\w-]+\.)*slack(-edge)?\.com\//.test(ref)) throw new Error('Not a Slack file');
    const res = await fetch(ref, { headers: { Authorization: `Bearer ${this.userToken}` } });
    if (!res.ok) throw new Error(`Slack: couldn't fetch the file (HTTP ${res.status})`);
    return { data: new Uint8Array(await res.arrayBuffer()), type: res.headers.get('content-type') || '' };
  }

  // Slack's upload flow: get an upload URL per file, send the bytes, then share
  // them in the channel. The resulting message arrives over the socket.
  async upload(convId, files, text) {
    try {
      const done = [];
      for (const f of files) {
        const { upload_url: url, file_id: id } = await this.call('files.getUploadURLExternal', { filename: f.name, length: String(f.data.length) });
        const res = await fetch(url, { method: 'POST', body: f.data });
        if (!res.ok) throw new Error(`Slack upload failed (HTTP ${res.status})`);
        done.push({ id, title: f.name });
      }
      await this.call('files.completeUploadExternal', { files: JSON.stringify(done), channel_id: convId, initial_comment: text || undefined });
    } catch (err) {
      if (/missing_scope/.test(err.message)) {
        throw new Error('Your Slack app needs file permissions: update it with the new manifest from Settings and reinstall it.');
      }
      throw err;
    }
    return null;
  }

  async markRead(convId) {
    const conv = this.convs.get(convId);
    if (conv) {
      conv.unread = false;
      conv.unreadCount = 0;
      conv.mentions = 0;
    }
    const ts = this.latest.get(convId);
    if (ts) await this.call('conversations.mark', { channel: convId, ts }).catch(() => {});
  }

  emitSoon() {
    if (this.emitTimer) return;
    this.emitTimer = setTimeout(() => {
      this.emitTimer = null;
      this.emit('conversations', this.conversations());
    }, 1000);
  }

  saveCacheSoon() {
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.saveCache(), 3000);
  }

  saveCache() {
    this.cache.save({ users: Object.fromEntries(this.users), latest: Object.fromEntries(this.latest) });
  }
}

module.exports = SlackProvider;
