import QtQuick
import Quickshell
import Quickshell.Io

// Replacement bars deliberately receive no live service objects. A local
// socket and a heartbeat file let every bar share the one session safely.
Scope {
    id: root
    property var state: ({state: "idle", active: false, settings: {}})
    property bool available: false
    property bool busy: false
    property string failure: ""
    property double updatedAt: 0
    readonly property string runtime: Quickshell.env("XDG_RUNTIME_DIR") + "/lockin"

    function send(action, details) {
        if (!available || busy) return
        const payload = details || {}
        payload.action = action
        busy = true
        command.exec(["python3", String(Qt.resolvedUrl("src/backend.py")).replace(/^file:\/\//, ""), "request", JSON.stringify(payload)])
    }

    FileView {
        id: status
        path: root.runtime + "/status.json"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                const value = JSON.parse(text())
                if (value.fatal) { root.available = false; root.failure = value.fatal; return }
                if (typeof value.state !== "string" || typeof value.updatedAt !== "number") throw new Error("invalid heartbeat")
                root.state = value
                root.updatedAt = value.updatedAt
                root.available = Date.now() / 1000 - value.updatedAt < 5
                root.failure = root.available ? "" : "service_stopped"
            } catch (e) { root.available = false; root.failure = "invalid_response" }
        }
        onLoadFailed: { root.available = false; root.failure = "service_stopped" }
    }
    Timer {
        interval: 2000
        repeat: true
        running: true
        onTriggered: {
            if (Date.now() / 1000 - root.updatedAt >= 5) {
                root.available = false
                root.failure = "service_stopped"
                status.reload()
            }
        }
    }
    Process {
        id: command
        stdout: SplitParser {
            onRead: function(data) {
                try {
                    const value = JSON.parse(data)
                    if (value.fatal) root.failure = value.fatal
                    else if (typeof value.state === "string") { root.state = value; root.failure = "" }
                } catch (e) { root.failure = "invalid_response" }
            }
        }
        onExited: function(code) { root.busy = false; if (code !== 0 && !root.failure) status.reload() }
    }
}
