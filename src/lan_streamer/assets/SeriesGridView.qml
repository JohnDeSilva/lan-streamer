import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    color: "#0F172A"
    radius: 8
    border.color: "#1E293B"
    border.width: 1

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            Text {
                text: "Media Library Overview"
                color: "#94A3B8"
                font.bold: true
                font.pixelSize: 13
            }

            Item { Layout.fillWidth: true } // horizontal right-align spacer

            CheckBox {
                text: "Hide Watched"
                checked: backendBridge ? backendBridge.filterOutWatched : false
                contentItem: Text {
                    text: parent.text
                    color: parent.checked ? "#38BDF8" : "#94A3B8"
                    font.bold: true
                    font.pixelSize: 12
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: parent.indicator.width + 6
                }
                onCheckedChanged: {
                    if (backendBridge && backendBridge.filterOutWatched !== checked) {
                        backendBridge.filterOutWatched = checked
                    }
                }
            }

            Text {
                text: "Sort:"
                color: "#64748B"
                font.pixelSize: 12
            }

            ComboBox {
                implicitWidth: 165
                model: ["Alphabetical", "Recently Added", "Recently Aired"]
                currentIndex: {
                    if (!backendBridge) return 0;
                    var sortOptionString = backendBridge.seriesSortOption;
                    if (sortOptionString === "Recently Added") return 1;
                    if (sortOptionString === "Recently Aired") return 2;
                    return 0;
                }
                
                contentItem: Text {
                    text: parent.displayText
                    color: "#E2E8F0"
                    font.pixelSize: 12
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 8
                }
                background: Rectangle {
                    implicitHeight: 32
                    color: "#1E293B"
                    radius: 6
                    border.color: "#334155"
                }
                onActivated: {
                    if (backendBridge) {
                        backendBridge.seriesSortOption = currentText
                    }
                }
            }

            ComboBox {
                implicitWidth: 240
                model: ["⚡ Library Actions ▼", "🔄 Search for New Files", "⚡ Full Library Refresh", "🧹 Library Cleanup"]
                currentIndex: 0
                
                contentItem: Text {
                    text: parent.displayText
                    color: "#FFFFFF"
                    font.bold: true
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    implicitHeight: 32
                    color: parent.hovered ? "#059669" : "#10B981"
                    radius: 6
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                onActivated: function(actionIndex) {
                    if (actionIndex === 1) {
                        if (backendBridge) backendBridge.scanForNewFiles()
                    } else if (actionIndex === 2) {
                        if (backendBridge) backendBridge.refreshEntireLibrary()
                    } else if (actionIndex === 3) {
                        if (backendBridge) backendBridge.cleanupLibrary()
                    }
                    currentIndex = 0
                }
            }

            ComboBox {
                implicitWidth: 220
                visible: backendBridge ? backendBridge.jellyfinEnabled : false
                model: ["🎬 Watch History ▼", "⬇️ Pull from Jellyfin", "⬆️ Push to Jellyfin"]
                currentIndex: 0
                
                contentItem: Text {
                    text: parent.displayText
                    color: "#FFFFFF"
                    font.bold: true
                    font.pixelSize: 12
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    implicitHeight: 32
                    color: parent.hovered ? "#0284C7" : "#0369A1"
                    radius: 6
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                onActivated: function(actionIndex) {
                    if (actionIndex === 1) {
                        if (backendBridge) backendBridge.pullWatchHistoryFromJellyfin()
                    } else if (actionIndex === 2) {
                        if (backendBridge) backendBridge.pushWatchHistoryToJellyfin()
                    }
                    currentIndex = 0
                }
            }
        }

        GridView {
            id: seriesGridView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            reuseItems: true
            model: backendBridge ? backendBridge.seriesModel : 0
            cellWidth: 140
            cellHeight: 215

            delegate: Item {
                width: seriesGridView.cellWidth
                height: seriesGridView.cellHeight
                
                required property int index
                required property string modelDisplay
                required property string posterPath

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 8
                    radius: 10
                    color: parent.hovered ? "#1E293B" : "#0B0F19"
                    border.color: parent.hovered ? "#38BDF8" : "#334155"
                    border.width: parent.hovered ? 2 : 1
                    Behavior on color { ColorAnimation { duration: 150 } }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 6
                        spacing: 6

                        // Poster Image Container
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 8
                            color: "#1E293B"
                            clip: true

                            Image {
                                anchors.fill: parent
                                source: posterPath ? (posterPath.startsWith("http") ? posterPath : "file://" + posterPath) : ""
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                
                                Text {
                                    anchors.centerIn: parent
                                    text: "🎬"
                                    font.pixelSize: 32
                                    visible: parent.status !== Image.Ready
                                    opacity: 0.3
                                }
                            }
                        }

                        // Title label below poster
                        Text {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 32
                            text: modelDisplay
                            color: "#FFFFFF"
                            font.pixelSize: 12
                            font.bold: true
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            rootWindow.selectedSeriesTitle = modelDisplay
                            rootWindow.selectedSeriesPoster = posterPath
                            rootWindow.selectedSeriesIndex = index
                            if (backendBridge) {
                                backendBridge.selectSeries(index)
                            }
                            rootWindow.isOverviewMode = false
                        }
                    }
                }
            }
        }
    }
}
