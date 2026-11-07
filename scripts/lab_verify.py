#!/usr/bin/env python3
"""Lab verification for the SmartUSBHub Pro 4CH control link.

Zero third-party dependencies; POSIX only (termios/select/pty).

The default run is read-only. The switching test moves real VBUS and runs
only with --allow-switch.

    python3 scripts/lab_verify.py --list
    python3 scripts/lab_verify.py --map
    python3 scripts/lab_verify.py --port /dev/ttyACM0
    python3 scripts/lab_verify.py --allow-switch --channel 1
    python3 scripts/lab_verify.py --allow-switch --set-power off --channel 4
    python3 scripts/lab_verify.py --allow-switch --find-device
    python3 scripts/lab_verify.py --self-test
"""

import argparse
import glob
import os
import pty
import select
import signal
import sys
import termios
import threading
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hubctl.devices.smartusbhub import protocol
from hubctl.devices.smartusbhub.transport import SerialLink
from hubctl.hal.base import LinkError

# --- Serial and framing -------------------------------------------------------
BAUD = 115200
SOF1 = 0x55
SOF2 = 0x5A
V3_MAGIC = b"\x55\xAB\xCD\xEF"
V3_HEADER_LEN = 10
V3_MAX_PAYLOAD = 54
V3_FLAG_STREAM = 0x01
FRAME_V1_LEN = 6
FRAME_V2_LEN = 7
ACK_TIMEOUT = 0.20
MULTI_TIMEOUT = 0.35
DRAIN_WINDOW = 0.02
RX_CHUNK = 4096
ENUM_POLL = 0.2
ENUM_SETTLE = 0.5
FIND_WAIT = 5.0
MAX_CHANNELS = 8
SERIAL_ERRORS = (OSError, termios.error, LinkError)

# --- Commands ---------------------------------------------------------------
CMD_GET_POWER = 0x00
CMD_SET_POWER = 0x01
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

# --- Device facts ------------------------------------------------------------
CHANNELS_4CH = 4
REJECT_MASK = 0xFF
REJECT_VALUE = 0xFF
PRODUCT_NAMES = {
    0x00: ("HBP_USB2_4CH", 4),
    0x01: ("HBP_USB2_2CH", 2),
    0x02: ("HBP_USB2_7CH", 7),
    0x03: ("HBP_USB2_7CH_ADV", 7),
    0x04: ("HBP_USB3_4CH", 4),
    0x05: ("HBL_USB2_4CH", 4),
}
VID = "1a86"
PID = "fe0c"
HUB_PID = "8091"
MODE_NORMAL = 0
MODE_INTERLOCK = 1
STATE_OFF = 0
STATE_ON = 1
DATA_DISCONNECTED = 0
DATA_CONNECTED = 1

class Rejected(Exception):
    """The device refused a control frame (interlock mode)."""


# Shared codec and transport (src/hubctl). One implementation, also used by the app.
Link = SerialLink
Frame = protocol.Frame
INCOMPLETE = protocol.INCOMPLETE
REJECTED = protocol.REJECTED
next_frame = protocol.next_frame
parse_v3 = protocol.parse_v3
crc16 = protocol.crc16
encode_v1 = protocol.encode_v1
encode_v2 = protocol.encode_v2
encode_v3 = protocol.encode_v3
channel_bit = protocol.channel_bit
mask_channels = protocol.mask_channels


def make_link(port, verbose=False):
    trace = None
    if verbose:
        trace = lambda direction, data: print(f"  {direction} {data.hex(' ')}")
    return SerialLink(port, trace=trace)


def discover_ports():
    candidates = sorted(glob.glob("/dev/ttyACM*")) + sorted(glob.glob("/dev/cu.usbmodem*"))
    if not sys.platform.startswith("linux"):
        return candidates
    matched = []
    checked = 0
    for port in candidates:
        name = os.path.basename(port)
        base = f"/sys/class/tty/{name}/device"
        readable = False
        matched_this = False
        for rel in ("..", "../.."):
            try:
                with open(os.path.join(base, rel, "idVendor")) as handle:
                    vid = handle.read().strip()
                with open(os.path.join(base, rel, "idProduct")) as handle:
                    pid = handle.read().strip()
            except OSError:
                continue
            readable = True
            if vid == VID and pid == PID:
                matched_this = True
                break
        if readable:
            checked += 1
        if matched_this:
            matched.append(port)
    return matched if checked else candidates


