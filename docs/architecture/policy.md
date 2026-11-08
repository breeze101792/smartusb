# ARCH-002 — automatic port control

| Field | Value |
| --- | --- |
| Status | Implemented |
| Scope | Per-port rules that switch VBUS without a key press |
| Runtime | In memory only; nothing persists |
| UI | [UI-MENU-002 §3.5, §3.6](./../ui/menu.md) |
| Safety | Writes only on a LIVE link in normal mode |

## 1. Decision

The app gains four independent per-port rules, all off by default. The
controller evaluates them after each completed poll and performs at most one
write per poll through a dedicated path:

```python
Controller.set_power(port, on, reason)   # not the key toggle
```

`set_power` never inverts the current state. It is the same guarded path as a
key press: link and mode gates, echo check, `0x00`/`0x08` readback, `last`
text. A decision whose target already matches the observed state updates the
bookkeeping without a write.

The rules are a pure function in `app/policy.py`:

```python
decide(snapshot, auto, usb_present, mono, wall) -> tuple[Auto, Decision | None]
```

It returns the new `Auto` (timers included) and at most one decision.
`mono` is `time.monotonic` for timers; `wall` is local wall time for the
schedule. Both are injected, so tests never sleep.

Nothing is queued across a gate: when a gate closes, the deferred work is
cancelled, not postponed (section 5).

## 2. Model

```python
@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    cycle_s: int | None = None           # power-cycle an ON port
    overcurrent_ma: int | None = None    # cut above this, two samples
    under_ma: int | None = None          # cut below this, two samples
    retry_s: int | None = None           # restore after a cut; capped
    recovery_s: int | None = None        # cycle when the device is gone
    schedule: tuple[int, int] | None = None  # minutes of day, from/to

@dataclass
class PortAuto:
    last_cycle_at: float | None = None
    cut_at: float | None = None
    over_at: int = 0            # consecutive over-threshold samples
    normal_at: int = 0          # consecutive normal samples while ON
    retries: int = 0
    low_since: float | None = None
    pending_on_at: float | None = None
    schedule_on: bool | None = None   # None until the first edge
    manual_until: float = 0.0
    pending_text: str | None = None   # result line for the queued on
    wall_at: float | None = None      # last wall time, for jump detection

@dataclass
class Auto:
    paused: bool = False
    policies: dict[int, Policy]
    state: dict[int, PortAuto]
```

`Auto` lives in the controller for the session. The TUI reads a copy for
rendering and sends edits back as actions.

## 3. Gates

A decision is returned only when all hold. A closed gate cancels pending work
(section 5).

| Gate | Rule |
| --- | --- |
| Link | `snapshot.link == LIVE` |
| Mode | `snapshot.status.mode == NORMAL` |
| Enabled | `policy.enabled` for that port |
| Paused | `auto.paused` is false |
| Manual hold | `mono >= state.manual_until` |
| Port exists | the port is in `snapshot.channels`; with no device there are no policy rows |

## 4. Rules

Evaluated in this order; the first rule that returns a decision wins for that
port. Ports are considered in ascending order, so a tie is deterministic.

1. **Overcurrent cut.** Port ON, current above `overcurrent_ma` for two
   consecutive polls → off. A safe cut ignores the manual hold. Store
   `cut_at` and `retries`. The counter resets after three normal samples while
   the port is ON; it is not cleared while the port is off.
2. **Under-current cut.** Port ON, current below `under_ma` for two consecutive
   polls → off. This is not a safety cut, so the manual hold suppresses it. It
   stores `cut_at` and feeds the retry rule like any other cut.
3. **Overcurrent retry.** Port OFF with `cut_at` set and `retry_s` set, at most
   three consecutive retries, `mono >= cut_at + retry_s` → on. A retry is
   suppressed by the manual hold. After the third retry the rule stops until
   the policy is re-armed (enable toggled off and on, or a schedule edge).
4. **Recovery.** Port ON with data on, no downstream device seen by this host
   for `recovery_s` → cycle: off now, on when the next poll is at least
   `AUTO_CYCLE_OFF_S` later. The USB map is the signal, not the current: a
   current floor sits inside the ±50 mA offset. This rule assumes the DATA hub
   is connected to this host; if it is not, leave it off.
5. **Cycle.** Port ON, `mono - last_cycle_at >= cycle_s` → off now, on after
   the off phase. A cycle never turns an off port on. `last_cycle_at` is set at
   the off write.
6. **Schedule edges.** Inside the `from`..`to` window (wrap when `to < from`;
   `from == to` means never) with `schedule_on` false → on. Outside with
   `schedule_on` true → off. Edge-triggered on wall time. A manual change
   between edges is not undone. A backward wall jump of more than 60 s skips
   one evaluation and resyncs. Enabling the schedule uses the default window
   08:00 to 18:00; while the schedule is off, `from` and `to` read `--`.
