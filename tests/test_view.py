import html
import re
import unittest
from pathlib import Path

from hubctl.app import menu, policy
from hubctl.app.view import (
    ANSI_RE,
    FOOTER_AUTO,
    FOOTER_CONTROL,
    FOOTER_CONTROL_LOST,
    FOOTER_DEVICE,
    FOOTER_MENU,
    FOOTER_NO_DEVICE,
    FOOTER_POLICY,
    INTERLOCK_BANNER,
    vlen,
)
from hubctl.hal.base import ChannelReading, LinkState, Mode
from hubctl.hal.usbmap import UsbDevice

from .helpers import (
    SELECTED,
    frame,
    make_auto,
    make_no_device,
    make_snapshot,
    plain,
)


def make_port_on():
    snapshot = make_snapshot(
        action="connected HBP_USB2_4CH on /dev/ttyACM0")
    snapshot.channels[2] = ChannelReading(True, True, 4610, 0)
    return snapshot

MOCKUP = Path(__file__).resolve().parents[1] / "docs/ui/mockup/index.html"


def mockup_frames():
    """Every ``<pre>`` frame of the mockup, tags stripped, in order."""
    text = MOCKUP.read_text(encoding="utf-8")
    blocks = re.findall(r'<pre class="frame[^"]*"[^>]*>(.*?)</pre>', text, re.S)
    return [html.unescape(re.sub(r"<[^>]+>", "", block)).rstrip("\n")
            for block in blocks]


def make_auto(paused=False):
    auto = policy.empty()
    auto.paused = paused
    auto.policies[2] = policy.Policy(
        enabled=True, cycle_s=600, overcurrent_ma=1500, retry_s=30,
        recovery_s=300, schedule=(480, 1080))
    auto.policies[3] = policy.Policy(enabled=True, cycle_s=1800)
    return auto


def mockup_cases():
    """(snapshot, state, width, height, render options), in file order."""
    auto = make_auto()
    return [
        (make_snapshot(), menu.State(port_index=1), 80, 24, {}),
        (make_snapshot(link=LinkState.STALE, age=2.3),
         menu.State(port_index=1), 80, 24, {}),
        (make_snapshot(link=LinkState.LOST, reconnect=4.0,
                       action="USB2 off - no reply, link lost", kind="err"),
         menu.State(port_index=1), 80, 24, {}),
        (make_snapshot(mode=Mode.INTERLOCK,
                       action="interlock - 0x01 rejected", kind="err"),
         menu.State(port_index=1), 80, 24, {}),
        (make_no_device(), menu.State(), 80, 24, {}),
        (make_snapshot(), menu.State(port_index=1), 60, 16, {}),
        (make_snapshot(), menu.State(port_index=1), 80, 24, {"auto": auto}),
        (make_snapshot(action="USB2 on - auto cycle"),
         menu.State(menu.POLICY, port=2), 80, 24, {"auto": auto}),
        (make_snapshot(action="USB2 on - auto cycle"),
         menu.State(menu.POLICY, port=2), 60, 16, {"auto": auto}),
        (make_snapshot(), menu.State(menu.MENU), 80, 24, {}),
        (make_snapshot(), menu.State(menu.MENU), 60, 16, {}),
        (make_snapshot(action="connected HBP_USB2_4CH on /dev/ttyACM0"),
         menu.State(menu.DEVICE), 80, 24, {}),
        (make_snapshot(action="connected HBP_USB2_4CH on /dev/ttyACM0"),
         menu.State(menu.HELP), 80, 24, {}),
        (make_snapshot(action="connected HBP_USB2_4CH on /dev/ttyACM0"),
         menu.State(menu.PORT, port=2), 80, 24, {}),
        (make_port_on(), menu.State(menu.PORT, port=2), 80, 24,
         {"usb": UsbDevice("045e", "028e", "Xbox 360 pad")}),
        (make_snapshot(action="connected HBP_USB2_4CH on /dev/ttyACM0",
                       port="/dev/ttyACM0", port_choices=("/dev/ttyACM0",)),
         menu.State(menu.SETTINGS), 80, 24, {}),
    ]


