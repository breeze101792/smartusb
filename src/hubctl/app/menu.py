"""Screens, items and key routing. No I/O, no clock, no terminal."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..constants import MAX_CHANNELS, POLL_CHOICES_S
from ..hal.base import ChannelReading, LinkState, Snapshot

# Screens. The control page is the only page; the menu opens over it.
CONTROL = "control"
PORT = "port"
MENU = "menu"
DEVICE = "device"
SETTINGS = "settings"
HELP = "help"

# Item actions.
OPEN_DEVICE = "open-device"
OPEN_SETTINGS = "open-settings"
OPEN_HELP = "open-help"
BACK = "back"
QUIT = "quit"
REFRESH = "refresh"
TOGGLE_POWER = "toggle-power"
TOGGLE_DATA = "toggle-data"
SET_PORT = "set-port"
SET_POLL = "set-poll"

# Style tokens, docs/ui/menu.md section 7.
TEXT = "text"
DIM = "dim"
OK = "ok"
WARN = "warn"
ERR = "err"
RAIL = "rail"

LABEL_DEVICE = "Device"
LABEL_SETTINGS = "Settings"
LABEL_HELP = "Help"
LABEL_BACK = "Back"
MENU_HEADING = "GLOBAL MENU"
PORT_LABEL = "USB PORT"

DEVICE_FIELD_LABELS = ("ports", "product", "firmware", "hardware", "address",
                       "buttons", "restore")

GUARDED_KEYS = ("enter", "space", "d", "m")

NEXT_KEYS = ("j", "down")
PREVIOUS_KEYS = ("k", "up")
BACK_KEYS = ("q", "escape")


@dataclass(frozen=True)
class State:
    """The screen and the selected row of the control list and the menu."""

    screen: str = CONTROL
    port_index: int = 0
    menu_index: int = 0
    settings_index: int = 0
    port: int = 0


@dataclass(frozen=True)
class Action:
    """What the app must do. Navigation is applied to the state instead."""

    kind: str
    port: int = 0
    value: object = None


@dataclass(frozen=True)
class Item:
    label: str
    action: str


@dataclass(frozen=True)
class Readout:
    """Display text plus the state the renderer colours by."""

    power_text: str
    power_on: bool | None
    data_text: str
    data_word: str
    data_on: bool | None
    voltage_text: str
    voltage_live: bool
    current_text: str
    current_live: bool


def port_label(number: int) -> str:
    """The display name of one port, used by the rows and by the tests."""
    return f"{PORT_LABEL} {number}"


def port_count(snapshot: Snapshot) -> int:
    """The number of port rows: the probed count, 1..7, or 0 with no device."""
    if snapshot.identity is None:
        return 0
    return max(1, min(snapshot.identity.channels, MAX_CHANNELS))


def items(state: State) -> list[Item]:
    """The selectable menu and device rows. The control list is the ports."""
    if state.screen == MENU:
        return [Item(LABEL_DEVICE, OPEN_DEVICE),
                Item(LABEL_SETTINGS, OPEN_SETTINGS),
                Item(LABEL_HELP, OPEN_HELP)]
    if state.screen in (PORT, DEVICE, SETTINGS, HELP):
        return [Item(LABEL_BACK, BACK)]
    return []


def index(snapshot: Snapshot, state: State) -> int:
    """The selected row of the current screen, clamped to its list."""
    if state.screen == MENU:
        return max(0, min(state.menu_index, len(items(state)) - 1))
    if state.screen == SETTINGS:
        return max(0, min(state.settings_index, len(SETTINGS_ROWS) - 1))
    if state.screen in (PORT, DEVICE, HELP):
        return 0
    count = port_count(snapshot)
    return 0 if count == 0 else max(0, min(state.port_index, count - 1))


def handle_key(snapshot: Snapshot, state: State,
               key: str) -> tuple[State, Action | None]:
    """Return the new state and the action the key asks the app to run."""
    if key == "ctrl-c":
        return state, Action(QUIT)
    if key in BACK_KEYS:
        return _back(state)
    if key == "r":
        return state, Action(REFRESH)
    if key in NEXT_KEYS:
        return _move(snapshot, state, 1), None
    if key in PREVIOUS_KEYS:
        return _move(snapshot, state, -1), None
    if key == "enter":
        return _enter(snapshot, state)
    if key == "m":
        return _menu(state)
    if state.screen == SETTINGS and key in ("left", "right"):
        return _change(snapshot, state, 1 if key == "right" else -1)
    if key == "space":
        return _write(snapshot, state, TOGGLE_POWER)
    if key == "d":
        return _write(snapshot, state, TOGGLE_DATA)
    return state, None


SETTINGS_ROWS = ("port", "poll")


def settings_rows(snapshot: Snapshot) -> list[tuple[str, str]]:
    """The labelled settings values, in display order."""
    return [
        ("port", snapshot.port_setting or "auto"),
        ("poll", f"{snapshot.poll_interval_s:.1f} s"),
    ]


def _change(snapshot: Snapshot, state: State,
            delta: int) -> tuple[State, Action | None]:
    """Left and right step the selected setting."""
    if index(snapshot, state) == 0:
        choices = [None, *snapshot.port_choices]
        current = (choices.index(snapshot.port_setting)
                   if snapshot.port_setting in choices else 0)
        target = choices[(current + delta) % len(choices)]
        return state, Action(SET_PORT, value=target)
    choices = list(POLL_CHOICES_S)
    current = min(range(len(choices)),
                  key=lambda i: abs(choices[i] - snapshot.poll_interval_s))
    target = choices[(current + delta) % len(choices)]
    return state, Action(SET_POLL, value=target)


def readout(snapshot: Snapshot, port: int) -> Readout:
    """One port's display text plus the state the renderer colours it by."""
    reading = snapshot.channels.get(port) or ChannelReading()
    unknown = snapshot.link == LinkState.LOST
    power_text = _power_text(reading, unknown)
    power_on = None if unknown else reading.power
    data_word = _data_word(reading, unknown)
    data_known = data_word == "on" or data_word == "off"
    return Readout(
        power_text=power_text,
        power_on=power_on,
        data_text=f"data {data_word}" if data_known else data_word,
        data_word=data_word,
        data_on=data_word == "on" if data_known else None,
        voltage_text=_voltage_text(reading, unknown),
        voltage_live=power_on is True and reading.voltage_mv is not None,
        current_text=_current_text(reading, unknown),
        current_live=not unknown and reading.current_ma is not None,
    )


