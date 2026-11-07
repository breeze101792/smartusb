"""The static driver list and endpoint selection."""

from __future__ import annotations

from ..devices.smartusbhub.driver import SmartUSBHubDriver
from .base import DeviceDriver, LinkError, NotThisDevice

DRIVERS = (SmartUSBHubDriver,)


def open_first(port: str | None = None, trace=None) -> DeviceDriver:
    """Open the first endpoint that answers an identity handshake.

    With ``port`` set, only that endpoint is tried: discovery is bypassed.
    """
    endpoints: list[str] = [port] if port else []
    if not endpoints:
        for driver in DRIVERS:
            endpoints.extend(driver.discover())
        endpoints = list(dict.fromkeys(endpoints))
    if not endpoints:
        raise LinkError(
            "no SmartUSBHub CMD port found; connect the CMD cable or pass --port")

    last: Exception | None = None
    for endpoint in endpoints:
        for driver in DRIVERS:
            try:
                return driver.open(endpoint, trace=trace)
            except NotThisDevice as exc:
                last = exc
            except LinkError as exc:
                last = exc
    if isinstance(last, LinkError):
        raise last
    raise NotThisDevice(str(last) if last else "no driver matched")
