#!/bin/bash
# Makes a code-signing certificate that stays on this Mac (login Keychain), so
# each build of Switchboard keeps the same identity. Run once per Mac.
set -euo pipefail
NAME="Switchboard Local Signing"
if security find-identity -p codesigning | grep -q "\"$NAME\""; then echo "Already set up: $NAME"; exit 0; fi
DIR=$(mktemp -d)
trap 'rm -rf "$DIR"' EXIT
cat > "$DIR/cert.cnf" <<CNF
[req]
distinguished_name = dn
x509_extensions = ext
prompt = no
[dn]
CN = $NAME
[ext]
basicConstraints = critical,CA:false
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
CNF
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$DIR/key.pem" -out "$DIR/cert.pem" -days 7300 -config "$DIR/cert.cnf" 2>/dev/null
PASS=$(openssl rand -hex 12)
openssl pkcs12 -export -inkey "$DIR/key.pem" -in "$DIR/cert.pem" -out "$DIR/id.p12" -passout "pass:$PASS" -name "$NAME" -legacy 2>/dev/null \
  || openssl pkcs12 -export -inkey "$DIR/key.pem" -in "$DIR/cert.pem" -out "$DIR/id.p12" -passout "pass:$PASS" -name "$NAME"
security import "$DIR/id.p12" -k "$HOME/Library/Keychains/login.keychain-db" -P "$PASS" -T /usr/bin/codesign
echo "Made $NAME. The first build asks once to let codesign use it: choose Always Allow."
