"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .app import store
from .app.controller import Controller
from .app.term import color_supported, utf8_supported
from .app.tui import run
from .constants import POLL_MAX_S, POLL_MIN_S


def _trace_writer(path):
    handle = open(path, "a", encoding="ascii", buffering=1)

    def trace(direction, data):
        handle.write(f"{time.monotonic():.6f} {direction} {data.hex(' ')}\n")

    return handle, trace


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="hubctl",
        description="Terminal control app for the SmartUSBHub Pro 4CH")
    parser.add_argument("--port", help="CMD serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--poll-interval", type=float, default=None,
                        metavar="S",
                        help="full poll period in seconds (default 1.0, or the "
                             "saved value)")
    parser.add_argument("--state", metavar="FILE",
                        help="state file (default: $XDG_STATE_HOME/hubctl/"
                             "state.json)")
    parser.add_argument("--trace", metavar="FILE",
                        help="append raw TX/RX hex to FILE")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument("--ascii", action="store_true", help="use ASCII borders")
    args = parser.parse_args(argv)

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("hubctl needs a terminal; run it from an interactive shell",
              file=sys.stderr)
        return 2
    if args.poll_interval is not None and not (
            POLL_MIN_S <= args.poll_interval <= POLL_MAX_S):
        parser.error("--poll-interval must be between 0.2 and 10.0")
    state_path = Path(args.state) if args.state else store.default_path()

    handle = None
    trace = None
    if args.trace:
        handle, trace = _trace_writer(args.trace)
    controller = Controller(poll_interval=args.poll_interval, port=args.port,
                            trace=trace, state_path=state_path)
    try:
        return run(controller,
                   color=not args.no_color and color_supported(),
                   utf8=not args.ascii and utf8_supported())
    except KeyboardInterrupt:
        return 130
    finally:
        controller.close()
        if handle is not None:
            handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
