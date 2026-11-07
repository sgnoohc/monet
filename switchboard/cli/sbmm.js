#!/usr/bin/env node
// sbmm: Switchboard's Mattermost in the terminal. Chat list on the left,
// conversation on the right, message line at the bottom. Reuses the desktop
// app's Mattermost provider, login (via the macOS Keychain), groups and nicknames.
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const zlib = require('zlib');
const readline = require('readline');
const { execFileSync } = require('child_process');
const MattermostProvider = require('../src/providers/mattermost');
const DemoProvider = require('../src/providers/demo');

const DEFAULT_URL = 'https://mattermost.web.cern.ch';
// The desktop app's data lives here on a Mac; other machines use the saved login.
const APP_DIR = path.join(os.homedir(), 'Library', 'Application Support', 'Switchboard');
const CONFIG_DIR = path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'sbmm');
const CLI_CONFIG = path.join(CONFIG_DIR, 'config.json');
const RUN_GAP = 5 * 60000;
const TIME_GAP = 60 * 60000;
const HELP = '^N/^P next/prev chat · PgUp/PgDn scroll · ^F find · ^L latest first · /react 👍 · ^C quit';
const USAGE = `sbmm: Mattermost in the terminal

  sbmm                  open the chat list (default)
  sbmm --login [CODE]   save a login: a code from --export-login, or a personal access token
  sbmm --login -        read the code from stdin, e.g.
                          sbmm --export-login | ssh otherhost sbmm --login -
  sbmm --export-login   print this machine's login (and groups/nicknames) as a code
  sbmm --logout         forget the saved login
  sbmm --demo           sample chats, no account

Environment: SBMM_URL and SBMM_TOKEN override the saved login.`;

const readJson = (file, fallback) => {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
};

const appConfig = process.platform === 'darwin' ? readJson(path.join(APP_DIR, 'config.json'), {}) : {};
const saved = readJson(CLI_CONFIG, {});

// ---------- login ----------

// The desktop app encrypts tokens with Electron safeStorage (Chromium "v10":
// AES-128-CBC, key = PBKDF2 of the Keychain password). macOS asks once
// before letting this read the Keychain item.
function decryptFromApp(b64) {
  const password = execFileSync('security', ['find-generic-password', '-w', '-s', 'Switchboard Safe Storage'], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
  }).trim();
  const data = Buffer.from(b64, 'base64');
  if (data.subarray(0, 3).toString() !== 'v10') throw new Error('unknown encryption format');
  const key = crypto.pbkdf2Sync(password, 'saltysalt', 1003, 16, 'sha1');
  const decipher = crypto.createDecipheriv('aes-128-cbc', key, Buffer.alloc(16, ' '));
  return Buffer.concat([decipher.update(data.subarray(3)), decipher.final()]).toString('utf8');
}

function appLogin() {
  const secret = readJson(path.join(APP_DIR, 'secrets.json'), {}).mattermost;
  if (!secret || process.platform !== 'darwin') return null;
  process.stderr.write('Using your Mattermost login from the Switchboard app (macOS may ask to allow Keychain access)…\n');
  return { url: appConfig.mattermost?.url || DEFAULT_URL, token: decryptFromApp(secret) };
}

// Order: environment, saved login (sbmm --login), the Mac app's Keychain.
function findLogin() {
  if (process.env.SBMM_TOKEN) return { url: process.env.SBMM_URL || saved.url || DEFAULT_URL, token: process.env.SBMM_TOKEN };
  if (saved.token) return { url: saved.url || DEFAULT_URL, token: saved.token };
  try {
    return appLogin();
  } catch (err) {
    process.stderr.write(`Couldn't read it from the Keychain (${String(err.message).split('\n')[0]}).\n`);
    return null;
  }
}

function prompt(question, hidden = false) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr, terminal: true });
  rl._writeToOutput = text => {
    if (!rl.muted) rl.output.write(text);
  };
  return new Promise(resolve => {
    rl.question(question, answer => {
      if (hidden) process.stderr.write('\n');
      rl.close();
      resolve(answer.trim());
    });
    rl.muted = hidden;
  });
}