7. **Pending on.** A port left off by a cycle or a recovery is turned on when
   `mono >= pending_on_at`. Cancelled by any gate, by a schedule edge and by a
   poll change.

## 5. Timer lifetime

| Event | Effect |
| --- | --- |
| Link goes STALE or LOST | cancel `pending_on_at`; clear `low_since`; keep `last_cycle_at` |
| Mode becomes interlock | same as LOST |
| Paused | same, and no rule runs |
| Policy disabled | same |
| Manual `Space` | `manual_until = mono + 5 s`; cancel `pending_on_at` |
| Observed power change not caused by the app | `manual_until = mono + 5 s` |
| Port change, identity change, reconnect | pause all automation, clear every timer |
| Exit | no write; a port mid-cycle stays off |

The last row is deliberate. A 2 s off phase can be left behind by `q`; the
user is told on the policy page that the rules are saved for the next run.

## 6. Timing

| Constant | Value | Why |
| --- | --- | --- |
| `AUTO_MIN_CYCLE_S` | 60 s | shortest cycle period |
| `AUTO_CYCLE_OFF_S` | 2 s | the device drops off the bus |
| `AUTO_MANUAL_HOLD_S` | 5 s | a key or a button wins |
| `AUTO_MAX_RETRIES` | 3 | stop retrying a persistent fault |
| `AUTO_OVER_SAMPLES` | 2 | cut after two over-threshold polls |
| `AUTO_NORMAL_SAMPLES` | 3 | re-arm after three normal polls |
| `AUTO_MAX_POLL_S` | 1 s | automation is off above a 1 s poll |

Above a 1 s poll the status shows `auto off - poll too long` and no rule
runs. The off phase is "at least 2 s", measured in polls.

## 7. Result text

| Rule | Text |
| --- | --- |
| overcurrent cut | `USB2 off - auto overcurrent 1.62 A` |
| under-current cut | `USB2 off - auto undercurrent 0.02 A` |
| overcurrent retry | `USB2 on - auto retry 1 of 3` |
| cycle off | `USB2 off - auto cycle 10 min` |
| cycle on | `USB2 on - auto cycle` |
| recovery off | `USB2 off - auto recovery, no device 5 min` |
| recovery on | `USB2 on - auto recovery` |
| schedule on | `USB2 on - auto schedule 08:00` |
| schedule off | `USB2 off - auto schedule 18:00` |

An automated write does not overwrite a manual result until one completed poll
has passed.

## 8. Display

| Element | Rule |
| --- | --- |
| Status text | append `auto <n>` when a policy is enabled, `auto paused`, or `auto off - poll too long`; omit the field when none apply |
| Status placement | every page draws the status on the `last` row, right-aligned, and never moves it; the status sheds the poll then the mode to keep ten columns for the action, and stays on row 3 only when there is no device |
| Narrow widths | drop `poll <n> s` first, never the auto field |
| Port rows | `A` at column 3 for an enabled port |
| Policy page | dim row 12: `rules are saved for the next run` |

## 9. Invariants

| ID | Invariant |
| --- | --- |
| INV-012 | An automated write happens only while the link is LIVE and the mode is normal |
| INV-013 | A manual VBUS change suppresses automation for 5 s on that port; a safe cut is exempt |
| INV-014 | At most one automated write per poll, through `set_power` with readback |
| INV-015 | The poll period and the rules are saved under `$XDG_STATE_HOME`; the runtime state is not, and exiting performs no write |
| INV-016 | The cut uses `0x04`; the vendor overcurrent candidates `0x1B`/`0x1C` stay out of the allow-list (`UNK-006`) |

## 10. Risks

| ID | Risk |
| --- | --- |
| RISK-001 | `0x04` is ±(2.5% + 50 mA) per the datasheet, not metrology. At 0.5 A the band is ±62 mA; the presets are approximate. `UNK-010` covers the per-unit offset. |
| RISK-002 | Retry is capped at three; a persistent fault then stays off until re-armed. |
| RISK-003 | The schedule uses local wall time; a jump larger than 60 s skips one evaluation. |
| RISK-004 | Recovery reads this host's sysfs. If the DATA hub goes to another host, leave recovery off. |

## 11. Verification

| Clause | Method | Where |
| --- | --- | --- |
| Each rule fires at its time and not before, on both clocks | pure `decide()` with fake clocks | host |
| Priority and the port tie-break | pure truth table | host |
| Gates cancel pending work; a reconnect never resumes a cycle | pure truth table | host |
| Two over-threshold samples cut; three normal samples re-arm | pure truth table | host |
| Retry caps at three and re-arms only as stated | pure truth table | host |
| `set_power` uses the target state, never the toggle | controller with a fake driver | host |
| A write restarts the poll cycle so the readback is not clobbered | controller assertion | host |
| `last` names the rule and a manual result survives one poll | controller assertion | host |
| UI: policy page, `A` marker, auto field, pause, narrow status | render and TUI assertions | host |
| A cycle on a free port with a device attached | on the unit, with approval | on target — not run |
