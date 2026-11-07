"""Pure ANSI rendering. No I/O, no clock, no device."""

from __future__ import annotations

import re

from ..constants import SMALL_HEIGHT
from ..hal.base import ChannelReading, LinkState, Mode, Snapshot

ESC = "\x1b["
RESET = f"{ESC}0m"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

TEXT = 252
DIM = 244
ACCENT = 81
OK = 78
WARN = 220
ERR = 203
BORDER = 240

COL_CH = 5
COL_POWER = 8
COL_DATA = 7
COL_VBUS = 12
COL_CURRENT = 9

UTF8 = {"tl": "\u250c", "tr": "\u2510", "bl": "\u2514", "br": "\u2518",
        "h": "\u2500", "v": "\u2502", "lt": "\u251c", "rt": "\u2524"}
ASCII = {"tl": "+", "tr": "+", "bl": "+", "br": "+",
         "h": "-", "v": "|", "lt": "+", "rt": "+"}


class Style:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text, color=None, bold=False, dim=False, rev=False):
        if not self.enabled:
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
    return len(ANSI_RE.sub("", text))


def clip(text, width):
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


def _top(width, title, style, glyphs):
    inner = width - 2
    left = style(" hubctl ", ACCENT, bold=True)
    right = style(f" {title} ", TEXT)
    fill = max(1, inner - 2 - vlen(left) - vlen(right))
    return (style(glyphs["tl"] + glyphs["h"], BORDER) + left
            + style(glyphs["h"] * fill, BORDER) + right
            + style(glyphs["h"] + glyphs["tr"], BORDER))


def _bottom(width, style, glyphs):
    return style(glyphs["bl"] + glyphs["h"] * (width - 2) + glyphs["br"], BORDER)


def _divider(width, style, glyphs):
    return style(glyphs["lt"] + glyphs["h"] * (width - 2) + glyphs["rt"], BORDER)


def _body(content, width, style, glyphs):
    return style(glyphs["v"], BORDER) + pad(content, width - 2) + style(glyphs["v"], BORDER)


def _assemble(body_lines, footer, width, height, title, style, glyphs):
    inner = width - 2
    slots = max(1, height - 2)
    if len(body_lines) > slots - 1:
        body_lines = body_lines[:slots - 1]
    while len(body_lines) < slots - 1:
        body_lines.append(_body("", width, style, glyphs))
    body_lines.append(_body(footer, width, style, glyphs))
    return ([_top(width, title, style, glyphs)] + body_lines
            + [_bottom(width, style, glyphs)])


def _power_text(reading, unknown):
    if unknown or reading.power is None:
        return "?"
    return "ON" if reading.power else "off"


def _data_text(reading, unknown):
    if unknown or reading.power is None:
        return "?"
    if reading.power is False:
        return "-"
    if reading.data is None:
        return "?"
    return "on" if reading.data else "off"


def _voltage_text(reading, unknown):
    if unknown or reading.voltage_mv is None:
        return "?"
    if reading.power is not True:
        return f"({reading.voltage_mv} mV)"
    return f"{reading.voltage_mv / 1000:.2f} V"


def _current_text(reading, unknown):
    if unknown or reading.current_ma is None:
        return "?"
    return f"{reading.current_ma / 1000:.2f} A"


def _row(number, reading, selected, stale, unknown, width, style):
    marker = "> " if selected else "  "
    power = _power_text(reading, unknown)
    data = _data_text(reading, unknown)
    volts = _voltage_text(reading, unknown)
    current = _current_text(reading, unknown)
    plain = (marker
             + cell(f"CH{number}", COL_CH)
             + cell(power, COL_POWER)
             + cell(data, COL_DATA)
             + cell(volts, COL_VBUS)
             + cell(current, COL_CURRENT))
    if selected:
        return style(pad(" " + plain, width - 2), rev=True)
    if stale or unknown:
        return style(pad(" " + plain, width - 2), dim=True)
    power_cell = cell(
        style("ON", OK, bold=True) if reading.power is True
        else style("off", DIM), COL_POWER)
    data_cell = cell(style(data, DIM if data in ("-", "?") else None), COL_DATA)
    volt_cell = cell(style(volts, DIM if reading.power is not True else None), COL_VBUS)
    return (" " + marker + cell(f"CH{number}", COL_CH)
            + power_cell + data_cell + volt_cell + cell(current, COL_CURRENT))


def _link_text(snapshot, style):
    if snapshot.link == LinkState.LIVE:
        return style("live", OK)
    if snapshot.link == LinkState.STALE:
        return style(f"stale {snapshot.last_cycle_age_s:.1f} s", WARN)
    if snapshot.reconnect_in_s is not None:
        return style(f"lost - reconnect in {snapshot.reconnect_in_s:.0f} s", ERR)
    return style("lost", ERR)


