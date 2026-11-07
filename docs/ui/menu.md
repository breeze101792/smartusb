# UI-MENU-002 — `hubctl` page

| Field | Value |
| --- | --- |
| Page | USB Control, with a global menu summoned over it |
| Platform | POSIX terminal, raw ANSI SGR, standard library only |
| Baseline | 80x24; minimum 60x16 |
| Refresh | One device request per 50 ms tick; full poll every 1.0 s |
| Status | Approved mockup; implementation pending |
| Mockup | [mockup/index.html](./mockup/index.html) |
| Replaces | UI-DASH-001 dashboard table (removed) |

The mockup is the visual truth. This document fixes the behaviour and the
contract the code must satisfy. Where the two differ, the mockup wins on
placement and this document wins on behaviour.

## 1. Purpose

Control the hub from one live page. The port list is the page. Global actions
live in a menu that opens over the list, so they never take the place of the
live readings. Each port is controlled directly from the list.

## 2. Frame

`render()` returns exactly `height` lines of exactly `width` visible columns.

| Element | Column | Row |
| --- | --- | --- |
| Left rail `│` | 4 | every row |
| Right rail `│` | `W-4` | every row |
| Header bar | 5..`W-5` | 1 |
| Footer bar | 5..`W-5` | `H` |
| Status line | 8 | 3 |
| Interlock banner | 8 | 4 |
| List, first row | 8 | 5 |
| `last` label | 8 | `H-1` |
| `last` text | 16 | `H-1` |

Header: left title at column 5. Right: the status badge `" " + state + " "`,
right-aligned so its last character is at `W-6`, with one bar cell at `W-5`
before the rail. Fill between with the bar.

Port row columns, 1-based, on the control page and the Device page's status
line:

| Field | Column | Width |
| --- | ---: | ---: |
| label `USB PORT n` | 8 | 12 |
| power `ON` / `off` / `?` | 20 | 4 |
| data `data on` / `data off` / `-` / `?` | 24 | 8 |
| voltage `4.61 V` or `(202 mV)` | 34 | 9 |
| current `0.00 A` | 45 | 7 |

Two spaces separate the data, voltage and current cells.

At 80x24, control page, LIVE:

```
   │HUBCTL  USB CONTROL                                              live  │
   │                                                                       │
   │   port /dev/ttyACM0   normal   live   poll 1.0 s                      │
   │                                                                       │
   │   USB PORT 1  ON  data on   4.61 V     0.00 A                         │
   │   USB PORT 2  off -         (202 mV)   0.00 A                         │
   │   USB PORT 3  ON  data off  5.02 V     0.21 A                         │
   │   USB PORT 4  ON  data on   4.88 V     0.44 A                         │
   │                                                                       │
   │   ...                                                                 │
   │   last    USB2 off - echo ok, 0x00 off, 0x08 off                      │
   │SPACE power   d data   m menu   q quit                                 │
```

Trailing padding to the right rail is spaces; the diagram compresses the middle
rows only.

## 3. Screens

### 3.1 USB Control

The only page. Header title `HUBCTL  USB CONTROL`. Status line:
`port <port>   <mode>   <link>   poll <n.n> s`, where mode is `normal`,
`interlock` or `unknown` and link is `live`, `stale <age> s` or `lost`. Badge:
`live`, `stale <age> s`, `lost - retry <n> s`, `interlock`, `no device`.

Items, in order: `USB PORT 1` .. `USB PORT n`, one row each, where `n` is the
probed port count, 1..7. There are no command rows; commands are in the global
menu.

Each row shows power, data, voltage and current. The selected row is the only
row in reverse video.

Footer: `SPACE power   d data   m menu   q quit`. On LOST and no device it
becomes `r retry` in place of `r refresh`; the no-device footer is
`r retry   m menu   q quit`.

`Enter` opens the selected port's detail page. The footer does not mention it.

### 3.2 Port detail

Header title `HUBCTL  USB PORT n - <power>`, plus ` - data <word>` when the port
is powered. Status line: `port <port>   1a86:fe0c   <link>`.

