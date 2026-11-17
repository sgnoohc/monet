// Keeps Switchboard the same on several Macs through a synced folder
// (OneDrive, iCloud Drive, ...). Two files live there:
//   layout.json  groups, pins, nicknames, hidden chats, people's colors and
//                pictures, list options and web apps. No logins.
//   logins.json  the account logins, encrypted with a passphrase typed once on
//                each Mac (scrypt + AES-256-GCM). Without the passphrase it is
//                unreadable, and it is only written when you sign in or out.
// Each Mac writes after a local change and checks the folder every 20 s; the
// newer file wins. A Mac that turns sync on adopts what is already there.
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { promisify } = require('util');

const scrypt = promisify(crypto.scrypt);
const POLL_MS = 20000;
const PUSH_DELAY_MS = 1500;
const DEVICE = os.hostname().replace(/\.local$/, '');
// What layout.json holds. 2: color tags and chat backgrounds. A file without it
// was written by an older Switchboard, which leaves those out (and drops them
// when it reads a newer file), so Settings asks to update that Mac.
const FORMAT = 2;
const layoutOf = data => ({ view: data.view, webApps: data.webApps });

const hash = obj => crypto.createHash('sha256').update(JSON.stringify(obj)).digest('hex');

// What each part of the layout is called in Settings, to say what changed.
const LAYOUT_PARTS = [
  ['groups', ['groups', 'assign']],
  ['pins', ['pins']],
  ['nicknames', ['nicknames']],
  ['color tags', ['tags', 'tagOf']],
  ['backgrounds', ['backgrounds']],
  ["people's colors and pictures", ['people']],
  ['shown and hidden chats', ['mode', 'keys']],
  ['list options', ['otherCollapsed', 'compact', 'flat', 'bigPictures', 'dmNames', 'showTimes']],
];

function layoutChanges(a, b) {
  const av = a?.view || {};
  const bv = b?.view || {};
  const same = k => JSON.stringify(av[k] ?? null) === JSON.stringify(bv[k] ?? null);
  const out = LAYOUT_PARTS.filter(([, keys]) => !keys.every(same)).map(([label]) => label);
  if (JSON.stringify(a?.webApps ?? null) !== JSON.stringify(b?.webApps ?? null)) out.push('web apps');
  return out;
}

// Which accounts differ between two sets of logins, by name (never the secrets).
function loginChanges(a, b) {
  const out = [];
  if ((a?.discord || null) !== (b?.discord || null)) out.push('Discord');
  if (JSON.stringify(a?.mattermost || null) !== JSON.stringify(b?.mattermost || null)) out.push('Mattermost');
  const slack = list => new Map((list || []).map(x => [x.id, x]));
  const sa = slack(a?.slack);
  const sb = slack(b?.slack);
  for (const id of new Set([...sa.keys(), ...sb.keys()])) {
    if (sa.get(id)?.secret !== sb.get(id)?.secret) out.push(`Slack (${(sa.get(id) || sb.get(id)).name || 'Slack'})`);
  }
  return out;
}

async function seal(payload, passphrase) {
  const salt = crypto.randomBytes(16);
  const iv = crypto.randomBytes(12);
  const key = await scrypt(passphrase, salt, 32, { N: 1 << 15, r: 8, p: 1, maxmem: 64 * 1024 * 1024 });
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const data = Buffer.concat([cipher.update(JSON.stringify(payload), 'utf8'), cipher.final()]);
  const b64 = b => b.toString('base64');
  return { salt: b64(salt), iv: b64(iv), tag: b64(cipher.getAuthTag()), data: b64(data) };
}

async function open(box, passphrase) {
  const buf = s => Buffer.from(s, 'base64');
  const key = await scrypt(passphrase, buf(box.salt), 32, { N: 1 << 15, r: 8, p: 1, maxmem: 64 * 1024 * 1024 });
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, buf(box.iv));
  decipher.setAuthTag(buf(box.tag));
  try {
    return JSON.parse(Buffer.concat([decipher.update(buf(box.data)), decipher.final()]).toString('utf8'));
  } catch {
    throw new Error('Wrong passphrase: it must match the one on your other Mac');
  }
}

