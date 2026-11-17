const { app, BrowserWindow, Menu, clipboard, dialog, ipcMain, powerMonitor, session, shell } = require('electron');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const QRCode = require('qrcode');
const store = require('./src/store');
const DiscordProvider = require('./src/providers/discord');
const MattermostProvider = require('./src/providers/mattermost');
const SlackProvider = require('./src/providers/slack');
const DemoProvider = require('./src/providers/demo');
const { createSync } = require('./src/sync');

const DEMO = process.env.SWITCHBOARD_DEMO === '1';
const CAPTURE = process.env.SWITCHBOARD_CAPTURE; // write a screenshot here and quit (for testing)
const CAPTURE_JS = process.env.SWITCHBOARD_CAPTURE_JS || `document.querySelectorAll('.conv')[1]?.click()`;

// Keep demo data away from real accounts and settings.
if (DEMO) app.setPath('userData', path.join(app.getPath('appData'), 'Switchboard Demo'));

// Web apps get a plain Chrome UA; some sites refuse browsers that say "Electron".
const USER_AGENT = `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${process.versions.chrome} Safari/537.36`;

// Microsoft sign-in opens popups; those stay in-app so they share the web app's session.
const POPUP_HOSTS = /(^|\.)(microsoftonline\.com|live\.com|microsoft\.com|office\.com|skype\.com|teams\.cloud\.microsoft)$/;

let win;
const providers = new Map(); // id -> provider
const statuses = {};

function sendToUi(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

// What a chat's unread state is after a new message, so the interface can match it
const countsOf = c => (c ? { unread: !!c.unread, unreadCount: c.unreadCount || 0, mentions: c.mentions || 0 } : null);

function startProvider(provider) {
  stopProvider(provider.id);
  providers.set(provider.id, provider);
  provider.on('status', s => {
    statuses[provider.id] = { provider: provider.id, label: provider.label, ...s };
    sendToUi('status', statuses[provider.id]);
  });
  provider.on('conversations', list => sendToUi('conversations', { provider: provider.id, list }));
  provider.on('message', ({ convId, message }) => sendToUi('message', { key: `${provider.id}:${convId}`, message, counts: countsOf(provider.convs?.get(convId)) }));
  provider.on('reaction', ({ convId, ...rest }) => sendToUi('reaction', { key: `${provider.id}:${convId}`, ...rest }));
  provider.connect();
}

function stopProvider(id) {
  const p = providers.get(id);
  if (!p) return;
  p.removeAllListeners();
  p.disconnect();
  providers.delete(id);
  delete statuses[id];
  sendToUi('conversations', { provider: id, list: [] });
  sendToUi('status', { provider: id, state: 'off' });
}

function startDiscord() {
  const token = store.getSecret('discord');
  if (token) startProvider(new DiscordProvider(token));
}

function startMattermost() {
  const token = store.getSecret('mattermost');
  const url = store.getConfig().mattermost.url;
  if (token && url) startProvider(new MattermostProvider(url, token));
}

function startSlack(account) {
  const secret = store.getSecret(`slack-${account.id}`);
  if (!secret) return;
  const { userToken, appToken } = JSON.parse(secret);
  startProvider(new SlackProvider({
    teamId: account.id,
    teamName: account.name,
    userToken,
    appToken,
    cache: store.cache(`slack-${account.id}`),
  }));
}

// How big things are on this Mac (not synced: the other Mac's screen may differ).
// zoom: the whole window, like ⌘+ in a browser; chatText: message text on top of that.
const ZOOMS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2];
const CHAT_TEXT = [0.85, 1, 1.15, 1.3, 1.5];
function display() {
  const d = store.getConfig().display || {};
  return { zoom: ZOOMS.includes(d.zoom) ? d.zoom : 1, chatText: CHAT_TEXT.includes(d.chatText) ? d.chatText : 1 };
}