def _mode_text(snapshot, style):
    if snapshot.status.mode == Mode.INTERLOCK:
        return style("interlock", WARN)
    if snapshot.status.mode == Mode.UNKNOWN:
        return style("unknown", WARN)
    return "normal"


def _footer(snapshot, style):
    if snapshot.link == LinkState.LOST:
        return (style(" q", TEXT, bold=True) + style(" quit   ", DIM)
                + style("r", TEXT, bold=True) + style(" retry now", DIM))
    live = (snapshot.link == LinkState.LIVE
            and snapshot.status.mode == Mode.NORMAL)
    parts = [
        ("j/k", "select", True),
        ("space", "power", live),
        ("d", "data", live),
        ("r", "refresh", True),
        ("q", "quit", True),
    ]
    line = " "
    for key, label, enabled in parts:
        shown = label if enabled else "-"
        line += style(key, TEXT, bold=True) if enabled else style(key, DIM)
        line += style(f" {shown}   ", DIM)
    return line.rstrip()


def _no_device(snapshot, width, height, style, glyphs):
    lines = [
        _body("", width, style, glyphs),
        _body(" " + style("no SmartUSBHub CMD port", WARN, bold=True),
              width, style, glyphs),
        _body("", width, style, glyphs),
        _body(" " + (snapshot.last_error or snapshot.last_action),
              width, style, glyphs),
        _body("", width, style, glyphs),
        _body(" connect the CMD USB-C port with a data cable,", width, style, glyphs),
        _body(" or pass --port /dev/ttyACM0.", width, style, glyphs),
    ]
    return _assemble(lines, _footer(snapshot, style), width, height,
                     "no device", style, glyphs)


def render(snapshot: Snapshot, selected: int, width: int, height: int,
           color: bool = True, utf8: bool = True):
    """Return exactly ``height`` lines of at most ``width`` visible columns."""
    style = Style(color)
    glyphs = UTF8 if utf8 else ASCII
    if snapshot.identity is None:
        return _no_device(snapshot, width, height, style, glyphs)

    identity = snapshot.identity
    count = max(1, identity.channels)
    selected = max(0, min(selected, count - 1))
    inner = width - 2
    stale = snapshot.link == LinkState.STALE
    unknown = snapshot.link == LinkState.LOST

    lines = []
    left = style("hubctl", ACCENT, bold=True) + " - " + identity.product
    right = style(f"FW {identity.firmware}  HW {identity.hardware} ", DIM)
    gap = max(1, inner - 1 - vlen(left) - vlen(right))
    lines.append(_body(" " + left + " " * gap + right, width, style, glyphs))

    line = (" " + style(f"{identity.port}  1a86:fe0c  ", DIM)
            + _mode_text(snapshot, style) + "  " + _link_text(snapshot, style)
            + style(f"  poll {snapshot.poll_interval_s:.1f} s", DIM))
    lines.append(_body(line, width, style, glyphs))
    lines.append(_divider(width, style, glyphs))

    if snapshot.status.mode == Mode.INTERLOCK:
        lines.append(_body(" " + style(
            "! interlock - switching disabled. Hold CH1 3 s, then r.",
            WARN), width, style, glyphs))
        lines.append(_divider(width, style, glyphs))

    header = ("   " + cell("CH", COL_CH) + cell("POWER", COL_POWER)
              + cell("DATA", COL_DATA) + cell("VBUS", COL_VBUS) + "CURRENT")
    lines.append(_body(style(header, DIM), width, style, glyphs))

    for index in range(count):
        number = index + 1
        reading = snapshot.channels.get(number, ChannelReading())
        lines.append(_body(
            _row(number, reading, index == selected, stale, unknown, width, style),
            width, style, glyphs))
    lines.append(_divider(width, style, glyphs))

    if height >= SMALL_HEIGHT:
        buttons = ("?" if snapshot.status.buttons_enabled is None
                   else "enabled" if snapshot.status.buttons_enabled else "disabled")
        restore = ("?" if snapshot.status.restore_enabled is None
                   else "enabled" if snapshot.status.restore_enabled else "disabled")
        lines.append(_body(
            " " + style("device    ", DIM)
            + f"{identity.product}  {count} channels  addr 0x{identity.address:04X}",
            width, style, glyphs))
        lines.append(_body(
            " " + style("settings  ", DIM)
            + f"buttons {buttons}  restore {restore}",
            width, style, glyphs))

    kind_color = {"ok": OK, "warn": WARN, "err": ERR}.get(snapshot.last_kind)
    lines.append(_body(
        " " + style("last      ", DIM) + style(snapshot.last_action, kind_color),
        width, style, glyphs))

    return _assemble(lines, _footer(snapshot, style), width, height,
                     identity.product, style, glyphs)
