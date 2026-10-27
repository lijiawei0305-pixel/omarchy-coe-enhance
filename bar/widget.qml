import QtQuick
import Quickshell
import qs.Commons as Commons
import qs.Ui

// One instance per monitor bar. State and the bridge live in Service.qml so
// every monitor shows the same connection.
BarWidget {
    id: root
    moduleName: "cc.coe-enhance"
    readonly property var service: bar?.shell?.serviceFor(root.moduleName) ?? null
    readonly property var snapshot: service ? service.snapshot : ({state: "offline", store: {profiles: [], llm: {}}})
    readonly property string dictationState: snapshot.state || "offline"
    readonly property bool bridgeConnected: service ? service.bridgeConnected : false
    readonly property bool busy: service ? service.busy : false
    readonly property bool opened: panelLoader.item ? panelLoader.item.opened : false
    readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing : false
    readonly property string screenName: root.QsWindow.window && root.QsWindow.window.screen ? root.QsWindow.window.screen.name : ""
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight

    function send(action, data) {
        if (!service) return
        if (action === "panel") service.setPanelOpen(root, !!(data && data.open))
        else service.send(action, data, root)
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
    function inspect() { return panelLoader.item ? panelLoader.item.inspect() : "{}" }
    function showPage(page, profileId) { if (panelLoader.item) panelLoader.item.showPage(page, profileId) }
    function preview(width, height) {
        if (panelLoader.item) { panelLoader.item.previewWidth = width; panelLoader.item.previewHeight = height }
    }
    onBarChanged: injectPanel()
    onServiceChanged: if (service) service.register(root)
    Component.onCompleted: if (service) service.register(root)
    Component.onDestruction: if (service) service.unregister(root)
    Connections {
        target: root.service
        function onOperationFinished(data, origin) {
            if (origin === root && panelLoader.item) panelLoader.item.operationFinished(data)
        }
    }
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
        foreground: root.dictationState === "error" ? Commons.Color.urgent
            : root.dictationState === "recording" ? Commons.Color.pick("coe.recording", "#e5c07b")
            : root.dictationState === "offline" ? Commons.Color.muted : Commons.Color.bar.text
        text: root.dictationState === "processing" ? "󰔟" : root.service && root.service.completedFeedback ? "󰄬" : root.dictationState === "offline" ? "󰍭" : "󰍬"
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
