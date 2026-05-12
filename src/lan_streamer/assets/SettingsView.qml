import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    color: "#0F172A"
    radius: 8
    border.color: "#1E293B"
    border.width: 1

    ScrollView {
        id: settingsScrollView
        anchors.fill: parent
        anchors.margins: 24
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: settingsScrollView.availableWidth
            spacing: 24

            Text {
                text: "System Configuration & Library Management"
                color: "#FFFFFF"
                font.pixelSize: 20
                font.bold: true
            }

            // Section 1: Library Management
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: libraryManagementLayout.implicitHeight + 32
                color: "#1E293B"
                radius: 8
                border.color: "#334155"
                border.width: 1

                ColumnLayout {
                    id: libraryManagementLayout
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 16

                    Text {
                        text: "📁 Libraries Setup"
                        color: "#38BDF8"
                        font.pixelSize: 16
                        font.bold: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16

                        Text {
                            Layout.preferredWidth: 160
                            text: "Select Library:"
                            color: "#94A3B8"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }

                        ComboBox {
                            id: settingsLibraryComboBox
                            Layout.fillWidth: true
                            model: backendBridge ? backendBridge.availableLibraries : []
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
                            }
                            onActivated: {
                                settingsDirectoriesListView.refreshDirectories()
                            }
                        }

                        Button {
                            Layout.preferredWidth: 220
                            text: "❌ Remove Selected Library"
                            background: Rectangle {
                                color: parent.hovered ? "#DC2626" : "#EF4444"
                                radius: 6
                            }
                            contentItem: Text {
                                text: parent.text
                                color: "#FFFFFF"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                if (backendBridge && settingsLibraryComboBox.currentText !== "") {
                                    backendBridge.removeSelectedLibrary(settingsLibraryComboBox.currentText)
                                    settingsDirectoriesListView.refreshDirectories()
                                }
                            }
                        }
                    }

                    // Add New Library Row
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16

                        Text {
                            Layout.preferredWidth: 160
                            text: "New Library Name:"
                            color: "#94A3B8"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }

                        TextField {
                            id: newLibraryNameInput
                            Layout.fillWidth: true
                            placeholderText: "Enter new library name..."
                            color: "#FFFFFF"
                            placeholderTextColor: "#64748B"
                            background: Rectangle {
                                color: "#0B0F19"
                                radius: 6
                                border.color: "#334155"
                                border.width: 1
                            }
                        }

                        Button {
                            Layout.preferredWidth: 220
                            text: "➕ Add New Library"
                            background: Rectangle {
                                color: parent.hovered ? "#059669" : "#10B981"
                                radius: 6
                            }
                            contentItem: Text {
                                text: parent.text
                                color: "#FFFFFF"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                if (backendBridge && newLibraryNameInput.text.trim() !== "") {
                                    backendBridge.addNewLibrary(newLibraryNameInput.text.trim())
                                    newLibraryNameInput.text = ""
                                    settingsDirectoriesListView.refreshDirectories()
                                }
                            }
                        }
                    }

                    // Directories list for the selected library
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16

                        Text {
                            Layout.preferredWidth: 160
                            Layout.alignment: Qt.AlignTop
                            text: "Root Directories:"
                            color: "#94A3B8"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }

                        ListView {
                            id: settingsDirectoriesListView
                            Layout.fillWidth: true
                            implicitHeight: Math.max(40, count * 36)
                            clip: true
                            spacing: 4
                            model: []

                            function refreshDirectories() {
                                if (backendBridge && settingsLibraryComboBox.currentText !== "") {
                                    model = backendBridge.getRootDirectoriesForLibrary(settingsLibraryComboBox.currentText)
                                } else {
                                    model = []
                                }
                            }

                            Component.onCompleted: refreshDirectories()
                            Connections {
                                target: backendBridge
                                function onAvailableLibrariesChanged() {
                                    settingsDirectoriesListView.refreshDirectories()
                                }
                            }

                            delegate: Rectangle {
                                width: ListView.view.width
                                height: 32
                                color: "#0B0F19"
                                radius: 4
                                border.color: "#334155"
                                border.width: 1

                                required property string modelData

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    spacing: 8

                                    Text {
                                        Layout.fillWidth: true
                                        text: modelData
                                        color: "#E2E8F0"
                                        elide: Text.ElideMiddle
                                    }

                                    Button {
                                        text: "Remove"
                                        background: Rectangle { color: parent.hovered ? "#991B1B" : "#7F1D1D"; radius: 4 }
                                        contentItem: Text { text: parent.text; color: "#FFFFFF"; font.pixelSize: 11; font.bold: true }
                                        onClicked: {
                                            if (backendBridge) {
                                                backendBridge.removeRootDirectoryFromLibrary(settingsLibraryComboBox.currentText, modelData)
                                                settingsDirectoriesListView.refreshDirectories()
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        Item {
                            Layout.preferredWidth: 220
                        }
                    }

                    // Add root directory input
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 16

                        Text {
                            Layout.preferredWidth: 160
                            text: "Add Directory Path:"
                            color: "#94A3B8"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }

                        TextField {
                            id: newDirectoryPathInput
                            Layout.fillWidth: true
                            placeholderText: "Enter absolute directory path to add..."
                            color: "#FFFFFF"
                            placeholderTextColor: "#64748B"
                            background: Rectangle {
                                color: "#0B0F19"
                                radius: 6
                                border.color: "#334155"
                                border.width: 1
                            }
                        }

                        Button {
                            Layout.preferredWidth: 220
                            text: "➕ Add Directory Path"
                            background: Rectangle {
                                color: parent.hovered ? "#0284C7" : "#0369A1"
                                radius: 6
                            }
                            contentItem: Text {
                                text: parent.text
                                color: "#FFFFFF"
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                            onClicked: {
                                if (backendBridge && settingsLibraryComboBox.currentText !== "" && newDirectoryPathInput.text.trim() !== "") {
                                    backendBridge.addRootDirectoryToLibrary(settingsLibraryComboBox.currentText, newDirectoryPathInput.text.trim())
                                    newDirectoryPathInput.text = ""
                                    settingsDirectoriesListView.refreshDirectories()
                                }
                            }
                        }
                    }
                }
            }

            // Section 2: Metadata & Sync API Configuration
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: apiConfigurationLayout.implicitHeight + 32
                color: "#1E293B"
                radius: 8
                border.color: "#334155"
                border.width: 1

                ColumnLayout {
                    id: apiConfigurationLayout
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 16

                    Text {
                        text: "🌐 API & Watch History Configuration"
                        color: "#38BDF8"
                        font.pixelSize: 16
                        font.bold: true
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 12

                        Text {
                            Layout.preferredWidth: 160
                            text: "Jellyfin Server URL:"
                            color: "#E2E8F0"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }
                        TextField {
                            Layout.fillWidth: true
                            text: backendBridge ? backendBridge.configJellyfinUrl : ""
                            placeholderText: "http://localhost:8096"
                            color: "#FFFFFF"
                            background: Rectangle { color: "#0B0F19"; radius: 6; border.color: "#334155"; border.width: 1 }
                            onEditingFinished: if (backendBridge) backendBridge.configJellyfinUrl = text
                        }

                        Text {
                            Layout.preferredWidth: 160
                            text: "Jellyfin API Token:"
                            color: "#E2E8F0"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }
                        TextField {
                            Layout.fillWidth: true
                            text: backendBridge ? backendBridge.configJellyfinApiKey : ""
                            placeholderText: "Enter API Token..."
                            echoMode: TextInput.PasswordEchoOnEdit
                            color: "#FFFFFF"
                            background: Rectangle { color: "#0B0F19"; radius: 6; border.color: "#334155"; border.width: 1 }
                            onEditingFinished: if (backendBridge) backendBridge.configJellyfinApiKey = text
                        }

                        Text {
                            Layout.preferredWidth: 160
                            text: "TMDB API Key:"
                            color: "#E2E8F0"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }
                        TextField {
                            Layout.fillWidth: true
                            text: backendBridge ? backendBridge.configTmdbApiKey : ""
                            placeholderText: "Enter TMDB API Key..."
                            echoMode: TextInput.PasswordEchoOnEdit
                            color: "#FFFFFF"
                            background: Rectangle { color: "#0B0F19"; radius: 6; border.color: "#334155"; border.width: 1 }
                            onEditingFinished: if (backendBridge) backendBridge.configTmdbApiKey = text
                        }
                    }

                    CheckBox {
                        text: "Sync Jellyfin Watch History on Application Startup"
                        checked: backendBridge ? backendBridge.configSyncHistoryOnStart : true
                        contentItem: Text {
                            text: parent.text
                            color: "#E2E8F0"
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: parent.indicator.width + 8
                        }
                        onCheckedChanged: if (backendBridge) backendBridge.configSyncHistoryOnStart = checked
                    }
                }
            }

            // Section 3: Playback & System Options
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: systemOptionsLayout.implicitHeight + 32
                color: "#1E293B"
                radius: 8
                border.color: "#334155"
                border.width: 1

                ColumnLayout {
                    id: systemOptionsLayout
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 16

                    Text {
                        text: "🖥️ Playback & Application Options"
                        color: "#38BDF8"
                        font.pixelSize: 16
                        font.bold: true
                    }

                    CheckBox {
                        text: "Use Integrated Embedded Video Player"
                        checked: backendBridge ? backendBridge.configUseEmbeddedPlayer : true
                        contentItem: Text { text: parent.text; color: "#E2E8F0"; verticalAlignment: Text.AlignVCenter; leftPadding: parent.indicator.width + 8 }
                        onCheckedChanged: if (backendBridge) backendBridge.configUseEmbeddedPlayer = checked
                    }

                    CheckBox {
                        text: "Enable Hardware Accelerated Decoding"
                        checked: backendBridge ? backendBridge.configEnableHardwareAcceleration : true
                        contentItem: Text { text: parent.text; color: "#E2E8F0"; verticalAlignment: Text.AlignVCenter; leftPadding: parent.indicator.width + 8 }
                        onCheckedChanged: if (backendBridge) backendBridge.configEnableHardwareAcceleration = checked
                    }

                    CheckBox {
                        text: "Enable Persistent Global File Logging"
                        checked: backendBridge ? backendBridge.configEnableGlobalFileLogging : false
                        contentItem: Text { text: parent.text; color: "#E2E8F0"; verticalAlignment: Text.AlignVCenter; leftPadding: parent.indicator.width + 8 }
                        onCheckedChanged: if (backendBridge) backendBridge.configEnableGlobalFileLogging = checked
                    }
                }
            }

            // Section 4: Advanced System Configuration
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: advancedConfigLayout.implicitHeight + 32
                color: "#1E293B"
                radius: 8
                border.color: "#334155"
                border.width: 1

                ColumnLayout {
                    id: advancedConfigLayout
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 16

                    Text {
                        text: "⚙️ Advanced System Configuration (Requires Restart)"
                        color: "#38BDF8"
                        font.pixelSize: 16
                        font.bold: true
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: 16
                        rowSpacing: 12

                        Text {
                            Layout.preferredWidth: 160
                            text: "Database Path:"
                            color: "#E2E8F0"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }
                        TextField {
                            Layout.fillWidth: true
                            text: backendBridge ? backendBridge.configDatabasePath : ""
                            placeholderText: "Absolute path to SQLite DB"
                            color: "#FFFFFF"
                            background: Rectangle { color: "#0B0F19"; radius: 6; border.color: "#334155"; border.width: 1 }
                            onEditingFinished: if (backendBridge) backendBridge.configDatabasePath = text
                        }

                        Text {
                            Layout.preferredWidth: 160
                            text: "Log Directory:"
                            color: "#E2E8F0"
                            font.bold: true
                            horizontalAlignment: Text.AlignRight
                        }
                        TextField {
                            Layout.fillWidth: true
                            text: backendBridge ? backendBridge.configLogDirectory : ""
                            placeholderText: "Directory for application logs"
                            color: "#FFFFFF"
                            background: Rectangle { color: "#0B0F19"; radius: 6; border.color: "#334155"; border.width: 1 }
                            onEditingFinished: if (backendBridge) backendBridge.configLogDirectory = text
                        }
                    }
                }
            }
        }
    }
}
