"""Candidate endpoint discovery.

Linux reads sysfs and keeps only the CMD port (1a86:fe0c). macOS has no sysfs;
the ioreg parser is best-effort and unverified on a Mac, so `--port` remains the
supported path there. A port is never opened here.
"""

from __future__ import annotations

import glob
import os
import subprocess
import sys

from ..constants import PID, VID


def _sysfs_ids(node: str, sysfs_root: str):
    base = os.path.join(sysfs_root, "class", "tty", os.path.basename(node), "device")
    for rel in ("..", "../.."):
        directory = os.path.join(base, rel)
        try:
            with open(os.path.join(directory, "idVendor"), encoding="ascii") as handle:
                vendor = handle.read().strip()
            with open(os.path.join(directory, "idProduct"), encoding="ascii") as handle:
                product = handle.read().strip()
        except OSError:
            continue
        return vendor, product
    return None


def _linux_ports(sysfs_root: str, ports):
    candidates = ports if ports is not None else sorted(glob.glob("/dev/ttyACM*"))
    found = []
    for path in candidates:
        ids = _sysfs_ids(path, sysfs_root)
        if ids == (VID, PID):
            found.append(path)
    return found


def _macos_ports():
    try:
        result = subprocess.run(
            ["ioreg", "-p", "IOUSB", "-l", "-w", "0"],
            capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    ports = []
    vendor = product = None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith('"idVendor"'):
            vendor = _parse_int(stripped.split("=", 1)[-1])
        elif stripped.startswith('"idProduct"'):
            product = _parse_int(stripped.split("=", 1)[-1])
        elif stripped.startswith('"IOCalloutDevice"'):
            device = stripped.split("=", 1)[-1].strip().strip('"')
            if vendor == int(VID, 16) and product == int(PID, 16) and device:
                ports.append(device)
            vendor = product = None
    return sorted(set(ports))


def _parse_int(text: str):
    text = text.strip().strip('"')
    try:
        return int(text, 0)
    except ValueError:
        try:
            return int(text)
        except ValueError:
            return None


def candidate_ports(sysfs_root: str = "/sys", ports=None):
    """Return candidate CMD endpoints. Never opens a port."""
    if sys.platform.startswith("linux") or sysfs_root != "/sys":
        return _linux_ports(sysfs_root, ports)
    if sys.platform == "darwin":
        return _macos_ports()
    return []
