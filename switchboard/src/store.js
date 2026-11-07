// Config lives in userData/config.json; tokens are encrypted with Electron's
// safeStorage (key held in the macOS Keychain) and kept in secrets.json.
const { app, safeStorage } = require('electron');
const fs = require('fs');
const path = require('path');

const DEFAULT_CONFIG = {
  mattermost: { url: 'https://mattermost.web.cern.ch' },
  // Sidebar visibility. mode 'all': keys are hidden chats. mode 'selected': keys are the only chats shown.
  view: { mode: 'all', keys: [], groups: [], assign: {}, nicknames: {}, otherCollapsed: false, compact: false, flat: false },
  slack: [], // [{ id: team id, name }]; tokens live in secrets as slack-<id>
  webApps: [
    { id: 'teams-personal', name: 'Teams (personal)', service: 'teams', url: 'https://teams.live.com/v2/' },
    { id: 'teams-uf', name: 'Teams (UF)', service: 'teams', url: 'https://teams.microsoft.com/v2/' },
  ],
};

const file = name => path.join(app.getPath('userData'), name);

function readJson(name, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file(name), 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJson(name, data) {
  fs.mkdirSync(app.getPath('userData'), { recursive: true });
  fs.writeFileSync(file(name), JSON.stringify(data, null, 2), { mode: 0o600 });
}

function getConfig() {
  const saved = readJson('config.json', {});
  return {
    ...DEFAULT_CONFIG,
    ...saved,
    mattermost: { ...DEFAULT_CONFIG.mattermost, ...saved.mattermost },
    view: { ...DEFAULT_CONFIG.view, ...saved.view },
  };
}

function setConfig(patch) {
  const next = { ...getConfig(), ...patch };
  writeJson('config.json', next);
  return next;
}

function getSecret(name) {
  const b64 = readJson('secrets.json', {})[name];
  if (!b64) return null;
  try {
    return safeStorage.decryptString(Buffer.from(b64, 'base64'));
  } catch {
    return null;
  }
}

function setSecret(name, value) {
  if (!safeStorage.isEncryptionAvailable()) throw new Error('macOS Keychain encryption is unavailable');
  const secrets = readJson('secrets.json', {});
  secrets[name] = safeStorage.encryptString(value).toString('base64');
  writeJson('secrets.json', secrets);
}

function deleteSecret(name) {
  const secrets = readJson('secrets.json', {});
  delete secrets[name];
  writeJson('secrets.json', secrets);
}

// Non-secret per-account cache (e.g. Slack user names and recent activity).
function cache(name) {
  return {
    load: () => readJson(`cache-${name}.json`, null),
    save: data => writeJson(`cache-${name}.json`, data),
  };
}

function deleteCache(name) {
  fs.rmSync(file(`cache-${name}.json`), { force: true });
}

module.exports = { getConfig, setConfig, getSecret, setSecret, deleteSecret, cache, deleteCache };
