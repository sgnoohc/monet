# PvP analysis

Numbers from Minecraft PvP fights, read from [Replay Mod](https://www.replaymod.com/) recordings:
who hit whom, how (crits, sprint hits, sweeps), from how far, how fast they clicked, how they moved,
what they used. A first step towards a sparring bot that moves like the players it's recorded.

## Install

Needs [Node.js](https://nodejs.org) 22 or later, and git. The project is a folder of the `monet`
repository:

    git clone https://github.com/sgnoohc/monet.git
    cd monet/pvp-analysis
    ./analyze.sh                    # on Windows: analyze.cmd

The first run installs the packages it needs (into `node_modules/`). To get just this folder and not
the rest of `monet`: `git clone --filter=blob:none --sparse https://github.com/sgnoohc/monet.git`,
then `cd monet && git sparse-checkout set pvp-analysis`. To update: `git pull`.

## Use

With [Replay Mod](https://www.replaymod.com/) recordings (`.mcpr`, in the game folder's `replay_recordings`):

    ./analyze.sh                                      # new recordings in, reports out
    ./analyze.sh --server pvphq --server 25569        # just these servers (overrides config.json)
    ./analyze.sh path/to/one.mcpr path/to/folder      # these recordings
    ./analyze.sh --force                              # analyse every recording again

(`analyze.cmd` on Windows, with the same options.) With no recordings given, it looks in Replay Mod's
`replay_recordings` in every [Prism Launcher](https://prismlauncher.org) instance (Prism as a Flatpak
too) and in the vanilla launcher's game folder (`~/.minecraft`; on macOS
`~/Library/Application Support/minecraft`; on Windows `%APPDATA%\.minecraft`), or where
`config.json`'s `folders` says.

Then open `reports/index.html` (the path is printed at the end).

**Run it after every session of recordings.** Each recording is analysed once and saved in
`history/` (a JSON file per recording), so a run only reads the new ones, and fights stay in the
reports and trends even after you delete their recordings. The reports are made from the whole
history every time.

**More than one computer.** Each computer keeps its own `history/`. To see every computer's fights in
one dashboard, copy the `history/*.json` files from one to the other and run `./analyze.sh` again: a
recording's file is named for the recording, so copying never makes doubles.

`analyze.sh` runs `bin/analyze.js` with the `node` on your PATH (or, if there's none, one in
`~/.local/share/node/current`); `node bin/analyze.js …` is the same, once the packages are installed.

It writes, in `reports/`:

- **`index.html`**, the dashboard (one file, works offline, light and dark): headline numbers with
  the change since the last session; how each measure moves over time, you against your opponents,
  a point per recording (or per day: there's a switch, and it moves to days once there are three);
  how your hits land (crits, sprint hits, sweeps); reach at hits; every fight, with its hit timeline
  and everything measured, both sides; and how each opponent fights. Fights new in the latest run are
  marked. Every chart has a table under it.
- `report.md`, the same as text: a table per fight, both fighters side by side, then your totals.
- `fights.json`, every number, for analysis of your own.

`config.json` holds the defaults: `servers` (only recordings on servers whose address has one of
these in it: PvPHQ, and the sparring server by its port, 25569, leaving out Quake Arena's gauntlet
fights) and, optionally, `folders` (where to look for recordings, such as
`["~/Games/minecraft/replay_recordings"]`).
A recording made of the same session twice (same server, start and length, such as copies in two
instances) is only read once; Replay Mod's working folders (`raw/`, `recording/`) are skipped.

**Changing the analysis.** When a change makes the numbers come out differently, bump
`ANALYZER_VERSION` in `src/fights.js`: the next run analyses every recording again that's still on
disk (keeping when each was first added), and keeps the old analysis of any that aren't.

**Recording fights:** start Replay Mod's recording before the duel's countdown and stop it after the
result, so the whole fight is in it. Both fighters are analysed, you and your opponent.

## What it measures, and how

A **fight** is a run of melee hits between the same two players, ending after 15 seconds without a
hit or when one of them dies. Hits from further than 6 blocks aren't melee (Quake Arena's guns) and
are left out. The winner is whoever didn't die, or your VICTORY / DEFEAT title.

| | How |
|---|---|
| Hits | `damage_event` packets, which name the attacker |
| Crits | the crit animation on the one hit, in the same tick (the server sends it to everyone) |
| Sweeps | the sweep particles, at the attacker |
| Sprint hits | the attacker was sprinting (their sprint flag) at the hit |
| Reach | from the attacker's eyes to the nearest point of the other's hitbox at the hit: what the server checks (3 blocks in survival) |
| Clicks | arm swings: CPS over the fight and in its best second, double clicks (two swings within 60 ms), swings that hit |
| Combos | hits in a row without being hit back: the longest, and how many of 3 or more |
| Movement | distance kept, sideways speed relative to the other player (strafing), time sprinting, jumps, sprint resets (w-taps) |
| Items | golden apples eaten, potions drunk, pearls, totems, shield blocks (sounds at the player), blocks placed near them (cobwebs, water, logs) |
| Health | the lowest it got, when the server sends it (yours always; others' only if the server shares it) |

**You** are the account the recording was made with (from the login, not the login's entity id,
which some servers, PvPHQ among them, replace).

**Limits.** Positions are what the recording player's game saw: other players' are a little behind
the server (their ping, and the client's smoothing), so their reach can read a little long or short;
yours are exact. Keys and clicks aren't recorded, only what the server was told: a click that didn't
swing isn't seen. The attack sounds (crit, knockback, sweep) aren't sent to the one who attacked, so
they're not used; the animation, particles and sprint flag are, and they're seen for everyone.

## Privacy

Recordings name everyone in them, and so do the history and the reports: `recordings/`, `history/`,
`reports/` and `*.mcpr` are in `.gitignore`. Don't commit or share them without the other players' names taken out.

## Files

| | |
|---|---|
| `analyze.sh`, `analyze.cmd` | run it (Linux and macOS; Windows), installing the packages the first time |
| `bin/analyze.js` | the command: new recordings into the history, reports out of it |
| `config.json` | which servers, and where the recordings are |
| `src/zip.js` | reads the `.mcpr` (a zip) |
| `src/replay.js` | the recording's packets, decoded with minecraft-protocol through login, configuration and play (and back to configuration when a proxy moves you to another server) |
| `src/world.js` | follows the players and writes down what they do |
| `src/fights.js` | fights, and each fighter's numbers |
| `src/history.js` | the history: an analysis per recording, in `history/` |
| `src/dashboard.js` | the dashboard: the fights as JSON in one HTML page that draws its own charts (SVG) |
| `src/report.js` | the Markdown report |
| `data/registries-1.21.11.json` | the ids the server sends (sounds, entity types, items, particles, block states), from the vanilla server's own data generator: minecraft-data's sound table for 1.21.11 is one off |
| `tools/make-registries.sh` | makes that file for a Minecraft version, from its server jar |
| `tools/packets.js` | what's in a recording: packets by kind, and any that can't be read |
| `test/run.js` | `npm test`: a recording written with minecraft-protocol's encoder, read back; a made-up fight where every number is known; the history; the dashboard (and that a player's name can't break out of it) |
