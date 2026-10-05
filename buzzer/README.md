# Buzzer Drill

Practice buzzing the instant a quiz bowl tossup finishes being read.

**Play:** https://sgnoohc.github.io/monet/buzzer/

- The browser reads each tossup aloud (Web Speech API). The whole question shows in gray and each word lights up as it is read.
- Press **Space** or tap the buzzer. **Enter** starts the next tossup, **Esc** stops one.
- A buzz after the reading ends is timed in milliseconds from the last word: Sharp ≤250, Quick ≤500, Steady ≤1000, Slow above that.
- A buzz before the end is a neg, shown as a negative time (how early you were). In Voice mode that is estimated from the reading pace; Text-only mode is exact.
- No buzz within 5 seconds is a dead tossup.
- 24 built-in tossups, or paste your own as `question | answer`, one per line.
- Results are kept in the browser's local storage.

Voice timing starts when the browser reports the speech ended, which can trail the last syllable by about 50–150 ms. Text-only mode times from the moment the last word appears.

Single static file: `index.html`.
