import unittest

from hubctl.app.view import ANSI_RE, render
from hubctl.hal.base import (
    ChannelReading,
    Identity,
    LinkState,
    Mode,
    Snapshot,
    Status,
)


def make_snapshot(link=LinkState.LIVE, mode=Mode.NORMAL, age=0.4,
                  action="poll ok", detail="ok"):
    identity = Identity("HBP_USB2_4CH", 0, "V1.3", "V2.0", 4, 0, "/dev/ttyACM0")
    channels = {
        1: ChannelReading(False, None, 202, 0),
        2: ChannelReading(False, None, 198, 0),
        3: ChannelReading(False, None, 205, 0),
        4: ChannelReading(True, True, 4614, 0),
    }
    return Snapshot(
        identity=identity,
        status=Status(mode, True, False),
        channels=channels,
        link=link,
        last_cycle_age_s=age,
        last_action=action,
        last_kind=detail,
        poll_interval_s=1.0,
        reconnect_in_s=2.0 if link == LinkState.LOST else None,
    )


def strip(line):
    return ANSI_RE.sub("", line)


class ViewTests(unittest.TestCase):
    def test_live_frame_is_exactly_sized(self):
        lines = render(make_snapshot(), 2, 80, 24, color=False)
        self.assertEqual(len(lines), 24)
        self.assertTrue(all(len(line) == 80 for line in lines))
        text = "\n".join(lines)
        self.assertIn("hubctl", text)
        self.assertIn("CH4", text)
        self.assertIn("(202 mV)", text)
        self.assertIn("4.61 V", text)
        self.assertIn("> CH3", text)
        self.assertIn("live", text)

    def test_no_colour_emits_no_escape_sequences(self):
        lines = render(make_snapshot(), 0, 80, 24, color=False)
        for line in lines:
            self.assertNotIn("\x1b", line)

    def test_colour_uses_reverse_for_selection(self):
        lines = render(make_snapshot(), 2, 80, 24, color=True)
        self.assertIn("\x1b[7m", lines[7])

    def test_off_channel_data_is_a_dash(self):
        lines = render(make_snapshot(), 0, 80, 24, color=False)
        row = lines[6]
        self.assertEqual(row[17], "-")
        self.assertIn("(198 mV)", row)

    def test_lost_has_unknown_values_and_a_retry_footer(self):
        lines = render(make_snapshot(link=LinkState.LOST), 0, 80, 24, color=False)
        text = "\n".join(lines)
        self.assertIn("?       ?      ?", text)
        self.assertIn("lost - reconnect in 2 s", text)
        self.assertIn("retry now", text)

    def test_stale_shows_age_and_disables_controls(self):
        lines = render(make_snapshot(link=LinkState.STALE, age=3.4), 0, 80, 24, color=False)
        text = "\n".join(lines)
        self.assertIn("stale 3.4 s", text)
        self.assertIn("space -", text)

    def test_interlock_banner_and_disabled_controls(self):
        lines = render(make_snapshot(mode=Mode.INTERLOCK), 0, 80, 24, color=False)
        text = "\n".join(lines)
        self.assertIn("interlock", text)
        self.assertIn("switching disabled", text)
        self.assertIn("space -", text)

    def test_small_height_drops_the_device_block(self):
        lines = render(make_snapshot(), 0, 60, 16, color=False)
        self.assertEqual(len(lines), 16)
        self.assertTrue(all(len(line) == 60 for line in lines))
        text = "\n".join(lines)
        self.assertNotIn("settings", text)
        self.assertIn("CH4", text)

    def test_no_device_frame(self):
        snapshot = Snapshot(
            identity=None,
            status=Status(Mode.UNKNOWN),
            channels={},
            link=LinkState.LOST,
            last_cycle_age_s=0.0,
            last_action="no SmartUSBHub CMD port found; pass --port",
            last_kind="err",
            reconnect_in_s=1.0,
        )
        lines = render(snapshot, 0, 80, 24, color=False)
        text = "\n".join(lines)
        self.assertEqual(len(lines), 24)
        self.assertIn("no SmartUSBHub CMD port", text)
        self.assertIn("pass --port", text)

    def test_ascii_borders(self):
        lines = render(make_snapshot(), 0, 60, 16, color=False, utf8=False)
        self.assertTrue(lines[0].startswith("+-"))
        self.assertTrue(lines[-1].startswith("+-"))


if __name__ == "__main__":
    unittest.main()
