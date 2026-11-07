#!/usr/bin/env python3
"""
pyterm — a retro CRT terminal emulator.

A real terminal emulator built from three pieces:
  * a pseudo-terminal (pty) running your login shell
  * pyte, which interprets the shell's ANSI/VT output into a screen grid
  * a Tkinter Canvas that draws that grid with a phosphor-CRT aesthetic

Everything (glyphs, cursor, scanlines) is painted on one Canvas. Tkinter widgets
are opaque, so a scanline *overlay* widget would hide the text — instead the
scanlines are drawn as canvas items stacked on top of the glyphs.

Monochrome phosphor is the authentic old-CRT look, so by default every cell is
drawn in one glowing color. Bold is rendered brighter and reverse-video is
honored so full-screen tools (vim, htop, less) remain usable.

Keys:
  F11  toggle fullscreen
  F12  cycle phosphor color (green -> amber -> white)
  Everything else is forwarded to the shell.
"""

import os
import pty
import fcntl
import termios
import struct
import select
import signal
import threading
import queue
import tkinter as tk
import tkinter.font as tkfont

import pyte


# ---------------------------------------------------------------------------
# Look & feel
# ---------------------------------------------------------------------------

DEFAULT_COLS = 90
DEFAULT_ROWS = 28

# Phosphor palettes. "fg" is the resting glow, "bright" is bold/highlight,
# "bg" is the faint darkness of an unlit phosphor screen, "dim" drives flicker.
THEMES = {
    "green": {"fg": "#33ff66", "bright": "#c7ffd8", "bg": "#021405", "dim": "#1d9a44"},
    "amber": {"fg": "#ffb000", "bright": "#ffe0a3", "bg": "#160c00", "dim": "#9c6a00"},
    "white": {"fg": "#dfe8ff", "bright": "#ffffff", "bg": "#04060a", "dim": "#64758c"},
}
THEME_ORDER = ["green", "amber", "white"]


# ---------------------------------------------------------------------------
# pyte screen with a bug workaround
# ---------------------------------------------------------------------------

class SafeScreen(pyte.Screen):
    """pyte 0.8.x crashes when a private-marked ``CSI ... m`` sequence is
    dispatched (e.g. ``ESC[>4;2m`` from vim's modifyOtherKeys setup): the
    parser calls ``select_graphic_rendition(..., private=True)`` but the stock
    handler doesn't accept that keyword. Swallow it so full-screen apps work."""

    def select_graphic_rendition(self, *attrs, **kwargs):
        super().select_graphic_rendition(*attrs)

BEZEL = "#141210"          # monitor shell
BEZEL_EDGE = "#2a2622"     # inner lip of the bezel
SCANLINE = "#000000"       # scanline tint (stippled, so semi-transparent)
FONT_FAMILY = "Menlo"      # falls back gracefully if unavailable
FONT_SIZE = 15
PAD = 8                    # inner padding inside the glass, in pixels

BLINK_INTERVAL_MS = 15 * 60 * 1000  # cursor stays solid this long between blinks
BLINK_OFF_MS = 400                  # how long the single blink lasts (cursor dark)


# ---------------------------------------------------------------------------
# Pseudo-terminal: spawn and talk to the shell
# ---------------------------------------------------------------------------

class Pty:
    """A forked pseudo-terminal running the user's shell."""

    def __init__(self, cols, rows, shell=None):
        self.shell = shell or os.environ.get("SHELL", "/bin/bash")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            # --- child process: become the shell ---
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            try:
                os.execvpe(self.shell, [self.shell], env)
            except OSError:
                os._exit(1)
        # --- parent process ---
        self.set_size(cols, rows)

    def set_size(self, cols, rows):
        """Tell the kernel the terminal's window size (so apps can lay out)."""
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def write(self, data):
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGHUP)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Special-key translation: Tkinter keysym -> terminal byte sequence
# ---------------------------------------------------------------------------

SPECIAL_KEYS = {
    "Return": b"\r",
    "KP_Enter": b"\r",
    "BackSpace": b"\x7f",
    "Tab": b"\t",
    "Escape": b"\x1b",
    "Up": b"\x1b[A",
    "Down": b"\x1b[B",
    "Right": b"\x1b[C",
    "Left": b"\x1b[D",
    "Home": b"\x1b[H",
    "End": b"\x1b[F",
    "Prior": b"\x1b[5~",   # Page Up
    "Next": b"\x1b[6~",    # Page Down
    "Insert": b"\x1b[2~",
    "Delete": b"\x1b[3~",
    "F1": b"\x1bOP", "F2": b"\x1bOQ", "F3": b"\x1bOR", "F4": b"\x1bOS",
    "F5": b"\x1b[15~", "F6": b"\x1b[17~", "F7": b"\x1b[18~", "F8": b"\x1b[19~",
    "F9": b"\x1b[20~", "F10": b"\x1b[21~",
}