const readStdin = () => new Promise(resolve => {
  let data = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => (data += chunk));
  process.stdin.on('end', () => resolve(data.trim()));
});

// "sbmm1:" + base64(deflate-raw(JSON {url, token, view})). It is a password: treat it like one.
const encodeLogin = data => `sbmm1:${zlib.deflateRawSync(JSON.stringify(data)).toString('base64')}`;
const decodeLogin = code => JSON.parse(zlib.inflateRawSync(Buffer.from(code.slice(6), 'base64')).toString('utf8'));

async function checkLogin(url, token) {
  const res = await fetch(`${url.replace(/\/+$/, '')}/api/v4/users/me`, { headers: { Authorization: `Bearer ${token}` } });
  if (res.status === 401) throw new Error('Mattermost rejected that login (expired or wrong token)');
  if (!res.ok) throw new Error(`Mattermost answered HTTP ${res.status}`);
  return (await res.json()).username;
}

async function login(code) {
  if (code === '-') code = await readStdin();
  if (!code && !process.stdin.isTTY) throw new Error('No login code on stdin');
  if (!code) code = await prompt('Paste the code from `sbmm --export-login`, or press Enter to use a personal access token: ', true);
  let data;
  if (code.startsWith('sbmm1:')) {
    data = decodeLogin(code);
  } else {
    const url = (await prompt(`Mattermost server [${saved.url || DEFAULT_URL}]: `)) || saved.url || DEFAULT_URL;
    const token = code || await prompt('Personal access token (hidden): ', true);
    if (!token) throw new Error('No token given');
    data = { url, token, view: saved.view };
  }
  const user = await checkLogin(data.url, data.token);
  fs.mkdirSync(CONFIG_DIR, { recursive: true, mode: 0o700 });
  fs.writeFileSync(CLI_CONFIG, JSON.stringify(data), { mode: 0o600 });
  process.stderr.write(`Logged in as @${user} on ${data.url}. Saved in ${CLI_CONFIG.replace(os.homedir(), '~')}.\n`);
}

function exportLogin() {
  const found = findLogin();
  if (!found) throw new Error('No Mattermost login on this machine to export');
  process.stdout.write(`${encodeLogin({ ...found, view: appConfig.view || saved.view })}\n`);
  if (process.stdout.isTTY) {
    process.stderr.write('\nThat code is your Mattermost login. Paste it only into your own machine (sbmm --login), or pipe it:\n  sbmm --export-login | ssh otherhost sbmm --login -\n');
  }
}

async function credentials() {
  const found = findLogin();
  if (found) return found;
  process.stderr.write('No Mattermost login on this machine yet.\n');
  await login('');
  return readJson(CLI_CONFIG, {});
}

// ---------- text measuring ----------

const segmenter = new Intl.Segmenter();
const graphemes = s => Array.from(segmenter.segment(s), x => x.segment);
const WIDE = /[ᄀ-ᅟ⺀-〾ぁ-㏿㐀-䶿一-鿿ꀀ-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]|[\u{1F000}-\u{1FAFF}\u{20000}-\u{3FFFD}]/u;

function charWidth(g) {
  const cp = g.codePointAt(0);
  if (cp < 32) return 0;
  if (g.includes('️') && /\p{Extended_Pictographic}/u.test(g)) return 2;
  return WIDE.test(g) ? 2 : 1;
}

const width = s => graphemes(s).reduce((w, g) => w + charWidth(g), 0);

function truncate(s, max) {
  if (width(s) <= max) return s;
  let out = '';
  let w = 0;
  for (const g of graphemes(s)) {
    if (w + charWidth(g) > max - 1) break;
    out += g;
    w += charWidth(g);
  }
  return `${out}…`;
}

const pad = (s, w) => s + ' '.repeat(Math.max(0, w - width(s)));

