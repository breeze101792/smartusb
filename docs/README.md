# smartusb — project documentation

Single entry point for every document in the smartusb project.

## What this project is

`smartusb` is a clean rebuild of the control software for the SmartUSBHub Pro
4CH USB2.0 (`HBP_USB2_4CH`). The terminal app is `hubctl`. The vendor SDK is
kept read-only under `reference/` as a study copy and is not a dependency.

Settled constraints:

| Constraint | Value |
| --- | --- |
| Target device | SmartUSBHub Pro 4CH USB2.0, first hardware |
| Host platforms | Linux and macOS (POSIX) |
| Firmware scope | Current firmware only; no legacy V1 fallback |
| Runtime dependencies | None — Python standard library only |
| API shape | HAL `DeviceDriver` + raw ANSI TUI; see [ARCH-001](./architecture/overview.md) |

Other hardware follows. Each device gets its own spec and its own verification
log.

## Documents

| ID | Document | Status |
| --- | --- | --- |
| — | [Hardware index](./hardware/README.md) | Draft |
| HW-SPEC-001 | [4CH hardware specification](./hardware/smartusbhub-pro-4ch.md) | Draft — verified in part |
| HW-VER-001 | [4CH verification and open questions](./hardware/verification.md) | CMD link verified; CH4 control passed |
| — | `scripts/lab_verify.py` | Self-test 20/20; shares codec/transport with `hubctl`; read-only run 12/12 |
| — | `scripts/lab_verify.py --map` | Maps current downstream devices to channels without CMD |
| — | `scripts/lab_verify.py --allow-switch --find-device` | Identifies the channel that enumerates a new downstream device |
| ARCH-001 | [Control-app architecture](./architecture/overview.md) | Implemented — layer, module, and contract view |
| — | [Architecture review page](./architecture/overview.html) | Implemented — visual companion |
| UI-MENU-002 | [Control-page spec](./ui/menu.md) | Implemented — matches `src/hubctl` |
| — | [UI mockup](./ui/mockup/index.html) | Approved — static ANSI rendering, eight states |
| IF-PROTO-001 | [Wire protocol contract](./contracts/protocols.md) | Implemented |
| T-PLAN-001 | [Test plan and results](./testing/TEST_PLAN.md) | Host suite passes; switching pending |
| OPS-BUILD-001 | [Build and run](./operations/build.md) | Implemented |
| — | [Control app README](../README.md) | Implemented — usage, keys, safety |
| — | [`src/hubctl`](../src/hubctl) | Implemented — host suite passes |

## Stage

Control app implemented. `src/hubctl` runs one USB Control page against the CMD
port: identity, mode, per-port power/data/voltage/current, and guarded VBUS/D+/D-
switching on the selected port. `m` opens a global menu with `Device`. The host
suite, the pty app test, the refactored lab-tool self-test, and a read-only
on-target run pass. Real VBUS switching by the app is not yet run.

## Reading order

1. [HW-SPEC-001](./hardware/smartusbhub-pro-4ch.md) — what the device is and
   what the software must honour.
2. [HW-VER-001](./hardware/verification.md) — what is actually proven, what is
   still unknown, and the checks that close each unknown.
3. [ARCH-001](./architecture/overview.md) — the control app layers, module
   boundaries and hardware contract.
4. [UI-MENU-002](./ui/menu.md) — the page, the global menu and its states.
5. [IF-PROTO-001](./contracts/protocols.md) — frames, commands and timing.
6. [T-PLAN-001](./testing/TEST_PLAN.md) — what is proven, and what is not.
7. Do not design control behaviour against an `UNK` line without either
   confirming it on the unit or recording the assumption.

## Immediate next step

Run one switching test on a free channel through the app, with explicit
approval, then close the assumptions the UI currently guards: data while VBUS
is off (`UNK-004`), power-on reconnect (`UNK-013`), and interlock release
(`UNK-005`). Interlock control and V3 streaming stay out of v1.
