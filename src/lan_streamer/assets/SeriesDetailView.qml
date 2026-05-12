import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

SplitView {
    orientation: Qt.Horizontal

    handle: Rectangle {
        implicitWidth: 6
        color: SplitHandle.hovered ? "#38BDF8" : "#1E293B"
        Behavior on color { ColorAnimation { duration: 100 } }
    }

    // Left Column: Hero Poster Area & Contextual Actions
    Rectangle {
        SplitView.preferredWidth: 260
        SplitView.minimumWidth: 200
        color: "#0F172A"
        radius: 8
        border.color: "#1E293B"
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 16

            // Back Navigation Button as topmost button
            Button {
                Layout.fillWidth: true
                Layout.preferredHeight: 40
                text: "← Back to Series Grid"
                font.bold: true
                
                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? "#334155" : "#1E293B"
                    border.color: parent.hovered ? "#38BDF8" : "#475569"
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 100 } }
                }
                contentItem: Text {
                    text: parent.text
                    color: "#38BDF8"
                    font: parent.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    rootWindow.isOverviewMode = true
                }
            }

            // Hero Poster presentation
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: width * 1.45
                radius: 10
                color: "#1E293B"
                border.color: "#334155"
                border.width: 1
                clip: true

                Image {
                    anchors.fill: parent
                    source: rootWindow.selectedSeriesPoster ? (rootWindow.selectedSeriesPoster.startsWith("http") ? rootWindow.selectedSeriesPoster : "file://" + rootWindow.selectedSeriesPoster) : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    
                    Text {
                        anchors.centerIn: parent
                        text: "🎬"
                        font.pixelSize: 48
                        visible: parent.status !== Image.Ready
                        opacity: 0.3
                    }
                }
            }

            // Series Title Header
            Text {
                Layout.fillWidth: true
                text: rootWindow.selectedSeriesTitle
                color: "#FFFFFF"
                font.pixelSize: 18
                font.bold: true
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
            }

            // Series Synopsis Summary displayed under the poster
            Text {
                Layout.fillWidth: true
                text: backendBridge ? backendBridge.selectedSeriesOverview : ""
                color: "#94A3B8"
                font.pixelSize: 13
                wrapMode: Text.Wrap
                lineHeight: 1.3
                visible: text !== ""
            }

            Item { Layout.fillHeight: true } // Bottom pusher spacing

            // Action Button: Match Metadata placed at the bottom of the column
            Button {
                id: matchMetadataButton
                Layout.fillWidth: true
                Layout.preferredHeight: 38
                text: "🔍 Match Metadata..."
                font.bold: true
                enabled: rootWindow.selectedSeriesIndex >= 0
                
                background: Rectangle {
                    radius: 6
                    color: parent.enabled ? (parent.hovered ? "#0284C7" : "#0369A1") : "#334155"
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                contentItem: Text {
                    text: parent.text
                    color: parent.enabled ? "#FFFFFF" : "#64748B"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font: parent.font
                }
                onClicked: {
                    if (backendBridge && rootWindow.selectedSeriesIndex >= 0) {
                        backendBridge.matchMetadataForSeries(rootWindow.selectedSeriesIndex)
                    }
                }
            }

            // Action Button: Rename Files placed beneath match metadata
            Button {
                id: renameFilesTriggerButton
                Layout.fillWidth: true
                Layout.preferredHeight: 38
                text: "✏️ Rename Files..."
                font.bold: true
                enabled: rootWindow.selectedSeriesIndex >= 0
                
                background: Rectangle {
                    radius: 6
                    color: parent.enabled ? (parent.hovered ? "#D97706" : "#B45309") : "#334155"
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                contentItem: Text {
                    text: parent.text
                    color: parent.enabled ? "#FFFFFF" : "#64748B"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font: parent.font
                }
                onClicked: {
                    renameFilesPopupDialog.openForSeries(rootWindow.selectedSeriesIndex)
                }
            }
        }
    }

    // Middle Column: Seasons List View
    Rectangle {
        SplitView.preferredWidth: 200
        SplitView.minimumWidth: 140
        color: "#0F172A"
        radius: 8
        border.color: "#1E293B"
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            Text {
                text: "Seasons"
                color: "#94A3B8"
                font.bold: true
                font.pixelSize: 12
            }

            ListView {
                id: seasonsListView
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                reuseItems: true
                model: backendBridge ? backendBridge.seasonModel : 0
                spacing: 4

                delegate: ItemDelegate {
                    width: ListView.view.width
                    height: 40
                    
                    required property int index
                    required property string modelDisplay
                    
                    highlighted: seasonsListView.currentIndex === index
                    
                    background: Rectangle {
                        radius: 6
                        color: parent.highlighted ? "#0284C7" : (parent.hovered ? "#1E293B" : "transparent")
                        Behavior on color { ColorAnimation { duration: 100 } }
                    }
                    contentItem: Text {
                        text: modelDisplay
                        color: parent.highlighted ? "#FFFFFF" : "#E2E8F0"
                        font.pixelSize: 14
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        seasonsListView.currentIndex = index
                        if (backendBridge) {
                            backendBridge.selectSeason(index)
                        }
                    }
                }
            }
        }
    }

    // Right Column: Focused Episode Viewport & Inline Bulk Toolbar
    Rectangle {
        SplitView.fillWidth: true
        color: "#0F172A"
        radius: 8
        border.color: "#1E293B"
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 12

            // Header Row with Bulk Operations directly positioned above episode viewport
            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Text {
                    text: "Episodes"
                    color: "#94A3B8"
                    font.bold: true
                    font.pixelSize: 13
                }

                Item { Layout.fillWidth: true } // Center gap spacer

                // Inline Action: Mark Selected Watched
                Button {
                    id: markWatchedButton
                    objectName: "markWatchedButton"
                    text: "✓ Mark Watched"
                    font.bold: true
                    enabled: episodesListView.selectedRows && episodesListView.selectedRows.length > 0
                    
                    background: Rectangle {
                        implicitWidth: 130
                        implicitHeight: 32
                        radius: 6
                        color: parent.enabled ? (parent.hovered ? "#059669" : "#10B981") : "#334155"
                        Behavior on color { ColorAnimation { duration: 150 } }
                    }
                    contentItem: Text {
                        text: parent.text
                        color: parent.enabled ? "#FFFFFF" : "#64748B"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font.bold: true
                        font.pixelSize: 12
                    }
                    onClicked: {
                        if (backendBridge && episodesListView.selectedRows) {
                            backendBridge.markEpisodesWatched(episodesListView.selectedRows)
                            episodesListView.selectedRows = [] // Clear selection after action
                        }
                    }
                }

                // Inline Action: Mark Selected Unwatched
                Button {
                    id: markUnwatchedButton
                    objectName: "markUnwatchedButton"
                    text: "✗ Mark Unwatched"
                    font.bold: true
                    enabled: episodesListView.selectedRows && episodesListView.selectedRows.length > 0
                    
                    background: Rectangle {
                        implicitWidth: 140
                        implicitHeight: 32
                        radius: 6
                        color: parent.enabled ? (parent.hovered ? "#D97706" : "#F59E0B") : "#334155"
                        Behavior on color { ColorAnimation { duration: 150 } }
                    }
                    contentItem: Text {
                        text: parent.text
                        color: parent.enabled ? "#FFFFFF" : "#64748B"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        font.bold: true
                        font.pixelSize: 12
                    }
                    onClicked: {
                        if (backendBridge && episodesListView.selectedRows) {
                            backendBridge.markEpisodesUnwatched(episodesListView.selectedRows)
                            episodesListView.selectedRows = [] // Clear selection after action
                        }
                    }
                }
            }

            // Main multiselectable episode viewport list
            ListView {
                id: episodesListView
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                reuseItems: true
                model: backendBridge ? backendBridge.episodeModel : 0
                spacing: 4
                
                property var selectedRows: []

                delegate: ItemDelegate {
                    width: ListView.view.width
                    height: 48
                    
                    required property int index
                    required property string modelDisplay
                    required property bool watched

                    property bool isSelected: episodesListView.selectedRows.indexOf(index) !== -1

                    background: Rectangle {
                        radius: 6
                        color: isSelected ? "#0369A1" : (parent.hovered ? "#1E293B" : "transparent")
                        border.color: isSelected ? "#38BDF8" : "transparent"
                        border.width: isSelected ? 1 : 0
                        Behavior on color { ColorAnimation { duration: 100 } }
                    }

                    contentItem: RowLayout {
                        spacing: 12
                        
                        // Beautiful custom status indicator pill
                        Rectangle {
                            Layout.preferredWidth: 28
                            Layout.preferredHeight: 28
                            radius: 14
                            color: watched ? "#10B981" : "#334155"
                            
                            Text {
                                anchors.centerIn: parent
                                text: watched ? "✓" : ""
                                color: "#FFFFFF"
                                font.bold: true
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: modelDisplay
                            color: isSelected ? "#FFFFFF" : "#E2E8F0"
                            font.pixelSize: 14
                            font.bold: isSelected
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }

                    onClicked: {
                        var currentSelectionArray = episodesListView.selectedRows.slice()
                        var selectionPosition = currentSelectionArray.indexOf(index)
                        if (selectionPosition !== -1) {
                            currentSelectionArray.splice(selectionPosition, 1)
                        } else {
                            currentSelectionArray.push(index)
                        }
                        episodesListView.selectedRows = currentSelectionArray
                    }
                    onDoubleClicked: {
                        if (backendBridge) {
                            backendBridge.playEpisode(index)
                        }
                    }
                }
            }
        }
    }
}
