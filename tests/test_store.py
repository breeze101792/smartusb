"""State file: round trip, tolerance and atomic replacement."""

import json
import tempfile
import unittest
from pathlib import Path

from hubctl.app import policy, store
from hubctl.constants import POLL_INTERVAL_S, POLL_MAX_S


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "hubctl" / "state.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip_keeps_poll_and_rules(self):
        rule = policy.Policy(enabled=True, cycle_s=600, overcurrent_ma=1800,
                             over_action=policy.ACTION_CYCLE, under_ma=100,
                             retry_s=30, recovery_s=300,
                             schedule=(8 * 60, 18 * 60))
        store.save(self.path, 1.5, {2: rule})
        poll, rules = store.load(self.path)
        self.assertEqual(poll, 1.5)
        self.assertEqual(rules, {2: rule})

    def test_a_missing_file_is_ignored(self):
        self.assertIsNone(store.load(self.path))

    def test_a_corrupt_file_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(store.load(self.path))

    def test_another_version_is_ignored(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"version": 99, "poll_s": 1.0}),
                             encoding="utf-8")
        self.assertIsNone(store.load(self.path))

    def test_unknown_fields_and_bad_values_fall_back(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({
            "version": store.STATE_VERSION,
            "poll_s": 99.0,
            "policies": {
                "1": {"enabled": True, "overcurrent_ma": 1500,
                      "over_action": "explode", "under_action": "cycle",
                      "schedule": [1, 2, 3], "extra": 1},
                "9": {"enabled": True},
                "x": {"enabled": True},
            },
        }), encoding="utf-8")
        poll, rules = store.load(self.path)
        self.assertEqual(poll, POLL_MAX_S)
        self.assertEqual(set(rules), {1})
        self.assertEqual(rules[1].overcurrent_ma, 1500)
        self.assertEqual(rules[1].over_action, policy.ACTION_CUT)
        self.assertIsNone(rules[1].schedule)
        self.assertEqual(rules[1].under_action, policy.ACTION_CYCLE)

    def test_the_default_path_follows_xdg(self):
        previous = __import__("os").environ.get("XDG_STATE_HOME")
        __import__("os").environ["XDG_STATE_HOME"] = "/tmp/xdg-state"
        try:
            self.assertEqual(store.default_path(),
                             Path("/tmp/xdg-state/hubctl/state.json"))
        finally:
            if previous is None:
                del __import__("os").environ["XDG_STATE_HOME"]
            else:
                __import__("os").environ["XDG_STATE_HOME"] = previous

    def test_the_file_holds_only_settings(self):
        store.save(self.path, POLL_INTERVAL_S, {})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"version", "poll_s", "policies"})


if __name__ == "__main__":
    unittest.main()
