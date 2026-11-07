"""Raw terminal: alternate screen, size, key decoding, one-write frames."""

from __future__ import annotations

import locale
import os
import select
import sys
import termios
import tty

ESC = "\x1b["
RESET = f"{ESC}0m"
ALT_ON = f"{ESC}?1049h"
ALT_OFF = f"{ESC}?1049l"
CURSOR_OFF = f"{ESC}?25l"
CURSOR_ON = f"{ESC}?25h"
HOME = f"{ESC}H"
CLEAR = f"{ESC}2J"


def color_supported() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return os.environ.get("TERM", "") != "dumb"


def utf8_supported() -> bool:
    encoding = locale.getpreferredencoding(False) or ""
    return "utf" in encoding.lower()


class Terminal:
    def __init__(self):
        self.in_fd = sys.stdin.fileno()
        self.out_fd = sys.stdout.fileno()
        self._saved = None

    def __enter__(self):
        self._saved = termios.tcgetattr(self.in_fd)
        try:
            tty.setraw(self.in_fd)
            os.write(self.out_fd, (ALT_ON + CURSOR_OFF + CLEAR + HOME).encode())
        except Exception:
            termios.tcsetattr(self.in_fd, termios.TCSADRAIN, self._saved)
            raise
        return self

    def __exit__(self, *_exc):
        try:
            os.write(self.out_fd, (RESET + CURSOR_ON + ALT_OFF).encode())
        finally:
            if self._saved is not None:
                termios.tcsetattr(self.in_fd, termios.TCSADRAIN, self._saved)

    def size(self):
        try:
            size = os.get_terminal_size(self.out_fd)
            return size.columns, size.lines
        except OSError:
            return 80, 24

    def clear(self):
        os.write(self.out_fd, (CLEAR + HOME).encode())

    def draw(self, lines):
        out = [HOME]
        for number, line in enumerate(lines, 1):
            out.append(f"{ESC}{number};1H{line}{ESC}K")
        out.append(RESET)
        os.write(self.out_fd, "".join(out).encode("utf-8"))

    def read_key(self, timeout_s: float):
        ready, _, _ = select.select([self.in_fd], [], [], timeout_s)
        if not ready:
            return None
        raw = os.read(self.in_fd, 1)
        if raw == b"\x1b":
            sequence = b""
            while select.select([self.in_fd], [], [], 0.01)[0]:
                sequence += os.read(self.in_fd, 1)
                if len(sequence) >= 2:
                    break
            keys = {b"[A": "up", b"[B": "down",
                    b"[C": "right", b"[D": "left"}
            if sequence in keys:
                return keys[sequence]
            return "escape" if sequence == b"" else "ignore"
        char = raw.decode("latin1")
        return {" ": "space", "\x03": "ctrl-c", "\r": "enter", "\n": "enter"}.get(char, char)
