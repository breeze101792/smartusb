"""Downstream USB mapping from a fake sysfs tree."""

import os
import shutil
import tempfile
import unittest

from hubctl.hal.usbmap import UsbDevice, hub_paths, port_device


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii") as handle:
        handle.write(text + "\n")


class UsbMapTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        write(os.path.join(self.root, "3-3.4", "idVendor"), "1a86")
        write(os.path.join(self.root, "3-3.4", "idProduct"), "8091")
        write(os.path.join(self.root, "3-3.4.2", "idVendor"), "045e")
        write(os.path.join(self.root, "3-3.4.2", "idProduct"), "028e")
        write(os.path.join(self.root, "3-3.4.2", "product"), "Xbox 360 pad")

    def test_hub_paths_finds_the_data_hub(self):
        self.assertEqual(hub_paths(self.root), ["3-3.4"])

    def test_port_device_reads_the_child_of_that_port(self):
        self.assertEqual(port_device(2, self.root),
                         UsbDevice("045e", "028e", "Xbox 360 pad"))

    def test_other_ports_are_empty(self):
        self.assertIsNone(port_device(1, self.root))
        self.assertIsNone(port_device(3, self.root))

    def test_no_hub_means_no_device(self):
        self.assertIsNone(port_device(2, os.path.join(self.root, "missing")))


if __name__ == "__main__":
    unittest.main()
