"""SmartUSBHub wire format: V1/V2/V3 frames, CRC, and channel masks.

Pure functions only. No I/O, no policy.
"""

from __future__ import annotations

from collections import namedtuple

# --- Framing -----------------------------------------------------------------
SOF1 = 0x55
SOF2 = 0x5A
V3_MAGIC = b"\x55\xAB\xCD\xEF"
V3_HEADER_LEN = 10
V3_MAX_PAYLOAD = 54
V3_FLAG_STREAM = 0x01
FRAME_V1_LEN = 6
FRAME_V2_LEN = 7

Frame = namedtuple("Frame", "cmd p0 value raw")

INCOMPLETE = object()
REJECTED = object()

# --- Commands ----------------------------------------------------------------
CMD_GET_POWER = 0x00
CMD_SET_POWER = 0x01
CMD_SET_POWER_INTERLOCK = 0x02
CMD_GET_VOLTAGE = 0x03
CMD_GET_CURRENT = 0x04
CMD_SET_DATA = 0x05
CMD_SET_MODE = 0x06
CMD_GET_MODE = 0x07
CMD_GET_DATA = 0x08
CMD_SET_BUTTON = 0x09
CMD_GET_BUTTON = 0x0A
CMD_SET_DEFAULT_POWER = 0x0B
CMD_GET_DEFAULT_POWER = 0x0C
CMD_SET_DEFAULT_DATA = 0x0D
CMD_GET_DEFAULT_DATA = 0x0E
CMD_SET_RESTORE = 0x0F
CMD_GET_RESTORE = 0x10
CMD_SET_ADDRESS = 0x11
CMD_GET_ADDRESS = 0x12
CMD_GET_PRODUCT = 0xF0
CMD_GET_CHANNELS = 0xF1
CMD_RESET = 0xFC
CMD_GET_FIRMWARE = 0xFD
CMD_GET_HARDWARE = 0xFE

V2_REPLY_COMMANDS = frozenset({
    CMD_GET_VOLTAGE, CMD_GET_CURRENT,
    CMD_SET_DEFAULT_POWER, CMD_GET_DEFAULT_POWER,
    CMD_SET_DEFAULT_DATA, CMD_GET_DEFAULT_DATA,
})

DEFAULT_COMMANDS = frozenset({
    CMD_SET_DEFAULT_POWER, CMD_GET_DEFAULT_POWER,
    CMD_SET_DEFAULT_DATA, CMD_GET_DEFAULT_DATA,
})

REJECT_MASK = 0xFF
REJECT_VALUE = 0xFF
REJECT_FRAME = bytes([SOF1, SOF2, CMD_SET_POWER, REJECT_MASK, REJECT_VALUE, 0xFF])


def next_frame(buf):
    """Pop one complete frame from the front of ``buf``; None if incomplete."""
    while buf:
        if buf[0] != SOF1:
            del buf[0]
            continue
        if len(buf) < 2:
            return None
        if buf[1] == 0xAB:
            result = parse_v3(buf)
            if result is REJECTED:
                continue
            if result is INCOMPLETE:
                return None
            return result
        if buf[1] != SOF2:
            del buf[0]
            continue
        if len(buf) < 3:
            return None
        cmd = buf[2]
        size = FRAME_V2_LEN if cmd in V2_REPLY_COMMANDS else FRAME_V1_LEN
        if len(buf) < size:
            return None
        if size == FRAME_V2_LEN:
            if (cmd + buf[3] + buf[4] + buf[5]) & 0xFF != buf[6]:
                del buf[0]
                continue
            value = (buf[4], buf[5])
        else:
            if (cmd + buf[3] + buf[4]) & 0xFF != buf[5]:
                del buf[0]
                continue
            value = buf[4]
        raw = bytes(buf[:size])
        del buf[:size]
        return Frame(cmd, raw[3], value, raw)
    return None


def parse_v3(buf):
    if len(buf) < len(V3_MAGIC):
        return INCOMPLETE
    if bytes(buf[:4]) != V3_MAGIC:
        del buf[0]
        return REJECTED
    if len(buf) < V3_HEADER_LEN:
        return INCOMPLETE
    length = buf[6] | (buf[7] << 8)
    if length > V3_MAX_PAYLOAD:
        del buf[0]
        return REJECTED
    total = V3_HEADER_LEN + length
    if len(buf) < total:
        return INCOMPLETE
    crc_region = bytes(buf[:8]) + b"\x00\x00" + bytes(buf[V3_HEADER_LEN:total])
    expected = buf[8] | (buf[9] << 8)
    if crc16(crc_region) != expected:
        del buf[0]
        return REJECTED
    cmd = buf[4]
    flags = buf[5]
    payload = bytes(buf[V3_HEADER_LEN:total])
    value = {"v3": True, "stream": bool(flags & V3_FLAG_STREAM), "payload": payload}
    raw = bytes(buf[:total])
    del buf[:total]
    return Frame(cmd, 0, value, raw)


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8005 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def encode_v1(cmd, p0, p1):
    return bytes([SOF1, SOF2, cmd, p0, p1, (cmd + p0 + p1) & 0xFF])


def encode_v2(cmd, p0, v0, v1):
    return bytes([SOF1, SOF2, cmd, p0, v0, v1, (cmd + p0 + v0 + v1) & 0xFF])


def encode_v3(cmd, payload=b"", flags=0):
    payload = bytes(payload)
    frame = bytearray(V3_MAGIC + bytes([
        cmd & 0xFF, flags & 0xFF,
        len(payload) & 0xFF, (len(payload) >> 8) & 0xFF, 0, 0]) + payload)
    crc = crc16(frame)
    frame[8] = crc & 0xFF
    frame[9] = (crc >> 8) & 0xFF
    return bytes(frame)


def channel_bit(channel):
    return 1 << (channel - 1)


def channel_mask(channels):
    mask = 0
    for channel in channels:
        if not 1 <= channel <= 7:
            raise ValueError(f"channel {channel} out of range 1..7")
        mask |= channel_bit(channel)
    return mask & 0x7F


def mask_channels(mask):
    return [index + 1 for index in range(7) if mask & (1 << index)]
