"""Raw termios link, exclusive port ownership, and the command allow-list."""

from __future__ import annotations

import fcntl
import os
import select
import termios
import time

from ...constants import (
    ACK_TIMEOUT_S,
    BAUD,
    DRAIN_WINDOW_S,
    WRITE_TIMEOUT_S,
)
from ...hal.base import LinkError
from . import protocol


class CommandNotAllowed(Exception):
    """A frame was blocked before it reached the port."""


# The app may transmit only these commands. Everything else is a persistent
# setting, a reset, a reboot, or an SDK-only feature, and is blocked here.
ALLOWED_COMMANDS = frozenset({
    protocol.CMD_GET_POWER,
    protocol.CMD_SET_POWER,
    protocol.CMD_GET_VOLTAGE,
    protocol.CMD_GET_CURRENT,
    protocol.CMD_SET_DATA,
    protocol.CMD_GET_MODE,
    protocol.CMD_GET_DATA,
    protocol.CMD_GET_BUTTON,
    protocol.CMD_GET_DEFAULT_POWER,
    protocol.CMD_GET_DEFAULT_DATA,
    protocol.CMD_GET_RESTORE,
    protocol.CMD_GET_ADDRESS,
    protocol.CMD_GET_PRODUCT,
    protocol.CMD_GET_CHANNELS,
    protocol.CMD_GET_FIRMWARE,
    protocol.CMD_GET_HARDWARE,
})


class SerialLink:
    """One open CMD port. Not reentrant; one owner at a time."""

    def __init__(self, port: str, trace=None, baud: int = BAUD):
        self.port = port
        self.trace = trace
        self.fd = None
        self._original = None
        self.buf = bytearray()
        try:
            self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise LinkError(f"{port} is in use by another process") from exc
            self._original = termios.tcgetattr(self.fd)
            self._configure(baud)
        except LinkError:
            self._release()
            raise
        except OSError as exc:
            self._release()
            raise LinkError(f"cannot open {port}: {exc}") from exc
        except termios.error as exc:
            self._release()
            raise LinkError(f"{port} is not a usable serial port: {exc}") from exc

    def _configure(self, baud):
        iflag, oflag, cflag, lflag, _ispeed, _ospeed, original_cc = self._original
        cflag &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB)
        for name in ("CRTSCTS", "CCTS_OFLOW", "CRTS_IFLOW"):
            if hasattr(termios, name):
                cflag &= ~getattr(termios, name)
        cflag |= termios.CS8 | termios.CREAD | termios.CLOCAL
        cc = list(original_cc)
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        speed = getattr(termios, f"B{baud}")
        termios.tcsetattr(
            self.fd, termios.TCSANOW,
            [0, 0, cflag, 0, speed, speed, cc])
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def _release(self):
        if self.fd is None:
            return
        try:
            if self._original is not None:
                termios.tcsetattr(self.fd, termios.TCSANOW, self._original)
        except (OSError, termios.error):
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.fd = None

    def close(self):
        self._release()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def _log(self, direction, data):
        if self.trace is not None:
            try:
                self.trace(direction, bytes(data))
            except Exception:
                pass

    def _require_fd(self):
        if self.fd is None:
            raise LinkError("the link is closed")

    def _write_all(self, data):
        self._require_fd()
        view = memoryview(data)
        sent = 0
        deadline = time.monotonic() + WRITE_TIMEOUT_S
        while sent < len(view):
            try:
                count = os.write(self.fd, view[sent:])
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                    raise LinkError("write timed out")
                continue
            except OSError as exc:
                raise LinkError(f"write failed: {exc}") from exc
            if count <= 0:
                raise LinkError("write failed")
            sent += count

    def send(self, cmd, p0=0, p1=0):
        if cmd not in ALLOWED_COMMANDS:
            raise CommandNotAllowed(f"command 0x{cmd:02X} is not permitted")
        packet = protocol.encode_v1(cmd, p0, p1)
        self._log("TX", packet)
        self._write_all(packet)

    def drain(self):
        deadline = time.monotonic() + DRAIN_WINDOW_S
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.read_frames(remaining):
                break

    def request(self, cmd, p0=0, p1=0, timeout=ACK_TIMEOUT_S, predicate=None):
        self.drain()
        self.send(cmd, p0, p1)
        return self.wait(cmd, timeout=timeout, predicate=predicate)

    def wait(self, cmd, timeout=ACK_TIMEOUT_S, predicate=None):
        deadline = time.monotonic() + timeout
        frames = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            got = self.read_frames(remaining)
            frames.extend(frame for frame in got if frame.cmd == cmd)
            if predicate is not None and predicate(frames):
                break
            if not got:
                break
        return frames

    def read_frames(self, timeout):
        deadline = time.monotonic() + timeout
        frames = []
        while True:
            frame = protocol.next_frame(self.buf)
            if frame is not None:
                frames.append(frame)
                continue
            if frames:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([self.fd], [], [], remaining)
            if not ready:
                break
            try:
                chunk = os.read(self.fd, 4096)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise LinkError(f"read failed: {exc}") from exc
            if not chunk:
                break
            self._log("RX", chunk)
            self.buf.extend(chunk)
        return frames
