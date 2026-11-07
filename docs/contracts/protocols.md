# IF-PROTO-001 — CMD wire protocol

| Field | Value |
| --- | --- |
| Device | SmartUSBHub Pro 4CH USB2.0 (`HBP_USB2_4CH`) |
| Source | Vendor `protocol.md` (2026-07-24), `scripts/lab_verify.py`, `src/hubctl/devices/smartusbhub/protocol.py` |
| Status | Implemented |

The CMD port is USB CDC serial at 115200 8N1, no flow control. Requests are V1
frames. Replies are V1 or V2. The app parses V3 frames so an unsolicited stream
cannot desynchronise the reader, but it never sends V3 commands.

## Frame layouts

| Family | Bytes | Layout |
| --- | --- | --- |
| V1 | 6 | `55 5A CMD CHANNEL VALUE SUM` |
| V2 | 7 | `55 5A CMD CHANNEL V0 V1 SUM` |
| V3 | 10 + N | `55 AB CD EF CMD FLAGS LEN_L LEN_H CRC_L CRC_H payload[N]` |

`SUM` is the low byte of the sum of `CMD`, `CHANNEL` and `VALUE` (`V0`+`V1` for
V2). `CRC` is CRC-16/IBM over the V3 header with the CRC field zeroed plus the
payload. Maximum V3 payload is 54 bytes.

Channel values are bits, not numbers: CH1 `0x01`, CH2 `0x02`, CH3 `0x04`,
CH4 `0x08`, up to CH7 `0x40`. A batch request ORs the bits.

## Command set the app may transmit

| Command | Meaning | Reply |
| --- | --- | --- |
| `0x00` | read power | one V1 frame per channel |
| `0x01` | set power | V1 echo; `55 5A 01 FF FF FF` if rejected |
| `0x03` | read voltage | V2, big-endian mV |
| `0x04` | read current | V2, big-endian mA |
| `0x05` | set D+/D- | V1 echo |
| `0x07` | read mode | V1, 0 normal, 1 interlock |
| `0x08` | read D+/D- | one V1 frame per channel |
| `0x0A` | read button control | V1 |
| `0x0C` | read power-on default | V2, two 8-bit fields |
| `0x0E` | read data default | V2, two 8-bit fields |
| `0x10` | read power-loss restore | V1 |
| `0x12` | read address | V1, `CHANNEL` = MSB, `VALUE` = LSB |
| `0xF0` | product type | V1, may be silent |
| `0xF1` | max channels | V1, may be silent |
| `0xFD` | firmware version | V1 |
| `0xFE` | hardware version | V1 |

Everything else is blocked in `transport.ALLOWED_COMMANDS`: `0x02` interlock
control, `0x06` mode, `0x09` button control, `0x0B`/`0x0D`/`0x0F`/`0x11`
settings, `0xFC` reset, `0xF7` reboot, V3 `0x1A`/`0x1E`-`0x21`/`0xF9`. The app
never writes NVM, resets, reboots, or enters firmware update.

## Decoding rules

| Path | Rule |
| --- | --- |
| `0x03`, `0x04` | V2 payload is a big-endian 16-bit unsigned value: mV and mA |
| `0x0B`-`0x0E` | V2 is a frame size; the two bytes are independent 8-bit `enable` and `value` fields |
| V3 measurement | little-endian fields; not enabled in v1 |
| `0xFD` | use the observed split: major in `CHANNEL`, minor in `VALUE`; if `CHANNEL` is 0, show the raw bytes |
| `0x12` | MSB in `CHANNEL`, LSB in `VALUE` |

Never apply the protocol prose's 0.1 V / 0.1 A scaling.

## Reply matching

- The link is not pure request/response. A button press sends an unsolicited
  `0x00` frame; a V3 frame with the stream flag is unsolicited too.
- The link drains pending frames before every request. A reply is filtered by
  command byte and, where needed, by channel mask. It is never bound by command
  byte alone.
- `0x00` and `0x08` answer once per channel. `0x03` and `0x04` are queried one
  channel at a time because a multi-channel mask is unproven (`UNK-015`).
- Silence is a valid result for optional and unsupported commands. It is a
  timeout for the mandatory poll.
- An unsolicited report and a poll reply are indistinguishable on the wire.
  The controller re-reads truth every cycle and verifies every write; it does
  not rely on a reply being newer than a report.

## Timing

| Constant | Value | Source |
| --- | ---: | --- |
| Baud | 115200 | protocol default |
| ACK timeout | 200 ms | chosen; vendor SDK uses 100 ms |
| Multi-frame timeout | 350 ms | chosen |
| Drain window | 20 ms | chosen |
| Write-to-readback settle | 30 ms | chosen |
| Minimum interval between writes | 1 ms | vendor SDK |

## Related

- Hardware facts: [HW-SPEC-001](../hardware/smartusbhub-pro-4ch.md) §9.
- Implementation: `src/hubctl/devices/smartusbhub/protocol.py`,
  `transport.py`, `driver.py`.
- Open protocol unknowns: [HW-VER-001](../hardware/verification.md) §3.
