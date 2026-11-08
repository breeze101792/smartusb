"""Persist the poll interval and the auto rules between runs.

One small JSON file under ``$XDG_STATE_HOME``. It holds user settings only:
the poll period and the per-port rules. The runtime state (paused, timers,
manual hold) never reaches it, and a corrupt or unknown file is ignored so a
bad write can never stop the app from starting.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from ..constants import MAX_CHANNELS, POLL_MAX_S, POLL_MIN_S
from . import policy

STATE_VERSION = 1
STATE_DIR_MODE = 0o700


def default_path() -> Path:
    """``$XDG_STATE_HOME/hubctl/state.json``, or the home fallback."""
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "hubctl" / "state.json"


def load(path) -> tuple[float, dict[int, policy.Policy]] | None:
    """The saved poll and rules, or None when there is nothing usable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    poll = data.get("poll_s")
    if not isinstance(poll, (int, float)) or isinstance(poll, bool):
        return None
    poll = max(POLL_MIN_S, min(POLL_MAX_S, float(poll)))
    rules = {}
    for key, entry in (data.get("policies") or {}).items():
        try:
            port = int(key)
        except (TypeError, ValueError):
            continue
        if not 1 <= port <= MAX_CHANNELS or not isinstance(entry, dict):
            continue
        rules[port] = _rule(entry)
    return poll, rules


def save(path, poll: float, policies: Mapping[int, policy.Policy]) -> None:
    """Write the state atomically; a failure leaves the old file in place."""
    target = Path(path)
    target.parent.mkdir(mode=STATE_DIR_MODE, parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "poll_s": round(float(poll), 3),
        "policies": {str(port): _entry(rule)
                     for port, rule in sorted(policies.items())},
    }
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent,
        prefix=".state-", suffix=".tmp", delete=False)
    try:
        with handle:
            json.dump(payload, handle, indent=1, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, target)
    except OSError:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _entry(rule: policy.Policy) -> dict:
    return {
        "enabled": rule.enabled,
        "cycle_s": rule.cycle_s,
        "overcurrent_ma": rule.overcurrent_ma,
        "over_action": rule.over_action,
        "under_ma": rule.under_ma,
        "under_action": rule.under_action,
        "retry_s": rule.retry_s,
        "recovery_s": rule.recovery_s,
        "schedule": list(rule.schedule) if rule.schedule else None,
    }


def _rule(entry: dict) -> policy.Policy:
    """Rebuild a rule, keeping only values the engine accepts."""
    schedule = entry.get("schedule")
    if (not isinstance(schedule, (list, tuple)) or len(schedule) != 2
            or not all(isinstance(part, int) and 0 <= part < 24 * 60
                       for part in schedule)):
        schedule = None
    else:
        schedule = (schedule[0], schedule[1])
    return policy.Policy(
        enabled=bool(entry.get("enabled")),
        cycle_s=_int(entry.get("cycle_s")),
        overcurrent_ma=_int(entry.get("overcurrent_ma")),
        over_action=_action(entry.get("over_action")),
        under_ma=_int(entry.get("under_ma")),
        under_action=_action(entry.get("under_action")),
        retry_s=_int(entry.get("retry_s")),
        recovery_s=_int(entry.get("recovery_s")),
        schedule=schedule,
    )


def _int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _action(value) -> str:
    return value if value in policy.ACTIONS else policy.ACTION_CUT