function setDisplay(patch) {
  const next = { ...display(), ...patch };
  if (!ZOOMS.includes(next.zoom)) next.zoom = 1;
  if (!CHAT_TEXT.includes(next.chatText)) next.chatText = 1;
  store.setConfig({ display: next });
  if (win && !win.isDestroyed()) win.webContents.setZoomFactor(next.zoom);
  sendToUi('display', next);
  return next;
}

function zoomStep(dir) {
  const i = ZOOMS.indexOf(display().zoom);
  setDisplay({ zoom: dir === 0 ? 1 : ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, i + dir))] });
}

// The standard menus, with View's zoom items wired to the saved size, and
// ⌘1–⌘9 showing just the chats with that color tag (the window sends the names).
let tagNames = [];
function buildMenu() {
  const tagItems = tagNames.slice(0, 9).map((name, i) => ({
    label: `Show ${name}`,
    accelerator: `CmdOrCtrl+${i + 1}`,
    click: () => sendToUi('hotkey', `tag:${i + 1}`),
  }));
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { role: 'appMenu' },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        { label: 'Bigger', accelerator: 'CmdOrCtrl+=', click: () => zoomStep(1) },
        { label: 'Bigger', accelerator: 'CmdOrCtrl+Plus', visible: false, acceleratorWorksWhenHidden: true, click: () => zoomStep(1) },
        { label: 'Smaller', accelerator: 'CmdOrCtrl+-', click: () => zoomStep(-1) },
        { label: 'Actual Size', accelerator: 'CmdOrCtrl+0', click: () => zoomStep(0) },
        ...(tagItems.length ? [{ type: 'separator' }, ...tagItems] : []),
        { type: 'separator' },
        { role: 'togglefullscreen' },
        { role: 'toggleDevTools' },
      ],
    },
    { role: 'windowMenu' },
  ]));
}

function settings() {
  const cfg = store.getConfig();
  return {
    demo: DEMO,
    mattermostUrl: cfg.mattermost.url,
    hasDiscord: !!store.getSecret('discord'),
    hasMattermost: !!store.getSecret('mattermost'),
    slack: cfg.slack.map(a => ({ id: a.id, name: a.name })),
    webApps: DEMO ? [] : cfg.webApps,
    view: cfg.view,
    display: display(),
    userAgent: USER_AGENT,
  };
}

