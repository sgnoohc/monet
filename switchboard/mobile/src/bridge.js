// Phone version of the desktop preload: provides `window.sb` with the same
// API, but runs the providers right here in the page. Accounts arrive by
// scanning the setup QR code shown by the Mac app.
import { App } from '@capacitor/app';
import { Preferences } from '@capacitor/preferences';
import { BarcodeScanner, BarcodeFormat } from '@capacitor-mlkit/barcode-scanning';
import DiscordProvider from '../../src/providers/discord';
import MattermostProvider from '../../src/providers/mattermost';
import SlackProvider from '../../src/providers/slack';
import DemoProvider from '../../src/providers/demo';

const DEFAULT_VIEW = { mode: 'all', keys: [], groups: [], assign: {}, nicknames: {}, pins: [], otherCollapsed: false, compact: false, flat: false };

// Stored in the app's private storage (not readable by other apps; backups are off).
let config = { mattermost: { url: '' }, slack: [], view: { ...DEFAULT_VIEW } };
let secrets = {};
const caches = {};

const listeners = {};
const emit = (event, payload) => (listeners[event] || []).forEach(fn => fn(payload));

const providers = new Map();
const statuses = {};

async function load() {
  const [c, s] = await Promise.all([Preferences.get({ key: 'config' }), Preferences.get({ key: 'secrets' })]);
  if (c.value) config = { ...config, ...JSON.parse(c.value) };
  config.view = { ...DEFAULT_VIEW, ...config.view };
  if (s.value) secrets = JSON.parse(s.value);
  for (const a of config.slack) {
    const { value } = await Preferences.get({ key: `cache-slack-${a.id}` });
    caches[a.id] = value ? JSON.parse(value) : null;
  }
}

const saveConfig = () => Preferences.set({ key: 'config', value: JSON.stringify(config) });
const saveSecrets = () => Preferences.set({ key: 'secrets', value: JSON.stringify(secrets) });

// What a chat's unread state is after a new message, so the interface can match it
const countsOf = c => (c ? { unread: !!c.unread, unreadCount: c.unreadCount || 0, mentions: c.mentions || 0 } : null);

function startProvider(p) {
  providers.set(p.id, p);
  p.on('status', s => {
    statuses[p.id] = { provider: p.id, label: p.label, ...s };
    emit('status', statuses[p.id]);
  });
  // Copies, so the interface's changes don't leak back into the providers
  p.on('conversations', list => emit('conversations', { provider: p.id, list: list.map(c => ({ ...c })) }));
  p.on('message', ({ convId, message }) => emit('message', { key: `${p.id}:${convId}`, message, counts: countsOf(p.convs?.get(convId)) }));
  p.on('reaction', ({ convId, ...rest }) => emit('reaction', { key: `${p.id}:${convId}`, ...rest }));
  p.connect();
}

function stopAll() {
  for (const [id, p] of providers) {
    p.removeAllListeners();
    p.disconnect();
    providers.delete(id);
    delete statuses[id];
    emit('conversations', { provider: id, list: [] });
    emit('status', { provider: id, state: 'off' });
  }
}

function startAll() {
  if (secrets.discord) startProvider(new DiscordProvider(secrets.discord, { os: 'Android' }));
  if (secrets.mattermost && config.mattermost.url) {
    startProvider(new MattermostProvider(config.mattermost.url, secrets.mattermost, { poll: true }));
  }
  for (const a of config.slack) {
    const sec = secrets[`slack-${a.id}`];
    if (!sec) continue;
    startProvider(new SlackProvider({
      teamId: a.id,
      teamName: a.name,
      userToken: sec.userToken,
      appToken: sec.appToken,
      cache: {
        load: () => caches[a.id],
        save: data => {
          caches[a.id] = data;
          Preferences.set({ key: `cache-slack-${a.id}`, value: JSON.stringify(data) });
        },
      },
    }));
  }
}

async function scanOnce() {
  const { barcodes } = await BarcodeScanner.scan({ formats: [BarcodeFormat.QrCode] });
  return barcodes[0]?.rawValue || '';
}

