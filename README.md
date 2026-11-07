# pyterm — a retro CRT terminal emulator

A real, working terminal emulator written in Python, dressed up to look like an
old phosphor CRT monitor.

![green phosphor](https://img.shields.io/badge/phosphor-green%20%7C%20amber%20%7C%20white-33ff66)

## What it actually is

Not a fake "type a command and see canned output" demo — it spawns your real
login shell and talks to it, so `vim`, `htop`, `top`, `less`, `ssh`, tab
completion, colors, and Ctrl-C all work.

Three moving parts:

1. **pty** (Python stdlib) — forks a pseudo-terminal running `$SHELL`.
2. **pyte** — interprets the shell's ANSI/VT escape codes into a screen grid.
3. **Tkinter** — draws that grid with the CRT look.

## The CRT look

- **Monochrome phosphor** — the authentic old-terminal style: everything glows
  in one color. Bold renders brighter; reverse-video is honored so TUIs stay
  readable.
- **Scanlines** — a dithered horizontal-line overlay across the "glass".
- **Blinking block cursor** and **subtle brightness flicker**.
- **Monitor bezel** with a power LED and a phosphor-mode status readout.

## Run it

```bash
cd ~/pyterm
./run.sh
```

`run.sh` creates a virtualenv and installs `pyte` the first time, then launches
the app. (Run it from a desktop session — it opens a GUI window.)

Or manually:

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python pyterm.py
```

## Keys

| Key   | Action                                   |
|-------|------------------------------------------|
| `F11` | Toggle fullscreen                        |
| `F12` | Cycle phosphor color (green → amber → white) |
| *(all other keys)* | Forwarded to the shell      |

## Tweaking

Open `pyterm.py` and edit the constants near the top:

- `DEFAULT_COLS` / `DEFAULT_ROWS` — startup grid size
- `THEMES` — add or recolor phosphor palettes
- `FONT_FAMILY` / `FONT_SIZE` — the glow font
- `BLINK_MS`, `FLICKER_MS` — cursor and flicker timing
- scanline spacing lives in `_draw_scanlines` (the `range(0, h, 3)` step)

## Notes

- Built and tested on macOS with the system Python's Tkinter (8.6).
- Uses `pty.fork` + `TIOCSWINSZ`, so it's Unix-only (macOS/Linux).