function wrap(text, max) {
  const lines = [];
  for (const para of text.split('\n')) {
    let line = '';
    for (const word of para.split(/(\s+)/)) {
      if (!word) continue;
      if (width(line + word) <= max) {
        line += word;
        continue;
      }
      if (line.trim()) lines.push(line.trimEnd());
      line = /^\s+$/.test(word) ? '' : word;
      while (width(line) > max) { // a word longer than the line
        let head = '';
        for (const g of graphemes(line)) {
          if (width(head + g) > max) break;
          head += g;
        }
        lines.push(head);
        line = line.slice(head.length);
      }
    }
    lines.push(line.trimEnd());
  }
  return lines;
}

// Messages come from other people: never let them send terminal escape codes.
const clean = s => (s || '').replace(/\t/g, '    ').replace(/[\u0000-\u0008\u000B-\u001F\u007F-\u009F]/g, '');

// ---------- terminal output ----------

const CSI = '\x1b[';
const sgr = (...codes) => `${CSI}${codes.join(';')}m`;
const RESET = sgr(0);
const DIM = sgr(2);
const BOLD = sgr(1);
const fg = n => sgr(38, 5, n);
const bg = n => sgr(48, 5, n);
const NAME_COLORS = [39, 41, 75, 114, 141, 168, 173, 179, 204, 208];
const nameColor = s => NAME_COLORS[([...s].reduce((n, c) => (n * 31 + c.codePointAt(0)) | 0, 0) >>> 0) % NAME_COLORS.length];
// The local time zone, passed explicitly to every date format: Bun-built
// binaries ignore TZ paths like /usr/share/zoneinfo/X and fall back to UTC.
const ZONE = (() => {
  const fromPath = p => /zoneinfo\/(.+)$/.exec(p || '')?.[1];
  const tz = process.env.TZ?.replace(/^:/, '');
  let zone = tz?.includes('zoneinfo/') ? fromPath(tz) : tz;
  if (!zone) {
    try {
      zone = fromPath(fs.readlinkSync('/etc/localtime'));
    } catch {}
  }
  try {
    new Intl.DateTimeFormat('en', { timeZone: zone });
    return zone;
  } catch {
    return undefined;
  }
})();

const formatTime = ts => new Date(ts).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: ZONE });
const dayKey = ts => new Date(ts).toLocaleDateString('en-CA', { timeZone: ZONE });

function formatDay(ts) {
  if (dayKey(ts) === dayKey(Date.now())) return 'Today';
  if (dayKey(ts) === dayKey(Date.now() - 864e5)) return 'Yesterday';
  return new Date(ts).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', timeZone: ZONE });
}

// ---------- state ----------

const view = {
  mode: 'all',
  keys: [],
  groups: [],
  assign: {},
  nicknames: {},
  ...(appConfig.view || saved.view),
};
const hiddenKeys = new Set(view.keys);

const state = {
  provider: null,
  status: { state: 'connecting' },
  convs: new Map(), // key -> conversation
  messages: new Map(), // key -> [message]
  exhausted: new Set(),
  open: null,
  scroll: 0, // lines scrolled up from the bottom
  input: '',
  cursor: 0, // index into graphemes(input)
  find: null, // string while ^F find is active
  flat: !!view.flat,
  notice: '',
  loadingOlder: false,
};

const title = c => clean(view.nicknames[c.key] || c.title);
const isVisible = c => (view.mode === 'all' ? !hiddenKeys.has(c.key) : hiddenKeys.has(c.key));
const isListed = c => isVisible(c) || c.unread || c.mentions > 0 || c.key === state.open;
const groupOf = key => (view.groups.some(g => g.id === view.assign[key]) ? view.assign[key] : '');

function listedConvs() {
  const q = state.find?.toLowerCase();
  return [...state.convs.values()]
    .filter(c => (q ? `${title(c)} ${c.title} ${c.subtitle}`.toLowerCase().includes(q) : isListed(c)))
    .sort((a, b) => (b.lastActivity || 0) - (a.lastActivity || 0));
}

