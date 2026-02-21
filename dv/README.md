# dv - Interactive Disk Usage Viewer

A terminal-based interactive viewer for `du` output. Browse your disk usage like a file manager — navigate directories, sort by size or name, and drill into subdirectories.

## Requirements

- Python 3.6+
- No external dependencies (stdlib only: `termios`, `tty`, `signal`)
- Unix/Linux/macOS terminal

## Generating Input

```bash
du /path/to/directory > du.txt
```

The input file should be in standard `du` output format (`SIZE\tPATH`, sizes in KB).

## Usage

```bash
python3 dv.py <du_file>
```

If no file is specified, it defaults to `du.txt` in the current directory.

### Example

```bash
du -a ~ > du.txt
python3 dv.py du.txt
```

## Keybindings

| Key | Action |
|---|---|
| `j` / `Down` | Move cursor down |
| `k` / `Up` | Move cursor up |
| `l` / `Right` / `Enter` | Enter directory |
| `h` / `Left` / `Backspace` | Go to parent directory |
| `PgUp` / `PgDn` | Scroll by page |
| `g` / `G` | Jump to top / bottom |
| `i` | **Go in** — set selected directory as virtual root |
| `o` | **Go out** — reset virtual root to actual root |
| `s` | Cycle sort mode: size desc → size asc → name A-Z → name Z-A |
| `q` / `ESC` | Quit |

## Interface

```
Path: ./some/directory  [Sort: Size (largest first)]
      SIZE  NAME
   1.05 GB  |-- CMSSW_15_0_0_pre3/
 970.57 MB  |-- thesis/
 814.24 MB  |-- www/
      32 KB  +-- .ssh
[q]uit [jk]move [l/Enter]enter [h]back [i]go-in [o]go-out [s]ort  4 items
```

- Directories with children show a trailing `/`
- The selected row is highlighted with reverse video
- `|--` connects items; `+--` marks the last item in a list

## Features

- **One-pass parsing** — loads large `du` files (200K+ lines) efficiently
- **Memory-efficient** — uses `__slots__` on tree nodes
- **No curses dependency** — uses raw ANSI escape codes for maximum compatibility
- **Terminal resize handling** — responds to SIGWINCH
- **Cursor memory** — when navigating back, the cursor returns to the directory you came from