# ---------------------------------------------------------------------------
# The CRT terminal window
# ---------------------------------------------------------------------------

class CRTTerminal(tk.Tk):
    def __init__(self, cols=DEFAULT_COLS, rows=DEFAULT_ROWS):
        super().__init__()
        self.cols, self.rows = cols, rows
        self.theme_name = "green"
        self.theme = THEMES[self.theme_name]
        self.cursor_on = True
        self._fullscreen = False

        self.title("pyterm — CRT-9000")
        self.configure(bg=BEZEL)

        # Monospace font and its cell geometry.
        self.font = tkfont.Font(family=FONT_FAMILY, size=FONT_SIZE)
        self.cell_w = self.font.measure("M")
        self.cell_h = self.font.metrics("linespace")

        self._build_widgets()

        # Terminal emulation backend.
        self.screen = SafeScreen(self.cols, self.rows)
        self.stream = pyte.ByteStream(self.screen)

        # Spawn the shell.
        self.pty = Pty(self.cols, self.rows)

        # Background reader thread -> thread-safe queue -> Tk main loop.
        self.read_q = queue.Queue()
        self._stop = threading.Event()
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()

        self._bind_events()

        # Start the loops.
        self.after(10, self._pump)
        self.after(BLINK_INTERVAL_MS, self._blink_cycle)

        self.canvas.focus_set()
        self._redraw()

    # -- widget construction -------------------------------------------------

    def _build_widgets(self):
        # Outer bezel gives the "monitor shell" feel.
        outer = tk.Frame(self, bg=BEZEL, bd=0,
                         highlightthickness=3, highlightbackground=BEZEL_EDGE)
        outer.pack(fill="both", expand=True, padx=18, pady=(18, 6))

        # One canvas for everything: glyphs, cursor, and scanlines on top.
        px = self.cols * self.cell_w + 2 * PAD
        py = self.rows * self.cell_h + 2 * PAD
        self.canvas = tk.Canvas(
            outer, bg=self.theme["bg"], bd=0, highlightthickness=0,
            width=px, height=py, cursor="arrow", takefocus=1,
        )
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)

        # A little retro status strip under the glass.
        strip = tk.Frame(self, bg=BEZEL)
        strip.pack(fill="x", padx=18, pady=(0, 14))
        tk.Label(strip, text="● PWR", fg="#ff5a5a", bg=BEZEL,
                 font=("Menlo", 9)).pack(side="left")
        self.status = tk.Label(strip, text="GREEN PHOSPHOR", fg="#6b6155",
                               bg=BEZEL, font=("Menlo", 9))
        self.status.pack(side="right")

    # -- event wiring --------------------------------------------------------

    def _bind_events(self):
        self.canvas.bind("<Key>", self._on_key)
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set())
        self.bind("<F11>", self._toggle_fullscreen)
        self.canvas.bind("<Configure>", self._on_configure)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_key(self, event):
        if event.keysym == "F12":
            self._cycle_theme()
            return "break"
        if event.keysym == "F11":
            return "break"

        # Control combos -> control bytes (Ctrl-C=0x03, Ctrl-D=0x04, ...).
        # macOS Tkinter often leaves event.char empty for these, so build the
        # byte ourselves from the keysym. state bit 0x4 is the Control mask.
        if (event.state & 0x4) and event.keysym not in ("Control_L", "Control_R"):
            ks = event.keysym
            if len(ks) == 1 and ks.isalpha():
                self.pty.write(bytes([ord(ks.lower()) - ord("a") + 1]))
                return "break"
            ctrl_extra = {
                "bracketleft": 0x1b, "backslash": 0x1c, "bracketright": 0x1d,
                "space": 0x00, "at": 0x00, "underscore": 0x1f,
            }
            if ks in ctrl_extra:
                self.pty.write(bytes([ctrl_extra[ks]]))
                return "break"

        data = SPECIAL_KEYS.get(event.keysym)
        if data is None:
            if event.char:
                data = event.char.encode("utf-8")
            else:
                return "break"
        self.pty.write(data)
        return "break"

    def _on_configure(self, event):
        # Recompute grid size from the canvas area and resize the pty.
        cols = max(20, (event.width - 2 * PAD) // self.cell_w)
        rows = max(5, (event.height - 2 * PAD) // self.cell_h)
        if (cols, rows) == (self.cols, self.rows):
            return
        self.cols, self.rows = cols, rows
        self.screen.resize(rows, cols)
        self.pty.set_size(cols, rows)
        self._redraw()

    def _toggle_fullscreen(self, _=None):
        self._fullscreen = not self._fullscreen
        self.attributes("-fullscreen", self._fullscreen)
        return "break"

    def _cycle_theme(self):
        i = THEME_ORDER.index(self.theme_name)
        self.theme_name = THEME_ORDER[(i + 1) % len(THEME_ORDER)]
        self.theme = THEMES[self.theme_name]
        self.canvas.config(bg=self.theme["bg"])
        self.status.config(text=f"{self.theme_name.upper()} PHOSPHOR")
        self._redraw()

    # -- shell I/O -----------------------------------------------------------

    def _reader_loop(self):
        fd = self.pty.fd
        while not self._stop.is_set():
            try:
                r, _, _ = select.select([fd], [], [], 0.1)
            except (OSError, ValueError):
                break
            if fd in r:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                self.read_q.put(data)
        self.read_q.put(None)  # EOF sentinel

    def _pump(self):
        """Drain shell output on the Tk thread and repaint if anything changed."""
        try:
            dirty = False
            while True:
                try:
                    data = self.read_q.get_nowait()
                except queue.Empty:
                    break
                if data is None:
                    self._on_close()
                    return
                try:
                    self.stream.feed(data)
                except Exception:
                    # Unsupported/garbled sequence: reset the parser and keep
                    # going rather than freezing the display.
                    self.stream = pyte.ByteStream(self.screen)
                dirty = True
            if dirty:
                self._redraw()
        finally:
            if not self._stop.is_set():
                self.after(10, self._pump)

    # -- rendering -----------------------------------------------------------

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        t = self.theme
        buf = self.screen.buffer

        # Glyphs, drawn as runs of same-attribute cells for speed.
        for y in range(self.rows):
            row = buf[y]
            x = 0
            while x < self.cols:
                base = row[x]
                rev = bool(base.reverse)
                bold = bool(base.bold)
                chars = []
                j = x
                while (j < self.cols
                       and bool(row[j].reverse) == rev
                       and bool(row[j].bold) == bold):
                    chars.append(row[j].data or " ")
                    j += 1
                text = "".join(chars)
                gx = PAD + x * self.cell_w
                gy = PAD + y * self.cell_h
                if rev:
                    c.create_rectangle(
                        gx, gy, gx + len(text) * self.cell_w, gy + self.cell_h,
                        fill=t["fg"], outline=t["fg"], tags="content")
                    c.create_text(gx, gy, text=text, anchor="nw",
                                  font=self.font, fill=t["bg"],
                                  tags=("content", "rev"))
                else:
                    color = t["bright"] if bold else t["fg"]
                    c.create_text(gx, gy, text=text, anchor="nw",
                                  font=self.font, fill=color,
                                  tags=("content", "glyph"))
                x = j

        self._draw_cursor()
        self._draw_scanlines()

    def _draw_cursor(self):
        cur = self.screen.cursor
        if not (self.cursor_on and not cur.hidden):
            return
        if not (0 <= cur.y < self.rows and 0 <= cur.x < self.cols):
            return
        t = self.theme
        gx = PAD + cur.x * self.cell_w
        gy = PAD + cur.y * self.cell_h
        self.canvas.create_rectangle(
            gx, gy, gx + self.cell_w, gy + self.cell_h,
            fill=t["fg"], outline=t["fg"], tags="content")
        ch = self.screen.buffer[cur.y][cur.x].data or " "
        self.canvas.create_text(gx, gy, text=ch, anchor="nw",
                                 font=self.font, fill=t["bg"], tags="content")

    def _draw_scanlines(self):
        h = self.canvas.winfo_height()
        w = self.canvas.winfo_width()
        if h <= 1:
            h = self.rows * self.cell_h + 2 * PAD
            w = self.cols * self.cell_w + 2 * PAD
        for y in range(0, h, 3):
            self.canvas.create_line(0, y, w, y, fill=SCANLINE,
                                    stipple="gray50", tags="scan")

    def _blink_cycle(self):
        """Every BLINK_INTERVAL_MS the cursor blinks exactly once."""
        if self._stop.is_set():
            return
        self.cursor_on = False
        self._redraw()
        self.after(BLINK_OFF_MS, self._blink_restore)

    def _blink_restore(self):
        """End the single blink, return to solid, and arm the next timer."""
        if self._stop.is_set():
            return
        self.cursor_on = True
        self._redraw()
        self.after(BLINK_INTERVAL_MS, self._blink_cycle)

    # -- shutdown ------------------------------------------------------------

    def _on_close(self):
        self._stop.set()
        try:
            self.pty.close()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


def main():
    app = CRTTerminal()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app._on_close()


if __name__ == "__main__":
    main()
