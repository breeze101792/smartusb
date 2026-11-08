import unittest

from hubctl.app import menu
from hubctl.hal.base import LinkState

from .helpers import make_no_device, make_snapshot


class PortTests(unittest.TestCase):
    def test_port_count_follows_the_probed_count(self):
        for channels in (1, 4, 7):
            self.assertEqual(menu.port_count(make_snapshot(channels=channels)),
                             channels)
        self.assertEqual(menu.port_count(make_no_device()), 0)

    def test_port_rows_are_named_usb_port(self):
        self.assertEqual(menu.port_label(2), "USB PORT 2")


class ItemTests(unittest.TestCase):
    def test_menu_has_device_settings_and_help(self):
        entries = menu.items(menu.State(menu.MENU))
        self.assertEqual([item.label for item in entries],
                         ["Device", "Settings", "Help"])
        self.assertEqual(entries[0].action, menu.OPEN_DEVICE)
        self.assertEqual(entries[1].action, menu.OPEN_SETTINGS)
        self.assertEqual(entries[2].action, menu.OPEN_HELP)

    def test_device_and_help_have_back_only(self):
        for screen in (menu.DEVICE, menu.SETTINGS, menu.HELP,
                       menu.POLICY):
            entries = menu.items(menu.State(screen))
            self.assertEqual([item.label for item in entries], ["Back"])
            self.assertEqual(entries[0].action, menu.BACK)

    def test_control_has_no_item_rows(self):
        self.assertEqual(menu.items(menu.State()), [])

    def test_device_fields_in_display_order(self):
        fields = menu.device_fields(make_snapshot())
        self.assertEqual([label for label, __value, _known in fields],
                         ["ports", "product", "firmware", "hardware",
                          "address", "buttons", "restore"])
        self.assertEqual([value for _label, value, _known in fields],
                         ["4", "HBP_USB2_4CH", "V2.0", "V1.3", "0x0005",
                          "enabled", "disabled"])

    def test_lost_field_values_are_unknown(self):
        fields = menu.device_fields(
            make_snapshot(link=LinkState.LOST, reconnect=2.0))
        self.assertTrue(all(value == "?" and not known
                        for _label, value, known in fields))

    def test_no_device_fields_are_all_unknown(self):
        fields = menu.device_fields(make_no_device())
        self.assertEqual(len(fields), len(menu.DEVICE_FIELD_LABELS))
        self.assertTrue(all(value == "?" and not known
                        for _label, value, known in fields))


class ReadoutTests(unittest.TestCase):
    def test_power_and_data_state_accompanies_the_copy(self):
        values = menu.readout(make_snapshot(), 1)
        self.assertEqual(values.power_text, "ON")
        self.assertIs(values.power_on, True)
        self.assertEqual(values.data_text, "data on")
        self.assertEqual(values.data_word, "on")
        self.assertIs(values.data_on, True)
        self.assertEqual(values.voltage_text, "4.61 V")
        self.assertTrue(values.voltage_live)
        self.assertEqual(values.current_text, "0.00 A")
        self.assertTrue(values.current_live)

    def test_power_off_reads_dash_and_residual_voltage(self):
        values = menu.readout(make_snapshot(), 2)
        self.assertIs(values.power_on, False)
        self.assertEqual(values.data_text, "-")
        self.assertIsNone(values.data_on)
        self.assertEqual(values.voltage_text, "(202 mV)")
        self.assertFalse(values.voltage_live)

    def test_lost_is_unknown_everywhere(self):
        values = menu.readout(
            make_snapshot(link=LinkState.LOST, reconnect=2.0), 1)
        self.assertEqual(values.power_text, "?")
        self.assertIsNone(values.power_on)
        self.assertEqual(values.data_text, "?")
        self.assertIsNone(values.data_on)
        self.assertEqual((values.voltage_text, values.current_text),
                         ("?", "?"))
        self.assertFalse(values.voltage_live)
        self.assertFalse(values.current_live)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot(channels=4)

    def test_next_and_previous_wrap_on_control(self):
        state = menu.State()
        state, action = menu.handle_key(self.snapshot, state, "k")
        self.assertIsNone(action)
        self.assertEqual(menu.index(self.snapshot, state), 3)
        state, _ = menu.handle_key(self.snapshot, state, "j")
        self.assertEqual(menu.index(self.snapshot, state), 0)
        state, _ = menu.handle_key(self.snapshot, state, "down")
        self.assertEqual(menu.index(self.snapshot, state), 1)
        state, _ = menu.handle_key(self.snapshot, state, "up")
        self.assertEqual(menu.index(self.snapshot, state), 0)

    def test_menu_navigation_wraps_between_items(self):
        state = menu.State(menu.MENU)
        moved, _ = menu.handle_key(self.snapshot, state, "j")
        self.assertEqual(menu.index(self.snapshot, moved), 1)
        back, _ = menu.handle_key(self.snapshot, moved, "k")
        self.assertEqual(menu.index(self.snapshot, back), 0)

    def test_navigation_does_nothing_on_device_and_help(self):
        for state in (menu.State(menu.DEVICE), menu.State(menu.HELP)):
            for key in ("j", "k", "down", "up"):
                moved, action = menu.handle_key(self.snapshot, state, key)
                self.assertIsNone(action)
                self.assertEqual(moved, state)

    def test_selection_is_clamped_to_the_port_count(self):
        state = menu.State(port_index=9)
        self.assertEqual(menu.index(self.snapshot, state), 3)
        state = menu.State(port_index=9)
        moved, _ = menu.handle_key(self.snapshot, state, "j")
        self.assertEqual(menu.index(self.snapshot, moved), 0)

    def test_no_device_selection_has_no_rows(self):
        snapshot = make_no_device()
        state = menu.State(port_index=9)
        self.assertEqual(menu.index(snapshot, state), 0)
        moved, action = menu.handle_key(snapshot, state, "j")
        self.assertEqual((moved, action), (state, None))


class KeyTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot(channels=4)

    def test_enter_on_a_port_opens_its_detail(self):
        for port_index in range(4):
            state = menu.State(port_index=port_index)
            moved, action = menu.handle_key(self.snapshot, state, "enter")
            self.assertIsNone(action)
            self.assertEqual(moved.screen, menu.PORT)
            self.assertEqual(moved.port, port_index + 1)
            back, action = menu.handle_key(self.snapshot, moved, "enter")
            self.assertIsNone(action)
            self.assertEqual(back.screen, menu.CONTROL)

    def test_m_opens_and_closes_without_quitting(self):
        state, action = menu.handle_key(self.snapshot, menu.State(), "m")
        self.assertIsNone(action)
        self.assertEqual(state.screen, menu.MENU)
        state, action = menu.handle_key(self.snapshot, state, "m")
        self.assertIsNone(action)
        self.assertEqual(state.screen, menu.CONTROL)

    def test_q_and_escape_close_the_menu(self):
        for key in ("q", "escape"):
            state = menu.State(menu.MENU, port_index=2)
            moved, action = menu.handle_key(self.snapshot, state, key)
            self.assertIsNone(action)
            self.assertEqual(moved, menu.State(port_index=2))

    def test_m_from_device_returns_to_control(self):
        state, action = menu.handle_key(self.snapshot,
                                        menu.State(menu.DEVICE), "m")
        self.assertIsNone(action)
        self.assertEqual(state.screen, menu.CONTROL)

    def test_enter_opens_device_and_returns(self):
        state, action = menu.handle_key(self.snapshot,
                                        menu.State(menu.MENU), "enter")
        self.assertIsNone(action)
        self.assertEqual(state.screen, menu.DEVICE)
        back, action = menu.handle_key(self.snapshot, state, "enter")
        self.assertIsNone(action)
        self.assertEqual(back.screen, menu.CONTROL)

    def test_enter_on_help_returns_to_control(self):
        state = menu.State(menu.MENU, menu_index=3)
        help, action = menu.handle_key(self.snapshot, state, "enter")
        self.assertIsNone(action)
        self.assertEqual(help.screen, menu.HELP)
        for key in ("enter", "q", "escape", "m"):
            back, action = menu.handle_key(self.snapshot, help, key)
            self.assertIsNone(action)
            self.assertEqual(back.screen, menu.CONTROL)

    def test_settings_cycle_port_and_poll(self):
        state = menu.State(menu.SETTINGS)
        _, action = menu.handle_key(self.snapshot, state, "right")
        self.assertEqual(action.kind, menu.SET_PORT)
        self.assertIsNone(action.value)
        moved, _ = menu.handle_key(self.snapshot, state, "j")
        self.assertEqual(menu.index(self.snapshot, moved), 1)
        _, action = menu.handle_key(self.snapshot, moved, "right")
        self.assertEqual(action.kind, menu.SET_POLL)
        self.assertEqual(action.value, 2.0)

    def test_space_changes_the_selected_policy_value(self):
        state = menu.State(menu.POLICY, port=2)
        _, action = menu.handle_key(self.snapshot, state, "space")
        self.assertEqual(action.kind, menu.SET_POLICY)
        self.assertEqual(action.port, 2)
        self.assertEqual(action.value, ("enabled", 1))
        moved, _ = menu.handle_key(self.snapshot, state, "j")
        _, action = menu.handle_key(self.snapshot, moved, "space")
        self.assertEqual(action.value, ("cycle", 1))

    def test_enter_leaves_the_read_only_pages_from_any_row(self):
        cases = (menu.State(menu.DEVICE), menu.State(menu.HELP),
                 menu.State(menu.PORT, port=2))
        for state in cases:
            back, action = menu.handle_key(self.snapshot, state, "enter")
            self.assertIsNone(action)
            self.assertEqual(back.screen, menu.CONTROL, state.screen)

    def test_enter_on_settings_edits_poll_or_steps_port(self):
        state = menu.State(menu.MENU, menu_index=1)
        settings, action = menu.handle_key(self.snapshot, state, "enter")
        self.assertIsNone(action)
        self.assertEqual(settings.screen, menu.SETTINGS)
        stepped, action = menu.handle_key(self.snapshot, settings, "enter")
        self.assertEqual(action.kind, menu.SET_PORT)
        poll = menu.State(menu.SETTINGS, settings_index=1)
        editing, action = menu.handle_key(self.snapshot, poll, "enter")
        self.assertIsNone(action)
        self.assertEqual(editing.edit, "")
        self.assertEqual(editing.screen, menu.SETTINGS)
        for key in ("q", "escape", "m"):
            back, action = menu.handle_key(self.snapshot, settings, key)
            self.assertIsNone(action)
            self.assertEqual(back.screen, menu.CONTROL, key)

    def test_the_poll_editor_commits_seconds(self):
        state = menu.State(menu.SETTINGS, settings_index=1)
        state, _ = menu.handle_key(self.snapshot, state, "enter")
        for key in ("1", ".", "5"):
            state, _ = menu.handle_key(self.snapshot, state, key)
        done, action = menu.handle_key(self.snapshot, state, "enter")
        self.assertIsNone(done.edit)
        self.assertEqual(action.kind, menu.SET_POLL)
        self.assertEqual(action.value, 1.5)

    def test_q_and_escape_return_from_device(self):
        for key in ("q", "escape"):
            moved, action = menu.handle_key(self.snapshot,
                                            menu.State(menu.DEVICE), key)
            self.assertIsNone(action)
            self.assertEqual(moved.screen, menu.CONTROL)

    def test_port_selection_survives_the_menu(self):
        state = menu.State(port_index=3)
        state, _ = menu.handle_key(self.snapshot, state, "m")
        state, _ = menu.handle_key(self.snapshot, state, "m")
        self.assertEqual(menu.index(self.snapshot, state), 3)
        state, _ = menu.handle_key(self.snapshot, state, "m")
        state, _ = menu.handle_key(self.snapshot, state, "enter")
        state, _ = menu.handle_key(self.snapshot, state, "enter")
        self.assertEqual(menu.index(self.snapshot, state), 3)

    def test_space_and_d_write_the_selected_port_from_control(self):
        state = menu.State(port_index=2)
        state, action = menu.handle_key(self.snapshot, state, "space")
        self.assertEqual((action.kind, action.port),
                         (menu.TOGGLE_POWER, 3))
        state, action = menu.handle_key(self.snapshot, state, "d")
        self.assertEqual((action.kind, action.port),
                         (menu.TOGGLE_DATA, 3))

    def test_space_acts_on_the_selected_row_and_d_does_nothing(self):
        moved, action = menu.handle_key(
            self.snapshot, menu.State(menu.MENU), "space")
        self.assertIsNone(action)
        self.assertEqual(moved.screen, menu.DEVICE)
        moved, action = menu.handle_key(
            self.snapshot, menu.State(menu.DEVICE), "space")
        self.assertIsNone(action)
        self.assertEqual(moved.screen, menu.CONTROL)
        for state in (menu.State(menu.MENU), menu.State(menu.DEVICE)):
            moved, action = menu.handle_key(self.snapshot, state, "d")
            self.assertIsNone(action)
            self.assertEqual(moved, state)

    def test_no_device_has_no_write_and_still_opens_the_menu(self):
        snapshot = make_no_device()
        _state, action = menu.handle_key(snapshot, menu.State(), "space")
        self.assertIsNone(action)
        state, action = menu.handle_key(snapshot, menu.State(), "m")
        self.assertIsNone(action)
        self.assertEqual(state.screen, menu.MENU)
        state, action = menu.handle_key(snapshot, state, "enter")
        self.assertEqual(state.screen, menu.DEVICE)
        self.assertIsNone(action)

    def test_refresh_on_every_screen(self):
        for state in (menu.State(), menu.State(menu.MENU),
                      menu.State(menu.DEVICE)):
            _state, action = menu.handle_key(self.snapshot, state, "r")
            self.assertEqual(action.kind, menu.REFRESH)

    def test_quit_on_control_and_ctrl_c_everywhere(self):
        for key in ("q", "escape"):
            _state, action = menu.handle_key(self.snapshot, menu.State(), key)
            self.assertEqual(action.kind, menu.QUIT)
        for state in (menu.State(), menu.State(menu.MENU),
                      menu.State(menu.DEVICE)):
            _state, action = menu.handle_key(self.snapshot, state, "ctrl-c")
            self.assertEqual(action.kind, menu.QUIT)

    def test_guarded_keys(self):
        self.assertEqual(menu.GUARDED_KEYS,
                         ("enter", "space", "d", "m", "p"))


class AutoTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot(channels=4)

    def test_menu_does_not_open_auto(self):
        for index, screen in ((0, menu.DEVICE), (1, menu.SETTINGS),
                              (2, menu.HELP)):
            state, action = menu.handle_key(
                self.snapshot, menu.State(menu.MENU, menu_index=index),
                "enter")
            self.assertIsNone(action)
            self.assertEqual(state.screen, screen)

    def test_a_opens_the_policy_for_the_selected_port(self):
        state, action = menu.handle_key(
            self.snapshot, menu.State(port_index=2), "a")
        self.assertIsNone(action)
        self.assertEqual(state.screen, menu.POLICY)
        self.assertEqual(state.port, 3)
        self.assertEqual(state.policy_index, 0)

    def test_a_does_nothing_off_the_control_page(self):
        for screen in (menu.MENU, menu.DEVICE, menu.POLICY, menu.SETTINGS,
                       menu.HELP):
            state, action = menu.handle_key(
                self.snapshot, menu.State(screen), "a")
            self.assertIsNone(action)
            self.assertEqual(state.screen, screen)

    def test_p_asks_for_pause_only_where_pause_is_offered(self):
        for screen in (menu.CONTROL, menu.POLICY):
            state, action = menu.handle_key(
                self.snapshot, menu.State(screen), "p")
            self.assertEqual(action.kind, menu.TOGGLE_PAUSE)
            self.assertEqual(state.screen, screen)
        for screen in (menu.MENU, menu.PORT, menu.DEVICE, menu.SETTINGS,
                       menu.HELP):
            _state, action = menu.handle_key(
                self.snapshot, menu.State(screen), "p")
            self.assertIsNone(action)

    def test_policy_navigation_wraps_over_the_rows_and_back(self):
        state = menu.State(menu.POLICY, port=2)
        self.assertEqual(menu.index(self.snapshot, state), 0)
        moved, _ = menu.handle_key(self.snapshot, state, "j")
        self.assertEqual(menu.index(self.snapshot, moved), 1)
        last = menu.State(menu.POLICY, port=2,
                          policy_index=len(menu.POLICY_ROWS))
        self.assertEqual(menu.index(self.snapshot, last), len(menu.POLICY_ROWS))
        wrapped, _ = menu.handle_key(self.snapshot, last, "j")
        self.assertEqual(menu.index(self.snapshot, wrapped), 0)

    def test_enter_opens_the_current_page_or_the_editor(self):
        current, action = menu.handle_key(
            self.snapshot, menu.State(menu.POLICY, port=2, policy_index=2),
            "enter")
        self.assertIsNone(action)
        self.assertEqual(current.screen, menu.CURRENT)
        state = menu.State(menu.POLICY, port=2, policy_index=1)
        editing, action = menu.handle_key(self.snapshot, state, "enter")
        self.assertIsNone(action)
        self.assertEqual(editing.edit, "")
        for key in ("q", "escape", "m"):
            back, action = menu.handle_key(self.snapshot, state, key)
            self.assertIsNone(action)
            self.assertEqual(back.screen, menu.CONTROL, key)
        toggled, action = menu.handle_key(
            self.snapshot, menu.State(menu.POLICY, port=2), "enter")
        self.assertIsNone(toggled.edit)
        self.assertEqual(action.kind, menu.SET_POLICY)

    def test_the_editor_types_commits_and_cancels(self):
        state = menu.State(menu.CURRENT, port=2, current_index=0)
        state, _ = menu.handle_key(self.snapshot, state, "enter")
        for key in ("1", ".", "8"):
            state, action = menu.handle_key(self.snapshot, state, key)
            self.assertIsNone(action)
        self.assertEqual(state.edit, "1.8")
        done, action = menu.handle_key(self.snapshot, state, "enter")
        self.assertIsNone(done.edit)
        self.assertEqual(action.kind, menu.SET_POLICY_VALUE)
        self.assertEqual(action.value, ("over", "1.8"))
        cancelled, action = menu.handle_key(
            self.snapshot,
            menu.State(menu.CURRENT, port=2, current_index=0, edit="2"),
            "escape")
        self.assertIsNone(action)
        self.assertIsNone(cancelled.edit)
        edited, _ = menu.handle_key(
            self.snapshot,
            menu.State(menu.CURRENT, port=2, current_index=0, edit="12"),
            "backspace")
        self.assertEqual(edited.edit, "1")

    def test_the_editor_refuses_out_of_range_input(self):
        cycle = menu.State(menu.POLICY, port=2, policy_index=1)
        cycle, _ = menu.handle_key(self.snapshot, cycle, "enter")
        cycle, _ = menu.handle_key(self.snapshot, cycle, "6")
        cycle, _ = menu.handle_key(self.snapshot, cycle, "5")
        self.assertEqual(cycle.edit, "6")
        amps = menu.State(menu.CURRENT, port=2, current_index=0, edit="4")
        kept, _ = menu.handle_key(self.snapshot, amps, "5")
        self.assertEqual(kept.edit, "4")
        low = menu.State(menu.POLICY, port=2, policy_index=3, edit="0")
        moved, action = menu.handle_key(self.snapshot, low, "enter")
        self.assertEqual(moved.edit, "0")
        self.assertIsNone(action)
        empty = menu.State(menu.CURRENT, port=2, current_index=0, edit="")
        done, action = menu.handle_key(self.snapshot, empty, "enter")
        self.assertIsNone(done.edit)
        self.assertIsNone(action)

    def test_the_editor_keeps_digits_only_and_one_dot(self):
        cycle = menu.State(menu.POLICY, port=2, policy_index=1, edit="4")
        kept, _ = menu.handle_key(self.snapshot, cycle, ".")
        self.assertEqual(kept.edit, "4")
        amps = menu.State(menu.CURRENT, port=2, current_index=0, edit="1.5")
        doubled, _ = menu.handle_key(self.snapshot, amps, ".")
        self.assertEqual(doubled.edit, "1.5")

    def test_question_opens_the_auto_help_and_q_returns(self):
        for screen, state in ((menu.POLICY, menu.State(menu.POLICY, port=2)),
                              (menu.CURRENT, menu.State(menu.CURRENT, port=2))):
            help_state, action = menu.handle_key(self.snapshot, state, "?")
            self.assertIsNone(action)
            self.assertEqual(help_state.screen, menu.AUTOHELP)
            back, action = menu.handle_key(self.snapshot, help_state, "q")
            self.assertIsNone(action)
            self.assertEqual(back.screen, menu.POLICY, screen)

    def test_space_changes_and_d_does_nothing_on_the_policy_page(self):
        moved, action = menu.handle_key(
            self.snapshot, menu.State(menu.POLICY, port=2), "space")
        self.assertEqual(action.kind, menu.SET_POLICY)
        self.assertEqual(moved.screen, menu.POLICY)
        moved, action = menu.handle_key(
            self.snapshot, menu.State(menu.POLICY, port=2), "d")
        self.assertIsNone(action)
        self.assertEqual(moved.screen, menu.POLICY)


if __name__ == "__main__":
    unittest.main()
