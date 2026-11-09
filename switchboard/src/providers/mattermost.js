// Mattermost via the official REST API v4 and its websocket. The token is
// either a personal access token or the MMAUTHTOKEN session from SSO login.
const { EventEmitter } = require('events');
const WebSocket = require('ws');
const { replaceShortcodes, shortcodeToEmoji, nameForEmoji } = require('../emoji');

class MattermostProvider extends EventEmitter {
  // poll: check for new posts on a timer instead of the websocket. Servers
  // reject websockets from app origins (the phone build), so it polls there.
  constructor(baseUrl, token, { poll = false } = {}) {
    super();
    this.poll = poll;
    this.id = 'mattermost';
    this.label = 'Mattermost';
    this.base = baseUrl.replace(/\/+$/, '');
    this.token = token;
    this.convs = new Map();
    this.users = new Map();
    this.teams = new Map();
    this.backoff = 1000;
    this.stopped = false;
    this.posts = new Map(); // recently seen posts, to quote thread roots
  }

  conversations() {
    return [...this.convs.values()];
  }

  async api(method, path, body) {
    const res = await fetch(`${this.base}/api/v4${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await res.json().catch(() => null);
    if (res.status === 401) {
      const err = new Error('Mattermost session expired. Sign in again in Settings.');
      err.auth = true;
      throw err;
    }
    if (!res.ok) throw new Error(j?.message ? `Mattermost: ${j.message}` : `Mattermost HTTP ${res.status}`);
    return j;
  }

  async connect() {
    this.stopped = false;
    this.emit('status', { state: 'connecting' });
    try {
      this.me = await this.api('GET', '/users/me');
      this.users.set(this.me.id, this.me);
      await this.loadChannels();
      if (this.stopped) return;
      this.emit('status', { state: 'connected', user: this.me.username });
      if (this.poll) this.startPolling();
      else this.openSocket();
    } catch (err) {
      this.emit('status', { state: 'error', error: err.message });
      if (!err.auth && !this.stopped) this.retry = setTimeout(() => this.connect(), this.nextBackoff());
    }
  }

  disconnect() {
    this.stopped = true;
    clearTimeout(this.retry);
    clearInterval(this.pollTimer);
    const ws = this.ws;
    this.ws = null;
    ws?.close();
  }

  nextBackoff() {
    const b = this.backoff;
    this.backoff = Math.min(b * 2, 60000);
    return b;
  }

  async loadChannels() {
    const teams = await this.api('GET', '/users/me/teams');
    this.teams = new Map(teams.map(t => [t.id, t]));
    const channels = new Map();
    const members = new Map();
    for (const t of teams) {
      const [chs, mems] = await Promise.all([
        this.api('GET', `/users/me/teams/${t.id}/channels`),
        this.api('GET', `/users/me/teams/${t.id}/channels/members`),
      ]);
      for (const c of chs) if (!c.delete_at) channels.set(c.id, c); // DMs repeat per team
      for (const m of mems) members.set(m.channel_id, m);
    }
    await this.ensureUsers([...channels.values()].filter(c => c.type === 'D').map(c => this.otherUser(c)));
    this.convs.clear();
    for (const c of channels.values()) this.putConv(c, members.get(c.id));
    this.emit('conversations', this.conversations());
  }

  otherUser(c) {
    const [a, b] = c.name.split('__');
    return a === this.me.id ? b : a;
  }

  async ensureUsers(ids) {
    const missing = [...new Set(ids)].filter(id => id && !this.users.has(id));
    for (let i = 0; i < missing.length; i += 100) {
      const users = await this.api('POST', '/users/ids', missing.slice(i, i + 100));
      for (const u of users) this.users.set(u.id, u);
    }
  }

  displayName(u) {
    if (!u) return 'Unknown';
    return u.nickname || [u.first_name, u.last_name].filter(Boolean).join(' ') || u.username;
  }

  putConv(c, member) {
    let title = `#${c.display_name || c.name}`;
    let subtitle = this.teams.get(c.team_id)?.display_name || '';
    let kind = 'channel';
    if (c.type === 'D') {
      title = this.displayName(this.users.get(this.otherUser(c)));
      subtitle = 'Direct message';
      kind = 'dm';
    } else if (c.type === 'G') {
      title = c.display_name;
      subtitle = 'Group';
      kind = 'group';
    }
    const muted = member?.notify_props?.mark_unread === 'mention';
    this.convs.set(c.id, {
      id: c.id,
      key: `mattermost:${c.id}`,
      provider: 'mattermost',
      service: 'mattermost',
      title,
      subtitle,
      kind,
      avatar: null,
      muted,
      lastActivity: c.last_post_at || c.create_at,
      unread: !muted && !!member && c.total_msg_count > member.msg_count,
      unreadCount: !muted && member ? Math.max(0, c.total_msg_count - member.msg_count) : 0,
      mentions: member?.mention_count || 0,
    });
  }

  openSocket() {
    const ws = new WebSocket(`${this.base.replace(/^http/, 'ws')}/api/v4/websocket`, {
      headers: { Authorization: `Bearer ${this.token}` },
    });
    this.ws = ws;
    ws.on('open', () => {
      this.backoff = 1000;
      ws.send(JSON.stringify({ seq: 1, action: 'authentication_challenge', data: { token: this.token } }));
    });
    ws.on('message', raw => {
      let ev;
      try {
        ev = JSON.parse(raw);
      } catch {
        return;
      }
      this.onEvent(ev).catch(() => {});
    });
    ws.on('close', () => {
      if (ws !== this.ws || this.stopped) return;
      this.emit('status', { state: 'connecting', error: 'Reconnecting…' });
      this.retry = setTimeout(() => this.connect(), this.nextBackoff()); // reloads channels to catch up
    });
    ws.on('error', () => {});
  }

  reconnect() {
    if (this.stopped) return;
    if (this.poll) {
      this.pollOnce().catch(() => {});
      return;
    }
    const old = this.ws;
    this.ws = null;
    try {
      old?.close();
    } catch {}
    clearTimeout(this.retry);
    this.connect(); // reloads channels, so missed messages show as unread
  }

  async fetchMedia(ref) {
    const res = await fetch(`${this.base}/api/v4/files/${ref}`, { headers: { Authorization: `Bearer ${this.token}` } });
    if (!res.ok) throw new Error(`Mattermost: couldn't fetch the file (HTTP ${res.status})`);
    return { data: new Uint8Array(await res.arrayBuffer()), type: res.headers.get('content-type') || '' };
  }

  async upload(convId, files, text) {
    const form = new FormData();
    form.append('channel_id', convId);
    for (const f of files) form.append('files', new File([f.data], f.name, { type: f.type || 'application/octet-stream' }));
    const res = await fetch(`${this.base}/api/v4/files`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.token}`, 'X-Requested-With': 'XMLHttpRequest' },
      body: form,
    });
    const j = await res.json().catch(() => null);
    if (!res.ok) throw new Error(j?.message ? `Mattermost: ${j.message}` : `Mattermost HTTP ${res.status}`);
    const post = await this.api('POST', '/posts', { channel_id: convId, message: text || '', file_ids: j.file_infos.map(f => f.id) });
    return this.toMessage(post);
  }

  startPolling() {
    clearInterval(this.pollTimer);
    this.pollTimer = setInterval(() => this.pollOnce().catch(() => {}), 15000);
  }

  async pollOnce() {
    if (this.stopped || this.polling) return;
    this.polling = true;
    try {
      const before = new Map([...this.convs].map(([id, c]) => [id, c.lastActivity]));
      await this.loadChannels();
      for (const [id, conv] of this.convs) {
        const since = before.get(id);
        if (!since || conv.lastActivity <= since) continue;
        const r = await this.api('GET', `/channels/${id}/posts?since=${since}`);
        const posts = Object.values(r.posts)
          .filter(p => p.create_at > since && !p.delete_at)
          .sort((a, b) => a.create_at - b.create_at);
        await this.ensureUsers(posts.map(p => p.user_id));
        for (const p of posts) {
          const mentionsMe = (p.message || '').includes(`@${this.me.username}`);
          this.emit('message', { convId: id, message: this.toMessage(p, mentionsMe) });
        }
      }
    } finally {
      this.polling = false;
    }
  }

  async onEvent(ev) {
    if (ev.event === 'posted') {
      const post = JSON.parse(ev.data.post);
      if (!this.convs.has(post.channel_id)) await this.loadChannels();
      const conv = this.convs.get(post.channel_id);
      if (!conv) return;
      await this.ensureUsers([post.user_id]);
      const mentions = ev.data.mentions ? JSON.parse(ev.data.mentions) : [];
      const message = this.toMessage(post, mentions.includes(this.me.id));
      conv.lastActivity = post.create_at;
      if (!message.isSelf && !conv.muted) {
        conv.unread = true;
        conv.unreadCount += 1;
        if (message.mentionsMe) conv.mentions += 1;
      }
      this.emit('message', { convId: post.channel_id, message });
    } else if (ev.event === 'reaction_added' || ev.event === 'reaction_removed') {
      const r = JSON.parse(ev.data.reaction);
      const convId = ev.broadcast?.channel_id || this.posts.get(r.post_id)?.channel_id;
      if (!convId) return;
      this.emit('reaction', {
        convId,
        messageId: r.post_id,
        reaction: this.reactionInfo(r.emoji_name, 1, false),
        mine: r.user_id === this.me.id,
        delta: ev.event === 'reaction_added' ? 1 : -1,
      });
    } else if (
      ev.event === 'direct_added' ||
      ev.event === 'group_added' ||
      (ev.event === 'user_added' && ev.data?.user_id === this.me.id)
    ) {
      await this.loadChannels();
    }
  }

  toMessage(p, mentionsMe = false) {
    this.posts.set(p.id, p);
    if (this.posts.size > 5000) this.posts.delete(this.posts.keys().next().value);
    const root = p.root_id ? this.posts.get(p.root_id) : null;
    return {
      id: p.id,
      ts: p.create_at,
      author: { id: p.user_id, name: p.props?.override_username || this.displayName(this.users.get(p.user_id)), avatar: null },
      isSelf: p.user_id === this.me.id,
      mentionsMe,
      isReply: !!p.root_id && !root,
      replyTo: root
        ? { id: root.id, author: this.displayName(this.users.get(root.user_id)), text: root.message || (root.metadata?.files?.length ? '📎 Attachment' : '') }
        : null,
      system: (p.type || '').startsWith('system_'),
      text: this.postText(p),
      reactions: this.reactionsOf(p),
      attachments: [
        // Files need the login to fetch, so they carry a ref for fetchMedia instead of a public URL.
        ...(p.metadata?.files || []).map(f => ({
          name: f.name,
          size: f.size,
          ref: f.id,
          thumbRef: f.has_preview_image || /^image\//.test(f.mime_type || '') ? `${f.id}/preview` : null,
          isImage: /^image\//.test(f.mime_type || ''),
        })),
        ...this.imageEmbeds(p).map(url => ({ name: 'Image', url, isImage: true })),
      ],
    };
  }

  // Links to images (GIFs included) are shown as the image itself.
  imageEmbeds(p) {
    return (p.metadata?.embeds || []).filter(e => e.type === 'image' && e.url).map(e => e.url);
  }

  postText(p) {
    const text = replaceShortcodes(p.message || '');
    return this.imageEmbeds(p).includes(text.trim()) ? '' : text;
  }

  reactionsOf(p) {
    const byName = new Map();
    for (const r of p.metadata?.reactions || []) {
      const entry = byName.get(r.emoji_name) || this.reactionInfo(r.emoji_name, 0, false);
      entry.count += 1;
      if (r.user_id === this.me.id) entry.me = true;
      byName.set(r.emoji_name, entry);
    }
    return [...byName.values()];
  }

  reactionInfo(name, count, me) {
    return { key: name, emoji: shortcodeToEmoji(name), name, imageUrl: null, count, me };
  }

  // value: a reaction key (emoji name) or a Unicode emoji from the quick picker.
  async react(convId, postId, value, add) {
    const name = nameForEmoji(value);
    if (add) await this.api('POST', '/reactions', { user_id: this.me.id, post_id: postId, emoji_name: name });
    else await this.api('DELETE', `/users/${this.me.id}/posts/${postId}/reactions/${encodeURIComponent(name)}`);
    return this.reactionInfo(name, 1, add);
  }

  async fetchMessages(convId, before) {
    const r = await this.api('GET', `/channels/${convId}/posts?per_page=50${before ? `&before=${before}` : ''}`);
    const posts = r.order.map(id => r.posts[id]).filter(p => !p.delete_at).reverse();
    // The response also carries thread roots that fall outside this page.
    for (const p of Object.values(r.posts)) if (!p.delete_at) this.posts.set(p.id, p);
    await this.ensureUsers(Object.values(r.posts).map(p => p.user_id));
    return posts.map(p => this.toMessage(p));
  }

  async send(convId, text) {
    return this.toMessage(await this.api('POST', '/posts', { channel_id: convId, message: text }));
  }

  async markRead(convId) {
    const conv = this.convs.get(convId);
    if (conv) {
      conv.unread = false;
      conv.unreadCount = 0;
      conv.mentions = 0;
    }
    await this.api('POST', '/channels/members/me/view', { channel_id: convId }).catch(() => {});
  }
}

module.exports = MattermostProvider;
