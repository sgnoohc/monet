#!/usr/bin/env bash
# Write data/registries-<version>.json: the ids a server of that version sends for sounds, entity
# types, items, particles and block states, from the vanilla server's own data generator (so they're
# exact: minecraft-data's sound table for 1.21.11 is one off). Needs Java 21+.
#
#   tools/make-registries.sh <vanilla server jar> <version>
#   tools/make-registries.sh ~/minecraft-mod/servers/pvp/test/tmp/server/.fabric/server/1.21.11-server.jar 1.21.11
set -euo pipefail
jar="${1:?the vanilla server jar}"
version="${2:?the Minecraft version, e.g. 1.21.11}"
here="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${JAVA_HOME:-$HOME/.local/share/jdk/current}/bin:$PATH"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
(cd "$work" && java -DbundlerMainClass=net.minecraft.data.Main -jar "$(realpath "$jar")" --reports --output "$work/out" > "$work/log" 2>&1)
python3 - "$work/out/reports" "$here/data/registries-$version.json" "$version" <<'EOF'
import json, sys
reports, out, version = sys.argv[1:]
registries = json.load(open(f'{reports}/registries.json'))
def by_id(name):
    entries = registries[name]['entries']
    names = [None] * (max(e['protocol_id'] for e in entries.values()) + 1)
    for key, e in entries.items():
        names[e['protocol_id']] = key.removeprefix('minecraft:')
    return names
# Block states: each block's ids are one run, so first and last are enough.
blocks = []
for key, block in json.load(open(f'{reports}/blocks.json')).items():
    ids = [s['id'] for s in block['states']]
    blocks.append([min(ids), max(ids), key.removeprefix('minecraft:')])
blocks.sort()
data = {
    'version': version,
    'sound_event': by_id('minecraft:sound_event'),
    'entity_type': by_id('minecraft:entity_type'),
    'item': by_id('minecraft:item'),
    'particle_type': by_id('minecraft:particle_type'),
    'block_states': blocks,
}
json.dump(data, open(out, 'w'), separators=(',', ':'))
print(f"wrote {out}: {len(data['sound_event'])} sounds, {len(data['entity_type'])} entity types, "
      f"{len(data['item'])} items, {len(data['particle_type'])} particles, {len(blocks)} blocks")
EOF