class PortDetailTests(unittest.TestCase):
    def test_usb_rows_show_the_device(self):
        snapshot = make_port_on()
        lines = plain(frame(snapshot, menu.State(menu.PORT, port=2),
                            usb=UsbDevice("045e", "028e", "Xbox 360 pad")))
        self.assertIn("045e:028e", lines[8])
        self.assertIn("Xbox 360 pad", lines[9])

    def test_data_off_explains_the_missing_usb_info(self):
        lines = plain(frame(make_snapshot(), menu.State(menu.PORT, port=2)))
        self.assertIn("data off", lines[8])

    def test_no_device_on_this_host_says_so(self):
        lines = plain(frame(make_port_on(), menu.State(menu.PORT, port=2)))
        self.assertIn("no device", lines[8])


class MockupTests(unittest.TestCase):
    def test_all_mockup_frames_reproduce_character_for_character(self):
        expected = mockup_frames()
        cases = mockup_cases()
        self.assertEqual(len(expected), 16)
        self.assertEqual(len(cases), 16)
        for number, (block, case) in enumerate(zip(expected, cases)):
            snapshot, state, width, height, options = case
            lines = plain(frame(snapshot, state, width, height, **options))
            self.assertEqual("\n".join(lines), block, f"frame {number}")


class FrameTests(unittest.TestCase):
    def test_live_frame_is_exactly_sized(self):
        lines = frame(make_snapshot(), menu.State())
        self.assertEqual(len(lines), 24)
        self.assertTrue(all(vlen(line) == 80 for line in lines))
        text = plain(lines)
        self.assertTrue(text[0].startswith("│HUBCTL  USB CONTROL"))
        self.assertTrue(text[0].endswith(" live  │"))
        self.assertTrue(text[4].startswith("│   USB PORT 1"))
        for value in ("ON", "data on", "4.61 V", "0.00 A", "0.00 W"):
            self.assertIn(value, text[4])
        self.assertTrue(text[5].startswith("│   USB PORT 2"))
        for value in ("off", "-", "(202 mV)", "0.00 W"):
            self.assertIn(value, text[5])
        self.assertTrue(text[4].endswith("│"))

    def test_frame_at_minimum_size(self):
        lines = frame(make_snapshot(), menu.State(), 60, 16)
        self.assertEqual(len(lines), 16)
        self.assertTrue(all(vlen(line) == 60 for line in lines))
        text = plain(lines)
        self.assertIn("USB PORT 4", text[7])
        self.assertIn("last", text[14])
        self.assertIn("SPACE power", text[15])

    def test_every_width_keeps_the_frame_width(self):
        snapshot = make_snapshot(channels=7)
        for width in (60, 80, 120, 200):
            lines = frame(snapshot, menu.State(), width, 16)
            self.assertEqual(len(lines), 16)
            self.assertTrue(all(vlen(line) == width for line in lines), width)

    def test_rails_and_bars(self):
        lines = plain(frame(make_snapshot(), menu.State()))
        for line in lines:
            self.assertEqual(line[0], "│")
            self.assertEqual(line[79], "│")
        self.assertIn("HUBCTL  USB CONTROL", lines[0])
        self.assertIn("SPACE power", lines[23])
        self.assertIn("last", lines[22])

    def test_ascii_rails(self):
        lines = plain(frame(make_snapshot(), menu.State(), 60, 16, utf8=False))
        for line in lines:
            self.assertEqual(line[0], "|")
            self.assertEqual(line[59], "|")
        self.assertFalse(any("│" in line for line in lines))


