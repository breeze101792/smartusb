# HW-SPEC-001 — SmartUSBHub Pro 4CH USB2.0

| Field | Value |
| --- | --- |
| Document | HW-SPEC-001 |
| Status | Draft — verified in part (see [HW-VER-001](./verification.md)) |
| Device | SmartUSBHub Pro 4CH USB2.0 |
| Order codes | `HBP_USB2_4CH`, `HBP_USB2_4CH_PSU` |
| Vendor docs | Datasheet v1.0 (2026-07-23), User guide v1.0 |
| Written | 2026-11-07 |

This is the hardware truth the control software is built against. It is not a
software design. Byte-level protocol framing is deferred to
`contracts/protocols.md` when the control code is designed.

**Evidence tags used throughout**

| Tag | Meaning |
| --- | --- |
| `OBS` | Observed on this host, 2026-11-07 — see [verification.md](./verification.md) |
| `DOC` | Stated in the vendor datasheet or user guide |
| `PROTO` | Stated in the vendor communication protocol document |
| `SDK` | Present only in the vendor SDK source, not in the public protocol document |
| `INF` | Derived from the above by reasoning; not directly stated |
| `UNK` | Not established — see [verification.md](./verification.md) |

Vendor source paths (read-only copy):
`reference/smartusbhub/docs/products/usb2_4p/datasheet.md`,
`reference/smartusbhub/docs/products/usb2_4p/user_guide.md`,
`reference/smartusbhub/docs/protocol.md`,
`reference/smartusbhub/smartusbhub.py`.

## 1. Model and variants

| Variant | Order code | Included adapter | Difference |
| --- | --- | --- | --- |
| Standard | `HBP_USB2_4CH` | None | — |
| Adapter bundle | `HBP_USB2_4CH_PSU` | 5 V / 2 A | Same unit plus supply |

Both variants are identical in function. Firmware identity across the two order
codes is an assumption, not a verified fact. There is no measurement variant:
voltage/current sensing is fitted to every unit (`DOC` datasheet §1.1).

## 2. Architecture

Three independent planes share one enclosure. Only the MCU bridges them.

```
CONTROL PLANE
  host ──USB-C CMD──> USB CDC ──frames──> MCU / port control
                                              │
DATA PLANE                                    │ drives
  host ──USB-C DATA──> 4-port USB2 MTT hub ──┐│
                                             ││
                       CH1..CH4 USB-A <── USB2 data switch ×4
                       CH1..CH4 USB-A <── VBUS switch ×4 <── common 5 V bus

POWER PLANE
  DATA ──one-way diode + 4 A fuse──┐
  CMD  ──one-way diode + 4 A fuse──┼──> common 5 V bus ──> VBUS switch ──> resettable fuse ──> CHn VBUS
  AUX  ──direct, no protection ────┘                            (×4)

  MCU also drives: status LED, channel LEDs ×4, channel buttons ×4 (read)
```

Compiled from Figure 2-1, datasheet §3.2 and §5. The vendor figure draws a
single power-switch block and does not draw the per-port fuse, LEDs or buttons;
per-channel switching and the per-port fuse come from the datasheet text.

The DATA and CMD ports are separate USB connections. Controlling the hub and
carrying downstream traffic need both (`DOC` user guide §5.3).

The four downstream ports sit behind a USB 2.0 hub with one independent
transaction translator per port (MTT) (`DOC` datasheet §3.1).

`OBS` The DATA-side hub enumerates on this host as `1a86:8091`, four
downstream ports, 480 Mbps, self-powered, `bcdDevice 17.10`. No downstream
device was attached at observation time.

## 3. Interfaces

