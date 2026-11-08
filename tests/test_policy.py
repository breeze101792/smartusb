"""ARCH-002 truth tables: pure ``decide()`` with fake clocks."""

import time
import unittest

from hubctl.app import policy
from hubctl.constants import (
    AUTO_CYCLE_OFF_S,
    AUTO_MANUAL_HOLD_S,
    AUTO_MAX_RETRIES,
    AUTO_NORMAL_SAMPLES,
    AUTO_OVER_SAMPLES,
)
from hubctl.hal.base import ChannelReading, LinkState, Mode, Snapshot, Status

MONO = 1000.0


def at(hour, minute=0, day=1):
    """A local wall time in 2026, away from a DST change."""
    return time.mktime((2026, 1, day, hour, minute, 0, 0, 0, -1))


def snapshot(power=True, data=True, current=0, channels=4,
             link=LinkState.LIVE, mode=Mode.NORMAL):
    readings = {number: ChannelReading(False, None, 8, 0)
                for number in range(1, channels + 1)}
    readings[1] = ChannelReading(power, data if power else None,
                                 4980 if power else 8, current)
    if channels >= 2:
        readings[2] = ChannelReading(power, data if power else None,
                                     4980 if power else 8, current)
    return Snapshot(identity=None, status=Status(mode), channels=readings,
                    link=link, last_cycle_age_s=0.0, last_action="")


def auto(rule, state=None, paused=False, rules=None):
    policies = {1: rule}
    if rules:
        policies.update(rules)
    return policy.Auto(paused=paused, policies=policies,
                       state={1: state or policy.PortAuto()})


def state(**fields):
    return policy.PortAuto(**fields)


def cycle_rule(seconds=600):
    return policy.Policy(enabled=True, cycle_s=seconds)


class GateTests(unittest.TestCase):
    def due(self):
        return auto(cycle_rule(), state(last_cycle_at=MONO - 600))

    def test_stale_cancels_the_deferred_work_and_keeps_the_baseline(self):
        for link in (LinkState.STALE, LinkState.LOST):
            rule = self.due()
            rule.state[1].pending_on_at = MONO
            rule.state[1].low_since = MONO - 1
            result, decision = policy.decide(
                snapshot(link=link), rule, {}, MONO, at(12))
            self.assertIsNone(decision)
            self.assertIsNone(result.state[1].pending_on_at)
            self.assertIsNone(result.state[1].low_since)
            self.assertEqual(result.state[1].last_cycle_at, MONO - 600)

    def test_interlock_cancels_the_deferred_work(self):
        rule = self.due()
        rule.state[1].pending_on_at = MONO
        result, decision = policy.decide(
            snapshot(mode=Mode.INTERLOCK), rule, {}, MONO, at(12))
        self.assertIsNone(decision)
        self.assertIsNone(result.state[1].pending_on_at)

    def test_paused_runs_no_rule_and_cancels(self):
        rule = self.due()
        rule.paused = True
        rule.state[1].low_since = MONO - 1
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNone(decision)
        self.assertIsNone(result.state[1].low_since)
        self.assertTrue(result.paused)

    def test_disabled_cancels_and_runs_nothing(self):
        rule = self.due()
        rule.policies[1] = policy.Policy(enabled=False, cycle_s=600)
        rule.state[1].pending_on_at = MONO
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNone(decision)
        self.assertIsNone(result.state[1].pending_on_at)

    def test_the_manual_hold_suppresses_a_cycle(self):
        rule = self.due()
        rule.state[1].manual_until = MONO + 1
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNone(decision)

    def test_the_manual_hold_expires(self):
        rule = self.due()
        rule.state[1].manual_until = MONO - 1
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertEqual(decision.text, "USB1 off - auto cycle 10 min")

    def test_the_manual_hold_cancels_the_queued_on(self):
        rule = self.due()
        rule.state[1].pending_on_at = MONO
        rule.state[1].pending_text = "USB1 on - auto cycle"
        rule.state[1].low_since = MONO - 1
        rule.state[1].manual_until = MONO + 1
        result, decision = policy.decide(snapshot(power=False), rule, {},
                                         MONO, at(12))
        self.assertIsNone(decision)
        self.assertIsNone(result.state[1].pending_on_at)
        self.assertIsNone(result.state[1].low_since)

    def test_a_port_missing_from_the_snapshot_is_skipped(self):
        rule = self.due()
        snap = snapshot()
        del snap.channels[1]
        _result, decision = policy.decide(snap, rule, {}, MONO, at(12))
        self.assertIsNone(decision)


