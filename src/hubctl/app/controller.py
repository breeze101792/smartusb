"""Session policy: tick schedule, poll cycle, write verification, reconnect."""

from __future__ import annotations

import time
from dataclasses import replace

from ..constants import (
    AUTO_MANUAL_HOLD_S,
    AUTO_MAX_POLL_S,
    FAILURE_LIMIT,
    LINK_DEADLINE_S,
    POLL_CHOICES_S,
    POLL_INTERVAL_S,
    POLL_MAX_S,
    POLL_MIN_S,
    PORT_CHOICES_TTL_S,
    RECONNECT_BACKOFF_S,
    STALE_AFTER_POLLS,
    WRITE_SETTLE_S,
)
from ..hal import usbmap
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
from ..hal.discovery import candidate_ports
from ..hal.registry import open_first
from . import policy, store
from .policy import Auto, Policy, PortAuto


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

    def __init__(self, open_fn=None, poll_interval: float | None = None,
                 clock=time.monotonic, sleep=time.sleep,
                 port: str | None = None, trace=None, wall=time.time,
                 state_path=None):
        self._port = port
        self._trace = trace
        self._state_path = state_path
        self._open_fn = open_fn or (
            lambda: open_first(self._port, trace=self._trace))
        self._poll = poll_interval
        self._port_choices: tuple[str, ...] = ()
        self._choices_at: float | None = None
        self._clock = clock
        self._wall = wall
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

        # ARCH-002 automation. The rules are restored from the state file.
        self._auto = self._restore(poll_interval)
        self._poll_count = 0
        self._manual_poll: int | None = None
        self._observed: dict[int, bool | None] = {}
        self._wrote: dict[int, bool] = {}

    def _restore(self, poll_interval: float | None) -> Auto:
        """Load the saved poll and rules; an explicit value wins."""
        stored = store.load(self._state_path) if self._state_path else None
        if stored is None:
            if poll_interval is None:
                self._poll = POLL_INTERVAL_S
            return policy.empty()
        saved_poll, rules = stored
        if poll_interval is None:
            self._poll = saved_poll
        return Auto(paused=False, policies=rules, state={})

    def _save(self):
        if self._state_path is None:
            return
        try:
            store.save(self._state_path, self._poll, self._auto.policies)
        except OSError as error:
            self._note(f"state not saved - {error.strerror or error}", "warn")

    # --- lifecycle --------------------------------------------------------
    def close(self):
        if self._driver is not None:
            try:
                self._driver.close()
            except DeviceError:
                pass
        self._driver = None

    def _port_options(self) -> tuple[str, ...]:
        now = self._clock()
        if (self._choices_at is None
                or now - self._choices_at > PORT_CHOICES_TTL_S):
            choices = list(dict.fromkeys(candidate_ports()))
            if self._port is not None and self._port not in choices:
                choices.append(self._port)
            self._port_choices = tuple(choices)
            self._choices_at = now
        return self._port_choices

    def set_port(self, port: str | None):
        """Switch endpoint and reopen. None means discovery."""
        if port == self._port:
            return
        self._port = port
        self.close()
        self._identity = None
        self._status = Status()
        self._channels = {}
        self._cycle = []
        self._failures = 0
        self._last_cycle = None
        self._backoff = 0
        self._next_open = self._clock()
        self._choices_at = None
        self._observed = {}
        self._wrote = {}
        self._auto = policy.reset(self._auto)
        self._note(f"port set to {port or 'auto'}", "ok")

    def set_poll(self, seconds: float):
        """Change the full poll period, bounded like the CLI."""
        seconds = max(POLL_MIN_S, min(POLL_MAX_S, seconds))
        if seconds == self._poll:
            return
        self._poll = seconds
        for state in self._auto.state.values():
            state.pending_on_at = None
            state.pending_text = None
        self._save()
        self._note(f"poll set to {seconds:.1f} s", "ok")

    # --- automation -------------------------------------------------------
    def auto(self) -> Auto:
        """A copy of the automation state, for rendering."""
        return Auto(paused=self._auto.paused,
                    policies=dict(self._auto.policies),
                    state={port: replace(item)
                           for port, item in self._auto.state.items()})

    def set_policy(self, port: int, policy: Policy):
        """Store one port's rules. A change of ``enabled`` re-arms the port."""
        previous = self._auto.policies.get(port)
        self._auto.policies[port] = policy
        if previous is None:
            self._auto.state.setdefault(port, PortAuto())
        elif previous.enabled != policy.enabled:
            self._auto.state[port] = PortAuto()
        if not policy.enabled:
            state = self._auto.state.get(port)
            if state is not None:
                state.pending_on_at = None
                state.pending_text = None
                state.low_since = None
        self._save()

    def set_auto_paused(self, paused: bool):
        """Pause or resume automation. Pausing cancels the deferred work."""
        if paused == self._auto.paused:
            return
        self._auto.paused = paused
        if paused:
            self._cancel_auto()

    def request_refresh(self):
        """Poll now. Also retries a lost link immediately."""
        self._cycle = []
        self._failures = 0
        self._next_cycle = self._clock()
        if self._driver is None:
            self._next_open = self._clock()

    def _restart_cycle(self):
        """Drop the in-flight poll so a stale reading cannot clobber a write."""
        self._cycle = []
        self._pending = {}
        self._failures = 0
        self._next_cycle = self._clock()

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
            port_setting=self._port,
            port_choices=self._port_options(),
        )

    # --- connect / reconnect ---------------------------------------------
    def _schedule_open(self, now: float):
        index = min(self._backoff, len(RECONNECT_BACKOFF_S) - 1)
        self._next_open = now + RECONNECT_BACKOFF_S[index]
        self._backoff = min(self._backoff + 1, len(RECONNECT_BACKOFF_S) - 1)

    def _try_open(self, now: float) -> bool:
        driver = None
        reconnecting = self._identity is not None
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
            self._observed = {}
            self._wrote = {}
            if reconnecting:
                self._auto = policy.reset(self._auto)
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
        self._cancel_auto()
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
        self._poll_count += 1
        self._note_external(now)
        if self._poll <= AUTO_MAX_POLL_S:
            self._evaluate()

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
        if changed and link != LinkState.LIVE:
            self._cancel_auto()
        self._link = link
        return changed

    # --- automation -------------------------------------------------------
    def _evaluate(self):
        """Run the rules once, after a completed poll, and write at most once."""
        now = self._clock()
        snapshot = self.snapshot()
        watched = [port for port, rule in self._auto.policies.items()
                   if rule.enabled and rule.recovery_s is not None]
        usb_present = usbmap.port_devices(watched)
        self._auto, decision = policy.decide(
            snapshot, self._auto, usb_present, now, self._wall())
        if decision is not None:
            self.set_power(decision.port, decision.on, decision.text,
                           auto=True)

    def _cancel_auto(self):
        """Let a closed gate cancel the deferred work, not postpone it."""
        now = self._clock()
        self._auto, _decision = policy.decide(
            self.snapshot(), self._auto, {}, now, self._wall())

    def _note_external(self, now: float):
        """A power state this app did not command is a press on the unit."""
        for port, reading in self._channels.items():
            previous = self._observed.get(port)
            if (port in self._auto.policies
                    and previous is not None
                    and reading.power is not None
                    and reading.power != previous
                    and not self._wrote.get(port)):
                state = self._auto.state.setdefault(port, PortAuto())
                state.manual_until = now + AUTO_MANUAL_HOLD_S
                state.pending_on_at = None
                state.pending_text = None
            self._observed[port] = reading.power
            self._wrote[port] = False

    # --- control ----------------------------------------------------------
    def _note(self, text: str, kind: str):
        self._last_action = text
        self._last_kind = kind

    def _note_result(self, text: str, kind: str, auto: bool):
        """A manual result keeps the line for one completed poll."""
        if (auto and self._manual_poll is not None
                and self._poll_count <= self._manual_poll + 1):
            return
        self._note(text, kind)
        if not auto:
            self._manual_poll = self._poll_count

    def _hold(self, channel: int):
        """A key press wins every rule but the safe cut, for five seconds."""
        state = self._auto.state.setdefault(channel, PortAuto())
        state.manual_until = self._clock() + AUTO_MANUAL_HOLD_S
        state.pending_on_at = None
        state.pending_text = None

    def set_power(self, port: int, on: bool, reason: str, auto: bool = False):
        """Write a target state, never a toggle (ARCH-002).

        The same guards as a key press, then the echo and readback path. When
        the target already matches the observed state nothing is written.
        """
        snapshot = self.snapshot()
        if self._driver is None or snapshot.link != LinkState.LIVE:
            self._note("link is not live - no write", "warn")
            return
        if self._status.mode != Mode.NORMAL:
            self._note("interlock mode - switching disabled", "warn")
            return
        current = self._channels.get(port)
        if current is None or current.power is None:
            self._note(f"{_usb(port)} power state unknown - no write", "warn")
            return
        if current.power == on:
            return
        self._write_power(port, on, reason, auto)

    def toggle_power(self, channel: int):
        self._hold(channel)
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
        self._write_power(channel, not current.power, None, False)

    def _write_power(self, channel: int, target: bool, reason: str | None,
                     auto: bool):
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

        self._wrote[channel] = True
        self._restart_cycle()
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
            self._note_result(
                f"{_usb(channel)} {verb} - state differs "
                f"(0x00 {'on' if power else 'off'})", "warn", auto)
        elif reason is not None:
            self._note_result(reason, "ok", auto)
        else:
            data_text = "?" if raw_data is None else ("on" if raw_data else "off")
            self._note_result(
                f"{_usb(channel)} {verb} - echo ok, "
                f"0x00 {'on' if power else 'off'}, 0x08 {data_text}", "ok",
                auto)

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

        self._restart_cycle()
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
            self._note_result(
                f"{_usb(channel)} data {verb} - state differs "
                f"(0x08 {'on' if data else 'off'})", "warn", False)
        else:
            self._note_result(
                f"{_usb(channel)} data {verb} - echo ok, "
                f"0x08 {'on' if data else 'off'}", "ok", False)

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
