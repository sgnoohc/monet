# calc

A curses-based TUI calculator with switchable skins.

## Skins

- **Office Calculator** — classic desktop calculator layout (4×8 grid)
- **TI-83 Plus** — styled after the TI-83 graphing calculator (5×8 grid, wide ENTER key)

Press `s` to toggle between skins.

## Features

- Recursive-descent expression parser with proper operator precedence
- Functions: `sin`, `cos`, `tan`, `log`, `ln`, `sqrt`
- Constants: `pi`, `e`, `ANS` (previous result)
- Implicit multiplication (e.g. `2pi`, `3(4+5)`)
- Exponentiation with `^`
- Visual button-press flash feedback
- Direct keyboard input — type digits and operators directly
- 256-color support with fallback for basic terminals

## Usage

```
python calc.py
```

## Controls

| Key               | Action              |
|--------------------|---------------------|
| `h/j/k/l`, arrows | Navigate buttons    |
| `Enter`, `Space`   | Press button        |
| `0-9`, `+-*/%^.()` | Direct input        |
| `=`                | Evaluate            |
| `c`                | Clear               |
| `Backspace`        | Delete last char    |
| `s`                | Switch skin         |
| `q`                | Quit                |