class OvercurrentTests(unittest.TestCase):
    def rule(self, held=False):
        rule = auto(policy.Policy(enabled=True, overcurrent_ma=1000))
        if held:
            rule.state[1].manual_until = MONO + 1
        return rule

    def test_one_sample_does_not_cut(self):
        rule = self.rule()
        result, decision = policy.decide(
            snapshot(current=1620), rule, {}, MONO, at(12))
        self.assertIsNone(decision)
        self.assertEqual(result.state[1].over_at, 1)

    def test_two_samples_cut_and_name_the_current(self):
        rule = self.rule()
        rule.state[1].over_at = AUTO_OVER_SAMPLES - 1
        result, decision = policy.decide(
            snapshot(current=1620), rule, {}, MONO, at(12))
        self.assertEqual(decision.text, "USB1 off - auto overcurrent 1.62 A")
        self.assertFalse(decision.on)
        self.assertEqual(decision.port, 1)
        self.assertEqual(result.state[1].cut_at, MONO)
        self.assertEqual(result.state[1].retries, 0)

    def test_a_safe_cut_ignores_the_manual_hold(self):
        rule = self.rule(held=True)
        rule.state[1].over_at = AUTO_OVER_SAMPLES - 1
        _result, decision = policy.decide(
            snapshot(current=1620), rule, {}, MONO, at(12))
        self.assertIsNotNone(decision)
        self.assertFalse(decision.on)

    def test_a_normal_sample_resets_the_over_counter(self):
        rule = self.rule()
        rule.state[1].over_at = 1
        result, _decision = policy.decide(snapshot(current=100), rule, {},
                                          MONO, at(12))
        self.assertEqual(result.state[1].over_at, 0)

    def test_three_normal_samples_re_arm(self):
        rule = self.rule()
        rule.state[1].retries = AUTO_MAX_RETRIES
        rule.state[1].normal_at = AUTO_NORMAL_SAMPLES - 1
        result, decision = policy.decide(snapshot(current=100), rule, {},
                                         MONO, at(12))
        self.assertIsNone(decision)
        self.assertEqual(result.state[1].retries, 0)

    def test_the_retry_counter_is_not_cleared_while_off(self):
        rule = auto(policy.Policy(enabled=True, overcurrent_ma=1000,
                                  retry_s=10))
        rule.state[1].retries = 2
        rule.state[1].normal_at = 0
        rule.state[1].cut_at = MONO - 1
        result, _decision = policy.decide(snapshot(power=False, current=0),
                                          rule, {}, MONO, at(12))
        self.assertEqual(result.state[1].retries, 2)


