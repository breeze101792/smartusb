# UI-DASH-001 — `hubctl` dashboard

| Field | Value |
| --- | --- |
| Screen | Dashboard — the only screen in v1 |
| Platform | POSIX terminal, raw ANSI SGR, standard library only |
| Baseline | 80x24; minimum 60x16 |
| Refresh | One device request per 50 ms tick; full poll every 1.0 s |
| Status | Implemented — matches `src/hubctl` |

Run the reference preview in a real terminal:

```
python3 docs/ui/mockup/preview.py
```

It draws the four states below with the same ANSI sequences the app will use.
`--dump <state> --no-color` prints one frame without a terminal. The preview
adds a `1-4 demo` hint to the footer; the app does not.

## 1. Purpose

Read the hub and switch its channels without guessing:

- identify the unit and its current operating mode;
- show per-channel power, data, voltage and current;
- toggle VBUS and D+/D− on one selected channel;
- say plainly when the link is stale, lost, or the device is in interlock.

## 2. Frame

The screen is a full-terminal box. The border is part of the renderer, not the
data. `render()` returns styled lines and the terminal layer positions them.

| Row | Content |
| --- | --- |
| 1 | top border: `hubctl` left, product name right |
| 2 | `hubctl - <product>`, right: `FW <version>  HW <version>` |
| 3 | `<port>  <vid:pid>  <mode>  <link>  poll <n.n> s` |
| 4 | divider |
| 5 | interlock banner, only in interlock, followed by a divider |
| next | table header: `CH  POWER  DATA  VBUS  CURRENT` |
| ... | one row per channel, `N` from the probed channel count |
| next | divider |
| next | `device` and `settings`, only when the terminal has 20 or more rows |
| next | `last` — result of the last action |
| bottom | key hints; the last row inside the border |
| last | bottom border |

Column grid, in characters after the border: marker 2, channel 5, power 8,
data 7, voltage 12, current 9. The selected row is marked with `>` and rendered
in reverse video; the marker alone is enough in monochrome.

At 60 columns the table is 43 columns wide, so it fits. Below 60x16 the screen
shows `terminal too small - need 60x16` instead of the frame.

## 3. Presentation rules

| Rule | Behaviour |
| --- | --- |
| Power | `ON` / `off` / `?`. Reads from `0x00` only. Never inferred from voltage. |
| Data | `on` / `off` / `-` / `?`. `-` means VBUS is off, so the state is not meaningful (`UNK-004`). |
| Voltage | `4.61 V`; source is the 16-bit mV reply. |
| Residual | On an off channel, wrap the raw reading: `(202 mV)`, dim. It is leakage/backfeed, not an output. |
| Current | `0.00 A`; source is the 16-bit mA reply. Below the accuracy floor it is still `0.00 A`. |
| Unknown | `?` for any field not received in the last complete poll. |
| Data cell while off | `-`, never `on`, even if `0x08` says on. |
| Colour | `ON` green, `off` dim, residual dim, warning yellow, error red. Text always carries the meaning too. |
| Units | V and A only. No raw mV in the table; raw bytes live in `--trace`. |
| Firmware | `FW V2.0` only while the observed two-byte split decodes sanely; otherwise `FW raw 02 00`. No legacy V1 fallback. |
| Settings | `buttons` and `restore` are read at connect, not every cycle. |

## 4. Link states

| State | Trigger | Header | Table | Controls |
| --- | --- | --- | --- | --- |
| LIVE | last complete poll age < 2x poll interval | `live`, green | full colour, last cycle | power and data enabled |
| STALE | age >= 2x poll interval and < 5 s | `stale <age> s`, warning | values dimmed | disabled; footer shows `space -`, `d -` |
| LOST | age >= 5 s, open failure, or `LinkError` | `lost - reconnect <n> in <s> s`, error | `?` in every field | disabled; `r` retries now, `q` quits |
| INTERLOCK | `0x07` reports interlock | `interlock` in warning colour | table still live | switching disabled, one-line banner explains why |
| NO DEVICE | discovery finds nothing at start | one message block | none | `r` retries, `q` quits |

An incomplete poll does not erase known values; fields not received become `?`
and the age keeps increasing. A single missed cycle is not a state change.

The interlock banner is one line: `! interlock - switching disabled. Hold CH1 3 s, then r.`
It fits at 60 columns.

## 5. Keys