// The OneDrive folder macOS mounts under ~/Library/CloudStorage, if there is one.
function suggestedFolder() {
  const root = path.join(os.homedir(), 'Library', 'CloudStorage');
  try {
    const dir = fs.readdirSync(root).find(d => d.startsWith('OneDrive'));
    if (dir) return path.join(root, dir, 'Switchboard');
  } catch {}
  return null;
}

// store: src/store.js. getLayout() -> { view, webApps }; applyLayout(layout).
// getLogins() -> payload; applyLogins(payload). onStatus(status) after changes.
function createSync({ store, getLayout, applyLayout, getLogins, applyLogins, onStatus }) {
  let pushTimer = null;
  let pollTimer = null;
  let queue = Promise.resolve(); // file work runs one step at a time, in order
  let pollQueued = false;
  let error = null;
  const seen = { layout: 0, logins: 0 }; // file mtimes already handled
  const files = { layout: null, logins: null }; // { at, from } of what is in the folder
  let localChangedAt = 0; // when the layout last changed here
  let running = null; // { step, steps, label } while "Sync now" works
  let lastRun = null; // what the last "Sync now" did

  const cfg = () => store.getConfig().sync || {};
  const save = patch => store.setConfig({ sync: { ...cfg(), ...patch } });
  const file = name => path.join(cfg().folder, name);
  const enabled = () => !!cfg().folder;

  function status() {
    const c = cfg();
    return {
      enabled: enabled(),
      folder: c.folder || null,
      suggested: suggestedFolder(),
      hasPassphrase: !!store.getSecret('syncPassphrase'),
      lastSync: c.lastSync || null, // { at, from, what, changes }
      device: DEVICE,
      files,
      pending: pending(),
      running,
      lastRun,
      error,
    };
  }

  // Which way "Sync now" would go: 'send' (this Mac has changes the folder
  // doesn't), 'get' (the folder has newer settings), or null (the same).
  function pending() {
    if (!enabled()) return null;
    const f = files.layout;
    if (f && takesLayout(f.at)) return 'get';
    if (!f || hash(getLayout()) !== cfg().layoutHash) return 'send';
    return null;
  }

  const report = (patch = {}) => {
    if ('error' in patch) error = patch.error;
    onStatus(status());
  };

  async function readJson(name) {
    try {
      const p = file(name);
      const { mtimeMs } = await fs.promises.stat(p);
      return { mtimeMs, data: JSON.parse(await fs.promises.readFile(p, 'utf8')) };
    } catch (e) {
      if (e.code === 'ENOENT') return null;
      throw new Error(`Couldn't read ${name} in the sync folder (${e.message})`);
    }
  }

  async function writeJson(name, data) {
    await fs.promises.mkdir(cfg().folder, { recursive: true });
    await fs.promises.writeFile(file(name), JSON.stringify(data));
    seen[name.replace('.json', '')] = (await fs.promises.stat(file(name))).mtimeMs;
    files[name.replace('.json', '')] = { at: data.at, from: data.from, format: data.format || 1 };
  }

  const note = (name, read) => {
    if (read?.data?.at) files[name] = { at: read.data.at, from: read.data.from, format: read.data.format || 1 };
    return read;
  };

  // Returns what changed compared with the folder's copy, or null if nothing was written.
  async function pushLayout(previous) {
    const layout = getLayout();
    const h = hash(layout);
    if (h === cfg().layoutHash) return null; // nothing new since the last write or pull
    if (previous === undefined) {
      const data = (await readJson('layout.json'))?.data;
      previous = data?.v === 1 ? layoutOf(data) : null;
    }
    const changes = previous ? layoutChanges(previous, layout) : ['everything (first copy)'];
    const at = Date.now();
    await writeJson('layout.json', { v: 1, format: FORMAT, at, from: DEVICE, ...layout });
    save({ layoutHash: h, layoutAt: at, lastSync: { at, from: DEVICE, what: 'settings', changes } });
    return changes;
  }

  async function pushLogins() {
    const passphrase = store.getSecret('syncPassphrase');
    if (!passphrase) return;
    const at = Date.now();
    await writeJson('logins.json', { v: 1, at, from: DEVICE, ...(await seal(getLogins(), passphrase)) });
    save({ loginsAt: at, lastSync: { at, from: DEVICE, what: 'logins' } });
  }

  // The folder's settings are taken when written after this Mac last synced,
  // unless this Mac has changed its own since then (it then sends them instead).
  const takesLayout = at => at > (cfg().layoutAt || 0)
    && !(localChangedAt > at && hash(getLayout()) !== cfg().layoutHash);

  function takeLayout(read) {
    const { at, from } = read.data;
    const before = getLayout();
    applyLayout(layoutOf(read.data));
    const after = getLayout();
    const changes = layoutChanges(before, after);
    save({ layoutHash: hash(after), layoutAt: at, lastSync: { at, from, what: 'settings', changes } });
    return { from, changes };
  }

  // Takes the other Mac's files when they are newer than what this Mac has.
  async function pull() {
    const layout = note('layout', await readJson('layout.json'));
    if (layout && layout.mtimeMs !== seen.layout) {
      seen.layout = layout.mtimeMs;
      if (layout.data.v === 1 && takesLayout(layout.data.at)) takeLayout(layout);
    }
    const passphrase = store.getSecret('syncPassphrase');
    const logins = note('logins', await readJson('logins.json'));
    if (passphrase && logins && logins.mtimeMs !== seen.logins) {
      const { v, at, from, ...box } = logins.data;
      if (v === 1 && at > (cfg().loginsAt || 0)) {
        applyLogins(await open(box, passphrase));
        save({ loginsAt: at, lastSync: { at, from, what: 'logins' } });
      }
      seen.logins = logins.mtimeMs; // after a successful open, so a wrong passphrase is retried once fixed
    }
  }

  // Runs fn after whatever sync work is already underway. Errors are shown in
  // Settings; with rethrow they also go back to the caller (wrong passphrase).
  function serial(fn, { rethrow = false } = {}) {
    const run = queue.then(async () => {
      try {
        const result = await fn();
        report({ error: null });
        return result;
      } catch (e) {
        report({ error: e.message });
        if (rethrow) throw e;
      }
    });
    queue = run.catch(() => {});
    return run;
  }

  const guarded = fn => serial(async () => {
    if (enabled()) await fn();
  });

  // A check that is already waiting covers this one too.
  function poll() {
    if (pollQueued) return queue;
    pollQueued = true;
    return serial(async () => {
      pollQueued = false; // cleared even when sync is off, so later checks aren't skipped
      if (enabled()) await pull();
    });
  }

  // Step by step, saying what went where. mode:
  //   'sync'  both ways: the newer copy wins
  //   'send'  this Mac's setup replaces the folder's (the other Mac then takes it)
  //   'get'   the folder's setup replaces this Mac's
  async function syncNow(mode) {
    clearTimeout(pushTimer); // a waiting local change is sent here
    const steps = 3;
    const step = (n, label) => {
      running = { step: n, steps, label, mode };
      report();
    };
    const result = { at: 0, mode, folder: cfg().folder, settings: null, logins: null };

    step(0, 'Reading the sync folder…');
    const layout = note('layout', await readJson('layout.json'));
    if (layout) seen.layout = layout.mtimeMs;
    const remote = layout?.data?.v === 1 ? layout.data : null;
    if (mode === 'get' && !remote) throw new Error('The sync folder has no settings yet. Send them from the Mac that has your setup.');
    if (remote && (mode === 'get' || (mode === 'sync' && takesLayout(remote.at)))) {
      step(1, `Copying settings from ${remote.from} to this Mac…`);
      const got = takeLayout(layout);
      result.settings = got.changes.length
        ? { action: 'received', from: got.from, at: remote.at, changes: got.changes }
        : { action: 'same', from: remote.from, at: remote.at };
    } else {
      step(1, mode === 'send' ? 'Copying this Mac\'s settings to the folder…' : 'Comparing this Mac\'s settings with the folder…');
      if (mode === 'send') save({ layoutHash: null }); // written even when nothing seems new
      const sent = await pushLayout(remote ? layoutOf(remote) : null);
      result.settings = sent
        ? { action: 'sent', changes: sent }
        : { action: 'same', from: remote?.from, at: remote?.at };
    }

    const passphrase = store.getSecret('syncPassphrase');
    if (!passphrase) {
      result.logins = { action: 'off' };
    } else {
      step(2, 'Checking logins…');
      const logins = note('logins', await readJson('logins.json'));
      const box = logins?.data?.v === 1 ? (({ v, at, from, ...rest }) => rest)(logins.data) : null;
      const theirs = box ? await open(box, passphrase) : null;
      if (logins) seen.logins = logins.mtimeMs;
      const mine = getLogins();
      const take = theirs && (mode === 'get' || (mode === 'sync' && logins.data.at > (cfg().loginsAt || 0)));
      if (take) {
        step(2, `Copying logins from ${logins.data.from} to this Mac…`);
        const changes = loginChanges(mine, theirs);
        applyLogins(theirs);
        save({ loginsAt: logins.data.at, lastSync: { at: logins.data.at, from: logins.data.from, what: 'logins' } });
        result.logins = changes.length
          ? { action: 'received', from: logins.data.from, at: logins.data.at, changes }
          : { action: 'same', from: logins.data.from, at: logins.data.at };
      } else if (mode !== 'get') {
        const changes = theirs ? loginChanges(theirs, mine) : ['all accounts (first copy)'];
        if (changes.length || mode === 'send') {
          step(2, 'Copying this Mac\'s logins to the folder (encrypted)…');
          await pushLogins();
          result.logins = changes.length ? { action: 'sent', changes } : { action: 'same', from: DEVICE, at: Date.now() };
        } else {
          result.logins = { action: 'same', from: logins.data.from, at: logins.data.at };
        }
      } else {
        result.logins = { action: 'none' };
      }
    }

    step(3, 'Done');
    result.at = Date.now();
    result.oldFormat = remote && !remote.format && remote.from !== DEVICE && result.settings.action !== 'sent' ? remote.from : null;
    lastRun = result;
  }

  function start() {
    clearInterval(pollTimer);
    if (!enabled()) return;
    pollTimer = setInterval(poll, POLL_MS);
    poll();
  }

  return {
    status,
    start,
    poll,
    // mode: 'sync', 'send' or 'get' (see above). Resolves when done.
    syncNow(mode = 'sync') {
      if (!['sync', 'send', 'get'].includes(mode)) mode = 'sync';
      return serial(async () => {
        if (!enabled()) return;
        try {
          await syncNow(mode);
        } catch (e) {
          lastRun = { at: Date.now(), mode, folder: cfg().folder, error: e.message };
          throw e;
        } finally {
          running = null;
        }
      });
    },
    // After a local layout change; quick successive changes are written once.
    layoutChanged() {
      localChangedAt = Date.now();
      if (!enabled()) return;
      clearTimeout(pushTimer);
      pushTimer = setTimeout(() => guarded(pushLayout), PUSH_DELAY_MS);
    },
    // After signing in or out of an account here.
    loginsChanged: () => guarded(pushLogins),

    // Turning sync on: if the folder already has the other Mac's settings, take
    // them; otherwise this Mac's settings become the first copy.
    async enable(folder) {
      folder = folder || suggestedFolder();
      if (!folder) throw new Error('No OneDrive folder found. Choose a folder that syncs between your Macs.');
      await serial(async () => {
        save({ folder, layoutHash: null, layoutAt: 0, loginsAt: 0, lastSync: null });
        seen.layout = 0;
        seen.logins = 0;
        if (await readJson('layout.json')) await pull();
        else await pushLayout();
        if (!(await readJson('logins.json'))) await pushLogins();
      });
      start();
    },

    disable() {
      clearInterval(pollTimer);
      clearTimeout(pushTimer);
      save({ folder: null });
      error = null;
      report();
    },

    // The same passphrase on every Mac. If the folder has logins, they must
    // open with it (and are then used here); if not, this Mac's are sealed with it.
    setPassphrase(passphrase) {
      passphrase = String(passphrase || '');
      if (passphrase.length < 8) return Promise.reject(new Error('Use a passphrase of at least 8 characters'));
      return serial(async () => {
        const logins = enabled() ? await readJson('logins.json') : null;
        if (logins?.data?.v === 1) {
          const { v, at, from, ...box } = logins.data;
          const payload = await open(box, passphrase); // throws on a mismatch, before anything is saved
          store.setSecret('syncPassphrase', passphrase);
          applyLogins(payload);
          seen.logins = logins.mtimeMs;
          save({ loginsAt: at, lastSync: { at, from, what: 'logins' } });
          return;
        }
        store.setSecret('syncPassphrase', passphrase);
        if (enabled()) await pushLogins();
      }, { rethrow: true });
    },
  };
}

module.exports = { createSync };
