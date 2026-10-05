#!/bin/bash
# Render packets.json to speech and encode each tossup as MP3 into ../audio/.
# usage: tools/build-audio.sh [voice name]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
swift "$here/render.swift" "$here/packets.json" "$tmp" "${1:-Samantha}"
mkdir -p "$here/../audio"
rm -f "$here/../audio/"*.m4a "$here/../audio/"*.mp3
for w in "$tmp"/*.wav; do
  ffmpeg -loglevel error -y -i "$w" -ac 1 -codec:a libmp3lame -b:a 48k "$here/../audio/$(basename "${w%.wav}").mp3"
done
echo "$(ls "$here/../audio" | wc -l | tr -d ' ') files, $(du -sh "$here/../audio" | cut -f1)"