class SweepTests(unittest.TestCase):
    STATES = (
        ("live", lambda: make_snapshot()),
        ("stale", lambda: make_snapshot(link=LinkState.STALE, age=3.4)),
        ("lost", lambda: make_snapshot(link=LinkState.LOST, reconnect=4.0)),
        ("interlock", lambda: make_snapshot(mode=Mode.INTERLOCK)),
        ("no device", make_no_device),
    )

    def test_every_screen_state_and_size_is_exactly_sized(self):
        screens = (menu.State(), menu.State(menu.MENU),
                   menu.State(menu.DEVICE), menu.State(menu.POLICY, port=2))
        for label, build in self.STATES:
            snapshot = build()
            for state in screens:
                for width in (60, 80, 120, 200):
                    for height in (16, 24, 40):
                        lines = frame(snapshot, state, width, height,
                                      auto=make_auto())
                        self.assertEqual(len(lines), height,
                                         (label, state.screen, width, height))
                        for line in lines:
                            self.assertEqual(
                                vlen(line), width,
                                (label, state.screen, width, height))


class ClippingTests(unittest.TestCase):
    def assert_balanced(self, line):
        index = 0
        while True:
            index = line.find("\x1b", index)
            if index < 0:
                return
            match = ANSI_RE.match(line, index)
            self.assertIsNotNone(match, repr(line[index:index + 10]))
            index = match.end()

    def test_long_action_and_product_clip_cleanly(self):
        snapshot = make_snapshot(action="x" * 120, product="P" * 80)
        for width, height in ((60, 16), (80, 24)):
            lines = frame(snapshot, menu.State(), width, height)
            self.assertEqual(len(lines), height)
            for line in lines:
                self.assertEqual(vlen(line), width)
                self.assert_balanced(line)
                text = ANSI_RE.sub("", line)
                self.assertTrue(text.endswith("│"))
                rail = line.rfind("│")
                self.assertNotEqual(line[rail - 1], "\x1b")

    def test_last_text_clips_to_forty_columns(self):
        text = plain(frame(make_snapshot(action="y" * 120), menu.State(),
                           60, 16))
        row = text[14]
        self.assertEqual(row[12:52], "y" * 40)
        self.assertEqual(row[59], "│")

    def test_monochrome_output_has_no_colour(self):
        snapshot = make_snapshot(action="x" * 120, product="P" * 80)
        lines = frame(snapshot, menu.State(), 60, 16, color=False)
        self.assertTrue(all("38;5;" not in line for line in lines))
        self.assertIn(SELECTED, lines[4])


class ListTests(unittest.TestCase):
    def test_port_rows_show_power_and_measurements(self):
        text = plain(frame(make_snapshot(), menu.State()))
        self.assertTrue(text[6].startswith("│   USB PORT 3"))
        for value in ("ON", "data off", "5.02 V", "0.21 A", "1.05 W"):
            self.assertIn(value, text[6])
        self.assertNotIn("CHANNEL", "\n".join(text))

    def test_seven_ports_fit_at_minimum_size(self):
        snapshot = make_snapshot(channels=7)
        text = plain(frame(snapshot, menu.State(), 60, 16))
        self.assertIn("USB PORT 7", text[10])
        self.assertIn("last", text[14])
        self.assertIn("SPACE power", text[15])

    def test_off_port_shows_dash_and_residual_voltage(self):
        text = plain(frame(make_snapshot(), menu.State()))
        row = text[5]
        self.assertTrue(row.startswith("│   USB PORT 2"))
        for value in ("off", "-", "(202 mV)"):
            self.assertIn(value, row)

    def test_selection_is_the_only_reverse_span_in_the_body(self):
        snapshot = make_snapshot()
        for selected in range(4):
            lines = frame(snapshot, menu.State(port_index=selected),
                          color=False)
            body = lines[1:-1]
            hits = [index for index, line in enumerate(body, 1)
                    if SELECTED in line]
            self.assertEqual(len(hits), 1, selected)
            self.assertEqual(hits[0], 4 + selected)
            self.assertEqual(body[hits[0] - 1].count(SELECTED), 1)
            self.assertIn(SELECTED, lines[0])
            self.assertIn(SELECTED, lines[-1])

    def test_selected_port_span_starts_at_the_item_column(self):
        lines = frame(make_snapshot(), menu.State(port_index=1))
        start = lines[5].index(SELECTED)
        self.assertEqual(vlen(lines[5][:start]), 4)
        self.assertTrue(ANSI_RE.sub("", lines[5][:start]).endswith("│   "))
        row = ANSI_RE.sub("", lines[5])
        for value in ("USB PORT 2", "off", "(202 mV)", "0.00 W"):
            self.assertIn(value, row)

    def test_every_port_label_is_bold(self):
        lines = frame(make_snapshot(), menu.State(port_index=1),
                      color=False)
        self.assertEqual(lines[4].count("\x1b[1m"), 1)


