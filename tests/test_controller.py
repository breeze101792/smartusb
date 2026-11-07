import unittest

from hubctl.app.controller import Controller
from hubctl.hal.base import (
    DeviceDriver,
    Identity,
    LinkError,
    LinkState,
    Mode,
    Rejected,
    StateMismatch,
    Status,
    Timeout,
)


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


def identity(firmware="V2.0", port="fake"):
    return Identity("HBP_USB2_4CH", 0, "V1.3", firmware, 4, 0, port)


class FakeDriver(DeviceDriver):
    supports_measurement = True
    supports_data_switch = True

    def __init__(self, ident=None):
        self._identity = ident or identity()
        self.power = {1: False, 2: False, 3: False, 4: True}
        self.data = {1: True, 2: True, 3: True, 4: True}
        self.mode = Mode.NORMAL
        self.closed = False
        self.fail_reads = False
        self.raise_link = False
        self.read_data_link = False
        self.old_readback = False
        self.bad_echo = False
        self.reject = False
        self.set_power_calls = []
        self.set_data_calls = []

    @classmethod
    def open(cls, endpoint, **options):
        return cls()

    def identity(self):
        return self._identity

    def close(self):
        self.closed = True

    def read_status(self):
        if self.raise_link:
            raise LinkError("unplugged")
        if self.fail_reads:
            raise Timeout("silent")
        return Status(self.mode, True, False)

    def read_power(self, channels):
        if self.raise_link:
            raise LinkError("unplugged")
        return {channel: self.power[channel] for channel in channels}

    def read_data(self, channels):
        if self.raise_link or self.read_data_link:
            raise LinkError("unplugged")
        return {channel: self.data[channel] for channel in channels}

    def read_voltage(self, channel):
        return 5000 + channel if self.power[channel] else 8 + channel

    def read_current(self, channel):
        return 100 + channel if self.power[channel] else 0

    def set_power(self, channels, on):
        self.set_power_calls.append((tuple(channels), on))
        if self.raise_link:
            raise LinkError("unplugged")
        if self.reject:
            raise Rejected("interlock")
        if self.bad_echo:
            raise StateMismatch("echo")
        for channel in channels:
            self.power[channel] = on
        if self.old_readback:
            for channel in channels:
                self.power[channel] = not on

    def set_data(self, channels, on):
        self.set_data_calls.append((tuple(channels), on))
        if self.bad_echo:
            raise StateMismatch("echo")
        for channel in channels:
            self.data[channel] = on


def run_cycle(controller, clock, ticks=15):
    controller.tick(clock())
    for _ in range(ticks):
        clock.advance(0.05)
        controller.tick(clock())


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.driver = FakeDriver()
        self.controller = Controller(
            open_fn=lambda: self.driver,
            clock=self.clock,
            sleep=self.clock.sleep)

    def tearDown(self):
        self.controller.close()

    def test_cycle_completes_and_populates_channels(self):
        run_cycle(self.controller, self.clock)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot.link, LinkState.LIVE)
        self.assertEqual(snapshot.identity.product, "HBP_USB2_4CH")
        self.assertEqual(snapshot.channels[4].power, True)
        self.assertEqual(snapshot.channels[1].power, False)
        self.assertIsNone(snapshot.channels[1].data)
        self.assertEqual(snapshot.channels[4].voltage_mv, 5004)
        self.assertLess(snapshot.last_cycle_age_s, 0.6)

    def test_stale_then_lost_after_the_deadline(self):
        run_cycle(self.controller, self.clock)
        self.clock.advance(2.1)
        self.assertEqual(self.controller.snapshot().link, LinkState.STALE)
        self.clock.advance(3.0)
        self.controller.tick(self.clock())
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot.link, LinkState.LOST)
        self.assertTrue(self.driver.closed)

    def test_repeated_timeouts_mark_the_link_lost(self):
        run_cycle(self.controller, self.clock)
        self.driver.fail_reads = True
        for _ in range(3):
            self.clock.advance(1.1)
            self.controller.tick(self.clock())
        self.assertEqual(self.controller.snapshot().link, LinkState.LOST)
        self.assertTrue(self.driver.closed)

    def test_toggle_power_reads_back(self):
        run_cycle(self.controller, self.clock)
        self.clock.advance(0.1)
        self.controller.toggle_power(1)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot.channels[1].power, True)
        self.assertIn("0x00 on", snapshot.last_action)
        self.assertEqual(self.driver.set_power_calls, [((1,), True)])
        self.assertEqual(snapshot.link, LinkState.LIVE)

    def test_readback_mismatch_is_not_a_link_failure(self):
        run_cycle(self.controller, self.clock)
        self.clock.advance(0.1)
        self.driver.old_readback = True
        self.controller.toggle_power(1)
        snapshot = self.controller.snapshot()
        self.assertIn("state differs", snapshot.last_action)
        self.assertNotEqual(snapshot.link, LinkState.LOST)
        self.assertFalse(self.driver.closed)

    def test_rejection_sets_interlock(self):
        run_cycle(self.controller, self.clock)
        self.clock.advance(0.1)
        self.driver.reject = True
        self.controller.toggle_power(1)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot.status.mode, Mode.INTERLOCK)
        self.assertIn("interlock", snapshot.last_action)
        self.assertEqual(snapshot.link, LinkState.LIVE)

    def test_data_needs_power(self):
        run_cycle(self.controller, self.clock)
        self.clock.advance(0.1)
        self.controller.toggle_data(1)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot.last_action,
                         "USB1 data needs power - key ignored")
        self.assertEqual(self.driver.set_data_calls, [])

    def test_no_device_retries_with_backoff(self):
        def missing():
            raise LinkError("no port")
        controller = Controller(open_fn=missing, clock=self.clock,
                                sleep=self.clock.sleep)
        controller.tick(self.clock())
        snapshot = controller.snapshot()
        self.assertEqual(snapshot.link, LinkState.LOST)
        self.assertIsNone(snapshot.identity)
        self.assertGreater(snapshot.reconnect_in_s, 0.0)
        self.clock.advance(1.1)
        controller.tick(self.clock())
        self.assertGreater(controller.snapshot().reconnect_in_s, 1.0)

    def test_reconnect_identity_gate_and_no_replay(self):
        run_cycle(self.controller, self.clock)
        self.clock.advance(0.1)
        self.controller.toggle_power(1)
        self.assertEqual(self.driver.set_power_calls, [((1,), True)])

        self.driver.raise_link = True
        self.clock.advance(1.1)
        self.controller.tick(self.clock())
        self.assertEqual(self.controller.snapshot().link, LinkState.LOST)

        other = FakeDriver(identity(firmware="V9.9", port="other"))
        self.controller._open_fn = lambda: other
        self.clock.advance(1.0)
        self.controller.tick(self.clock())
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot.link, LinkState.LOST)
        self.assertIn("different device", snapshot.last_action)
        self.assertTrue(other.closed)
        self.assertEqual(other.set_power_calls, [])

        same = FakeDriver(identity())
        self.controller._open_fn = lambda: same
        self.clock.advance(2.0)
        run_cycle(self.controller, self.clock)
        self.assertEqual(self.controller.snapshot().link, LinkState.LIVE)
        self.assertEqual(same.set_power_calls, [])


