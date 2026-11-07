# OPS-BUILD-001 — build, run, and troubleshoot

| Field | Value |
| --- | --- |
| App | `hubctl` |
| Runtime | Python 3.9+, standard library only |
| Hosts | Linux and macOS |
| Status | Implemented |

## Run from the repository

```
./tui.sh
./tui.sh --port /dev/ttyACM0
```

The launcher sets `PYTHONPATH` to the repository `src/` and passes arguments
through. It requires an interactive terminal.

The app needs an interactive terminal. Discovery on Linux keeps only
`/dev/ttyACM*` whose sysfs IDs are `1a86:fe0c`. It never opens the DATA hub
`1a86:8091`. On macOS, pass `--port`.

## Install the console script

```
python3 -m pip install -e .
hubctl
```

If the system Python is externally managed, use a virtual environment:

```
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

There are no runtime dependencies.

## Test

```
PYTHONPATH=src python3 -m unittest discover -s tests -t . -v
python3 scripts/lab_verify.py --self-test
python3 scripts/lab_verify.py
```

The last command is read-only. Real switching needs explicit approval; see
[T-PLAN-001](../testing/TEST_PLAN.md).

## Trace

```
hubctl --trace /tmp/hubctl.trace
```

Each line is `<monotonic-seconds> TX|RX <hex bytes>`. The trace is append-only.
Use it to prove which commands reached the unit.

## Port permissions

The CMD port is `/dev/ttyACM0` on Linux. Add the user to the owning group
(`uucp` on Arch, `dialout` on Debian) and reconnect:

```
sudo usermod -aG uucp "$USER"
```

The app takes an exclusive `flock` on the fd. A second instance, or a tool that
holds the port, gets `port is in use by another process`.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `no SmartUSBHub CMD port found` | CMD USB-C cable is a data cable; `lsusb` shows `1a86:fe0c`; pass `--port` if sysfs is unavailable |
| `port is in use` | Another `hubctl`, `lab_verify.py`, or the vendor SDK holds the port |
| Link goes stale | Pull/replug the CMD cable; the app retries with backoff |
| `link is not live - no write` | Wait for the next poll, or press `r` |
| `interlock mode - switching disabled` | The unit is in interlock; hold CH1 for 3 s to return to normal, then `r` |
| Values show `?` | No complete poll yet, or the link is lost |
| Garbled frame in the trace | Check 115200 8N1 and that no other process writes the port |
