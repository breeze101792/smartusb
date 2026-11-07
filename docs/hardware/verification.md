# HW-VER-001 — 4CH hardware verification and open questions

| Field | Value |
| --- | --- |
| Document | HW-VER-001 |
| Status | CMD link verified; first control test passed |
| Applies to | HW-SPEC-001, unit on this host |
| Date | 2026-11-07 |

This file records what is actually established about the unit, what is only
documented, and what must still be confirmed on the target. A spec line backed
by an `UNK` here is not settled.

## 1. Evidence log

Host: Arch Linux, kernel 7.2.14. Unit connected 2026-11-07 22:00:36.

### 1.1 What enumerated

```
Bus 003 Device 033: ID 1a86:8091 QinHeng Electronics USB HUB
```

| Property | Value | Source |
| --- | --- | --- |
| sysfs path | `/sys/bus/usb/devices/3-3.4` | `lsusb -t` |
| VID:PID | `1a86:8091` | sysfs `idVendor`/`idProduct` |
| Product string | `USB HUB` | sysfs `product` |
| Device class | `09` (hub), one interface | sysfs `bDeviceClass`, `bNumInterfaces` |
| Downstream ports | 4 (`maxchild=4`) | sysfs `maxchild` |
| Speed | 480 Mbps (`version 2.00`) | sysfs `speed`, `version` |
| Self-powered | `bmAttributes=0xE0` (bit 6 set) | sysfs `bmAttributes` |
| Bus power request | 100 mA | sysfs `bMaxPower` |
| Device release | `bcdDevice 17.10` | sysfs `bcdDevice` |
| Ports 1–4 | all empty | sysfs `3-3.4-port1..4` |

This is the DATA-side hub. It matches the documented four-port USB 2.0 MTT hub
(`DOC` datasheet §3.1).

### 1.2 Control link

At 22:00 only the DATA hub was present; no CMD device existed. At 22:33 the CMD
port enumerated and answered the identity queries.

| Property | Value |
| --- | --- |
| USB device | Bus 003 Device 036: `1a86:fe0c` QinHeng Electronics SmartUSBHub |
| sysfs path | `3-3.2` |
| Device node | `/dev/ttyACM0` |
| Stable by-id | `usb-makerlabtools_SmartUSBHub_2B22BDDFC176ABCD-if00` |
| Hardware version | V1.3 (raw 3) |
| Firmware version | V2.0 (raw `02 00`) |
| Product type | `0x00`, HBP_USB2_4CH |
| Max channels | 4 |
| Device address | `0x0000` |
| Operate mode | normal |
| Button control | enabled |
| Power-loss restore | disabled |

