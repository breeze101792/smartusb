import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

from .fakehub import FakeHub

ROOT = Path(__file__).resolve().parents[1]


class AppPtyTests(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.NamedTemporaryFile(
            prefix="hubctl-state-", suffix=".json", delete=False)
        self.state.close()

    def tearDown(self):
        try:
            os.unlink(self.state.name)
        except OSError:
            pass

    def test_start_switch_and_quit(self):
        hub = FakeHub()
        hub.start()
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                   TERM="xterm-256color", NO_COLOR="1")
        process = subprocess.Popen(
            [sys.executable, "-m", "hubctl", "--port", hub.port,
             "--no-color", "--state", self.state.name],
            stdin=slave, stdout=slave, stderr=slave,
            env=env, cwd=str(ROOT), close_fds=True)
        os.close(slave)
        output = bytearray()

        def drain(seconds):
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.05)
                if not ready:
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                output.extend(chunk)

        try:

            def wait_for(needle, seconds=3):
                start = len(output)
                end = time.time() + seconds
                while needle not in bytes(output[start:]) and time.time() < end:
                    drain(0.1)
                return needle in bytes(output[start:])

            self.assertTrue(wait_for(b"HUBCTL"))
            self.assertTrue(wait_for(b"USB PORT 4"))
            self.assertTrue(wait_for(b"live"))

            os.write(master, b" ")
            self.assertTrue(wait_for(b"USB1 on - echo"))

            os.write(master, b"m")
            self.assertTrue(wait_for(b"HUBCTL  MENU"))

            os.write(master, b"q")
            self.assertTrue(wait_for(b"SPACE power"))

            os.write(master, b"q")
            drain(0.5)
            code = process.wait(timeout=3)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            try:
                os.close(master)
            except OSError:
                pass
            hub.close()

        self.assertEqual(code, 0)
        self.assertIn(b"\x1b[?1049h", bytes(output))
        self.assertIn(b"\x1b[?1049l", bytes(output))
        self.assertIn(b"USB1 on - echo ok", bytes(output))
        self.assertIn(b"HUBCTL  MENU", bytes(output))
        self.assertIn((0x01, 0x01, 1), hub.received)

    def test_no_device_state_and_quit(self):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                   TERM="xterm-256color", NO_COLOR="1")
        process = subprocess.Popen(
            [sys.executable, "-m", "hubctl", "--port", "/dev/ttyHUBNOPE",
             "--no-color", "--state", self.state.name],
            stdin=slave, stdout=slave, stderr=slave,
            env=env, cwd=str(ROOT), close_fds=True)
        os.close(slave)
        output = bytearray()

        def drain(seconds):
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([master], [], [], 0.05)
                if not ready:
                    continue
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                output.extend(chunk)

        try:
            deadline = time.time() + 4
            while b"no SmartUSBHub" not in output and time.time() < deadline:
                drain(0.1)
            self.assertIn(b"no SmartUSBHub", bytes(output))
            os.write(master, b"q")
            drain(0.5)
            code = process.wait(timeout=3)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            try:
                os.close(master)
            except OSError:
                pass

        self.assertEqual(code, 0)
        self.assertIn(b"\x1b[?1049l", bytes(output))


if __name__ == "__main__":
    unittest.main()
