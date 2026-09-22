#!/usr/bin/env bash
# Build redpen.app: a self-contained Mac app.
#
# Everything it needs is carried inside the bundle -- Python, Pillow, numpy,
# typst, poppler and the on-device Vision helper -- so it runs on a Mac with
# no Homebrew, no Python and no Xcode.  Nothing is fetched at run time.
#
#   ./mac/build_app.sh              -> mac/dist/redpen.app
#   ./mac/build_app.sh --dmg        -> also a disk image to hand someone
#
# The result is ad-hoc signed, not notarized: on another Mac the first launch
# needs right-click -> Open (see mac/README-install.txt, written alongside).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
VENV=${VENV:-$ROOT/.venv}
PY=$VENV/bin/python
APP=$ROOT/mac/dist/redpen.app
# redpen/__init__.py is the one place the version lives; pyproject reads the
# same attribute, and this becomes the bundle's CFBundleShortVersionString,
# which is what the About box shows.
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' redpen/__init__.py | head -1)
[ -n "$VERSION" ] || { echo "no __version__ in redpen/__init__.py"; exit 1; }

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }

[ -x "$PY" ] || { echo "no venv at $VENV — pip install -e . in one first"; exit 1; }
command -v swiftc >/dev/null || { echo "swiftc missing — install the Xcode command line tools"; exit 1; }
command -v typst  >/dev/null || { echo "typst missing — brew install typst (only to BUILD)"; exit 1; }
"$PY" -c "import PyInstaller" 2>/dev/null || { echo "pip install pyinstaller in $VENV"; exit 1; }

# ---- 1. the Vision helper, compiled now so the app needs no compiler -------
say "compiling the on-device OCR helper"
swiftc -O redpen/vision/visionocr.swift -o redpen/vision/visionocr

# ---- 2. the Python backend ------------------------------------------------
say "freezing the backend"
rm -rf mac/build mac/dist/redpen-backend "$APP"
"$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN \
  --name redpen-backend --onedir --console \
  --distpath mac/dist --workpath mac/build --specpath mac \
  --paths "$ROOT" \
  --add-data "$ROOT/redpen/quizlib.typ:redpen" \
  --add-data "$ROOT/redpen/vision/visionocr:redpen/vision" \
  --add-data "$ROOT/redpen/vision/visionocr.swift:redpen/vision" \
  mac/redpen_backend.py >/dev/null

# ---- 3. the window --------------------------------------------------------
say "compiling the window"
mkdir -p mac/build
swiftc -O mac/redpen.swift -o mac/build/redpen

# ---- 4. assemble ----------------------------------------------------------
say "assembling the bundle"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/backend"
cp mac/build/redpen "$APP/Contents/MacOS/redpen"
cp -R mac/dist/redpen-backend/. "$APP/Contents/Resources/backend/"
[ -f mac/redpen.icns ] && cp mac/redpen.icns "$APP/Contents/Resources/redpen.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>redpen</string>
  <key>CFBundleDisplayName</key><string>redpen</string>
  <key>CFBundleIdentifier</key><string>com.github.sgnoohc.redpen</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>redpen</string>
  <key>CFBundleIconFile</key><string>redpen.icns</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>MIT</string>
  <!-- The interface is a page served by the app itself, on loopback only. -->
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST

# ---- 5. the tools it shells out to ----------------------------------------
say "bundling typst and poppler"
BIN=$APP/Contents/Resources/backend/bin
mkdir -p "$BIN/lib"
cp "$(command -v typst)" "$BIN/typst"
for t in pdftoppm pdfinfo pdfseparate pdfunite; do
  command -v "$t" >/dev/null || { echo "missing $t — brew install poppler"; exit 1; }
  cp "$(command -v "$t")" "$BIN/$t"
done
chmod u+w "$BIN"/* "$BIN"/lib 2>/dev/null || true

# Copy every library those tools reach, and repoint each reference at the copy
# inside the bundle.  Poppler asks for its own library as @rpath/..., not by an
# absolute path, so a search for "/opt/homebrew" alone misses it and the app
# dies with "Library not loaded" on a machine without Homebrew -- which is the
# only machine that matters here.  Repeats until nothing new turns up, because
# the libraries have libraries.
BREW=$(brew --prefix 2>/dev/null || echo /opt/homebrew)

find_lib() {                                  # $1 = libfoo.N.dylib
  local n=$1 p
  for p in "$BREW/lib/$n" "$BREW"/opt/*/lib/"$n" "/usr/local/lib/$n"; do
    [ -f "$p" ] && { echo "$p"; return 0; }
  done
  return 1
}

