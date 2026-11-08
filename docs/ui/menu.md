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
| Left rail `│` | 1 | every row |
| Right rail `│` | `W` | every row |
| Header bar | 2..`W-1` | 1 |
| Footer bar | 2..`W-1` | `H` |
| Status line | 5 | 3 |
| Interlock banner | 5 | 4 |
| List, first row | 5 | 5 |
| `last` label | 5 | `H-1` |
| `last` text | 13 | `H-1` |

Header: left title at column 2. Right: the status badge `" " + state + " "`,
right-aligned so its last character is at `W-2`, with one bar cell at `W-1`
before the rail. Fill between with the bar.

Port row columns are responsive. The label sits at column 5 with its 12-column
cell. The five value cells keep their widths (4, 8, 9, 7, 6) and are spread from
column 17 to the last usable column with an equal gap, never less than two
spaces. At 80 columns that puts power at 17, data at 27, voltage at 41, current
at 57 and watts at 71, with three spaces before the rail. At 60 columns the
label moves to 4, the gaps compress to two spaces, and two columns stay clear
before the rail.

Label and value pages, the port detail, Device, Settings and the policy page,
put the label at the left padding and right-align the value three columns
before the rail, two at the minimum width.

The left and right padding inside the rails are equal: three columns at width
72 and above, two below. The header, footer, status line, `last` line and every
page follow the same padding.

At 80x24, control page, LIVE:

```
│HUBCTL  USB CONTROL                                                     live  │
│                                                                              │
│   port /dev/ttyACM0   normal   live   poll 1.0 s                             │
│                                                                              │
│   USB PORT 1  ON        data on       4.61 V         0.00 A       0.00 W     │
│   USB PORT 2  off       -             (202 mV)       0.00 A       0.00 W     │
│   USB PORT 3  ON        data off      5.02 V         0.21 A       1.05 W     │
│   USB PORT 4  ON        data on       4.88 V         0.44 A       2.15 W     │
   ...
│   last    USB2 off - echo ok, 0x00 off, 0x08 off                             │
│SPACE power   d data   a auto   p pause   q quit                              │
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

Footer: `SPACE power   d data   a auto   p pause   q quit`. On LOST it becomes
`r retry   a auto   p pause   q quit`; the no-device footer is the same.

`Enter` opens the selected port's detail page. `a` opens the selected port's
policy page and `p` pauses or resumes automation.

An enabled policy marks its port row with `A` at column 3. The status line ends
with `auto <n>` when at least one port has an enabled policy, `auto paused`, or
`auto off - poll too long` above a 1 s poll. With no enabled policy, no pause and
a normal poll, the field is omitted. At 60 columns the status drops
`poll <n> s` first; it never drops the auto field.

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

Labels at column 5, values right-aligned at the rail, in the same tokens as the
port row.
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

v1 has four items: `Device`, `Auto`, `Settings` and `Help`. Later global
actions append here. The selected item is the only reverse-video row. `j` and `k` wrap between
items.

Footer: `ENTER open   m close   q close`. `m`, `Esc` and `q` close the menu and
return to the list with the same port selected. Closing the menu never quits.

At 80x24 with the menu open:

```
│HUBCTL  USB CONTROL                                                     live  │
│                                                                              │
│   port /dev/ttyACM0   normal   live   poll 1.0 s                             │
│                                                                              │
│   GLOBAL MENU                                                                │
│   Device                                                                     │
│   Auto                                                                       │
│   Settings                                                                   │
│   Help                                                                       │
   ...