| Interface | Qty | Connector | Function |
| --- | ---: | --- | --- |
| CMD | 1 | USB-C | Control link; enumerates as USB CDC serial |
| USB 2.0 DATA upstream | 1 | USB-C | Carries downstream USB traffic to the host |
| AUX POWER | 1 | USB-C | Regulated 5 V DC input only |
| Downstream ports | 4 | USB-A | CH1–CH4, independently switched VBUS and D+/D− |
| Channel buttons | 4 | — | Short press toggles VBUS on the matching channel |
| Channel LEDs | 4 | — | On when that channel's VBUS is enabled |
| Status LED | 1 | — | Run, identify, and command-activity indication |

## 4. Power

### 4.1 Inputs

| Input | Path protection | Current limit | Notes |
| --- | --- | ---: | --- |
| DATA USB-C | One-way diode + 4 A fuse, reverse-current/OVP/OCP (`DOC`) | Host port; 4 A path fuse | Feeds the common 5 V bus |
| CMD USB-C | One-way diode + 4 A fuse, reverse-current/OVP/OCP (`DOC`) | Host port; 4 A path fuse | Feeds the common 5 V bus |
| AUX USB-C | **None onboard** (Figure 2-1: "DIRECT · NO PROTECTION"; datasheet §5 says no independent OCP) | 5 A Type-C connector rating, not a protective limit | External supply must current-limit and survive a short |
| Total, all inputs | — | **< 10 A** (`DOC`) | `I_total = I_DATA + I_CMD + I_AUX` |

`INF` A USB 2.0 Standard-A host port supplies at most 500 mA. A USB-C host can
advertise 1.5 A or 3 A at 5 V over CC without PD, so the host-side inputs are
not hard-bounded at 500 mA. This comes from the USB specification, not the
vendor documents.

### 4.2 Voltage

| Parameter | Min | Typ | Max | Unit | Source |
| --- | ---: | ---: | ---: | --- | --- |
| Recommended input | 4.75 | 5.00 | 5.25 | V | `DOC` §4 |
| Absolute maximum, any input | 0 | — | **5.5** | V | `DOC` §4 |
| Downstream VBUS, no overload | 4.5 | 5.0 | 5.5 | V | `DOC` §4 |

Only regulated 5 V DC may be applied. PD triggers, boost cables and 9/12/15/20 V
supplies destroy the unit (`DOC` §4, user guide §2.2).

### 4.3 Output path

| Parameter | Value | Source |
| --- | ---: | --- |
| Per-channel output-path capability | 4 A | `DOC` §3.3 |
| USB BC 1.2 CDP charging current | ≤ 1.5 A per port | `DOC` §3.3 |
| Fast charging | No QC, no USB PD | `DOC` §3.3 |
| Per-port protection | Resettable fuse | `DOC` §5 |
| Included adapter (`_PSU` only) | 5 V / 2 A, shared by all four ports | `DOC` §1.1 |

The 4 A figure is path capability, not a guaranteed charging current. A load of
four ports at 1.5 A each draws about 6 A, which the included 2 A adapter cannot
supply (`DOC` §4).

## 5. Channel switching

### 5.1 Independent control

VBUS and the USB 2.0 D+/D− pair are switched independently per channel. That
yields three documented operating states:

| VBUS | D+/D− | Effect | Typical use |
| --- | --- | --- | --- |
| On | Connected | Powered and enumerated | Normal operation |
| On | Disconnected | Powered, off the USB bus | Simulate a data-only unplug |
| Off | Auto-disconnected | Full unplug | Power-cycle reset |

`DOC` user guide §7.1. Turning VBUS off disconnects the data line in all modes
(`DOC` user guide §7.1; restated for interlock in `PROTO` CMD 0x02). Whether the
next power-on reconnects it, or the data switch keeps its last state, is not
documented and the sources disagree — see `UNK-013`. The reverse case —
D+/D− connected while VBUS is off — is also undocumented; see `UNK-004`.

`OBS` Turning CH4 VBUS off made `0x08` read off: the firmware auto-disconnects
D+/D− on power-off.

### 5.2 Interlock mode

In interlock mode only one channel may be powered (`PROTO` CMD 0x02):

