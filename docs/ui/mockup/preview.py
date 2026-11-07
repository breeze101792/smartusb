#!/usr/bin/env python3
"""ANSI design preview for the hubctl dashboard.

Reference material, not the application. It draws the four dashboard states
with the ANSI sequences the real renderer will use, so the layout can be
reviewed in a real terminal instead of a browser.

    python3 docs/ui/mockup/preview.py
    python3 docs/ui/mockup/preview.py --dump live --no-color

Interactive keys: 1-4 switch the demo state, j/k or Up/Down select a channel,
space toggles VBUS, d toggles D+/D-, r returns to LIVE, q quits.
"""

import argparse
import os
import re
import select
import signal
import sys
import termios
import tty
from dataclasses import dataclass

# --- ANSI -------------------------------------------------------------------
ESC = "\x1b["
RESET = f"{ESC}0m"
ALT_ON = f"{ESC}?1049h"
ALT_OFF = f"{ESC}?1049l"
CURSOR_OFF = f"{ESC}?25l"
CURSOR_ON = f"{ESC}?25h"
HOME = f"{ESC}H"
CLEAR = f"{ESC}2J"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

TEXT = 252
DIM = 244
ACCENT = 81
OK = 78
WARN = 220
ERR = 203
BORDER = 240

USE_COLOR = True

# --- Layout -----------------------------------------------------------------
MIN_WIDTH = 60
MIN_HEIGHT = 16
SMALL_HEIGHT = 20          # below this, drop the device block
TICK_S = 0.1

COL_CH = 5
COL_POWER = 8
COL_DATA = 7
COL_VBUS = 12
COL_CURRENT = 9

STATES = ("live", "interlock", "stale", "lost")


def paint(text, color=None, bold=False, dim=False, rev=False):
    if not USE_COLOR:
        return text
    codes = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    if rev:
        codes.append("7")
    if color is not None:
        codes.append(f"38;5;{color}")
    if not codes:
        return text
    return f"{ESC}{';'.join(codes)}m{text}{RESET}"


def vlen(text):
    return len(ansi_strip(text))


def ansi_strip(text):
    return ANSI_RE.sub("", text)


def clip(text, width):
    """Truncate to visible width, keeping ANSI sequences."""
    out = []
    visible = 0
    index = 0
    while index < len(text) and visible < width:
        match = ANSI_RE.match(text, index)
        if match:
            out.append(match.group(0))
            index = match.end()
            continue
        out.append(text[index])
        visible += 1
        index += 1
    return "".join(out)


def pad(text, width):
    visible = vlen(text)
    if visible > width:
        text = clip(text, width)
        visible = width
    return text + " " * (width - visible)


def cell(content, width):
    return pad(content, width)


def color_enabled():
    return not os.environ.get("NO_COLOR") and os.environ.get("TERM", "") != "dumb"


def utf8_locale():
    for name in ("LC_ALL", "LC_CTYPE", "LANG"):
        value = os.environ.get(name)
        if value:
            upper = value.upper()
            return "UTF-8" in upper or "UTF8" in upper
    return False


@dataclass
class Channel:
    power: bool | None
    data: bool | None
    mv: int | None
    ma: int | None


@dataclass(frozen=True)
class Glyphs:
    tl: str
    tr: str
    bl: str
    br: str
    h: str
    v: str
    lt: str
    rt: str


UTF8 = Glyphs("\u250c", "\u2510", "\u2514", "\u2518", "\u2500", "\u2502", "\u251c", "\u2524")
ASCII = Glyphs("+", "+", "+", "+", "-", "|", "+", "+")


def base_channels():
    return [
        Channel(False, None, 202, 0),
        Channel(False, None, 198, 0),
        Channel(False, None, 205, 0),
        Channel(True, True, 4614, 0),
    ]


LAST = {
    "live": ("poll ok - 4 channels", "ok"),
    "interlock": ("mode is interlock - switching disabled", "warn"),
    "stale": ("no reply to 0x00 (poll 3) - retrying", "warn"),
    "lost": ("device stopped replying - state unknown, nothing applied", "err"),
}


def demo_channels(state):
    channels = base_channels()
    if state == "lost":
        for channel in channels:
            channel.power = None
            channel.data = None
            channel.mv = None
            channel.ma = None
    return channels


def power_text(channel):
    if channel.power is None:
        return "?"
    return "ON" if channel.power else "off"


def data_text(channel):
    if channel.power is None:
        return "?"
    if channel.power is False:
        return "-"
    if channel.data is None:
        return "?"
    return "on" if channel.data else "off"


def volt_text(channel):
    if channel.mv is None:
        return "?"
    if channel.power is False:
        return f"({channel.mv} mV)"
    return f"{channel.mv / 1000:.2f} V"


def current_text(channel):
    if channel.ma is None:
        return "?"
    return f"{channel.ma / 1000:.2f} A"


