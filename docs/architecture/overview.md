# ARCH-001 — `hubctl` software architecture

| Field | Value |
| --- | --- |
| Status | Implemented — host tests and read-only on-target pass |
| Scope | v1 terminal control app for the SmartUSBHub Pro 4CH |
| Runtime | Python 3.9+, standard library only |
| Hosts | Linux and macOS (POSIX) |
| Review page | [overview.html](./overview.html) |

## 1. Decision

One process, one page, four layers:

```
TUI (raw ANSI)  ->  Controller  ->  DeviceDriver (HAL)  ->  4CH driver  ->  codec + transport
```

- **Single thread.** `select(..., 50 ms)` is the clock. Each tick performs at
  most one device request. There is no worker thread, queue, or event bus.
  Worst-case key lag is one ACK timeout, 0.35 s.
- **Raw ANSI, not curses.** The renderer emits SGR and cursor addressing
  directly. The frame, colours, and redraw cost stay under our control, and the
  terminal database is out of the runtime path. Standard library only.
- **The HAL is a switched-power-channel device**, not a generic instrument. A
  future non-channel device gets its own ABC, not a genericized version of this
  one.
- **The TUI never imports a device module.** It sees `Snapshot` and the
  `Controller` only. Protocol bytes cannot reach the screen.
- **Reuse the verified code.** The frame codec and termios link are shared with
  `scripts/lab_verify.py`, which now imports them. Its pty self-test passes
  20/20 and its read-only run passes 12/12 on the unit. Discovery is separate:
  the app's `hal/discovery.py` is strict (VID:PID only); the lab tool keeps its
  wider candidate scan for macOS.

## 2. Layers

| Layer | Files | Responsibility | Must not |
| --- | --- | --- | --- |
| CLI / TUI | `cli.py`, `app/tui.py`, `app/menu.py`, `app/view.py`, `app/term.py` | arguments, terminal lifecycle, keys, menu state, pure ANSI rendering | speak protocol, open a port |
| Controller | `app/controller.py` | tick schedule, poll cycle, write verification, staleness, reconnect | format text, build frames |
| HAL | `hal/base.py`, `hal/registry.py` | types, `DeviceDriver` ABC, error taxonomy, driver list | know termios or ANSI |
| Discovery | `hal/discovery.py` | enumerate candidate endpoints per platform | open or write a port |
| 4CH driver | `devices/smartusbhub/driver.py` | 4CH semantics: masks, mode, channel state, capabilities | know the UI |
| Codec / transport | `devices/smartusbhub/protocol.py`, `transport.py` | frames, CRC, serial fd, allow-list, exclusive lock | know channel semantics |

Dependency direction is acyclic:

```
cli -> tui -> controller -> hal.base
          tui -> menu -> hal.base (types only)
          tui -> view -> menu, hal.base (types only)
          tui -> term
       controller -> hal.registry -> driver -> protocol + transport
```

## 3. Module boundaries

| Module | Owns | PROVIDES | REQUIRES |
| --- | --- | --- | --- |
| `hal/base.py` | types and the driver contract | `Identity`, `Status`, `ChannelReading`, `Snapshot`, `Mode`, `LinkState`, `DeviceDriver`, error classes | nothing |
| `hal/discovery.py` | candidate endpoint list | `candidate_ports() -> list[str]` | stdlib only |
| `hal/registry.py` | static driver tuple | `DRIVERS`, `open_first(port=None) -> DeviceDriver` | `hal.base`, each driver |
| `devices/smartusbhub/protocol.py` | frame encoding and parsing | `encode_v1`, `encode_v2`, `encode_v3`, `next_frame`, `crc16` | nothing |
| `devices/smartusbhub/transport.py` | fd, exclusive lock, allow-list | `SerialLink(port)`, `request`, `write`, `close` | `protocol`, stdlib |
| `devices/smartusbhub/driver.py` | device semantics and state | `DeviceDriver` methods | `hal.base`, `protocol`, `transport` |
| `app/controller.py` | session state and policy | `Controller` methods, `snapshot()` | `hal.base`, `hal.registry` |
| `app/menu.py` | page and menu state, item lists, key routing | `State`, `Action`, `items()`, `index()`, `handle_key()`, `readout()`, `device_fields()` | `hal.base` types |
| `app/view.py` | ANSI text layout | `render(snapshot, state, width, height) -> list[str]` | `menu`, `hal.base` types |
| `app/term.py` | raw mode, alternate screen, size, key decode, frame write | `Terminal`, `read_key()`, `draw()` | stdlib |
| `app/tui.py` | loop and input handling | `run(controller)` | `term`, `view`, `menu`, `controller` |
| `cli.py` | arguments, exit codes | `main(argv) -> int` | everything above |

