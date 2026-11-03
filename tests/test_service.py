import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from backend import Hyprland, Service, Sites, Store
import sites
from engine import Engine, Invalid


class FakeHyprland:
    def __init__(self):
        self.events = None
        self.workspace = {"id": 2, "name": "2"}
        self.fail = False
        self.returns = []

    def current(self):
        if self.fail:
            raise Invalid("hyprland_unavailable")
        return self.workspace

    def connect(self):
        if self.fail:
            raise Invalid("hyprland_unavailable")
        self.events = True

    def disconnect(self):
        self.events = None

    def enforce(self, workspace):
        if self.fail:
            raise Invalid("hyprland_unavailable")
        self.returns.append(workspace)


class FakeSites:
    def __init__(self):
        self.ready = True
        self.setting_up = False
        self.wanted = []
        self.fail = False

    def allowed(self):
        return self.ready

    def begin_setup(self):
        self.setting_up = True

    def poll_setup(self):
        pass

    def sync(self, want):
        if self.fail:
            raise Invalid("sites_unavailable")
        self.wanted.append(want)

    def release(self):
        self.wanted.append(False)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addCleanup(self.store.close)
        self.hypr = FakeHyprland()
        self.sites = FakeSites()
        self.service = Service(self.store, self.hypr, self.sites)

    def test_atomic_store_roundtrip_and_exclusive_service(self):
        self.service.command({"action": "start", "options": {"guard": False}})
        self.assertTrue(self.store.load().snapshot()["active"])
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(Path(self.tmp.name).glob(".state-*")), [])
        with self.assertRaisesRegex(Invalid, "service_already_running"):
            Store(self.tmp.name)

    def test_guard_enforces_only_focus_phases(self):
        now = [1_800_000_000]
        self.service.engine.clock = lambda: now[0]
        self.service.command({"action": "start", "options": {"mode": "pomodoro"}})
        self.assertTrue(self.service.tick()["guardHealthy"])
        self.assertEqual(self.hypr.returns[-1], {"id": 2, "name": "2"})
        now[0] += 1500
        self.assertEqual(self.service.tick()["state"], "break")
        self.assertIsNone(self.hypr.events)
        self.assertEqual(len(self.hypr.returns), 1)
        now[0] += 300
        self.assertTrue(self.service.tick()["guardHealthy"])
        self.assertEqual(len(self.hypr.returns), 2)

    def test_guard_failure_is_visible_and_recovers(self):
        self.service.command({"action": "start"})
        self.hypr.fail = True
        self.assertEqual(self.service.tick()["guardError"], "hyprland_unavailable")
        self.hypr.fail = False
        self.assertTrue(self.service.tick()["guardHealthy"])

    def test_cannot_start_if_guard_is_unavailable(self):
        self.hypr.fail = True
        self.service.command({"action": "start"})
        self.assertFalse(self.service.tick()["active"])
        self.assertEqual(self.service.error, "hyprland_unavailable")

    def test_failed_save_does_not_start_or_cancel_a_session(self):
        real_save = self.store.save
        def fail(_engine):
            raise Invalid("state_unwritable")
        self.store.save = fail
        self.service.command({"action": "start", "options": {"guard": False}})
        self.assertFalse(self.service.tick()["active"])
        self.store.save = real_save
        self.service.command({"action": "start", "options": {"guard": False}})
        self.store.save = fail
        self.service.command({"action": "unlock", "confirmation": "UNLOCK"})
        self.assertTrue(self.service.tick()["active"])
        self.assertEqual(self.service.error, "state_unwritable")

    def test_unknown_actions_cannot_pause_skip_or_mutate(self):
        self.service.command({"action": "start", "options": {"guard": False}})
        before = self.service.engine.document()
        for action in ("pause", "skip", "setDuration", "stop", "rm -rf"):
            self.service.command({"action": action})
            self.assertEqual(self.service.error, "invalid_command")
            self.assertEqual(self.service.engine.document(), before)

    def test_sites_are_blocked_only_during_focus(self):
        now = [1_800_000_000]
        self.service.engine.clock = lambda: now[0]
        self.service.command({"action": "start", "options": {"mode": "pomodoro", "guard": False, "blockSites": True}})
        state = self.service.tick()
        self.assertTrue(state["sitesBlocked"])
        self.assertEqual(self.sites.wanted[-1], True)
        now[0] += 1500
        self.assertFalse(self.service.tick()["sitesBlocked"])
        self.assertEqual(self.sites.wanted[-1], False)
        now[0] += 300
        self.service.tick()
        self.assertEqual(self.sites.wanted[-1], True)
        self.service.command({"action": "unlock", "confirmation": "UNLOCK"})
        self.service.tick()
        self.assertEqual(self.sites.wanted[-1], False)

    def test_blocking_needs_setup_before_start_and_failures_show(self):
        self.sites.ready = False
        self.service.command({"action": "start", "options": {"guard": False, "blockSites": True}})
        self.assertEqual(self.service.error, "sites_setup_required")
        self.assertFalse(self.service.tick()["active"])
        self.service.command({"action": "setupSites"})
        self.assertTrue(self.service.tick()["sitesSetup"])
        self.sites.ready = True
        self.service.command({"action": "start", "options": {"guard": False, "blockSites": True}})
        self.sites.fail = True
        state = self.service.tick()
        self.assertEqual((state["active"], state["sitesError"], state["sitesBlocked"]), (True, "sites_unavailable", False))

    def test_bad_state_is_never_overwritten(self):
        self.store.path.write_text("{broken", encoding="utf-8")
        self.assertRaisesRegex(Invalid, "state_unreadable", self.store.load)
        self.assertEqual(self.store.path.read_text(), "{broken")

    def test_special_workspace_is_closed_before_returning(self):
        hypr = Hyprland()
        calls = []
        def run(*args):
            calls.append(args)
            if args == ("-j", "monitors"):
                return json.dumps([{"focused": True, "specialWorkspace": {"id": -99, "name": "special:scratch"}}])
            if args == ("-j", "activeworkspace"):
                return '{"id":3,"name":"3"}'
            return "ok"
        hypr.run = run
        hypr.enforce({"id": 2})
        self.assertIn(("dispatch", "hl.dsp.workspace.toggle_special(" + hypr.lua_string("scratch") + ")"), calls)
        self.assertEqual(calls[-1], ("dispatch", 'hl.dsp.focus({ workspace = "2" })'))

    def test_workspace_dispatch_falls_back_for_legacy_hyprland(self):
        hypr = Hyprland()
        calls = []
        def run(*args):
            calls.append(args)
            if args[1].startswith("hl."):
                raise Invalid("hyprland_unavailable")
            return "ok"
        hypr.run = run
        hypr.focus(3)
        self.assertEqual(calls[-1], ("dispatch", "workspace", "3"))

    def test_moving_focus_between_monitors_returns_to_committed_workspace(self):
        hypr = Hyprland()
        calls = []
        def run(*args):
            calls.append(args)
            if args == ("-j", "monitors"):
                return json.dumps([
                    {"focused": False, "specialWorkspace": {"id": -99, "name": "special:other"}},
                    {"focused": True, "specialWorkspace": {"id": 0, "name": ""}}])
            if args == ("-j", "activeworkspace"):
                return '{"id":8,"name":"8"}'
            return "ok"
        hypr.run = run
        hypr.enforce({"id": 2})
        self.assertEqual(calls[-1], ("dispatch", 'hl.dsp.focus({ workspace = "2" })'))
        self.assertFalse(any("toggle_special" in " ".join(call) for call in calls))

    def test_lua_workspace_names_are_escaped_as_bytes(self):
        value = '"); os.execute("touch /tmp/unsafe") --\nç'
        encoded = Hyprland.lua_string(value)
        self.assertTrue(encoded.startswith('"\\034'))
        self.assertNotIn("os.execute", encoded)
        self.assertNotIn("\n", encoded)


class SitesOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hosts = Path(self.tmp.name) / "hosts"
        self.hosts.write_bytes(b"127.0.0.1 localhost\n")
        self.calls = []
        patcher = mock.patch.object(Sites, "allowed", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.blocker = Sites(self.tmp.name, hosts=self.hosts)
        self.blocker.helper_run = self.run_helper

    def run_helper(self, action):
        self.calls.append(action)
        sites.write(str(self.hosts), sites.DEFAULT_SITES if action == "block" else None)
        self.blocker.stamp = None

    def test_never_lifts_a_block_it_did_not_place(self):
        self.hosts.write_bytes(sites.render(self.hosts.read_bytes(), ["x.com"]))
        self.blocker.sync(False)
        self.assertEqual(self.calls, [])

    def test_blocks_once_restores_after_rewrite_and_releases(self):
        self.blocker.sync(True)
        self.blocker.sync(True)
        self.blocker.sync(True)
        self.assertEqual(self.calls, ["block"])
        self.hosts.write_bytes(b"# rewritten by hblock\n127.0.0.1 localhost\n")
        self.blocker.sync(True)
        self.assertEqual(self.calls, ["block", "block"])
        # A restarted service (e.g. after a crash) still owns and lifts it.
        restarted = Sites(self.tmp.name, hosts=self.hosts)
        restarted.helper_run = self.run_helper
        restarted.release()
        self.assertEqual(self.calls[-1], "unblock")
        self.assertFalse(sites.blocked(self.hosts.read_bytes()))
        restarted.release()
        self.assertEqual(len(self.calls), 3)


class ProtocolTests(unittest.TestCase):
    def test_local_socket_routes_commands_to_one_session(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = str(Path(__file__).resolve().parents[1] / "src/backend.py")
            runtime = directory + "/runtime"
            worker = subprocess.Popen([sys.executable, backend, "serve", "--state-dir", directory, "--runtime-dir", runtime],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                ready, _, _ = select.select([worker.stdout], [], [], 5)
                self.assertTrue(ready)
                worker.stdout.readline()
                result = subprocess.run([sys.executable, backend, "request", '{"action":"start","options":{"guard":false}}', "--runtime-dir", runtime],
                    capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["state"], "focus")
                heartbeat = json.loads((Path(runtime) / "status.json").read_text())
                self.assertTrue(heartbeat["active"])
                self.assertIn("updatedAt", heartbeat)
                result = subprocess.run([sys.executable, backend, "request", '{"action":"start"}', "--runtime-dir", runtime],
                    capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["error"], "already_active")
            finally:
                worker.stdin.close()
                worker.wait(timeout=5)
                worker.stdout.close()
                worker.stderr.close()
            self.assertFalse((Path(runtime) / "control.sock").exists())
            self.assertFalse((Path(runtime) / "status.json").exists())

    def test_stream_start_invalid_input_unlock_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / "src/backend.py"), "serve", "--state-dir", directory, "--runtime-dir", directory + "/runtime"]
            worker = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            def read():
                ready, _, _ = select.select([worker.stdout], [], [], 5)
                self.assertTrue(ready, "service timed out")
                return json.loads(worker.stdout.readline())
            def request(value):
                worker.stdin.write(json.dumps(value).encode() + b"\n")
                worker.stdin.flush()
                return read()
            try:
                self.assertEqual(read()["state"], "idle")
                self.assertEqual(request({"action": "start", "options": {"guard": False}})["state"], "focus")
                self.assertEqual(request({"action": "pause"})["error"], "invalid_command")
                self.assertEqual(request({"action": "unlock", "confirmation": "UNLOCK"})["state"], "cancelled")
                worker.stdin.close()
                self.assertEqual(worker.wait(timeout=5), 0, worker.stderr.read().decode())
                saved = json.loads((Path(directory) / "state.json").read_text())
                self.assertEqual(Engine(saved).snapshot()["state"], "cancelled")
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait()
                worker.stdout.close()
                worker.stderr.close()


if __name__ == "__main__":
    unittest.main()
