# Switchboard

Discord, Mattermost, Slack and Teams in one Mac window: every chat in one list on the left, the conversation on the right.

- **One list** across services, newest first, with unread dots, @mention counts and search (⌘K).
- **Groups** you make yourself (right-click a chat → Move to group, or drag it onto a group). **Ctrl+L** toggles "latest first", which ignores groups.
- **Pins**: Edit → Pin, then tick the chats to pin (or right-click a chat → Pin to top of group). Pinned chats stay at the top of their group in the order you set (right-click → Move pin up/down, or drag a chat onto a pinned one); a thin line separates them from the rest. Unread chats move to the top of their part and go back once read.
- **Choose what shows** with Edit. A hidden chat pops back in when a new message arrives and drops out again once read, unless you keep it.
- **Nicknames** for any chat, visible only to you (right-click → Rename).
- **iMessage-style bubbles**, reply quotes, compact list (☰), **Ctrl+J / Ctrl+K** to move between chats.
- **Teams** (personal and UF) and other sites run as embedded web apps with their own logins.

## Accounts

| Service | How it connects |
|---|---|
| Discord | Your user token (unofficial; see the warning in Settings) |
| Mattermost | Official API; sign in through the server's own login page (CERN SSO works) |
| Slack | Official API through your own private Slack app (Settings has the manifest) |
| Teams | Embedded web app |

Tokens are encrypted with the macOS Keychain (Electron `safeStorage`) and stored under `~/Library/Application Support/Switchboard/`, never in this folder.

## Run and build

```bash
npm install
npm start          # run from source
npm run demo       # sample conversations, no accounts needed
npm run package    # builds dist/Switchboard-darwin-arm64/Switchboard.app
```

Copy the built app into `~/Applications` to install it. Needs Node 22 (newer Node breaks nothing here, but Electron bundles its own).

## Phone (Android)

`mobile/` is the Pixel version, built with Capacitor from the same interface and connectors: Discord, Mattermost and Slack in one list, with groups, nicknames and bubbles. It works while open (no background notifications). Mattermost checks for new messages every 15 s, because servers refuse websockets from app origins.

Set it up by scanning the code from **Settings → Set up phone** on the Mac; that copies your accounts, groups and nicknames.

```bash
cd mobile
npm install
npm run apk            # builds android/app/build/outputs/apk/debug/app-debug.apk
npm run install-phone  # adb install over USB (USB debugging on)
```

Needs Java 21 (`brew install openjdk@21`) and the Android SDK (`brew install --cask android-commandlinetools`, then `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"`), with `JAVA_HOME` and `ANDROID_HOME` set.

## Terminal (Mattermost only)

`cli/sbmm.js` (linked as `sbmm`) is Mattermost in the terminal: chat list on the left, the conversation on the right, message line at the bottom. It reuses the desktop app's login (read from the macOS Keychain; macOS asks once), groups and nicknames.

| Key | Does |
|---|---|
| Ctrl+J / Ctrl+K (or Ctrl+N / Ctrl+P, Alt+J / Alt+K) | next / previous chat |
| PgUp / PgDn, ↑ / ↓ | scroll (older messages load at the top) |
| Ctrl+F | find a chat; Enter opens the first match |
| Ctrl+L | latest first (ignore groups) |
| `/react 👍` | toggle a reaction on the latest message from someone else |
| `/style` | switch between `plain` (one line per message, like Discordo; the default) and `bubbles`; remembered |
| Ctrl+C | quit |

`sbmm --demo` shows sample chats.

### On another machine

`npm run cli` builds standalone copies into `dist-cli/`:

- `sbmm-linux-x64`, `sbmm-linux-arm64`, `sbmm-darwin-arm64`, `sbmm-darwin-x64`: self-contained programs, nothing to install (built with Bun)
- `sbmm.js`: one file for any machine with Node 18+

Copy one over and give it your login. The Mac's login (plus groups and nicknames) travels as a code:

```bash
scp dist-cli/sbmm-linux-x64 otherhost:bin/sbmm
sbmm --export-login | ssh otherhost bin/sbmm --login -
```

or run `sbmm --login` there and paste the code (or a personal access token). The login is saved in `~/.config/sbmm/config.json` (readable only by you); `sbmm --logout` removes it. The code is a live Mattermost session: treat it like a password. When the session expires, export it again.

## Layout

- `main.js`: window, IPC, account management, web-app sandboxing
- `src/providers/`: one file per service (`discord.js`, `mattermost.js`, `slack.js`, plus `demo.js`)
- `src/store.js`: settings and encrypted tokens
- `renderer/`: the interface (`app.js`, `styles.css`, `index.html`)
- `cli/`: terminal Mattermost client
- `mobile/`: Android app (`src/bridge.js` runs the providers in the phone's web view; `build.mjs` assembles it)
- `gmhelper/`: start of a Google Messages helper (Go, on hold)
