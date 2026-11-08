import unittest
from unittest import mock

from hubctl.app import policy
from hubctl.app.tui import _loop
from hubctl.app.view import (
    ANSI_RE,
    FOOTER_CONTROL,
    FOOTER_DEVICE,
    FOOTER_MENU,
    FOOTER_POLICY,
    FOOTER_SETTINGS,
    FOOTER_NO_DEVICE,
)

from .helpers import make_auto, make_no_device, make_snapshot

GAP = 0.5


class FakeClock:
    def __init__(self, start=100.0):
        self.value = start

    def __call__(self):
        return self.value


class FakeController:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.refreshes = 0
        self.power = []
        self.data = []
        self.polls = []
        self.ports = []
        self.pauses = []
        self.policies = []
        self._auto = make_auto()

    def tick(self, now):
        return False

    def snapshot(self):
        return self._snapshot

    def auto(self):
        return self._auto

    def request_refresh(self):
        self.refreshes += 1

    def toggle_power(self, channel):
        self.power.append(channel)

    def set_poll(self, seconds):
        self.polls.append(seconds)

    def set_port(self, port):
        self.ports.append(port)

    def toggle_data(self, channel):
        self.data.append(channel)

    def set_auto_paused(self, paused):
        self.pauses.append(paused)
        self._auto.paused = paused

    def set_policy(self, port, rule):
        self.policies.append((port, rule))
        self._auto.policies[port] = rule


class FakeTerminal:
    def __init__(self, clock, script, width=80, height=24):
        self.clock = clock
        self.script = list(script)
        self.width = width
        self.height = height
        self.frames = []
        self.clears = 0

    def size(self):
        return self.width, self.height

    def clear(self):
        self.clears += 1

    def draw(self, lines):
        self.frames.append(list(lines))

    def read_key(self, timeout_s):
        if not self.script:
            raise AssertionError("key script exhausted before the loop exited")
        key, gap = self.script.pop(0)
        self.clock.value += gap
        return key


def run_loop(script, snapshot=None):
    clock = FakeClock()
    terminal = FakeTerminal(clock, script)
    controller = FakeController(snapshot or make_snapshot())
    code = _loop(controller, terminal, False, True, clock=clock)
    return code, controller, terminal


def headers(terminal):
    return [ANSI_RE.sub("", frame[0]) for frame in terminal.frames]


def footers(terminal):
    return [ANSI_RE.sub("", frame[-1]) for frame in terminal.frames]