class RetryTests(unittest.TestCase):
    def rule(self, retries=0, cut=MONO - 11, retry_s=10):
        rule = auto(policy.Policy(enabled=True, overcurrent_ma=1000,
                                  retry_s=retry_s))
        rule.state[1] = state(cut_at=cut, retries=retries)
        return rule

    def test_a_retry_waits_for_its_time(self):
        rule = self.rule(cut=MONO - 9)
        _result, decision = policy.decide(snapshot(power=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)

    def test_a_retry_fires_at_its_time_and_counts(self):
        rule = self.rule()
        result, decision = policy.decide(snapshot(power=False), rule, {},
                                         MONO, at(12))
        self.assertEqual(decision.text, "USB1 on - auto retry 1 of 3")
        self.assertTrue(decision.on)
        self.assertEqual(result.state[1].retries, 1)
        self.assertIsNone(result.state[1].cut_at)

    def test_a_second_cut_keeps_the_retry_budget(self):
        rule = self.rule(retries=AUTO_MAX_RETRIES, cut=MONO - 1)
        rule.state[1].over_at = AUTO_OVER_SAMPLES - 1
        result, decision = policy.decide(
            snapshot(power=True, current=1620), rule, {}, MONO, at(12))
        self.assertFalse(decision.on)
        self.assertEqual(result.state[1].retries, AUTO_MAX_RETRIES)

    def test_the_retry_stops_after_three(self):
        rule = self.rule(retries=AUTO_MAX_RETRIES)
        _result, decision = policy.decide(snapshot(power=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)

    def test_the_manual_hold_suppresses_a_retry(self):
        rule = self.rule()
        rule.state[1].manual_until = MONO + 1
        _result, decision = policy.decide(snapshot(power=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)

    def test_no_retry_without_a_retry_time(self):
        rule = auto(policy.Policy(enabled=True, overcurrent_ma=1000))
        rule.state[1] = state(cut_at=MONO - 11)
        _result, decision = policy.decide(snapshot(power=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)


class CycleTests(unittest.TestCase):
    def test_the_first_sighting_starts_the_period_without_a_write(self):
        rule = auto(cycle_rule())
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNone(decision)
        self.assertEqual(result.state[1].last_cycle_at, MONO)

    def test_the_cycle_fires_at_its_time_and_not_before(self):
        rule = auto(cycle_rule(), state(last_cycle_at=MONO - 599))
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNone(decision)

    def test_the_cycle_turns_the_port_off_then_on(self):
        rule = auto(cycle_rule(), state(last_cycle_at=MONO - 600))
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertEqual(decision.text, "USB1 off - auto cycle 10 min")
        self.assertFalse(decision.on)
        self.assertEqual(result.state[1].pending_on_at,
                         MONO + AUTO_CYCLE_OFF_S)
        self.assertEqual(result.state[1].last_cycle_at, MONO)

        later = MONO + AUTO_CYCLE_OFF_S
        on, decision = policy.decide(snapshot(power=False), result, {}, later,
                                     at(12))
        self.assertEqual(decision.text, "USB1 on - auto cycle")
        self.assertTrue(decision.on)
        self.assertIsNone(on.state[1].pending_on_at)

    def test_a_cycle_never_turns_an_off_port_on(self):
        rule = auto(cycle_rule(), state(last_cycle_at=MONO - 600))
        _result, decision = policy.decide(snapshot(power=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)


class RecoveryTests(unittest.TestCase):
    def rule(self, seconds=300):
        return auto(policy.Policy(enabled=True, recovery_s=seconds))

    def test_a_missing_device_starts_the_timer_without_a_write(self):
        result, decision = policy.decide(snapshot(), self.rule(), {}, MONO,
                                         at(12))
        self.assertIsNone(decision)
        self.assertEqual(result.state[1].low_since, MONO)

    def test_the_recovery_cycles_after_its_time(self):
        rule = auto(policy.Policy(enabled=True, recovery_s=300),
                    state(low_since=MONO - 300))
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertEqual(decision.text,
                         "USB1 off - auto recovery, no device 5 min")
        self.assertFalse(decision.on)
        self.assertEqual(result.state[1].pending_on_at,
                         MONO + AUTO_CYCLE_OFF_S)

    def test_a_present_device_cancels_the_timer(self):
        rule = auto(policy.Policy(enabled=True, recovery_s=300),
                    state(low_since=MONO - 300))
        result, decision = policy.decide(snapshot(), rule, {1: True}, MONO,
                                         at(12))
        self.assertIsNone(decision)
        self.assertIsNone(result.state[1].low_since)

    def test_data_off_is_not_a_recovery(self):
        rule = auto(policy.Policy(enabled=True, recovery_s=300),
                    state(low_since=MONO - 300))
        _result, decision = policy.decide(snapshot(data=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)

    def test_an_off_port_is_not_recovered(self):
        rule = auto(policy.Policy(enabled=True, recovery_s=300),
                    state(low_since=MONO - 300))
        _result, decision = policy.decide(snapshot(power=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)


class ScheduleTests(unittest.TestCase):
    WINDOW = (8 * 60, 18 * 60)

    def rule(self, window=WINDOW, schedule_on=None, power=False, **fields):
        return auto(policy.Policy(enabled=True, schedule=window),
                    state(schedule_on=schedule_on, **fields))

    def test_inside_the_window_turns_on_at_the_edge(self):
        _result, decision = policy.decide(snapshot(power=False),
                                          self.rule(), {}, MONO, at(8))
        self.assertEqual(decision.text, "USB1 on - auto schedule 08:00")
        self.assertTrue(decision.on)

    def test_an_already_on_port_just_records_the_edge(self):
        rule = self.rule(schedule_on=False, power=True)
        result, decision = policy.decide(snapshot(power=True), rule, {},
                                         MONO, at(9))
        self.assertIsNone(decision)
        self.assertTrue(result.state[1].schedule_on)

    def test_outside_the_window_turns_off_at_the_edge(self):
        rule = self.rule(schedule_on=True, power=True)
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(18))
        self.assertEqual(decision.text, "USB1 off - auto schedule 18:00")
        self.assertFalse(decision.on)

    def test_outside_without_a_previous_edge_writes_nothing(self):
        _result, decision = policy.decide(snapshot(), self.rule(schedule_on=None),
                                          {}, MONO, at(20))
        self.assertIsNone(decision)

    def test_the_window_wraps(self):
        window = (22 * 60, 6 * 60)
        for hour in (23, 0, 5):
            _result, decision = policy.decide(
                snapshot(power=False), self.rule(window=window, schedule_on=False),
                {}, MONO, at(hour))
            self.assertEqual(decision.text, "USB1 on - auto schedule 22:00")
        for hour in (12, 21, 6):
            _result, decision = policy.decide(
                snapshot(power=True), self.rule(window=window, schedule_on=True),
                {}, MONO, at(hour))
            self.assertEqual(decision.text, "USB1 off - auto schedule 06:00")

    def test_from_equal_to_means_never(self):
        rule = self.rule(window=(9 * 60, 9 * 60), schedule_on=True)
        for hour in (8, 9, 10):
            _result, decision = policy.decide(snapshot(), rule, {}, MONO,
                                              at(hour))
            self.assertIsNone(decision)

    def test_a_backward_jump_skips_one_evaluation_and_resyncs(self):
        rule = self.rule(schedule_on=True, wall_at=at(19))
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(9))
        self.assertIsNone(decision)
        self.assertTrue(result.state[1].schedule_on)
        self.assertEqual(result.state[1].wall_at, at(9))

        again, decision = policy.decide(snapshot(), result, {},
                                        MONO + 60, at(9) + 60)
        self.assertIsNone(decision)
        self.assertTrue(again.state[1].schedule_on)

    def test_a_small_backward_step_is_not_a_jump(self):
        rule = self.rule(schedule_on=True, wall_at=at(18, 0) + 30)
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(18))
        self.assertEqual(decision.text, "USB1 off - auto schedule 18:00")

    def test_a_forward_jump_still_fires_the_edge(self):
        rule = self.rule(schedule_on=True, wall_at=at(17, 58))
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(18, 2))
        self.assertEqual(decision.text, "USB1 off - auto schedule 18:00")


class PriorityTests(unittest.TestCase):
    def test_the_cut_wins_over_the_cycle(self):
        rule = auto(policy.Policy(enabled=True, overcurrent_ma=1000,
                                  cycle_s=600),
                    state(last_cycle_at=MONO - 600, over_at=1))
        _result, decision = policy.decide(snapshot(current=1620), rule, {},
                                          MONO, at(12))
        self.assertIn("overcurrent", decision.text)

    def test_recovery_wins_over_the_cycle(self):
        rule = auto(policy.Policy(enabled=True, recovery_s=300, cycle_s=600),
                    state(last_cycle_at=MONO - 600, low_since=MONO - 300))
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIn("recovery", decision.text)

    def test_the_schedule_wins_over_the_pending_on(self):
        rule = auto(policy.Policy(enabled=True, schedule=(8 * 60, 18 * 60)),
                    state(schedule_on=True, pending_on_at=MONO,
                          pending_text="USB1 on - auto cycle"))
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(18))
        self.assertEqual(decision.text, "USB1 off - auto schedule 18:00")

    def test_ports_are_evaluated_in_ascending_order(self):
        rules = {2: policy.Policy(enabled=True, cycle_s=600)}
        rule = auto(policy.Policy(enabled=True, cycle_s=600),
                    state(last_cycle_at=MONO - 600), rules=rules)
        rule.state[2] = state(last_cycle_at=MONO - 600)
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertEqual(decision.port, 1)
        self.assertEqual(result.state[2].last_cycle_at, MONO - 600)

    def test_one_decision_per_call(self):
        rules = {2: policy.Policy(enabled=True, cycle_s=600)}
        rule = auto(policy.Policy(enabled=True, cycle_s=600),
                    state(last_cycle_at=MONO - 600), rules=rules)
        rule.state[2] = state(last_cycle_at=MONO - 600)
        _result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNotNone(decision)


class PendingOnTests(unittest.TestCase):
    def test_the_queued_on_fires_at_its_time(self):
        rule = auto(policy.Policy(enabled=True),
                    state(pending_on_at=MONO,
                          pending_text="USB1 on - auto recovery"))
        result, decision = policy.decide(snapshot(power=False), rule, {},
                                         MONO, at(12))
        self.assertEqual(decision.text, "USB1 on - auto recovery")
        self.assertIsNone(result.state[1].pending_on_at)

    def test_the_queued_on_waits(self):
        rule = auto(policy.Policy(enabled=True), state(pending_on_at=MONO + 1))
        _result, decision = policy.decide(snapshot(power=False), rule, {},
                                          MONO, at(12))
        self.assertIsNone(decision)

    def test_a_port_already_on_only_clears_the_timer(self):
        rule = auto(policy.Policy(enabled=True), state(pending_on_at=MONO))
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNone(decision)
        self.assertIsNone(result.state[1].pending_on_at)


class ApiTests(unittest.TestCase):
    def test_empty_has_no_policies_and_is_not_paused(self):
        auto_state = policy.empty()
        self.assertFalse(auto_state.paused)
        self.assertEqual(auto_state.policies, {})
        self.assertEqual(auto_state.state, {})

    def test_decide_never_mutates_its_argument(self):
        rule = auto(cycle_rule(), state(last_cycle_at=MONO - 600))
        result, decision = policy.decide(snapshot(), rule, {}, MONO, at(12))
        self.assertIsNotNone(decision)
        self.assertIsNone(rule.state[1].pending_on_at)
        self.assertIsNotNone(result.state[1].pending_on_at)

    def test_reset_pauses_and_clears_every_timer(self):
        rule = auto(policy.Policy(enabled=True, cycle_s=600),
                    state(last_cycle_at=1.0, cut_at=2.0, over_at=1,
                          normal_at=2, retries=2, low_since=3.0,
                          pending_on_at=4.0, pending_text="x",
                          schedule_on=True, manual_until=5.0, wall_at=6.0))
        result = policy.reset(rule)
        self.assertTrue(result.paused)
        self.assertEqual(result.policies, rule.policies)
        self.assertEqual(result.state[1], policy.PortAuto())

    def test_a_manual_hold_of_five_seconds_is_a_constant(self):
        self.assertEqual(AUTO_MANUAL_HOLD_S, 5)


class StepTests(unittest.TestCase):
    def test_the_value_tables_step_and_wrap(self):
        rule = policy.Policy()
        self.assertEqual(policy.step(rule, "cycle", 1).cycle_s, 60)
        self.assertEqual(policy.step(rule, "cycle", -1).cycle_s, 3600)
        ten = policy.Policy(cycle_s=600)
        self.assertEqual(policy.step(ten, "cycle", 1).cycle_s, 1800)

        over = policy.Policy(overcurrent_ma=2000)
        self.assertIsNone(policy.step(over, "overcurrent", 1).overcurrent_ma)
        self.assertEqual(policy.step(policy.Policy(), "overcurrent", 1)
                         .overcurrent_ma, 500)

        self.assertEqual(policy.step(policy.Policy(), "retry", 1).retry_s, 10)
        self.assertEqual(policy.step(policy.Policy(), "recovery", 1)
                         .recovery_s, 60)

    def test_enabled_toggles_both_ways(self):
        self.assertTrue(policy.step(policy.Policy(), "enabled", 1).enabled)
        self.assertFalse(
            policy.step(policy.Policy(enabled=True), "enabled", -1).enabled)

    def test_the_schedule_toggles_and_the_hours_wrap(self):
        rule = policy.Policy()
        on = policy.step(rule, "schedule", 1)
        self.assertEqual(on.schedule, (8 * 60, 18 * 60))
        self.assertIsNone(policy.step(on, "schedule", 1).schedule)

        late = policy.Policy(schedule=(23 * 60, 0))
        self.assertEqual(policy.step(late, "from", 1).schedule,
                         (0, 0))
        self.assertEqual(policy.step(late, "to", -1).schedule, (23 * 60, 23 * 60))

    def test_the_hours_do_nothing_while_the_schedule_is_off(self):
        rule = policy.Policy()
        self.assertEqual(policy.step(rule, "from", 1), rule)


if __name__ == "__main__":
    unittest.main()
