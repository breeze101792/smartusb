"""A pty-backed SmartUSBHub for host tests. No hardware."""

from __future__ import annotations

import os
import pty
import select
import threading

from hubctl.devices.smartusbhub import protocol


class FakeHub(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.master, self.slave = pty.openpty()
        os.set_blocking(self.master, False)
        self.port = os.ttyname(self.slave)
        self.stop_event = threading.Event()
        self.buf = bytearray()
        self.write_lock = threading.Lock()

        self.mode = 0
        self.power = {1: 0, 2: 0, 3: 0, 4: 0}
        self.data = {1: 1, 2: 1, 3: 1, 4: 1}
        self.silent = False
        self.reject = False
        self.bad_echo = False
        self.received = []

    def run(self):
        while not self.stop_event.is_set():
            try:
                ready, _, _ = select.select([self.master], [], [], 0.02)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(self.master, 4096)
            except BlockingIOError:
                continue
            except OSError:
                break
            if not chunk:
                break
            self.buf.extend(chunk)
            while True:
                packet = self._next_packet()
                if packet is None:
                    break
                self._handle(packet)

    def _next_packet(self):
        while len(self.buf) >= protocol.FRAME_V1_LEN:
            if self.buf[0] != protocol.SOF1 or self.buf[1] != protocol.SOF2:
                del self.buf[0]
                continue
            packet = bytes(self.buf[:protocol.FRAME_V1_LEN])
            del self.buf[:protocol.FRAME_V1_LEN]
            if (packet[2] + packet[3] + packet[4]) & 0xFF != packet[5]:
                continue
            return packet
        return None

    def _write(self, data):
        with self.write_lock:
            try:
                os.write(self.master, data)
            except OSError:
                pass

    def _handle(self, packet):
        cmd, p0, p1 = packet[2], packet[3], packet[4]
        self.received.append((cmd, p0, p1))
        if self.silent:
            return
        if cmd == protocol.CMD_GET_HARDWARE:
            self._write(protocol.encode_v1(cmd, 0, 3))
        elif cmd == protocol.CMD_GET_FIRMWARE:
            self._write(protocol.encode_v1(cmd, 2, 0))
        elif cmd == protocol.CMD_GET_PRODUCT:
            self._write(protocol.encode_v1(cmd, 0, 0))
        elif cmd == protocol.CMD_GET_CHANNELS:
            self._write(protocol.encode_v1(cmd, 0, 4))
        elif cmd == protocol.CMD_GET_ADDRESS:
            self._write(protocol.encode_v1(cmd, 0, 0))
        elif cmd == protocol.CMD_GET_MODE:
            self._write(protocol.encode_v1(cmd, 0, self.mode))
        elif cmd == protocol.CMD_GET_BUTTON:
            self._write(protocol.encode_v1(cmd, 0, 1))
        elif cmd == protocol.CMD_GET_RESTORE:
            self._write(protocol.encode_v1(cmd, 0, 0))
        elif cmd == protocol.CMD_GET_POWER:
            self._write(b"".join(
                protocol.encode_v1(cmd, protocol.channel_bit(ch), self.power[ch])
                for ch in protocol.mask_channels(p0)))
        elif cmd == protocol.CMD_GET_DATA:
            self._write(b"".join(
                protocol.encode_v1(cmd, protocol.channel_bit(ch), self.data[ch])
                for ch in protocol.mask_channels(p0)))
        elif cmd == protocol.CMD_SET_POWER:
            if self.mode == 1 or self.reject:
                self._write(protocol.REJECT_FRAME)
                return
            for ch in protocol.mask_channels(p0):
                self.power[ch] = p1
            echo = 1 - p1 if self.bad_echo else p1
            self._write(protocol.encode_v1(cmd, p0, echo))
        elif cmd == protocol.CMD_SET_DATA:
            for ch in protocol.mask_channels(p0):
                self.data[ch] = p1
            echo = 1 - p1 if self.bad_echo else p1
            self._write(protocol.encode_v1(cmd, p0, echo))
        elif cmd in (protocol.CMD_GET_VOLTAGE, protocol.CMD_GET_CURRENT):
            for ch in protocol.mask_channels(p0):
                if cmd == protocol.CMD_GET_VOLTAGE:
                    raw = 5000 + ch if self.power[ch] else 8 + ch
                else:
                    raw = 100 + ch if self.power[ch] else 0
                self._write(protocol.encode_v2(cmd, protocol.channel_bit(ch),
                                               raw >> 8, raw & 0xFF))

    def inject(self, cmd, p0, value):
        self._write(protocol.encode_v1(cmd, p0, value))

    def disconnect(self):
        self.stop_event.set()
        try:
            os.close(self.master)
        except OSError:
            pass

    def close(self):
        self.stop_event.set()
        try:
            os.close(self.master)
        except OSError:
            pass
        try:
            os.close(self.slave)
        except OSError:
            pass
        self.join(timeout=1)
