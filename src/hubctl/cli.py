"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
import time

from .app.controller import Controller
from .app.term import color_supported, utf8_supported
from .app.tui import run
from .constants import POLL_INTERVAL_S, POLL_MAX_S, POLL_MIN_S


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
    parser.add_argument("--poll-interval", type=float, default=POLL_INTERVAL_S,
                        metavar="S", help="full poll period in seconds (default 1.0)")
    parser.add_argument("--trace", metavar="FILE",
                        help="append raw TX/RX hex to FILE")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument("--ascii", action="store_true", help="use ASCII borders")
    args = parser.parse_args(argv)

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("hubctl needs a terminal; run it from an interactive shell",
              file=sys.stderr)
        return 2
    if args.poll_interval < POLL_MIN_S or args.poll_interval > POLL_MAX_S:
        parser.error("--poll-interval must be between 0.2 and 10.0")

    handle = None
    trace = None
    if args.trace:
        handle, trace = _trace_writer(args.trace)
    controller = Controller(poll_interval=args.poll_interval, port=args.port,
                            trace=trace)
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
