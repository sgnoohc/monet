const { app, BrowserWindow, Menu, clipboard, ipcMain, powerMonitor, session, shell } = require('electron');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const QRCode = require('qrcode');
const store = require('./src/store');
const DiscordProvider = require('./src/providers/discord');
const MattermostProvider = require('./src/providers/mattermost');
const SlackProvider = require('./src/providers/slack');
const DemoProvider = require('./src/providers/demo');

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

  ipcMain.handle('messages:send', (_e, key, text) => {
    const { provider, convId } = route(key);
    return provider.send(convId, text);
  });

  ipcMain.handle('messages:upload', (_e, key, files, text) => {
    const { provider, convId } = route(key);
    if (!provider.upload) throw new Error('Sending files is not supported here');
    if (files.some(f => f.data.length > 50 * 1024 * 1024)) throw new Error('Files over 50 MB are not supported');
    return provider.upload(convId, files.map(f => ({ name: String(f.name), type: String(f.type || ''), data: f.data })), text);
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

  // GIF search goes through Discord's GIF picker API, whichever chat it is for.
  ipcMain.handle('gifs:search', (_e, query) => {
    const discord = providers.get('discord');
    if (!discord) throw new Error('GIF search uses your Discord account. Connect Discord in Settings to use it.');
    return discord.searchGifs(query);
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
    return settings();
  });

  ipcMain.handle('discord:remove', () => {
    store.deleteSecret('discord');
    stopProvider('discord');
    return settings();
  });

  ipcMain.handle('mattermost:browserLogin', async (_e, url) => {
    const base = normalizeUrl(url);
    const token = await mattermostBrowserLogin(base);
    store.setConfig({ mattermost: { url: base } });
    store.setSecret('mattermost', token);
    startMattermost();
    return settings();
  });

  ipcMain.handle('mattermost:setToken', (_e, url, token) => {
    token = String(token || '').trim();
    if (!token) throw new Error('Paste a token first');
    store.setConfig({ mattermost: { url: normalizeUrl(url) } });
    store.setSecret('mattermost', token);
    startMattermost();
    return settings();
  });

  ipcMain.handle('mattermost:remove', async () => {
    store.deleteSecret('mattermost');
    stopProvider('mattermost');
    await session.fromPartition('persist:mattermost-login').clearStorageData();
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
    return settings();
  });

  ipcMain.handle('slack:remove', (_e, id) => {
    store.deleteSecret(`slack-${id}`);
    store.deleteCache(`slack-${id}`);
    store.setConfig({ slack: store.getConfig().slack.filter(a => a.id !== id) });
    stopProvider(`slack-${id}`);
    return settings();
  });

  ipcMain.handle('webapps:set', (_e, list) => {
    const clean = list.map(a => ({
      id: String(a.id).replace(/[^\w-]/g, ''),
      name: String(a.name).slice(0, 60),
      service: a.service === 'teams' ? 'teams' : 'web',
      url: new URL(a.url).href,
    }));
    if (clean.some(a => !a.url.startsWith('https://'))) throw new Error('Web app addresses must use https');
    store.setConfig({ webApps: clean });
    return settings();
  });

  ipcMain.handle('view:set', (_e, view) => {
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
    store.setConfig({
      view: {
        nicknames,
        mode: view.mode === 'selected' ? 'selected' : 'all',
        keys: [...new Set((view.keys || []).map(String))],
        groups,
        assign,
        pins: [...new Set((Array.isArray(view.pins) ? view.pins : []).map(String))].slice(0, 500),
        otherCollapsed: !!view.otherCollapsed,
        compact: !!view.compact,
        flat: !!view.flat,
      },
    });
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
      text = encode('SBL', { v: 1, view });
      for (const key of ['keys', 'assign', 'nicknames']) {
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
  sendToUi('hotkey', 'refresh');
}

app.whenReady().then(() => {
  powerMonitor.on('resume', reconnectAll);
  powerMonitor.on('unlock-screen', reconnectAll);
  hardenContents();
  registerIpc();
  createWindow();
  if (DEMO) {
    startProvider(new DemoProvider());
  } else {
    startDiscord();
    startMattermost();
    for (const account of store.getConfig().slack) startSlack(account);
  }
});

app.on('activate', () => {
  if (win && !win.isDestroyed()) win.show();
});

app.on('before-quit', () => {
  app.isQuitting = true;
});
