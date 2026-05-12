import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: rootWindow
    objectName: "rootWindow"
    
    // Curated dark slate background palette
    color: "#0B0F19"

    // Dynamic presentation layer view state tracking
    property bool isOverviewMode: true
    property bool isSettingsMode: false
    property string selectedSeriesTitle: ""
    property string selectedSeriesPoster: ""
    property int selectedSeriesIndex: -1

    // Main layout wrapper
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 16

        // Top Header & Global Status Area
        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            Text {
                text: "LAN Streamer"
                font.pixelSize: 26
                font.bold: true
                color: "#FFFFFF"
            }

            // Library Dropdown selector styled modernly
            ComboBox {
                id: librarySelector
                objectName: "librarySelector"
                Layout.preferredWidth: 200
                model: backendBridge ? backendBridge.availableLibraries : ["Main Library"]
                
                background: Rectangle {
                    color: "#1E293B"
                    radius: 8
                    border.color: librarySelector.hovered ? "#38BDF8" : "#334155"
                    border.width: 1
                }
                contentItem: Text {
                    text: librarySelector.displayText
                    color: "#FFFFFF"
                    font.pixelSize: 14
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: 12
                }
                onActivated: {
                    if (backendBridge) {
                        backendBridge.selectLibrary(currentText)
                    }
                }
            }

            Item { Layout.fillWidth: true } // Flexible horizontal spacer

            // Reactive Live Status Message pill badge
            Rectangle {
                Layout.preferredHeight: 36
                Layout.preferredWidth: statusTextItem.implicitWidth + 32
                radius: 18
                color: "#0F172A"
                border.color: "#1E293B"
                border.width: 1

                Text {
                    id: statusTextItem
                    objectName: "statusTextItem"
                    anchors.centerIn: parent
                    text: backendBridge ? backendBridge.statusMessage : "System Ready"
                    color: "#38BDF8"
                    font.pixelSize: 13
                    font.bold: true
                }
            }

            // Settings Button to toggle configuration page
            Button {
                id: settingsButton
                objectName: "settingsButton"
                Layout.preferredHeight: 36
                Layout.preferredWidth: 140
                text: rootWindow.isSettingsMode ? "🎬 Media Library" : "⚙️ Settings"
                font.bold: true
                font.pixelSize: 13
                
                background: Rectangle {
                    radius: 18
                    color: parent.hovered ? "#334155" : "#1E293B"
                    border.color: parent.hovered ? "#38BDF8" : "#475569"
                    border.width: 1
                    Behavior on color { ColorAnimation { duration: 150 } }
                }
                contentItem: Text {
                    text: parent.text
                    color: "#FFFFFF"
                    font: parent.font
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    rootWindow.isSettingsMode = !rootWindow.isSettingsMode
                }
            }
        }

        // Dynamic StackLayout wrapper managing standalone library overview grid and detailed show viewports
        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: rootWindow.isSettingsMode ? 2 : (rootWindow.isOverviewMode ? 0 : 1)

            // Page 0: Full Library Series Poster Grid Overview
            SeriesGridView {
                objectName: "seriesGridViewComponent"
                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            // Page 1: Dedicated Multi-Pane Detail Screen
            SeriesDetailView {
                objectName: "seriesDetailViewComponent"
                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            // Page 2: Premium Global Configuration and Library Setup Page
            SettingsView {
                objectName: "settingsViewComponent"
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }
    }

    // Manual Metadata Match Search Popup Dialog
    MetadataMatchDialog {
        id: metadataMatchPopupDialog
        objectName: "metadataMatchPopupDialog"
    }

    // File Renaming Customization Dialog Overlay
    RenameFilesDialog {
        id: renameFilesPopupDialog
        objectName: "renameFilesPopupDialog"
    }
}
