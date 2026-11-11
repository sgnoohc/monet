// Assembles www/ for the Android app from the desktop interface plus the
// phone bridge. Run with `npm run build` (or `npm run apk` to also build the APK).
import { build } from 'esbuild';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const here = import.meta.dirname;
const renderer = path.join(here, '..', 'renderer');
const out = path.join(here, 'www');

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

await build({
  absWorkingDir: here,
  entryPoints: ['src/bridge.js'],
  outfile: path.join(out, 'bridge.js'),
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'chrome120',
  alias: { ws: './src/ws-shim.js', events: './node_modules/events/events.js' },
  logLevel: 'warning',
});

for (const file of ['app.js', 'styles.css']) fs.copyFileSync(path.join(renderer, file), path.join(out, file));
fs.copyFileSync(path.join(here, 'mobile.css'), path.join(out, 'mobile.css'));

// Same page as the desktop, with a phone viewport, the phone stylesheet and the
// bridge loaded before the app. The desktop CSP is dropped: the page talks to
// Discord/Slack websockets directly and Capacitor injects its own scripts.
let html = fs.readFileSync(path.join(renderer, 'index.html'), 'utf8');
const swaps = [
  [/<meta http-equiv="Content-Security-Policy"[^>]*>/, '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'],
  ['<link rel="stylesheet" href="styles.css">', '<link rel="stylesheet" href="styles.css">\n  <link rel="stylesheet" href="mobile.css">'],
  ['<script src="app.js"></script>', '<script src="bridge.js"></script>\n  <script src="app.js"></script>'],
];
for (const [from, to] of swaps) {
  const next = html.replace(from, to);
  if (next === html) throw new Error(`index.html no longer contains ${from}`);
  html = next;
}
fs.writeFileSync(path.join(out, 'index.html'), html);

// People's pictures are too big for the setup QR codes, so they ride along in
// the APK instead: copied from this Mac's own settings into www/ (git-ignored,
// like the APK), never into the repository.
const macConfig = path.join(os.homedir(), 'Library', 'Application Support', 'Switchboard', 'config.json');
const pictures = {};
try {
  for (const [key, p] of Object.entries(JSON.parse(fs.readFileSync(macConfig, 'utf8')).view?.people || {})) {
    if (p?.image) pictures[key] = p.image;
  }
} catch {} // no Mac app settings here: the phone just keeps its own pictures
fs.writeFileSync(path.join(out, 'pictures.json'), JSON.stringify(pictures));
if (Object.keys(pictures).length) console.log(`included ${Object.keys(pictures).length} people's pictures from the Mac app`);
console.log('built', out);