// Scans one setup code, or keeps reopening the scanner to collect every part
// of a multi-part code while the Mac cycles through them.
async function scanText() {
  let text = await scanOnce();
  if (!text) throw new Error('No code was scanned');
  if (!text.startsWith('SBP:')) return text;
  const parts = new Map();
  let session = null;
  let total = 0;
  for (let attempt = 0; attempt < 40; attempt++) {
    const m = /^SBP:(\w+):(\d+)\/(\d+):(.*)$/s.exec(text);
    if (m) {
      if (m[1] !== session) {
        session = m[1];
        parts.clear();
      }
      total = Number(m[3]);
      parts.set(Number(m[2]), m[4]);
      if (parts.size === total) return [...parts.entries()].sort((a, b) => a[0] - b[0]).map(e => e[1]).join('');
    }
    navigator.vibrate?.(20);
    text = await scanOnce().catch(() => '');
    if (!text) throw new Error(`Got ${parts.size} of ${total} parts. Tap Scan setup code to try again.`);
  }
  throw new Error('Could not collect every part of the code');
}

function settings() {
  return {
    platform: 'android',
    demo: DEMO,
    mattermostUrl: config.mattermost.url,
    hasDiscord: !!secrets.discord,
    hasMattermost: !!secrets.mattermost,
    slack: config.slack,
    webApps: [],
    view: config.view,
    userAgent: '',
  };
}

function route(key) {
  const i = key.indexOf(':');
  const provider = providers.get(key.slice(0, i));
  if (!provider) throw new Error('That account is not connected');
  return { provider, convId: key.slice(i + 1) };
}

// "SB1:" (accounts) or "SBL:" (layout) + base64(deflate-raw(JSON)), from the Mac app.
async function decodeSetup(text) {
  const kind = { 'SB1:': 'accounts', 'SBL:': 'layout' }[text.slice(0, 4)];
  if (!kind) throw new Error('That is not a Switchboard setup code');
  const bytes = Uint8Array.from(atob(text.slice(4)), ch => ch.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return { kind, data: JSON.parse(await new Response(stream).text()) };
}

// Bottom sheet standing in for the desktop's native context menu.
function actionSheet(items) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'sheet-overlay';
    const close = id => {
      overlay.remove();
      resolve(id);
    };
    const button = (label, cls, onclick) => {
      const b = document.createElement('button');
      b.className = `sheet-item ${cls}`;
      b.textContent = label;
      b.addEventListener('click', e => {
        e.stopPropagation();
        onclick();
      });
      return b;
    };
    const render = (list, title) => {
      const sheet = document.createElement('div');
      sheet.className = 'sheet';
      sheet.addEventListener('click', e => e.stopPropagation());
      if (title) {
        const t = document.createElement('div');
        t.className = 'sheet-title';
        t.textContent = title;
        sheet.append(t);
      }
      for (const item of list) {
        if (item.type === 'separator') {
          const sep = document.createElement('div');
          sep.className = 'sheet-sep';
          sheet.append(sep);
          continue;
        }
        const label = `${item.checked ? '✓ ' : ''}${item.label}${item.submenu ? '  ›' : ''}`;
        const b = button(label, '', () => (item.submenu ? overlay.replaceChildren(render(item.submenu, item.label)) : close(item.id)));
        b.disabled = item.enabled === false;
        sheet.append(b);
      }
      sheet.append(button('Cancel', 'sheet-cancel', () => close(null)));
      return sheet;
    };
    overlay.addEventListener('click', () => close(null));
    overlay.append(render(items));
    document.body.append(overlay);
  });
}

// Long-press on a chat or group header opens its menu. Native long-press
// events are swallowed so only ours (untrusted) reach the app.
function enableLongPress() {
  let timer = null;
  let suppressClickUntil = 0;
  document.addEventListener('contextmenu', e => {
    if (e.isTrusted) e.preventDefault();
  }, true);
  document.addEventListener('touchstart', e => {
    const target = e.target.closest('#convs .conv, #convs .group-head, #messages .msg-stack');
    if (!target) return;
    const { clientX, clientY } = e.touches[0];
    timer = setTimeout(() => {
      timer = null;
      suppressClickUntil = Date.now() + 800;
      navigator.vibrate?.(15);
      target.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX, clientY }));
    }, 500);
  }, { passive: true });
  const cancel = () => {
    clearTimeout(timer);
    timer = null;
  };
  document.addEventListener('touchmove', cancel, { passive: true });
  document.addEventListener('touchend', cancel, { passive: true });
  document.addEventListener('click', e => {
    if (Date.now() < suppressClickUntil) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);
}

