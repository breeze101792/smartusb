"""The interactive loop. Tick, draw, key, repeat."""

from __future__ import annotations

import signal
import time

from ..constants import KEY_REPEAT_GUARD_S, MIN_HEIGHT, MIN_WIDTH, TICK_MS
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


def _loop(controller: Controller, terminal: Terminal, color: bool, utf8: bool) -> int:
    selected = 0
    dirty = True
    last_draw = 0.0
    last_size = None
    last_toggle = 0.0

    while True:
        now = time.monotonic()
        if controller.tick(now):
            dirty = True
        snapshot = controller.snapshot()
        count = snapshot.identity.channels if snapshot.identity else 4
        selected = max(0, min(selected, count - 1))

        width, height = terminal.size()
        if (width, height) != last_size:
            last_size = (width, height)
            terminal.clear()
            dirty = True

        if dirty or now - last_draw >= 0.5:
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                terminal.draw([
                    f"terminal too small - need {MIN_WIDTH}x{MIN_HEIGHT}"])
            else:
                terminal.draw(render(snapshot, selected, width, height, color, utf8))
            last_draw = now
            dirty = False

        key = terminal.read_key(TICK_MS / 1000.0)
        if key is None:
            continue
        if key in ("q", "ctrl-c"):
            return 0
        if key in ("j", "down"):
            selected = (selected + 1) % count
            dirty = True
        elif key in ("k", "up"):
            selected = (selected - 1) % count
            dirty = True
        elif key == "space":
            if now - last_toggle >= KEY_REPEAT_GUARD_S:
                controller.toggle_power(selected + 1)
                last_toggle = now
                dirty = True
        elif key == "d":
            if now - last_toggle >= KEY_REPEAT_GUARD_S:
                controller.toggle_data(selected + 1)
                last_toggle = now
                dirty = True
        elif key == "r":
            controller.request_refresh()
            dirty = True
