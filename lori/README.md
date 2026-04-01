# lori — Life Orchestration & Routine Intelligence

Personal life orchestration tool. Terminal-based daily briefings, project tracking, schedule management, driving time queries, and HTML dashboard emails.

## Setup

```bash
lori init          # creates ~/.lori/ with template YAML files
lori setup         # interactive configuration wizard
lori               # full daily briefing → then interactive TUI
lori --short       # compact one-liner (for login hook, no TUI)
```

After the briefing, `lori` launches an interactive TUI for managing projects, tasks, and your calendar — no subcommands needed.

## CLI Commands

| Command | Description |
|---------|-------------|
| `lori` | Full daily briefing, then launch TUI |
| `lori --short` | Compact briefing (no TUI) |
| `lori init` | First-run setup (creates ~/.lori/) |
| `lori setup` | Interactive configuration wizard |
| `lori week` | Weekly overview with free time |
| `lori projects` | List all projects |
| `lori show <name>` | Project details (fuzzy match) |
| `lori checkin` | Interactive project follow-up |
| `lori add project` | Guided Q&A to add project |
| `lori add event` | Guided Q&A to add event |
| `lori add task <project> <desc>` | Quick task add |
| `lori add milestone <project> <name> --due DATE` | Quick milestone add |
| `lori done <item>` | Fuzzy-match mark complete |
| `lori undone` | Undo a completed milestone |
| `lori drive <from> <to>` | Driving time query (OSRM) |
| `lori reschedule <project>` | Reschedule milestones |
| `lori timeline <project>` | Visual milestone timeline |
| `lori html` | Generate HTML dashboard |
| `lori email` | Email HTML dashboard |
| `lori alert setup` | Install scrontab alerts |
| `lori edit` | Open YAML files in $EDITOR |

## TUI

The TUI has two modes, toggled with `c`:

**Task mode** — manage projects, milestones, and tasks across four views (cycle with `v`):
- **Projects** — all projects with details panel
- **Today / Week / Month** — timeline of upcoming items

**Calendar mode** — schedule and events across four views:
- **Day** — single day event list
- **N-Day** — 2–14 consecutive days (`+`/`-` to adjust)
- **Week** — 7-day column layout
- **Month** — full calendar grid

### Key bindings

Global:
| Key | Action |
|-----|--------|
| `v` | Cycle view |
| `c` | Toggle task/calendar mode |
| `i` | Quick-capture to Inbox |
| `j`/`k` or `↑`/`↓` | Navigate |
| `g`/`G` | Jump to top/bottom |
| `Enter`/`→` | Enter detail panel |
| `Esc`/`←` | Back to left panel |
| `q` | Quit |

Projects view:
| Key | Action |
|-----|--------|
| `a` | Add project |
| `x` | Delete project |
| `A` | Archive project (paused/completed) |
| `s` | Toggle sort by due date |
| `f` | Filter (active only / all) |

Timeline views (Today/Week/Month):
| Key | Action |
|-----|--------|
| `a` | Add item |
| `d` | Mark done |
| `u` | Mark undone |
| `r` | Reschedule |
| `x` | Delete |

Calendar views:
| Key | Action |
|-----|--------|
| `a` | Add event |
| `e` | Edit event |
| `x` | Delete event |
| `y`/`p` | Copy/paste event |
| `o` | Open location URL |
| `h`/`l` | Previous/next day or month |
| `t` | Jump to today |
| `S` | Toggle week start (Mon/Sun) |

Detail panel (right side):
| Key | Action |
|-----|--------|
| `d` | Mark done |
| `u` | Undo done |
| `x` | Delete |
| `r` | Reschedule |
| `a` | Add item |
| `n` | Edit notes |
| `m` | Move from Inbox |

## Data Files (~/.lori/)

- `config.yaml` — preferences, email settings, weather API key
- `projects.yaml` — projects with milestones & tasks
- `schedule.yaml` — events, recurring items, travel, blocked time
- `locations.yaml` — saved places with coordinates

## MCP Server

`mcp_server.py` exposes driving time tools for Claude Code integration.