// Sidebar rows in display order: group headers (from the desktop app) and chats.
function sidebarRows() {
  const list = listedConvs();
  if (state.flat || state.find || !view.groups.length) return list.map(conv => ({ conv }));
  const rows = [];
  for (const g of [...view.groups, { id: '', name: 'Other' }]) {
    const items = list.filter(c => groupOf(c.key) === g.id);
    if (!items.length) continue;
    rows.push({ head: g.name, unread: items.filter(c => c.unread || c.mentions).length });
    rows.push(...items.map(conv => ({ conv })));
  }
  return rows;
}

const chatOrder = () => sidebarRows().filter(r => r.conv).map(r => r.conv.key);

// ---------- rendering ----------

const sameRun = (a, b) => a && b && !a.system && !b.system && a.isSelf === b.isSelf &&
  a.author.id === b.author.id && b.ts - a.ts < RUN_GAP && dayKey(a.ts) === dayKey(b.ts);

// Every message as screen lines for a pane `pw` columns wide.
function messageLines(msgs, pw, group) {
  const out = [];
  const max = Math.max(16, Math.floor(pw * 0.72) - 2);
  const center = (text, style) => {
    const t = truncate(text, pw - 2);
    out.push(' '.repeat(Math.max(0, Math.floor((pw - width(t)) / 2))) + style + t + RESET);
  };
  const place = (content, w, mine) => (mine ? ' '.repeat(Math.max(0, pw - 1 - w)) : ' ') + content;
  msgs.forEach((m, i) => {
    const prev = msgs[i - 1];
    if (!prev || dayKey(prev.ts) !== dayKey(m.ts) || m.ts - prev.ts > TIME_GAP) {
      out.push('');
      center(`${formatDay(m.ts)} ${formatTime(m.ts)}`, DIM);
    }
    if (m.system) {
      center(clean(m.text), DIM + sgr(3));
      return;
    }
    const first = !sameRun(prev, m);
    if (first) out.push('');
    if (first && group && !m.isSelf) {
      const name = clean(m.author.name);
      out.push(` ${fg(nameColor(name))}${BOLD}${truncate(name, pw - 2)}${RESET}`);
    }
    if (m.replyTo) {
      const quote = truncate(`↪ ${clean(m.replyTo.author)}: ${clean(m.replyTo.text).replace(/\n/g, ' ')}`, max);
      out.push(place(DIM + quote + RESET, width(quote), m.isSelf));
    }
    const text = clean(m.text);
    const body = text ? wrap(text, max) : [];
    for (const a of m.attachments || []) body.push(truncate(`${a.isImage ? '🖼 ' : a.isVideo ? '🎞 ' : '📎 '}${clean(a.name)}  ${a.url}`, max));
    if (m.isReply && !m.replyTo) body.unshift('↪ reply in thread');
    if (body.length) {
      const bw = Math.max(...body.map(width));
      const colors = m.isSelf ? bg(27) + fg(231) : m.mentionsMe ? bg(94) + fg(231) : bg(237) + fg(255);
      for (const line of body) out.push(place(`${colors} ${pad(line, bw)} ${RESET}`, bw + 2, m.isSelf));
    }
    if (m.reactions?.length) {
      const parts = m.reactions.map(r => `${r.me ? fg(45) : DIM}${r.emoji || `:${clean(r.name)}:`} ${r.count}${RESET}`);
      const plain = m.reactions.map(r => `${r.emoji || `:${r.name}:`} ${r.count}`).join('  ');
      out.push(place(parts.join('  '), width(plain), m.isSelf));
    }
  });
  return out;
}

let renderQueued = false;
function render() {
  if (renderQueued) return;
  renderQueued = true;
  setImmediate(draw);
}

