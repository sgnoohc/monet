// Builds standalone copies of sbmm into dist-cli/:
//   sbmm.js              one file, needs Node 18+ (no npm install)
//   sbmm-<os>-<arch>     self-contained programs, if Bun is installed
import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const root = path.join(import.meta.dirname, '..');
const out = path.join(root, 'dist-cli');
fs.mkdirSync(out, { recursive: true });

await build({
  entryPoints: [path.join(root, 'cli', 'sbmm.js')],
  outfile: path.join(out, 'sbmm.js'),
  bundle: true,
  platform: 'node',
  target: 'node18',
  format: 'cjs',
  external: ['bufferutil', 'utf-8-validate'], // optional speedups for ws
  logLevel: 'warning',
});
fs.chmodSync(path.join(out, 'sbmm.js'), 0o755);
console.log('built dist-cli/sbmm.js');

let bun;
try {
  bun = execFileSync('which', ['bun'], { encoding: 'utf8' }).trim();
} catch {
  console.log('Bun not found; skipping self-contained programs (brew install oven-sh/bun/bun)');
  process.exit(0);
}
for (const target of ['linux-x64', 'linux-arm64', 'darwin-arm64', 'darwin-x64']) {
  execFileSync(bun, ['build', path.join(out, 'sbmm.js'), '--compile', `--target=bun-${target}`, '--outfile', path.join(out, `sbmm-${target}`)], { stdio: 'ignore' });
  console.log(`built dist-cli/sbmm-${target}`);
}