class ControlTests(unittest.TestCase):
    def test_enter_opens_the_port_detail_and_never_writes(self):
        code, controller, terminal = run_loop(
            [("enter", 0.0), ("enter", GAP), ("q", GAP)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])
        self.assertTrue(any("HUBCTL  USB PORT 1 - ON - data on" in line
                            for line in headers(terminal)))
        self.assertTrue(any("voltage" in "".join(frame)
                            and "current" in "".join(frame)
                            for frame in terminal.frames))
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])

    def test_space_and_d_write_the_selected_port(self):
        code, controller, _terminal = run_loop(
            [("j", 0.0), ("space", GAP), ("d", GAP), ("q", GAP)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.power, [2])
        self.assertEqual(controller.data, [2])

    def test_held_space_acts_once(self):
        script = ([("space", 0.0)] + [("space", 0.03)] * 34
                  + [("q", GAP)])
        code, controller, _terminal = run_loop(script)
        self.assertEqual(code, 0)
        self.assertEqual(controller.power, [1])

    def test_space_then_d_inside_the_guard_both_act(self):
        code, controller, _terminal = run_loop(
            [("space", 0.05), ("d", 0.2), ("q", GAP)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.power, [1])
        self.assertEqual(controller.data, [1])

    def test_q_and_escape_quit_on_control(self):
        for key in ("q", "escape"):
            code, _controller, _terminal = run_loop([(key, 0.0)])
            self.assertEqual(code, 0)


class MenuTests(unittest.TestCase):
    def test_m_opens_the_menu_and_m_closes_it_without_quitting(self):
        code, _controller, terminal = run_loop(
            [("m", 0.0), ("r", 0.1), ("m", GAP), ("q", 1.0)])
        self.assertEqual(code, 0)
        self.assertTrue(any(FOOTER_MENU in line for line in footers(terminal)))
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])

    def test_q_closes_the_menu_and_does_not_quit(self):
        code, _controller, terminal = run_loop(
            [("m", 0.0), ("q", GAP), ("q", 1.0)])
        self.assertEqual(code, 0)
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])
        self.assertEqual(terminal.clock.value, 101.5)

    def test_escape_closes_the_menu(self):
        code, _controller, terminal = run_loop(
            [("m", 0.0), ("escape", GAP), ("q", 1.0)])
        self.assertEqual(code, 0)
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])

    def test_the_m_guard_drops_a_held_key(self):
        code, _controller, terminal = run_loop(
            [("m", 0.0), ("m", 0.1), ("q", GAP), ("q", 1.0)])
        self.assertEqual(code, 0)
        self.assertAlmostEqual(terminal.clock.value, 101.6)

    def test_enter_opens_device_and_returns(self):
        code, controller, terminal = run_loop(
            [("m", 0.0), ("enter", GAP), ("enter", 1.0), ("q", 1.5)])
        self.assertEqual(code, 0)
        self.assertTrue(any("HUBCTL  DEVICE" in line
                            for line in headers(terminal)))
        self.assertTrue(any(FOOTER_DEVICE in line
                            for line in footers(terminal)))
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])

    def test_m_returns_from_device_to_control(self):
        code, _controller, terminal = run_loop(
            [("m", 0.0), ("enter", GAP), ("m", 1.0), ("q", 1.5)])
        self.assertEqual(code, 0)
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])

    def test_navigate_to_help_and_back(self):
        code, controller, terminal = run_loop(
            [("m", 0.0), ("j", GAP), ("j", 1.0), ("j", 1.2), ("enter", 1.5),
             ("q", 2.0), ("q", 2.5)])
        self.assertEqual(code, 0)
        self.assertTrue(any("HUBCTL  HELP" in line
                            for line in headers(terminal)))
        self.assertTrue(any("hubctl 0.1.0" in ANSI_RE.sub("", line)
                            for frame in terminal.frames for line in frame))
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])

    def test_space_and_d_do_nothing_on_menu_and_device(self):
        code, controller, _terminal = run_loop(
            [("m", 0.0), ("space", 0.1), ("d", 0.2), ("enter", GAP),
             ("space", 1.0), ("d", 1.1), ("q", 1.5), ("q", 2.0)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])

    def test_no_device_menu_still_opens(self):
        code, _controller, terminal = run_loop(
            [("m", 0.0), ("enter", GAP), ("q", 1.0), ("q", 1.5)],
            snapshot=make_no_device())
        self.assertEqual(code, 0)
        self.assertTrue(any("GLOBAL MENU" in frame[4]
                            for frame in terminal.frames))
        self.assertTrue(any("HUBCTL  DEVICE" in line
                            for line in headers(terminal)))
        self.assertIn(FOOTER_NO_DEVICE, footers(terminal)[-1])


class AutoTests(unittest.TestCase):
    def test_a_opens_the_policy_for_the_selected_port_and_p_pauses(self):
        code, controller, terminal = run_loop(
            [("a", 0.0), ("p", GAP), ("j", 1.0), ("p", 1.5), ("q", 2.0),
             ("q", 2.5)])
        self.assertEqual(code, 0)
        self.assertTrue(any("HUBCTL  AUTO - USB PORT 1" in line
                            for line in headers(terminal)))
        self.assertTrue(any(FOOTER_POLICY in line for line in footers(terminal)))
        self.assertEqual(controller.pauses, [True, False])
        self.assertTrue(any("auto paused" in ANSI_RE.sub("", line)
                            for frame in terminal.frames for line in frame))
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])

    def test_p_pauses_from_the_control_page(self):
        code, controller, _terminal = run_loop(
            [("p", 0.0), ("q", GAP)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.pauses, [True])

    def test_the_policy_page_steps_a_value_and_never_writes(self):
        code, controller, terminal = run_loop(
            [("a", 0.0), ("j", GAP), ("right", 1.0), ("right", 1.5),
             ("q", 2.0), ("q", 2.5)])
        self.assertEqual(code, 0)
        self.assertTrue(any("HUBCTL  AUTO - USB PORT 1" in line
                            for line in headers(terminal)))
        self.assertTrue(any(FOOTER_POLICY in line for line in footers(terminal)))
        self.assertEqual(len(controller.policies), 2)
        port, rule = controller.policies[-1]
        self.assertEqual(port, 1)
        self.assertEqual(rule.cycle_s, 300)
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])

    def test_the_auto_pages_never_reach_the_power_or_data_path(self):
        code, controller, _terminal = run_loop(
            [("a", 0.0), ("space", GAP), ("d", 1.0), ("q", 1.5),
             ("q", 2.0)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])
        self.assertEqual(controller.policies, [])


