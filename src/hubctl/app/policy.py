"""ARCH-002 automatic port control: the pure rule engine.

No I/O and no clock: ``decide`` takes the monotonic and wall times from the
caller, so a test never sleeps and never touches a device. The controller owns
the returned ``Auto`` and performs the single write a decision asks for.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Mapping

from ..constants import (
    AUTO_CYCLE_OFF_S,
    AUTO_MAX_RETRIES,
    AUTO_MIN_CYCLE_S,
    AUTO_NORMAL_SAMPLES,
    AUTO_OVER_SAMPLES,
    AUTO_SCHEDULE_DEFAULT,
    AUTO_WALL_JUMP_S,
)
from ..hal.base import ChannelReading, LinkState, Mode, Snapshot

# Policy fields in display order, docs/ui/menu.md section 3.6.
POLICY_FIELDS = ("enabled", "cycle", "overcurrent", "retry", "recovery",
                 "schedule", "from", "to")

# Allowed values, docs/ui/menu.md section 3.6. None is off.
CYCLE_CHOICES = (None, AUTO_MIN_CYCLE_S, 300, 600, 1800, 3600)
OVERCURRENT_CHOICES = (None, 500, 1000, 1500, 2000)
RETRY_CHOICES = (None, 10, 30, 60)
RECOVERY_CHOICES = (None, 60, 300, 600)

HOURS = 24


@dataclass(frozen=True)
class Policy:
    """One port's four independent rules. All off by default."""

    enabled: bool = False
    cycle_s: int | None = None
    overcurrent_ma: int | None = None
    retry_s: int | None = None
    recovery_s: int | None = None
    schedule: tuple[int, int] | None = None


@dataclass
class PortAuto:
    """Per-port timers and counters, docs/architecture/policy.md section 2."""

    last_cycle_at: float | None = None
    cut_at: float | None = None
    over_at: int = 0
    normal_at: int = 0
    retries: int = 0
    low_since: float | None = None
    pending_on_at: float | None = None
    schedule_on: bool | None = None
    manual_until: float = 0.0
    # Not timers: the text of the queued on write, and the wall time of the
    # last schedule evaluation, used to detect a backward clock jump.
    pending_text: str | None = None
    wall_at: float | None = None


@dataclass
class Auto:
    """The whole automation state: one flag, one policy and timers per port."""

    paused: bool = False
    policies: dict[int, Policy] = field(default_factory=dict)
    state: dict[int, PortAuto] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    """The single write a poll asks for."""

    port: int
    on: bool
    text: str


def empty() -> Auto:
    """Automation with no policies, not paused."""
    return Auto()


def reset(auto: Auto) -> Auto:
    """Pause automation and clear every timer, keeping the policies.

    Used for a port change, an identity change and a reconnect (section 5).
    """
    ports = set(auto.state) | set(auto.policies)
    return Auto(paused=True, policies=dict(auto.policies),
                state={port: PortAuto() for port in ports})


def decide(snapshot: Snapshot, auto: Auto,
           usb_present: Mapping[int, bool], mono: float,
           wall: float) -> tuple[Auto, Decision | None]:
    """Apply the gates and the rules once, then return the new state.

    ``usb_present`` maps a port to whether this host sees a downstream device;
    a missing port counts as no device. ``mono`` drives the timers, ``wall``
    (epoch seconds) the schedule. At most one decision comes back.
    """
    state = {port: replace(item) for port, item in auto.state.items()}
    result = Auto(auto.paused, dict(auto.policies), state)

    if (snapshot.link != LinkState.LIVE
            or snapshot.status.mode != Mode.NORMAL):
        _cancel(result)
        return result, None
    if auto.paused:
        _cancel(result)
        return result, None

    for port in sorted(result.policies):
        rule = result.policies[port]
        if not rule.enabled:
            _cancel_port(result, port)
            continue
        reading = snapshot.channels.get(port)
        if reading is None:
            continue
        decision = _evaluate_port(port, rule, reading, result, usb_present,
                                  mono, wall)
        if decision is not None:
            return result, decision
    return result, None


