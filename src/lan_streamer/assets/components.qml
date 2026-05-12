import QtQuick
import QtQuick.Controls

// Reusable premium customized standard controls repository
Item {
    id: componentLibrary

    // 1. Customized ScrollBar with sleek glass-like aesthetics
    component PremiumScrollBar : ScrollBar {
        id: control
        contentItem: Rectangle {
            implicitWidth: 6
            implicitHeight: 100
            radius: width / 2
            color: control.pressed ? "#38BDF8" : (control.hovered ? "#64748B" : "#334155")
            opacity: 0.8
            Behavior on color { ColorAnimation { duration: 150 } }
        }
    }

    // 2. Styled Base Dialog Container
    component PremiumDialog : Dialog {
        id: dialogControl
        modal: true
        background: Rectangle {
            color: "#0F172A"
            radius: 12
            border.color: "#334155"
            border.width: 1
        }
        header: Label {
            text: dialogControl.title
            font.pixelSize: 18
            font.bold: true
            font.family: "Inter"
            color: "#FFFFFF"
            padding: 16
        }
    }
}