class RefreshTests(unittest.TestCase):
    def test_r_requests_a_refresh_on_every_screen(self):
        code, controller, _terminal = run_loop(
            [("r", 0.0), ("m", 0.1), ("r", GAP), ("enter", 1.0),
             ("r", 1.5), ("q", 2.0), ("q", 2.5)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.refreshes, 3)

    def test_port_detail_reads_the_usb_map_only_with_data_on(self):
        with mock.patch("hubctl.app.tui.usbmap.port_device",
                        return_value=None) as lookup:
            code, _controller, _terminal = run_loop(
                [("enter", 0.0), ("r", 0.2), ("r", 0.9), ("q", 1.4),
                 ("q", 1.9)])
        self.assertEqual(code, 0)
        self.assertGreaterEqual(lookup.call_count, 1)

    def test_usb_map_is_not_read_on_the_control_page(self):
        with mock.patch("hubctl.app.tui.usbmap.port_device",
                        return_value=None) as lookup:
            code, _controller, _terminal = run_loop([("q", 0.0)])
        self.assertEqual(code, 0)
        lookup.assert_not_called()

    def test_every_screen_redraws_without_an_error(self):
        code, controller, terminal = run_loop([
            ("r", 0.0),
            ("enter", 0.5), ("r", 0.7), ("r", 1.2), ("q", 1.7),
            ("m", 2.2), ("r", 2.4),
            ("enter", 2.9), ("r", 3.1), ("r", 3.6), ("q", 4.1),
            ("m", 4.6), ("j", 4.8), ("enter", 5.3), ("r", 5.5),
            ("right", 5.7), ("r", 6.2), ("q", 6.7),
            ("m", 7.2), ("j", 7.4), ("j", 7.6), ("enter", 8.1),
            ("r", 8.3), ("r", 8.8), ("q", 9.3),
            ("q", 9.8),
        ])
        self.assertEqual(code, 0)
        self.assertGreater(len(terminal.frames), 20)
        self.assertEqual(controller.power, [])
        self.assertEqual(controller.data, [])

    def test_settings_changes_poll_and_port(self):
        code, controller, terminal = run_loop(
            [("m", 0.0), ("j", GAP), ("j", 1.0), ("enter", 1.5),
             ("j", 2.0), ("right", 2.5), ("k", 3.0), ("right", 3.5),
             ("q", 4.0), ("q", 4.5)])
        self.assertEqual(code, 0)
        self.assertEqual(controller.polls, [2.0])
        self.assertEqual(controller.ports, [None])
        self.assertTrue(any("HUBCTL  SETTINGS" in line
                            for line in headers(terminal)))
        self.assertTrue(any(FOOTER_SETTINGS in line
                            for line in footers(terminal)))
        self.assertIn(FOOTER_CONTROL, footers(terminal)[-1])

    def test_ctrl_c_quits_on_every_screen(self):
        for prefix in ([], [("m", 0.0)], [("m", 0.0), ("enter", GAP)]):
            code, _controller, _terminal = run_loop(
                prefix + [("ctrl-c", 1.0)])
            self.assertEqual(code, 0)


class RenderTests(unittest.TestCase):
    def test_menu_frames_have_one_selection_and_no_port_rows(self):
        _code, _controller, terminal = run_loop(
            [("m", 0.0), ("q", GAP), ("q", 1.0)])
        menus = [frame for frame, footer in zip(terminal.frames,
                                                footers(terminal))
                 if FOOTER_MENU in footer]
        self.assertEqual(len(menus), 1)
        body = menus[0][1:-1]
        self.assertEqual(sum(frame.count("\x1b[1;7m") for frame in body), 1)
        self.assertNotIn("USB PORT", "\n".join(menus[0]))


if __name__ == "__main__":
    unittest.main()
