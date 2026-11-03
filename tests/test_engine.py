import copy
import datetime
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from engine import DEFAULTS, Engine, Invalid, options


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

    def test_site_block_follows_focus_phases_and_defaults_off(self):
        self.assertFalse(DEFAULTS["blockSites"])
        self.assertFalse(self.engine.snapshot()["blockSites"])
        self.start(mode="pomodoro", blockSites=True)
        self.assertTrue(self.engine.snapshot()["blockSites"])
        self.assertFalse(self.advance(25 * 60)["blockSites"])
        self.assertTrue(self.advance(5 * 60)["blockSites"])
        self.engine.unlock("UNLOCK")
        self.assertFalse(self.engine.snapshot()["blockSites"])
        with self.assertRaisesRegex(Invalid, "invalid_options"):
            options({"blockSites": "yes"})
        legacy = self.engine.document()
        del legacy["settings"]["blockSites"]
        del legacy["settings"]["sites"]
        restored = Engine(legacy)
        self.assertFalse(restored.settings["blockSites"])
        self.assertIn("github.com", restored.settings["sites"])

    def test_saved_sites_apply_to_sessions_that_do_not_name_any(self):
        self.engine.edit_sites("add", "lobste.rs")
        self.engine.edit_sites("remove", "x.com")
        config = self.engine.configure({"guard": False, "blockSites": True})
        self.assertEqual(config["sites"][-1], "lobste.rs")
        self.engine.start(config)
        self.assertEqual(self.engine.snapshot()["sites"], config["sites"])
        self.assertEqual(self.engine.document()["settings"]["sites"], config["sites"])
        for bad in (["X.com"], "x.com", [f"s{n}.example.com" for n in range(101)]):
            with self.assertRaises(Invalid):
                options({"sites": bad})

    def test_week_tracks_live_focus_and_freezes_on_break(self):
        self.start(mode="pomodoro")
        self.assertEqual(len(self.engine.snapshot()["week"]), 7)
        self.assertEqual(self.advance(600)["week"][-1]["seconds"], 600)
        self.assertEqual(self.advance(16 * 60)["week"][-1]["seconds"], 1500)
        self.assertEqual(self.advance(60)["week"][-1]["seconds"], 1500)
        self.engine.unlock("UNLOCK")
        self.assertEqual(self.engine.snapshot()["week"][-1]["seconds"], 1500)
        restored = Engine(self.engine.document(), clock=lambda: self.now)
        self.assertEqual(restored.snapshot()["week"], self.engine.snapshot()["week"])

    def test_week_splits_midnight_and_does_not_double_count_completion(self):
        self.now = time.mktime(datetime.datetime(2026, 11, 2, 23, 30).timetuple())
        self.start(deepMinutes=60)
        state = self.advance(3600)
        self.assertEqual([d["seconds"] for d in state["week"]][-2:], [1800, 1800])
        self.engine.reset()
        self.assertEqual(self.engine.snapshot()["week"], state["week"])
        self.advance(7 * 86400)
        self.assertEqual(sum(d["seconds"] for d in self.engine.snapshot()["week"]), 0)

    def test_week_reads_legacy_history(self):
        self.engine.history = [{"endedAt": self.now, "focusedSeconds": 3600, "outcome": "complete"}]
        self.assertEqual(self.engine.snapshot()["week"][-1]["seconds"], 3600)

    def test_wave_rises_during_focus_and_falls_afterwards(self):
        self.start(deepMinutes=60)
        self.assertEqual(self.engine.snapshot()["wave"][-1]["hours"], 0)
        self.assertAlmostEqual(self.advance(1800)["wave"][-1]["hours"], 0.5)
        self.assertAlmostEqual(self.advance(1800)["wave"][-1]["hours"], 1)
        self.assertAlmostEqual(self.advance(1800)["wave"][-1]["hours"], 1)
        restored = Engine(self.engine.document(), clock=lambda: self.now)
        self.assertEqual(restored.snapshot()["wave"], self.engine.snapshot()["wave"])
        self.assertAlmostEqual(self.advance(5 * 3600)["wave"][-1]["hours"], 0.5)
        self.assertEqual(self.advance(1800)["wave"][-1]["hours"], 0)

    def test_wave_excludes_breaks_and_reads_legacy_totals(self):
        self.start(mode="pomodoro", focusMinutes=25, breakMinutes=5)
        self.assertAlmostEqual(self.advance(30 * 60)["wave"][-1]["hours"], 25 / 60)
        self.engine = Engine(clock=lambda: self.now)
        self.engine.history = [{"endedAt": self.now, "focusedSeconds": 1800, "outcome": "complete"}]
        self.assertAlmostEqual(self.engine.snapshot()["wave"][-1]["hours"], 0.5)


if __name__ == "__main__":
    unittest.main()