function normalizeUrl(url) {
  const u = new URL(/^https?:\/\//.test(url) ? url : `https://${url}`);
  if (u.protocol !== 'https:') throw new Error('Server address must use https');
  return u.origin;
}

function route(key) {
  const i = key.indexOf(':');
  const provider = providers.get(key.slice(0, i));
  if (!provider) throw new Error('That account is not connected');
  return { provider, convId: key.slice(i + 1) };
}

// Opens the server's normal login page (SSO included) and waits for the
// session cookie, which works as a Bearer token for the API.
function mattermostBrowserLogin(base) {
  const partition = 'persist:mattermost-login';
  const ses = session.fromPartition(partition);
  const loginWin = new BrowserWindow({
    width: 900,
    height: 760,
    parent: win,
    title: 'Sign in to Mattermost',
    webPreferences: { partition, contextIsolation: true, sandbox: true },
  });
  loginWin.webContents.setUserAgent(USER_AGENT);
  loginWin.loadURL(`${base}/login`);
  return new Promise((resolve, reject) => {
    let done = false;
    const timer = setInterval(async () => {
      const [cookie] = await ses.cookies.get({ url: base, name: 'MMAUTHTOKEN' });
      if (cookie?.value && !done) {
        done = true;
        clearInterval(timer);
        loginWin.close();
        resolve(cookie.value);
      }
    }, 1000);
    loginWin.on('closed', () => {
      clearInterval(timer);
      if (!done) {
        done = true;
        reject(new Error('Sign-in window was closed before login finished'));
      }
    });
  });
}

// The sidebar layout, checked and trimmed whether it comes from this window or the other Mac.
function cleanView(view = {}) {
  const groups = (Array.isArray(view.groups) ? view.groups : []).slice(0, 200).map(g => ({
    id: String(g.id).replace(/[^\w-]/g, '').slice(0, 40),
    name: String(g.name || 'Group').slice(0, 60),
    collapsed: !!g.collapsed,
  }));
  const ids = new Set(groups.map(g => g.id));
  const assign = {};
  for (const [key, gid] of Object.entries(view.assign || {})) if (ids.has(gid)) assign[String(key)] = gid;
  const nicknames = {};
  for (const [key, name] of Object.entries(view.nicknames || {}).slice(0, 5000)) {
    if (String(name).trim()) nicknames[String(key)] = String(name).trim().slice(0, 80);
  }
  // Per-person look: name colour, whether the picture takes it too, and a small uploaded picture.
  const people = {};
  for (const [key, p] of Object.entries(view.people || {}).slice(0, 2000)) {
    const color = /^#[0-9a-f]{6}$/i.test(p?.color) ? p.color : undefined;
    const image = typeof p?.image === 'string' && p.image.length < 100000 && /^data:image\/(webp|jpeg|png);base64,[\w+/=]+$/.test(p.image) ? p.image : undefined;
    if (color || image) people[String(key).slice(0, 200)] = { color, tint: !!(color && p.tint), image };
  }
  // Color tags: named colors put on chats, or on a whole server ("server:..." keys).
  const tags = (Array.isArray(view.tags) ? view.tags : []).slice(0, 50).map(t => ({
    id: String(t.id).replace(/[^\w-]/g, '').slice(0, 40),
    name: String(t.name || 'Tag').slice(0, 40),
    color: /^#[0-9a-f]{6}$/i.test(t.color) ? t.color : '#8d8d86',
  })).filter(t => t.id);
  const tagIds = new Set(tags.map(t => t.id));
  const tagOf = {};
  for (const [key, id] of Object.entries(view.tagOf || {}).slice(0, 5000)) if (tagIds.has(id)) tagOf[String(key).slice(0, 200)] = id;
  // Chat backgrounds: a preset name, a picture (sized down when chosen), or a photo's
  // number in the app's list (fetched at the window's size). "*" is every chat's default.
  const backgrounds = {};
  for (const [key, b] of Object.entries(view.backgrounds || {}).slice(0, 500)) {
    const preset = typeof b?.preset === 'string' && /^[a-z-]{1,20}$/.test(b.preset) ? b.preset : undefined;
    const image = typeof b?.image === 'string' && b.image.length < 1500000 && /^data:image\/(webp|jpeg|png);base64,[\w+/=]+$/.test(b.image) ? b.image : undefined;
    const photo = typeof b?.photo === 'string' && /^\d{1,5}$/.test(b.photo) ? b.photo : undefined;
    if (preset || image || photo) backgrounds[String(key).slice(0, 200)] = image ? { image } : photo ? { photo } : { preset };
  }
  return {
    nicknames,
    people,
    tags,
    backgrounds,
    tagOf,
    mode: view.mode === 'selected' ? 'selected' : 'all',
    keys: [...new Set((view.keys || []).map(String))],
    groups,
    assign,
    pins: [...new Set((Array.isArray(view.pins) ? view.pins : []).map(String))].slice(0, 500),
    otherCollapsed: !!view.otherCollapsed,
    compact: !!view.compact,
    flat: !!view.flat,
    bigPictures: view.bigPictures !== false,
    dmNames: view.dmNames !== false,
    showTimes: view.showTimes !== false,
  };
}

function cleanWebApps(list) {
  const clean = (Array.isArray(list) ? list : []).map(a => ({
    id: String(a.id).replace(/[^\w-]/g, ''),
    name: String(a.name).slice(0, 60),
    service: a.service === 'teams' ? 'teams' : 'web',
    url: new URL(a.url).href,
  }));
  if (clean.some(a => !a.url.startsWith('https://'))) throw new Error('Web app addresses must use https');
  return clean;
}

// ---------- sync between Macs (see src/sync.js) ----------

function getLogins() {
  const cfg = store.getConfig();
  const mmToken = store.getSecret('mattermost');
  return {
    discord: store.getSecret('discord') || null,
    mattermost: mmToken ? { url: cfg.mattermost.url, token: mmToken } : null,
    slack: cfg.slack.map(a => ({ id: a.id, name: a.name, secret: store.getSecret(`slack-${a.id}`) })).filter(a => a.secret),
  };
}

// Makes this Mac's accounts match the other Mac's: signs in, switches or signs out.
function applyLogins(p) {
  if ((p.discord || null) !== (store.getSecret('discord') || null)) {
    if (p.discord) {
      store.setSecret('discord', p.discord);
      startDiscord();
    } else {
      store.deleteSecret('discord');
      stopProvider('discord');
    }
  }
  const mm = p.mattermost;
  if (mm?.token && mm.url) {
    if (mm.token !== store.getSecret('mattermost') || normalizeUrl(mm.url) !== store.getConfig().mattermost.url) {
      store.setConfig({ mattermost: { url: normalizeUrl(mm.url) } });
      store.setSecret('mattermost', mm.token);
      startMattermost();
    }
  } else if (store.getSecret('mattermost')) {
    store.deleteSecret('mattermost');
    stopProvider('mattermost');
  }
  const remote = (Array.isArray(p.slack) ? p.slack : []).filter(a => a?.id && a.secret);
  for (const a of remote) {
    if (a.secret === store.getSecret(`slack-${a.id}`)) continue;
    const account = { id: String(a.id), name: String(a.name || 'Slack') };
    store.setSecret(`slack-${account.id}`, a.secret);
    store.setConfig({ slack: [...store.getConfig().slack.filter(x => x.id !== account.id), account] });
    startSlack(account);
  }
  for (const a of store.getConfig().slack) {
    if (remote.some(r => r.id === a.id)) continue;
    store.deleteSecret(`slack-${a.id}`);
    store.deleteCache(`slack-${a.id}`);
    store.setConfig({ slack: store.getConfig().slack.filter(x => x.id !== a.id) });
    stopProvider(`slack-${a.id}`);
  }
  sendToUi('settings', settings());
}

const sync = createSync({
  store,
  getLayout: () => {
    const cfg = store.getConfig();
    return { view: cfg.view, webApps: cfg.webApps };
  },
  applyLayout: ({ view, webApps }) => {
    store.setConfig({ view: cleanView(view), ...(Array.isArray(webApps) ? { webApps: cleanWebApps(webApps) } : {}) });
    sendToUi('settings', settings());
  },
  getLogins,
  applyLogins,
  onStatus: status => sendToUi('sync', status),
});

function registerIpc() {
  ipcMain.handle('state:get', () => ({
    settings: settings(),
    statuses,
    conversations: [...providers.values()].flatMap(p => p.conversations()),
  }));

  ipcMain.handle('messages:fetch', (_e, key, before) => {
    const { provider, convId } = route(key);
    return provider.fetchMessages(convId, before);
  });

  ipcMain.handle('messages:send', (_e, key, text, opts) => {
    const { provider, convId } = route(key);
    return provider.send(convId, text, { replyTo: opts?.replyTo ? String(opts.replyTo) : undefined });
  });

  // A thread's messages, or null where the service has no threads to fetch (Discord).
  ipcMain.handle('messages:thread', (_e, key, rootId) => {
    const { provider, convId } = route(key);
    return provider.thread ? provider.thread(convId, String(rootId)) : null;
  });

  ipcMain.handle('messages:upload', (_e, key, files, text, opts) => {
    const { provider, convId } = route(key);
    if (!provider.upload) throw new Error('Sending files is not supported here');
    if (files.some(f => f.data.length > 50 * 1024 * 1024)) throw new Error('Files over 50 MB are not supported');
    return provider.upload(convId, files.map(f => ({ name: String(f.name), type: String(f.type || ''), data: f.data })), text, { replyTo: opts?.replyTo ? String(opts.replyTo) : undefined });
  });

  // Files that need the account's login (Mattermost, Slack) to download.
  ipcMain.handle('media:fetch', (_e, key, ref) => {
    const { provider } = route(key);
    if (!provider.fetchMedia) throw new Error('Not available');
    return provider.fetchMedia(ref);
  });

  // Saves an attachment to Downloads. Documents and media open in their app;
  // anything else is only revealed in Finder, so nothing runnable is launched.
  ipcMain.handle('file:open', async (_e, key, attachment) => {
    let data;
    if (attachment.ref) {
      ({ data } = await route(key).provider.fetchMedia(attachment.ref));
    } else if (/^https:\/\//.test(attachment.url || '')) {
      const res = await fetch(attachment.url);
      if (!res.ok) throw new Error(`Download failed (HTTP ${res.status})`);
      data = new Uint8Array(await res.arrayBuffer());
    } else {
      throw new Error('Nothing to download');
    }
    const name = path.basename(String(attachment.name || 'file')).replace(/[/\\:]/g, '_') || 'file';
    const { name: base, ext } = path.parse(name);
    let target = path.join(app.getPath('downloads'), name);
    for (let i = 1; fs.existsSync(target); i++) target = path.join(app.getPath('downloads'), `${base} (${i})${ext}`);
    fs.writeFileSync(target, data);
    const SAFE = /\.(pdf|png|jpe?g|gif|webp|heic|svg|txt|md|csv|json|log|docx?|xlsx?|pptx?|key|pages|numbers|mp4|mov|m4v|webm|mp3|m4a|wav)$/i;
    if (SAFE.test(target)) shell.openPath(target);
    else shell.showItemInFolder(target);
    return target;
  });

  ipcMain.handle('messages:react', (_e, key, messageId, value, add) => {
    const { provider, convId } = route(key);
    if (!provider.react) throw new Error('Reactions are not supported here');
    return provider.react(convId, messageId, value, add);
  });

  ipcMain.handle('messages:reactors', (_e, key, messageId, reactionKey) => {
    const { provider, convId } = route(key);
    return provider.reactors ? provider.reactors(convId, messageId, reactionKey) : [];
  });

  ipcMain.handle('messages:members', (_e, key) => {
    const { provider, convId } = route(key);
    if (!provider.members) throw new Error('Not available for this chat');
    return provider.members(convId);
  });

  ipcMain.handle('messages:pinned', (_e, key) => {
    const { provider, convId } = route(key);
    return provider.pinned ? provider.pinned(convId) : [];
  });

  // GIF search goes through Discord's GIF picker API, whichever chat it is for.
  // GIF search through Discord's picker, or Mattermost's (Giphy) when Discord isn't connected.
  ipcMain.handle('gifs:search', (_e, query) => {
    const source = providers.get('discord') || providers.get('mattermost');
    if (!source?.searchGifs) throw new Error('GIF search needs Discord or Mattermost. Connect one in Settings.');
    return source.searchGifs(query);
  });

  ipcMain.handle('conv:markRead', (_e, key) => {
    const { provider, convId } = route(key);
    return provider.markRead(convId);
  });

  ipcMain.handle('discord:setToken', (_e, token) => {
    token = String(token || '').trim().replace(/^"|"$/g, '');
    if (!token) throw new Error('Paste a token first');
    store.setSecret('discord', token);
    startDiscord();
    sync.loginsChanged();
    return settings();
  });

  ipcMain.handle('discord:remove', () => {
    store.deleteSecret('discord');
    stopProvider('discord');
    sync.loginsChanged();
    return settings();
  });

  ipcMain.handle('mattermost:browserLogin', async (_e, url) => {
    const base = normalizeUrl(url);
    const token = await mattermostBrowserLogin(base);
    store.setConfig({ mattermost: { url: base } });
    store.setSecret('mattermost', token);
    startMattermost();
    sync.loginsChanged();
    return settings();
  });

  ipcMain.handle('mattermost:setToken', (_e, url, token) => {
    token = String(token || '').trim();
    if (!token) throw new Error('Paste a token first');
    store.setConfig({ mattermost: { url: normalizeUrl(url) } });
    store.setSecret('mattermost', token);
    startMattermost();
    sync.loginsChanged();
    return settings();
  });

  ipcMain.handle('mattermost:remove', async () => {
    store.deleteSecret('mattermost');
    stopProvider('mattermost');
    await session.fromPartition('persist:mattermost-login').clearStorageData();
    sync.loginsChanged();
    return settings();
  });

  ipcMain.handle('slack:add', async (_e, userToken, appToken) => {
    userToken = String(userToken || '').trim();
    appToken = String(appToken || '').trim();
    if (!userToken.startsWith('xoxp-')) throw new Error('The User OAuth Token starts with xoxp-');
    if (!appToken.startsWith('xapp-')) throw new Error('The app-level token starts with xapp-');
    const res = await fetch('https://slack.com/api/auth.test', { method: 'POST', headers: { Authorization: `Bearer ${userToken}` } });
    const auth = await res.json();
    if (!auth.ok) throw new Error(`Slack rejected the user token (${auth.error})`);
    const account = { id: auth.team_id, name: auth.team };
    store.setSecret(`slack-${account.id}`, JSON.stringify({ userToken, appToken }));
    store.setConfig({ slack: [...store.getConfig().slack.filter(a => a.id !== account.id), account] });
    startSlack(account);
    sync.loginsChanged();
    return settings();
  });

  ipcMain.handle('slack:remove', (_e, id) => {
    store.deleteSecret(`slack-${id}`);
    store.deleteCache(`slack-${id}`);
    store.setConfig({ slack: store.getConfig().slack.filter(a => a.id !== id) });
    stopProvider(`slack-${id}`);
    sync.loginsChanged();
    return settings();
  });

  ipcMain.handle('webapps:set', (_e, list) => {
    store.setConfig({ webApps: cleanWebApps(list) });
    sync.layoutChanged();
    return settings();
  });

  ipcMain.on('menu:tags', (_e, names) => {
    const next = (Array.isArray(names) ? names : []).slice(0, 9).map(n => String(n).slice(0, 40));
    if (JSON.stringify(next) === JSON.stringify(tagNames)) return;
    tagNames = next;
    buildMenu();
  });

  ipcMain.handle('display:set', (_e, patch) => setDisplay({ zoom: Number(patch?.zoom ?? display().zoom), chatText: Number(patch?.chatText ?? display().chatText) }));

  ipcMain.handle('view:set', (_e, view) => {
    store.setConfig({ view: cleanView(view) });
    sync.layoutChanged();
  });

  // Native context menu; resolves with the clicked item's id, or null.
  ipcMain.handle('menu:popup', (e, items) => new Promise(resolve => {
    let done = false;
    const finish = id => {
      if (!done) {
        done = true;
        resolve(id);
      }
    };
    const build = list => list.map(item => (item.type === 'separator' ? { type: 'separator' } : {
      label: String(item.label),
      type: item.checked != null ? 'checkbox' : 'normal',
      checked: !!item.checked,
      enabled: item.enabled !== false,
      submenu: item.submenu ? build(item.submenu) : undefined,
      click: item.submenu ? undefined : () => finish(item.id),
    }));
    const menu = Menu.buildFromTemplate(build(items));
    menu.popup({
      window: BrowserWindow.fromWebContents(e.sender),
      callback: () => setTimeout(() => finish(null), 50),
    });
  }));

  // Setup codes for the phone app, kept small so each QR scans easily:
  // "accounts" (tokens) is one code; "layout" (groups, nicknames, hidden chats)
  // is split into parts that the Mac cycles through and the phone collects.
  // Format: prefix + base64(deflate-raw(JSON)); SB1 = accounts, SBL = layout,
  // each layout part being "SBP:<session>:<i>/<n>:<slice of the SBL text>".
  ipcMain.handle('phone:setupCode', async (_e, part) => {
    const cfg = store.getConfig();
    const encode = (prefix, payload) => `${prefix}:${zlib.deflateRawSync(JSON.stringify(payload), { level: 9 }).toString('base64')}`;
    let text;
    const dropped = [];
    if (part === 'layout') {
      const view = { ...cfg.view };
      // Pictures are far too big for a QR code; colours travel, pictures stay on the Mac.
      view.people = Object.fromEntries(Object.entries(view.people || {})
        .filter(([, p]) => p.color)
        .map(([key, p]) => [key, { color: p.color, tint: p.tint }]));
      text = encode('SBL', { v: 1, view });
      for (const key of ['people', 'keys', 'assign', 'nicknames']) {
        if (text.length <= 1800) break;
        delete view[key];
        if (key === 'keys') view.mode = 'all';
        dropped.push(key);
        text = encode('SBL', { v: 1, view });
      }
    } else {
      const mmToken = store.getSecret('mattermost');
      text = encode('SB1', {
        v: 1,
        discord: store.getSecret('discord'),
        mattermost: mmToken ? { url: cfg.mattermost.url, token: mmToken } : null,
        slack: cfg.slack
          .map(a => ({ id: a.id, name: a.name, ...JSON.parse(store.getSecret(`slack-${a.id}`) || '{}') }))
          .filter(a => a.userToken),
      });
    }
    const qr = t => QRCode.toDataURL(t, { errorCorrectionLevel: 'L', margin: 3, width: 720 });
    if (part !== 'layout') return { dataUrls: [await qr(text)], dropped };
    const PART = 400;
    const session = Math.random().toString(36).slice(2, 6);
    const n = Math.ceil(text.length / PART);
    const parts = Array.from({ length: n }, (_, i) => `SBP:${session}:${i + 1}/${n}:${text.slice(i * PART, (i + 1) * PART)}`);
    return { dataUrls: await Promise.all(parts.map(qr)), dropped };
  });

  ipcMain.handle('sync:get', () => sync.status());
  ipcMain.handle('sync:enable', async (_e, folder) => {
    await sync.enable(folder ? String(folder) : null);
    return sync.status();
  });
  ipcMain.handle('sync:choose', async () => {
    const r = await dialog.showOpenDialog(win, {
      title: 'Choose a folder that syncs between your Macs',
      defaultPath: sync.status().suggested || app.getPath('home'),
      properties: ['openDirectory', 'createDirectory'],
    });
    if (r.canceled || !r.filePaths[0]) return sync.status();
    await sync.enable(r.filePaths[0]);
    return sync.status();
  });
  ipcMain.handle('sync:disable', () => {
    sync.disable();
    return sync.status();
  });
  ipcMain.handle('sync:passphrase', async (_e, passphrase) => {
    await sync.setPassphrase(passphrase);
    return sync.status();
  });
  ipcMain.handle('sync:now', async () => {
    await sync.syncNow();
    return sync.status();
  });

  ipcMain.on('clipboard:write', (_e, text) => clipboard.writeText(String(text)));

  ipcMain.on('badge', (_e, n) => app.dock?.setBadge(n > 0 ? String(n) : ''));
  ipcMain.on('focus', () => {
    win?.show();
    win?.focus();
  });
  ipcMain.on('open-external', (_e, url) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
  });
}