Per-module PROVIDES/REQUIRES contracts with pre/postconditions, error tables and
resource clauses are written in `architecture/modules/` after the scope is
approved. This file fixes the boundaries; it does not duplicate them.

## 4. HAL contract

Types cross the boundary, not bytes:

```python
class Mode(Enum):          NORMAL | INTERLOCK | UNKNOWN
class LinkState(Enum):     LIVE | STALE | LOST

@dataclass(frozen=True)
class Identity:
    product: str           # "HBP_USB2_4CH" or "code 0x05"
    hardware: str          # "V1.3" or "raw 03"
    firmware: str          # "V2.0" or "raw 02 00"
    channels: int          # 1..7, from 0xF1, else product table, else 4
    address: int           # 0..0xFFFF
    port: str              # endpoint that answered

@dataclass
class ChannelReading:
    power: bool | None     # 0x00
    data: bool | None      # 0x08, None when power is off
    voltage_mv: int | None # 0x03, raw
    current_ma: int | None # 0x04, raw

@dataclass
class Status:
    mode: Mode             # 0x07
    buttons_enabled: bool | None   # 0x0A
    restore_enabled: bool | None   # 0x10

@dataclass
class Snapshot:
    identity: Identity | None   # None before the first successful open
    status: Status
    channels: dict[int, ChannelReading]
    link: LinkState
    last_cycle_age_s: float
    last_action: str
    last_kind: str             # ok | warn | err
    last_error: str | None
    reconnect_in_s: float | None
    poll_interval_s: float
```

```python
class DeviceDriver(ABC):
    supports_measurement: ClassVar[bool] = False
    supports_data_switch: ClassVar[bool] = False

    @classmethod
    def discover(cls) -> Iterable[str]: ...            # candidate endpoints, no opens
    @classmethod
    def open(cls, endpoint: str) -> "DeviceDriver": ...  # raises NotThisDevice

    def close(self) -> None: ...
    def identity(self) -> Identity: ...
    def read_status(self) -> Status: ...                 # one request (0x07)
    def read_power(self, channels) -> dict[int, bool | None]: ...   # one request
    def read_data(self, channels) -> dict[int, bool | None]: ...    # one request
    def read_voltage(self, channel: int) -> int | None: ...         # one request
    def read_current(self, channel: int) -> int | None: ...         # one request
    def read_channels(self, channels) -> dict[int, ChannelReading]: ...  # convenience
    def set_power(self, channels: Sequence[int], on: bool) -> None: ...
    def set_data(self, channels: Sequence[int], on: bool) -> None: ...  # NotSupported
```

`read_channels()` composes the single-request calls. The controller uses the
single-request calls so one tick issues exactly one request; tests use the
convenience method.

| Error | Raised when | Controller reaction |
| --- | --- | --- |
| `NotThisDevice` | the identity handshake gets no reply at `open()` | try the next candidate; never write again to that port |
| `LinkError` | unplug, I/O error, or silence on a mandatory query | close, mark LOST, start reconnect backoff |
| `Timeout` | a write ACK or a readback did not arrive | one retry for a readback; otherwise `LinkError` |
| `NotSupported` | the capability flag is false | disable the key; never send the command |
| `Rejected` | `55 5A 01 FF FF FF` for `0x01` | set mode INTERLOCK, show banner, disable switching |
| `StateMismatch` | the echo or readback differs from the request | report in `last`; keep the link; no reconnect |

`Timeout` and `NotSupported` are separate on purpose: silence on a mandatory
query is a link failure, not a missing feature (`HW-C-003`).

