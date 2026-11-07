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
- **Solid block cursor** that blinks just once every 15 minutes (no flashing).
- **Monitor bezel** with a power LED and a phosphor-mode status readout.

## Requirements

- **Python 3** with **Tkinter** (the `tkinter` module).
  - macOS: the system `python3` already includes it — nothing to install.
  - Debian/Ubuntu: `sudo apt install python3-tk`
  - Fedora: `sudo dnf install python3-tkinter`
- A desktop session — it opens a GUI window (won't run over plain SSH).
- Unix only (macOS / Linux). It uses `pty.fork`, so it won't run on Windows.

`pyte` is installed automatically by `run.sh`; you don't need it beforehand.

## Get it & run it

```bash
git clone https://github.com/xod442/myterm.git
cd myterm
./run.sh
```

`run.sh` creates a virtualenv, installs `pyte` the first time, then launches the
app. Every run after that just starts it.

### Manual install (if you'd rather not use run.sh)

```bash
cd myterm
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
- `BLINK_INTERVAL_MS` — how long the cursor stays solid between blinks (default 15 min)
- `BLINK_OFF_MS` — how long the single blink stays dark
- scanline spacing lives in `_draw_scanlines` (the `range(0, h, 3)` step)

## Notes

- Built and tested on macOS with the system Python's Tkinter (8.6).
- Uses `pty.fork` + `TIOCSWINSZ`, so it's Unix-only (macOS/Linux).
