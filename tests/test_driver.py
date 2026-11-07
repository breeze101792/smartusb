import unittest

from hubctl.devices.smartusbhub import protocol
from hubctl.devices.smartusbhub.driver import SmartUSBHubDriver
from hubctl.devices.smartusbhub.transport import CommandNotAllowed
from hubctl.hal.base import Mode, Rejected, StateMismatch, Timeout

from .fakehub import FakeHub


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.hub = FakeHub()
        self.hub.start()
        self.driver = SmartUSBHubDriver.open(self.hub.port)

    def tearDown(self):
        self.driver.close()
        self.hub.close()

    def test_identity(self):
        identity = self.driver.identity()
        self.assertEqual(identity.product, "HBP_USB2_4CH")
        self.assertEqual(identity.channels, 4)
        self.assertEqual(identity.hardware, "V1.3")
        self.assertEqual(identity.firmware, "V2.0")
        self.assertEqual(identity.address, 0)
        self.assertEqual(identity.port, self.hub.port)

    def test_status(self):
        status = self.driver.read_status()
        self.assertEqual(status.mode, Mode.NORMAL)
        self.assertTrue(status.buttons_enabled)
        self.assertFalse(status.restore_enabled)

    def test_read_channels_applies_the_off_data_rule(self):
        self.hub.power[4] = 1
        readings = self.driver.read_channels([1, 2, 3, 4])
        self.assertFalse(readings[1].power)
        self.assertIsNone(readings[1].data)
        self.assertTrue(readings[4].power)
        self.assertTrue(readings[4].data)
        self.assertEqual(readings[4].voltage_mv, 5004)
        self.assertEqual(readings[1].voltage_mv, 9)

    def test_set_power(self):
        self.driver.set_power([1], True)
        self.assertEqual(self.hub.power[1], 1)
        self.assertEqual(self.driver.read_power([1])[1], True)
        self.assertTrue(self.driver.read_data([1])[1])

    def test_interlock_rejects_power(self):
        self.hub.mode = 1
        with self.assertRaises(Rejected):
            self.driver.set_power([1], True)

    def test_bad_echo_is_a_state_mismatch(self):
        self.hub.bad_echo = True
        with self.assertRaises(StateMismatch):
            self.driver.set_power([1], True)

    def test_silence_is_a_timeout(self):
        self.hub.silent = True
        with self.assertRaises(Timeout):
            self.driver.read_status()

    def test_allow_list_blocks_nvm_writes(self):
        with self.assertRaises(CommandNotAllowed):
            self.driver.link.send(protocol.CMD_SET_MODE, 0, 1)
        self.assertNotIn(protocol.CMD_SET_MODE,
                         [packet[0] for packet in self.hub.received])

    def test_unsolicited_report_does_not_break_a_poll(self):
        self.hub.inject(protocol.CMD_GET_POWER, protocol.channel_bit(1), 1)
        values = self.driver.read_power([1, 2, 3, 4])
        self.assertEqual(values, {1: False, 2: False, 3: False, 4: False})

    def test_out_of_range_channel(self):
        with self.assertRaises(ValueError):
            self.driver.read_power([5])


if __name__ == "__main__":
    unittest.main()
