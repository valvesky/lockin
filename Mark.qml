import QtQuick
import qs.Commons as Commons

// Four corners and a center point: attention, narrowed to one thing.
Item {
    id: root
    property color ink: Commons.Color.accent
    implicitWidth: 32
    implicitHeight: 32
    Repeater {
        model: 4
        Item {
            required property int index
            width: root.width
            height: root.height
            rotation: index * 90
            Rectangle { x: 1; y: 1; width: parent.width * 0.31; height: 2; color: root.ink }
            Rectangle { x: 1; y: 1; width: 2; height: parent.height * 0.31; color: root.ink }
        }
    }
    Rectangle {
        width: root.width * 0.2
        height: width
        anchors.centerIn: parent
        color: root.ink
    }
}
