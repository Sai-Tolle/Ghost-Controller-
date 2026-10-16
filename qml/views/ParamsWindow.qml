import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import "../components"

// PARAMETERS — separate, movable window (drag it to a second monitor while
// flying). Read all from the vehicle, search / filter by group, stage edits,
// WRITE sends them and keeps only edits the vehicle did NOT confirm.
Window {
    id: win
    objectName: "paramsWindow"
    title: qsTr("Parameters")
    width: 1060
    height: 700
    minimumWidth: 820
    minimumHeight: 480
    color: Token.color_base_surface
    signal openConnection()

    readonly property var tm: Telemetry.telemetry
    readonly property bool linked: tm.connected
    readonly property bool armed: linked && tm.armed
    property string editing: ""          // name of the row whose editor is open
    property string editError: ""
    property string toast: ""
    property bool toastOk: true

    function say(text, ok) { toast = text; toastOk = ok !== false; toastTimer.restart() }
    Timer { id: toastTimer; interval: 5000; onTriggered: win.toast = "" }

    onVisibleChanged: if (visible && linked) Params.ensureLoaded()
    onLinkedChanged: if (visible && linked) Params.ensureLoaded()

    function beginEdit(name) { editing = name; editError = "" }
    function commitEdit(name, text) {
        var res = Params.stage(name, text)
        if (res.ok) { editing = ""; editError = "" } else editError = res.error
    }

    Shortcut { sequence: "Ctrl+F"; onActivated: search.forceActiveFocus() }
    Shortcut { sequence: "Escape"; onActivated: if (win.editing !== "") win.editing = ""; else win.close() }

    // ---- header -----------------------------------------------------------------------------------
    Rectangle {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 56
        color: Token.color_hud_topbarBg
        Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: Token.color_ui_line }

        Row {
            anchors.left: parent.left; anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 16
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Parameters"
                font.pixelSize: 13
                font.weight: Font.DemiBold; color: Token.color_ui_text
            }
            Rectangle { width: 1; height: 22; color: Token.color_ui_line; anchors.verticalCenter: parent.verticalCenter }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: !win.linked ? "No Vehicle"
                          : (Vehicle.firmware !== "" ? Vehicle.firmware : "Vehicle") + (win.armed ? " · Armed" : " · Disarmed")
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    color: !win.linked ? Token.color_text_muted : win.armed ? Token.color_status_warn : Token.color_status_ok
                }
                Text {
                    objectName: "paramsStatus"
                    text: Params.state === "loading" ? (Params.total > 0 ? "Loading " + Params.received + " / " + Params.total : "Requesting parameter list…")
                        : Params.count > 0 ? Params.count + " parameters" + (Params.state === "partial" ? " · incomplete" : "")
                        : Params.state === "error" ? Params.message : "Not loaded"
                    font.pixelSize: 13; font.weight: Font.DemiBold
                    color: Params.state === "error" || Params.state === "partial" ? Token.color_status_warn : Token.color_ui_text
                }
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            TextButton {
                objectName: "paramsRefreshBtn"
                label: Params.state === "loading" ? "Loading…" : "Refresh"
                enabled: win.linked && Params.available && Params.state !== "loading" && !Params.writing
                onClicked: {
                    if (Params.pendingCount > 0) win.say("Refreshing keeps your " + Params.pendingCount + " staged edit(s)", true)
                    Params.refresh()
                }
            }
            TextButton { label: "Load File…"; enabled: Params.count > 0 && !Params.writing; onClicked: importDialog.open() }
            TextButton { label: "Save File…"; enabled: Params.count > 0; onClicked: exportDialog.open() }
        }
        Rectangle {                                       // load progress
            anchors { left: parent.left; bottom: parent.bottom }
            height: 2
            visible: Params.state === "loading" && Params.total > 0
            width: parent.width * (Params.total > 0 ? Params.received / Params.total : 0)
            color: Token.color_accent_primary
            Behavior on width { NumberAnimation { duration: 150 } }
        }
    }

    // ---- empty states -------------------------------------------------------------------------------
    Column {
        anchors.centerIn: parent
        spacing: 12
        visible: Params.count === 0
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: !Params.available ? "No MAVLink backend"
                : !win.linked ? "No vehicle link"
                : Params.state === "loading" ? "Loading parameters" : "No parameters loaded"
            font.pixelSize: 18
            font.weight: Font.DemiBold
            color: !win.linked ? Token.color_status_danger : Token.color_ui_text
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: !Params.available ? "Running in simulation — parameters need a real backend link."
                : !win.linked ? "Connect a vehicle to read and write its parameters."
                : Params.state === "loading" ? "This takes a few seconds over USB / UDP, longer over a telemetry radio."
                : Params.state === "error" ? Params.message : "Press REFRESH to read them from the vehicle."
            font.pixelSize: 12; color: Token.color_ui_textDim
        }
        TextButton {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !win.linked && Params.available
            label: "Connection…"
            onClicked: win.openConnection()
        }
    }

    // ---- groups sidebar --------------------------------------------------------------------------------
    Rectangle {
        id: sidebar
        visible: Params.count > 0
        anchors { left: parent.left; top: header.bottom; bottom: footer.top }
        width: 180
        color: Qt.alpha(Token.color_ui_text, 0.03)
        Rectangle { anchors { right: parent.right; top: parent.top; bottom: parent.bottom } width: 1; color: Token.color_ui_line }
        ListView {
            id: groupList
            anchors.fill: parent
            anchors.margins: 8
            anchors.rightMargin: 9
            clip: true
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            header: Item {
                width: groupList.width; height: 32
                Rectangle {
                    anchors.fill: parent; anchors.bottomMargin: 2; radius: 6
                    color: Params.group === "" ? Token.color_ui_accentSoft : (allHover.hovered ? Token.color_ui_fill : "transparent")
                    Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter
                           text: "All"; font.pixelSize: 12; font.weight: Font.DemiBold
                           color: Token.color_ui_text }
                    Text { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                           text: Params.count; font.pixelSize: 11; color: Token.color_ui_textDim }
                    HoverHandler { id: allHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: if (Params.group !== "") Params.setGroup(Params.group) }
                }
            }
            model: Params.groups
            delegate: Rectangle {
                required property var modelData
                readonly property bool on: Params.group === modelData.name
                width: groupList.width; height: 26; radius: 6
                color: on ? Token.color_ui_accentSoft : (gHover.hovered ? Token.color_ui_fill : "transparent")
                Text { anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter
                       text: modelData.name; font.pixelSize: 12
                       color: Token.color_ui_text; font.weight: on ? Font.DemiBold : Font.Normal }
                Text { anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                       text: modelData.count; font.pixelSize: 11; color: Token.color_ui_textDim }
                HoverHandler { id: gHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: Params.setGroup(modelData.name) }
            }
        }
    }

    // ---- table --------------------------------------------------------------------------------------
    Item {
        id: main
        visible: Params.count > 0
        anchors { left: sidebar.right; right: parent.right; top: header.bottom; bottom: footer.top }

        Row {
            id: toolbar
            anchors { left: parent.left; top: parent.top; leftMargin: 14; topMargin: 12 }
            spacing: 10
            TextField {
                id: search
                objectName: "paramSearch"
                width: 300; height: 32
                placeholderText: "Search parameters   (Ctrl+F)"
                placeholderTextColor: Token.color_text_disabled
                color: Token.color_ui_text
                font.pixelSize: 13
                leftPadding: 10
                selectByMouse: true
                onTextChanged: searchDebounce.restart()
                background: Rectangle { radius: 8; color: Token.color_ui_fill; border.width: search.activeFocus ? 2 : 0
                                        border.color: Qt.alpha(Token.color_accent_primary, 0.8) }
                Timer { id: searchDebounce; interval: 120; onTriggered: Params.setFilter(search.text) }
            }
            TextButton {
                anchors.verticalCenter: parent.verticalCenter
                label: "Modified Only" + (Params.pendingCount > 0 ? " · " + Params.pendingCount : "")
                tone: Params.modifiedOnly ? "primary" : "neutral"
                onClicked: Params.setModifiedOnly(!Params.modifiedOnly)
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: Params.shown + " shown"
                font.pixelSize: 11; color: Token.color_ui_textDim
            }
        }

        // column header
        Row {
            id: colHead
            anchors { left: parent.left; right: parent.right; top: toolbar.bottom; leftMargin: 14; rightMargin: 14; topMargin: 12 }
            height: 22
            readonly property real wName: 230
            readonly property real wValue: 150
            readonly property real wNew: 200
            readonly property real wType: 80
            Repeater {
                model: [{ t: "Name", w: colHead.wName }, { t: "Value", w: colHead.wValue },
                        { t: "New Value", w: colHead.wNew }, { t: "Type", w: colHead.wType }, { t: "Status", w: 200 }]
                delegate: Text {
                    required property var modelData
                    width: modelData.w; text: modelData.t
                    font.pixelSize: 11
                    font.weight: Font.DemiBold; color: Token.color_ui_textDim
                }
            }
        }
        Rectangle { anchors { left: parent.left; right: parent.right; top: colHead.bottom } height: 1; color: Token.color_ui_line }

        ListView {
            id: table
            objectName: "paramTable"
            anchors { left: parent.left; right: parent.right; top: colHead.bottom; bottom: parent.bottom; topMargin: 1 }
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: Params.model
            reuseItems: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: Rectangle {
                id: rowItem
                required property int index
                required property string name
                required property string value
                required property string ptype
                required property string pending
                required property bool modified
                required property string error
                readonly property bool isEditing: win.editing === name
                width: table.width; height: 34
                color: error !== "" ? Qt.alpha(Token.color_status_danger, 0.07)
                     : modified ? Qt.alpha(Token.color_status_warn, 0.07)
                     : rowHover.hovered ? Qt.alpha(Token.color_ui_text, 0.04)
                     : index % 2 ? Qt.alpha(Token.color_ui_text, 0.015) : "transparent"
                HoverHandler { id: rowHover }
                Rectangle { anchors { left: parent.left; top: parent.top; bottom: parent.bottom } width: 2
                            visible: rowItem.modified; color: rowItem.error !== "" ? Token.color_status_danger : Token.color_status_warn }
                Row {
                    anchors.left: parent.left; anchors.leftMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        width: colHead.wName; elide: Text.ElideRight
                        anchors.verticalCenter: parent.verticalCenter
                        text: rowItem.name
                        font.pixelSize: 13; font.weight: Font.DemiBold
                        color: Token.color_ui_text
                    }
                    Item {                                      // current value — click to edit
                        width: colHead.wValue; height: 26
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: rowItem.value
                            font.pixelSize: 13
                            color: rowItem.modified ? Token.color_ui_textDim : Token.color_ui_text
                            font.strikeout: rowItem.modified
                        }
                        HoverHandler { cursorShape: Qt.IBeamCursor }
                        TapHandler { onTapped: win.beginEdit(rowItem.name) }
                    }
                    Item {                                      // staged value / editor
                        width: colHead.wNew; height: 26
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            visible: !rowItem.isEditing
                            anchors.verticalCenter: parent.verticalCenter
                            text: rowItem.modified ? rowItem.pending : "—"
                            font.pixelSize: 13
                            font.weight: rowItem.modified ? Font.Bold : Font.Normal
                            color: rowItem.modified ? Token.color_status_warn : Token.color_text_disabled
                        }
                        HoverHandler { enabled: !rowItem.isEditing; cursorShape: Qt.IBeamCursor }
                        TapHandler { enabled: !rowItem.isEditing; onTapped: win.beginEdit(rowItem.name) }
                        TextField {
                            id: editor
                            visible: rowItem.isEditing
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 16; height: 28
                            color: Token.color_ui_text
                            font.pixelSize: 13
                            leftPadding: 8
                            selectByMouse: true
                            onVisibleChanged: if (visible) { text = rowItem.modified ? rowItem.pending : rowItem.value; forceActiveFocus(); selectAll() }
                            onAccepted: win.commitEdit(rowItem.name, text)
                            Keys.onEscapePressed: win.editing = ""
                            Keys.onTabPressed: { win.commitEdit(rowItem.name, text) }
                            onActiveFocusChanged: if (!activeFocus && rowItem.isEditing && win.editError === "") win.editing = ""
                            background: Rectangle { radius: 5; color: Token.color_ui_fill; border.width: 1
                                                    border.color: win.editError !== "" ? Token.color_status_danger : Token.color_accent_primary }
                        }
                    }
                    Text {
                        width: colHead.wType
                        anchors.verticalCenter: parent.verticalCenter
                        text: rowItem.ptype
                        font.pixelSize: 11; color: Token.color_ui_textDim
                    }
                    Text {
                        width: Math.max(80, table.width - colHead.wName - colHead.wValue - colHead.wNew - colHead.wType - 70)
                        anchors.verticalCenter: parent.verticalCenter
                        elide: Text.ElideRight
                        text: rowItem.isEditing && win.editError !== "" ? "⚠ " + win.editError
                            : rowItem.isEditing ? "Enter to stage · Esc to cancel"
                            : rowItem.error !== "" ? "⚠ " + rowItem.error
                            : rowItem.modified ? "staged — not written yet" : ""
                        font.pixelSize: 11
                        color: (rowItem.isEditing && win.editError !== "") || rowItem.error !== "" ? Token.color_status_danger
                             : rowItem.isEditing ? Token.color_ui_textDim : Token.color_status_warn
                    }
                }
                Text {                                          // revert ×
                    visible: rowItem.modified && !Params.writing
                    anchors.right: parent.right; anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: "↺"
                    font.pixelSize: 14; color: undoHover.hovered ? Token.color_ui_text : Token.color_ui_textDim
                    HoverHandler { id: undoHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: Params.unstage(rowItem.name) }
                    ToolTip.visible: undoHover.hovered
                    ToolTip.text: "Discard this edit"
                }
            }
        }
    }

    // ---- footer: staged edits + write ----------------------------------------------------------------------------
    Rectangle {
        id: footer
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 54
        color: Token.color_hud_topbarBg
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: 1; color: Token.color_ui_line }

        Column {
            anchors.left: parent.left; anchors.leftMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                text: Params.writing ? "Writing " + Params.writeDone + " / " + Params.writeTotal
                    : Params.pendingCount > 0 ? Params.pendingCount + " staged edit" + (Params.pendingCount > 1 ? "s" : "")
                    : "No pending changes"
                font.pixelSize: 12; font.weight: Font.DemiBold
                color: Params.pendingCount > 0 || Params.writing ? Token.color_status_warn : Token.color_ui_textDim
            }
            Text {
                text: win.toast !== "" ? win.toast
                    : win.armed && Params.pendingCount > 0 ? "Vehicle is armed — writing is blocked until it is disarmed"
                    : Params.errorCount > 0 ? Params.errorCount + " edit(s) were not accepted — see Status"
                    : ""
                visible: text !== ""
                font.pixelSize: 11
                color: win.toast !== "" ? (win.toastOk ? Token.color_status_ok : Token.color_status_danger)
                     : win.armed && Params.pendingCount > 0 || Params.errorCount > 0 ? Token.color_status_danger
                     : Token.color_ui_textDim
            }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            TextButton { label: "Discard All"; enabled: Params.pendingCount > 0 && !Params.writing; onClicked: Params.discardAll() }
            TextButton {
                objectName: "paramsWriteBtn"
                label: Params.writing ? "Writing…" : "Write " + (Params.pendingCount > 0 ? Params.pendingCount + " " : "") + "To Vehicle"
                tone: "primary"
                width: 190
                enabled: Params.pendingCount > 0 && !Params.writing && win.linked && !win.armed
                onClicked: Params.writeAll()
            }
            TextButton { label: "Close"; onClicked: win.close() }
        }
    }

    Connections {
        target: Params
        function onWriteChanged() {
            if (!Params.writing && Params.writeTotal > 0)
                win.say(Params.writeOk + " of " + Params.writeTotal + " written and confirmed by the vehicle",
                        Params.writeOk === Params.writeTotal)
        }
    }

    // ---- files ------------------------------------------------------------------------------------------------------
    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        defaultSuffix: "params"
        nameFilters: ["Parameter file (*.params *.param *.txt)"]
        onAccepted: {
            var r = Params.exportTo(selectedFile.toString())
            win.say(r.ok ? "Saved " + r.count + " parameters" : "⚠ " + r.error, r.ok)
        }
    }
    FileDialog {
        id: importDialog
        nameFilters: ["Parameter files (*.params *.param *.parm *.txt)", "All files (*)"]
        onAccepted: {
            var r = Params.importFrom(selectedFile.toString())
            if (!r.ok) { win.say("⚠ " + r.error, false); return }
            win.say(r.staged + " staged · " + r.unchanged + " already equal"
                    + (r.unknown ? " · " + r.unknown + " not on this vehicle" : "")
                    + (r.invalid ? " · " + r.invalid + " invalid" : "") + " — review, then Write", r.staged > 0)
            if (r.staged > 0) Params.setModifiedOnly(true)
        }
    }
}