function draw() {
  renderQueued = false;
  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  const sw = Math.max(22, Math.min(36, Math.floor(cols * 0.3)));
  const pw = cols - sw - 1;
  const x0 = sw + 2;
  const mh = rows - 4;
  let out = `${CSI}?25l`;
  const at = (row, col) => `${CSI}${row};${col}H`;

  // Sidebar
  const s = state.status;
  const dot = s.state === 'connected' ? fg(41) : s.state === 'error' ? fg(196) : fg(214);
  out += at(1, 1) + BOLD + pad(' Mattermost', sw - 2) + RESET + dot + '● ' + RESET;
  const srows = sidebarRows();
  const openIdx = srows.findIndex(r => r.conv?.key === state.open);
  const listH = rows - 2;
  const top = Math.max(0, Math.min(openIdx - Math.floor(listH / 2), srows.length - listH));
  for (let i = 0; i < listH; i++) {
    const r = srows[top + i];
    let cell = ' '.repeat(sw);
    if (r?.head) {
      const label = ` ${r.head.toUpperCase()}`;
      cell = DIM + BOLD + pad(truncate(label, sw - 4), sw - 4) + RESET + (r.unread ? fg(39) + pad(String(r.unread), 4) + RESET : ' '.repeat(4));
    } else if (r?.conv) {
      const c = r.conv;
      const badge = c.mentions ? `${fg(196)}${c.mentions}${RESET}` : c.unread ? `${fg(39)}●${RESET}` : ' ';
      const badgeW = c.mentions ? String(c.mentions).length : 1;
      const name = truncate(title(c), sw - 3 - badgeW);
      const bodyStyle = c.key === state.open ? sgr(7) : c.unread || c.mentions ? BOLD : c.muted ? DIM : '';
      cell = `${bodyStyle} ${pad(name, sw - 2 - badgeW)}${RESET}${badge} `;
    }
    out += at(2 + i, 1) + cell;
  }
  for (let row = 1; row <= rows - 1; row++) out += at(row, sw + 1) + DIM + '│' + RESET;

  // Header
  const conv = state.convs.get(state.open);
  const head = conv
    ? `${BOLD}${truncate(title(conv), pw - 2)}${RESET}${DIM}  ${truncate(title(conv) !== clean(conv.title) ? `${clean(conv.title)} · ${clean(conv.subtitle)}` : clean(conv.subtitle), Math.max(0, pw - width(title(conv)) - 4))}${RESET}`
    : `${DIM}Pick a chat with ^N / ^P${RESET}`;
  out += `${at(1, x0)} ${head}${RESET}${CSI}K`;
  out += at(2, x0) + DIM + '─'.repeat(pw) + RESET;

  // Messages, bottom-aligned, offset by state.scroll
  const msgs = state.messages.get(state.open);
  let lines = [];
  if (conv && !msgs) lines = [`${DIM} Loading…${RESET}`];
  else if (msgs) lines = messageLines(msgs, pw, conv.kind !== 'dm');
  if (msgs && state.exhausted.has(state.open)) lines.unshift(`${DIM} Beginning of conversation${RESET}`);
  state.scroll = Math.max(0, Math.min(state.scroll, lines.length - mh));
  const end = lines.length - state.scroll;
  const visible = lines.slice(Math.max(0, end - mh), end);
  for (let i = 0; i < mh; i++) {
    const line = visible[i - (mh - visible.length)] ?? '';
    out += `${at(3 + i, x0)}${line}${RESET}${CSI}K`;
  }
  if (state.scroll > 0) out += at(3, x0 + pw - 14) + DIM + `↑ ${state.scroll} more ↓` + RESET;
  if (msgs && end - mh <= 0 && !state.exhausted.has(state.open)) loadOlder();

  // Input line and help
  const prompt = state.find != null ? `${fg(214)}find:${RESET} ` : `${fg(39)}›${RESET} `;
  const promptW = state.find != null ? 6 : 2;
  const text = state.find ?? state.input;
  const g = graphemes(text);
  const before = state.find != null ? text : g.slice(0, state.cursor).join('');
  const room = pw - promptW - 2;
  let shown = text;
  let caret = width(before);
  if (caret > room) { // keep the caret in view
    const cut = graphemes(before);
    while (width(cut.join('')) > room) cut.shift();
    shown = cut.join('') + g.slice(state.find != null ? g.length : state.cursor).join('');
    caret = width(cut.join(''));
  }
  out += at(rows - 1, x0) + DIM + '─'.repeat(pw) + RESET;
  out += `${at(rows, 1)}${DIM}${truncate(state.notice || HELP, sw - 1)}${RESET}${CSI}K`;
  out += `${at(rows, x0)} ${prompt}${truncate(shown, room + 1)}${CSI}K`;
  out += `${at(rows, x0 + 1 + promptW + caret)}${CSI}?25h`;
  process.stdout.write(out);
}