def probe(port, verbose=False):
    try:
        link = make_link(port, verbose)
    except SERIAL_ERRORS as exc:
        print(f"  {port}: cannot open: {exc}")
        return None
    try:
        if link.request(CMD_GET_HARDWARE, timeout=ACK_TIMEOUT):
            return link
        if link.request(CMD_GET_FIRMWARE, timeout=ACK_TIMEOUT):
            return link
        link.close()
        return None
    except SERIAL_ERRORS:
        link.close()
        return None


# --- Report -----------------------------------------------------------------
class Report:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0

    def ok(self, label, detail):
        print(f"  {label:<28} {detail:<30} PASS")
        self.passed += 1

    def fail(self, label, detail):
        print(f"  {label:<28} {detail:<30} FAIL")
        self.failed += 1

    def skip(self, label, detail):
        print(f"  {label:<28} {detail:<30} SKIP")
        self.skipped += 1

    def check(self, label, got, expected):
        if got == expected:
            self.ok(label, str(got))
        else:
            self.fail(label, f"got {got}, expected {expected}")

    def summary(self):
        print(f"\nRESULT: {self.passed} passed, {self.failed} failed, {self.skipped} skipped")
        return 0 if self.failed == 0 else 1


# --- Queries ----------------------------------------------------------------
def query_one(link, cmd, timeout=ACK_TIMEOUT):
    frames = link.request(cmd, timeout=timeout)
    return frames[-1] if frames else None


def read_power(link, channels):
    mask = sum(channel_bit(ch) for ch in channels)
    frames = link.request(
        CMD_GET_POWER, mask, 0, timeout=MULTI_TIMEOUT,
        predicate=lambda got: all(any(ch in mask_channels(f.p0) for f in got) for ch in channels))
    result = {}
    for frame in frames:
        for ch in mask_channels(frame.p0):
            result[ch] = frame.value
    return {ch: result.get(ch) for ch in channels}


def read_data(link, channels):
    mask = sum(channel_bit(ch) for ch in channels)
    frames = link.request(
        CMD_GET_DATA, mask, 0, timeout=MULTI_TIMEOUT,
        predicate=lambda got: all(any(ch in mask_channels(f.p0) for f in got) for ch in channels))
    result = {}
    for frame in frames:
        for ch in mask_channels(frame.p0):
            result[ch] = frame.value
    return {ch: result.get(ch) for ch in channels}


def read_measurement(link, cmd, channel):
    bit = channel_bit(channel)
    frames = link.request(
        cmd, bit, 0, timeout=ACK_TIMEOUT,
        predicate=lambda got: any(frame.p0 == bit for frame in got))
    for frame in reversed(frames):
        if frame.p0 == bit and isinstance(frame.value, tuple):
            return (frame.value[0] << 8) | frame.value[1]
    return None


def read_mode(link):
    frame = query_one(link, CMD_GET_MODE)
    return None if frame is None else frame.value


def channel_count(link):
    frame = query_one(link, CMD_GET_CHANNELS)
    if frame is not None and 0 < frame.value <= MAX_CHANNELS:
        return frame.value
    return CHANNELS_4CH


# --- Control ----------------------------------------------------------------
def set_power(link, channels, state):
    mask = sum(channel_bit(ch) for ch in channels)
    frames = link.request(CMD_SET_POWER, mask, state, timeout=ACK_TIMEOUT)
    if not frames:
        raise IOError("no ACK for power command")
    frame = frames[-1]
    if frame.p0 == REJECT_MASK and frame.value == REJECT_VALUE:
        raise Rejected("device rejected 0x01 (interlock mode)")
    if frame.p0 != mask or frame.value != state:
        raise IOError(f"unexpected power echo {fmt_frame(frame)}")


def set_data(link, channels, state):
    mask = sum(channel_bit(ch) for ch in channels)
    frames = link.request(CMD_SET_DATA, mask, state, timeout=ACK_TIMEOUT)
    if not frames:
        raise IOError("no ACK for data command")
    frame = frames[-1]
    if frame.p0 != mask or frame.value != state:
        raise IOError(f"unexpected data echo {fmt_frame(frame)}")


