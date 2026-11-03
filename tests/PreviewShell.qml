import QtQuick
import QtTest
import Quickshell
import qs.Commons as Commons
import "@ROOT@" as LockIn

ShellRoot {
    id: harness
    property string output: "@OUTPUT@"
    property string lastAction: ""
    property var wave: {
        const start = new Date(2026, 9, 28).getTime() / 1000
        const result = []
        for (let i = 0; i <= 156; i++) {
            const hour = i % 24
            const peak = [0.5, 0.95, 0.4, 0, 0.7, 1, 0.6][Math.floor(i / 24)]
            const value = peak * Math.pow(Math.max(0, Math.cos((hour - 11) / 8 * Math.PI / 2)), 2) * (Math.abs(hour - 11) < 8 ? 1 : 0)
            result.push({time: start + i * 3600, hours: value})
        }
        return result
    }
    property var week: [
        {date: "2026-10-28", seconds: 3600}, {date: "2026-10-29", seconds: 7200},
        {date: "2026-10-30", seconds: 1800}, {date: "2026-10-31", seconds: 0},
        {date: "2026-11-01", seconds: 5400}, {date: "2026-11-02", seconds: 9000},
        {date: "2026-11-03", seconds: 4500}]
    property var lastDetails: ({})
    property var config: ({mode: "deepwork", deepMinutes: 50, focusMinutes: 25, breakMinutes: 5,
        longBreakMinutes: 15, longBreakEvery: 4, rounds: 4, guard: true, blockSites: false, intention: ""})
    property QtObject mock: QtObject {
        property bool available: true
        property string failure: ""
        property var state: ({state: "idle", active: false, remaining: 0, settings: harness.config,
            todayMinutes: 75, todaySessions: 2, week: harness.week, wave: harness.wave, error: "", guardError: "",
            sitesReady: false, sitesSetup: false, sitesError: ""})
        function send(action, details) { harness.lastAction = action; harness.lastDetails = details || {} }
    }
    FloatingWindow {
        id: window
        visible: true
        implicitWidth: 484
        implicitHeight: card.height
        color: Commons.Color.background
        Rectangle {
            id: card
            width: 484
            height: view.implicitHeight + 64
            color: Commons.Color.background
            LockIn.FocusView { id: view; x: 32; y: 32; width: 420; service: harness.mock }
        }
        TestCase {
            name: "LockInPanel"
            when: window.visible
            function find(item, name) {
                if (item.objectName === name) return item
                for (let child of item.children || []) {
                    const match = find(child, name)
                    if (match) return match
                }
                return null
            }
            function capture(name) {
                wait(100)
                let saved = false
                const suffix = Quickshell.env("LOCKIN_PREVIEW_LANGUAGE") === "pt" ? "-pt" : ""
                verify(card.grabToImage(function(result) { saved = result.saveToFile(harness.output + "/" + name + suffix + ".png") }))
                tryVerify(function() { return saved }, 2000)
            }
            function test_panel() {
                wait(350)
                Commons.Color.foreground = "#e8e6dc"
                Commons.Color.background = "#141716"
                Commons.Color.accent = "#d4f57a"
                Commons.Color.urgent = "#e59888"
                Commons.Style.fontFamily = "JetBrainsMono Nerd Font"
                Commons.Style.cornerRadius = 0
                capture("deepwork")
                view.mode = "pomodoro"
                capture("pomodoro")
                view.mode = "deepwork"
                const sitesToggle = find(view, "sitesToggle")
                const setup = find(view, "sitesSetup")
                verify(sitesToggle.visible)
                verify(!setup.visible)
                mouseClick(sitesToggle)
                verify(view.blockSites)
                wait(20)
                verify(setup.visible)
                capture("sites-setup")
                mouseClick(setup)
                compare(harness.lastAction, "setupSites")
                mock.state = Object.assign({}, mock.state, {sitesSetup: true})
                wait(20)
                verify(!setup.enabled)
                mock.state = Object.assign({}, mock.state, {sitesSetup: false, sitesReady: true})
                wait(20)
                verify(!setup.visible)
                const start = find(view, "startButton")
                verify(start !== null)
                mouseClick(start)
                compare(harness.lastAction, "start")
                compare(harness.lastDetails.options.deepMinutes, 50)
                compare(harness.lastDetails.options.blockSites, true)
                mouseClick(sitesToggle)
                verify(!view.blockSites)
                harness.lastAction = ""
                view.forceActiveFocus()
                keyClick(Qt.Key_Space)
                compare(harness.lastAction, "start")
                mock.state = {state: "focus", active: true, remaining: 1368, progress: 0.544,
                    phase: "focus", mode: "deepwork", intention: "Ship the thing.", guard: true,
                    workspace: {id: 3, name: "3"}, round: 1, rounds: 1, settings: harness.config,
                    todayMinutes: 75, todaySessions: 2, week: harness.week, wave: harness.wave, error: "", guardError: ""}
                capture("focus")
                const sitesStatus = find(view, "sitesStatus")
                verify(!sitesStatus.visible)
                mock.state = Object.assign({}, mock.state, {blockSites: true, sitesBlocked: true})
                wait(20)
                verify(sitesStatus.visible)
                capture("focus-sites")
                mock.state = Object.assign({}, mock.state, {blockSites: false, sitesBlocked: false})
                const graph = find(view, "weekGraph")
                compare(graph.days.length, 7)
                const liveWeek = harness.week.map(day => Object.assign({}, day))
                liveWeek[6].seconds += 60
                mock.state = Object.assign({}, mock.state, {week: liveWeek})
                wait(200)
                compare(graph.days[6].seconds, 4560)
                const liveWave = harness.wave.map(sample => Object.assign({}, sample))
                liveWave[liveWave.length - 1].hours = 0.65
                mock.state = Object.assign({}, mock.state, {wave: liveWave})
                wait(200)
                compare(graph.samples[graph.samples.length - 1].hours, 0.65)
                harness.lastAction = ""
                view.forceActiveFocus()
                keyClick(Qt.Key_Space)
                compare(harness.lastAction, "")
                const markup = '<img src="https://example.invalid/tracker">'
                mock.state = Object.assign({}, mock.state, {intention: markup})
                wait(20)
                function checkText(item) {
                    if (item.text === markup) { compare(item.textFormat, Text.PlainText); return true }
                    for (const child of item.children || []) if (checkText(child)) return true
                    return false
                }
                verify(checkText(view), "The intention heading must render user text as plain text")
                mock.state = Object.assign({}, mock.state, {intention: "Ship the thing."})
                view.unlocking = true
                capture("unlock")
                const unlock = find(view, "unlockField")
                unlock.text = "UNLOCK"
                unlock.forceActiveFocus()
                keyClick(Qt.Key_Return)
                compare(harness.lastAction, "unlock")
                compare(harness.lastDetails.confirmation, "UNLOCK")
                view.unlocking = false
                mock.state = Object.assign({}, mock.state, {state: "break", phase: "short_break", mode: "pomodoro",
                    remaining: 300, progress: 0, round: 2, rounds: 4, guard: false})
                capture("break")
                mock.state = Object.assign({}, mock.state, {state: "complete", active: false, remaining: 0})
                capture("complete")
                for (const outcome of ["complete", "cancelled"]) {
                    mock.state = Object.assign({}, mock.state, {state: outcome})
                    wait(20)
                    verify(find(view, "intention").visible)
                    verify(find(view, "focusMinutes").visible)
                    harness.lastAction = ""
                    mouseClick(start)
                    compare(harness.lastAction, "start")
                    harness.lastAction = ""
                    view.forceActiveFocus()
                    keyClick(Qt.Key_Space)
                    compare(harness.lastAction, "start")
                }
                console.log("Panel checks passed")
            }
        }
    }
}
