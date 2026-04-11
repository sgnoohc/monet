# Space Attack

A terminal-based space shooter built with Python curses — defend Earth from waves of alien invaders.

```
  ____  ____   _    ____ _____      _  _____ _____  _    ____ _  __
 / ___||  _ \ / \  / ___| ____|    / \|_   _|_   _|/ \  / ___| |/ /
 \___ \| |_) / _ \| |   |  _|     / _ \ | |   | | / _ \| |   | ' /
  ___) |  __/ ___ \ |___| |___   / ___ \| |   | |/ ___ \ |___| . \
 |____/|_| /_/   \_\____|_____| /_/   \_\_|   |_/_/   \_\____|_|\_\
```

## Features

- **ASCII art sprites** — player ship, two fighter variants, bombers, destructible bunkers, and animated explosions
- **4 difficulty levels** — Easy, Medium, Difficult, Insane (adjusts alien fire rate and movement speed)
- **Destructible bunkers** — four shields that erode from both player and alien fire; bombs blast larger craters
- **Alien HP system** — fighters take 2 hits, bombers take 3; color shifts from full health to critical
- **Title screen** with difficulty selector and in-game status bar

## Requirements

- Python 3.6+
- A terminal at least **130 x 58** characters
- No external dependencies (uses only `curses`, `time`, `random`)

## Running

```bash
python3 space_attack.py
```

## Controls

| Key | Action |
|-----|--------|
| Arrow Left / Right | Move ship |
| Space | Shoot |
| Q | Quit |
| R | Restart (after game over) |
| M | Return to menu (after game over) |
