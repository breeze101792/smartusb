"""Key decoding from a raw fd."""

import os
import unittest

from hubctl.app.term import Terminal


class KeyDecodeTests(unittest.TestCase):
    def read(self, data):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, data)
            terminal = Terminal.__new__(Terminal)
            terminal.in_fd = read_fd
            return terminal.read_key(0.5)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_arrows(self):
        self.assertEqual(self.read(b"\x1b[A"), "up")
        self.assertEqual(self.read(b"\x1b[B"), "down")
        self.assertEqual(self.read(b"\x1b[C"), "right")
        self.assertEqual(self.read(b"\x1b[D"), "left")

    def test_lone_escape(self):
        self.assertEqual(self.read(b"\x1b"), "escape")

    def test_other_escape_sequences_are_ignored(self):
        for sequence in (b"\x1b[3~", b"\x1b[H", b"\x1bOP",
                         b"\x1b[5~", b"\x1bd"):
            self.assertEqual(self.read(sequence), "ignore", sequence)

    def test_plain_keys(self):
        self.assertEqual(self.read(b"q"), "q")
        self.assertEqual(self.read(b" "), "space")
        self.assertEqual(self.read(b"\r"), "enter")
        self.assertEqual(self.read(b"\x03"), "ctrl-c")


if __name__ == "__main__":
    unittest.main()
