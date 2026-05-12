import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: renameFilesPopupRoot
    width: 700
    height: 550
    x: Math.round((parent.width - width) / 2)
    y: Math.round((parent.height - height) / 2)
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    property var previewItemsList: []
    property int internalSeriesIndex: -1

    function openForSeries(seriesIndex) {
        internalSeriesIndex = seriesIndex
        previewItemsList = []
        open()
        if (backendBridge && seriesIndex >= 0) {
            previewItemsList = backendBridge.getRenamePreviews(seriesIndex, renameTemplateInput.text.trim())
        }
    }

    background: Rectangle {
        color: "#0F172A"
        radius: 12
        border.color: "#334155"
        border.width: 1
    }

    contentItem: ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 16

        // Dialog Header Title
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "✏️ Rename Files for: " + rootWindow.selectedSeriesTitle
                color: "#FFFFFF"
                font.pixelSize: 18
                font.bold: true
                elide: Text.ElideRight
            }
            Button {
                text: "✕"
                background: Rectangle { color: "transparent" }
                contentItem: Text { text: parent.text; color: "#94A3B8"; font.pixelSize: 18; font.bold: true }
                onClicked: renameFilesPopupRoot.close()
            }
        }

        // Template Customize Row
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            TextField {
                id: renameTemplateInput
                Layout.fillWidth: true
                text: "{SeriesTitle} S{SeasonNumber:02}E{EpisodeNumber:02} - {EpisodeTitle}"
                color: "#FFFFFF"
                background: Rectangle {
                    color: "#0B0F19"
                    radius: 6
                    border.color: "#334155"
                    border.width: 1
                }
                onAccepted: renamePreviewTriggerButton.clicked()
            }

            Button {
                id: renamePreviewTriggerButton
                text: "Preview"
                background: Rectangle {
                    color: parent.hovered ? "#D97706" : "#B45309"
                    radius: 6
                }
                contentItem: Text {
                    text: parent.text
                    color: "#FFFFFF"
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                }
                onClicked: {
                    if (backendBridge && renameFilesPopupRoot.internalSeriesIndex >= 0) {
                        renameFilesPopupRoot.previewItemsList = backendBridge.getRenamePreviews(renameFilesPopupRoot.internalSeriesIndex, renameTemplateInput.text.trim())
                    }
                }
            }
        }

        // Preview List Items View
        ListView {
            id: renamePreviewListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: renameFilesPopupRoot.previewItemsList

            delegate: Rectangle {
                id: delegateRenameContainer
                width: ListView.view.width
                height: modelData.safe ? 55 : 75
                color: "#0B0F19"
                radius: 8
                border.color: modelData.safe ? "#334155" : "#EF4444"
                border.width: 1

                required property var modelData

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: delegateRenameContainer.modelData.new_name
                        color: "#FFFFFF"
                        font.bold: true
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        text: delegateRenameContainer.modelData.old_path
                        color: "#64748B"
                        font.pixelSize: 11
                        elide: Text.ElideLeft
                    }

                    Text {
                        Layout.fillWidth: true
                        text: "⚠️ " + (delegateRenameContainer.modelData.error || "Unsafe filename")
                        color: "#EF4444"
                        font.pixelSize: 11
                        visible: !delegateRenameContainer.modelData.safe
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                text: "No items available to rename"
                color: "#64748B"
                visible: parent.model.length === 0
            }
        }

        // Bottom Apply Trigger Action Row
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true } // Spacer pushing button right

            Button {
                id: applyRenamesButton
                objectName: "applyRenamesButton"
                text: "Apply Renames"
                enabled: renameFilesPopupRoot.previewItemsList.length > 0
                background: Rectangle {
                    color: parent.enabled ? (parent.hovered ? "#059669" : "#10B981") : "#334155"
                    radius: 6
                    implicitWidth: 140
                    implicitHeight: 38
                }
                contentItem: Text {
                    text: parent.text
                    color: parent.enabled ? "#FFFFFF" : "#64748B"
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    if (backendBridge) {
                        backendBridge.applyRenames(renameFilesPopupRoot.previewItemsList)
                        renameFilesPopupRoot.close()
                    }
                }
            }
        }
    }
}