## 5. The tick

```
every 50 ms
  key = read_key(select timeout 50 ms)      # raw fd, ESC [ A/B decoded
  if key:            route through menu.handle_key(); a toggle runs the write path
  else:              issue one request from the poll cycle
  if snapshot changed or the size changed: draw()
```

Poll cycle, one request per tick, in this order:

1. `0x07` mode
2. `0x00` power, mask derived from the probed channel count
3. `0x08` data, same mask
4. `0x03` voltage, one channel at a time (`UNK-015`)
5. `0x04` current, one channel at a time

For four channels that is 3 + 2N = 11 requests. Including the 20 ms drain
window the cycle takes about 0.3 s, inside the 1 s interval. If the cycle overruns, it is
abandoned and restarted; values from the last complete cycle stay visible with
increasing age.

Timing constants, all named:

| Constant | Value | Source |
| --- | --- | --- |
| `TICK_MS` | 50 ms | UI responsiveness |
| `POLL_INTERVAL_S` | 1.0 s | chosen |
| `ACK_TIMEOUT_S` | 0.20 s | `src/hubctl/constants.py`; vendor SDK 100 ms is tighter |
| `MULTI_TIMEOUT_S` | 0.35 s | `src/hubctl/constants.py` |
| `DRAIN_WINDOW_S` | 0.02 s | `src/hubctl/constants.py` |
| `WRITE_SETTLE_S` | 0.03 s | chosen; lets the switch and MCU settle before readback |
| `STALE_AFTER` | 2 x poll | chosen |
| `LINK_DEADLINE_S` | 5 s | chosen |
| `KEY_REPEAT_GUARD_S` | 0.4 s | chosen; blocks terminal autorepeat |
| `RECONNECT_BACKOFF_S` | 1, 2, 4, 8 (cap) | chosen |

## 6. Write path

`Space` or `d` on the control page runs this sequence synchronously:

1. Guard: link LIVE, mode NORMAL, selected port known, and for `d` power is
   `ON`.
2. Transport checks the command against its allow-list.
3. Send `0x01` (power) or `0x05` (data) with a mask built from the channel.
4. Wait for the echo, at most `ACK_TIMEOUT_S`. `55 5A 01 FF FF FF` means
   interlock: set mode, disable switching, stop.
5. Sleep `WRITE_SETTLE_S`.
6. Re-read power (`0x00`) **and** data (`0x08`) for the channel. Retry once.
   Power-off auto-disconnects D+/D−, and power-on reconnect is `UNK-013`; both
   states must be re-read (`HW-C-012`).
7. Write the result to `last`: echo and readback, or a mismatch.

A mismatch is a state result, never a link error, and never a reconnect. The
worst-case block on a failing link is about 1.1 s; the alternative is a worker
thread, deferred until it is measured as a problem.

## 7. Safety invariants

| ID | Invariant | Enforced by |
| --- | --- | --- |
| INV-001 | The app transmits only `0x00 0x01 0x03 0x04 0x05 0x07 0x08 0x0A 0x0C 0x0E 0x10 0x12 0xF0 0xF1 0xFD 0xFE` | transport allow-list, before any write |
| INV-002 | No write changes NVM, resets, reboots, or enters firmware update | same allow-list excludes `0x02 0x06 0x09 0x0B 0x0D 0x0F 0x11 0xFC 0xF7 0x1A 0x1E-0x21 0xF9` |
| INV-003 | Channel masks are derived from the probed count and bounded to `0x7F` | driver; `HW-C-001` |
| INV-004 | Power state comes from `0x00`, never from voltage | driver and view; `HW-C-007` |
| INV-005 | Every switch is followed by `0x00` and `0x08` readback | controller; `HW-C-012` |
| INV-006 | Commands are only sent while link is LIVE | controller; prevents acting on stale state |
| INV-007 | No command is replayed after a reconnect | single thread, key-driven commands, no queue |
| INV-008 | A reconnect resumes only if the identity matches the session | controller identity gate; `HW-C-008`, `HW-C-009` |
| INV-009 | One process owns the port | exclusive non-blocking `flock` on the fd |
| INV-010 | The terminal is restored on every exit path | raw-mode enter/leave in `finally`, plus SIGTERM/SIGHUP |
| INV-011 | The app never binds a reply by command byte alone | framing plus per-command decode; unsolicited `0x00` is drained and treated as truth |

