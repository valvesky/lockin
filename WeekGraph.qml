import QtQuick
import qs.Commons as Commons
import qs.Commons

Column {
    id: root
    property var days: []
    property var samples: []
    readonly property real ceiling: Math.max(1, ...samples.map(sample => sample.hours))
    readonly property color ink: Commons.Color.accent
    spacing: Style.space(8)

    Item {
        id: plot
        width: parent.width
        height: Style.space(112)
        readonly property real inset: Style.space(8)
        readonly property real floorY: height - inset
        readonly property real rangeY: height - inset * 2
        readonly property real endTime: root.samples.length ? root.samples[root.samples.length - 1].time : 1
        readonly property real startTime: root.samples.length ? root.samples[0].time : 0
        readonly property real span: Math.max(1, endTime - startTime)
        readonly property var points: root.samples.map(sample => ({
            x: inset + (width - inset * 2) * (sample.time - startTime) / span,
            y: floorY - rangeY * sample.hours / root.ceiling
        }))
        onPointsChanged: curve.requestPaint()

        function slope(i) {
            const p = plot.points
            if (i === 0 || i === p.length - 1) return 0
            const a = (p[i].y - p[i - 1].y) / Math.max(0.001, p[i].x - p[i - 1].x)
            const b = (p[i + 1].y - p[i].y) / Math.max(0.001, p[i + 1].x - p[i].x)
            if (a * b <= 0) return 0
            return Math.sign(a) * Math.min(Math.abs((a + b) / 2), 3 * Math.min(Math.abs(a), Math.abs(b)))
        }

        function at(x) {
            const points = plot.points
            if (!points.length) return Qt.point(inset, floorY)
            for (let i = 1; i < points.length; i++) {
                if (points[i].x < x) continue
                const a = points[i - 1], b = points[i]
                const t = Math.max(0, Math.min(1, (x - a.x) / Math.max(0.001, b.x - a.x)))
                const u = 1 - t, dx = b.x - a.x
                const y = u * u * u * a.y + 3 * u * u * t * (a.y + plot.slope(i - 1) * dx / 3)
                    + 3 * u * t * t * (b.y - plot.slope(i) * dx / 3) + t * t * t * b.y
                return Qt.point(a.x + dx * t, y)
            }
            return Qt.point(points[points.length - 1].x, points[points.length - 1].y)
        }

        Canvas {
            id: curve
            anchors.fill: parent
            antialiasing: true
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            Connections { target: root; function onInkChanged() { curve.requestPaint() } }
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                const points = plot.points
                if (!points.length) return
                function trace() {
                    ctx.moveTo(points[0].x, points[0].y)
                    for (let i = 1; i < points.length; i++) {
                        const a = points[i - 1], b = points[i], dx = (b.x - a.x) / 3
                        ctx.bezierCurveTo(a.x + dx, a.y + plot.slope(i - 1) * dx,
                            b.x - dx, b.y - plot.slope(i) * dx, b.x, b.y)
                    }
                }
                ctx.beginPath()
                trace()
                ctx.lineTo(points[points.length - 1].x, plot.floorY)
                ctx.lineTo(points[0].x, plot.floorY)
                ctx.closePath()
                const fill = ctx.createLinearGradient(0, plot.inset, 0, plot.floorY)
                fill.addColorStop(0, Qt.alpha(root.ink, 0.24))
                fill.addColorStop(1, Qt.alpha(root.ink, 0))
                ctx.fillStyle = fill
                ctx.fill()
                ctx.beginPath()
                trace()
                ctx.strokeStyle = root.ink
                ctx.lineWidth = Style.space(2)
                ctx.lineJoin = "round"
                ctx.lineCap = "round"
                ctx.stroke()
            }
        }

        MouseArea {
            id: scrub
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
        }
        Item {
            id: marker
            readonly property point position: plot.at(scrub.containsMouse ? scrub.mouseX : plot.width - plot.inset)
            x: position.x
            y: position.y
            Behavior on x { NumberAnimation { duration: Style.duration(180); easing.type: Easing.OutCubic } }
            Behavior on y { NumberAnimation { duration: Style.duration(180); easing.type: Easing.OutCubic } }
            Rectangle {
                width: Style.space(20); height: width; radius: width / 2
                x: -width / 2; y: -height / 2
                color: Qt.alpha(root.ink, 0.12)
            }
            Rectangle {
                width: Style.space(7); height: width; radius: width / 2
                x: -width / 2; y: -height / 2
                color: root.ink
            }
        }
        PlainLabel {
            visible: scrub.containsMouse
            x: Math.max(0, Math.min(plot.width - width, marker.x - width / 2))
            y: Math.max(0, marker.y - height - Style.space(12))
            text: {
                const t = plot.startTime + Math.max(0, Math.min(1, (scrub.mouseX - plot.inset) / (plot.width - 2 * plot.inset))) * plot.span
                const hours = (plot.floorY - marker.position.y) / plot.rangeY * root.ceiling
                return new Date(t * 1000).toLocaleString(Qt.locale(Commons.I18n.formatLocale), "ddd HH:mm")
                    + " · " + Commons.I18n.formatNumber(hours, 2) + " h / 6 h"
            }
            color: Commons.Color.foreground
            font.pixelSize: Style.font.caption
        }
    }

    Row {
        width: parent.width
        Repeater {
            model: root.days
            Column {
                required property var modelData
                required property int index
                width: root.width / 7
                spacing: Style.space(3)
                PlainLabel {
                    width: parent.width
                    text: Commons.I18n.formatNumber(modelData.seconds / 3600, 2) + " h"
                    font.pixelSize: Style.font.caption
                    color: index === 6 ? root.ink : Qt.alpha(Commons.Color.foreground, 0.65)
                    horizontalAlignment: Text.AlignHCenter
                }
                PlainLabel {
                    width: parent.width
                    text: {
                        const parts = modelData.date.split("-")
                        return new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]), 12)
                            .toLocaleDateString(Qt.locale(Commons.I18n.formatLocale), "ddd")
                    }
                    font.pixelSize: Style.font.caption
                    color: Qt.alpha(Commons.Color.foreground, 0.52)
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }
}