class ResultStringTests(unittest.TestCase):
    """Every result line of docs/ui/menu.md section 6."""

    def setUp(self):
        self.clock = Clock()
        self.driver = FakeDriver()
        self.controller = Controller(
            open_fn=lambda: self.driver,
            clock=self.clock,
            sleep=self.clock.sleep)
        run_cycle(self.controller, self.clock)
        self.clock.advance(0.1)

    def tearDown(self):
        self.controller.close()

    def note(self):
        return self.controller.snapshot().last_action

    def power_on(self, channel):
        self.driver.power[channel] = True

    def poll_again(self):
        self.clock.advance(1.1)
        run_cycle(self.controller, self.clock)
        self.clock.advance(0.1)

    def test_power_on_verified(self):
        self.controller.toggle_power(2)
        self.assertEqual(self.note(),
                         "USB2 on - echo ok, 0x00 on, 0x08 on")

    def test_power_off_verified(self):
        self.power_on(2)
        self.driver.data[2] = False
        self.poll_again()
        self.controller.toggle_power(2)
        self.assertEqual(self.note(),
                         "USB2 off - echo ok, 0x00 off, 0x08 off")

    def test_data_on_verified(self):
        self.power_on(2)
        self.driver.data[2] = False
        self.poll_again()
        self.controller.toggle_data(2)
        self.assertEqual(self.note(), "USB2 data on - echo ok, 0x08 on")

    def test_data_off_verified(self):
        self.power_on(2)
        self.poll_again()
        self.controller.toggle_data(2)
        self.assertEqual(self.note(), "USB2 data off - echo ok, 0x08 off")

    def test_echo_mismatch(self):
        self.power_on(2)
        self.poll_again()
        self.driver.bad_echo = True
        self.controller.toggle_power(2)
        self.assertEqual(self.note(), "USB2 off - echo differs, not applied")

    def test_readback_mismatch(self):
        self.power_on(2)
        self.poll_again()
        self.driver.old_readback = True
        self.controller.toggle_power(2)
        self.assertEqual(self.note(), "USB2 off - state differs (0x00 on)")

    def test_rejection(self):
        self.driver.reject = True
        self.controller.toggle_power(2)
        self.assertEqual(self.note(), "interlock - 0x01 rejected")

    def test_link_failure_names_the_port_and_the_verb(self):
        self.power_on(2)
        self.poll_again()
        self.driver.raise_link = True
        self.controller.toggle_power(2)
        self.assertEqual(self.note(), "USB2 off - no reply, link lost")
        self.assertEqual(self.controller.snapshot().link, LinkState.LOST)

    def test_link_loss_during_the_power_readback_keeps_the_link_text(self):
        self.power_on(2)
        self.poll_again()
        self.driver.read_data_link = True
        self.controller.toggle_power(2)
        snapshot = self.controller.snapshot()
        self.assertEqual(snapshot.last_action,
                         "USB2 off - no reply, link lost")
        self.assertEqual(snapshot.last_kind, "err")
        self.assertEqual(snapshot.link, LinkState.LOST)

    def test_link_loss_during_the_data_readback_is_not_a_timeout(self):
        self.power_on(2)
        self.poll_again()
        self.driver.read_data_link = True
        self.controller.toggle_data(2)
        self.assertEqual(self.note(), "USB2 data off - no reply, link lost")
        self.assertEqual(self.controller.snapshot().link, LinkState.LOST)

    def test_data_while_off(self):
        self.controller.toggle_data(2)
        self.assertEqual(self.note(),
                         "USB2 data needs power - key ignored")


if __name__ == "__main__":
    unittest.main()
