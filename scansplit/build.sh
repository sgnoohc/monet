#!/usr/bin/env bash
# Build scansplit.app — one Swift file, no dependencies beyond the Xcode
# command line tools.  Ad-hoc signed, not notarized.
#
#   ./build.sh               -> dist/scansplit.app
#   ./build.sh --install     -> also copy it to /Applications
set -euo pipefail
cd "$(dirname "$0")"
VERSION=0.1.0
APP=dist/scansplit.app

command -v swiftc >/dev/null || { echo "swiftc missing — xcode-select --install"; exit 1; }

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" build
swiftc -O -parse-as-library -swift-version 5 -target arm64-apple-macos14 \
  scansplit.swift -o build/scansplit-arm64
swiftc -O -parse-as-library -swift-version 5 -target x86_64-apple-macos14 \
  scansplit.swift -o build/scansplit-x86_64
lipo -create build/scansplit-arm64 build/scansplit-x86_64 -output "$APP/Contents/MacOS/scansplit"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>scansplit</string>
  <key>CFBundleDisplayName</key><string>scansplit</string>
  <key>CFBundleIdentifier</key><string>com.github.sgnoohc.scansplit</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>scansplit</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>MIT</string>
  <!-- So a scan and a roster can be dropped on the Dock icon.  Alternate:
       scansplit never becomes the default app for PDFs or CSVs. -->
  <key>CFBundleDocumentTypes</key>
  <array>
    <dict>
      <key>CFBundleTypeName</key><string>PDF scan</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key><array><string>com.adobe.pdf</string></array>
    </dict>
    <dict>
      <key>CFBundleTypeName</key><string>Roster</string>
      <key>CFBundleTypeRole</key><string>Viewer</string>
      <key>LSHandlerRank</key><string>Alternate</string>
      <key>LSItemContentTypes</key><array><string>public.comma-separated-values-text</string></array>
    </dict>
  </array>
</dict></plist>
PLIST

codesign --force --sign - "$APP" >/dev/null 2>&1
echo "built $APP ($VERSION)"

if [ "${1:-}" = "--install" ]; then
  rm -rf /Applications/scansplit.app
  cp -R "$APP" /Applications/
  echo "installed /Applications/scansplit.app"
fi
