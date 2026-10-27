import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

// One bridge per shell. The bar instantiates the widget once per monitor, but
// the bridge's owner lock admits a single process, so every widget reads and
// writes through this service.
Item {
    id: root
    property var snapshot: ({state: "offline", store: {profiles: [], llm: {}}})
    readonly property string dictationState: snapshot.state || "offline"
    property bool bridgeConnected: false
    readonly property string ownerToken: Date.now().toString(36) + "-" + Math.random().toString(36).slice(2)
    Component.onDestruction: Quickshell.execDetached([root.python, "-B", root.script, "cleanup", root.ownerToken])
    property int serial: 0
    property bool busy: false
    property int pendingId: 0
    property string message: ""
    property bool failed: false
    readonly property bool completedFeedback: doneFeedback.running
    property var widgets: []
    property var openWidgets: []
    property var origins: ({})
    readonly property bool panelOpen: openWidgets.length > 0
    readonly property string python: Quickshell.env("HOME") + "/.local/share/omarchy-coe-enhance/venv/bin/python"
    readonly property string script: Qt.resolvedUrl("scripts/coe-bridge.py").toString().replace("file://", "")
    signal operationFinished(var data, var origin)

    function send(action, data, origin) {
        if (!bridgeConnected) { message = "桥接层尚未连接"; failed = true; return }
        var req = data || {}
        req.action = action
        req.request_id = ++serial
        if (action !== "get" && action !== "panel") { busy = true; pendingId = req.request_id; message = "正在执行…"; failed = false }
        if (origin) origins[req.request_id] = origin
        bridge.write(JSON.stringify(req) + "\n")
    }
    function receive(line) {
        try {
            var data = JSON.parse(line)
            if (data.type === "fatal") { message = data.error; failed = true; return }
            if (data.store) { var first = !bridgeConnected; snapshot = data; bridgeConnected = true; if (first) root.send("panel", {open:root.panelOpen}) }
            if (data.type === "response") {
                if (data.request_id === pendingId) busy = false
                failed = data.ok === false
                message = data.error || data.notice || "操作完成"
                var origin = origins[data.request_id] || null
                delete origins[data.request_id]
                if (data.action !== "get" && data.action !== "panel") root.operationFinished(data, origin)
            }
            if (data.state === "completed") doneFeedback.restart()
        } catch (e) { message = "桥接层响应无效"; failed = true }
    }
    // The bridge holds paste while any panel is open, on whichever monitor.
    function setPanelOpen(widget, open) {
        var next = openWidgets.filter(function(w) { return w !== widget })
        if (open) next.push(widget)
        var changed = (next.length > 0) !== panelOpen
        openWidgets = next
        if (changed && bridgeConnected) send("panel", {open: panelOpen})
    }
    function register(widget) {
        if (widgets.indexOf(widget) < 0) widgets = widgets.concat([widget])
    }
    function unregister(widget) {
        setPanelOpen(widget, false)
        widgets = widgets.filter(function(w) { return w !== widget })
    }
    // Panel IPC acts on the focused monitor's bar, like a click there would.
    function targetWidget() {
        var name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : ""
        for (var i = 0; i < widgets.length; i++)
            if (widgets[i].screenName === name) return widgets[i]
        return widgets.length ? widgets[0] : null
    }
    Process {
        id: bridge
        command: [root.python, "-B", root.script, "watch", root.ownerToken]
        stdinEnabled: true
        running: true
        stdout: SplitParser { onRead: function(data) { root.receive(data) } }
        onExited: {
            root.bridgeConnected = false
            root.busy = false
            root.origins = ({})
            root.snapshot = {state: "offline", store: root.snapshot.store}
            retry.restart()
        }
    }
    IpcHandler {
        target: "cc.coe-enhance"
        function status(): string {
            return JSON.stringify({connected:root.bridgeConnected,state:root.dictationState,opened:root.panelOpen,busy:root.busy,error:root.failed ? root.message : (root.snapshot.error || ""),notice:root.message})
        }
        function inspect(): string {
            var widget = root.targetWidget()
            return widget ? widget.inspect() : "{}"
        }
        function showPage(page: string, profileId: string): void {
            var widget = root.targetWidget()
            if (widget) widget.showPage(page, profileId)
        }
        function preview(width: int, height: int): void {
            var widget = root.targetWidget()
            if (widget) widget.preview(width, height)
        }
    }
    Timer { id: retry; interval: 3000; onTriggered: bridge.running = true }
    Timer { id: doneFeedback; interval: 1300 }
}
