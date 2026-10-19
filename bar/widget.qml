import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
    id: root
    moduleName: "cc.coe-enhance"
    property var snapshot: ({state: "offline", store: {profiles: [], llm: {}}})
    property string dictationState: snapshot.state || "offline"
    property bool bridgeConnected: false
    readonly property string ownerToken: Date.now().toString(36) + "-" + Math.random().toString(36).slice(2)
    Component.onDestruction: Quickshell.execDetached([root.python, "-B", root.script, "cleanup", root.ownerToken])
    property int serial: 0
    property bool busy: false
    property int pendingId: 0
    property string message: ""
    property bool failed: false
    readonly property bool opened: panelLoader.item ? panelLoader.item.opened : false
    readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing : false
    readonly property string python: Quickshell.env("HOME") + "/.local/share/omarchy-coe-enhance/venv/bin/python"
    readonly property string script: Qt.resolvedUrl("../scripts/coe-bridge.py").toString().replace("file://", "")
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function send(action, data) {
        if (!bridgeConnected) { message = "桥接层尚未连接"; failed = true; return }
        var req = data || {}
        req.action = action
        req.request_id = ++serial
        if (action !== "get" && action !== "panel") { busy = true; pendingId = req.request_id; message = "正在执行…"; failed = false }
        bridge.write(JSON.stringify(req) + "\n")
    }
    function receive(line) {
        try {
            var data = JSON.parse(line)
            if (data.type === "fatal") { message = data.error; failed = true; return }
            if (data.store) { var first = !bridgeConnected; snapshot = data; bridgeConnected = true; if (first) root.send("panel", {open:root.opened}) }
            if (data.type === "response") {
                if (data.request_id === pendingId) busy = false
                failed = data.ok === false
                message = data.error || data.notice || "操作完成"
                if (panelLoader.item && data.action !== "get" && data.action !== "panel") panelLoader.item.operationFinished(data)
            }
            if (data.state === "completed") doneFeedback.restart()
        } catch (e) { message = "桥接层响应无效"; failed = true }
    }
    function injectPanel() {
        if (!panelLoader.item) return
        panelLoader.item.bar = bar
        panelLoader.item.anchorItem = button
        panelLoader.item.hostWidget = root
    }
    function open() { if (panelLoader.item) panelLoader.item.open() }
    function close() { if (panelLoader.item) panelLoader.item.close() }
    function toggle() { opened ? close() : open() }
    function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }
    onBarChanged: injectPanel()
    Process {
        id: bridge
        command: [root.python, "-B", root.script, "watch", root.ownerToken]
        stdinEnabled: true
        running: true
        stdout: SplitParser { onRead: function(data) { root.receive(data) } }
        onExited: {
            root.bridgeConnected = false
            root.busy = false
            root.snapshot = {state: "offline", store: root.snapshot.store}
            retry.restart()
        }
    }
    IpcHandler {
        target: "cc.coe-enhance"
        function status(): string {
            return JSON.stringify({connected:root.bridgeConnected,state:root.dictationState,opened:root.opened,busy:root.busy,error:root.failed ? root.message : (root.snapshot.error || ""),notice:root.message})
        }
        function inspect(): string {
            return panelLoader.item ? panelLoader.item.inspect() : "{}"
        }
        function showPage(page: string, profileId: string): void {
            if (panelLoader.item) panelLoader.item.showPage(page, profileId)
        }
        function preview(width: int, height: int): void {
            if (panelLoader.item) { panelLoader.item.previewWidth = width; panelLoader.item.previewHeight = height }
        }
    }
    Timer { id: retry; interval: 3000; onTriggered: bridge.running = true }
    Timer { id: doneFeedback; interval: 1300 }
    Loader {
        id: panelLoader
        active: true
        source: Qt.resolvedUrl("../CoePanel.qml")
        visible: false
        onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
    }
    BarIconButton {
        id: button
        bar: root.bar
        foreground: root.dictationState === "error" ? Color.urgent
            : root.dictationState === "recording" ? Color.pick("coe.recording", "#e5c07b")
            : root.dictationState === "offline" ? Color.muted : Color.bar.text
        text: root.dictationState === "processing" ? "󰔟" : doneFeedback.running ? "󰄬" : root.dictationState === "offline" ? "󰍭" : "󰍬"
        tooltipText: "Coe 语音输入 · " + ({idle:"已就绪",recording:"正在录音",processing:"正在识别/纠错",completed:"已完成",error:"发生错误",offline:"服务未连接"}[root.dictationState] || root.dictationState)
        textRotation: root.dictationState === "processing" ? spinner.angle : 0
        onPressed: function(code) { if (code === Qt.LeftButton) root.toggle() }
        opacity: root.dictationState === "recording" ? pulse.value : 1
    }
    QtObject { id: pulse; property real value: 1 }
    SequentialAnimation {
        running: root.dictationState === "recording"
        loops: Animation.Infinite
        NumberAnimation { target: pulse; property: "value"; from: 1; to: 0.4; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { target: pulse; property: "value"; from: 0.4; to: 1; duration: 700; easing.type: Easing.InOutSine }
    }
    QtObject { id: spinner; property real angle: 0 }
    NumberAnimation { target: spinner; property: "angle"; from: 0; to: 360; duration: 1000; loops: Animation.Infinite; running: root.dictationState === "processing" }
}
