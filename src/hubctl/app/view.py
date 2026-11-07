"""Pure ANSI rendering. No I/O, no clock, no device."""

from __future__ import annotations

import re

from .. import __version__
from ..constants import (
    BAR_LEFT_COL,
    BAR_RIGHT_FROM_END,
    BANNER_ROW,
    CURRENT_COL,
    CURRENT_WIDTH,
    DATA_COL,
    DATA_WIDTH,
    DEVICE_BACK_ROW,
    DEVICE_VALUE_COL,
    LABEL_COL,
    LABEL_WIDTH,
    LAST_LABEL_COL,
    LAST_ROW_FROM_END,
    LAST_TEXT_COL,
    LIST_ROW,
    MENU_ITEM_ROW,
    PID,
    POWER_COL,
    POWER_WIDTH,
    RAIL_LEFT_COL,
    RAIL_RIGHT_FROM_END,
    STATUS_COL,
    STATUS_ROW,
    VID,
    VOLTAGE_COL,
    VOLTAGE_WIDTH,
)
from ..hal.base import LinkState, Mode, Snapshot
from . import menu

ESC = "\x1b["
RESET = f"{ESC}0m"
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

C_OK = 78
C_WARN = 220
C_ERR = 203
C_DIM = 244
C_RAIL = 240

TOKENS = {
    menu.TEXT: ("", None),
    menu.DIM: ("2", C_DIM),
    menu.OK: ("", C_OK),
    menu.WARN: ("", C_WARN),
    menu.ERR: ("", C_ERR),
    menu.RAIL: ("", C_RAIL),
}

PORT_CELLS = (
    (LABEL_COL, LABEL_WIDTH),
    (POWER_COL, POWER_WIDTH),
    (DATA_COL, DATA_WIDTH),
    (VOLTAGE_COL, VOLTAGE_WIDTH),
    (CURRENT_COL, CURRENT_WIDTH),
)

TITLE_CONTROL = "HUBCTL  USB CONTROL"
TITLE_DEVICE = "HUBCTL  DEVICE"
TITLE_SETTINGS = "HUBCTL  SETTINGS"
TITLE_HELP = "HUBCTL  HELP"
HELP_TITLE = f"hubctl {__version__}"
HELP_SUBTITLE = "SmartUSBHub Pro 4CH terminal control"
HELP_KEYS = (
    ("j/k", "select port"),
    ("SPACE", "power on/off"),
    ("d", "data on/off"),
    ("m", "menu, r refresh"),
    ("ENTER", "open, q quit"),
)
HELP_KEY_WIDTH = 8
LAST_LABEL = "last"
INTERLOCK_BANNER = "! interlock - switching disabled. Hold CH1 3 s, then r."
NO_DEVICE_WARN = "no SmartUSBHub CMD port"
NO_DEVICE_HINT = "connect the CMD USB-C port, or pass --port /dev/ttyACM0."

FOOTER_CONTROL = "SPACE power   d data   m menu   q quit"
FOOTER_CONTROL_LOST = "SPACE power   d data   r retry   m menu   q quit"
FOOTER_NO_DEVICE = "r retry   m menu   q quit"
FOOTER_MENU = "ENTER open   m close   q close"
FOOTER_DEVICE = "ENTER back   q back"
FOOTER_SETTINGS = "LEFT/RIGHT change   ENTER back   q back"


