import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui

BarWidget {
    id: root
    moduleName: "valvesky.lockin"
    readonly property var service: client
    readonly property bool opened: panel.opened
    readonly property bool popoutSwitchClosing: panel.popoutSwitchClosing
    readonly property var session: service ? service.state : ({})
    readonly property bool active: !!session.active
    readonly property string clock: {
        const seconds = session.remaining || 0
        return Commons.I18n.formatNumber(Math.floor(seconds / 60)) + ":"
            + (seconds % 60 < 10 ? Commons.I18n.formatNumber(0) : "")
            + Commons.I18n.formatNumber(seconds % 60)
    }
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function open() { panel.open() }
    function close() { panel.close() }
    function toggle() { opened ? close() : open() }
    function closeForPopoutSwitch() { panel.closeForPopoutSwitch() }

    SessionClient { id: client }
    Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

    WidgetButton {
        id: button
        bar: root.bar
        text: root.active && !root.vertical ? root.clock : "󰌾"
        active: root.active
        activeColor: root.session.state === "break" ? Commons.Color.foreground : Commons.Color.accent
        tooltipText: strings.t(root.active ? (root.session.state === "break" ? "bar.break" : "bar.focus") : "bar.idle")
        onPressed: function(button) { if (button === Qt.LeftButton) root.toggle() }
    }

    Panel {
        id: panel
        moduleName: root.moduleName
        bar: root.bar
        manageIpc: true
        ipcTarget: "lockin"

        KeyboardPanel {
            id: popup
            anchorItem: button
            owner: root
            bar: root.bar
            open: panel.opened
            focusTarget: view
            contentWidth: fittedContentWidth(Style.space(420))
            contentHeight: fittedContentHeight(viewport.contentHeight)

            Flickable {
                id: viewport
                // Keep control borders inside the clip at fractional display scales.
                readonly property int paintInset: Style.space(2)
                anchors.fill: parent
                contentWidth: width
                contentHeight: view.implicitHeight + paintInset * 2
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                FocusView {
                    id: view
                    x: viewport.paintInset
                    y: viewport.paintInset
                    width: viewport.width - viewport.paintInset * 2
                    service: root.service
                    onCloseRequested: root.close()
                }
            }
        }
    }
}