// ---------- actions ----------

function noteFor(text, ms = 4000) {
  state.notice = text;
  render();
  clearTimeout(noteFor.timer);
  noteFor.timer = setTimeout(() => {
    state.notice = '';
    render();
  }, ms);
}

async function openConv(key) {
  const conv = state.convs.get(key);
  if (!conv) return;
  state.open = key;
  state.scroll = 0;
  if (conv.unread || conv.mentions) {
    conv.unread = false;
    conv.mentions = 0;
    state.provider.markRead(conv.id).catch(() => {});
  }
  render();
  try {
    const fresh = await state.provider.fetchMessages(conv.id);
    const lastTs = fresh.length ? fresh[fresh.length - 1].ts : 0;
    const extra = (state.messages.get(key) || []).filter(m => m.ts > lastTs && !fresh.some(f => f.id === m.id));
    state.messages.set(key, [...fresh, ...extra]);
    if (fresh.length < 50) state.exhausted.add(key);
  } catch (err) {
    noteFor(err.message);
  }
  render();
}

async function loadOlder() {
  const key = state.open;
  const list = state.messages.get(key);
  if (!list?.length || state.loadingOlder || state.exhausted.has(key)) return;
  state.loadingOlder = true;
  try {
    const older = await state.provider.fetchMessages(state.convs.get(key).id, list[0].id);
    if (older.length < 50) state.exhausted.add(key);
    const ids = new Set(list.map(m => m.id));
    list.unshift(...older.filter(m => !ids.has(m.id))); // scroll is from the bottom, so the view stays put
  } catch (err) {
    noteFor(err.message);
  } finally {
    state.loadingOlder = false;
    render();
  }
}

function step(delta) {
  const order = chatOrder();
  if (!order.length) return;
  const i = order.indexOf(state.open);
  const next = order[i === -1 ? (delta > 0 ? 0 : order.length - 1) : Math.min(order.length - 1, Math.max(0, i + delta))];
  if (next !== state.open) openConv(next);
}

function applyReaction(key, messageId, info, mine, delta) {
  const m = state.messages.get(key)?.find(x => x.id === messageId);
  if (!m) return;
  m.reactions ||= [];
  let r = m.reactions.find(x => x.key === info.key);
  if (mine && (delta > 0 ? r?.me : !r?.me)) return;
  if (!r) {
    if (delta < 0) return;
    r = { ...info, count: 0, me: false };
    m.reactions.push(r);
  }
  r.count += delta;
  if (mine) r.me = delta > 0;
  if (r.count <= 0) m.reactions.splice(m.reactions.indexOf(r), 1);
  render();
}

// /react 👍 (or /react heart) toggles a reaction on the latest message from someone else.
async function reactCommand(arg) {
  const conv = state.convs.get(state.open);
  const target = [...(state.messages.get(state.open) || [])].reverse().find(m => !m.isSelf && !m.system);
  if (!conv || !target) return noteFor('Nothing to react to here');
  const value = arg.replace(/^:|:$/g, '') || '👍';
  const mine = target.reactions?.find(r => r.me && (r.emoji === value || r.name === value || r.key === value));
  try {
    const info = await state.provider.react(conv.id, target.id, mine ? mine.key : value, !mine);
    applyReaction(state.open, target.id, info, true, mine ? -1 : 1);
  } catch (err) {
    noteFor(err.message);
  }
}

