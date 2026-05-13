import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: metadataMatchPopupRoot
    width: 750
    height: 600
    x: Math.round((parent.width - width) / 2)
    y: Math.round((parent.height - height) / 2)
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    
    property string targetSeriesName: ""

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

        // Header Title
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: "🔍 Match Metadata for: " + metadataMatchPopupRoot.targetSeriesName
                color: "#FFFFFF"
                font.pixelSize: 18
                font.bold: true
                elide: Text.ElideRight
            }
            Button {
                objectName: "closeMetadataMatchDialogButton"
                text: "✕"
                background: Rectangle { color: "transparent" }
                contentItem: Text { text: parent.text; color: "#94A3B8"; font.pixelSize: 18; font.bold: true }
                onClicked: metadataMatchPopupRoot.close()
            }
        }

        // Search Input Row
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            ComboBox {
                id: metadataSearchProviderComboBox
                Layout.preferredWidth: 160
                model: ["TMDB", "Jellyfin"]
                background: Rectangle {
                    color: "#0B0F19"
                    radius: 6
                    border.color: "#334155"
                    border.width: 1
                }
                contentItem: Text {
                    text: parent.displayText
                    color: "#FFFFFF"
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                    font.bold: true
                }
                onActivated: metadataSearchTriggerButton.clicked()
            }

            TextField {
                id: metadataSearchQueryInput
                Layout.fillWidth: true
                placeholderText: "Search Title..."
                color: "#FFFFFF"
                placeholderTextColor: "#64748B"
                background: Rectangle {
                    color: "#0B0F19"
                    radius: 6
                    border.color: "#334155"
                    border.width: 1
                }
                onAccepted: metadataSearchTriggerButton.clicked()
            }

            Button {
                id: metadataSearchTriggerButton
                objectName: "metadataSearchTriggerButton"
                text: "Search"
                background: Rectangle {
                    color: parent.hovered ? "#0284C7" : "#0369A1"
                    radius: 6
                }
                contentItem: Text {
                    text: parent.text
                    color: "#FFFFFF"
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                }
                onClicked: {
                    if (backendBridge && metadataSearchQueryInput.text.trim() !== "") {
                        metadataSearchResultsListView.model = backendBridge.searchSeriesMetadata(metadataSearchQueryInput.text.trim(), metadataSearchProviderComboBox.currentText)
                    }
                }
            }
        }

        // Results List
        ListView {
            id: metadataSearchResultsListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: []

            delegate: Rectangle {
                id: delegateResultContainer
                width: ListView.view.width
                height: 70
                color: searchResultMouseArea.containsMouse ? "#1E293B" : "#0B0F19"
                radius: 8
                border.color: searchResultMouseArea.containsMouse ? "#38BDF8" : "#334155"
                border.width: 1
                Behavior on color { ColorAnimation { duration: 100 } }

                required property var modelData

                MouseArea {
                    id: searchResultMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 12

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Text {
                            Layout.fillWidth: true
                            text: delegateResultContainer.modelData.name + (delegateResultContainer.modelData.first_air_date ? " (" + delegateResultContainer.modelData.first_air_date.substring(0, 4) + ")" : "")
                            color: "#FFFFFF"
                            font.bold: true
                            font.pixelSize: 14
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: delegateResultContainer.modelData.overview || "No description available."
                            color: "#94A3B8"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            maximumLineCount: 2
                        }
                    }

                    Button {
                        objectName: "applyMetadataMatchButton"
                        text: "Apply"
                        background: Rectangle {
                            color: parent.hovered ? "#059669" : "#10B981"
                            radius: 6
                        }
                        contentItem: Text {
                            text: parent.text
                            color: "#FFFFFF"
                            font.bold: true
                            font.pixelSize: 12
                        }
                        onClicked: {
                            if (backendBridge) {
                                backendBridge.applySeriesMetadataMatch(metadataMatchPopupRoot.targetSeriesName, delegateResultContainer.modelData)
                                metadataMatchPopupRoot.close()
                            }
                        }
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                text: "No search results found"
                color: "#64748B"
                visible: parent.model.length === 0
            }
        }
    }

    Connections {
        target: backendBridge
        function onOpenMetadataMatchDialog(seriesTargetName) {
            metadataMatchPopupRoot.targetSeriesName = seriesTargetName
            metadataSearchQueryInput.text = seriesTargetName
            metadataSearchResultsListView.model = []
            metadataMatchPopupRoot.open()
            // Auto-trigger initial search
            if (backendBridge && seriesTargetName.trim() !== "") {
                metadataSearchResultsListView.model = backendBridge.searchSeriesMetadata(seriesTargetName.trim(), metadataSearchProviderComboBox.currentText)
            }
        }
    }
}
