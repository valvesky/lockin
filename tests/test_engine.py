import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from engine import DEFAULTS, Engine, Invalid


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        self.engine = Engine(clock=lambda: self.now)

    def start(self, **kwargs):
        self.engine.start({**DEFAULTS, "guard": False, **kwargs})

    def advance(self, seconds):
        self.now += seconds
        self.engine.settle()
        return self.engine.snapshot()

    def test_deepwork_finishes_exactly_once_at_deadline(self):
        self.start(deepMinutes=50)
        self.assertEqual(self.advance(2999)["remaining"], 1)
        self.assertEqual(self.advance(1)["state"], "complete")
        self.advance(600)
        self.assertEqual(len(self.engine.history), 1)
        self.assertEqual(self.engine.history[0]["focusedSeconds"], 3000)
        self.assertEqual(self.engine.snapshot()["todaySessions"], 1)

    def test_pomodoro_releases_guard_on_break_and_rearms_next_round(self):
        self.engine.start({**DEFAULTS, "mode": "pomodoro"}, {"id": 3, "name": "work"})
        self.assertTrue(self.engine.snapshot()["guard"])
        state = self.advance(25 * 60)
        self.assertEqual((state["state"], state["remaining"], state["guard"]), ("break", 300, False))
        state = self.advance(5 * 60)
        self.assertEqual((state["state"], state["round"], state["guard"]), ("focus", 2, True))

    def test_long_break_every_four_rounds_and_no_break_after_last(self):
        self.start(mode="pomodoro", rounds=5)
        kinds = [p["kind"] for p in self.engine.session["phases"]]
        self.assertEqual(kinds, ["focus", "short_break", "focus", "short_break", "focus",
                                 "short_break", "focus", "long_break", "focus"])
        self.assertEqual(self.engine.session["phases"][7]["end"] - self.engine.session["phases"][7]["start"], 900)

    def test_default_pomodoro_is_115_minutes(self):
        self.start(mode="pomodoro")
        self.assertEqual(self.engine.session["phases"][-1]["end"] - self.now, 115 * 60)
        self.assertEqual(self.advance(115 * 60)["state"], "complete")
        self.assertEqual(self.engine.history[0]["focusedSeconds"], 100 * 60)

    def test_restart_preserves_commitment_and_deadline(self):
        self.start(deepMinutes=90)
        self.advance(1000)
        restored = Engine(self.engine.document(), clock=lambda: self.now)
        self.assertEqual(restored.snapshot()["remaining"], 4400)
        self.assertRaisesRegex(Invalid, "already_active", restored.start, {"guard": False})
        self.assertRaisesRegex(Invalid, "already_active", restored.reset)

    def test_sleep_can_pass_multiple_phases_without_drift(self):
        self.start(mode="pomodoro")
        state = self.advance(65 * 60)
        self.assertEqual((state["phase"], state["round"], state["remaining"]), ("focus", 3, 1200))
        self.assertEqual(self.advance(24 * 3600)["state"], "complete")
        self.assertEqual(len(self.engine.history), 1)

    def test_emergency_unlock_requires_exact_confirmation_and_records_interruption(self):
        self.start()
        self.advance(90)
        for word in (None, "unlock", " UNLOCK", ""):
            self.assertRaisesRegex(Invalid, "confirmation_required", self.engine.unlock, word)
            self.assertTrue(self.engine.snapshot()["active"])
        self.engine.unlock("UNLOCK")
        self.assertEqual(self.engine.snapshot()["state"], "cancelled")
        self.assertEqual(self.engine.history[0]["focusedSeconds"], 90)
        self.assertEqual(self.engine.snapshot()["todaySessions"], 0)

    def test_work_time_excludes_breaks(self):
        self.start(mode="pomodoro")
        self.advance(27 * 60)
        self.engine.unlock("UNLOCK")
        self.assertEqual(self.engine.history[0]["focusedSeconds"], 25 * 60)

    def test_invalid_options_never_start(self):
        for kwargs in ({"deepMinutes": 0}, {"deepMinutes": 481}, {"rounds": True},
                       {"focusMinutes": 1.5}, {"guard": "yes"}, {"mode": "other"},
                       {"intention": "x" * 141}):
            with self.subTest(kwargs=kwargs):
                self.assertRaises(Invalid, self.start, **kwargs)
                self.assertIsNone(self.engine.session)

    def test_guard_refuses_special_or_missing_workspace(self):
        for workspace in (None, {"id": -99}, {"id": "3"}, {"id": True}):
            self.assertRaisesRegex(Invalid, "workspace_unavailable", self.engine.start, {}, workspace)

    def test_restore_rejects_corrupt_state(self):
        self.start()
        doc = self.engine.document()
        for key, value in (("startedAt", float("nan")), ("outcome", "paused"), ("config", [])):
            corrupted = copy.deepcopy(doc)
            corrupted["session"][key] = value
            self.assertRaises(Invalid, Engine, corrupted)

    def test_markup_is_kept_as_literal_user_text(self):
        self.start(intention='<img src="https://example.invalid/tracker">')
        self.assertEqual(self.engine.snapshot()["intention"], '<img src="https://example.invalid/tracker">')

    def test_history_is_bounded(self):
        for _ in range(205):
            self.start(deepMinutes=1)
            self.advance(60)
        self.assertEqual(len(self.engine.document()["history"]), 200)


if __name__ == "__main__":
    unittest.main()