def read_identity(link, report):
    hardware = query_one(link, CMD_GET_HARDWARE)
    if hardware is None:
        report.fail("hardware version", "no reply")
    else:
        report.ok("hardware version", f"V1.{hardware.value} (raw {hardware.value})")

    firmware = query_one(link, CMD_GET_FIRMWARE)
    if firmware is None:
        report.fail("firmware version", "no reply")
        firmware_string = "unknown"
    else:
        major = firmware.p0 if firmware.p0 > 0 else 1
        firmware_string = f"V{major}.{firmware.value}"
        report.ok("firmware version",
                  f"{firmware_string} (raw {firmware.p0:02X} {firmware.value:02X})")

    product = query_one(link, CMD_GET_PRODUCT)
    if product is None:
        report.skip("product type", "no reply (unsupported)")
        product_id = None
    else:
        name, _channels = PRODUCT_NAMES.get(product.value, (f"unknown({product.value:02X})", 0))
        product_id = product.value
        report.ok("product type", f"0x{product.value:02X} {name}")

    channels = query_one(link, CMD_GET_CHANNELS)
    if channels is None:
        report.skip("max channels", "no reply (unsupported)")
        max_channels = None
    elif channels.value == 0xFF:
        report.skip("max channels", "0xFF (unsupported)")
        max_channels = None
    elif 0 < channels.value <= MAX_CHANNELS:
        max_channels = channels.value
        report.ok("max channels", str(max_channels))
    else:
        report.fail("max channels", f"{channels.value} out of range")
        max_channels = CHANNELS_4CH
    if max_channels is None and product_id in PRODUCT_NAMES:
        max_channels = PRODUCT_NAMES[product_id][1]

    address = query_one(link, CMD_GET_ADDRESS)
    if address is None:
        report.fail("device address", "no reply")
    else:
        report.ok("device address", f"0x{(address.p0 << 8) | address.value:04X}")

    mode = query_one(link, CMD_GET_MODE)
    if mode is None:
        report.fail("operate mode", "no reply")
    else:
        report.ok("operate mode", "normal" if mode.value == MODE_NORMAL else "interlock")

    button = query_one(link, CMD_GET_BUTTON)
    if button is None:
        report.fail("button control", "no reply")
    else:
        report.ok("button control", "enabled" if button.value == 1 else "disabled")

    restore = query_one(link, CMD_GET_RESTORE)
    if restore is None:
        report.fail("power-loss restore", "no reply")
    else:
        report.ok("power-loss restore", "enabled" if restore.value == 1 else "disabled")

    return {
        "hardware": None if hardware is None else hardware.value,
        "firmware": firmware_string,
        "product": product_id,
        "channels": max_channels or CHANNELS_4CH,
        "mode": None if mode is None else mode.value,
    }


def print_states(link, channels, report):
    power = read_power(link, channels)
    data = read_data(link, channels)
    for ch in channels:
        voltage = read_measurement(link, CMD_GET_VOLTAGE, ch)
        current = read_measurement(link, CMD_GET_CURRENT, ch)
        power_text = "?" if power[ch] is None else ("on" if power[ch] else "off")
        data_text = "?" if data[ch] is None else ("on" if data[ch] else "off")
        voltage_text = "?" if voltage is None else f"{voltage}mV"
        current_text = "?" if current is None else f"{current}mA"
        print(f"  CH{ch}  power={power_text:<3} data={data_text:<3} "
              f"V={voltage_text:<8} I={current_text}")
        if power[ch] is None or data[ch] is None:
            report.fail(f"CH{ch} state", "incomplete reply")
        else:
            report.ok(f"CH{ch} state", f"power={power_text} data={data_text}")


def restore_channel(link, channel, initial_power, initial_data):
    errors = []
    try:
        set_power(link, [channel], initial_power)
        if read_power(link, [channel])[channel] != initial_power:
            errors.append("power readback mismatch")
    except (Rejected, IOError, OSError, LinkError) as exc:
        errors.append(f"power: {exc}")

    try:
        set_data(link, [channel], initial_data)
        if initial_power == STATE_ON:
            if read_data(link, [channel])[channel] != initial_data:
                errors.append("data readback mismatch")
    except (Rejected, IOError, OSError, LinkError) as exc:
        errors.append(f"data: {exc}")
    return errors