resolve_libs() {
  local changed=1 b dep base src
  while [ $changed -eq 1 ]; do
    changed=0
    for b in "$BIN"/* "$BIN"/lib/*; do
      [ -f "$b" ] || continue
      while read -r dep; do
        case "$dep" in
          /usr/lib/*|/System/*) continue ;;
          @rpath/*|@loader_path/*)  base=$(basename "$dep"); src=$(find_lib "$base") || continue ;;
          "$BREW"/*|/usr/local/Cellar/*|/usr/local/opt/*)
                                    base=$(basename "$dep"); src=$dep ;;
          @executable_path/*) continue ;;
          *) continue ;;
        esac
        if [ ! -f "$BIN/lib/$base" ]; then
          cp -L "$src" "$BIN/lib/$base"; chmod u+w "$BIN/lib/$base"; changed=1
        fi
        install_name_tool -change "$dep" "@executable_path/lib/$base" "$b" 2>/dev/null || true
      done < <(otool -L "$b" 2>/dev/null | tail -n +2 | awk '{print $1}')
    done
  done
  for l in "$BIN"/lib/*; do
    [ -f "$l" ] && install_name_tool -id "@executable_path/lib/$(basename "$l")" "$l" 2>/dev/null || true
  done
}
resolve_libs
echo "    $(ls "$BIN" | grep -v '^lib$' | tr '\n' ' ')"
echo "    $(ls "$BIN"/lib 2>/dev/null | wc -l | tr -d ' ') bundled libraries"

# ---- 6. sign --------------------------------------------------------------
# install_name_tool invalidates a signature, and on Apple silicon an unsigned
# binary will not run at all, so everything is re-signed ad-hoc.  Deepest
# first: the bundle's own signature has to be applied last.
say "signing (ad-hoc)"
# Every Mach-O, not just the ones with the execute bit: the libraries had
# their load commands rewritten too, and on Apple silicon a dylib with a stale
# signature takes the whole process down with SIGKILL.  Libraries first, then
# the tools that load them, then the bundle.
for f in "$BIN"/lib/* "$BIN"/*; do
  [ -f "$f" ] || continue
  codesign --force --timestamp=none -s - "$f" >/dev/null 2>&1 || true
done
find "$APP/Contents/Resources/backend/_internal" -name "*.dylib" -o -name "*.so" 2>/dev/null |
  while read -r f; do codesign --force --timestamp=none -s - "$f" >/dev/null 2>&1 || true; done
codesign --force --deep --timestamp=none -s - "$APP" 2>/dev/null || \
  codesign --force --deep -s - "$APP"
codesign --verify --deep "$APP" && echo "    signature verifies"

# ---- 7. prove it is self-contained ----------------------------------------
# Built on a machine that has Homebrew; it has to run on one that does not.
say "checking it runs with no Homebrew on PATH"
for t in typst pdfinfo pdftoppm pdfseparate pdfunite; do
  if env -i PATH=/usr/bin:/bin "$BIN/$t" --version >/dev/null 2>&1 ||
     env -i PATH=/usr/bin:/bin "$BIN/$t" -v >/dev/null 2>&1; then
    echo "    $t ok"
  else
    echo "    $t FAILS without Homebrew:"
    env -i PATH=/usr/bin:/bin "$BIN/$t" -v 2>&1 | head -2 | sed "s/^/      /"
    exit 1
  fi
done
if leftover=$(otool -L "$BIN"/* 2>/dev/null | grep -E "$BREW|/usr/local/(Cellar|opt)" | head -3); then
  if [ -n "$leftover" ]; then
    echo "    still points outside the bundle:"; echo "$leftover" | sed "s/^/      /"; exit 1
  fi
fi

cat > mac/dist/README-install.txt <<TXT
redpen — install
================

Drag redpen.app to your Applications folder.

The app is not notarized by Apple, so the FIRST time you open it on a new Mac:

    right-click (or control-click) redpen.app  ->  Open  ->  Open

Only the first launch needs this; afterwards it opens normally. If you prefer
the terminal, this does the same thing:

    xattr -dr com.apple.quarantine /Applications/redpen.app

Nothing else is needed. Python, typst and poppler are all inside the app, and
everything — including reading the handwriting — runs on your own machine.
TXT

SIZE=$(du -sh "$APP" | cut -f1)
say "built $APP  ($SIZE)"

if [ "${1:-}" = "--dmg" ]; then
  say "making a disk image"
  rm -f mac/dist/redpen.dmg
  STAGE=$(mktemp -d)
  cp -R "$APP" "$STAGE/"
  cp mac/dist/README-install.txt "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -quiet -volname redpen -srcfolder "$STAGE" -ov -format UDZO mac/dist/redpen.dmg
  rm -rf "$STAGE"
  say "built mac/dist/redpen.dmg ($(du -sh mac/dist/redpen.dmg | cut -f1))"
fi