## 8. Discovery and reconnect

- Linux: read `/sys/class/tty/<node>/device/../idVendor` and `idProduct`; keep
  `1a86:fe0c`; never match the DATA hub `1a86:8091` (`HW-C-008`). The sysfs root
  is a parameter so tests can inject a fake tree.
- macOS: no sysfs. `ioreg` is parsed for `idVendor`/`idProduct` and the callout
  device. This is not yet verified on a Mac; until it is, macOS requires
  `--port`.
- Explicit `--port` bypasses discovery.
- Every candidate is opened and must answer the identity queries. A port that
  does not answer is closed and never written to again.
- Reconnect uses the same discovery, then compares product, hardware, firmware,
  channels, and address with the recorded identity. Serial number is not used
  in v1 because the serial command is SDK-only (`UNK-008`). A mismatch keeps the
  app in LOST and reports `different device on <port>`.

## 9. Future hardware

Adding a model or instrument:

1. Add a driver module implementing `DeviceDriver`; set the capability flags.
2. Add its endpoints to `discovery` if the transport differs.
3. Add the class to the `DRIVERS` tuple.
4. Write its hardware spec under `docs/hardware/` before it ships.

Rejected on purpose: dynamic plugin discovery, entry points, a generic
instrument abstraction, async I/O, and a background service. Each costs more
than the second driver it would serve.

## 10. Out of scope in v1

Interlock switching (`0x02`), persistent settings writes, reset/reboot/factory
reset, firmware update, overcurrent, V3 streaming, names/alias/serial,
downstream sysfs device map, non-interactive CLI output, mouse.

## 11. Verification

| Claim | Method | Result |
| --- | --- | --- |
| Codec matches documented and captured frames | vector tests, bad checksum resync, truncation | host — 8 pass |
| Driver: identity, masks, reads, writes, rejection, silence, allow-list | pty fake device | host — 10 pass |
| Controller: poll schedule, write verify, staleness, reconnect, result strings, port and poll settings | fake driver, injectable clock | host — 23 pass |
| Menu model: port list, port detail, global menu, Settings, Enter never writes, key routing | pure `menu` assertions | host — 32 pass |
| Render: frame, states, width/height sweep, clipping, selection without colour, thirteen mockup frames | pure `render()` assertions | host — 35 pass |
| TUI loop: `m` opens and closes, Enter opens the port detail, Device, Settings and Help, usb map read only with data on, every screen redrawn, per-key repeat guard | fake controller, terminal and clock | host — 21 pass |
| Discovery filters `fe0c` and rejects `8091` | fake sysfs tree | host — 2 pass |
| Key decode: arrows, lone Esc, unknown sequences ignored, plain keys | raw pipe fd | host — 4 pass |
| Downstream USB map: hub discovery, port child, empty port, missing tree | fake sysfs tree | host — 4 pass |
| App starts, toggles a port, opens the menu, quits, restores the screen | real app process in a pty | host — 2 pass |
| Identity, mode, channel reads on the unit | app read-only run, raw trace | on target — pass |
| Lab tool after the shared-codec refactor | `--self-test`; default read-only run | 20/20; 12/12 |
| Real VBUS switching | toggle a free channel, read both states | **pending explicit approval** |
| Unplug recovery, LIVE -> STALE -> LOST | pull the CMD cable | not run |
| SIGTERM restores the terminal | send SIGTERM, inspect `stty` | not run |

The pty fake device must not hide the unknowns: it stays silent on demand,
emits a rejection, emits an unsolicited `0x00`, and can close the link.

## 12. Open decisions

| ID | Question | Effect |
| --- | --- | --- |
| OD-001 | What class of hardware comes after the 4CH? | whether the HAL stops at switched-power-channel devices |
| OD-002 | Is a non-interactive `hubctl status` / `--json` wanted? | adds a second front end over the same controller |