def usb_hub_devpaths():
    """Return all sysfs devpaths with the WCH hub PID (1a86:8091)."""
    paths = []
    for entry in glob.glob("/sys/bus/usb/devices/*"):
        if ":" in os.path.basename(entry):
            continue
        try:
            with open(os.path.join(entry, "idVendor")) as handle:
                vid = handle.read().strip()
            with open(os.path.join(entry, "idProduct")) as handle:
                pid = handle.read().strip()
        except OSError:
            continue
        if vid == VID and pid == HUB_PID:
            paths.append(os.path.basename(entry))
    return sorted(paths)


def downstream_devices(devpath):
    """Map device name to (vid, pid, product) for children of the hub."""
    devices = {}
    for entry in glob.glob(f"/sys/bus/usb/devices/{devpath}.*"):
        name = os.path.basename(entry)
        if ":" in name:
            continue
        try:
            with open(os.path.join(entry, "idVendor")) as handle:
                vid = handle.read().strip()
            with open(os.path.join(entry, "idProduct")) as handle:
                pid = handle.read().strip()
            try:
                with open(os.path.join(entry, "product")) as handle:
                    product = handle.read().strip()
            except OSError:
                product = ""
        except OSError:
            continue
        devices[name] = (vid, pid, product)
    return devices


def port_of(name, hub):
    """Return the downstream port number for a sysfs name, or None."""
    if not name.startswith(hub + "."):
        return None
    head = name[len(hub) + 1:].split(".", 1)[0]
    return int(head) if head.isdigit() else None


def map_ports(hub=None):
    """Print the current sysfs mapping of downstream devices to channels."""
    if not sys.platform.startswith("linux"):
        print("--map needs Linux sysfs")
        return 2
    hubs = [hub] if hub else usb_hub_devpaths()
    if not hubs:
        print("no device with 1a86:8091 found")
        return 2
    for devpath in hubs:
        print(f"hub {devpath}")
        devices = downstream_devices(devpath)
        if not devices:
            print("  no downstream devices")
            continue
        for name, (vid, pid, product) in sorted(devices.items()):
            ch = port_of(name, devpath)
            label = f"CH{ch}" if ch is not None else "?"
            print(f"  {label}: {name} {vid}:{pid} {product}")
    return 0


def find_device(link, wait, hub=None):
    """Power each channel in turn and report where a new device enumerates."""
    if not sys.platform.startswith("linux"):
        print("--find-device needs Linux sysfs")
        return 2
    if hub is None:
        matches = usb_hub_devpaths()
        if len(matches) != 1:
            listed = ", ".join(matches) if matches else "none"
            print(f"found {len(matches)} device(s) with 1a86:8091: {listed}")
            print("pass --hub <devpath> to select the SmartUSBHub DATA hub")
            return 2
        hub = matches[0]
    if not os.path.isdir(f"/sys/bus/usb/devices/{hub}"):
        print(f"hub {hub} is not present")
        return 2
    mode = read_mode(link)
    if mode is None:
        print("cannot read operate mode; device is not answering")
        return 1
    if mode != MODE_NORMAL:
        print("device is in interlock mode; individual channel selection is unavailable")
        return 1
    channels = tuple(range(1, channel_count(link) + 1))
    initial = read_power(link, channels)
    if any(value is None for value in initial.values()):
        print("cannot read initial channel state")
        return 1
    baseline = downstream_devices(hub)
    print(f"hub {hub}; downstream devices now: {len(baseline)}")
    at_start = {}
    for name, (vid, pid, product) in sorted(baseline.items()):
        ch = port_of(name, hub)
        label = f"CH{ch}" if ch is not None else "?"
        print(f"  already present: {label} {name} {vid}:{pid} {product}")
        if ch is not None:
            at_start.setdefault(ch, []).append((name, vid, pid, product))
    print(f"\nTesting CH1–CH{channels[-1]}: each channel powers on for up to {wait:.1f}s.")
    print("A bus-powered device will not appear until its channel is on.")

    found = None
    restore_failed = False
    try:
        for ch in channels:
            if initial[ch] == STATE_ON:
                if ch in at_start:
                    for name, vid, pid, product in at_start[ch]:
                        print(f"CH{ch}: already on, device {name} {vid}:{pid} {product}")
                    found = ch
                    break
                print(f"CH{ch}: already on, no device")
                continue
            before = downstream_devices(hub)
            print(f"CH{ch}: power on ...", end="", flush=True)
            set_power(link, [ch], STATE_ON)
            if read_power(link, [ch])[ch] != STATE_ON:
                print(" power readback failed")
                set_power(link, [ch], STATE_OFF)
                continue
            deadline = time.monotonic() + wait
            new = {}
            while time.monotonic() < deadline:
                now = downstream_devices(hub)
                new = {key: value for key, value in now.items() if key not in before}
                if new:
                    break
                time.sleep(ENUM_POLL)
            set_power(link, [ch], STATE_OFF)
            time.sleep(ENUM_SETTLE)
            now = downstream_devices(hub)
            new.update({key: value for key, value in now.items()
                        if key not in before and key not in new})
            if new:
                for name, (vid, pid, product) in sorted(new.items()):
                    print(f" device on CH{ch}: {name} {vid}:{pid} {product}")
                found = ch
                break
            print(" no new device")
    except Rejected as exc:
        print(f"\n{exc}")
        return 1
    finally:
        for ch in channels:
            try:
                set_power(link, [ch], initial[ch])
            except (Rejected, IOError, OSError, LinkError) as exc:
                restore_failed = True
                print(f"  restore CH{ch} failed: {exc}")
                print(f"  Check CH{ch} by hand before leaving the bench.")

    if found is not None:
        print(f"\nRESULT: device is on CH{found}")
        return 1 if restore_failed else 0
    print("\nRESULT: no new downstream device appeared on any channel")
    return 1


