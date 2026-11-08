"""The interactive loop. Tick, draw, key, repeat."""

from __future__ import annotations

import signal
import time

from ..constants import (
    KEY_REPEAT_GUARD_S,
    MIN_HEIGHT,
    MIN_WIDTH,
    REDRAW_INTERVAL_S,
    TICK_MS,
    USB_REFRESH_S,
)
from ..hal import usbmap
from . import menu, policy
from .controller import Controller
from .term import Terminal
from .view import render


def _terminate(_signum, _frame):
    raise SystemExit(130)


def run(controller: Controller, color: bool = True, utf8: bool = True) -> int:
    handlers = {}
    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None:
            handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _terminate)

    try:
        with Terminal() as terminal:
            return _loop(controller, terminal, color, utf8)
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)


def _execute(controller: Controller, action: menu.Action) -> None:
    if action.kind == menu.REFRESH:
        controller.request_refresh()
    elif action.kind == menu.TOGGLE_POWER:
        controller.toggle_power(action.port)
    elif action.kind == menu.TOGGLE_DATA:
        controller.toggle_data(action.port)
    elif action.kind == menu.SET_PORT:
        controller.set_port(action.value)
    elif action.kind == menu.SET_POLL:
        controller.set_poll(action.value)
    elif action.kind == menu.TOGGLE_PAUSE:
        controller.set_auto_paused(not controller.auto().paused)
    elif action.kind == menu.SET_POLICY:
        field, delta = action.value
        rule = controller.auto().policies.get(action.port, policy.Policy())
        controller.set_policy(action.port, policy.step(rule, field, delta))
    elif action.kind == menu.SET_POLICY_VALUE:
        field, text = action.value
        rule = controller.auto().policies.get(action.port, policy.Policy())
        typed = policy.set_value(rule, field, text)
        if typed is not None:
            controller.set_policy(action.port, typed)


def _loop(controller: Controller, terminal: Terminal, color: bool,
          utf8: bool, clock=time.monotonic) -> int:
    state = menu.State()
    dirty = True
    last_draw = 0.0
    last_size = None
    last_event = {key: None for key in menu.GUARDED_KEYS}
    usb_port = None
    usb_value = None
    usb_at = 0.0

    while True:
        now = clock()
        if controller.tick(now):
            dirty = True
        snapshot = controller.snapshot()

        width, height = terminal.size()
        if (width, height) != last_size:
            last_size = (width, height)
            terminal.clear()
            dirty = True

        if dirty or now - last_draw >= REDRAW_INTERVAL_S:
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                terminal.draw([
                    f"terminal too small - need {MIN_WIDTH}x{MIN_HEIGHT}"])
            else:
                usb = None
                if (state.screen == menu.PORT
                        and menu.readout(snapshot, state.port).data_word == "on"):
                    if usb_port != state.port or now - usb_at >= USB_REFRESH_S:
                        usb_port, usb_at = state.port, now
                        usb_value = usbmap.port_device(state.port)
                    usb = usb_value
                terminal.draw(render(snapshot, state, width, height,
                                     color, utf8, usb, controller.auto()))
            last_draw = now
            dirty = False

        key = terminal.read_key(TICK_MS / 1000.0)
        if key is None:
            continue
        now = clock()
        if key in menu.GUARDED_KEYS:
            previous = last_event[key]
            last_event[key] = now
            if previous is not None and now - previous < KEY_REPEAT_GUARD_S:
                continue
        previous = state
        state, action = menu.handle_key(snapshot, state, key)
        if action is not None and action.kind == menu.QUIT:
            return 0
        if action is not None:
            _execute(controller, action)
        if state != previous or action is not None:
            dirty = True