class MenuTests(unittest.TestCase):
    def test_menu_block_replaces_the_rows_and_keeps_the_chrome(self):
        control = frame(make_snapshot(), menu.State(port_index=1))
        opened = frame(make_snapshot(), menu.State(menu.MENU, port_index=1))
        self.assertEqual(control[0], opened[0])
        self.assertEqual(control[2], opened[2])
        self.assertEqual(control[-2], opened[-2])
        self.assertIn("GLOBAL MENU", plain(opened)[4])
        self.assertIn("Device", plain(opened)[5])
        self.assertNotIn("USB PORT", "\n".join(plain(opened)))
        self.assertIn(FOOTER_MENU, plain(opened)[-1])
        self.assertIn(FOOTER_CONTROL, plain(control)[-1])

    def test_menu_heading_is_dim_and_the_item_is_selected(self):
        lines = frame(make_snapshot(), menu.State(menu.MENU))
        self.assertIn("2;38;5;244", lines[4])
        self.assertEqual(lines[5].count(SELECTED), 1)

    def test_enter_opens_the_device_page(self):
        lines = frame(make_snapshot(), menu.State(menu.DEVICE))
        text = plain(lines)
        self.assertIn("HUBCTL  DEVICE", text[0])
        self.assertIn("ENTER back   q back", text[23])

    def test_no_device_menu_still_opens(self):
        lines = frame(make_no_device(), menu.State(menu.MENU))
        text = plain(lines)
        self.assertIn("no device", text[0])
        self.assertIn("GLOBAL MENU", text[4])
        self.assertIn("Device", text[5])
        self.assertIn(FOOTER_MENU, text[23])
        self.assertNotIn("last", text[22])


class StateTests(unittest.TestCase):
    def test_stale_dims_every_value(self):
        lines = frame(make_snapshot(link=LinkState.STALE, age=3.4),
                      menu.State())
        text = plain(lines)
        self.assertIn("stale 3.4 s", text[0])
        self.assertIn("stale 3.4 s", text[2])
        self.assertIn("2;38;5;244", lines[5])

    def test_lost_shows_unknown_fields_and_retry(self):
        snapshot = make_snapshot(link=LinkState.LOST, reconnect=2.0)
        lines = frame(snapshot, menu.State())
        text = plain(lines)
        self.assertIn("lost - retry 2 s", text[0])
        self.assertTrue(text[4].startswith("│   USB PORT 1"))
        self.assertEqual(text[4].count("?"), 5)
        self.assertTrue(text[4].endswith("│"))
        self.assertIn(FOOTER_CONTROL_LOST, text[23])

    def test_lost_values_carry_the_dim_span(self):
        lines = frame(make_snapshot(link=LinkState.LOST, reconnect=2.0),
                      menu.State(port_index=2))
        self.assertEqual(lines[4].count("2;38;5;244"), 5)
        self.assertNotIn("38;5;78", lines[4])

    def test_interlock_banner_on_row_four(self):
        lines = frame(make_snapshot(mode=Mode.INTERLOCK), menu.State())
        text = plain(lines)
        self.assertIn("interlock", text[0])
        self.assertIn(INTERLOCK_BANNER, text[3])
        self.assertTrue(text[3].endswith("│"))
        self.assertIn("38;5;220", lines[3])
        self.assertIn("38;5;78", lines[6])

    def test_interlock_menu_keeps_the_banner(self):
        text = plain(frame(make_snapshot(mode=Mode.INTERLOCK),
                           menu.State(menu.MENU)))
        self.assertIn(INTERLOCK_BANNER, text[3])

    def test_no_device_screen(self):
        snapshot = make_no_device()
        lines = frame(snapshot, menu.State())
        text = plain(lines)
        self.assertIn("no device", text[0])
        self.assertIn("discovery 1a86:fe0c   no port   retry 4 s", text[2])
        self.assertIn("no SmartUSBHub CMD port", text[4])
        self.assertIn("pass --port", text[5])
        self.assertNotIn("USB PORT", "\n".join(text))
        self.assertIn(FOOTER_NO_DEVICE, text[23])
        self.assertNotIn("last", text[22])


