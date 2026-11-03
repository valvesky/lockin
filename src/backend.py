#!/usr/bin/env python3
"""Lock-In's local JSON-line service; no network or third-party dependencies."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time

from engine import Engine, Invalid, options
import sites


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.lock = open(self.directory / "service.lock", "a", encoding="utf-8")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise Invalid("service_already_running") from exc

    def load(self):
        if not self.path.exists():
            return Engine()
        try:
            if self.path.stat().st_size > 512 * 1024:
                raise Invalid("invalid_state")
            return Engine(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, TypeError, KeyError, OverflowError, OSError) as exc:
            raise Invalid("state_unreadable") from exc

    def save(self, engine):
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, prefix=".state-", delete=False) as f:
                name = f.name
                json.dump(engine.document(), f, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        except OSError as exc:
            if name and os.path.exists(name):
                os.unlink(name)
            raise Invalid("state_unwritable") from exc

    def close(self):
        self.lock.close()


class Hyprland:
    def __init__(self):
        self.events = None
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        runtime = os.environ.get("XDG_RUNTIME_DIR", "")
        self.directory = Path(runtime) / "hypr" / signature if signature and runtime else None

    def run(self, *arguments):
        try:
            result = subprocess.run(["hyprctl", *arguments], capture_output=True, text=True, timeout=2, check=True)
            return result.stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise Invalid("hyprland_unavailable") from exc

    def current(self):
        try:
            ws = json.loads(self.run("-j", "activeworkspace"))
            if type(ws.get("id")) is not int or ws["id"] <= 0:
                raise Invalid("workspace_unavailable")
            return {"id": ws["id"], "name": str(ws.get("name", ws["id"]))[:200]}
        except (ValueError, AttributeError) as exc:
            raise Invalid("workspace_unavailable") from exc

    def connect(self):
        self.disconnect()
        if self.directory is None:
            raise Invalid("hyprland_unavailable")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(1)
        try:
            connection.connect(str(self.directory / ".socket2.sock"))
            connection.setblocking(False)
            self.events = connection
        except OSError as exc:
            connection.close()
            raise Invalid("hyprland_unavailable") from exc

    def disconnect(self):
        if self.events is not None:
            self.events.close()
            self.events = None

    @staticmethod
    def lua_string(value):
        # Decimal byte escapes are valid Lua for every UTF-8 byte, including
        # quotes, newlines, and names that resemble Lua source code.
        return '"' + "".join(f"\\{byte:03d}" for byte in str(value).encode("utf-8")) + '"'

    def dispatch(self, expression, *legacy):
        try:
            self.run("dispatch", expression)
        except Invalid:
            self.run("dispatch", *legacy)

    def focus(self, workspace_id):
        if type(workspace_id) is not int or workspace_id <= 0:
            raise Invalid("workspace_unavailable")
        self.dispatch(f'hl.dsp.focus({{ workspace = "{workspace_id}" }})', "workspace", str(workspace_id))

    def enforce(self, workspace):
        try:
            monitors = json.loads(self.run("-j", "monitors"))
            focused = next((m for m in monitors if m.get("focused")), {})
            special = focused.get("specialWorkspace", {})
            if special.get("id", 0) != 0:
                name = str(special.get("name", "")).removeprefix("special:")
                if name:
                    self.dispatch("hl.dsp.workspace.toggle_special(" + self.lua_string(name) + ")", "togglespecialworkspace", name)
        except (ValueError, TypeError, AttributeError) as exc:
            raise Invalid("hyprland_unavailable") from exc
        if self.current()["id"] != workspace["id"]:
            self.focus(workspace["id"])


class Sites:
    """Places and lifts the focus-time social media block through the root helper.

    A service only lifts a block it placed: a marker in its state directory
    records ownership, so a crash or reboot is cleaned up on the next start and
    a second service (or a test) never touches someone else's block.
    """

    SETUP = Path(__file__).resolve().with_name("site-block-setup")

    def __init__(self, directory, hosts=sites.HOSTS, helper=sites.HELPER):
        self.marker = Path(directory) / "sites-blocked"
        self.hosts = Path(hosts)
        self.helper = helper
        self.stamp = None
        self.retry_at = 0.0
        self.setup = None
        self.ready = self.allowed()

    def allowed(self):
        # The long listing names the matched rule's tags; only Lock-In's own
        # rule grants this command without authentication.
        try:
            result = subprocess.run(["sudo", "-n", "-l", "-l", self.helper, "block"],
                                    capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and "!authenticate" in result.stdout

    @property
    def setting_up(self):
        return self.setup is not None

    def begin_setup(self):
        if self.setup is not None or self.ready:
            return
        try:
            self.setup = subprocess.Popen(["pkexec", str(self.SETUP)], stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise Invalid("sites_setup_failed") from exc

    def poll_setup(self):
        if self.setup is None or self.setup.poll() is None:
            return
        self.setup = None
        self.ready = self.allowed()
        if not self.ready:
            raise Invalid("sites_setup_failed")

    def helper_run(self, action):
        if time.monotonic() < self.retry_at:
            raise Invalid("sites_unavailable")
        payload = "".join(f"{domain}\n" for domain in sites.DEFAULT_SITES) if action == "block" else ""
        try:
            subprocess.run(["sudo", "-n", self.helper, action], input=payload, capture_output=True,
                           text=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            # Back off: sudo logs every refused attempt.
            self.retry_at = time.monotonic() + 30
            self.ready = self.allowed()
            raise Invalid("sites_unavailable") from exc
        self.stamp = None

    def sync(self, want):
        owned = self.marker.exists()
        if not want:
            if owned:
                self.helper_run("unblock")
                self.marker.unlink(missing_ok=True)
            return
        try:
            stat = self.hosts.stat()
            stamp = (stat.st_mtime_ns, stat.st_ino, stat.st_size)
            # Recheck only when the file changes, e.g. a blocklist tool rewrote it.
            if owned and stamp == self.stamp:
                return
            present = sites.blocked(self.hosts.read_bytes())
        except OSError as exc:
            raise Invalid("sites_unavailable") from exc
        if not present:
            self.marker.touch(mode=0o600)
            self.helper_run("block")
        else:
            self.marker.touch(mode=0o600)
            self.stamp = stamp

    def release(self):
        try:
            self.sync(False)
        except Invalid:
            pass


class Service:
    def __init__(self, store, hyprland=None, blocker=None):
        self.store = store
        self.engine = store.load()
        self.hypr = hyprland or Hyprland()
        self.sites = blocker or Sites(store.directory)
        self.error = ""
        self.guard_error = ""
        self.sites_error = ""

    def command(self, request):
        self.error = ""
        try:
            if not isinstance(request, dict):
                raise Invalid("invalid_command")
            action = request.get("action")
            before = self.engine.document()
            try:
                if action == "start":
                    self.engine.settle()
                    if self.engine.snapshot()["active"]:
                        raise Invalid("already_active")
                    config = options(request.get("options", {}))
                    if config["blockSites"] and not self.sites.ready:
                        self.sites.ready = self.sites.allowed()
                        if not self.sites.ready:
                            raise Invalid("sites_setup_required")
                    workspace = None
                    if config["guard"]:
                        workspace = self.hypr.current()
                        # A guard that cannot observe workspace changes must refuse to start.
                        self.hypr.connect()
                    self.engine.start(config, workspace)
                elif action == "unlock":
                    self.engine.unlock(request.get("confirmation"))
                elif action == "reset":
                    self.engine.reset()
                elif action == "setupSites":
                    self.sites.begin_setup()
                    return
                elif action == "status":
                    return
                else:
                    raise Invalid("invalid_command")
                self.store.save(self.engine)
            except Exception:
                self.engine = Engine(before, clock=self.engine.clock)
                raise
        except Invalid as exc:
            self.error = str(exc)

    def tick(self):
        before = self.engine.document()
        if self.engine.settle():
            try:
                self.store.save(self.engine)
            except Invalid as exc:
                self.engine = Engine(before, clock=self.engine.clock)
                self.error = str(exc)
        state = self.engine.snapshot()
        self.guard_error = ""
        if state["guard"]:
            try:
                if self.hypr.events is None:
                    self.hypr.connect()
                self.hypr.enforce(state["workspace"])
            except Invalid as exc:
                self.guard_error = str(exc)
        else:
            self.hypr.disconnect()
        try:
            self.sites.poll_setup()
        except Invalid as exc:
            self.error = str(exc)
        self.sites_error = ""
        try:
            self.sites.sync(state["blockSites"])
        except Invalid as exc:
            self.sites_error = str(exc)
        return {**state, "error": self.error, "guardError": self.guard_error,
                "guardHealthy": state["guard"] and not self.guard_error,
                "sitesReady": self.sites.ready, "sitesSetup": self.sites.setting_up,
                "sitesError": self.sites_error,
                "sitesBlocked": state["blockSites"] and not self.sites_error}


def emit(state):
    print(json.dumps(state, ensure_ascii=False), flush=True)


def runtime_path(override=None):
    if override is not None:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise Invalid("runtime_unavailable")
    return Path(runtime) / "lockin"


def publish(directory, state):
    # The public heartbeat is in XDG_RUNTIME_DIR (RAM); durable state is only
    # written on mutations, never once a second.
    temporary = directory / f".status-{os.getpid()}"
    try:
        with open(temporary, "w", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as output:
            json.dump({**state, "updatedAt": time.time()}, output, ensure_ascii=False)
        os.replace(temporary, directory / "status.json")
    except OSError as exc:
        raise Invalid("runtime_unavailable") from exc


def serve(store, directory):
    service = Service(store)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    control_path = directory / "control.sock"
    # The durable-state lock is already held, so an old socket is stale.
    control_path.unlink(missing_ok=True)
    control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    control.bind(str(control_path))
    os.chmod(control_path, 0o600)
    control.listen(8)
    control.setblocking(False)
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ, "stdin")
    selector.register(control, selectors.EVENT_READ, "control")
    os.set_blocking(sys.stdin.fileno(), False)
    buffer = b""
    event_socket = None
    next_tick = 0.0
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            now = time.monotonic()
            if now >= next_tick:
                state = service.tick()
                publish(directory, state)
                emit(state)
                next_tick = time.monotonic() + 1
            if service.hypr.events is not event_socket:
                if event_socket is not None:
                    try:
                        selector.unregister(event_socket)
                    except (KeyError, ValueError):
                        pass
                event_socket = service.hypr.events
                if event_socket is not None:
                    selector.register(event_socket, selectors.EVENT_READ, "hyprland")
            for key, _mask in selector.select(max(0, next_tick - time.monotonic())):
                if key.data == "stdin":
                    chunk = os.read(sys.stdin.fileno(), 16384)
                    if not chunk:
                        running = False
                        break
                    buffer += chunk
                    if len(buffer) > 32768:
                        buffer = b""
                        service.error = "invalid_command"
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            service.command(json.loads(line))
                        except (ValueError, UnicodeDecodeError):
                            service.error = "invalid_command"
                        next_tick = 0
                elif key.data == "control":
                    connection, _ = control.accept()
                    connection.settimeout(1)
                    try:
                        with connection.makefile("rb") as stream:
                            line = stream.readline(32769)
                        if len(line) > 32768:
                            raise ValueError("Request too large")
                        service.command(json.loads(line))
                        state = service.tick()
                        publish(directory, state)
                        connection.sendall(json.dumps(state, ensure_ascii=False).encode() + b"\n")
                        emit(state)
                    except (ValueError, UnicodeDecodeError):
                        connection.sendall(b'{"error":"invalid_command"}\n')
                    except OSError:
                        pass
                    finally:
                        connection.close()
                else:
                    try:
                        data = key.fileobj.recv(65536)
                    except (OSError, BlockingIOError):
                        data = b""
                    if not data:
                        service.hypr.disconnect()
                    # Also watch focused-monitor and active-window changes, including
                    # entering another monitor without switching its workspace.
                    if not data or any(name in data for name in (b"workspace", b"focusedmon", b"activewindow", b"activespecial")):
                        next_tick = 0
    finally:
        # Never leave sites blocked behind a stopped service; a restart
        # mid-session blocks them again on its first tick.
        service.sites.release()
        selector.close()
        service.hypr.disconnect()
        control.close()
        control_path.unlink(missing_ok=True)
        (directory / "status.json").unlink(missing_ok=True)


def request(directory, raw):
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or len(raw.encode()) > 32768:
            raise Invalid("invalid_command")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(4)
            connection.connect(str(directory / "control.sock"))
            connection.sendall(json.dumps(value).encode() + b"\n")
            with connection.makefile("rb") as stream:
                result = json.loads(stream.readline(32769))
        emit(result)
        return 1 if result.get("error") else 0
    except (OSError, ValueError) as exc:
        raise Invalid("service_stopped") from exc


def main():
    parser = argparse.ArgumentParser(description="Lock-In's Omarchy service (JSON lines on stdin/stdout).")
    parser.add_argument("command", choices=["serve", "request"])
    parser.add_argument("payload", nargs="?", default='{"action":"status"}')
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--state-dir", type=Path,
                        default=Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "lockin")
    args = parser.parse_args()
    store = None
    directory = None
    try:
        directory = runtime_path(args.runtime_dir)
        if args.command == "request":
            return request(directory, args.payload)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        store = Store(args.state_dir)
        serve(store, directory)
    except BrokenPipeError:
        return 0
    except (Invalid, OSError) as exc:
        code = str(exc) if isinstance(exc, Invalid) else "service_failed"
        if args.command == "serve" and directory is not None and store is not None:
            try:
                publish(directory, {"fatal": code, "state": "idle", "active": False})
            except (Invalid, OSError):
                pass
        emit({"fatal": code})
        print(f"lockin: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
