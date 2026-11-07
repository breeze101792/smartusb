"""Session policy: tick schedule, poll cycle, write verification, reconnect."""

from __future__ import annotations

import time

from ..constants import (
    FAILURE_LIMIT,
    LINK_DEADLINE_S,
    POLL_INTERVAL_S,
    RECONNECT_BACKOFF_S,
    STALE_AFTER_POLLS,
    WRITE_SETTLE_S,
)
from ..hal.base import (
    ChannelReading,
    DeviceDriver,
    DeviceError,
    Identity,
    LinkError,
    LinkState,
    Mode,
    Rejected,
    Snapshot,
    StateMismatch,
    Status,
    Timeout,
)
from ..hal.registry import open_first


def _same_identity(left: Identity, right: Identity) -> bool:
    return (left.product == right.product
            and left.product_code == right.product_code
            and left.hardware == right.hardware
            and left.firmware == right.firmware
            and left.channels == right.channels
            and left.address == right.address)


def _usb(port: int) -> str:
    """The result-line abbreviation for USB PORT n."""
    return f"USB{port}"


def _link_lost(port: int, verb: str) -> str:
    return f"{_usb(port)} {verb} - no reply, link lost"


class Controller:
    """One device, one poll cycle, one request per tick.

    Commands exist only for the duration of a key press. Nothing is queued, so
    a reconnect cannot replay a switch against a device that came back.
    """

    def __init__(self, open_fn=None, poll_interval: float = POLL_INTERVAL_S,
                 clock=time.monotonic, sleep=time.sleep):
        self._open_fn = open_fn or (lambda: open_first())
        self._poll = poll_interval
        self._clock = clock
        self._sleep = sleep

        self._driver: DeviceDriver | None = None
        self._identity: Identity | None = None
        self._status = Status()
        self._channels: dict[int, ChannelReading] = {}

        self._last_cycle: float | None = None
        self._last_action = "searching for device"
        self._last_kind = "warn"
        self._last_error: str | None = None
        self._link = LinkState.LOST

        self._next_open = 0.0
        self._backoff = 0
        self._cycle: list[tuple] = []
        self._cycle_index = 0
        self._cycle_started = 0.0
        self._next_cycle = 0.0
        self._pending: dict[int, ChannelReading] = {}
        self._failures = 0

    # --- lifecycle --------------------------------------------------------
    def close(self):
        if self._driver is not None:
            try:
                self._driver.close()
            except DeviceError:
                pass
        self._driver = None

    def request_refresh(self):
        """Poll now. Also retries a lost link immediately."""
        self._cycle = []
        self._failures = 0
        self._next_cycle = self._clock()
        if self._driver is None:
            self._next_open = self._clock()

    def tick(self, now: float) -> bool:
        """Perform at most one device request. True when the snapshot changed."""
        changed = False
        if self._driver is None:
            if now >= self._next_open:
                changed = self._try_open(now)
            return changed

        changed |= self._refresh_link(now)
        if self._driver is None:
            return changed

        if not self._cycle and now >= self._next_cycle:
            self._start_cycle(now)
        if self._cycle:
            changed |= self._run_step(now)
        return changed

    def snapshot(self) -> Snapshot:
        now = self._clock()
        age = 0.0 if self._last_cycle is None else now - self._last_cycle
        if self._driver is None:
            link = LinkState.LOST
        elif self._last_cycle is None:
            link = LinkState.STALE
        elif age < self._poll * STALE_AFTER_POLLS:
            link = LinkState.LIVE
        elif age < LINK_DEADLINE_S:
            link = LinkState.STALE
        else:
            link = LinkState.LOST
        reconnect = None
        if self._driver is None:
            reconnect = max(0.0, self._next_open - now)
        return Snapshot(
            identity=self._identity,
            status=Status(self._status.mode, self._status.buttons_enabled,
                          self._status.restore_enabled),
            channels={
                channel: ChannelReading(reading.power, reading.data,
                                        reading.voltage_mv, reading.current_ma)
                for channel, reading in self._channels.items()
            },
            link=link,
            last_cycle_age_s=age,
            last_action=self._last_action,
            last_kind=self._last_kind,
            last_error=self._last_error,
            reconnect_in_s=reconnect,
            poll_interval_s=self._poll,
        )

    # --- connect / reconnect ---------------------------------------------
    def _schedule_open(self, now: float):
        index = min(self._backoff, len(RECONNECT_BACKOFF_S) - 1)
        self._next_open = now + RECONNECT_BACKOFF_S[index]
        self._backoff = min(self._backoff + 1, len(RECONNECT_BACKOFF_S) - 1)

    def _try_open(self, now: float) -> bool:
        driver = None
        try:
            driver = self._open_fn()
            identity = driver.identity()
            if self._identity is not None and not _same_identity(identity, self._identity):
                driver.close()
                self._note(f"different device on {identity.port} - not controlling", "err")
                self._schedule_open(now)
                return True
            self._driver = driver
            self._identity = identity
            self._status = Status()
            try:
                self._status = driver.read_status()
            except (Timeout, LinkError):
                pass
            self._channels = {
                channel: ChannelReading()
                for channel in range(1, identity.channels + 1)
            }
            self._pending = {}
            self._cycle = []
            self._failures = 0
            self._last_cycle = None
            self._link = LinkState.STALE
            self._next_cycle = now
            self._next_open = 0.0
            self._backoff = 0
            self._last_error = None
            self._note(f"connected {identity.product} on {identity.port}", "ok")
            return True
        except DeviceError as exc:
            if driver is not None and driver is not self._driver:
                try:
                    driver.close()
                except DeviceError:
                    pass
            self._last_error = str(exc)
            self._note(str(exc), "err")
            self._schedule_open(now)
            return True

    def _mark_lost(self, reason: str):
        if self._driver is not None:
            try:
                self._driver.close()
            except DeviceError:
                pass
        self._driver = None
        self._link = LinkState.LOST
        self._cycle = []
        self._failures = 0
        self._last_error = reason
        self._note(reason, "err")
        self._schedule_open(self._clock())

    # --- polling ----------------------------------------------------------
    def _start_cycle(self, now: float):
        if self._identity is None:
            return
        channels = list(range(1, self._identity.channels + 1))
        self._cycle = ([("status", 0), ("power", 0), ("data", 0)]
                       + [("voltage", channel) for channel in channels]
                       + [("current", channel) for channel in channels])
        self._cycle_index = 0
        self._cycle_started = now
        self._pending = {channel: ChannelReading() for channel in channels}

    def _run_step(self, now: float) -> bool:
        name, channel = self._cycle[self._cycle_index]
        try:
            if name == "status":
                self._status = self._driver.read_status()
                changed = True
            elif name == "power":
                values = self._driver.read_power(range(1, self._identity.channels + 1))
                for number, value in values.items():
                    if number in self._pending:
                        self._pending[number].power = value
                changed = False
            elif name == "data":
                values = self._driver.read_data(range(1, self._identity.channels + 1))
                for number, value in values.items():
                    if number in self._pending:
                        self._pending[number].data = value
                changed = False
            elif name == "voltage":
                if channel in self._pending:
                    self._pending[channel].voltage_mv = self._driver.read_voltage(channel)
                changed = False
            elif name == "current":
                if channel in self._pending:
                    self._pending[channel].current_ma = self._driver.read_current(channel)
                changed = False
            else:
                changed = False
        except Timeout as exc:
            self._failures += 1
            if self._failures >= FAILURE_LIMIT:
                self._mark_lost("no reply from device")
            else:
                self._last_error = str(exc)
            return True
        except LinkError as exc:
            self._mark_lost(str(exc))
            return True
        except StateMismatch as exc:
            self._last_error = str(exc)
            self._note(str(exc), "warn")
            return True

        self._failures = 0
        self._cycle_index += 1
        if self._cycle_index >= len(self._cycle):
            self._finish_cycle(now)
            return True
        return changed

    def _finish_cycle(self, now: float):
        for reading in self._pending.values():
            if reading.power is not True:
                reading.data = None
        self._channels = self._pending
        self._pending = {}
        self._last_cycle = now
        self._link = LinkState.LIVE
        self._last_error = None
        self._cycle = []
        self._next_cycle = self._cycle_started + self._poll
        if self._next_cycle < now:
            self._next_cycle = now

    def _refresh_link(self, now: float) -> bool:
        if self._last_cycle is None:
            link = LinkState.STALE
        else:
            age = now - self._last_cycle
            if age < self._poll * STALE_AFTER_POLLS:
                link = LinkState.LIVE
            elif age < LINK_DEADLINE_S:
                link = LinkState.STALE
            else:
                self._mark_lost("link deadline exceeded")
                return True
        changed = link != self._link
        self._link = link
        return changed

    # --- control ----------------------------------------------------------
    def _note(self, text: str, kind: str):
        self._last_action = text
        self._last_kind = kind

    def toggle_power(self, channel: int):
        snapshot = self.snapshot()
        if self._driver is None or snapshot.link != LinkState.LIVE:
            self._note("link is not live - no write", "warn")
            return
        if self._status.mode != Mode.NORMAL:
            self._note("interlock mode - switching disabled", "warn")
            return
        current = self._channels.get(channel)
        if current is None or current.power is None:
            self._note(
                f"{_usb(channel)} power state unknown - no write", "warn")
            return
        target = not current.power
        verb = "on" if target else "off"
        failure = _link_lost(channel, verb)
        driver = self._driver
        try:
            driver.set_power([channel], target)
        except Rejected:
            self._status.mode = Mode.INTERLOCK
            self._note("interlock - 0x01 rejected", "warn")
            return
        except StateMismatch:
            self._note(f"{_usb(channel)} {verb} - echo differs, not applied",
                       "warn")
            return
        except (LinkError, Timeout):
            self._mark_lost(failure)
            return

        self._sleep(WRITE_SETTLE_S)
        power = self._read_back(lambda: driver.read_power([channel]), channel,
                                failure)
        if self._driver is None:
            return
        data = self._read_back(lambda: driver.read_data([channel]), channel,
                               failure)
        if self._driver is None:
            return
        if power is None:
            self._note(f"{_usb(channel)} {verb} - readback timed out", "warn")
            return
        raw_data = data
        stored = self._channels[channel]
        self._channels[channel] = ChannelReading(
            power=power,
            data=data if power is True else None,
            voltage_mv=stored.voltage_mv,
            current_ma=stored.current_ma,
        )
        if power != target:
            self._note(
                f"{_usb(channel)} {verb} - state differs "
                f"(0x00 {'on' if power else 'off'})", "warn")
        else:
            data_text = "?" if raw_data is None else ("on" if raw_data else "off")
            self._note(
                f"{_usb(channel)} {verb} - echo ok, "
                f"0x00 {'on' if power else 'off'}, 0x08 {data_text}", "ok")

    def toggle_data(self, channel: int):
        snapshot = self.snapshot()
        if self._driver is None or snapshot.link != LinkState.LIVE:
            self._note("link is not live - no write", "warn")
            return
        if self._status.mode != Mode.NORMAL:
            self._note("interlock mode - switching disabled", "warn")
            return
        current = self._channels.get(channel)
        if current is None or current.power is not True:
            self._note(
                f"{_usb(channel)} data needs power - key ignored", "warn")
            return
        if current.data is None:
            self._note(
                f"{_usb(channel)} data state unknown - no write", "warn")
            return
        target = not current.data
        verb = "on" if target else "off"
        failure = _link_lost(channel, f"data {verb}")
        driver = self._driver
        try:
            driver.set_data([channel], target)
        except StateMismatch:
            self._note(
                f"{_usb(channel)} data {verb} - echo differs, not applied",
                "warn")
            return
        except (LinkError, Timeout):
            self._mark_lost(failure)
            return

        self._sleep(WRITE_SETTLE_S)
        data = self._read_back(lambda: driver.read_data([channel]), channel,
                               failure)
        if self._driver is None:
            return
        if data is None:
            self._note(
                f"{_usb(channel)} data {verb} - readback timed out", "warn")
            return
        stored = self._channels[channel]
        self._channels[channel] = ChannelReading(
            power=stored.power,
            data=data,
            voltage_mv=stored.voltage_mv,
            current_ma=stored.current_ma,
        )
        if data != target:
            self._note(
                f"{_usb(channel)} data {verb} - state differs "
                f"(0x08 {'on' if data else 'off'})", "warn")
        else:
            self._note(
                f"{_usb(channel)} data {verb} - echo ok, "
                f"0x08 {'on' if data else 'off'}", "ok")

    def _read_back(self, read, channel: int, failure: str):
        for attempt in range(2):
            try:
                return read().get(channel)
            except Timeout:
                if attempt == 1:
                    return None
            except LinkError:
                self._mark_lost(failure)
                return None
        return None
