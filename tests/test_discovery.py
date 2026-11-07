import tempfile
import unittest
from pathlib import Path

from hubctl.hal.discovery import candidate_ports


class DiscoveryTests(unittest.TestCase):
    def test_filters_by_vid_pid_through_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root / "class" / "tty" / "ttyACM0"
            node.mkdir(parents=True)
            usb = root / "devices" / "3-3.2"
            usb.mkdir(parents=True)
            (usb / "idVendor").write_text("1a86\n")
            (usb / "idProduct").write_text("fe0c\n")
            interface = usb / "3-3.2:1.0"
            interface.mkdir()
            (node / "device").symlink_to(interface)

            self.assertEqual(
                candidate_ports(str(root), ["/dev/ttyACM0"]), ["/dev/ttyACM0"])

    def test_rejects_the_data_hub(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            node = root / "class" / "tty" / "ttyACM1"
            node.mkdir(parents=True)
            usb = root / "devices" / "3-3.3"
            usb.mkdir(parents=True)
            (usb / "idVendor").write_text("1a86\n")
            (usb / "idProduct").write_text("8091\n")
            interface = usb / "3-3.3:1.0"
            interface.mkdir()
            (node / "device").symlink_to(interface)

            self.assertEqual(candidate_ports(str(root), ["/dev/ttyACM1"]), [])


if __name__ == "__main__":
    unittest.main()