def row(channel, number, state, selected, inner):
    marker = "> " if selected else "  "
    plain = (marker
             + cell(f"CH{number}", COL_CH)
             + cell(power_text(channel), COL_POWER)
             + cell(data_text(channel), COL_DATA)
             + cell(volt_text(channel), COL_VBUS)
             + cell(current_text(channel), COL_CURRENT))
    if selected:
        return paint(pad(" " + plain, inner), rev=True)
    if state in ("stale", "lost"):
        return paint(pad(" " + plain, inner), dim=True)
    # Cell colours, still padded to the same columns.
    if channel.power is True:
        power = cell(paint("ON", OK, bold=True), COL_POWER)
    elif channel.power is False:
        power = cell(paint("off", DIM), COL_POWER)
    else:
        power = cell(paint("?", DIM), COL_POWER)
    data = cell(paint(data_text(channel), DIM if data_text(channel) in ("-", "?") else None),
                COL_DATA)
    if channel.power is False and channel.mv is not None:
        volt = cell(paint(f"({channel.mv} mV)", DIM), COL_VBUS)
    else:
        volt = cell(volt_text(channel), COL_VBUS)
    current = cell(current_text(channel), COL_CURRENT)
    return " " + marker + cell(f"CH{number}", COL_CH) + power + data + volt + current


def top_border(width, glyphs):
    inner = width - 2
    left = paint(" hubctl ", ACCENT, bold=True)
    right = paint(" SmartUSBHub Pro 4CH ", TEXT)
    fill = max(1, inner - 2 - vlen(left) - vlen(right))
    return (paint(glyphs.tl + glyphs.h, BORDER) + left
            + paint(glyphs.h * fill, BORDER) + right
            + paint(glyphs.h + glyphs.tr, BORDER))


def bottom_border(width, glyphs):
    return paint(glyphs.bl + glyphs.h * (width - 2) + glyphs.br, BORDER)


def divider(width, glyphs):
    inner = width - 2
    return paint(glyphs.lt + glyphs.h * inner + glyphs.rt, BORDER)


def body(content, inner, glyphs):
    return paint(glyphs.v, BORDER) + pad(content, inner) + paint(glyphs.v, BORDER)


def footer(state, inner):
    if state == "lost":
        left = paint(" q", TEXT, bold=True) + paint(" quit   ", DIM)
        left += paint("r", TEXT, bold=True) + paint(" retry now", DIM)
    else:
        disabled = state in ("interlock", "stale")
        parts = [
            ("j/k", "select", True),
            ("space", "-" if disabled else "power", not disabled),
            ("d", "-" if disabled else "data", not disabled),
            ("r", "refresh", True),
            ("q", "quit", True),
        ]
        left = " "
        for key, label, enabled in parts:
            left += paint(key, TEXT, bold=True) if enabled else paint(key, DIM)
            left += paint(" " + label + "   ", DIM)
        left = left.rstrip()
    hint = paint("1-4 demo", DIM)
    if inner - vlen(left) - vlen(hint) - 1 < 1:
        return left
    gap = max(1, inner - vlen(left) - vlen(hint) - 1)
    return left + " " * gap + hint + " "


def frame(state, channels, selected, last, width, height, glyphs):
    inner = width - 2
    lines = []

    left = paint("hubctl", ACCENT, bold=True) + " - SmartUSBHub Pro 4CH"
    right = paint("FW V2.0  HW V1.3 ", DIM)
    gap = max(0, inner - 1 - vlen(left) - vlen(right))
    lines.append(body(" " + left + " " * gap + right, inner, glyphs))

    mode = paint("interlock", WARN) if state == "interlock" else "normal"
    link_state = "stale" if state == "stale" else "lost" if state == "lost" else "live"
    link = {"live": paint("live", OK),
            "stale": paint("stale 3.4 s", WARN),
            "lost": paint("lost - reconnect 2 in 3 s", ERR)}[link_state]
    line = " " + paint("/dev/ttyACM0  1a86:fe0c  ", DIM) + mode + "  " + link
    line += paint("  poll 1.0 s", DIM)
    lines.append(body(line, inner, glyphs))
    lines.append(divider(width, glyphs))

    if state == "interlock":
        lines.append(body(" " + paint(
            "! interlock - switching disabled. Hold CH1 3 s, then r.", WARN), inner, glyphs))
        lines.append(divider(width, glyphs))

    header = ("   " + cell("CH", COL_CH) + cell("POWER", COL_POWER)
              + cell("DATA", COL_DATA) + cell("VBUS", COL_VBUS) + "CURRENT")
    lines.append(body(paint(header, DIM), inner, glyphs))

    for index, channel in enumerate(channels):
        lines.append(body(row(channel, index + 1, state, index == selected, inner),
                          inner, glyphs))
    lines.append(divider(width, glyphs))

    if height >= SMALL_HEIGHT:
        line = " " + paint("device    ", DIM) + "HBP_USB2_4CH  4 channels  addr 0x0000"
        lines.append(body(line, inner, glyphs))
        line = " " + paint("settings  ", DIM) + "buttons enabled  restore disabled"
        lines.append(body(line, inner, glyphs))

    text, kind = last
    colour = {"ok": OK, "warn": WARN, "err": ERR}.get(kind)
    line = " " + paint("last      ", DIM) + paint(text, colour)
    lines.append(body(line, inner, glyphs))

    slots = max(1, height - 2)
    if len(lines) > slots - 1:
        lines = lines[:slots - 1]
    while len(lines) < slots - 1:
        lines.append(body("", inner, glyphs))
    lines.append(body(footer(state, inner), inner, glyphs))
    return [top_border(width, glyphs)] + lines + [bottom_border(width, glyphs)]


