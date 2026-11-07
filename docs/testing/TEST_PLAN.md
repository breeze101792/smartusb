# T-PLAN-001 — test plan and results

| Field | Value |
| --- | --- |
| Scope | `hubctl` host tests, pty integration, read-only on-target checks |
| Framework | `unittest`, standard library only |
| Status | Host suite passes; real switching pending explicit approval |

## Run

```
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
python3 scripts/lab_verify.py --self-test
python3 scripts/lab_verify.py
```

The last command reads the unit and switches nothing.

## Host and pty cases

| ID | Case | Where | Result |
| --- | --- | --- | --- |
| T-APP-001 | V1/V2/V3 framing, CRC, resync, truncation, masks | `tests/test_protocol.py` | 8 pass |
| T-APP-002 | Driver identity, status, reads, writes, interlock rejection, bad echo, silence, allow-list, unsolicited report | `tests/test_driver.py` (pty fake) | 10 pass |
| T-APP-003 | Controller poll cycle, staleness, deadline, write readback, mismatch, rejection, data guard, backoff, identity gate, no replay, result strings, link loss during readback | `tests/test_controller.py` (fake driver, fake clock) | 20 pass |
| T-APP-004 | Frame: rails, bars, badge, port grid, reverse-video selection, residual voltage, data dash, every link state, interlock, no device, 60x16, ASCII rails, width/height sweep, clipping, LOST dim, menu block, Device page, all nine mockup frames character for character | `tests/test_view.py` | 32 pass |
| T-APP-005 | Discovery keeps `fe0c`, rejects `8091` | `tests/test_discovery.py` (fake sysfs tree) | 2 pass |
| T-APP-006 | Real app process: start, draw, toggle a port with Space, open the menu, quit, alternate-screen restore; no-device state | `tests/test_app_pty.py` (pty + FakeHub) | 2 pass |
| T-APP-007 | Control page and global menu: port list, selection wrap, `m` open/close, Enter reserved on ports, Enter opens Device, key routing | `tests/test_menu.py` | 28 pass |
| T-APP-008 | TUI loop: `m` opens and closes, Enter opens Device, Space and `d` act, per-key repeat guard, q/Esc quit and back, refresh on every screen | `tests/test_tui.py` (fake controller, terminal and clock) | 16 pass |
| T-APP-009 | Key decode: arrows, lone Esc, unknown escape sequences ignored, plain keys | `tests/test_term.py` (pipe fd) | 4 pass |

The pty fake can stay silent, reject `0x01`, echo the wrong value, inject an
unsolicited `0x00`, and disconnect.

## On-target

| ID | Case | Result |
| --- | --- | --- |
| T-HW-001 | Read identity, mode, channel state, measurements through the app | pass — V1.3, V2.0, 4 channels, all off at observation |
| T-HW-002 | Prove the app wrote only read commands | pass — trace contains `0x00 0x03 0x04 0x07 0x08 0x0A 0x10 0x12 0xF0 0xF1 0xFD 0xFE`, no `0x01`/`0x05` |
| T-HW-003 | `lab_verify.py` after the shared-codec refactor | 20/20 self-test; 12/12 read-only run |
| T-HW-004 | Switch a free port through the app and read both states | **pending explicit approval** |
| T-HW-005 | Pull the CMD cable: LIVE -> STALE -> LOST -> LIVE | not run |
| T-HW-006 | SIGTERM during the TUI, then inspect `stty` | pass — exit 130, alternate screen left, cursor shown, `icanon` and `OPOST` restored |

## Not covered

- Interlock rejection on the unit: the fake covers the frame path, but the unit
  was in normal mode. Entering interlock changes NVM and needs approval.
- V3 measurement streaming (`UNK-007`) and multi-channel `0x03`/`0x04`
  (`UNK-015`).
- Measurement accuracy (`UNK-010`).
- macOS `ioreg` discovery. macOS still needs `--port`.