- The ordinary power command `0x01` has no effect.
- A rejected `0x01` is answered with `55 5A 01 FF FF FF`.
- Channel selection uses command `0x02`.
- Turning the selected channel off also disconnects its data line.

`SDK` and `PROTO` disagree on how to release all channels; see `UNK-005`.

### 5.3 Defaults and restore

At power-up the channel state is decided in this order (`PROTO` CMD 0x0B):

1. If a power-on default is enabled for the channel, apply it.
2. Else, if power-loss state restore is enabled, restore the pre-loss state.
3. Else all channels come up OFF.

Factory defaults (`PROTO` notes for CMD 0x09, 0x0B, 0x0D, 0x11; user guide App. A):

| Setting | Factory value |
| --- | --- |
| Channel power | OFF |
| Channel data line | Connected |
| Operating mode | Normal |
| Power-loss restore | Disabled |
| Button control | Enabled |
| Device address | `0x0000` |

## 6. Measurement

Sensing hardware is present on every 4CH unit (`DOC` datasheet §1.1).

| Quantity | Range | Resolution | Accuracy |
| --- | --- | ---: | --- |
| VBUS voltage | 0–5.5 V per channel | 1.48 mV | ±(0.91% × reading + 36 mV) |
| Output current | 0–4.0 A per channel | 1.15 mA | ±(2.5% × reading + 50 mA) |

`DOC` datasheet §3.4.

Wire encoding, from the sources that define it:

| Path | Encoding | Endianness | Source |
| --- | --- | --- | --- |
| `0x03` voltage reply | 16-bit unsigned, mV | Big-endian | `PROTO` CMD 0x03 |
| `0x04` current reply | 16-bit unsigned, mA | Big-endian | `PROTO` CMD 0x04 |
| `0x1A` batch/stream | 16-bit unsigned, mV and mA per channel | Little-endian | `SDK` `smartusbhub.py:1521-1522` |

Two contradictions must not be carried into the software by accident:

- The protocol document's prose says resolution is 0.1 V / 0.1 A, while the
  datasheet and the wire format use mV / mA (`PROTO` CMD 0x03, 0x04).
- V2 is a frame size, not a data type. Only `0x03` and `0x04` carry a big-endian
  16-bit value. `0x0B`–`0x0E` are also 7-byte V2 frames, but their two payload
  bytes are independent 8-bit `enable` and `value` fields; parsing them as
  big-endian 16-bit yields nonsense. V3 measurement fields are little-endian.
  Decode per command.

A channel that is off can still read a few millivolts. Vendor examples show
8–12 mV with the channel OFF (`PROTO` CMD 0x03). No source states whether the
off-state switch blocks reverse current from a self-powered device, so a
nonzero reading may be offset or backfeed. Software must read the power state
with `0x00` and must not infer it from a voltage reading.

`OBS` On this unit: CH4 on with a PCM2902 speaker read 4614 mV and 0 mA at idle;
after switching off it read 202 mV and 0 mA. An off channel is not at 0 V, and
an idle current below the accuracy floor reads as 0 mA.

Readings are for observation and troubleshooting, not metrology (`DOC` user
guide §7.5).

## 7. Indicators and buttons

| Control | Action | Result |
| --- | --- | --- |
| Button 1–4 | Short press | Toggle VBUS on that channel |
| Button 1 | Hold 3 s | Toggle Normal / Interlock (retained) |
| Button 1 | Hold 6 s | Factory reset |
| Button 1 | Hold while powering on | Enter firmware-upgrade mode |
| Button 2 | Hold 3 s | Enable/disable power-loss restore (default off) |

`DOC` user guide App. A.

| LED | Pattern | Meaning |
| --- | --- | --- |
| Status | On 100 ms / off 900 ms | Normal operation |
| Status | 80 ms toggle for ~10 s | Identify command |
| Status | Single toggle | Command received and processed |
| Channel | On / off | VBUS enabled / disabled on that channel |

