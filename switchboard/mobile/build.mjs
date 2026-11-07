// Assembles www/ for the Android app from the desktop interface plus the
// phone bridge. Run with `npm run build` (or `npm run apk` to also build the APK).
import { build } from 'esbuild';
import fs from 'node:fs';
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
console.log('built', out);
