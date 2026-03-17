# Session Chair Timer

A full-screen, browser-based countdown timer for managing conference presentation sessions. No server or dependencies required — just open `index.html` in a browser.

![Screenshot placeholder](https://img.shields.io/badge/status-ready-green)

## Features

- **Markdown-based schedule** — configure sessions using a markdown table or list in a built-in editor with live preview
- **Split timing** — supports `10+2 min` format for talk + Q&A phases with distinct visual indicators
- **Manual start/stop** — start, pause, resume, and reset each session independently (talks never run exactly on schedule)
- **Color warnings**:
  - Normal: dark blue
  - 3 minutes remaining: yellow
  - 1 minute remaining: red
  - Over time: pulsing bright red with `+MM:SS` display
- **Q&A phase** has its own color scheme (blue) with tighter warnings (yellow at 1 min, red at 30 sec)
- **Real-time clock** and scheduled time range displayed in the top bar
- **Bottom schedule bar** — click any session to jump directly to it
- **Speed multiplier** (1x / 5x / 10x / 30x) for testing and dry runs
- **Keyboard shortcuts**:
  - `Space` — start / pause
  - `R` — reset current session
  - `Left arrow` or `P` — previous session
  - `Right arrow` or `N` — next session

## Usage

1. Open `index.html` in any modern browser
2. Edit the schedule in the markdown editor (or use the pre-loaded example)
3. Click **Start Timer**
4. Use **Start** to begin the countdown when the presenter is ready
5. Navigate between sessions with **Prev** / **Next** or click the bottom bar

## Markdown Format

### Table format

```markdown
## Session Block Title

| Time  | Duration | Session                              |
|-------|----------|--------------------------------------|
| 09:00 | 15 min   | Opening Remarks — Speaker Name       |
| 09:15 | 10+2 min | Talk Title — Speaker Name            |
```

### List format

```markdown
- 09:00 | 15 min | Opening Remarks — Speaker Name
- 09:15 | 10+2 min | Talk Title — Speaker Name
```

- Column order is auto-detected (time, duration, and session name)
- `10+2 min` means 10 minutes for the talk, 2 minutes for Q&A
- Plain `12 min` works for sessions without a Q&A split
- Headings (`## ...`) and blank lines are ignored — use them to organize
