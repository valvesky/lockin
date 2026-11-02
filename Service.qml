import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons as Commons

Scope {
    id: root
    property var shell: null
    property var manifest: null
    property var state: ({state: "idle", active: false, remaining: 0, settings: {}, todayMinutes: 0, todaySessions: 0})
    property bool available: false
    property string failure: ""
    property string lastPhase: ""

    Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }
    Commons.ShellIpc {
        target: "lockin-session"
        function status(): string { return JSON.stringify({available: root.available, failure: root.failure, session: root.state}) }
    }

    function send(action, details) {
        if (!available) return
        const request = details || {}
        request.action = action
        worker.write(JSON.stringify(request) + "\n")
    }

    Process {
        id: worker
        command: ["python3", String(Qt.resolvedUrl("src/backend.py")).replace(/^file:\/\//, ""), "serve"]
        stdinEnabled: true
        running: true
        stdout: SplitParser {
            onRead: function(data) {
                try {
                    const value = JSON.parse(data)
                    if (value.fatal) {
                        root.failure = value.fatal
                        root.available = false
                    } else if (typeof value.state === "string") {
                        const phase = value.state + ":" + (value.round || 0)
                        if (root.lastPhase && phase !== root.lastPhase && value.state !== "idle" && value.state !== "cancelled") {
                            const key = value.state === "complete" ? "notice.complete" : value.state === "break" ? "notice.break" : "notice.focus"
                            notice.exec(["notify-send", "--app-name=Lock-In", "--icon=appointment-soon", "Lock-In", strings.t(key)])
                        }
                        root.lastPhase = phase
                        root.state = value
                        root.failure = ""
                        root.available = true
                    }
                } catch (e) {
                    root.failure = "invalid_response"
                    root.available = false
                }
            }
        }
        stderr: SplitParser { onRead: function(data) { console.warn("Lock-In: " + data) } }
        onExited: {
            root.available = false
            if (!root.failure) root.failure = "service_stopped"
            retry.restart()
        }
    }
    Process { id: notice }
    Timer {
        id: retry
        interval: 5000
        onTriggered: worker.running = true
    }
}