The user guide gives 100 ms on / 900 ms off for normal operation. The protocol's
CMD 0x06 note gives 0.5 s on/off for normal and 0.25 s for interlock. The sources
conflict; the pattern is cosmetic and no control logic may depend on it
(`UNK-014`).

Channel power, operating mode, defaults, restore, button control, address and
factory reset are also command-settable. Firmware-upgrade mode is entered only
by holding Button 1 while powering on; the public command set has no upgrade
command. LED patterns are not command-settable. The buttons are the fallback
when no host is attached (`DOC` user guide §7).

## 8. USB data path

| Parameter | Value |
| --- | --- |
| Standard | USB 2.0 High-Speed |
| Maximum link rate | 480 Mbps |
| Compatible speeds | Full-Speed 12 Mbps, Low-Speed 1.5 Mbps, USB 1.1 |
| Hub architecture | MTT, one independent TT per downstream port |
| Upstream | 1 × USB-C |
| Downstream | 4 × USB-A |

`DOC` datasheet §3.1. The downstream ports are USB-A; there is no USB-C
downstream port and no USB 3 path.

## 9. Control interface (CMD)

| Parameter | Value | Source |
| --- | --- | --- |
| Physical | USB-C | `DOC` §2.2 |
| Device class | USB CDC serial; the ACM subclass is inferred from `/dev/ttyACM*` | `DOC` §2.2; `INF` |
| Host device name | `/dev/ttyACM*` Linux, `/dev/cu.usbmodem*` macOS, `COMx` Windows | `PROTO` |
| VID:PID | `1A86:FE0C` | `SDK`; `OBS` |
| Baud rate | 115200 default; protocol states a 115200–921600 range; how the rate is selected is undocumented | `PROTO`; `UNK-012` |
| Framing | 8 data bits, no parity, 1 stop bit | `PROTO` |
| Model | Request/response plus unsolicited reports and stream frames | `PROTO`; `SDK` |

`OBS` 2026-11-07 22:33: the CMD port enumerated as `1a86:fe0c` at `3-3.2`,
node `/dev/ttyACM0`, by-id `usb-makerlabtools_SmartUSBHub_2B22BDDFC176ABCD-if00`.
Identity: hardware V1.3, firmware V2.0, product `0x00`, 4 channels, address
`0x0000`, normal mode, buttons enabled, restore disabled.

Protocol facts that constrain any control implementation:

- Three frame families share the link: V1 (6 bytes), V2 (7 bytes), V3
  (10 + payload bytes, maximum 64 bytes total) (`PROTO`).
- Frames with a bad format or an unsupported command get no reply (`PROTO`).
- The link is not purely request/response. A button press sends an unsolicited
  `0x00` status report for that channel (`PROTO` line 107). V3 frames whose
  `FLAGS` carry `STREAM` are unsolicited and are not acknowledged (`PROTO`
  §Frame format). A receiver must never bind a reply by command code alone.
- A multi-channel query returns one reply frame per channel, not an aggregate
  frame (`PROTO` CMD 0x00, 0x08; `SDK` `smartusbhub.py:1222-1250`). For `0x03`
  and `0x04` the vendor documents only single-channel queries; whether a mask
  works is `UNK-015`.
- The vendor SDK uses a 100 ms ACK timeout and a 1 ms minimum interval between
  writes (`SDK` `smartusbhub.py:169-231`, `:749-755`). These are SDK tuning
  values, not documented device limits. The SDK notes a ~2.5 ms physical
  round-trip floor.
- These commands exist only in the SDK, not in the public protocol document:
  V3-framed `0x1A` measurements and stream, `0x1E`/`0x1F` channel names,
  `0x20`/`0x21` alias, and the payload stage of `0xF9` serial number;
  V1-framed `0x1B`/`0x1C` overcurrent, `0x1D` identify, `0xF0` product type,
  `0xF1` max channels, `0xF7` reboot, and the ACK stage of `0xF9`
  (`SDK` `smartusbhub.py:97-136`, `:2582`, `:1605-1611`).
