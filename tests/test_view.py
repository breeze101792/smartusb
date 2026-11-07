import html
import re
import unittest
from pathlib import Path

from hubctl.app import menu
from hubctl.app.view import (
    ANSI_RE,
    FOOTER_CONTROL,
    FOOTER_CONTROL_LOST,
    FOOTER_DEVICE,
    FOOTER_MENU,
    FOOTER_NO_DEVICE,
    INTERLOCK_BANNER,
    vlen,
)
from hubctl.hal.base import LinkState, Mode

from .helpers import SELECTED, frame, make_no_device, make_snapshot, plain

MOCKUP = Path(__file__).resolve().parents[1] / "docs/ui/mockup/index.html"


def mockup_frames():
    """The nine ``<pre>`` frames of the mockup, tags stripped, in order."""
    text = MOCKUP.read_text(encoding="utf-8")
    blocks = re.findall(r'<pre class="frame"[^>]*>(.*?)</pre>', text, re.S)
    return [html.unescape(re.sub(r"<[^>]+>", "", block)).rstrip("\n")
            for block in blocks]


def mockup_cases():
    """(snapshot, state, width) for frames A, D, E, F, G, H, B, I, C."""
    return [
        (make_snapshot(), menu.State(port_index=1), 80, 24),
        (make_snapshot(link=LinkState.STALE, age=2.3),
         menu.State(port_index=1), 80, 24),
        (make_snapshot(link=LinkState.LOST, reconnect=4.0,
                       action="USB2 off - no reply, link lost", kind="err"),
         menu.State(port_index=1), 80, 24),
        (make_snapshot(mode=Mode.INTERLOCK,
                       action="interlock - 0x01 rejected",
                       kind="err"), menu.State(port_index=1), 80, 24),
        (make_no_device(), menu.State(), 80, 24),
        (make_snapshot(), menu.State(port_index=1), 60, 16),
        (make_snapshot(), menu.State(menu.MENU, port_index=1), 80, 24),
        (make_snapshot(), menu.State(menu.MENU, port_index=1), 60, 16),
        (make_snapshot(action="connected HBP_USB2_4CH on /dev/ttyACM0"),
         menu.State(menu.DEVICE), 80, 24),
    ]


class MockupTests(unittest.TestCase):
    def test_all_nine_frames_reproduce_character_for_character(self):
        expected = mockup_frames()
        cases = mockup_cases()
        self.assertEqual(len(expected), 9)
        self.assertEqual(len(cases), 9)
        for number, (block, (snapshot, state, width, height)) in enumerate(
                zip(expected, cases)):
            lines = plain(frame(snapshot, state, width, height))
            self.assertEqual("\n".join(lines), block, f"frame {number}")


class FrameTests(unittest.TestCase):
    def test_live_frame_is_exactly_sized(self):
        lines = frame(make_snapshot(), menu.State())
        self.assertEqual(len(lines), 24)
        self.assertTrue(all(vlen(line) == 80 for line in lines))
        text = plain(lines)
        self.assertEqual(
            text[0],
            "   │HUBCTL  USB CONTROL"
            "                                              live  │    ")
        self.assertEqual(
            text[4],
            "   │   USB PORT 1  ON  data on   4.61 V     0.00 A"
            "                         │    ")
        self.assertEqual(
            text[5],
            "   │   USB PORT 2  off -         (202 mV)   0.00 A"
            "                         │    ")

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
            self.assertEqual(line[3], "│")
            self.assertEqual(line[75], "│")
        self.assertIn("HUBCTL  USB CONTROL", lines[0])
        self.assertIn("SPACE power", lines[23])
        self.assertIn("last", lines[22])

    def test_ascii_rails(self):
        lines = plain(frame(make_snapshot(), menu.State(), 60, 16, utf8=False))
        for line in lines:
            self.assertEqual(line[3], "|")
            self.assertEqual(line[55], "|")
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
                   menu.State(menu.DEVICE))
        for label, build in self.STATES:
            snapshot = build()
            for state in screens:
                for width in (60, 80, 120, 200):
                    for height in (16, 24, 40):
                        lines = frame(snapshot, state, width, height)
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
                self.assertTrue(text.endswith("│" + " " * 4))
                rail = line.rfind("│")
                self.assertNotEqual(line[rail - 1], "\x1b")

    def test_last_text_clips_to_forty_columns(self):
        text = plain(frame(make_snapshot(action="y" * 120), menu.State(),
                           60, 16))
        row = text[14]
        self.assertEqual(row[15:55], "y" * 40)
        self.assertEqual(row[55], "│")

    def test_monochrome_output_has_no_colour(self):
        snapshot = make_snapshot(action="x" * 120, product="P" * 80)
        lines = frame(snapshot, menu.State(), 60, 16, color=False)
        self.assertTrue(all("38;5;" not in line for line in lines))
        self.assertIn(SELECTED, lines[4])


