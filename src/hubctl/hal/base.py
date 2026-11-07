"""Hardware abstraction: values, the driver contract, and the error taxonomy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Iterable, Sequence


class Mode(Enum):
    NORMAL = "normal"
    INTERLOCK = "interlock"
    UNKNOWN = "unknown"


class LinkState(Enum):
    LIVE = "live"
    STALE = "stale"
    LOST = "lost"


@dataclass(frozen=True)
class Identity:
    product: str
    product_code: int | None
    hardware: str
    firmware: str
    channels: int
    address: int
    port: str


@dataclass
class ChannelReading:
    power: bool | None = None
    data: bool | None = None
    voltage_mv: int | None = None
    current_ma: int | None = None


@dataclass
class Status:
    mode: Mode = Mode.UNKNOWN
    buttons_enabled: bool | None = None
    restore_enabled: bool | None = None


@dataclass
class Snapshot:
    identity: Identity | None
    status: Status
    channels: dict[int, ChannelReading]
    link: LinkState
    last_cycle_age_s: float
    last_action: str
    last_kind: str = "ok"
    last_error: str | None = None
    reconnect_in_s: float | None = None
    poll_interval_s: float = 1.0
    port_setting: str | None = None
    port_choices: tuple[str, ...] = ()


class DeviceError(Exception):
    """Base class for every driver failure."""


class NotThisDevice(DeviceError):
    """The endpoint did not answer the identity handshake."""


class LinkError(DeviceError):
    """The serial link failed: unplug, I/O error, or an unavailable port."""


class Timeout(DeviceError):
    """A mandatory request got no reply."""


class NotSupported(DeviceError):
    """The driver does not implement this capability."""


class Rejected(DeviceError):
    """The device refused a control frame (interlock mode)."""


class StateMismatch(DeviceError):
    """The echo or the readback differs from the request."""


class DeviceDriver(ABC):
    """A switched-power-channel device.

    The controller talks to values only. Protocol bytes never cross this
    boundary. Measurement and the data switch are capability-gated because the
    vendor family already has models without them.
    """

    supports_measurement: ClassVar[bool] = False
    supports_data_switch: ClassVar[bool] = False

    @classmethod
    def discover(cls) -> Iterable[str]:
        return ()

    @classmethod
    @abstractmethod
    def open(cls, endpoint: str, **options) -> "DeviceDriver":
        """Open one endpoint and run the identity handshake."""

    @abstractmethod
    def close(self) -> None:
        """Release the port. Safe to call twice."""

    @abstractmethod
    def identity(self) -> Identity:
        """Identity captured at open."""

    @abstractmethod
    def read_status(self) -> Status:
        """Mode and settings. One request."""

    @abstractmethod
    def read_power(self, channels: Sequence[int]) -> dict[int, bool | None]:
        """Power state per channel. One request."""

    @abstractmethod
    def read_data(self, channels: Sequence[int]) -> dict[int, bool | None]:
        """Raw D+/D- state per channel. One request."""

    @abstractmethod
    def read_voltage(self, channel: int) -> int | None:
        """VBUS in mV, or None if the reply was missing. One request."""

    @abstractmethod
    def read_current(self, channel: int) -> int | None:
        """Current in mA, or None if the reply was missing. One request."""

    def read_channels(self, channels: Sequence[int]) -> dict[int, ChannelReading]:
        """Convenience read used by tests; the controller uses the single-request calls."""
        power = self.read_power(channels)
        data = self.read_data(channels)
        result: dict[int, ChannelReading] = {}
        for channel in channels:
            state = power.get(channel)
            result[channel] = ChannelReading(
                power=state,
                data=data.get(channel) if state is True else None,
                voltage_mv=self.read_voltage(channel),
                current_ma=self.read_current(channel),
            )
        return result

    @abstractmethod
    def set_power(self, channels: Sequence[int], on: bool) -> None:
        """Switch VBUS. Raises Rejected in interlock mode."""

    def set_data(self, channels: Sequence[int], on: bool) -> None:
        raise NotSupported("this device has no D+/D- switch")

    def __enter__(self) -> "DeviceDriver":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
