#!/usr/bin/env bash
# Run the analysis (bin/analyze.js) with Node.js 22 or later: the one on the PATH, or else one in
# ~/.local/share/node/current. Installs the packages the first time. Options as for bin/analyze.js:
#
#   ./analyze.sh --server pvphq --server 25569
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
command -v node >/dev/null || export PATH="$HOME/.local/share/node/current/bin:$PATH"
command -v node >/dev/null || { echo "Node.js 22 or later is needed: https://nodejs.org"; exit 1; }
major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$major" -ge 22 ] || { echo "Node.js 22 or later is needed (this is $(node --version)): https://nodejs.org"; exit 1; }
[ -d "$here/node_modules" ] || (cd "$here" && npm ci --silent --no-audit --no-fund)
exec node "$here/bin/analyze.js" "$@"
