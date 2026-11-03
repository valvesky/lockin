import QtQuick
import qs.Ui
import qs.Commons
import qs.Commons as Commons

FocusScope {
    id: root
    property var service: null
    readonly property var session: service ? service.state : ({})
    readonly property bool available: !!service && service.available
    readonly property bool active: !!session.active
    property string mode: "deepwork"
    property int deepMinutes: 50
    property int focusMinutes: 25
    property int breakMinutes: 5
    property int longBreakMinutes: 15
    property int rounds: 4
    property bool guard: true
    property bool blockSites: false
    property bool unlocking: false
    property bool help: false
    property bool initialized: false
    signal closeRequested()
    implicitHeight: content.implicitHeight
    focus: true

    readonly property color ink: Commons.Color.foreground
    readonly property color muted: Qt.alpha(ink, 0.52)
    readonly property color accent: session.state === "break" ? Commons.Color.foreground : Commons.Color.accent

    Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

    function initialize() {
        if (initialized || !available) return
        const cfg = session.settings || {}
        mode = cfg.mode || "deepwork"
        deepMinutes = cfg.deepMinutes || 50
        focusMinutes = cfg.focusMinutes || 25
        breakMinutes = cfg.breakMinutes || 5
        longBreakMinutes = cfg.longBreakMinutes || 15
        rounds = cfg.rounds || 4
        guard = cfg.guard !== false
        blockSites = cfg.blockSites === true
        intention.text = cfg.intention || ""
        initialized = true
    }
    onAvailableChanged: initialize()
    Component.onCompleted: initialize()
    onActiveChanged: { unlocking = false; unlockField.text = "" }

    function start() {
        if (active || !available) return
        service.send("start", {options: {mode: mode, deepMinutes: deepMinutes, focusMinutes: focusMinutes,
            breakMinutes: breakMinutes, longBreakMinutes: longBreakMinutes, longBreakEvery: 4,
            rounds: rounds, guard: guard, blockSites: blockSites, intention: intention.text}})
    }
    function clock(seconds) {
        return Commons.I18n.formatNumber(Math.floor(seconds / 60)) + ":"
            + (seconds % 60 < 10 ? Commons.I18n.formatNumber(0) : "")
            + Commons.I18n.formatNumber(seconds % 60)
    }
    function errorText(code) { return strings.t("error." + code, strings.t("error.generic")) }
    Keys.onEscapePressed: {
        if (unlocking) { unlocking = false; root.forceActiveFocus() }
        else if (help) help = false
        else root.closeRequested()
    }
    Keys.onPressed: function(event) {
        if (event.text === "?") { help = !help; event.accepted = true }
        else if (event.key === Qt.Key_Space && !active) { start(); event.accepted = true }
    }

    Column {
        id: content
        width: parent.width
        spacing: Style.space(18)

        Row {
            width: parent.width
            spacing: Style.space(12)
            Mark { width: Style.space(30); height: width; anchors.verticalCenter: parent.verticalCenter }
            Column {
                width: parent.width - Style.space(70)
                anchors.verticalCenter: parent.verticalCenter
                PlainLabel { text: "LOCK-IN"; font.pixelSize: Style.font.subtitle; font.bold: true; font.letterSpacing: 3 }
            }
            Button {
                text: "?"
                focusable: true
                foreground: root.muted
                horizontalPadding: Style.space(6)
                onClicked: root.help = !root.help
            }
        }

        WeekGraph {
            objectName: "weekGraph"
            width: parent.width
            days: root.session.week || []
            samples: root.session.wave || []
        }

        Rectangle { width: parent.width; height: 1; color: Qt.alpha(root.ink, 0.12) }

        Row {
            visible: !root.active
            width: parent.width
            spacing: Style.space(6)
            Repeater {
                model: ["deepwork", "pomodoro"]
                Button {
                    required property string modelData
                    width: (parent.width - parent.spacing) / 2
                    text: strings.t("mode." + modelData)
                    selected: root.mode === modelData
                    bordered: true
                    focusable: true
                    foreground: root.ink
                    onClicked: root.mode = modelData
                }
            }
        }

        PlainLabel {
            width: parent.width
            text: root.active ? (root.session.intention || strings.t("active.intention"))
                : strings.t("setup.title")
            font.pixelSize: Style.font.title
            font.bold: true
            wrapMode: Text.WordWrap
        }

        TextField {
            id: intention
            objectName: "intention"
            visible: !root.active
            width: parent.width
            placeholderText: strings.t("setup.intention")
            maximumLength: 140
            foreground: root.ink
            onAccepted: { root.forceActiveFocus(); root.start() }
        }

        Column {
            visible: root.active
            width: parent.width
            spacing: Style.space(8)
            PlainLabel {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.clock(root.session.remaining || 0)
                color: root.accent
                font.pixelSize: Style.space(76)
                font.weight: Font.Light
                font.letterSpacing: -3
            }
            PlainLabel {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.session.mode === "pomodoro"
                    ? strings.t("active.round").arg(Commons.I18n.formatNumber(root.session.round)).arg(Commons.I18n.formatNumber(root.session.rounds))
                    : strings.t("mode.deepwork")
                color: root.muted
                font.pixelSize: Style.font.bodySmall
            }
            Rectangle {
                width: parent.width
                height: Style.space(3)
                color: Qt.alpha(root.ink, 0.12)
                Rectangle { width: parent.width * (root.session.progress || 0); height: parent.height; color: root.accent }
            }
        }

        Column {
            visible: !root.active
            width: parent.width
            spacing: Style.space(14)

            Row {
                width: parent.width
                spacing: Style.space(12)
                NumberField {
                    objectName: "focusMinutes"
                    label: strings.t(root.mode === "deepwork" ? "setup.duration" : "setup.focus")
                    value: root.mode === "deepwork" ? root.deepMinutes : root.focusMinutes
                    from: 1
                    to: root.mode === "deepwork" ? 480 : 180
                    width: root.mode === "deepwork" ? parent.width : (parent.width - parent.spacing) / 2
                    fieldWidth: width
                    foreground: root.ink
                    onModified: function(value) { if (root.mode === "deepwork") root.deepMinutes = value; else root.focusMinutes = value }
                }
                NumberField {
                    visible: root.mode === "pomodoro"
                    label: strings.t("setup.break")
                    value: root.breakMinutes
                    from: 1; to: 60
                    width: (parent.width - parent.spacing) / 2
                    fieldWidth: width
                    foreground: root.ink
                    onModified: function(value) { root.breakMinutes = value }
                }
            }
            Row {
                width: parent.width
                spacing: Style.space(6)
                visible: root.mode === "deepwork"
                Repeater {
                    model: [25, 50, 90]
                    Button {
                        required property int modelData
                        width: (parent.width - parent.spacing * 2) / 3
                        text: strings.t("setup.minutes").arg(Commons.I18n.formatNumber(modelData))
                        selected: root.deepMinutes === modelData
                        focusable: true
                        foreground: root.muted
                        onClicked: root.deepMinutes = modelData
                    }
                }
            }
            Row {
                visible: root.mode === "pomodoro"
                width: parent.width
                spacing: Style.space(12)
                NumberField {
                    label: strings.t("setup.rounds")
                    value: root.rounds
                    from: 1; to: 12
                    width: (parent.width - parent.spacing) / 2
                    fieldWidth: width
                    foreground: root.ink
                    onModified: function(value) { root.rounds = value }
                }
                NumberField {
                    label: strings.t("setup.longBreak")
                    value: root.longBreakMinutes
                    from: 1; to: 120
                    width: (parent.width - parent.spacing) / 2
                    fieldWidth: width
                    foreground: root.ink
                    onModified: function(value) { root.longBreakMinutes = value }
                }
            }
        }

        Toggle {
            width: parent.width
            visible: !root.active
            label: strings.t("guard.label")
            checked: root.guard
            titleSize: Style.font.body
            foreground: root.ink
            onClicked: root.guard = !root.guard
        }

        Toggle {
            objectName: "sitesToggle"
            width: parent.width
            visible: !root.active
            label: strings.t("sites.label")
            checked: root.blockSites
            titleSize: Style.font.body
            foreground: root.ink
            onClicked: root.blockSites = !root.blockSites
        }

        Column {
            visible: !root.active && root.blockSites && root.available && !root.session.sitesReady
            width: parent.width
            spacing: Style.space(8)
            PlainLabel {
                width: parent.width
                text: strings.t("sites.setupHint")
                color: root.muted
                wrapMode: Text.WordWrap
                font.pixelSize: Style.font.bodySmall
            }
            Button {
                objectName: "sitesSetup"
                width: parent.width
                text: strings.t(root.session.sitesSetup ? "sites.waiting" : "sites.setup")
                bordered: true
                focusable: true
                foreground: root.ink
                enabled: !root.session.sitesSetup
                opacity: enabled ? 1 : 0.45
                onClicked: root.service.send("setupSites")
            }
        }

        PlainLabel {
            width: parent.width
            visible: root.active
            text: root.session.guardError ? root.errorText(root.session.guardError)
                : root.session.guard ? strings.t("guard.active").arg(Commons.I18n.formatNumber(root.session.workspace ? root.session.workspace.id : 0))
                : strings.t(root.session.state === "break" ? "guard.break" : "guard.timerOnly")
            color: root.session.guardError ? Commons.Color.urgent : root.muted
            wrapMode: Text.WordWrap
            font.pixelSize: Style.font.bodySmall
            horizontalAlignment: Text.AlignHCenter
        }

        PlainLabel {
            objectName: "sitesStatus"
            width: parent.width
            visible: (root.active && !!root.session.blockSites) || !!root.session.sitesError
            text: root.session.sitesError ? root.errorText(root.session.sitesError) : strings.t("sites.active")
            color: root.session.sitesError ? Commons.Color.urgent : root.muted
            wrapMode: Text.WordWrap
            font.pixelSize: Style.font.bodySmall
            horizontalAlignment: Text.AlignHCenter
        }

        PlainLabel {
            width: parent.width
            visible: !root.available || !!root.session.error || (!!root.service && !!root.service.failure)
            text: !root.available || (!!root.service && !!root.service.failure) ? root.errorText(root.service && root.service.failure ? root.service.failure : "connecting")
                : root.errorText(root.session.error)
            color: Commons.Color.urgent
            wrapMode: Text.WordWrap
            font.pixelSize: Style.font.bodySmall
        }

        Button {
            objectName: "startButton"
            visible: !root.active
            width: parent.width
            text: strings.t("action.start")
            bordered: true
            selected: true
            focusable: true
            fontSize: Style.font.subtitle
            verticalPadding: Style.space(12)
            foreground: root.ink
            enabled: root.available
            opacity: enabled ? 1 : 0.45
            onClicked: {
                root.forceActiveFocus()
                root.start()
            }
        }

        Button {
            width: parent.width
            visible: root.active && !root.unlocking
            text: strings.t("action.emergency")
            foreground: root.muted
            focusable: true
            onClicked: { root.unlocking = true; Qt.callLater(function() { unlockField.forceActiveFocus() }) }
        }

        Column {
            visible: root.active && root.unlocking
            width: parent.width
            spacing: Style.space(8)
            PlainLabel { width: parent.width; text: strings.t("unlock.hint"); color: root.muted; wrapMode: Text.WordWrap }
            TextField {
                id: unlockField
                objectName: "unlockField"
                width: parent.width
                placeholderText: "UNLOCK"
                maximumLength: 6
                foreground: root.ink
                onAccepted: if (text === "UNLOCK" && root.available) root.service.send("unlock", {confirmation: text})
            }
            Row {
                width: parent.width
                spacing: Style.space(8)
                Button {
                    text: strings.t("action.keepGoing")
                    width: (parent.width - parent.spacing) / 2
                    focusable: true
                    foreground: root.ink
                    onClicked: { root.unlocking = false; unlockField.text = ""; root.forceActiveFocus() }
                }
                Button {
                    text: strings.t("action.unlock")
                    width: (parent.width - parent.spacing) / 2
                    enabled: unlockField.text === "UNLOCK" && root.available
                    opacity: enabled ? 1 : 0.4
                    bordered: true
                    focusable: true
                    foreground: Commons.Color.urgent
                    onClicked: root.service.send("unlock", {confirmation: unlockField.text})
                }
            }
        }

        Column {
            width: parent.width
            visible: root.help
            spacing: Style.space(8)
            Rectangle { width: parent.width; height: 1; color: Qt.alpha(root.ink, 0.12) }
            PlainLabel { width: parent.width; text: strings.t("help.keys"); color: root.muted; wrapMode: Text.WordWrap; font.pixelSize: Style.font.caption }
            PlainLabel { width: parent.width; text: strings.t("help.limits"); color: root.muted; wrapMode: Text.WordWrap; font.pixelSize: Style.font.caption }
        }

        Rectangle { width: parent.width; height: 1; color: Qt.alpha(root.ink, 0.12) }
        Row {
            width: parent.width
            PlainLabel {
                width: parent.width * 0.65
                text: strings.t("footer.today").arg(Commons.I18n.formatNumber(root.session.todayMinutes || 0))
                color: root.muted
                font.pixelSize: Style.font.caption
            }
            PlainLabel {
                width: parent.width * 0.35
                text: strings.tn("footer.sessions", root.session.todaySessions || 0).arg(Commons.I18n.formatNumber(root.session.todaySessions || 0))
                color: root.muted
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignRight
            }
        }
    }
}