// Passkeys need Apple's browser entitlement, which an unsigned local build
// lacks, so a passkey prompt would hang forever. Reporting them as unavailable
// makes sign-in pages fall back to codes, passwords or authenticator apps.
const NO_PASSKEYS = `(() => {
  if (window.__sbNoPasskeys) return;
  window.__sbNoPasskeys = true;
  const deny = () => Promise.reject(new DOMException('Passkeys are not available in this app', 'NotAllowedError'));
  try {
    if (navigator.credentials) {
      navigator.credentials.get = deny;
      navigator.credentials.create = deny;
    }
    if (window.PublicKeyCredential) {
      PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable = () => Promise.resolve(false);
      PublicKeyCredential.isConditionalMediationAvailable = () => Promise.resolve(false);
    }
  } catch {}
})();`;

function blockPasskeys(contents) {
  // Runs before any page script, in every frame and after every navigation.
  try {
    contents.debugger.attach('1.3');
    contents.debugger.sendCommand('Page.addScriptToEvaluateOnNewDocument', { source: NO_PASSKEYS }).catch(() => {});
  } catch {}
  // Fallback if the debugger was unavailable.
  contents.on('dom-ready', () => contents.executeJavaScript(NO_PASSKEYS).catch(() => {}));
}

function hardenContents() {
  app.on('web-contents-created', (_e, contents) => {
    blockPasskeys(contents);
    if (contents.getType() === 'webview') {
      // Keyboard focus inside a web app never reaches the sidebar, so forward the app's hotkeys.
      const HOTKEYS = { KeyJ: 'next', KeyK: 'prev', KeyL: 'flat' };
      contents.on('before-input-event', (event, input) => {
        if (input.type === 'keyDown' && input.control && !input.meta && !input.alt && HOTKEYS[input.code]) {
          event.preventDefault();
          sendToUi('hotkey', HOTKEYS[input.code]);
        }
      });
      contents.setWindowOpenHandler(({ url }) => {
        try {
          if (url === 'about:blank' || POPUP_HOSTS.test(new URL(url).hostname)) return { action: 'allow' };
        } catch {}
        if (/^https?:\/\//.test(url)) shell.openExternal(url);
        return { action: 'deny' };
      });
    }
  });

  app.on('session-created', ses => {
    const allowed = new Set(['notifications', 'media', 'clipboard-sanitized-write', 'fullscreen']);
    ses.setPermissionRequestHandler((_wc, permission, cb) => cb(allowed.has(permission)));
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 760,
    minHeight: 480,
    title: 'Switchboard',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 18 },
    backgroundColor: '#1e1f22',
    show: !CAPTURE,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webviewTag: true,
      backgroundThrottling: false, // keep counting and polling at full speed while the window is hidden
    },
  });

  win.webContents.on('will-attach-webview', (e, prefs, params) => {
    delete prefs.preload;
    prefs.nodeIntegration = false;
    prefs.contextIsolation = true;
    if (!params.src.startsWith('https://') || !params.partition?.startsWith('persist:webapp-')) e.preventDefault();
  });
  win.webContents.on('will-navigate', e => e.preventDefault());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  // Closing the window hides it (like Mail/Messages) so connections stay up.
  win.on('close', e => {
    if (!app.isQuitting && !CAPTURE) {
      e.preventDefault();
      win.hide();
    }
  });

  win.on('focus', () => sync.poll()); // pick up the other Mac's changes as soon as you're back
  win.webContents.on('did-finish-load', () => win.webContents.setZoomFactor(display().zoom));
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  if (CAPTURE) {
    win.webContents.once('did-finish-load', async () => {
      await new Promise(r => setTimeout(r, 800));
      await win.webContents.executeJavaScript(CAPTURE_JS);
      await new Promise(r => setTimeout(r, 800));
      try {
        const image = await win.webContents.capturePage();
        fs.writeFileSync(CAPTURE, image.toPNG());
      } catch (err) {
        console.error('capture failed:', err);
      }
      app.quit();
    });
  }
}

// After sleep, sockets look open but are dead: reconnect and refresh the open chat.
function reconnectAll() {
  for (const p of providers.values()) p.reconnect?.();
  sync.poll();
  sendToUi('hotkey', 'refresh');
}

app.whenReady().then(() => {
  powerMonitor.on('resume', reconnectAll);
  powerMonitor.on('unlock-screen', reconnectAll);
  hardenContents();
  registerIpc();
  buildMenu();
  createWindow();
  if (DEMO) {
    startProvider(new DemoProvider());
  } else {
    startDiscord();
    startMattermost();
    for (const account of store.getConfig().slack) startSlack(account);
    sync.start();
  }
});

app.on('activate', () => {
  if (win && !win.isDestroyed()) win.show();
});

app.on('before-quit', () => {
  app.isQuitting = true;
});