# --- Terminal ---------------------------------------------------------------
class Screen:
    def __init__(self):
        self.fd = sys.stdin.fileno()
        self.saved = None

    def __enter__(self):
        self.saved = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        os.write(sys.stdout.fileno(),
                 (ALT_ON + CURSOR_OFF + CLEAR + HOME).encode())
        return self

    def __exit__(self, *_exc):
        os.write(sys.stdout.fileno(), (RESET + CURSOR_ON + ALT_OFF).encode())
        if self.saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)


def terminal_size():
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
        return size.columns, size.lines
    except OSError:
        return 80, 24


def draw(lines):
    out = [HOME]
    for number, line in enumerate(lines, 1):
        out.append(f"{ESC}{number};1H{line}{ESC}K")
    out.append(RESET)
    os.write(sys.stdout.fileno(), "".join(out).encode())


def read_key(timeout):
    if not select.select([sys.stdin.fileno()], [], [], timeout)[0]:
        return None
    raw = os.read(sys.stdin.fileno(), 1)
    if raw == b"\x1b":
        seq = b""
        while select.select([sys.stdin.fileno()], [], [], 0.01)[0]:
            seq += os.read(sys.stdin.fileno(), 1)
            if len(seq) >= 2:
                break
        return {b"[A": "up", b"[B": "down"}.get(seq)
    char = raw.decode("latin1")
    return {" ": "space", "\x03": "ctrl-c", "\r": "enter", "\n": "enter"}.get(char, char)


def _terminate(_signum, _frame):
    raise SystemExit(130)


def interactive(start_state):
    global USE_COLOR
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("preview needs a terminal; use --dump <state> instead", file=sys.stderr)
        return 2
    USE_COLOR = color_enabled()
    glyphs = UTF8 if utf8_locale() else ASCII
    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGHUP, _terminate)

    state = start_state
    selected = 2
    channels = demo_channels(state)
    last = LAST[state]
    last_size = None
    dirty = True

    with Screen():
        while True:
            size = terminal_size()
            if size != last_size:
                last_size = size
                dirty = True
            if dirty:
                width, height = size
                if width < MIN_WIDTH or height < MIN_HEIGHT:
                    draw([paint(f"terminal too small - need {MIN_WIDTH}x{MIN_HEIGHT}", ERR)])
                else:
                    draw(frame(state, channels, selected, last, width, height, glyphs))
                dirty = False

            key = read_key(TICK_S)
            if key is None:
                continue
            if key in ("q", "ctrl-c"):
                break
            if key in ("j", "down"):
                selected = (selected + 1) % len(channels)
                dirty = True
            elif key in ("k", "up"):
                selected = (selected - 1) % len(channels)
                dirty = True
            elif key in "1234" and len(key) == 1:
                state = STATES[int(key) - 1]
                channels = demo_channels(state)
                last = LAST[state]
                dirty = True
            elif key == " " and state == "live":
                channel = channels[selected]
                channel.power = not channel.power
                channel.data = True if channel.power else None
                channel.mv = 4614 if channel.power else 205
                channel.ma = 0
                last = (f"CH{selected + 1} power "
                        f"{'on' if channel.power else 'off'} - echo ok, "
                        f"0x00 {'on' if channel.power else 'off'}, "
                        f"0x08 {'on' if channel.power else 'off'}", "ok")
                dirty = True
            elif key == "d" and state == "live" and channels[selected].power:
                channel = channels[selected]
                channel.data = not channel.data
                last = (f"CH{selected + 1} data "
                        f"{'on' if channel.data else 'off'} - echo ok, 0x08 "
                        f"{'on' if channel.data else 'off'}", "ok")
                dirty = True
            elif key == "r":
                state = "live"
                channels = demo_channels(state)
                last = ("poll ok - 4 channels", "ok")
                dirty = True
    return 0


def dump(state, color, ascii_only, width, height):
    global USE_COLOR
    USE_COLOR = color and color_enabled()
    glyphs = ASCII if (ascii_only or not utf8_locale()) else UTF8
    last = LAST[state]
    lines = frame(state, demo_channels(state), 2, last, width, height, glyphs)
    sys.stdout.write("\n".join(lines) + (RESET if USE_COLOR else "") + "\n")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="ANSI dashboard design preview")
    parser.add_argument("--dump", choices=STATES, help="print one state and exit")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument("--ascii", action="store_true", help="use ASCII borders")
    parser.add_argument("--width", type=int, default=80)
    parser.add_argument("--height", type=int, default=24)
    args = parser.parse_args(argv)

    if args.dump:
        return dump(args.dump, not args.no_color, args.ascii, args.width, args.height)
    return interactive("live")


if __name__ == "__main__":
    sys.exit(main())
