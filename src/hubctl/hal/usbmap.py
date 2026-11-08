"""Downstream USB devices on this host, read from sysfs.

Linux only. A missing or unreadable tree returns nothing; the caller shows
that as no device. Nothing here opens a port or writes.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from ..constants import HUB_PID, VID

ROOT = "/sys/bus/usb/devices"


@dataclass(frozen=True)
class UsbDevice:
    vid: str
    pid: str
    product: str


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return None


def hub_paths(root: str = ROOT) -> list[str]:
    """Devpaths of the DATA hub, 1a86:8091."""
    found = []
    for entry in glob.glob(os.path.join(root, "*")):
        name = os.path.basename(entry)
        if ":" in name:
            continue
        if _read(os.path.join(entry, "idVendor")) == VID and \
                _read(os.path.join(entry, "idProduct")) == HUB_PID:
            found.append(name)
    return sorted(found)


def port_devices(ports, root: str = ROOT) -> dict[int, bool]:
    """Which downstream ports have a device, with one scan of the hubs."""
    hubs = hub_paths(root)
    return {port: any(_read(os.path.join(root, f"{hub}.{port}", "idVendor"))
                      is not None for hub in hubs)
            for port in ports}


def port_device(port: int, root: str = ROOT) -> UsbDevice | None:
    """The device plugged into downstream port ``port``, if this host sees it."""
    for hub in hub_paths(root):
        entry = os.path.join(root, f"{hub}.{port}")
        vid = _read(os.path.join(entry, "idVendor"))
        pid = _read(os.path.join(entry, "idProduct"))
        if vid is None or pid is None:
            continue
        return UsbDevice(vid, pid,
                         _read(os.path.join(entry, "product")) or "")
    return None
