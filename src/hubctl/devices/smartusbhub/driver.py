"""The SmartUSBHub Pro 4CH driver."""

from __future__ import annotations

from typing import Sequence

from ...hal.base import (
    ChannelReading,
    DeviceDriver,
    DeviceError,
    Identity,
    Mode,
    NotSupported,
    NotThisDevice,
    Rejected,
    StateMismatch,
    Status,
    Timeout,
)
from ...hal.discovery import candidate_ports
from ...constants import ACK_TIMEOUT_S, MULTI_TIMEOUT_S
from . import protocol
from .transport import SerialLink

PRODUCT_NAMES = {
    0x00: ("HBP_USB2_4CH", 4),
    0x01: ("HBP_USB2_2CH", 2),
    0x02: ("HBP_USB2_7CH", 7),
    0x03: ("HBP_USB2_7CH_ADV", 7),
    0x04: ("HBP_USB3_4CH", 4),
    0x05: ("HBL_USB2_4CH", 4),
}

DEFAULT_CHANNELS = 4


def _all_channels(frames, channels):
    seen = set()
    for frame in frames:
        seen.update(protocol.mask_channels(frame.p0))
    return set(channels).issubset(seen)


class SmartUSBHubDriver(DeviceDriver):
    supports_measurement = True
    supports_data_switch = True

    def __init__(self, link: SerialLink):
        self.link = link
        self._identity: Identity | None = None
        self._buttons: bool | None = None
        self._restore: bool | None = None

    @classmethod
    def discover(cls):
        return candidate_ports()

    @classmethod
    def open(cls, endpoint: str, trace=None) -> "SmartUSBHubDriver":
        link = SerialLink(endpoint, trace=trace)
        driver = cls(link)
        try:
            driver._identity = driver._read_identity(endpoint)
            button = driver._query(protocol.CMD_GET_BUTTON)
            restore = driver._query(protocol.CMD_GET_RESTORE)
            driver._buttons = None if button is None else bool(button.value)
            driver._restore = None if restore is None else bool(restore.value)
        except Exception:
            link.close()
            raise
        return driver

    # --- identity ---------------------------------------------------------
    def identity(self) -> Identity:
        if self._identity is None:
            raise DeviceError("driver is not open")
        return self._identity

    def _query(self, cmd, timeout=ACK_TIMEOUT_S):
        frames = self.link.request(
            cmd, timeout=timeout, predicate=lambda got: bool(got))
        return frames[-1] if frames else None

    def _read_identity(self, endpoint: str) -> Identity:
        hardware = self._query(protocol.CMD_GET_HARDWARE)
        firmware = self._query(protocol.CMD_GET_FIRMWARE)
        if hardware is None and firmware is None:
            raise NotThisDevice(f"{endpoint} did not answer the identity query")
        product = self._query(protocol.CMD_GET_PRODUCT)
        channel_frame = self._query(protocol.CMD_GET_CHANNELS)
        address = self._query(protocol.CMD_GET_ADDRESS)

        product_code = None if product is None else product.value
        family = PRODUCT_NAMES.get(product_code) if product_code is not None else None
        product_name = family[0] if family else (
            f"code 0x{product_code:02X}" if product_code is not None else "unknown")

        channels = DEFAULT_CHANNELS
        if channel_frame is not None and 0 < channel_frame.value <= 7:
            channels = channel_frame.value
        elif family:
            channels = family[1]

        hardware_text = "unknown" if hardware is None else f"V1.{hardware.value}"
        if firmware is None:
            firmware_text = "unknown"
        elif firmware.p0 > 0:
            firmware_text = f"V{firmware.p0}.{firmware.value}"
        else:
            firmware_text = f"raw {firmware.p0:02X} {firmware.value:02X}"

        return Identity(
            product=product_name,
            product_code=product_code,
            hardware=hardware_text,
            firmware=firmware_text,
            channels=channels,
            address=0 if address is None else (address.p0 << 8) | address.value,
            port=endpoint,
        )

    # --- status -----------------------------------------------------------
    def read_status(self) -> Status:
        frame = self._query(protocol.CMD_GET_MODE)
        if frame is None:
            raise Timeout("no reply to mode query 0x07")
        if frame.value == 0:
            mode = Mode.NORMAL
        elif frame.value == 1:
            mode = Mode.INTERLOCK
        else:
            mode = Mode.UNKNOWN
        return Status(mode, self._buttons, self._restore)

    # --- channel state ----------------------------------------------------
    def _validate(self, channels: Sequence[int]):
        count = self.identity().channels
        for channel in channels:
            if not 1 <= channel <= count:
                raise ValueError(f"CH{channel} out of range 1..{count}")

    def _read_bits(self, cmd, channels: Sequence[int]):
        self._validate(channels)
        mask = protocol.channel_mask(channels)
        frames = self.link.request(
            cmd, mask, 0, timeout=MULTI_TIMEOUT_S,
            predicate=lambda got: _all_channels(got, channels))
        if not frames:
            raise Timeout(f"no reply to 0x{cmd:02X}")
        result = {channel: None for channel in channels}
        for frame in frames:
            if not isinstance(frame.value, int):
                continue
            for channel in protocol.mask_channels(frame.p0):
                if channel in result:
                    result[channel] = bool(frame.value)
        return result

    def read_power(self, channels: Sequence[int]):
        return self._read_bits(protocol.CMD_GET_POWER, channels)

    def read_data(self, channels: Sequence[int]):
        return self._read_bits(protocol.CMD_GET_DATA, channels)

    def _measure(self, cmd, channel: int):
        bit = protocol.channel_bit(channel)
        frames = self.link.request(
            cmd, bit, 0, timeout=ACK_TIMEOUT_S,
            predicate=lambda got: any(
                frame.p0 == bit and isinstance(frame.value, tuple) for frame in got))
        for frame in reversed(frames):
            if frame.p0 == bit and isinstance(frame.value, tuple) and len(frame.value) == 2:
                return (frame.value[0] << 8) | frame.value[1]
        return None

    def read_voltage(self, channel: int):
        self._validate([channel])
        if not self.supports_measurement:
            return None
        return self._measure(protocol.CMD_GET_VOLTAGE, channel)

    def read_current(self, channel: int):
        self._validate([channel])
        if not self.supports_measurement:
            return None
        return self._measure(protocol.CMD_GET_CURRENT, channel)

    def read_channels(self, channels: Sequence[int]):
        power = self.read_power(channels)
        data = self.read_data(channels)
        result = {}
        for channel in channels:
            state = power.get(channel)
            result[channel] = ChannelReading(
                power=state,
                data=data.get(channel) if state is True else None,
                voltage_mv=self.read_voltage(channel),
                current_ma=self.read_current(channel),
            )
        return result

    # --- control ----------------------------------------------------------
    def _set_bits(self, cmd, channels: Sequence[int], on: bool):
        self._validate(channels)
        mask = protocol.channel_mask(channels)
        value = 1 if on else 0
        frames = self.link.request(
            cmd, mask, value, timeout=ACK_TIMEOUT_S,
            predicate=lambda got: bool(got))
        if not frames:
            raise Timeout(f"no ACK for command 0x{cmd:02X}")
        if cmd == protocol.CMD_SET_POWER:
            for frame in frames:
                if (frame.p0 == protocol.REJECT_MASK
                        and frame.value == protocol.REJECT_VALUE):
                    raise Rejected("device rejected 0x01 in interlock mode")
        frame = frames[-1]
        if frame.p0 != mask or frame.value != value:
            raise StateMismatch(
                f"echo 0x{frame.p0:02X}/0x{frame.value:02X}, "
                f"expected 0x{mask:02X}/0x{value:02X}")

    def set_power(self, channels: Sequence[int], on: bool):
        self._set_bits(protocol.CMD_SET_POWER, channels, on)

    def set_data(self, channels: Sequence[int], on: bool):
        if not self.supports_data_switch:
            raise NotSupported("this device has no D+/D- switch")
        self._set_bits(protocol.CMD_SET_DATA, channels, on)

    def close(self):
        self.link.close()
