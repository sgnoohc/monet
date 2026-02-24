# memorize

An interactive terminal-based memorization tool for line-by-line text recall practice, built with Python curses.

## Usage

By default, it reads the `text` file in the same directory as `memorize.py`:

```bash
python3 memorize.py
```

To memorize a different file, pass it as an argument:

```bash
python3 memorize.py /path/to/my_speech.txt
```

When using a custom file, stats are saved alongside it (e.g. `my_speech_stats.json`).

## How It Works

Lines are presented one at a time, hidden by default. You try to recall each line, then reveal it to check. You can mark lines as "struggling" or "confident", and the tool tracks your statistics in `memorize_stats.json`.

## Modes

- **Normal** — step through lines sequentially
- **Review** — focus on lines where struggle count exceeds confident count, sorted by difficulty
- **Test** — shows the previous line as context and asks you to recall what comes next

## Controls

| Key | Action |
|-----|--------|
| `SPACE` | Reveal line / advance to next |
| `s` | Mark as struggling |
| `c` | Mark as confident |
| `h` | Hint (reveal one word at a time) |
| `b` | Go back one line |
| `f` | Reveal line / go forward one line |
| `g` | Go to a specific line number |
| `v` | Enter review mode |
| `x` | Enter test mode |
| `n` | Return to normal mode |
| `t` | Show statistics summary |
| `w` | Toggle word count hint |
| `p` | Toggle showing previous lines |
| `+`/`-` | Adjust number of previous lines shown |
| `e` | Edit current line in vim |
| `E` | Edit full file in vim (jumps to current line) |
| `l` | Cycle label mode (line number / item number / both) |
| `q` | Quit |
