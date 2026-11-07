# smartusb

Control software for the SmartUSBHub Pro 4CH USB2.0 (`HBP_USB2_4CH`).
The terminal app is `hubctl`.

Python standard library only. Linux and macOS. The vendor SDK under
`reference/` is a read-only study copy and is not a dependency.

## What it does

- Finds the CMD port by `1a86:fe0c`; it never opens the DATA hub `1a86:8091`.
- Shows identity, mode, and per-port power, D+/D-, voltage and current on one
  control page, one row per port.
- Switches VBUS and D+/D- on the selected port, then reads both states back.
- Opens a global menu with `m`; it holds `Device`, `Settings` and `Help`.
- Shows LIVE / STALE / LOST; switching is disabled when the link is stale or the
  unit is in interlock mode.
- Blocks NVM writes, reset, reboot, factory reset, interlock control and V3
  streaming in the transport allow-list.
- Reconnects only after re-probing identity; it never replays a command.

## Run

```
./tui.sh
./tui.sh --port /dev/ttyACM0
```

Equivalent without the launcher:

```
PYTHONPATH=src python3 -m hubctl
```

Install the console script:

```
python3 -m pip install -e .
hubctl
```

## Keys

| Key | Control | Port detail | Global menu | Settings | Device | Help |
| --- | --- | --- | --- | --- | --- | --- |
| `j` / `Down` | next port | - | next item | next setting | - | - |
| `k` / `Up` | previous port | - | previous item | previous setting | - | - |
| `Left` / `Right` | - | - | - | change the value | - | - |
| `Enter` | open the port detail | back | open the item | back | back | back |
| `Space` | toggle VBUS on the selected port | - | - | - | - | - |
| `d` | toggle D+/D- (only while powered) | - | - | - | - | - |
| `m` | open the menu | back to control | close | back to control | back to control | back to control |
| `r` | poll now; retry a lost link | poll now | poll now | poll now | poll now | poll now |
| `q` / `Esc` | quit | back | close | back | back | back |
| `Ctrl-C` | quit and restore the terminal | quit | quit | quit | quit | quit |

`Space` and `d` are refused unless the link is LIVE, the mode is normal, and for
`d` the port is powered. The reason appears on the `last` line.

Enter never switches. Terminal autorepeat can repeat a held Enter, so the only
write keys are `Space` and `d`, and the 0.4 s guard is per key. Enter opens the
port detail page, which is read-only in v1. Settings changes the endpoint and
the poll period; a port change closes the link and reopens.

## Flags

| Flag | Meaning |
| --- | --- |
| `--port` | bypass discovery, use this serial port |
| `--poll-interval S` | full poll period, default 1.0 |
| `--trace FILE` | append raw TX/RX hex to FILE |
| `--no-color` | no SGR colour |
| `--ascii` | ASCII borders instead of box drawing |

## Safety

- A switch happens only on a key press. The app never switches as a side
  effect.
- Writes are limited to `0x01` (power) and `0x05` (data), each verified by
  `0x00` and `0x08` readback.
- Power state comes from `0x00`, never from a voltage reading.
- Interlock mode is read-only in this version.
- One process owns the port: exclusive `flock`.
- Terminal state is restored on `q`, `Ctrl-C`, SIGTERM and SIGHUP.

## Verify

```
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
python3 scripts/lab_verify.py --self-test
python3 scripts/lab_verify.py
```

The last command is read-only. Real VBUS switching needs explicit approval.

Status: v1 implemented. Host suite and read-only on-target run pass. Real
switching, unplug recovery and SIGTERM restore are not yet run on the unit.

## Layout

```
src/hubctl/                 terminal app
  hal/                      driver contract, discovery, registry
  devices/smartusbhub/      codec, transport, 4CH driver
  app/                      controller, menu model, ANSI view, terminal layer, TUI
tests/                      host and pty tests
scripts/lab_verify.py       hardware verification, shares the codec/transport
docs/                       specification, architecture, protocol, tests, operations
```

## Documentation

Start at [docs/README.md](docs/README.md).