| Key | Action | Enabled when | Guard |
| --- | --- | --- | --- |
| `j`, `Down` | select next channel | always | — |
| `k`, `Up` | select previous channel | always | — |
| `Space` | toggle VBUS on the selected channel | LIVE, normal mode | 0.4 s repeat guard |
| `d` | toggle D+/D− on the selected channel | LIVE, normal mode, selected power is `ON` | 0.4 s repeat guard |
| `r` | poll now; retry a lost link | always | — |
| `q`, `Ctrl-C` | quit | always | restores the terminal |
| resize | redraw | always | below 60x16 show the size message |

No key writes persistent settings, resets the unit, or acts on more than one
channel. Terminal key autorepeat must not produce a stream of VBUS switches;
the 0.4 s guard drops repeats of `Space` and `d`.

## 6. The `last` line

Every write ends here, with what actually happened:

| Result | Text |
| --- | --- |
| success | `CH3 power off - echo ok, 0x00 off, 0x08 off` |
| echo mismatch | `CH3 power off - echo 0x00 0x08 differs, not applied` |
| readback mismatch | `CH3 power off - command sent, state differs (0x00 on)` |
| rejection | `interlock mode - 0x01 rejected, switching disabled` |
| link failure | `CH3 power off - no reply, link lost` |
| blocked data toggle | `data needs power on - key ignored` |

A readback mismatch is a device-state result, never a link failure, and never a
reason to reconnect. `last` holds the most recent result only.

## 7. ANSI tokens

| Token | 256-colour | 8-colour | Use |
| --- | ---: | ---: | --- |
| text | 252 | default foreground | table, keys |
| dim | 244 | bright black (90) | off channels, residual, disabled keys |
| accent | 81 | cyan (36) | wordmark, section labels |
| ok | 78 | green (32) | `ON`, `live` |
| warn | 220 | yellow (33) | `stale`, interlock banner |
| err | 203 | red (31) | `lost`, failed write |
| border | 240 | bright black (90) | frame and dividers |
| selection | — | — | reverse video (`SGR 7`) |

Use 256-colour SGR when `TERM` contains `256color` or `COLORTERM` is set, else
the 8-colour mapping. If `NO_COLOR` is set or `TERM=dumb`, emit no SGR colour at
all; the frame, text and `>` marker do not change.

Box drawing is UTF-8 (`┌ ─ │`). If the locale is not UTF-8, fall back to
`+ - |`. The preview reproduces both with `--ascii`.

## 8. Renderer rules

| Rule | Reason |
| --- | --- |
| Enter the alternate screen (`CSI ?1049h`), hide the cursor (`CSI ?25l`), clear once | full-screen app without touching scrollback |
| Address each row with `CSI <row>;1H`, append `CSI K`, one write per frame | no newline dependence; raw mode disables `OPOST` |
| Redraw only on a key, a size change, or a new snapshot | no periodic flicker or wasted writes |
| Reset SGR, show the cursor, leave the alternate screen, restore `termios` in `finally` | a crash or SIGTERM must not leave the shell in raw mode |
| Read size with `ioctl(TIOCGWINSZ)` on every frame boundary | resize is picked up without a signal handler |
| Read keys from a raw fd with `select(..., 50 ms)`; decode `ESC [ A/B` | arrows and the tick come from one loop |
| SIGTERM and SIGHUP raise `SystemExit` before the `finally` runs | cleanup on kill and hangup |

No curses. The renderer owns its output so the layout, colours, and redraw cost
are under our control.

## 9. Out of scope in v1

No interlock switching (`0x02`), no persistent-setting writes, no reset,
reboot or factory reset, no firmware update, no V3 stream, no overcurrent API,
no channel names or aliases, no downstream USB device map, no mouse, no
truecolour themes.

## 10. Verification

| Clause | Method | Where |
| --- | --- | --- |
| Four states render the specified rows | pure `render()` assertions on ANSI-stripped output | host |
| Selected row is identifiable without colour | assert `>` prefix with `NO_COLOR=1` | host |
| Every line fits the width, 60..200 columns | render at bounds, assert visible length | host |
| Height is exact, footer on the last row | assert `len(lines) == height` | host |
| Off-channel voltage never reads as an output | assert parentheses and dim attribute | host |
| Data cell is `-` while power is off | snapshot assertion | host |
| Terminal is restored after `q`, Ctrl-C, SIGTERM | run in a pty; assert `?1049l`, `?25h`, and `stty` | host |
| Identity and mode match the unit | compare with HW-VER-001 | on target |
| Toggle shows a truthful `last` line | switch a free channel, read back | on target |
| Unplug moves LIVE -> STALE -> LOST | pull the CMD cable | on target |
| Visual quality, spacing, colour balance | review against the preview | human |

The visual row is a review, not a test. Everything else has a named check.