| Row | Field | Value |
| --- | --- | --- |
| 5 | `power` | `ON`, `off` or `?` |
| 6 | `data` | `on`, `off`, `-` or `?` |
| 7 | `voltage` | `4.61 V`, `(202 mV)` or `?` |
| 8 | `current` | `0.00 A` or `?` |
| 9 | `usb` | `045e:028e`, `data off` or `no device` |
| 10 | `product` | the device's product string, when row 9 has a device |

Labels at column 8, values at column 20, in the same tokens as the port row.
Rows 11 and 12 stay free for the monitor and advanced controls that come next.
`Back` is the only item, at row 13, selected.

The `usb` and `product` rows come from this host's sysfs, under the DATA hub
`1a86:8091` and downstream port `n`. They are read only while D+/D- is `on`:
with data off the port is not connected to the host, so row 9 reads `data off`
and row 10 is blank. With data on and no device enumerated, row 9 reads
`no device`. A device on another host cannot appear, by definition. This is
read-only; it never writes the hub or the downstream device.

Footer: `ENTER back   q back`. `Enter`, `q`, `Esc` and `m` return to the control
page with the same port selected. `Space` and `d` do nothing here: this page
reads, and the control page writes.

### 3.3 Global menu

`m` on the control page replaces the port rows with the menu block on the same
page. Header, status line, `last` and footer stay. The menu is application-wide,
not a peer page.

| Row | Content |
| --- | --- |
| 5 | `GLOBAL MENU`, dim |
| 6 | first item |
| ... | one item per row |

v1 has three items: `Device`, `Settings` and `Help`. Later global actions append
here. The selected item is the only reverse-video row. `j` and `k` wrap between
items.

Footer: `ENTER open   m close   q close`. `m`, `Esc` and `q` close the menu and
return to the list with the same port selected. Closing the menu never quits.

At 80x24 with the menu open:

```
   │HUBCTL  USB CONTROL                                              live  │
   │                                                                       │
   │   port /dev/ttyACM0   normal   live   poll 1.0 s                      │
   │                                                                       │
   │   GLOBAL MENU                                                         │
   │   Device                                                              │
   │   Help                                                               │
   │                                                                       │
   │   last    USB2 off - echo ok, 0x00 off, 0x08 off                      │
   │ENTER open   m close   q close                                         │
```

### 3.4 Settings

Header title `HUBCTL  SETTINGS`. Status line:
`port <port>   1a86:fe0c   <link>`.

| Row | Setting | Values |
| --- | --- | --- |
| 5 | `port` | `auto` or a discovered endpoint, including the current one |
| 6 | `poll` | `0.5 s`, `1.0 s`, `2.0 s`, `5.0 s` |

Labels at column 8, values at column 20. `j` and `k` select a row; `Left` and
`Right` step the value and wrap. `Back` is at row 13, selected.

Footer: `LEFT/RIGHT change   ENTER back   q back`. `Enter`, `q`, `Esc` and `m`
return to the control page.

Changing `port` closes the link, clears the identity and reopens at the new
endpoint, or by discovery for `auto`. Changing `poll` takes effect on the next
cycle. Both write a result to the `last` line, which stays visible below the
settings.

### 3.5 Device

Header title `HUBCTL  DEVICE`. Status line:
`port <port>   1a86:fe0c   <link>`. Rows 5..11, label at 8 and value at 20:

| Row | Field | Source |
| --- | --- | --- |
| 5 | `ports` | probed port count |
| 6 | `product` | identity |
| 7 | `firmware` | identity |
| 8 | `hardware` | identity |
| 9 | `address` | identity |
| 10 | `buttons` | status |
| 11 | `restore` | status |

`Back` is the only item, at row 13, selected. Values not read read `?`.
Footer: `ENTER back   q back`. `Enter`, `q` and `Esc` return to the control
page. The `last` line stays on row `H-1`.

### 3.6 Help

Header title `HUBCTL  HELP`. Status line: `port <port>   1a86:fe0c   <link>`.

| Row | Content |
| --- | --- |
| 5 | `hubctl <version>` in bold, from `hubctl.__version__` |
| 6 | `SmartUSBHub Pro 4CH terminal control` in dim |
| 8 | `j/k     select port` |
| 9 | `SPACE   power on/off` |
| 10 | `d       data on/off` |
| 11 | `m       menu, r refresh` |
| 12 | `q       quit, Esc back` |
| 13 | `Back`, selected |