def control_test(link, channel, report):
    """Return True if the test ran, False if it was skipped."""
    print(f"\nSWITCHING TEST — CH{channel}: this moves real VBUS.")
    mode = read_mode(link)
    if mode is None:
        report.fail("switching test", "cannot read operate mode")
        return True
    if mode != MODE_NORMAL:
        report.skip("switching test", "device is in interlock mode")
        return False

    initial_power = read_power(link, [channel])[channel]
    initial_data = read_data(link, [channel])[channel]
    if initial_power is None or initial_data is None:
        report.fail("switching test", "cannot read initial state")
        return True
    print(f"  initial: power={'on' if initial_power else 'off'} "
          f"data={'on' if initial_data else 'off'}")

    try:
        set_power(link, [channel], STATE_ON)
        report.check("set power on", read_power(link, [channel])[channel], STATE_ON)

        set_data(link, [channel], DATA_DISCONNECTED)
        report.check("data disconnect", read_data(link, [channel])[channel], DATA_DISCONNECTED)

        set_data(link, [channel], DATA_CONNECTED)
        report.check("data reconnect", read_data(link, [channel])[channel], DATA_CONNECTED)

        set_power(link, [channel], STATE_OFF)
        report.check("set power off", read_power(link, [channel])[channel], STATE_OFF)
    except Rejected as exc:
        report.fail("switching test", str(exc))
    except (IOError, OSError, LinkError) as exc:
        report.fail("switching test", str(exc)[:40])
    finally:
        errors = restore_channel(link, channel, initial_power, initial_data)
        if errors:
            report.fail("restore", "see warning")
            print(f"  RESTORE FAILED: {'; '.join(errors)}")
            print(f"  Check CH{channel} power and data by hand before leaving the bench.")
        else:
            text = f"  restored: power={'on' if initial_power else 'off'}"
            if initial_power == STATE_ON:
                text += f", data={'on' if initial_data else 'off'}"
            else:
                text += " (data restore sent; readback skipped while power is off)"
            print(text)
    return True