class DeviceTests(unittest.TestCase):
    def test_device_fields(self):
        lines = frame(make_snapshot(), menu.State(menu.DEVICE))
        text = plain(lines)
        self.assertIn("HUBCTL  DEVICE", text[0])
        self.assertIn("port /dev/ttyACM0", text[2])
        expected = [("ports", "4"), ("product", "HBP_USB2_4CH"),
                    ("firmware", "V2.0"), ("hardware", "V1.3"),
                    ("address", "0x0005"), ("buttons", "enabled"),
                    ("restore", "disabled")]
        for offset, (label, value) in enumerate(expected):
            row = text[4 + offset]
            self.assertTrue(row.startswith("│   " + label), row)
            self.assertTrue(row.rstrip(" │").endswith(value), row)
        self.assertEqual(text[12].strip(" │"), "Back")

    def test_device_selection_is_the_back_row(self):
        lines = frame(make_snapshot(), menu.State(menu.DEVICE), color=False)
        body = lines[1:-1]
        hits = [index for index, line in enumerate(body, 1)
                if SELECTED in line]
        self.assertEqual(hits, [12])

    def test_lost_device_values_are_unknown(self):
        snapshot = make_snapshot(link=LinkState.LOST, reconnect=2.0)
        text = plain(frame(snapshot, menu.State(menu.DEVICE)))
        self.assertIn("lost", text[2])
        for offset in range(7):
            self.assertTrue(text[4 + offset].rstrip(" │").endswith("?"),
                            text[4 + offset])

    def test_no_device_device_page_is_all_unknown(self):
        text = plain(frame(make_no_device(), menu.State(menu.DEVICE)))
        for offset in range(7):
            self.assertTrue(text[4 + offset].rstrip(" │").endswith("?"),
                            text[4 + offset])
        self.assertNotIn("last", text[22])