Keys are at column 8 in an 8-column cell, the description at column 16.
`Enter`, `q`, `Esc` and `m` return to the control page. Footer:
`ENTER back   q back`. The `last` line stays on row `H-1`.

### 3.7 No device

Control page with no identity:

| Row | Content |
| --- | --- |
| 3 | `discovery 1a86:fe0c   no port   retry <n> s` |
| 5 | `no SmartUSBHub CMD port` in warn |
| 6 | `connect the CMD USB-C port, or pass --port /dev/ttyACM0.` in dim |
| 8 | no port rows |

The `last` row is blank. The menu still opens with its `Device` item, whose
fields all read `?`.

## 4. States

| State | Badge | Rows | Writes | Footer |
| --- | --- | --- | --- | --- |
| LIVE | `live` ok | full colour | allowed | normal |
| STALE | `stale <age> s` warn | values dim | refused | normal |
| LOST | `lost - retry <n> s` err | every field `?`, dim | refused | `r retry` replaces `r refresh` |
| INTERLOCK | `interlock` warn | banner on row 4, values live | refused | normal |
| NO DEVICE | `no device` warn | message block only | none | `r retry   m menu   q quit` |

A refused write still reaches the controller, which writes the reason to
`last`. The page never invents a refusal of its own. A single late poll is
STALE, not LOST. In LOST the port selection stays visible and the menu stays
reachable, so `Quit` and `Device` are never lost.

The interlock banner is one line, naming the physical button on the unit:
`! interlock - switching disabled. Hold CH1 3 s, then r.`

## 5. Keys

| Key | Control | Port detail | Global menu | Settings | Device | Help | Guard |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `j`, `Down` | next port | none | next item | next setting | none | none | wraps |
| `k`, `Up` | previous port | none | previous item | previous setting | none | none | wraps |
| `Left`, `Right` | none | none | none | step the value | none | none | — |
| `Enter` | open port detail | back | open item | back | back | back | 0.4 s |
| `Space` | toggle VBUS on the selected port | none | none | none | none | none | 0.4 s |
| `d` | toggle D+/D- on the selected port | none | none | none | none | none | 0.4 s |
| `m` | open menu | back to control | close | back to control | back to control | back to control | 0.4 s |
| `r` | poll now | poll now | poll now | poll now | poll now | poll now | — |
| `q`, `Esc` | quit | back | close | back | back | back | — |
| `Ctrl-C` | quit | quit | quit | quit | quit | quit | — |
| resize | redraw | redraw | redraw | redraw | redraw | redraw | below 60x16 show the size message |

The 0.4 s guard is per key, and every event of a guarded key refreshes its
timestamp, including a dropped one. Holding a key acts at most once when
autorepeat begins and then stays silent until it is released. Only `Space` and
`d` write. `Enter` never writes and does nothing on the control page in v1.

## 6. The `last` line

Every write ends here with what actually happened. The text must fit the
40 columns between column 16 and the right rail at 60 columns; longer text is
clipped.

| Result | Text |
| --- | --- |
| power on, verified | `USB2 on - echo ok, 0x00 on, 0x08 on` |
| power off, verified | `USB2 off - echo ok, 0x00 off, 0x08 off` |
| data on, verified | `USB2 data on - echo ok, 0x08 on` |
| data off, verified | `USB2 data off - echo ok, 0x08 off` |
| echo mismatch | `USB2 off - echo differs, not applied` |
| readback mismatch | `USB2 off - state differs (0x00 on)` |
| rejection | `interlock - 0x01 rejected` |
| link failure | `USB2 off - no reply, link lost` |
| data while off | `USB2 data needs power - key ignored` |

`USBn` is the result-line abbreviation for `USB PORT n`. A readback mismatch is
a device-state result, never a link failure, and never a reason to reconnect.
`last` holds the most recent result only and is not cleared by navigation.

## 7. Tokens

No background is set. The canvas is the terminal's own. Colour appears only on
state values.