# --- Offline self-test ------------------------------------------------------
class FakeHub(threading.Thread):
    """Minimal wire-level device for the pty self-test."""

    def __init__(self, fd):
        super().__init__(daemon=True)
        self.fd = fd
        self.stop_event = threading.Event()
        self.buf = bytearray()
        self.power = {ch: STATE_OFF for ch in range(1, 5)}
        self.data = {ch: DATA_CONNECTED for ch in range(1, 5)}
        self.mode = MODE_NORMAL
        self.button = 1
        self.restore = 0
        self.address = 0x0000

    def stop(self):
        self.stop_event.set()
        self.join(timeout=1)

    def run(self):
        while not self.stop_event.is_set():
            try:
                chunk = os.read(self.fd, RX_CHUNK)
            except BlockingIOError:
                time.sleep(0.002)
                continue
            except OSError:
                break
            if not chunk:
                break
            self.buf.extend(chunk)
            while len(self.buf) >= FRAME_V1_LEN:
                if self.buf[0] != SOF1 or self.buf[1] != SOF2:
                    del self.buf[0]
                    continue
                packet = bytes(self.buf[:FRAME_V1_LEN])
                del self.buf[:FRAME_V1_LEN]
                reply = self.respond(packet)
                if reply:
                    os.write(self.fd, reply)

    def respond(self, packet):
        cmd, mask, value = packet[2], packet[3], packet[4]
        if cmd == CMD_GET_HARDWARE:
            return encode_v1(cmd, 0, 3)
        if cmd == CMD_GET_FIRMWARE:
            return encode_v1(cmd, 2, 1)
        if cmd == CMD_GET_PRODUCT:
            return encode_v1(cmd, 0, 0x00)
        if cmd == CMD_GET_CHANNELS:
            return encode_v1(cmd, 0, CHANNELS_4CH)
        if cmd == CMD_GET_ADDRESS:
            return encode_v1(cmd, self.address >> 8, self.address & 0xFF)
        if cmd == CMD_GET_MODE:
            return encode_v1(cmd, 0, self.mode)
        if cmd == CMD_GET_BUTTON:
            return encode_v1(cmd, 0, self.button)
        if cmd == CMD_GET_RESTORE:
            return encode_v1(cmd, 0, self.restore)
        if cmd == CMD_SET_MODE:
            self.mode = value
            return encode_v1(cmd, mask, value)
        if cmd == CMD_SET_BUTTON:
            self.button = value
            return encode_v1(cmd, mask, value)
        if cmd == CMD_SET_RESTORE:
            self.restore = value
            return encode_v1(cmd, mask, value)
        if cmd == CMD_SET_ADDRESS:
            self.address = (mask << 8) | value
            return encode_v1(cmd, mask, value)
        if cmd == CMD_GET_POWER:
            return b"".join(
                encode_v1(cmd, channel_bit(ch), self.power[ch]) for ch in mask_channels(mask))
        if cmd == CMD_GET_DATA:
            return b"".join(
                encode_v1(cmd, channel_bit(ch), self.data[ch]) for ch in mask_channels(mask))
        if cmd == CMD_SET_POWER:
            for ch in mask_channels(mask):
                self.power[ch] = value
            return encode_v1(cmd, mask, value)
        if cmd == CMD_SET_DATA:
            for ch in mask_channels(mask):
                self.data[ch] = value
            return encode_v1(cmd, mask, value)
        if cmd in (CMD_GET_VOLTAGE, CMD_GET_CURRENT):
            replies = []
            for ch in mask_channels(mask):
                if cmd == CMD_GET_VOLTAGE:
                    raw = 5000 + ch if self.power[ch] else 8
                else:
                    raw = 100 + ch if self.power[ch] else 0
                replies.append(encode_v2(cmd, channel_bit(ch), raw >> 8, raw & 0xFF))
            return b"".join(replies)
        if cmd in (CMD_GET_DEFAULT_POWER, CMD_GET_DEFAULT_DATA):
            return encode_v2(cmd, mask, 0, 0)
        if cmd == CMD_RESET:
            return encode_v1(cmd, 0, 0)
        return b""


def parser_cases(report):
    print("\nFRAME PARSER")
    good = encode_v1(CMD_GET_HARDWARE, 0, 3)
    bad_sum = bytes([SOF1, SOF2, CMD_GET_HARDWARE, 0, 3, 0x00])
    bad_v3 = bytearray(encode_v3(0x1A, b"\x01\x02\x03\x04"))
    bad_v3[8] ^= 0xFF
    truncated = encode_v3(0x1A, b"\x01\x02")[:6]
    cases = (
        ("bad V1 checksum resync", bad_sum + good, [CMD_GET_HARDWARE]),
        ("bad V3 CRC resync", bytes(bad_v3) + good, [CMD_GET_HARDWARE]),
        ("valid V3 frame", encode_v3(0x1A, b"\x0F"), [0x1A]),
        ("truncated V3 buffered", truncated, []),
    )
    for name, data, expected in cases:
        buf = bytearray(data)
        cmds = []
        while True:
            frame = next_frame(buf)
            if frame is None:
                break
            cmds.append(frame.cmd)
        report.check(name, cmds, expected)