│   last    USB2 off - echo ok, 0x00 off, 0x08 off                             │
│ENTER open   m close   q close                                                │
```

### 3.4 Settings

Header title `HUBCTL  SETTINGS`. Status line:
`port <port>   1a86:fe0c   <link>`.

| Row | Setting | Values |
| --- | --- | --- |
| 5 | `port` | `auto` or a discovered endpoint, including the current one |
| 6 | `poll` | `0.5 s`, `1.0 s`, `2.0 s`, `5.0 s` |

Labels at column 5, values right-aligned at the rail. `j` and `k` select a row; `Left` and
`Right` step the value and wrap. `Back` is at row 13, selected.

Footer: `LEFT/RIGHT change   ENTER back   q back`. `Enter`, `q`, `Esc` and `m`
return to the control page.

Changing `port` closes the link, clears the identity and reopens at the new
endpoint, or by discovery for `auto`. Changing `poll` takes effect on the next
cycle. Both write a result to the `last` line, which stays visible below the
settings.

### 3.5 Port policy

Header title `HUBCTL  AUTO - USB PORT n`, for the port selected on the control
page. `a` on the control page opens it, and the menu's `Auto` item opens it for
the same selected port. Status line as on the control page.

| Row | Setting | Values |
| --- | --- | --- |
| 5 | `enabled` | `off`, `on` |
| 6 | `cycle` | `off`, `1`, `5`, `10`, `30`, `60 min` |
| 7 | `overcurrent` | `off`, `0.5`, `1.0`, `1.5`, `2.0 A` |
| 8 | `retry` | `off`, `10`, `30`, `60 s` |
| 9 | `recovery` | `off`, `1`, `5`, `10 min` |
| 10 | `schedule` | `off`, `on` |
| 11 | `from` | `00`..`23`, wraps; `--` while the schedule is off |
| 12 | `to` | `00`..`23`, wraps; `--` while the schedule is off |
| 13 | `Back` | |

Row 14 is a dim line: `rules clear when hubctl exits`.

`j`/`k` select a row; `Left`/`Right` step the value and wrap. Values are stored
even while `enabled` is off. `Back` is at row 13.

Footer: `LEFT/RIGHT change   p pause   ENTER back   q back`. `Enter`, `q` and
`Esc` return to the control page; `m` also returns to control. `p` pauses or
resumes automation.

The rules and their priority are in
[ARCH-002 §4](../architecture/policy.md).

### 3.6 Device

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

### 3.7 Help

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

Keys are at column 5 in an 8-column cell, the description at column 13.
`Enter`, `q`, `Esc` and `m` return to the control page. Footer:
`ENTER back   q back`. The `last` line stays on row `H-1`.

### 3.8 No device

Control page with no identity:

| Row | Content |
| --- | --- |
| 3 | `discovery 1a86:fe0c   no port   retry <n> s` |
| 5 | `no SmartUSBHub CMD port` in warn |
| 6 | `connect the CMD USB-C port, or pass --port /dev/ttyACM0.` in dim |
| 8 | no port rows |

The `last` row is blank. The menu still opens with `Device`, `Auto`, `Settings`
and `Help`; Device fields all read `?`. `a` does nothing without a port, so there
is nothing to configure until the device connects.

## 4. States

| State | Badge | Rows | Writes | Footer |
| --- | --- | --- | --- | --- |
| LIVE | `live` ok | full colour | allowed | normal |
| STALE | `stale <age> s` warn | values dim | refused | normal |
| LOST | `lost - retry <n> s` err | every field `?`, dim | refused | `r retry   a auto   p pause   q quit` |
| INTERLOCK | `interlock` warn | banner on row 4, values live | refused | normal |
| NO DEVICE | `no device` warn | message block only | none | `r retry   a auto   p pause   q quit` |

A refused write still reaches the controller, which writes the reason to
`last`. The page never invents a refusal of its own. A single late poll is
STALE, not LOST. In LOST the port selection stays visible and the menu stays
reachable, so `Quit` and `Device` are never lost.

The interlock banner is one line, naming the physical button on the unit:
`! interlock - switching disabled. Hold CH1 3 s, then r.`

## 5. Keys

| Key | Control | Port policy | Port detail | Global menu | Settings | Device | Help |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `j`, `Down` | next port | next row | none | next item | next setting | none | none |
| `k`, `Up` | previous port | previous row | none | previous item | previous setting | none | none |
| `Left`, `Right` | none | step the value | none | none | step the value | none | none |
| `Enter` | open port detail | back | back | open item | back | back | back |
| `a` | open the selected port's policy | none | none | none | none | none | none |
| `p` | pause automation | pause automation | none | none | none | none | none |
| `Space` | toggle VBUS on the selected port | none | none | none | none | none | none | none |
| `d` | toggle D+/D- on the selected port | none | none | none | none | none | none | none |
| `m` | open menu | back to control | back to control | back to control | close | back to control | back to control | back to control |
| `r` | poll now | poll now | poll now | poll now | poll now | poll now | poll now | poll now |
| `q`, `Esc` | quit | back | back to the list | back | close | back | back | back |
| `Ctrl-C` | quit | quit | quit | quit | quit | quit | quit | quit |

The 0.4 s guard is per key, and every event of a guarded key refreshes its
timestamp, including a dropped one. Holding a key acts at most once when
autorepeat begins and then stays silent until it is released. Only `Space` and
`d` write. `Enter` never writes; on the control page it opens the port detail.

## 6. The `last` line

Every write ends here with what actually happened. The text must fit the
columns between column 13 and the right rail at 60 columns; longer text is
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

Automated writes use the same form and name the rule, for example
`USB2 off - auto overcurrent 1.62 A` and `USB2 on - auto cycle`. The full table
is in [ARCH-002 §6](../architecture/policy.md).

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

Selection is a bold reverse fill across the item: for a port row, from the label
through the watt cell; for a menu row, the label plus one trailing space; for a
label and value row, the full interior of the frame. It is the only selection cue and it survives `NO_COLOR`, because
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
padded with spaces to exactly `width`; the rails are written at columns 1 and
`W`. The menu block overwrites only rows 5..H-2, so the page chrome is
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
| Frame: rails at 1 and `W`, bars on rows 1 and `H`, `last` on `H-1` | pure `render()` assertions | host |
| Every line exactly `width` visible columns, 60x16 to 200x60, at 60, 80, 120, 200 | render sweep | host |
| Port rows use the spread columns, one per probed port, 1..7 | render at 4 and 7 ports | host |
| Selection is one reverse-video row on ports and in the menu, survives `NO_COLOR` | assert `SGR 7` on exactly one row | host |
| `m` replaces the port rows with the menu, keeps header, status, `last`, footer | render assertion | host |
| Enter opens the selected port detail with four labelled fields; Enter, q, Esc and m return | render and TUI assertions | host |
| Port detail shows the downstream device only with data on and a matching sysfs child | render, usbmap and TUI assertions | host |
| `m`, `Esc` and `q` close the menu and never quit | TUI loop with a fake controller | host |
| Menu items are `Device`, `Auto`, `Settings` and `Help`. The list is only the four ports. | menu and TUI assertions | host |
| Help shows the package version and the key list; Enter, q, Esc and m return | render and TUI assertions | host |
| Enter on a port opens its detail; Enter opens the selected menu item; q/Esc/Enter return | TUI loop | host |
| The port policy page renders and steps every value, for the selected port | render and TUI assertions | host |
| `A` markers, `auto <n>` and `auto paused` follow the policy state | render assertions | host |
| A rule fires only on a LIVE link in normal mode, never while paused or in the manual hold | pure `decide()` assertions | host |
| Priority: overcurrent, recovery, cycle, schedule, pending on | pure truth table | host |
| One automated write per poll and no replay after reconnect | controller with a fake clock | host |
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