| Token | 256 | 8-colour | Use |
| --- | ---: | --- | --- |
| text | default | default | labels, measurements |
| dim | 244 + faint | 90 | off, `-`, `?`, residual, `GLOBAL MENU`, disabled rows |
| ok | 78 | 32 | power ON, data on, live |
| warn | 220 | 33 | stale, interlock, no device |
| err | 203 | 31 | lost, failed write |
| rail | 240 | 90 | the two rails |
| bar | bold + reverse (`SGR 1;7`) | same | header, footer |
| selection | bold + reverse (`SGR 1;7`) | same | selected port or menu item |

Selection is a bold reverse fill across the item text: for a port row, from the
label through the current cell; for a menu or Device row, the label plus one
trailing space. It is the only selection cue and it survives `NO_COLOR`, because
it uses reverse video, not colour.

With `NO_COLOR` or `TERM=dumb`, emit no SGR colour; keep bold, faint and
reverse. With a non-UTF-8 locale, replace `│` with `|`.

## 8. Renderer rules

Unchanged from UI-DASH-001: alternate screen, hidden cursor, one write per
frame, redraw only on a key, a snapshot change or a resize, `ioctl` size on every
frame boundary, raw fd read with `select(..., 50 ms)`, terminal restored in
`finally` and on SIGTERM/SIGHUP. One extra redraw every 0.5 s keeps
`stale <age> s` and the retry countdown moving between device replies.

The header and footer bars are one `bold + reverse` span each. Every line is
padded with spaces to exactly `width`; the rails are written at columns 4 and
`W-4`. The menu block overwrites only rows 5..H-2, so the page chrome is
untouched.

Only the four arrow keys decode as arrows. A lone `Esc` keypress is `escape`.
Any other escape sequence, such as `Delete`, `Home`, `F1` or an Alt chord, is
ignored, so an unrecognised key can never quit the app or write a port.

Widths count one code point as one column. A wide glyph in the product name or
in a `--port` path would widen the line and wrap it. Both are ASCII on the
supported hardware; the case is unverified.

## 9. Out of scope

The port detail page is read-only in v1. The monitor and advanced controls that
fill rows 11 and 12 come later. No downstream device is configured, reset or
opened; only its identity is read from sysfs. No mouse, no scrolling lists, no port names or aliases, no downstream
device map, no persistent settings writes, no reset or firmware update, no V2/V3
streaming, no interlock control.

## 10. Verification

| Clause | Method | Where |
| --- | --- | --- |
| Frame: rails at 4 and `W-4`, bars on rows 1 and `H`, `last` on `H-1` | pure `render()` assertions | host |
| Every line exactly `width` visible columns, 60x16 to 200x60, at 60, 80, 120, 200 | render sweep | host |
| Port rows use the fixed columns, one per probed port, 1..7 | render at 4 and 7 ports | host |
| Selection is one reverse-video row on ports and in the menu, survives `NO_COLOR` | assert `SGR 7` on exactly one row | host |
| `m` replaces the port rows with the menu, keeps header, status, `last`, footer | render assertion | host |
| Enter opens the selected port detail with four labelled fields; Enter, q, Esc and m return | render and TUI assertions | host |
| Port detail shows the downstream device only with data on and a matching sysfs child | render, usbmap and TUI assertions | host |
| `m`, `Esc` and `q` close the menu and never quit | TUI loop with a fake controller | host |
| Menu items `Device`, `Settings` and `Help`; `j`/`k` wrap and Enter opens the selection | menu and TUI assertions | host |
| Help shows the package version and the key list; Enter, q, Esc and m return | render and TUI assertions | host |
| Enter on a port does nothing; Enter opens Device from the menu; Enter returns from Device | TUI loop | host |
| Space and `d` write on the control page; the guard is per key; Enter never writes | TUI loop | host |
| Power-off port: data cell `-`, data write refused with a `last` note | render and loop assertions | host |
| STALE and LOST dim values, `?` fields, `r retry` | render assertion | host |
| Interlock banner on row 4 and the banner names CH1 | render assertion | host |
| No device: message block, no port rows, blank `last`, menu still opens | render assertion | host |
| `last` text fits 40 columns; a long result clips without splitting SGR | render assertion | host |
| Every result string in section 6 is produced by the controller | controller tests | host |
| Terminal restored after q, Ctrl-C, SIGTERM | pty run | host |
| Switches show a truthful `last` line | switch a free port on the unit | on target |
| Visual quality | review against the mockup | human |

A visual row is a review, not a test. Everything else has a named check.