- `OBS` Firmware V2.0 replies `55 5A FD 02 00 ...`: the major version is in
  `CHANNEL`, the minor in `VALUE`.
- The SDK's product table lists no overcurrent capability for this model
  (`SDK` `smartusbhub.py:169-179`), but the SDK does not gate its overcurrent
  methods either. Whether the hardware reports overcurrent is `INF` at best —
  see `UNK-006`.

The 4CH command set that is documented publicly is `0x00`–`0x12`, `0xFC`–`0xFE`
(`PROTO`). The SDK adds the commands listed above.

## 10. Mechanical and environmental

| Parameter | Value |
| --- | --- |
| Dimensions | 106 mm × 46 mm × 18 mm |
| Weight | 52 g |
| Enclosure | PMMA |
| Mounting | Stacked mounting with standoffs |
| Operating temperature | 0–50 °C, non-condensing |
| Storage temperature | −10–85 °C, non-condensing |

`DOC` datasheet §6.

## 11. Constraints the control software must honour

Each item is testable against the implementation.

| ID | Constraint | Why |
| --- | --- | --- |
| HW-C-001 | Address only CH1–CH4. Never build a mask above `0x0F`. | Four channels only (`DOC` §3.2) |
| HW-C-002 | In interlock mode use `0x02` for power; treat `55 5A 01 FF FF FF` as a rejection, not a success. | `0x01` is ignored in interlock (`PROTO` CMD 0x02) |
| HW-C-003 | Do not wait for a reply to every frame. Invalid and unsupported frames are silent. | `PROTO` note |
| HW-C-004 | Handle one reply frame per channel for multi-channel queries; for `0x03`/`0x04` do not assume a mask is accepted until `UNK-015` is closed. | `PROTO` CMD 0x00, 0x08; `SDK` |
| HW-C-005 | Treat measurement replies as unsigned mV and mA. Never apply the protocol prose's 0.1 V / 0.1 A scaling. | Datasheet §3.4 vs `PROTO` |
| HW-C-006 | Decode per command: `0x03`/`0x04` are big-endian 16-bit; `0x0B`–`0x0E` are two independent 8-bit fields; V3 measurement fields are little-endian. | `PROTO` CMD 0x03, 0x04, 0x0B–0x0E; `SDK` |
| HW-C-007 | Read power state with `0x00`; never infer it from a voltage reading, which may be offset or backfeed. | Off CH4 read 202 mV; on read 4614 mV |
| HW-C-008 | Discover the control port by `1A86:FE0C`, then probe identity before control. Do not match the DATA hub `1A86:8091`. | `SDK` `:938`; `OBS` |
| HW-C-009 | Never select a device by address alone until its address is known to be unique. Factory default is `0x0000`. | `PROTO` CMD 0x11 |
| HW-C-010 | Expose no overcurrent API for this model unless a probe proves otherwise. | `INF` from SDK product table; `UNK-006` |
| HW-C-011 | Switching VBUS or D+/D− is an unplug event; require explicit caller intent and never do it implicitly. | `DOC` §5; user guide §2.2 |
| HW-C-012 | Do not assume D+/D− state is meaningful while VBUS is off, and do not assume power-on reconnects it. Read `0x08` after any transition. | `UNK-004`, `UNK-013` |
| HW-C-013 | Keep the CMD link alive during firmware update; the firmware-update path is not part of normal control. | user guide §9.3 |
| HW-C-014 | Never bind a reply by command code alone. `0x00` arrives unsolicited on button presses, and V3 stream frames are unsolicited. | `PROTO` line 107; V3 `FLAGS` |
| HW-C-015 | Treat mode, button control, defaults, restore, address and factory reset as persistent NVM writes. Record and restore the original values; never change them as a side effect of ordinary control. | `PROTO` notes; `UNK` if the unit differs |

## 12. Open questions

Tracked with IDs in [verification.md](./verification.md). Nothing in this spec
is to be treated as settled where that file says `UNK`.