def step(rule: Policy, field: str, delta: int) -> Policy:
    """Step one policy value by ``delta``, wrapping (menu.md section 3.6)."""
    if field == "enabled":
        return replace(rule, enabled=not rule.enabled)
    if field == "cycle":
        return replace(rule, cycle_s=_choose(CYCLE_CHOICES, rule.cycle_s,
                                             delta))
    if field == "overcurrent":
        return replace(rule, overcurrent_ma=_choose(OVERCURRENT_CHOICES,
                                                     rule.overcurrent_ma,
                                                     delta))
    if field == "retry":
        return replace(rule, retry_s=_choose(RETRY_CHOICES, rule.retry_s,
                                             delta))
    if field == "recovery":
        return replace(rule, recovery_s=_choose(RECOVERY_CHOICES,
                                                rule.recovery_s, delta))
    if field == "schedule":
        window = None if rule.schedule is not None else AUTO_SCHEDULE_DEFAULT
        return replace(rule, schedule=window)
    if field in ("from", "to") and rule.schedule is not None:
        start, end = rule.schedule
        if field == "from":
            start = ((start // 60 + delta) % HOURS) * 60
        else:
            end = ((end // 60 + delta) % HOURS) * 60
        return replace(rule, schedule=(start, end))
    return rule


def _choose(choices, current, delta: int):
    """Step through a value table and wrap. An unknown value starts at zero."""
    index = choices.index(current) if current in choices else 0
    return choices[(index + delta) % len(choices)]


def _cancel(auto: Auto):
    """Cancel the deferred work of every port; keep the cycle baseline."""
    for state in auto.state.values():
        _cancel_port_state(state)


def _cancel_port(auto: Auto, port: int):
    state = auto.state.get(port)
    if state is not None:
        _cancel_port_state(state)


def _evaluate_port(port: int, rule: Policy, reading: ChannelReading,
                   auto: Auto, usb_present: Mapping[int, bool], mono: float,
                   wall: float) -> Decision | None:
    state = auto.state.setdefault(port, PortAuto())
    power = reading.power

    cut = _overcurrent(port, rule, reading, state, power, mono)
    if cut is not None:
        return cut
    if mono < state.manual_until:
        # A key or a button wins every rule but the safe cut, and a gate
        # cancels the deferred work instead of postponing it.
        _cancel_port_state(state)
        return None

    retry = _retry(port, rule, state, power, mono)
    if retry is not None:
        return retry

    recovery = _recovery(port, rule, reading, state, usb_present, mono, power)
    if recovery is not None:
        return recovery

    cycle = _cycle(port, rule, state, power, mono)
    if cycle is not None:
        return cycle

    edge = _schedule(port, rule, state, power, wall)
    if edge is not None:
        return edge

    return _pending_on(port, state, power, mono)


def _overcurrent(port: int, rule: Policy, reading: ChannelReading,
                 state: PortAuto, power: bool | None,
                 mono: float) -> Decision | None:
    """Rule 1. Two above-threshold samples cut; three normal samples re-arm."""
    if rule.overcurrent_ma is None:
        return None
    if power is not True:
        state.over_at = 0
        return None
    current = reading.current_ma
    if current is None:
        return None
    if current > rule.overcurrent_ma:
        state.over_at += 1
        state.normal_at = 0
        if state.over_at < AUTO_OVER_SAMPLES:
            return None
        state.over_at = 0
        state.cut_at = mono
        _cancel_port_state(state)
        return Decision(port, False,
                        f"USB{port} off - auto overcurrent "
                        f"{current / 1000:.2f} A")
    state.over_at = 0
    state.normal_at += 1
    if state.normal_at >= AUTO_NORMAL_SAMPLES:
        state.retries = 0
    return None


def _retry(port: int, rule: Policy, state: PortAuto, power: bool | None,
           mono: float) -> Decision | None:
    """Rule 2. Restore after a cut, capped at AUTO_MAX_RETRIES."""
    if power is not False or rule.retry_s is None or state.cut_at is None:
        return None
    if state.retries >= AUTO_MAX_RETRIES:
        return None
    if mono < state.cut_at + rule.retry_s:
        return None
    state.retries += 1
    state.cut_at = None
    state.over_at = 0
    state.normal_at = 0
    return Decision(port, True,
                    f"USB{port} on - auto retry "
                    f"{state.retries} of {AUTO_MAX_RETRIES}")


def _recovery(port: int, rule: Policy, reading: ChannelReading,
              state: PortAuto, usb_present: Mapping[int, bool], mono: float,
              power: bool | None) -> Decision | None:
    """Rule 3. Cycle a port whose downstream device left the bus."""
    if power is not True or rule.recovery_s is None:
        return None
    if reading.data is not True:
        state.low_since = None
        return None
    if usb_present.get(port, False):
        state.low_since = None
        return None
    if state.low_since is None:
        state.low_since = mono
        return None
    if mono - state.low_since < rule.recovery_s:
        return None
    state.low_since = None
    state.last_cycle_at = mono
    state.pending_on_at = mono + AUTO_CYCLE_OFF_S
    state.pending_text = f"USB{port} on - auto recovery"
    return Decision(port, False,
                    f"USB{port} off - auto recovery, no device "
                    f"{rule.recovery_s // 60} min")


def _cycle(port: int, rule: Policy, state: PortAuto, power: bool | None,
           mono: float) -> Decision | None:
    """Rule 4. Power-cycle an ON port on its period; never turns one on."""
    if power is not True or rule.cycle_s is None:
        return None
    if state.last_cycle_at is None:
        state.last_cycle_at = mono
        return None
    if mono - state.last_cycle_at < rule.cycle_s:
        return None
    state.last_cycle_at = mono
    state.pending_on_at = mono + AUTO_CYCLE_OFF_S
    state.pending_text = f"USB{port} on - auto cycle"
    return Decision(port, False,
                    f"USB{port} off - auto cycle {rule.cycle_s // 60} min")


def _schedule(port: int, rule: Policy, state: PortAuto, power: bool | None,
              wall: float) -> Decision | None:
    """Rule 5. Edge-triggered on local wall time; from == to means never."""
    if rule.schedule is None:
        return None
    start, end = rule.schedule
    if start == end:
        return None
    inside = _inside(start, end, wall)
    if state.wall_at is not None and wall < state.wall_at - AUTO_WALL_JUMP_S:
        state.wall_at = wall
        state.schedule_on = inside
        return None
    state.wall_at = wall
    if inside and state.schedule_on is not True:
        state.schedule_on = True
        state.retries = 0
        state.pending_on_at = None
        state.pending_text = None
        if power is True:
            return None
        return Decision(port, True,
                        f"USB{port} on - auto schedule {_clock(start)}")
    if not inside and state.schedule_on is True:
        state.schedule_on = False
        state.retries = 0
        state.pending_on_at = None
        state.pending_text = None
        if power is False:
            return None
        return Decision(port, False,
                        f"USB{port} off - auto schedule {_clock(end)}")
    return None


def _pending_on(port: int, state: PortAuto, power: bool | None,
                mono: float) -> Decision | None:
    """Rule 6. The on phase of a cycle, a recovery or a scheduled retry."""
    if state.pending_on_at is None or mono < state.pending_on_at:
        return None
    text = state.pending_text or f"USB{port} on - auto cycle"
    state.pending_on_at = None
    state.pending_text = None
    state.over_at = 0
    state.normal_at = 0
    if power is True:
        return None
    return Decision(port, True, text)


def _cancel_port_state(state: PortAuto):
    state.pending_on_at = None
    state.pending_text = None
    state.low_since = None


def _inside(start: int, end: int, wall: float) -> bool:
    """Is the wall clock inside minutes ``start``..``end``, wrapping?"""
    minute = _minute_of_day(wall)
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end


def _minute_of_day(wall: float) -> int:
    local = time.localtime(wall)
    return local.tm_hour * 60 + local.tm_min


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
