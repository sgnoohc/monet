#!/usr/bin/env bash
# Wrap gmailify.css in a UserCSS metadata block + @-moz-document so Stylus can
# install it. Regenerate after every edit to gmailify.css.
set -euo pipefail
cd "$(dirname "$0")"

# Version lives in the /* @version x.y.z */ marker at the top of gmailify.css.
SRC=${1:-gmailify.css}
OUT=${2:-gmailify.user.css}
VERSION=$(sed -n 's|^/\* @version \(.*\) \*/|\1|p' "$SRC" | head -1)
VERSION=${VERSION:-0.1.0}

{
  cat <<HEADER
/* ==UserStyle==
@name           gmailify${NAME_SUFFIX:-} — Outlook as Gmail
@namespace      github.com/sgnoohc/monet
@version        ${VERSION}
@description    Reskins outlook.cloud.microsoft to look like Gmail.
@author         sgnoohc
@license        MIT
@homepageURL    https://github.com/sgnoohc/monet/tree/main/gmailify
@supportURL     https://github.com/sgnoohc/monet/issues
@updateURL      https://raw.githubusercontent.com/sgnoohc/monet/main/gmailify/gmailify.user.css
==/UserStyle== */

@-moz-document domain("outlook.cloud.microsoft"),
               domain("outlook.office.com"),
               domain("outlook.office365.com"),
               domain("outlook.live.com") {
HEADER
  # Embedded @font-face blocks first, then the stylesheet.
  # LOCAL=1 builds your personal copy: the Google Sans faces from
  # fonts.local.css and the photo from background.css, neither of which is
  # committed.  LOCAL=1 ./build.sh gmailify.css gmailify.local.user.css
  FONTS=fonts.css
  if [ "${LOCAL:-0}" = "1" ] && [ -f fonts.local.css ]; then FONTS=fonts.local.css; fi
  sed 's/^/  /; s/[[:space:]]*$//' "$FONTS"
  sed 's/^/  /; s/[[:space:]]*$//' "$SRC"
  # Background last: it overrides the --gm-bg-image default in gmailify.css.
  # Opt-in, because background.css embeds a photo that should stay on your own
  # machine rather than being committed.
  if [ "${LOCAL:-0}" = "1" ] && [ -f background.css ]; then
    sed 's/^/  /; s/[[:space:]]*$//' background.css
  fi
  echo "}"
} > "$OUT"

echo "built $OUT (v${VERSION}, $(wc -l < "$OUT") lines)"
