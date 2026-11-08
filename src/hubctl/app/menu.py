"""Screens, items and key routing. No I/O, no clock, no terminal."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..constants import MAX_CHANNELS, POLL_CHOICES_S, POLL_LIMITS_S
from ..hal.base import ChannelReading, LinkState, Snapshot
from . import policy

# Screens. Every page shares one frame; the menu opens over the control page.
CONTROL = "control"
PORT = "port"
MENU = "menu"
POLICY = "policy"
CURRENT = "current"
AUTOHELP = "autohelp"
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
TOGGLE_PAUSE = "toggle-pause"
SET_POLICY = "set-policy"
SET_POLICY_VALUE = "set-policy-value"

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
PORT_LABEL = "USB PORT"
AUTO_MARKER = "A"
AUTO_NOTE = "rules are saved for the next run"
AUTO_TITLE = "HUBCTL  AUTO"
POLICY_ROWS = policy.POLICY_FIELDS
CURRENT_ROWS = policy.CURRENT_FIELDS

# Fields with a typed value, and the unit the editor shows beside it.
EDIT_UNITS = {"cycle": "min", "over": "A", "under": "A", "retry": "s",
              "recovery": "min", "poll": "s"}
EDIT_DECIMALS = ("over", "under", "poll")
EDIT_LIMITS = {
    "cycle": policy.CYCLE_LIMITS,
    "over": policy.OVERCURRENT_LIMITS,
    "under": policy.UNDERCURRENT_LIMITS,
    "retry": policy.RETRY_LIMITS,
    "recovery": policy.RECOVERY_LIMITS,
    "from": (0, policy.HOURS - 1),
    "to": (0, policy.HOURS - 1),
    "poll": POLL_LIMITS_S,
}
EDIT_CHARS = "0123456789."
EDIT_MAX_LEN = 4

DEVICE_FIELD_LABELS = ("ports", "product", "firmware", "hardware", "address",
                       "buttons", "restore")

GUARDED_KEYS = ("enter", "space", "d", "m", "p")

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
    auto_index: int = 0
    policy_index: int = 0
    current_index: int = 0
    port: int = 0
    edit: str | None = None


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
    watt_text: str
    watt_live: bool


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
    if state.screen in (PORT, DEVICE, SETTINGS, HELP, POLICY, CURRENT):
        return [Item(LABEL_BACK, BACK)]
    return []


def index(snapshot: Snapshot, state: State) -> int:
    """The selected row of the current screen, clamped to its list."""
    if state.screen == MENU:
        return max(0, min(state.menu_index, len(items(state)) - 1))
    if state.screen == SETTINGS:
        return max(0, min(state.settings_index, len(SETTINGS_ROWS) - 1))
    if state.screen == POLICY:
        return max(0, min(state.policy_index, len(POLICY_ROWS)))
    if state.screen == CURRENT:
        return max(0, min(state.current_index, len(CURRENT_ROWS)))
    if state.screen in (PORT, DEVICE, HELP):
        return 0
    count = port_count(snapshot)
    return 0 if count == 0 else max(0, min(state.port_index, count - 1))


def handle_key(snapshot: Snapshot, state: State,
               key: str) -> tuple[State, Action | None]:
    """Return the new state and the action the key asks the app to run."""
    if key == "ctrl-c":
        return state, Action(QUIT)
    if state.edit is not None:
        return _edit_key(state, key)
    if key in BACK_KEYS:
        return _back(state)
    if key == "?" and state.screen in (POLICY, CURRENT):
        return replace(state, screen=AUTOHELP), None
    if state.screen == AUTOHELP and key in ("enter", "space", "?"):
        return _back(state)
    if key == "r":
        return state, Action(REFRESH)
    if key in NEXT_KEYS:
        return _move(snapshot, state, 1), None
    if key in PREVIOUS_KEYS:
        return _move(snapshot, state, -1), None
    if key == "enter":
        if state.screen == POLICY:
            return _policy_enter(state)
        if state.screen == CURRENT:
            return _current_enter(state)
        if state.screen == SETTINGS:
            return _settings_enter(snapshot, state)
        return _enter(snapshot, state)
    if key == "m":
        return _menu(state)
    if key == "a" and state.screen == CONTROL:
        count = port_count(snapshot)
        if count == 0:
            return state, None
        return replace(state, screen=POLICY, port=index(snapshot, state) + 1,
                       policy_index=0), None
    if key == "p" and state.screen in (CONTROL, POLICY, CURRENT):
        return state, Action(TOGGLE_PAUSE)
    if state.screen == SETTINGS and key in ("left", "right"):
        return _change(snapshot, state, 1 if key == "right" else -1)
    if state.screen in (POLICY, CURRENT) and key in ("left", "right"):
        return _step(state, 1 if key == "right" else -1)
    if key == "space":
        if state.screen == CONTROL:
            return _write(snapshot, state, TOGGLE_POWER)
        if state.screen == SETTINGS:
            return _change(snapshot, state, 1)
        if state.screen in (POLICY, CURRENT):
            return _space(state)
        return _enter(snapshot, state)
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
        watt_text=_watt_text(reading, unknown),
        watt_live=(not unknown and reading.voltage_mv is not None
                   and reading.current_ma is not None),
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
    if state.screen in (CURRENT, AUTOHELP):
        return replace(state, screen=POLICY), None
    return replace(state, screen=CONTROL, menu_index=0, port=0), None


def _menu(state: State) -> tuple[State, Action | None]:
    """m opens the menu on control and closes or backs out of it elsewhere."""
    screen = MENU if state.screen == CONTROL else CONTROL
    return replace(state, screen=screen, menu_index=0, port=0), None


def _enter(snapshot: Snapshot,
           state: State) -> tuple[State, Action | None]:
    """Enter runs the selected menu item and backs out of every other page.

    Enter never writes and does nothing on the control page.
    """
    if state.screen == CONTROL:
        count = port_count(snapshot)
        if count == 0:
            return state, None
        return replace(state, screen=PORT,
                       port=index(snapshot, state) + 1), None
    if state.screen != MENU:
        # Settings, Device, Help and port detail select a setting, not the
        # Back item, so Enter always leaves the page.
        return _back(state)
    item = items(state)[index(snapshot, state)]
    if item.action == OPEN_DEVICE:
        return replace(state, screen=DEVICE), None
    if item.action == OPEN_SETTINGS:
        return replace(state, screen=SETTINGS, settings_index=0), None
    if item.action == OPEN_HELP:
        return replace(state, screen=HELP), None
    return _back(state)


def _write(snapshot: Snapshot, state: State,
           kind: str) -> tuple[State, Action | None]:
    """Space and d write on the control page only, for the selected port."""
    if state.screen != CONTROL or port_count(snapshot) == 0:
        return state, None
    return state, Action(kind, index(snapshot, state) + 1)


def _move(snapshot: Snapshot, state: State, delta: int) -> State:
    """j and k wrap every list; Device and Help have one row."""
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
    if state.screen == POLICY:
        count = len(POLICY_ROWS) + 1
        return replace(state,
                       policy_index=(index(snapshot, state) + delta) % count)
    if state.screen == CURRENT:
        count = len(CURRENT_ROWS) + 1
        return replace(state,
                       current_index=(index(snapshot, state) + delta) % count)
    return state


def _rows(state: State) -> tuple[str, ...]:
    if state.screen == CURRENT:
        return CURRENT_ROWS
    if state.screen == SETTINGS:
        return SETTINGS_ROWS
    return POLICY_ROWS


def _position(state: State) -> int:
    if state.screen == CURRENT:
        return min(state.current_index, len(CURRENT_ROWS))
    if state.screen == SETTINGS:
        return min(state.settings_index, len(SETTINGS_ROWS) - 1)
    return min(state.policy_index, len(POLICY_ROWS))


def _policy_enter(state: State) -> tuple[State, Action | None]:
    """Enter opens the current sub-page, edits a value, or backs out."""
    position = _position(state)
    if position == len(POLICY_ROWS):
        return _back(state)
    if POLICY_ROWS[position] == "current":
        return replace(state, screen=CURRENT, current_index=0), None
    return _edit_start(state)


def _settings_enter(snapshot: Snapshot,
                    state: State) -> tuple[State, Action | None]:
    """Enter edits the poll interval and steps the port choice."""
    if SETTINGS_ROWS[_position(state)] == "poll":
        return _edit_start(state)
    return _change(snapshot, state, 1)


def _current_enter(state: State) -> tuple[State, Action | None]:
    if _position(state) == len(CURRENT_ROWS):
        return _back(state)
    return _edit_start(state)


def _space(state: State) -> tuple[State, Action | None]:
    """Space steps the selected value, or leaves when Back is selected."""
    if _position(state) == len(_rows(state)):
        return _back(state)
    return _step(state, 1)


def _edit_start(state: State) -> tuple[State, Action | None]:
    """Enter opens the editor on a numeric row and toggles a boolean row."""
    field = _rows(state)[_position(state)]
    if field in ("enabled", "schedule", "over_action", "under_action"):
        return _step(state, 1)
    return replace(state, edit=""), None


def _edit_key(state: State, key: str) -> tuple[State, Action | None]:
    """Digits type, Enter commits, Esc cancels, other keys are ignored."""
    field = _rows(state)[_position(state)]
    if key == "enter":
        if state.edit == "":
            return replace(state, edit=None), None
        if not edit_valid(field, state.edit):
            return state, None
        if state.screen == SETTINGS:
            return (replace(state, edit=None),
                    Action(SET_POLL, value=round(float(state.edit), 1)))
        return (replace(state, edit=None),
                Action(SET_POLICY_VALUE, port=state.port,
                       value=(field, state.edit)))
    if key == "escape":
        return replace(state, edit=None), None
    if key == "backspace":
        return replace(state, edit=state.edit[:-1]), None
    if len(key) == 1 and key in EDIT_CHARS:
        if len(state.edit) >= EDIT_MAX_LEN:
            return state, None
        if key == "." and (field not in EDIT_DECIMALS or "." in state.edit):
            return state, None
        if not _edit_accepts(field, state.edit, key):
            return state, None
        return replace(state, edit=state.edit + key), None
    return state, None


def _edit_value(field: str, text: str):
    try:
        return float(text)
    except ValueError:
        return None


def edit_valid(field: str, text: str) -> bool:
    """The buffer holds a number the field accepts at commit time."""
    value = _edit_value(field, text)
    if value is None:
        return False
    low, high = EDIT_LIMITS[field]
    return low <= value <= high


def _edit_accepts(field: str, text: str, char: str) -> bool:
    """A keystroke is kept only while the number stays under the maximum."""
    value = _edit_value(field, text + char)
    return value is not None and value <= EDIT_LIMITS[field][1]


def edit_text(field: str, text: str) -> str:
    """The value cell while the row is being typed into."""
    body = text or "_"
    unit = EDIT_UNITS.get(field)
    return f"{body} {unit}" if unit else body


def _step(state: State, delta: int) -> tuple[State, Action | None]:
    """Left and right step the selected policy value."""
    position = _position(state)
    if position >= len(_rows(state)) or state.port < 1:
        return state, None
    field = _rows(state)[position]
    return state, Action(SET_POLICY, port=state.port, value=(field, delta))


def auto_summary(rule: policy.Policy) -> list[tuple[str, str]]:
    """The Auto list summary as (text, token) pieces, menu.md section 3.5."""
    if not rule.enabled:
        return [("off", DIM)]
    pieces = [("on", OK)]
    rest = ""
    if rule.cycle_s is not None:
        rest += f" cyc{rule.cycle_s // 60}"
    if rule.overcurrent_ma is not None:
        rest += f" oc{rule.overcurrent_ma / 1000:.1f}"
        if rule.retry_s is not None:
            rest += f"/{rule.retry_s}"
    if rule.recovery_s is not None:
        rest += f" rec{rule.recovery_s // 60}"
    if rule.schedule is not None:
        start, end = rule.schedule
        rest += f" sch{start // 60}-{end // 60}"
    if rest:
        pieces.append((rest, TEXT))
    return pieces


def policy_row(rule: policy.Policy,
               field: str) -> tuple[str, str, str]:
    """One policy page row: label, value text and its token."""
    if field == "enabled":
        return ("enabled", *_on_off(rule.enabled))
    if field == "cycle":
        return ("cycle", *_minutes(rule.cycle_s))
    if field == "current":
        return ("current", *_current_summary(rule))
    if field == "over":
        if rule.overcurrent_ma is None:
            return ("over", "off", DIM)
        return ("over", f"{rule.overcurrent_ma / 1000:.1f} A", TEXT)
    if field == "over_action":
        token = DIM if rule.overcurrent_ma is None else TEXT
        return ("over action", rule.over_action, token)
    if field == "under":
        if rule.under_ma is None:
            return ("under", "off", DIM)
        return ("under", f"{rule.under_ma / 1000:.2f} A", TEXT)
    if field == "under_action":
        token = DIM if rule.under_ma is None else TEXT
        return ("under action", rule.under_action, token)
    if field == "retry":
        if rule.retry_s is None:
            return ("retry", "off", DIM)
        return ("retry", f"{rule.retry_s} s", TEXT)
    if field == "recovery":
        return ("recovery", *_minutes(rule.recovery_s))
    if field == "schedule":
        return ("schedule", *_on_off(rule.schedule is not None))
    window = rule.schedule
    if window is None:
        return (field, "--", DIM)
    minutes = window[0] if field == "from" else window[1]
    return (field, f"{minutes // 60:02d}", TEXT)


def _current_summary(rule: policy.Policy) -> tuple[str, str]:
    parts = []
    if rule.overcurrent_ma is not None:
        parts.append(f"{rule.overcurrent_ma / 1000:.1f} A {rule.over_action}")
    if rule.under_ma is not None:
        parts.append(f"{rule.under_ma / 1000:.2f} A {rule.under_action}")
    if not parts:
        return "off", DIM
    return " / ".join(parts), TEXT


def _on_off(value: bool) -> tuple[str, str]:
    return ("on", OK) if value else ("off", DIM)


def _minutes(seconds: int | None) -> tuple[str, str]:
    if seconds is None:
        return ("off", DIM)
    return (f"{seconds // 60} min", TEXT)


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


def _watt_text(reading: ChannelReading, unknown: bool) -> str:
    if unknown or reading.voltage_mv is None or reading.current_ma is None:
        return "?"
    return f"{reading.voltage_mv * reading.current_ma / 1_000_000:.2f} W"
