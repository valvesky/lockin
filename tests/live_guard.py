#!/usr/bin/env python3
"""Explicit integration check: briefly switch to an empty workspace and back."""
import json
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from backend import Hyprland


def hypr(*args):
    return subprocess.check_output(["hyprctl", *args], text=True, timeout=3)


original = json.loads(hypr("-j", "activeworkspace"))["id"]
assert original > 0, "Run from a regular workspace"
test_workspace = max(w["id"] for w in json.loads(hypr("-j", "workspaces"))) + 1000
with tempfile.TemporaryDirectory(prefix="lockin-live-") as directory:
    process = subprocess.Popen([sys.executable, str(root / "src/backend.py"), "serve",
        "--state-dir", directory, "--runtime-dir", directory + "/runtime"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    def read():
        ready, _, _ = select.select([process.stdout], [], [], 5)
        assert ready, "Backend timed out"
        return json.loads(process.stdout.readline())
    try:
        read()
        process.stdin.write(b'{"action":"start","options":{"deepMinutes":1}}\n')
        process.stdin.flush()
        state = read()
        assert state["guardHealthy"], state
        Hyprland().focus(test_workspace)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if json.loads(hypr("-j", "activeworkspace"))["id"] == original:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Guard did not return to the committed workspace")
        print("Live Hyprland workspace guard passed.")
    finally:
        if process.poll() is None:
            process.stdin.write(b'{"action":"unlock","confirmation":"UNLOCK"}\n')
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=5)
        if json.loads(hypr("-j", "activeworkspace"))["id"] == test_workspace:
            Hyprland().focus(original)
        process.stdout.close()
        process.stderr.close()
