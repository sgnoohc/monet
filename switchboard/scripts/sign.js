// Signs the packaged app. With the "Switchboard Local Signing" certificate in
// this Mac's login Keychain, every build has the same identity, so macOS keeps
// its "Always Allow" for Switchboard's saved logins. Without the certificate
// the app is signed ad hoc, which makes macOS ask again after each build.
// Make the certificate once with: npm run make-cert
const { execFileSync } = require('child_process');

const APP = 'dist/Switchboard-darwin-arm64/Switchboard.app';
const NAME = 'Switchboard Local Signing';

let identity = '-';
try {
  if (execFileSync('security', ['find-identity', '-p', 'codesigning'], { encoding: 'utf8' }).includes(`"${NAME}"`)) identity = NAME;
} catch {}
if (identity === '-') console.log(`No "${NAME}" certificate: signing ad hoc (macOS will ask for Keychain access again). Run npm run make-cert once to fix.`);
execFileSync('codesign', ['--force', '--deep', '--sign', identity, APP], { stdio: 'inherit' });
console.log(`signed with ${identity === '-' ? 'an ad-hoc signature' : NAME}`);