class AutoScreenTests(unittest.TestCase):
    def test_port_rows_are_marked_at_column_three(self):
        text = plain(frame(make_snapshot(), menu.State(), auto=make_auto()))
        self.assertEqual(text[4][2], " ")        # USB PORT 1, no policy
        self.assertEqual(text[5][2], "A")        # USB PORT 2, enabled
        self.assertEqual(text[6][2], "A")        # USB PORT 3, enabled
        self.assertEqual(text[7][2], " ")
        self.assertTrue(text[5].startswith("│ A "))

    def test_no_marker_without_a_policy(self):
        text = plain(frame(make_snapshot(), menu.State()))
        self.assertNotIn(" A USB PORT", "\n".join(text))

    def test_status_counts_enabled_ports(self):
        text = plain(frame(make_snapshot(), menu.State(), auto=make_auto()))
        self.assertIn("poll 1.0 s   auto 2", text[2])

    def test_status_says_paused(self):
        auto = make_auto(paused=True)
        text = plain(frame(make_snapshot(), menu.State(), auto=auto))
        self.assertIn("auto paused", text[2])
        self.assertNotIn("auto 2", text[2])

    def test_status_says_poll_too_long(self):
        text = plain(frame(make_snapshot(poll=2.0), menu.State(),
                          auto=make_auto()))
        self.assertIn("auto off - poll too long", text[2])

    def test_sixty_columns_keep_poll_and_auto(self):
        text = plain(frame(make_snapshot(), menu.State(), 60, 16,
                          auto=make_auto()))
        self.assertIn("poll 1.0 s", text[2])
        self.assertIn("auto 2", text[2])
        self.assertEqual(text[2].rstrip(" │"),
                         "│  port /dev/ttyACM0   normal   live   poll 1.0 s"
                         "   auto 2")

    def test_the_policy_page_names_the_port_and_clears_on_exit(self):
        text = plain(frame(make_snapshot(), menu.State(menu.POLICY, port=2),
                           auto=make_auto()))
        self.assertIn("HUBCTL  AUTO - USB PORT 2", text[0])
        self.assertEqual(text[13].rstrip(" │"),
                         "│   rules clear when hubctl exits")
        self.assertEqual(text[12].strip(" │"), "Back")

    def test_policy_page_shows_every_value(self):
        text = plain(frame(make_snapshot(),
                           menu.State(menu.POLICY, port=2), auto=make_auto()))
        self.assertIn("HUBCTL  AUTO - USB PORT 2", text[0])
        expected = [("enabled", "on"), ("cycle", "10 min"),
                    ("overcurrent", "1.5 A"), ("retry", "30 s"),
                    ("recovery", "5 min"), ("schedule", "on"),
                    ("from", "08"), ("to", "18")]
        for offset, (label, value) in enumerate(expected):
            row = text[4 + offset]
            self.assertTrue(row.startswith("│   " + label), row)
            self.assertTrue(row.rstrip(" │").endswith(value), row)
        self.assertEqual(text[12].strip(" │"), "Back")

    def test_policy_page_selection_is_the_enabled_row(self):
        lines = frame(make_snapshot(), menu.State(menu.POLICY, port=2),
                      color=False, auto=make_auto())
        body = lines[1:-1]
        hits = [index for index, line in enumerate(body, 1)
                if SELECTED in line]
        self.assertEqual(hits, [4])

    def test_policy_page_dims_the_schedule_window_when_it_is_off(self):
        auto = make_auto()
        auto.policies[1] = policy.Policy(enabled=False)
        text = plain(frame(make_snapshot(), menu.State(menu.POLICY, port=1),
                           auto=auto))
        self.assertTrue(text[4].rstrip(" │").endswith("off"))
        self.assertTrue(text[9].rstrip(" │").endswith("off"))
        self.assertTrue(text[10].rstrip(" │").endswith("--"))
        self.assertTrue(text[11].rstrip(" │").endswith("--"))


class SelectionTests(unittest.TestCase):
    def test_selected_port_with_a_marker_still_starts_at_the_item_column(self):
        lines = frame(make_snapshot(), menu.State(port_index=1),
                      auto=make_auto())
        start = lines[5].index(SELECTED)
        self.assertEqual(vlen(lines[5][:start]), 4)


class FooterTests(unittest.TestCase):
    CASES = (
        (make_snapshot(), menu.State(), FOOTER_CONTROL),
        (make_snapshot(link=LinkState.LOST, reconnect=4.0), menu.State(),
         FOOTER_CONTROL_LOST),
        (make_no_device(), menu.State(), FOOTER_NO_DEVICE),
        (make_snapshot(), menu.State(menu.MENU), FOOTER_MENU),
        (make_snapshot(), menu.State(menu.DEVICE), FOOTER_DEVICE),
        (make_snapshot(), menu.State(menu.POLICY, port=2), FOOTER_POLICY),
    )

    def test_every_footer_fits_the_minimum_width(self):
        for snapshot, state, expected in self.CASES:
            text = plain(frame(snapshot, state, 60, 16, auto=make_auto()))
            self.assertIn(expected, text[15])
            self.assertLessEqual(len(expected), 51)

    def test_footer_texts(self):
        self.assertEqual(FOOTER_CONTROL,
                         "SPACE power   d data   a auto   p pause   q quit")
        self.assertEqual(FOOTER_CONTROL_LOST,
                         "r retry   a auto   p pause   q quit")
        self.assertEqual(FOOTER_NO_DEVICE,
                         "r retry   a auto   p pause   q quit")
        self.assertEqual(FOOTER_MENU, "ENTER open   m close   q close")
        self.assertEqual(FOOTER_DEVICE, "ENTER back   q back")
        self.assertEqual(FOOTER_AUTO, "ENTER open   p pause   q back")
        self.assertEqual(FOOTER_POLICY,
                         "LEFT/RIGHT change   p pause   ENTER back   q back")


if __name__ == "__main__":
    unittest.main()