def device_fields(snapshot: Snapshot) -> list[tuple[str, str, bool]]:
    """The labelled device fields, in display order, rows 5 to 11.

    The third value says whether the field was read; the renderer dims a
    field that was not.
    """
    identity = snapshot.identity
    if identity is None:
        return [(label, "?", False) for label in DEVICE_FIELD_LABELS]
    lost = snapshot.link == LinkState.LOST

    def text(value) -> tuple[str, bool]:
        if lost or value is None or value == "":
            return "?", False
        return str(value), True

    def flag(value: bool | None) -> tuple[str, bool]:
        if lost or value is None:
            return "?", False
        return ("enabled" if value else "disabled"), True

    status = snapshot.status
    return [
        ("ports", *text(port_count(snapshot))),
        ("product", *text(identity.product)),
        ("firmware", *text(identity.firmware)),
        ("hardware", *text(identity.hardware)),
        ("address", *text(f"0x{identity.address:04X}")),
        ("buttons", *flag(status.buttons_enabled)),
        ("restore", *flag(status.restore_enabled)),
    ]


def _back(state: State) -> tuple[State, Action | None]:
    """q and Esc quit on control and only ever go back elsewhere."""
    if state.screen == CONTROL:
        return state, Action(QUIT)
    return replace(state, screen=CONTROL, menu_index=0, port=0), None


def _menu(state: State) -> tuple[State, Action | None]:
    """m opens the menu on control and closes or backs out of it elsewhere."""
    screen = MENU if state.screen == CONTROL else CONTROL
    return replace(state, screen=screen, menu_index=0, port=0), None


def _enter(snapshot: Snapshot,
           state: State) -> tuple[State, Action | None]:
    """Enter runs the selected menu item and backs out of Device.

    Enter never writes and does nothing on the control page.
    """
    if state.screen == CONTROL:
        count = port_count(snapshot)
        if count == 0:
            return state, None
        return replace(state, screen=PORT,
                       port=index(snapshot, state) + 1), None
    item = items(state)[index(snapshot, state)]
    if item.action == OPEN_DEVICE:
        return replace(state, screen=DEVICE), None
    if item.action == OPEN_SETTINGS:
        return replace(state, screen=SETTINGS, settings_index=0), None
    if item.action == OPEN_HELP:
        return replace(state, screen=HELP), None
    if item.action == BACK:
        return replace(state, screen=CONTROL, port=0), None
    return state, None


def _write(snapshot: Snapshot, state: State,
           kind: str) -> tuple[State, Action | None]:
    """Space and d write on the control page only, for the selected port."""
    if state.screen != CONTROL or port_count(snapshot) == 0:
        return state, None
    return state, Action(kind, index(snapshot, state) + 1)


def _move(snapshot: Snapshot, state: State, delta: int) -> State:
    """j and k wrap the port list and the menu; Device and Help have one row."""
    if state.screen == CONTROL:
        count = port_count(snapshot)
        if count == 0:
            return state
        return replace(state, port_index=(index(snapshot, state) + delta) % count)
    if state.screen == MENU:
        count = len(items(state))
        return replace(state, menu_index=(index(snapshot, state) + delta) % count)
    if state.screen == SETTINGS:
        count = len(SETTINGS_ROWS)
        return replace(state,
                       settings_index=(index(snapshot, state) + delta) % count)
    return state


def _power_text(reading: ChannelReading, unknown: bool) -> str:
    if unknown or reading.power is None:
        return "?"
    return "ON" if reading.power else "off"


def _data_word(reading: ChannelReading, unknown: bool) -> str:
    if unknown or reading.power is None:
        return "?"
    if reading.power is False:
        return "-"
    if reading.data is None:
        return "?"
    return "on" if reading.data else "off"


def _voltage_text(reading: ChannelReading, unknown: bool) -> str:
    if unknown or reading.voltage_mv is None:
        return "?"
    if reading.power is not True:
        return f"({reading.voltage_mv} mV)"
    return f"{reading.voltage_mv / 1000:.2f} V"


def _current_text(reading: ChannelReading, unknown: bool) -> str:
    if unknown or reading.current_ma is None:
        return "?"
    return f"{reading.current_ma / 1000:.2f} A"
