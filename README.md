# smartusb

Control software for the SmartUSBHub Pro 4CH USB2.0 (`HBP_USB2_4CH`).
The terminal app is `hubctl`.

Python standard library only. Linux and macOS. The vendor SDK under
`reference/` is a read-only study copy and is not a dependency.

## What it does

- Finds the CMD port by `1a86:fe0c`; it never opens the DATA hub `1a86:8091`.
- Shows identity, mode, and per-channel power, D+/D-, voltage and current.
- Switches VBUS and D+/D- on one selected channel, then reads both states back.
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

| Key | Action |
| --- | --- |
| `j` / `Down` | select next channel |
| `k` / `Up` | select previous channel |
| `Space` | toggle VBUS on the selected channel |
| `d` | toggle D+/D- (only while that channel is powered) |
| `r` | poll now; retry a lost link |
| `q` / `Ctrl-C` | quit and restore the terminal |

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
  app/                      controller, ANSI view, terminal layer, TUI
tests/                      host and pty tests
scripts/lab_verify.py       hardware verification, shares the codec/transport
docs/                       specification, architecture, protocol, tests, operations
```

## Documentation

Start at [docs/README.md](docs/README.md).