class ListTests(unittest.TestCase):
    def test_port_rows_show_power_and_measurements(self):
        text = plain(frame(make_snapshot(), menu.State()))
        self.assertIn("USB PORT 3  ON  data off  5.02 V     0.21 A", text[6])
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
        self.assertEqual(row[23], "-")
        self.assertIn("(202 mV)", row)

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
        self.assertEqual(vlen(lines[5][:start]), 7)
        self.assertTrue(ANSI_RE.sub("", lines[5][:start]).endswith("│   "))
        self.assertIn("USB PORT 2  off -         (202 mV)   0.00 A ", lines[5])

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
        self.assertEqual(
            text[4],
            "   │   USB PORT 1  ?   ?         ?          ?"
            "                              │    ")
        self.assertIn(FOOTER_CONTROL_LOST, text[23])

    def test_lost_values_carry_the_dim_span(self):
        lines = frame(make_snapshot(link=LinkState.LOST, reconnect=2.0),
                      menu.State(port_index=2))
        self.assertEqual(lines[4].count("2;38;5;244"), 4)
        self.assertNotIn("38;5;78", lines[4])

    def test_interlock_banner_on_row_four(self):
        lines = frame(make_snapshot(mode=Mode.INTERLOCK), menu.State())
        text = plain(lines)
        self.assertIn("interlock", text[0])
        self.assertEqual(
            text[3],
            "   │   " + INTERLOCK_BANNER + "             │    ")
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
        self.assertEqual(
            text[2],
            "   │   discovery 1a86:fe0c   no port   retry 4 s"
            "                           │    ")
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
            self.assertTrue(
                text[4 + offset].startswith(
                    "   │   " + label.ljust(12) + value),
                text[4 + offset])
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


class FooterTests(unittest.TestCase):
    CASES = (
        (make_snapshot(), menu.State(), FOOTER_CONTROL),
        (make_snapshot(link=LinkState.LOST, reconnect=4.0), menu.State(),
         FOOTER_CONTROL_LOST),
        (make_no_device(), menu.State(), FOOTER_NO_DEVICE),
        (make_snapshot(), menu.State(menu.MENU), FOOTER_MENU),
        (make_snapshot(), menu.State(menu.DEVICE), FOOTER_DEVICE),
    )

    def test_every_footer_fits_the_minimum_width(self):
        for snapshot, state, expected in self.CASES:
            text = plain(frame(snapshot, state, 60, 16))
            self.assertIn(expected, text[15])
            self.assertLessEqual(len(expected), 51)

    def test_footer_texts(self):
        self.assertEqual(FOOTER_CONTROL,
                         "SPACE power   d data   m menu   q quit")
        self.assertEqual(FOOTER_CONTROL_LOST,
                         "SPACE power   d data   r retry   m menu   q quit")
        self.assertEqual(FOOTER_NO_DEVICE, "r retry   m menu   q quit")
        self.assertEqual(FOOTER_MENU, "ENTER open   m close   q close")
        self.assertEqual(FOOTER_DEVICE, "ENTER back   q back")


if __name__ == "__main__":
    unittest.main()