// index.html?demo shows sample conversations, for checking the layout.
const DEMO = new URLSearchParams(location.search).has('demo');
const ready = load().then(() => (DEMO ? startProvider(new DemoProvider()) : startAll()));

App.addListener('backButton', () => emit('hotkey', 'back'));
// Android freezes the app in the background; sockets come back dead.
App.addListener('resume', () => {
  for (const p of providers.values()) p.reconnect?.();
  emit('hotkey', 'refresh');
});
enableLongPress();

window.sb = {
  platform: 'android',
  async getState() {
    await ready;
    return {
      settings: settings(),
      statuses,
      conversations: [...providers.values()].flatMap(p => p.conversations()).map(c => ({ ...c })),
    };
  },
  async fetchMessages(key, before) {
    const { provider, convId } = route(key);
    return provider.fetchMessages(convId, before);
  },
  async send(key, text) {
    const { provider, convId } = route(key);
    return provider.send(convId, text);
  },
  async react(key, messageId, value, add) {
    const { provider, convId } = route(key);
    return provider.react(convId, messageId, value, add);
  },
  async upload(key, files, text) {
    const { provider, convId } = route(key);
    return provider.upload(convId, files, text);
  },
  async fetchMedia(key, ref) {
    const { provider } = route(key);
    return provider.fetchMedia(ref);
  },
  async searchGifs(query) {
    const discord = providers.get('discord');
    if (!discord) throw new Error('GIF search uses your Discord account. Add Discord from your Mac first.');
    return discord.searchGifs(query);
  },
  async markRead(key) {
    const { provider, convId } = route(key);
    return provider.markRead(convId);
  },
  async setView(view) {
    config.view = { ...DEFAULT_VIEW, ...view };
    await saveConfig();
  },
  // Accounts code: replaces every account and reconnects. Layout code: replaces
  // groups/nicknames/hidden chats (the page reloads to pick them up).
  async scanSetup() {
    const { available } = await BarcodeScanner.isGoogleBarcodeScannerModuleAvailable();
    if (!available) {
      await BarcodeScanner.installGoogleBarcodeScannerModule();
      throw new Error('Downloading the QR scanner from Google. Try again in a few seconds.');
    }
    const text = await scanText();
    const { kind, data } = await decodeSetup(text);
    if (kind === 'layout') {
      config.view = { ...DEFAULT_VIEW, ...data.view };
      await saveConfig();
      return kind;
    }
    stopAll();
    secrets = {};
    config.slack = [];
    if (data.discord) secrets.discord = data.discord;
    if (data.mattermost) {
      secrets.mattermost = data.mattermost.token;
      config.mattermost.url = data.mattermost.url;
    }
    for (const a of data.slack || []) {
      secrets[`slack-${a.id}`] = { userToken: a.userToken, appToken: a.appToken };
      config.slack.push({ id: a.id, name: a.name });
    }
    await Promise.all([saveConfig(), saveSecrets()]);
    for (const a of config.slack) caches[a.id] ??= null;
    startAll();
    return kind;
  },
  async removeAll() {
    secrets = {};
    config.slack = [];
    config.mattermost.url = '';
    await Promise.all([saveConfig(), saveSecrets()]);
  },
  popupMenu: items => actionSheet(items),
  copyText: text => navigator.clipboard?.writeText(text),
  setBadge() {},
  focus() {},
  // Capacitor hands navigation to other sites to the system browser.
  openExternal(url) {
    if (/^https?:\/\//.test(url)) window.location.assign(url);
  },
  exit: () => App.minimizeApp(),
  on(event, fn) {
    (listeners[event] ||= []).push(fn);
  },
};