class Style:
    """Colour obeys NO_COLOR; bold, faint and reverse never do."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text, token=None, bold=False, rev=False):
        attribute, colour = TOKENS.get(token, ("", None))
        codes = []
        if attribute:
            codes.append(attribute)
        if bold:
            codes.append("1")
        if rev:
            codes.append("7")
        if colour is not None and self.enabled:
            codes.append(f"38;5;{colour}")
        if not codes:
            return text
        return f"{ESC}{';'.join(codes)}m{text}{RESET}"


def _plain(text, *_args, **_kwargs):
    return text


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
        if ESC in text:
            text += RESET
        visible = width
    return text + " " * (width - visible)


def _inner(width):
    return width - BAR_LEFT_COL - BAR_RIGHT_FROM_END + 1


def _indent(column):
    return " " * (column - BAR_LEFT_COL)


def _body(content, width, style, glyph):
    return (" " * (RAIL_LEFT_COL - 1) + style(glyph, menu.RAIL)
            + pad(content, _inner(width))
            + style(glyph, menu.RAIL) + " " * RAIL_RIGHT_FROM_END)


def _header(title, badge, token, width, style, glyph):
    badge_text = clip(f" {badge} ", max(1, _inner(width) - 1))
    room = _inner(width) - vlen(badge_text) - 1
    title = clip(title, max(0, room))
    fill = " " * max(0, room - vlen(title))
    content = (style(title + fill, bold=True, rev=True)
               + style(badge_text, token, bold=True)
               + style(" ", bold=True, rev=True))
    return (" " * (RAIL_LEFT_COL - 1) + style(glyph, menu.RAIL) + content
            + style(glyph, menu.RAIL) + " " * RAIL_RIGHT_FROM_END)


def _footer(text, width, style, glyph):
    bar = pad(text, _inner(width))
    return _body(style(bar, bold=True, rev=True), width, style, glyph)


def _row(cells, style):
    """Lay cells out at their fixed columns, filling the gaps with spaces."""
    out = []
    column = LABEL_COL
    for (target, width), (text, token, bold) in zip(PORT_CELLS, cells):
        out.append(" " * (target - column))
        out.append(style(pad(text, width), token, bold=bold))
        column = target + width
    return "".join(out)


def _port_row(snapshot, number, selected, style):
    values = menu.readout(snapshot, number)
    if snapshot.link == LinkState.STALE:
        tokens = (menu.DIM,) * 4
    else:
        tokens = (
            menu.OK if values.power_on else menu.DIM,
            menu.OK if values.data_on else menu.DIM,
            menu.TEXT if values.voltage_live else menu.DIM,
            menu.TEXT if values.current_live else menu.DIM,
        )
    cells = (
        (menu.port_label(number), menu.TEXT, True),
        (values.power_text, tokens[0], False),
        (values.data_text, tokens[1], False),
        (values.voltage_text, tokens[2], False),
        (values.current_text, tokens[3], False),
    )
    if selected:
        return (_indent(LABEL_COL)
                + style(_row(cells, _plain), bold=True, rev=True))
    return _indent(LABEL_COL) + _row(cells, style)


def _item_row(item, selected, style):
    if selected:
        return (_indent(LABEL_COL)
                + style(item.label + " ", bold=True, rev=True))
    return (_indent(LABEL_COL)
            + style(pad(item.label, LABEL_WIDTH), menu.TEXT, bold=True))


def _field_row(label, value, known, style):
    token = menu.TEXT if known else menu.DIM
    return (_indent(LABEL_COL)
            + style(pad(label, DEVICE_VALUE_COL - LABEL_COL), menu.TEXT,
                    bold=True)
            + style(value, token))


def _link(snapshot):
    if snapshot.link == LinkState.LIVE:
        return "live", menu.OK
    if snapshot.link == LinkState.STALE:
        return f"stale {snapshot.last_cycle_age_s:.1f} s", menu.WARN
    return "lost", menu.ERR


def _badge(snapshot):
    if snapshot.identity is None:
        return "no device", menu.WARN
    if snapshot.status.mode == Mode.INTERLOCK:
        return "interlock", menu.WARN
    if snapshot.link == LinkState.LOST:
        if snapshot.reconnect_in_s is None:
            return "lost", menu.ERR
        return f"lost - retry {snapshot.reconnect_in_s:.0f} s", menu.ERR
    return _link(snapshot)


def _retry(snapshot):
    if snapshot.reconnect_in_s is None:
        return "?"
    return f"{snapshot.reconnect_in_s:.0f} s"


def _mode(snapshot):
    if snapshot.status.mode == Mode.INTERLOCK:
        return "interlock", menu.WARN
    if snapshot.status.mode == Mode.UNKNOWN:
        return "unknown", menu.WARN
    return "normal", menu.TEXT


def _port(snapshot):
    return "?" if snapshot.identity is None else snapshot.identity.port


def _main_status(snapshot, style):
    mode, mode_token = _mode(snapshot)
    link, link_token = _link(snapshot)
    return (_indent(STATUS_COL) + style("port ", menu.DIM)
            + style(_port(snapshot), menu.TEXT)
            + "   " + style(mode, mode_token)
            + "   " + style(link, link_token)
            + "   " + style(f"poll {snapshot.poll_interval_s:.1f} s", menu.DIM))


def _discovery_status(snapshot, style):
    return (_indent(STATUS_COL) + style("discovery ", menu.DIM)
            + style(f"{VID}:{PID}", menu.TEXT)
            + "   " + style("no port", menu.WARN)
            + "   " + style(f"retry {_retry(snapshot)}", menu.DIM))


def _status_row(snapshot, style):
    if snapshot.identity is None:
        return _discovery_status(snapshot, style)
    return _main_status(snapshot, style)


def _device_status(snapshot, style):
    link, link_token = _link(snapshot)
    return (_indent(STATUS_COL) + style("port ", menu.DIM)
            + style(_port(snapshot), menu.TEXT)
            + "   " + style(f"{VID}:{PID}", menu.TEXT)
            + "   " + style(link, link_token))


def _last_row(snapshot, style):
    token = (snapshot.last_kind
             if snapshot.last_kind in (menu.OK, menu.WARN, menu.ERR)
             else menu.TEXT)
    return (_indent(LAST_LABEL_COL)
            + pad(style(LAST_LABEL, menu.DIM), LAST_TEXT_COL - LAST_LABEL_COL)
            + style(snapshot.last_action, token))


def _banner_row(snapshot, style):
    if snapshot.status.mode != Mode.INTERLOCK:
        return None
    return _indent(LABEL_COL) + style(INTERLOCK_BANNER, menu.WARN)


def _control_rows(snapshot, state, style):
    rows = {STATUS_ROW: _status_row(snapshot, style)}
    if snapshot.identity is None:
        rows[LIST_ROW] = _indent(LABEL_COL) + style(NO_DEVICE_WARN, menu.WARN)
        rows[LIST_ROW + 1] = (_indent(LABEL_COL)
                              + style(NO_DEVICE_HINT, menu.DIM))
        return rows
    banner = _banner_row(snapshot, style)
    if banner is not None:
        rows[BANNER_ROW] = banner
    selected = menu.index(snapshot, state)
    for offset in range(menu.port_count(snapshot)):
        rows[LIST_ROW + offset] = _port_row(snapshot, offset + 1,
                                            offset == selected, style)
    return rows


def _menu_rows(snapshot, state, style):
    rows = {STATUS_ROW: _status_row(snapshot, style)}
    banner = _banner_row(snapshot, style)
    if banner is not None:
        rows[BANNER_ROW] = banner
    rows[LIST_ROW] = _indent(LABEL_COL) + style(menu.MENU_HEADING, menu.DIM)
    selected = menu.index(snapshot, state)
    for offset, item in enumerate(menu.items(state)):
        rows[MENU_ITEM_ROW + offset] = _item_row(item, offset == selected,
                                                 style)
    return rows


def _device_rows(snapshot, state, style):
    rows = {STATUS_ROW: _device_status(snapshot, style)}
    for offset, (label, value, known) in enumerate(
            menu.device_fields(snapshot)):
        rows[LIST_ROW + offset] = _field_row(label, value, known, style)
    entries = menu.items(state)
    rows[DEVICE_BACK_ROW] = _item_row(entries[0], True, style)
    return rows


def _help_rows(snapshot, state, style):
    rows = {STATUS_ROW: _device_status(snapshot, style)}
    rows[LIST_ROW] = (_indent(LABEL_COL)
                      + style(HELP_TITLE, menu.TEXT, bold=True))
    rows[LIST_ROW + 1] = (_indent(LABEL_COL)
                          + style(HELP_SUBTITLE, menu.DIM))
    for offset, (key, text) in enumerate(HELP_KEYS):
        rows[LIST_ROW + 3 + offset] = (
            _indent(LABEL_COL)
            + style(pad(key, HELP_KEY_WIDTH), menu.TEXT, bold=True)
            + style(text, menu.DIM))
    rows[DEVICE_BACK_ROW] = _item_row(menu.items(state)[0], True, style)
    return rows


def _detail_row(label, value, token, style):
    return (_indent(LABEL_COL)
            + style(pad(label, DEVICE_VALUE_COL - LABEL_COL), menu.TEXT,
                    bold=True)
            + style(value, token))


def _port_detail_rows(snapshot, state, style, usb):
    values = menu.readout(snapshot, state.port)
    power_token = menu.OK if values.power_on else menu.DIM
    data_token = menu.OK if values.data_on else menu.DIM
    voltage_token = menu.TEXT if values.voltage_live else menu.DIM
    current_token = menu.TEXT if values.current_live else menu.DIM
    rows = {STATUS_ROW: _device_status(snapshot, style)}
    fields = (
        ("power", values.power_text, power_token),
        ("data", values.data_word, data_token),
        ("voltage", values.voltage_text, voltage_token),
        ("current", values.current_text, current_token),
    )
    for offset, (label, value, token) in enumerate(fields):
        rows[LIST_ROW + offset] = _detail_row(label, value, token, style)
    if usb is not None:
        rows[LIST_ROW + 4] = _detail_row("usb", f"{usb.vid}:{usb.pid}",
                                         menu.TEXT, style)
        rows[LIST_ROW + 5] = _detail_row("product", usb.product or "?",
                                         menu.TEXT, style)
    else:
        reason = "data off" if values.data_word != "on" else "no device"
        rows[LIST_ROW + 4] = _detail_row("usb", reason, menu.DIM, style)
    rows[DEVICE_BACK_ROW] = _item_row(menu.items(state)[0], True, style)
    return rows


def _settings_rows(snapshot, state, style):
    rows = {STATUS_ROW: _device_status(snapshot, style)}
    selected = menu.index(snapshot, state)
    for offset, (label, value) in enumerate(menu.settings_rows(snapshot)):
        text = (style(pad(label, DEVICE_VALUE_COL - LABEL_COL), menu.TEXT,
                      bold=True)
                + style(value, menu.TEXT))
        if offset == selected:
            text = style(pad(label, DEVICE_VALUE_COL - LABEL_COL) + value,
                         bold=True, rev=True)
        rows[LIST_ROW + offset] = _indent(LABEL_COL) + text
    rows[DEVICE_BACK_ROW] = _item_row(menu.items(state)[0], True, style)
    return rows


def _screen_rows(snapshot, state, style, usb=None):
    if state.screen == menu.MENU:
        return _menu_rows(snapshot, state, style)
    if state.screen == menu.DEVICE:
        return _device_rows(snapshot, state, style)
    if state.screen == menu.HELP:
        return _help_rows(snapshot, state, style)
    if state.screen == menu.PORT:
        return _port_detail_rows(snapshot, state, style, usb)
    if state.screen == menu.SETTINGS:
        return _settings_rows(snapshot, state, style)
    return _control_rows(snapshot, state, style)


def _heading(snapshot, state):
    if state.screen == menu.DEVICE:
        return TITLE_DEVICE
    if state.screen == menu.SETTINGS:
        return TITLE_SETTINGS
    if state.screen == menu.HELP:
        return TITLE_HELP
    if state.screen == menu.PORT:
        values = menu.readout(snapshot, state.port)
        title = f"HUBCTL  {menu.port_label(state.port)} - {values.power_text}"
        if values.power_on is True:
            title += f" - data {values.data_word}"
        return title
    return TITLE_CONTROL


def _footer_text(snapshot, state):
    if state.screen == menu.SETTINGS:
        return FOOTER_SETTINGS
    if state.screen in (menu.PORT, menu.DEVICE, menu.HELP):
        return FOOTER_DEVICE
    if state.screen == menu.MENU:
        return FOOTER_MENU
    if snapshot.identity is None:
        return FOOTER_NO_DEVICE
    if snapshot.link == LinkState.LOST:
        return FOOTER_CONTROL_LOST
    return FOOTER_CONTROL


def render(snapshot: Snapshot, state: menu.State, width: int, height: int,
           color: bool = True, utf8: bool = True, usb=None):
    """Return exactly ``height`` lines of exactly ``width`` visible columns."""
    style = Style(color)
    glyph = "\u2502" if utf8 else "|"
    if height <= 0:
        return []
    badge, token = _badge(snapshot)
    lines = [_header(_heading(snapshot, state), badge, token,
                     width, style, glyph)]
    if height >= 2:
        rows = _screen_rows(snapshot, state, style, usb)
        if snapshot.identity is not None:
            rows[height - LAST_ROW_FROM_END] = _last_row(snapshot, style)
        body = [rows.get(row, "") for row in range(2, height)]
        lines.extend(_body(content, width, style, glyph) for content in body)
        lines.append(_footer(_footer_text(snapshot, state), width, style,
                             glyph))
    return lines
