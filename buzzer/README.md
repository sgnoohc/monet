# Buzzer Drill

Practice buzzing the instant a tossup finishes being read.

**Play:** https://sgnoohc.github.io/monet/buzzer/

- **Recorded reader (default):** each built-in tossup is a recording played through Web Audio. The end of the reading is the last audible sample of the decoded audio, mapped to the keyboard/touch event clock with the audio output timestamp, so reaction times are measured against what you actually hear. The waveform under the buzzer is the real audio.
- **Browser voice** reads your own questions (Web Speech API); its end time depends on when the browser reports the speech ended (±50–150 ms). **Text only** reveals words at a fixed pace.
- Packets: **Civics Bowl** (49 tossups from the civics study guide), **General** (20), or paste your own as `question | answer`, one per line.
- Press **Space** or tap the buzzer. **Enter** starts the next tossup, **Esc** stops one.
- Buzz after the end: timed in ms (Sharp ≤250, Quick ≤500, Steady ≤1000, Slow). Before the end: a neg, shown as a negative time.
- **Early buffer** (0–500 ms): a buzz that close before the end counts as on time.
- A buzzer sound plays on each buzz (Web Audio; toggle under Display).
- Results are kept in the browser's local storage.

Use speakers or wired headphones for the most accurate times; Bluetooth adds delay the browser can't always report.

## Rebuilding the recordings

Questions live in `tools/packets.json`. After editing them, copy the lists into `PACKETS` in `index.html` and run:

    tools/build-audio.sh            # macOS: renders with the Samantha voice into audio/*.mp3
    tools/build-audio.sh "Daniel"   # or another installed voice