def self_test(verbose=False):
    master, slave = pty.openpty()
    os.set_blocking(master, False)
    path = os.ttyname(slave)
    print("SmartUSBHub lab verification — SELF-TEST (pty, no hardware)")
    print(f"port: {path}")
    link = make_link(path, verbose)
    fake = FakeHub(master)
    fake.start()
    report = Report()
    try:
        parser_cases(report)
        print("\nIDENTITY")
        info = read_identity(link, report)
        channels = tuple(range(1, info["channels"] + 1))
        print("\nCHANNEL STATE (read-only)")
        print_states(link, channels, report)
        control_test(link, 1, report)
    finally:
        fake.stop()
        link.close()
        os.close(master)
        os.close(slave)
    return report.summary()


# --- Main -------------------------------------------------------------------
def run_checks(link, args, report):
    print("\nIDENTITY")
    info = read_identity(link, report)
    channels = tuple(range(1, info["channels"] + 1))
    print("\nCHANNEL STATE (read-only)")
    print_states(link, channels, report)

    if not args.allow_switch:
        print("\nSWITCHING TEST skipped: pass --allow-switch to move VBUS.")
        return False
    if args.channel not in channels:
        report.fail("switching test", f"CH{args.channel} out of range")
        return False
    return control_test(link, args.channel, report) is False


def _raise_interrupt(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description="SmartUSBHub Pro 4CH lab verification")
    parser.add_argument("--port", help="serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--list", action="store_true", help="list candidate control ports")
    parser.add_argument("--map", action="store_true",
                        help="map current downstream devices to channels (no CMD port needed)")
    parser.add_argument("--allow-switch", action="store_true",
                        help="allow VBUS switching (required for --channel and --find-device)")
    parser.add_argument("--channel", type=int, default=1, help="channel for the switching test")
    parser.add_argument("--set-power", choices=("on", "off"),
                        help="set one channel's power and leave it in that state (needs --allow-switch)")
    parser.add_argument("--find-device", action="store_true",
                        help="power each channel in turn and report which port enumerates a device (needs --allow-switch)")
    parser.add_argument("--hub", help="sysfs devpath of the DATA hub, e.g. 3-3.4")
    parser.add_argument("--wait", type=float, default=FIND_WAIT,
                        help="seconds per channel to wait for enumeration (--find-device)")
    parser.add_argument("--self-test", action="store_true", help="run offline over a pty")
    parser.add_argument("--verbose", action="store_true", help="dump raw TX/RX bytes")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test(verbose=args.verbose)
    if args.map:
        return map_ports(args.hub)
    if args.find_device and not args.allow_switch:
        print("--find-device moves VBUS; add --allow-switch to run it.")
        return 2
    if args.set_power is not None and not args.allow_switch:
        print("--set-power moves VBUS; add --allow-switch to run it.")
        return 2

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, _raise_interrupt)

    ports = [args.port] if args.port else discover_ports()
    if args.list:
        if not ports:
            print("no candidate ports")
            return 2
        for port in ports:
            print(port)
        return 0
    if not ports:
        print("No candidate control port. Connect the CMD USB-C port with a data cable,")
        print("or pass --port. Linux expects /dev/ttyACM*, macOS /dev/cu.usbmodem*.")
        return 2
    if not args.port and sys.platform == "darwin" and len(ports) > 1:
        print(f"macOS: cannot filter CDC ports by VID:PID; probing {len(ports)} candidate(s)")

    print(f"SmartUSBHub lab verification ({BAUD} 8N1)")
    link = None
    report = Report()
    code = 0
    try:
        for port in ports:
            print(f"probing {port}")
            link = probe(port, verbose=args.verbose)
            if link is not None:
                print(f"port: {port}")
                break
        if link is None:
            print("No device answered the identity query. Check the CMD cable and permissions.")
            return 2
        if args.set_power is not None:
            count = channel_count(link)
            if not 1 <= args.channel <= count:
                print(f"CH{args.channel} out of range 1..{count}")
                code = 2
            else:
                state = STATE_ON if args.set_power == "on" else STATE_OFF
                set_power(link, [args.channel], state)
                got = read_power(link, [args.channel])[args.channel]
                print(f"CH{args.channel}: power={'on' if got else 'off'}")
                code = 0 if got == state else 1
        elif args.find_device:
            code = find_device(link, args.wait, args.hub)
        else:
            write_skipped = run_checks(link, args, report)
            code = report.summary()
            if write_skipped and code == 0:
                print("Requested switching test did not run.")
                code = 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    except SERIAL_ERRORS as exc:
        print(f"\nlink error: {exc}")
        return 1
    finally:
        if link is not None:
            link.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