Read-only channel state at 22:33: CH1–CH3 off, data on, 0 mV, 0 mA. CH4 on,
data on, 4614 mV, 0 mA. The C-Media PCM2902 (`08bb:2902`, "USB PnP Sound
Device", bus-powered, 100 mA) was enumerated at `3-3.4.4` = **CH4**, ALSA card 5.

### 1.3 First control test

CH4 was switched off with `55 5A 01 08 00 09` (`0x01`, mask `0x08`, value `0`).
The tool read back power off and left the channel off.

| Observation | Result |
| --- | --- |
| Power readback | off |
| Data readback | off — firmware auto-disconnected D+/D− |
| CH4 voltage | 4614 mV → 202 mV |
| Speaker | disappeared from `lsusb` and ALSA |
| CH1–CH3 | unchanged, off |
| `--map` | no downstream devices |

This confirms independent per-channel VBUS control and the power-off data
auto-disconnect. It also confirms that an off channel can still read a nonzero
voltage (202 mV), so state must come from `0x00`, not from the ADC.

### 1.4 Not verifiable from available sources

No schematic, PCB or EDA data is available. The following are not established
and are not software-relevant today, except where they set the limits in
HW-SPEC-001:

- the OVP element and topology on the DATA and CMD paths;
- input fuse trip curves;
- per-port resettable-fuse hold and trip currents;
- inrush behaviour and input sequencing;
- downstream switch reverse blocking;
- the MCU supply rail.

Do not infer any of these from the block diagram. It draws function, not parts.

## 2. Confirmation status

| Item | Class | Evidence |
| --- | --- | --- |
| Data-side hub is `1a86:8091`, 4 ports, 480 Mbps | `OBS` | §1.1 |
| Data-side hub is self-powered | `OBS` | `bmAttributes=0xE0` |
| CMD port is USB CDC serial at 115200 8N1 | `OBS`/`DOC` | §1.2, `/dev/ttyACM0` |
| CMD ACM subclass | `OBS` | `/dev/ttyACM0` bound |
| CMD VID:PID is `1a86:fe0c` | `OBS` | §1.2 |
| Hardware version V1.3 | `OBS` | §1.2 |
| Firmware version V2.0, major = CHANNEL, minor = VALUE | `OBS` | §1.2 |
| Product type `0x00`, 4 channels | `OBS` | §1.2 |
| CH4 controls the PCM2902 speaker | `OBS` | §1.3 |
| Power-off auto-disconnects D+/D− | `OBS` | §1.3 |
| An off channel can read 202 mV | `OBS` | §1.3 |
| 5 V only, 5.5 V absolute maximum | `DOC` | datasheet §4 |
| AUX POWER has no independent onboard overcurrent protection; Figure 2-1 calls the path unprotected | `DOC` | datasheet §5, Figure 2-1 |
| Per-port resettable fuse | `DOC` | datasheet §5 |
| Per-channel path rating 4 A, BC 1.2 1.5 A | `DOC` | datasheet §3.3 |
| Measurement range/resolution/accuracy | `DOC` | datasheet §3.4 |
| MTT, one TT per downstream port | `DOC` | datasheet §3.1 |
| Buttons and LED behaviour | `DOC` | user guide App. A |
| V1/V2/V3 frame layouts | `PROTO` | protocol §Frame format |
| Public command set `0x00`–`0x12`, `0xFC`–`0xFE` | `PROTO` | protocol |
| SDK-only commands: V3-framed `0x1A`, `0x1E`–`0x21`, `0xF9` payload; V1-framed `0x1B`–`0x1D`, `0xF0`, `0xF1`, `0xF7`, `0xF9` ACK | `SDK` only | `smartusbhub.py:97-136` |
| V3 measurement payload layout | `SDK` only | `smartusbhub.py:1492-1537` |
| V3 name/alias/serial payloads | `SDK` only | `smartusbhub.py:1613-1700` |
| Model has no overcurrent reporting | `INF` | product table lacks it |
| Device on CH4 is a C-Media PCM2902, bus-powered | `OBS` | `3-3.4.4`, `bmAttributes=0x80`, `bMaxPower=100mA` |
| CH4 VBUS is on | `INF` | A bus-powered device cannot enumerate otherwise |
| Speaker is on CH4 (`3-3.4.4`) | `OBS` | `scripts/lab_verify.py --map` |
| Interlock release-all frame | `UNK-005` | sources disagree |
| D+/D− connected while VBUS off | `UNK-004` | not documented |

## 3. Unknowns

| ID | Question | Impact | How to confirm |
| --- | --- | --- | --- |
| UNK-004 | Is D+/D− meaningful or settable while VBUS is off? Power-off auto-disconnect is observed; setting it while off is not. | State model and readback semantics | Set data line with power off, read back `0x08`, then power on |
| UNK-005 | How is interlock released? `SDK` sends mask `0x00`, value `0x00`; `PROTO` shows mask `0x0F`, value `0x01` | Interlock API correctness | Enter interlock, try both frames, read `0x00` after each |
| UNK-006 | Does this model answer `0x1B`/`0x1C` (overcurrent)? | Whether an OC API exists | Send `0x1B 00 00`, expect silence if unsupported |
| UNK-007 | Exact V3 measurement payload on this firmware: `mask, fresh, valid, period, tick, [V LE16, I LE16]…` | Measurement parser | Enable stream or force a sample, capture raw bytes |
| UNK-008 | Are V3 channel-name, alias and serial commands implemented on this firmware? | Optional features | Query `0x1F`, `0x21`, `0xF9` |
| UNK-009 | Do `0x0B`–`0x0E` replies match the documented 7-byte shape on this firmware? The shape is documented; conformance is not. | Default-state parser | Query `0x0C`, `0x0E` on one channel, compare with `PROTO` examples |
| UNK-010 | Actual measurement noise and offset at 0 A and at a known load | Accuracy claims and filtering | Compare against a DMM at 0 A and one known load |
| UNK-011 | Which input actually powers the current unit (DATA only, or AUX fitted)? | Power budget assumptions | Physical inspection of the connected cables |
| UNK-012 | Does the unit follow a 921600 host setting, and is the link stable there? | Throughput choice | Query identity at 115200 and 921600 |
| UNK-013 | Does power-on reconnect D+/D−, or does the data switch keep its last state? Sources conflict: user guide §8.4 says enabling power also connects data, §7.1 lists an On/Disconnected state. | State model and safe sequencing | Set data off with power on, power off, power on, read `0x08` |
| UNK-014 | Which status-LED pattern is correct? User guide gives 100/900 ms; protocol CMD 0x06 gives 0.5 s normal and 0.25 s interlock. | Cosmetic only | Observe the unit in both modes |
| UNK-015 | Do `0x03`/`0x04` accept a multi-channel mask and reply once per channel? Only single-channel queries are documented. | Batch measurement path | Send each with mask `0x0F`, count replies |
| UNK-017 | Why was CH4 on at first observation: button press, power-on default, or power-loss restore? | Startup-state behaviour and defaults testing | Read `0x0C` and `0x10`, power-cycle, observe CH4 |

Resolved:

| ID | Result | Evidence |
| --- | --- | --- |
| UNK-001 | CMD is `1a86:fe0c` at `3-3.2`, node `/dev/ttyACM0` | §1.2 |
| UNK-002 | Firmware V2.0, raw `02 00`: major = `CHANNEL`, minor = `VALUE` | §1.2 |
| UNK-003 | Product `0x00`, 4 channels; both `0xF0` and `0xF1` answer | §1.2 |
| UNK-016 | Speaker on CH4; switching CH4 off removed it | §1.3 |

## 4. Read-only probe sequence

Implemented by `scripts/lab_verify.py`; the default run executes exactly this
sequence. All frames below are queries. They change no device state. Every frame
is V1 unless stated. Checksums are included.

| Command | Frame | Expected reply |
| --- | --- | --- |
| Hardware version `0xFE` | `55 5A FE 00 00 FE` | V1, value = hardware version |
| Firmware version `0xFD` | `55 5A FD 00 00 FD` | V1; byte split is `UNK-002` |
| Product type `0xF0` | `55 5A F0 00 00 F0` | V1, value = product code; silence if unsupported |
| Max channels `0xF1` | `55 5A F1 00 00 F1` | V1, value = 4; `0xFF` means unsupported |
| Device address `0x12` | `55 5A 12 00 00 12` | V1, `CHANNEL` = MSB, `VALUE` = LSB |
| Operate mode `0x07` | `55 5A 07 00 00 07` | V1, `0` normal, `1` interlock |
| Button control `0x0A` | `55 5A 0A 00 00 0A` | V1, `0` disabled, `1` enabled |
| Power-loss restore `0x10` | `55 5A 10 00 00 10` | V1, `0` disabled, `1` enabled |
| All power states `0x00` | `55 5A 00 0F 00 0F` | Four V1 frames, one per channel |
| All data states `0x08` | `55 5A 08 0F 00 17` | Four V1 frames, one per channel |
| Channel voltage `0x03` | `55 5A 03 01 00 04` (CH1; repeat per channel) | V2, big-endian mV |
| Channel current `0x04` | `55 5A 04 01 00 05` (CH1; repeat per channel) | V2, big-endian mA |

The tool sends single-channel `0x03`/`0x04` queries. Multi-channel mask
acceptance is `UNK-015`.

Preconditions: CMD port connected with a data cable; nothing attached to the
downstream ports; no control application holding the port open. The SDK waits up
to 100 ms for an ACK and notes a ~2.5 ms physical round-trip floor. Silent
frames are a valid result for the optional commands and must be recorded, not
retried forever.

## 5. Controlled write checks

Each check needs explicit approval before running. Every check ends by restoring
the state recorded at the start. Do not run these with a downstream device that
must stay powered. `scripts/lab_verify.py --allow-switch --channel 1` runs the
single-channel parts of T-HW-001 and T-HW-002 and refuses to run in interlock
mode. `scripts/lab_verify.py --allow-switch --find-device` powers each channel
in turn and reports which one enumerates a new child of the DATA hub.

| ID | Check | Steps | Pass criterion |
| --- | --- | --- | --- |
| T-HW-001 | Single-channel power | Confirm Normal mode (`0x07` reads `0`). Read `0x00` all. Set CH1 on (`55 5A 01 01 01 03`). Read `0x00` CH1. Set CH1 off (`55 5A 01 01 00 02`). Read back. | Readback follows the command; other channels unchanged |
| T-HW-002 | Data-only unplug | With CH1 on, set CH1 data off (`55 5A 05 01 00 06`). Read `0x08`. Restore data on. | Power stays on, data state reads off, then on |
| T-HW-003 | Interlock rejection | Record mode. Set interlock (`55 5A 06 00 01 07`). Send `0x01` on CH1. Record reply. Restore mode. | Reply is `55 5A 01 FF FF FF`; power did not change |
| T-HW-004 | Interlock release | In interlock, send both release frames from `UNK-005`, reading `0x00` after each. Restore mode. | Exactly one frame clears all channels |
| T-HW-005 | Measurement sanity | CH1 on, nothing attached. Read `0x03`/`0x04`. Repeat with a known load. | Voltage ≈ 5 V; current offset small; load reading within datasheet accuracy |
| T-HW-006 | Version encoding | Read `0xFD`, decode both bytes. | Matches the printed/labeled firmware version |

Persistent settings — mode, defaults, restore, address, button control — survive
power cycles, and factory reset rewrites all of them. Record the original values
and restore them after any check that changes one. A power-on default left
enabled changes what the unit does at the next power-up.

Result 2026-11-07: T-HW-001 on CH4 passed. Power-off readback was off, data read
off, voltage fell 4614 mV → 202 mV, and the speaker disappeared from `lsusb` and
ALSA. CH4 was left off.

## 6. Sources

| Source | Path | Version |
| --- | --- | --- |
| Vendor datasheet | `reference/smartusbhub/docs/products/usb2_4p/datasheet.md` | v1.0, 2026-07-23 |
| Vendor user guide | `reference/smartusbhub/docs/products/usb2_4p/user_guide.md` | v1.0 |
| Vendor protocol | `reference/smartusbhub/docs/protocol.md` | 2026-07-24 |
| Vendor protocol PDF | `reference/smartusbhub/docs/downloads/protocol-en.pdf` | 2026-07-24 |
| System block diagram | `reference/smartusbhub/docs/products/usb2_4p/assets/system_block_diagram.svg` | v1.0 |
| Vendor SDK | `reference/smartusbhub/smartusbhub.py` | 1.2.1 |

The vendor SDK is Apache-2.0. It is a study copy. The rebuild is written from the
protocol facts, not by copying its source; if any code were reused, Apache-2.0
attribution would apply. The vendor documents are cited, not reproduced.

`OBS` facts must be re-checked if the unit, cable or host changes.
