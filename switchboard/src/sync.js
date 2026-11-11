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

const hash = obj => crypto.createHash('sha256').update(JSON.stringify(obj)).digest('hex');

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
      lastSync: c.lastSync || null, // { at, from, what }
      device: DEVICE,
      error,
    };
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
  }

  async function pushLayout() {
    const layout = getLayout();
    const h = hash(layout);
    if (h === cfg().layoutHash) return; // nothing new since the last write or pull
    const at = Date.now();
    await writeJson('layout.json', { v: 1, at, from: DEVICE, ...layout });
    save({ layoutHash: h, layoutAt: at, lastSync: { at, from: DEVICE, what: 'layout' } });
  }

  async function pushLogins() {
    const passphrase = store.getSecret('syncPassphrase');
    if (!passphrase) return;
    const at = Date.now();
    await writeJson('logins.json', { v: 1, at, from: DEVICE, ...(await seal(getLogins(), passphrase)) });
    save({ loginsAt: at, lastSync: { at, from: DEVICE, what: 'logins' } });
  }

  // Takes the other Mac's files when they are newer than what this Mac has.
  async function pull() {
    const layout = await readJson('layout.json');
    if (layout && layout.mtimeMs !== seen.layout) {
      seen.layout = layout.mtimeMs;
      const { v, at, from, ...rest } = layout.data;
      if (v === 1 && at > (cfg().layoutAt || 0)) {
        applyLayout(rest);
        save({ layoutHash: hash(getLayout()), layoutAt: at, lastSync: { at, from, what: 'layout' } });
      }
    }
    const passphrase = store.getSecret('syncPassphrase');
    const logins = await readJson('logins.json');
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
    // After a local layout change; quick successive changes are written once.
    layoutChanged() {
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