async function submit() {
  const text = state.input.trim();
  if (!text) return;
  const conv = state.convs.get(state.open);
  state.input = '';
  state.cursor = 0;
  if (text === '/quit' || text === '/q') return quit();
  if (text === '/help') return noteFor(HELP, 8000);
  const react = /^\/(react|r)(?:\s+(.*))?$/.exec(text);
  if (react) return reactCommand((react[2] || '').trim());
  if (!conv) return noteFor('Pick a chat first (^N / ^P)');
  try {
    const message = await state.provider.send(conv.id, text);
    onMessage({ convId: conv.id, message });
    state.scroll = 0;
  } catch (err) {
    state.input = text;
    state.cursor = graphemes(text).length;
    noteFor(err.message);
  }
  render();
}

function onMessage({ convId, message }) {
  const key = `${state.provider.id}:${convId}`;
  const conv = state.convs.get(key);
  if (!conv) return;
  conv.lastActivity = Math.max(conv.lastActivity || 0, message.ts);
  const list = state.messages.get(key);
  const isNew = !list?.some(m => m.id === message.id);
  if (list && isNew) list.push(message);
  if (isNew && !message.isSelf && !conv.muted) {
    if (key === state.open) state.provider.markRead(convId).catch(() => {});
    else if (conv.kind !== 'channel' || message.mentionsMe) process.stdout.write('\x07'); // bell
  }
  render();
}

// ---------- keyboard ----------

function insert(text) {
  if (state.find != null) {
    state.find += text.replace(/\s+/g, ' ');
    return;
  }
  const g = graphemes(state.input);
  const add = graphemes(clean(text.replace(/\r?\n/g, ' ')));
  g.splice(state.cursor, 0, ...add);
  state.input = g.join('');
  state.cursor += add.length;
}

function edit(fn) {
  const g = graphemes(state.input);
  fn(g);
  state.input = g.join('');
}

function handleKey(k) {
  const mh = (process.stdout.rows || 24) - 4;
  if (k.paste != null) return insert(k.paste);
  const seq = k.seq || k.ch;
  switch (seq) {
    case '\x03': case '\x11': return quit(); // ^C ^Q
    case '\x0e': case '\x1bj': case '\x1b[1;3B': return step(1); // ^N, Alt+J, Alt+Down
    case '\x10': case '\x1bk': case '\x1b[1;3A': return step(-1); // ^P, Alt+K, Alt+Up
    case '\x0c': // ^L
      state.flat = !state.flat;
      return noteFor(state.flat ? 'Latest first: on' : 'Latest first: off (grouped)');
    case '\x06': state.find = ''; return; // ^F
    case '\x1b[5~': state.scroll += mh - 2; return; // PgUp
    case '\x1b[6~': state.scroll = Math.max(0, state.scroll - (mh - 2)); return; // PgDn
    case '\x1b[A': state.scroll += 3; return;
    case '\x1b[B': state.scroll = Math.max(0, state.scroll - 3); return;
    case '\x1b':
      state.find = null;
      return;
    default:
  }
  if (state.find != null) {
    if (seq === '\r') {
      const first = chatOrder()[0];
      state.find = null;
      if (first) openConv(first);
    } else if (seq === '\x7f' || seq === '\b') state.find = state.find.slice(0, -1);
    else if (k.ch && k.ch >= ' ') insert(k.ch);
    return;
  }
  switch (seq) {
    case '\r': return submit();
    case '\x7f': case '\b':
      if (state.cursor > 0) edit(g => g.splice(--state.cursor, 1));
      return;
    case '\x1b[3~': edit(g => g.splice(state.cursor, 1)); return;
    case '\x1b[D': state.cursor = Math.max(0, state.cursor - 1); return;
    case '\x1b[C': state.cursor = Math.min(graphemes(state.input).length, state.cursor + 1); return;
    case '\x01': case '\x1b[H': case '\x1bOH': case '\x1b[1~': state.cursor = 0; return;
    case '\x05': case '\x1b[F': case '\x1bOF': case '\x1b[4~': state.cursor = graphemes(state.input).length; return;
    case '\x15': state.input = ''; state.cursor = 0; return; // ^U
    case '\x17': // ^W: delete the word before the cursor
      edit(g => {
        let i = state.cursor;
        while (i > 0 && g[i - 1] === ' ') i--;
        while (i > 0 && g[i - 1] !== ' ') i--;
        g.splice(i, state.cursor - i);
        state.cursor = i;
      });
      return;
    default:
      if (k.ch && k.ch >= ' ') insert(k.ch);
  }
}

