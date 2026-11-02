"""Deterministic session model. All durations are minutes, timestamps are seconds."""

from __future__ import annotations

import copy
import math
import time
import uuid

DEFAULTS = {
    "mode": "deepwork", "deepMinutes": 50, "focusMinutes": 25,
    "breakMinutes": 5, "longBreakMinutes": 15, "longBreakEvery": 4,
    "rounds": 4, "guard": True, "intention": "",
}


class Invalid(ValueError):
    pass


def options(raw):
    if not isinstance(raw, dict):
        raise Invalid("invalid_options")
    result = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    if result["mode"] not in ("deepwork", "pomodoro"):
        raise Invalid("invalid_mode")
    for key, maximum in (("deepMinutes", 480), ("focusMinutes", 180),
                         ("breakMinutes", 60), ("longBreakMinutes", 120),
                         ("longBreakEvery", 12), ("rounds", 12)):
        value = result[key]
        if type(value) is not int or not 1 <= value <= maximum:
            raise Invalid("invalid_duration")
    if type(result["guard"]) is not bool:
        raise Invalid("invalid_options")
    if not isinstance(result["intention"], str) or len(result["intention"]) > 140:
        raise Invalid("invalid_intention")
    result["intention"] = " ".join(result["intention"].split())
    return result


def schedule(config, started):
    result = []
    cursor = started
    rounds = config["rounds"] if config["mode"] == "pomodoro" else 1
    for number in range(1, rounds + 1):
        minutes = config["focusMinutes"] if config["mode"] == "pomodoro" else config["deepMinutes"]
        result.append({"kind": "focus", "round": number, "start": cursor, "end": cursor + minutes * 60})
        cursor += minutes * 60
        if number < rounds:
            long_break = number % config["longBreakEvery"] == 0
            minutes = config["longBreakMinutes"] if long_break else config["breakMinutes"]
            result.append({"kind": "long_break" if long_break else "short_break", "round": number,
                           "start": cursor, "end": cursor + minutes * 60})
            cursor += minutes * 60
    return result


class Engine:
    def __init__(self, document=None, clock=time.time):
        self.clock = clock
        self.settings = dict(DEFAULTS)
        self.session = None
        self.history = []
        if document is not None:
            self.restore(document)

    def restore(self, doc):
        if not isinstance(doc, dict) or type(doc.get("version")) is not int or doc["version"] != 1:
            raise Invalid("invalid_state")
        self.settings = options(doc.get("settings", {}))
        history = doc.get("history", [])
        if not isinstance(history, list) or len(history) > 200:
            raise Invalid("invalid_state")
        for entry in history:
            if not isinstance(entry, dict) or type(entry.get("focusedSeconds")) is not int:
                raise Invalid("invalid_state")
            ended = entry.get("endedAt")
            if not 0 <= entry["focusedSeconds"] <= 12 * 180 * 60:
                raise Invalid("invalid_state")
            if type(ended) not in (int, float) or not math.isfinite(ended) or not 0 < ended < 253402300799:
                raise Invalid("invalid_state")
        self.history = copy.deepcopy(history)
        session = doc.get("session")
        if session is None:
            return
        if not isinstance(session, dict):
            raise Invalid("invalid_state")
        config = options(session.get("config"))
        started = session.get("startedAt")
        if type(started) not in (int, float) or not math.isfinite(started) or not 0 < started < 253402300799:
            raise Invalid("invalid_state")
        if session.get("outcome") not in (None, "complete", "cancelled"):
            raise Invalid("invalid_state")
        if not isinstance(session.get("id"), str) or len(session["id"]) > 64:
            raise Invalid("invalid_state")
        workspace = session.get("workspace")
        if config["guard"] and (not isinstance(workspace, dict)
                                or type(workspace.get("id")) is not int or workspace["id"] <= 0):
            raise Invalid("invalid_state")
        if workspace is not None:
            if not isinstance(workspace, dict) or not isinstance(workspace.get("name"), str):
                raise Invalid("invalid_state")
            if len(workspace["name"]) > 200:
                raise Invalid("invalid_state")
        ended = session.get("endedAt")
        if session.get("outcome") and (type(ended) not in (int, float) or not math.isfinite(ended)):
            raise Invalid("invalid_state")
        self.session = {**copy.deepcopy(session), "config": config, "phases": schedule(config, started)}

    def document(self):
        return copy.deepcopy({"version": 1, "settings": self.settings,
                              "session": self.session, "history": self.history[-200:]})

    def start(self, raw, workspace=None):
        if self.snapshot()["active"]:
            raise Invalid("already_active")
        config = options(raw)
        if config["guard"] and (not workspace or type(workspace.get("id")) is not int or workspace["id"] <= 0):
            raise Invalid("workspace_unavailable")
        now = self.clock()
        self.settings = config
        self.session = {"id": uuid.uuid4().hex, "config": config, "startedAt": now,
                        "workspace": workspace, "phases": schedule(config, now), "outcome": None}

    def settle(self):
        if self.session and not self.session["outcome"] and self.clock() >= self.session["phases"][-1]["end"]:
            self.finish("complete", self.session["phases"][-1]["end"])
            return True
        return False

    def finish(self, outcome, ended):
        session = self.session
        session["outcome"] = outcome
        session["endedAt"] = ended
        focused = sum(max(0, min(ended, p["end"]) - p["start"])
                      for p in session["phases"] if p["kind"] == "focus")
        self.history.append({"id": session["id"], "endedAt": ended,
                             "focusedSeconds": int(focused), "outcome": outcome})
        self.history = self.history[-200:]

    def unlock(self, confirmation):
        if confirmation != "UNLOCK":
            raise Invalid("confirmation_required")
        self.settle()
        if not self.session or self.session["outcome"]:
            raise Invalid("not_active")
        self.finish("cancelled", self.clock())

    def reset(self):
        if self.snapshot()["active"]:
            raise Invalid("already_active")
        self.session = None

    def snapshot(self):
        now = self.clock()
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        daily = [e for e in self.history
                 if time.strftime("%Y-%m-%d", time.localtime(e["endedAt"])) == today]
        state = {"state": "idle", "active": False, "remaining": 0, "progress": 0,
                 "round": 0, "rounds": 0, "phase": "", "intention": "", "workspace": None,
                 "guard": False, "settings": copy.deepcopy(self.settings),
                 "todayMinutes": sum(e["focusedSeconds"] for e in daily) // 60,
                 "todaySessions": sum(e["outcome"] == "complete" for e in daily)}
        session = self.session
        if session is None:
            return state
        config = session["config"]
        state.update({"intention": config["intention"], "mode": config["mode"],
                      "rounds": config["rounds"] if config["mode"] == "pomodoro" else 1,
                      "workspace": session["workspace"]})
        if session["outcome"]:
            state.update({"state": session["outcome"], "progress": 1 if session["outcome"] == "complete" else 0})
            return state
        for phase in session["phases"]:
            if now < phase["end"]:
                duration = phase["end"] - phase["start"]
                remaining = max(0, min(duration, phase["end"] - now))
                state.update({"state": "focus" if phase["kind"] == "focus" else "break",
                              "active": True, "remaining": math.ceil(remaining),
                              "progress": max(0, min(1, 1 - remaining / duration)),
                              "phase": phase["kind"], "round": phase["round"],
                              "guard": config["guard"] and phase["kind"] == "focus"})
                return state
        state.update({"state": "complete", "progress": 1})
        return state