// Splits raw input into keys: escape sequences, bracketed pastes and characters.
function parseKeys(data) {
  const keys = [];
  let i = 0;
  while (i < data.length) {
    if (data.startsWith('\x1b[200~', i)) {
      const end = data.indexOf('\x1b[201~', i);
      keys.push({ paste: data.slice(i + 6, end === -1 ? undefined : end) });
      i = end === -1 ? data.length : end + 6;
      continue;
    }
    if (data[i] === '\x1b') {
      const m = /^\x1b(\[[0-9;]*[A-Za-z~]|O[A-Za-z]|[^\x1b])?/.exec(data.slice(i));
      keys.push({ seq: m[0] });
      i += m[0].length;
      continue;
    }
    const ch = String.fromCodePoint(data.codePointAt(i));
    keys.push({ ch });
    i += ch.length;
  }
  return keys;
}

// ---------- start / stop ----------

let screenTaken = false; // only undo the full-screen mode if we entered it

function restoreTerminal() {
  if (!screenTaken) return;
  screenTaken = false;
  process.stdout.write(`${CSI}?2004l${CSI}?25h${CSI}?1049l`);
  if (process.stdin.isTTY) process.stdin.setRawMode(false);
}

function quit() {
  state.provider?.disconnect();
  restoreTerminal();
  process.exit(0);
}

async function main() {
  const [cmd, arg] = process.argv.slice(2);
  if (cmd === '--help' || cmd === '-h') return console.log(USAGE);
  if (cmd === '--export-login') return exportLogin();
  if (cmd === '--login') return login(arg || '');
  if (cmd === '--logout') {
    fs.rmSync(CLI_CONFIG, { force: true });
    return console.error('Forgot the saved login.');
  }
  if (cmd && cmd !== '--demo') throw new Error(`unknown option ${cmd}\n\n${USAGE}`);
  if (!process.stdin.isTTY) throw new Error('sbmm needs an interactive terminal');
  let provider;
  if (process.env.SBMM_DEMO || cmd === '--demo') {
    provider = new DemoProvider();
  } else {
    const { url, token } = await credentials();
    provider = new MattermostProvider(url, token);
  }
  state.provider = provider;
  provider.on('status', s => {
    state.status = s;
    if (s.error) noteFor(s.error, 8000);
    render();
  });
  provider.on('conversations', list => {
    state.convs = new Map(list.map(c => [c.key, c]));
    if (!state.open) {
      const first = chatOrder()[0];
      if (first) openConv(first);
    }
    render();
  });
  provider.on('message', onMessage);
  provider.on('reaction', ({ convId, messageId, reaction, mine, delta }) => applyReaction(`${provider.id}:${convId}`, messageId, reaction, mine, delta));

  screenTaken = true;
  process.stdout.write(`${CSI}?1049h${CSI}?2004h${CSI}2J`);
  process.stdin.setRawMode(true);
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', data => {
    for (const k of parseKeys(data)) handleKey(k);
    render();
  });
  process.stdout.on('resize', render);
  process.on('SIGTERM', quit);
  render();
  provider.connect();
}

process.removeAllListeners('warning'); // e.g. Node 18's fetch ExperimentalWarning would scribble on the screen

process.on('uncaughtException', err => {
  restoreTerminal();
  console.error(err);
  process.exit(1);
});

main().catch(err => {
  restoreTerminal();
  console.error(`sbmm: ${err.message}`);
  process.exit(1);
});
