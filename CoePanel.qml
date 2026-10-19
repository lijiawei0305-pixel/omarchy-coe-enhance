pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import QtQuick.Controls as QQC
import qs.Commons
import qs.Ui

Panel {
    id: root
    moduleName: "cc.coe-enhance"
    manageIpc: false
    property var anchorItem: null
    property var hostWidget: null
    readonly property var store: hostWidget ? hostWidget.snapshot.store : ({
            profiles: [],
            llm: {}
        })
    readonly property string dictationState: hostWidget ? hostWidget.dictationState : "offline"
    readonly property bool working: hostWidget ? hostWidget.busy : false
    readonly property bool inFlight: dictationState === "recording" || dictationState === "processing"
    readonly property color ink: Color.popups.text
    readonly property color muted: Util.alpha(ink, 0.68)
    readonly property real gap: Style.spacing.md
    property string page: "home"
    property var asrDraft: ({})
    property var llmDraft: ({})
    property string draftBaseline: ""
    property string editingId: ""
    property string providerChoice: "openai"
    property string asrSecret: ""
    property string llmSecret: ""
    property bool removeAsrKey: false
    property bool removeLlmKey: false
    property bool editAsrKey: false
    property bool editLlmKey: false
    property bool advanced: false
    property bool promptExpanded: false
    property bool showLlmConnection: false
    property string expandedProfile: ""
    property string confirm: ""
    property string pendingPage: ""
    property string pendingDelete: ""
    property string feedback: ""
    property bool feedbackError: false
    property string languageDraft: ""
    property string languageProfileId: ""
    // Test viewport caps exercise layout in this existing Shell, never another instance.
    property int previewWidth: 0
    property int previewHeight: 0
    readonly property bool editor: page === "asr" || page === "llm"
    readonly property bool dirty: editor && (JSON.stringify(page === "asr" ? asrDraft : llmDraft) !== draftBaseline || (page === "asr" && (asrSecret !== "" || removeAsrKey)) || (page === "llm" && (llmSecret !== "" || removeLlmKey)))
    readonly property var activeProfile: profile(store.active)
    readonly property var activeLanguageCapability: languageCapability(activeProfile)
    readonly property var draftLanguageCapability: languageCapability(asrDraft)
    readonly property var languageOptions: languageChoices(activeProfile, languageDraft)
    readonly property var providerOptions: [
        {
            value: "openai",
            label: "OpenAI 音频转写"
        },
        {
            value: "compatible",
            label: "自定义兼容接口"
        },
        {
            value: "aliyun",
            label: "阿里云百炼"
        },
        {
            value: "doubao",
            label: "豆包语音识别"
        },
        {
            value: "sensevoice",
            label: "SenseVoice HTTP"
        },
        {
            value: "qwen",
            label: "Qwen3-ASR / vLLM"
        }
    ]
    readonly property string stateLabel: ({
            idle: "已就绪",
            recording: "录音中",
            processing: "正在识别",
            completed: "已完成",
            error: "出错",
            offline: "服务未启动"
        }[dictationState] || "连接中")
    readonly property string shortcutLabel: (store.hotkey === "Alt_R" ? "右 Alt" : (store.hotkey || "未设置")) + (store.hotkey_mode === "hold" ? " · 按住说话" : " · 点击切换")
    readonly property string title: ({
            home: "Coe 语音输入",
            settings: "管理与设置",
            profiles: "模型与服务",
            asr: editingId ? "编辑语音识别服务" : "添加语音识别服务",
            llm: "AI 文本纠错",
            diagnostics: "服务与诊断",
            language: "识别语言"
        }[page] || "Coe 语音输入")

    function copy(o) {
        return JSON.parse(JSON.stringify(o || {}));
    }
    function profile(id) {
        var ps = store.profiles || [];
        for (var i = 0; i < ps.length; i++)
            if (ps[i].id === id)
                return ps[i];
        return ({});
    }
    function languageCapability(p) {
        var catalog = store.language_catalog || {};
        var rules = catalog.rules || [];
        for (var i = 0; i < rules.length; i++) {
            var rule = rules[i];
            if (p.provider !== rule.provider || p.protocol !== rule.protocol)
                continue;
            if (rule.models && rule.models.indexOf(p.model) < 0)
                continue;
            if (rule.endpoint_pattern && !(new RegExp(rule.endpoint_pattern)).test(p.endpoint || ""))
                continue;
            return rule;
        }
        return catalog.fallback || {mode: "none", max_hints: 0, codes: [], verified: false};
    }
    function languageSupported(p) {
        return languageCapability(p).mode !== "none";
    }
    function normalizedLanguage(value) {
        return !value || value === "auto" ? "" : value;
    }
    function languageChoices(p, saved) {
        var cap = languageCapability(p);
        var labels = (store.language_catalog || {}).labels || {};
        var choices = [{value: "", label: "自动识别"}];
        cap.codes.forEach(function(code) {
            choices.push({value: code, label: labels[code] || code});
        });
        saved = normalizedLanguage(saved);
        if (saved && cap.codes.indexOf(saved) < 0)
            choices.push({value: saved, label: "已保存的高级语言设置"});
        return choices;
    }
    function languageSelectable(value) {
        return languageSupported(activeProfile) && (value === "" || activeLanguageCapability.codes.indexOf(value) >= 0);
    }
    function selectLanguage(value) {
        if (!languageSelectable(value))
            return;
        send("preferences", {language: value, language_profile_id: activeProfile.id});
    }
    function syncLanguageDraft() {
        languageProfileId = activeProfile.id || "";
        languageDraft = normalizedLanguage(activeProfile.language);
    }
    onActiveProfileChanged: if (page === "language" && languageProfileId !== (activeProfile.id || ""))
        syncLanguageDraft()
    function shortName(p) {
        var known = {
            "qwen-audio-3.0-asr-flash": "阿里云 · Qwen Audio Flash",
            "fun-asr-flash-2026-06-15": "阿里云 · Fun-ASR Flash",
            "gpt-4o-mini-transcribe": "OpenAI · GPT-4o Mini",
            "gpt-4o-transcribe": "OpenAI · GPT-4o Transcribe",
            "whisper-1": "OpenAI · Whisper"
        };
        if (known[p.model] && (p.provider === "aliyun-asr" || (p.provider === "openai" && String(p.endpoint).indexOf("api.openai.com") >= 0)))
            return known[p.model];
        if (p.provider === "doubao" && (!p.name || p.name === "豆包 Flash"))
            return "豆包 · 语音识别";
        return p.name || p.model || "尚未配置语音服务";
    }
    function options() {
        return (store.profiles || []).map(function (p) {
            return {
                value: p.id,
                label: root.shortName(p)
            };
        });
    }
    function notify(message, failed) {
        feedback = message;
        feedbackError = !!failed;
        feedbackTimer.restart();
    }
    function send(action, data) {
        feedback = "";
        hostWidget.send(action, data || {});
    }
    function resetSecrets() {
        asrSecret = "";
        llmSecret = "";
        removeAsrKey = false;
        removeLlmKey = false;
        editAsrKey = false;
        editLlmKey = false;
    }
    function open() {
        root.controller.show();
        page = "home";
        confirm = "";
        feedback = "";
        resetSecrets();
        hostWidget.send("get");
    }
    function reallyClose() {
        root.controller.hide();
        resetSecrets();
        confirm = "";
        page = "home";
        previewWidth = 0;
        previewHeight = 0;
    }
    function close() {
        if (dirty) {
            pendingPage = "__close__";
            confirm = "discard";
        } else
            reallyClose();
    }
    function toggle() {
        opened ? close() : open();
    }
    onOpenedChanged: if (hostWidget)
        hostWidget.send("panel", {
            open: opened
        })
    function navigate(next) {
        if (dirty && next !== page) {
            pendingPage = next;
            confirm = "discard";
            return;
        }
        enter(next);
    }
    function enter(next) {
        confirm = "";
        advanced = false;
        promptExpanded = false;
        showLlmConnection = false;
        if (next === "llm") {
            resetSecrets();
            llmDraft = copy(store.llm);
            draftBaseline = JSON.stringify(llmDraft);
        }
        if (next === "language")
            syncLanguageDraft();
        page = next;
        Qt.callLater(function () {
            scroller.contentY = 0;
            keyCatcher.forceActiveFocus();
        });
    }
    function back() {
        if (confirm !== "") {
            confirm = "";
            return;
        }
        navigate(page === "home" ? "__close__" : page === "asr" ? "profiles" : page === "settings" || page === "language" ? "home" : "settings");
        if (page === "__close__")
            reallyClose();
    }
    function discard() {
        draftBaseline = "";
        resetSecrets();
        var next = pendingPage;
        confirm = "";
        if (next === "__close__")
            reallyClose();
        else
            enter(next);
    }
    function editProfile(id) {
        resetSecrets();
        editingId = id || "";
        asrDraft = copy(id ? profile(id) : (store.presets || {}).openai);
        if (!id)
            asrDraft.timeout = 60;
        providerChoice = ({
                "aliyun-asr": "aliyun",
                "qwen3-asr-vllm": "qwen"
            }[asrDraft.provider] || asrDraft.provider || "openai");
        if (providerChoice === "openai" && String(asrDraft.endpoint).indexOf("api.openai.com") < 0)
            providerChoice = "compatible";
        draftBaseline = JSON.stringify(asrDraft);
        enter("asr");
    }
    function updateAsr(key, value) {
        if (asrDraft[key] !== value) {
            var p = copy(asrDraft);
            p[key] = value;
            asrDraft = p;
        }
    }
    function updateLlm(key, value) {
        if (llmDraft[key] !== value) {
            var p = copy(llmDraft);
            p[key] = value;
            llmDraft = p;
        }
    }
    function chooseProvider(value) {
        providerChoice = value;
        var p = copy(store.presets[value]);
        p.timeout = asrDraft.timeout || 60;
        p.name = asrDraft.name || p.name;
        asrDraft = p;
    }
    function asrPayload() {
        return {
            id: editingId,
            profile: copy(asrDraft),
            api_key: asrSecret,
            delete_api_key: removeAsrKey
        };
    }
    function save() {
        if (page === "asr")
            send("save", asrPayload());
        else if (page === "llm")
            send("save_llm", {
                llm: copy(llmDraft),
                llm_key: llmSecret,
                delete_llm_key: removeLlmKey
            });
    }
    function operationFinished(data) {
        if (!data.ok) {
            notify(data.error || "保存失败，请检查设置", true);
            return;
        }
        if (data.action === "save" && page === "asr") {
            editingId = store.active;
            asrDraft = copy(profile(editingId));
            draftBaseline = JSON.stringify(asrDraft);
            resetSecrets();
        }
        if (data.action === "save_llm" && page === "llm") {
            llmDraft = copy(store.llm);
            draftBaseline = JSON.stringify(llmDraft);
            resetSecrets();
        }
        if (data.action === "preferences" && page === "language")
            syncLanguageDraft();
        if (data.action === "duplicate")
            expandedProfile = "";
        notify(data.notice || ({
                save: "服务已保存并应用",
                save_llm: "纠错设置已应用",
                default: "默认模型已更新",
                duplicate: "已复制配置",
                delete: "配置已删除",
                activate: "当前模型已切换",
                preferences: "设置已应用"
            }[data.action] || "操作完成"), false);
    }
    function inspect() {
        return JSON.stringify({
            page: page,
            dirty: dirty,
            confirmation: confirm,
            feedbackError: feedbackError,
            keyboardActive: keyCatcher.Window.window ? keyCatcher.Window.window.active : false,
            x: panel.cardOrigin.x,
            y: panel.cardOrigin.y,
            width: panel.contentWidth,
            height: panel.contentHeight,
            viewportHeight: scroller.height,
            bodyHeight: pageLoader.implicitHeight,
            scrollable: scroller.contentHeight > scroller.height + 1,
            state: dictationState,
            hotkey: store.hotkey,
            mode: store.hotkey_mode,
            languageMode: activeLanguageCapability.mode,
            languageCodes: activeLanguageCapability.codes,
            languageMaxHints: activeLanguageCapability.max_hints,
            languageSelection: normalizedLanguage(activeProfile.language),
            languageDraft: languageDraft,
            draftLanguageMode: draftLanguageCapability.mode,
            draftLanguageMaxHints: draftLanguageCapability.max_hints,
            draftLanguageCodes: draftLanguageCapability.codes,
            draftLanguageVerified: draftLanguageCapability.verified,
            controls: controlMetadata(keyCatcher),
            profileCount: (store.profiles || []).length,
            focus: focusName(keyCatcher)
        });
    }
    function controlMetadata(item) {
        var result = [];
        if (!item.visible)
            return result;
        if (item.objectName)
            result.push({name: item.objectName, enabled: item.enabled, editable: typeof item.readOnly === "boolean" && !item.readOnly});
        for (var i = 0; item.children && i < item.children.length; i++)
            result = result.concat(controlMetadata(item.children[i]));
        return result;
    }
    function focusName(item) {
        if (item.activeFocus) {
            var control = item;
            while (control && control !== keyCatcher) {
                if (control.objectName)
                    return control.objectName;
                if (typeof control.label === "string" && control.label)
                    return control.label;
                control = control.parent;
            }
        }
        for (var i = 0; item.children && i < item.children.length; i++) {
            var found = focusName(item.children[i]);
            if (found)
                return found;
        }
        return "";
    }
    function reveal(item) {
        var ancestor = item.parent;
        while (ancestor && ancestor !== pageLoader)
            ancestor = ancestor.parent;
        if (!ancestor)
            return;
        var top = item.mapToItem(pageLoader, 0, 0).y;
        if (top < scroller.contentY)
            scroller.contentY = top;
        else if (top + item.height > scroller.contentY + scroller.height)
            scroller.contentY = Math.min(scroller.contentHeight - scroller.height, top + item.height - scroller.height);
    }
    function showPage(next, id) {
        // Old input-page links now lead to read-only usage information.
        if (next === "input")
            next = "diagnostics";
        if (["home", "settings", "profiles", "asr", "llm", "diagnostics", "language"].indexOf(next) < 0)
            return;
        if (!opened)
            open();
        if (next === "asr")
            editProfile(id || store.active);
        else
            navigate(next);
    }
    Timer {
        id: feedbackTimer
        interval: 6000
        onTriggered: root.feedback = ""
    }
    Timer {
        id: recordDelay
        interval: 250
        onTriggered: root.hostWidget.send("toggle")
    }

    component Caption: Text {
        width: parent.width
        color: root.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    component Switch: ToggleSwitch {
        objectName: "AI 文本纠错开关"
        Accessible.role: Accessible.CheckBox
        Accessible.name: objectName
        activeFocusOnTab: true
        hasCursor: activeFocus
        opacity: enabled ? 1 : 0.45
        Keys.onSpacePressed: toggled()
        Keys.onReturnPressed: toggled()
        onActiveFocusChanged: if (activeFocus)
            root.reveal(this)
    }
    component Heading: Text {
        width: parent.width
        color: root.ink
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        font.bold: true
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
    }
    component Action: Button {
        objectName: text || tooltipText
        Accessible.role: Accessible.Button
        Accessible.name: text || tooltipText
        foreground: root.ink
        focusable: true
        opacity: enabled ? 1 : 0.42
        onActiveFocusChanged: if (activeFocus)
            root.reveal(this)
    }
    component Field: Column {
        property string label: ""
        property string value: ""
        property string placeholder: ""
        property bool secret: false
        property int limit: 4096
        property var inputValidator: null
        signal edited(string value)
        width: parent.width
        spacing: Style.spacing.labelGap
        Caption {
            text: parent.label
        }
        TextField {
            id: fieldInput
            objectName: parent.label
            Accessible.name: parent.label
            width: parent.width
            text: parent.value
            placeholderText: parent.placeholder
            password: parent.secret
            maximumLength: parent.limit
            validator: parent.inputValidator
            foreground: root.ink
            selectByMouse: true
            onTextEdited: parent.edited(text)
            Component.onCompleted: cursorPosition = 0
            onActiveFocusChanged: {
                if (activeFocus)
                    root.reveal(this);
                else
                    cursorPosition = 0;
            }
            QQC.ToolTip.visible: hovered && !password && text.length > 42
            QQC.ToolTip.text: text
            QQC.ToolTip.delay: 700
        }
    }
    component Divider: Rectangle {
        width: parent.width
        height: 1
        color: Util.alpha(root.ink, 0.11)
    }
    component NavRow: Item {
        property string label: ""
        property string description: ""
        signal activated
        width: parent.width
        implicitHeight: 64
        Action {
            anchors.fill: parent
            onClicked: parent.activated()
            tooltipText: parent.description
        }
        Column {
            anchors.left: parent.left
            anchors.leftMargin: Style.spacing.controlPaddingX
            anchors.right: arrow.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Heading {
                text: parent.parent.label
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
            }
            Caption {
                text: parent.parent.description
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
            }
        }
        Text {
            id: arrow
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: "›"
            color: root.muted
            font.pixelSize: Style.font.title
        }
    }
    KeyboardPanel {
        id: panel
        anchorItem: root.anchorItem
        owner: root.hostWidget || root
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        contentWidth: panel.fittedContentWidth(root.previewWidth > 0 ? root.previewWidth : 420)
        contentHeight: panel.fittedContentHeight(layout.naturalHeight, root.previewHeight > 0 ? root.previewHeight : (root.page === "home" ? 610 : 740))
        PanelKeyCatcher {
            id: keyCatcher
            anchors.fill: parent
            blocked: true
            Keys.onEscapePressed: root.back()
            Column {
                id: layout
                anchors.fill: parent
                spacing: root.gap
                readonly property real naturalHeight: header.implicitHeight + headerLine.height + pageLoader.implicitHeight + footer.implicitHeight + spacing * 3
                Row {
                    id: header
                    width: parent.width
                    spacing: 8
                    height: implicitHeight
                    Action {
                        visible: root.page !== "home"
                        iconText: "󰁍"
                        tooltipText: "返回"
                        onClicked: root.back()
                    }
                    Text {
                        width: parent.width - (root.page !== "home" ? 42 : stateBadge.width + settingsButton.width + 16)
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.title
                        color: root.ink
                        font.family: Style.font.family
                        font.pixelSize: Style.font.title
                        font.bold: true
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }
                    Row {
                        id: stateBadge
                        visible: root.page === "home"
                        spacing: 6
                        anchors.verticalCenter: parent.verticalCenter
                        Rectangle {
                            width: 6
                            height: 6
                            radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.dictationState === "error" ? Color.urgent : root.dictationState === "offline" ? root.muted : Color.accent
                        }
                        Text {
                            text: root.stateLabel
                            color: root.dictationState === "error" ? Color.urgent : root.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }
                    }
                    Action {
                        id: settingsButton
                        visible: root.page === "home"
                        iconText: "󰒓"
                        tooltipText: "管理与设置"
                        onClicked: root.navigate("settings")
                    }
                }
                Divider {
                    id: headerLine
                }
                Column {
                    width: parent.width
                    visible: root.confirm !== ""
                    spacing: 8
                    height: visible ? implicitHeight : 0
                    Heading {
                        text: ({
                                discard: "放弃未保存的更改？",
                                delete: "确定删除这项配置？",
                                asrKey: "移除此服务的密钥？",
                                llmKey: "移除纠错密钥并关闭纠错？",
                                test: "发送测试音频进行识别？",
                                restart: "重启 Coe 服务？"
                            }[root.confirm] || "请确认")
                    }
                    Caption {
                        text: root.confirm === "test" ? "会上传半秒合成音，服务商可能计费。此测试不代表真实语音准确率。" : root.confirm === "asrKey" || root.confirm === "llmKey" ? "保存并应用后生效。其他配置不变，历史备份仍保留密钥。" : root.confirm === "restart" ? "会短暂断开服务。录音或识别期间不能重启。" : "取消可返回继续编辑。"
                    }
                    Row {
                        spacing: 8
                        Action {
                            text: "取消"
                            onClicked: root.confirm = ""
                        }
                        Action {
                            text: root.confirm === "test" ? "确认测试识别" : "确认"
                            bordered: true
                            enabled: !root.working
                            onClicked: {
                                var c = root.confirm;
                                root.confirm = "";
                                if (c === "discard")
                                    root.discard();
                                else if (c === "delete")
                                    root.send("delete", {
                                        id: root.pendingDelete
                                    });
                                else if (c === "asrKey") {
                                    root.removeAsrKey = true;
                                    root.asrSecret = "";
                                    root.editAsrKey = false;
                                } else if (c === "llmKey") {
                                    root.removeLlmKey = true;
                                    root.llmSecret = "";
                                    root.updateLlm("enabled", false);
                                    root.editLlmKey = false;
                                } else if (c === "test")
                                    root.send("test", root.asrPayload());
                                else if (c === "restart")
                                    root.send("service", {
                                        verb: "restart"
                                    });
                            }
                        }
                    }
                }
                Flickable {
                    id: scroller
                    width: parent.width
                    height: Math.max(40, parent.height - header.height - headerLine.height - footer.height - parent.spacing * 3 - (root.confirm !== "" ? confirmationHeight() : 0))
                    function confirmationHeight() {
                        return layout.children[2].height + layout.spacing;
                    }
                    contentHeight: pageLoader.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    QQC.ScrollBar.vertical: QQC.ScrollBar {
                        policy: scroller.contentHeight > scroller.height ? QQC.ScrollBar.AsNeeded : QQC.ScrollBar.AlwaysOff
                    }
                    Loader {
                        id: pageLoader
                        width: parent.width
                        sourceComponent: ({
                                home: homePage,
                                settings: settingsPage,
                                profiles: profilesPage,
                                asr: asrPage,
                                llm: llmPage,
                                diagnostics: diagnosticsPage,
                                language: languagePage
                            }[root.page] || homePage)
                    }
                }
                Column {
                    id: footer
                    width: parent.width
                    spacing: 8
                    Caption {
                        visible: root.inFlight && root.page !== "home"
                        text: "录音或识别进行中，结束后才可应用设置。"
                    }
                    Caption {
                        visible: root.editor
                        text: root.dirty ? "未保存的更改" : "与已保存配置一致"
                        color: root.dirty ? Color.accent : root.muted
                    }
                    Row {
                        visible: root.editor
                        width: parent.width
                        spacing: 8
                        Action {
                            width: (parent.width - 8) / 2
                            text: "取消"
                            enabled: !root.working
                            onClicked: root.back()
                        }
                        Action {
                            width: (parent.width - 8) / 2
                            text: root.working ? "正在应用…" : "保存并应用"
                            bordered: true
                            enabled: root.dirty && !root.working && !root.inFlight
                            onClicked: root.save()
                        }
                    }
                    Caption {
                        visible: root.feedback !== "" || root.working || !!(root.hostWidget && (root.hostWidget.snapshot.error || root.hostWidget.snapshot.hotkey_error))
                        text: root.working ? "正在处理，请稍候…" : (root.feedback || (root.hostWidget ? (root.hostWidget.snapshot.error || root.hostWidget.snapshot.hotkey_error || "") : ""))
                        color: root.feedbackError || (root.hostWidget && !!root.hostWidget.snapshot.error) ? Color.urgent : Color.accent
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }

    Component {
        id: homePage
        Column {
            width: parent.width
            spacing: 18
            Column {
                width: parent.width
                spacing: 8
                Caption {
                    text: "当前模型"
                }
                Dropdown {
                    id: modelPicker
                    width: parent.width
                    showLabel: false
                    options: root.options()
                    value: root.store.active || ""
                    enabled: !root.working && !root.inFlight
                    onChanged: function (v) {
                        value = root.store.active || "";
                        if (v !== root.store.active)
                            root.send("activate", {
                                id: v
                            });
                    }
                }
                Connections {
                    target: root
                    function onStoreChanged() {
                        modelPicker.value = root.store.active || "";
                    }
                }
                HoverHandler {
                    id: modelHover
                }
                QQC.ToolTip.visible: modelHover.hovered
                QQC.ToolTip.text: (root.activeProfile.name || "") + "\n" + (root.activeProfile.model || "")
                QQC.ToolTip.delay: 600
            }
            Action {
                width: parent.width
                height: 58
                text: root.dictationState === "recording" ? "结束录音并识别" : root.dictationState === "processing" ? "正在识别，请稍候" : "开始语音输入"
                iconText: root.dictationState === "recording" ? "󰓛" : root.dictationState === "processing" ? "󰔟" : "󰍬"
                iconSpinning: root.dictationState === "processing"
                fontSize: Style.font.title
                background: Util.alpha(Color.accent, 0.16)
                bordered: true
                enabled: !root.working && root.dictationState !== "processing" && root.dictationState !== "offline" && !!root.store.active
                onClicked: {
                    root.reallyClose();
                    recordDelay.restart();
                }
            }
            Column {
                width: parent.width
                spacing: 8
                Flow {
                    width: parent.width
                    spacing: 6
                    Text {
                        width: 78
                        height: 32
                        verticalAlignment: Text.AlignVCenter
                        text: "识别语言"
                        color: root.ink
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                    }
                    Repeater {
                        model: root.languageChoices(root.activeProfile, "").filter(function(o) {
                            return ["", "zh", "en"].indexOf(o.value) >= 0;
                        })
                        Action {
                            required property var modelData
                            text: modelData.value === "" ? "自动" : modelData.label
                            selected: root.normalizedLanguage(root.activeProfile.language) === modelData.value
                            enabled: !root.working && !root.inFlight && root.languageSelectable(modelData.value)
                            onClicked: root.selectLanguage(modelData.value)
                        }
                    }
                    Action {
                        text: "更多"
                        enabled: !root.working && !!root.activeProfile.id
                        onClicked: root.navigate("language")
                    }
                }
                Caption {
                    visible: !root.languageSupported(root.activeProfile)
                    text: "当前模型自动识别语言，无需手动选择。"
                }
            }
            Divider {}
            Row {
                width: parent.width
                spacing: 12
                Column {
                    width: parent.width - toggle.implicitWidth - 12
                    spacing: 4
                    Heading {
                        text: "AI 文本纠错"
                        font.bold: false
                    }
                    Caption {
                        text: "自动优化标点和表达"
                    }
                }
                Switch {
                    id: toggle
                    anchors.verticalCenter: parent.verticalCenter
                    checked: !!root.store.llm.enabled
                    enabled: !root.working && !root.inFlight
                    onToggled: root.send("preferences", {
                        llm_enabled: !checked
                    })
                }
            }
            Row {
                width: parent.width
                Text {
                    width: parent.width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    text: "文本输出"
                    color: root.ink
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                }
                Caption {
                    width: parent.width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    horizontalAlignment: Text.AlignRight
                    text: "智能粘贴"
                }
            }
            Divider {}
            Row {
                width: parent.width
                Text {
                    width: parent.width - manage.implicitWidth
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.shortcutLabel
                    color: root.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                }
                Action {
                    id: manage
                    text: "管理与设置  ›"
                    fontSize: Style.font.caption
                    onClicked: root.navigate("settings")
                }
            }
            Caption {
                text: "音频发送至所选服务；不保存录音或转写历史。"
            }
        }
    }
    Component {
        id: settingsPage
        Column {
            width: parent.width
            spacing: 8
            NavRow {
                label: "模型与服务"
                description: (root.store.profiles || []).length + " 项已保存配置 · 管理默认模型与密钥"
                onActivated: root.navigate("profiles")
            }
            NavRow {
                label: "AI 文本纠错"
                description: root.store.llm.enabled ? "已开启 · 配置独立模型与纠错指令" : "已关闭 · 连接配置和指令已保留"
                onActivated: root.navigate("llm")
            }
            NavRow {
                label: "服务与诊断"
                description: "服务状态、恢复与录音取消"
                onActivated: root.navigate("diagnostics")
            }
        }
    }
    Component {
        id: profilesPage
        Column {
            width: parent.width
            spacing: 12
            Caption {
                text: "切换当前模型用于本次及之后的录音；默认标记可独立设置。"
            }
            Repeater {
                model: root.store.profiles || []
                Column {
                    id: profileRow
                    required property var modelData
                    width: parent.width
                    spacing: 6
                    Action {
                        width: parent.width
                        leftAlign: true
                        text: ""
                        selected: profileRow.modelData.id === root.store.active
                        tooltipText: profileRow.modelData.name + "\n" + profileRow.modelData.model
                        onClicked: root.expandedProfile = root.expandedProfile === profileRow.modelData.id ? "" : profileRow.modelData.id
                        Text {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            verticalAlignment: Text.AlignVCenter
                            text: (profileRow.modelData.id === root.store.active ? "✓  " : "    ") + root.shortName(profileRow.modelData)
                            color: root.ink
                            font.family: Style.font.family
                            font.pixelSize: Style.font.body
                            elide: Text.ElideRight
                            textFormat: Text.PlainText
                        }
                    }
                    Caption {
                        text: (profileRow.modelData.id === root.store.active ? "当前使用" : "已保存") + (profileRow.modelData.id === root.store.default ? "  ·  默认" : "")
                        leftPadding: 12
                    }
                    Flow {
                        width: parent.width
                        visible: root.expandedProfile === profileRow.modelData.id
                        spacing: 4
                        Action {
                            text: "使用此模型"
                            enabled: !root.working && !root.inFlight && profileRow.modelData.id !== root.store.active
                            onClicked: root.send("activate", {
                                id: profileRow.modelData.id
                            })
                        }
                        Action {
                            text: "编辑"
                            enabled: !root.working
                            onClicked: root.editProfile(profileRow.modelData.id)
                        }
                        Action {
                            text: "复制"
                            enabled: !root.working && !root.inFlight
                            onClicked: root.send("duplicate", {
                                id: profileRow.modelData.id
                            })
                        }
                        Action {
                            text: "设为默认"
                            enabled: !root.working && !root.inFlight && profileRow.modelData.id !== root.store.default
                            onClicked: root.send("default", {
                                id: profileRow.modelData.id
                            })
                        }
                        Action {
                            text: "删除"
                            foreground: Color.urgent
                            enabled: !root.working && !root.inFlight && profileRow.modelData.id !== root.store.active
                            onClicked: {
                                root.pendingDelete = profileRow.modelData.id;
                                root.confirm = "delete";
                            }
                        }
                    }
                    Divider {}
                }
            }
            Action {
                width: parent.width
                text: "＋ 添加语音识别服务"
                bordered: true
                onClicked: root.editProfile("")
            }
        }
    }
    Component {
        id: asrPage
        Column {
            width: parent.width
            spacing: 14
            Field {
                label: "配置名称"
                value: root.asrDraft.name || ""
                limit: 80
                onEdited: function (v) {
                    root.updateAsr("name", v);
                }
            }
            Dropdown {
                width: parent.width
                label: "语音识别服务"
                value: root.providerChoice
                options: root.providerOptions
                onChanged: function (v) {
                    root.chooseProvider(v);
                    value = Qt.binding(function() { return root.providerChoice; });
                }
            }
            Field {
                label: "模型名称（模型 ID）"
                value: root.asrDraft.model || ""
                placeholder: root.asrDraft.provider === "sensevoice" ? "由服务端管理" : "填写服务商提供的模型名称"
                enabled: ["doubao", "sensevoice"].indexOf(root.asrDraft.provider) < 0
                limit: 256
                onEdited: function (v) {
                    root.updateAsr("model", v);
                }
            }
            Field {
                label: "API Endpoint · 服务地址"
                value: root.asrDraft.endpoint || ""
                placeholder: "https://…"
                onEdited: function (v) {
                    root.updateAsr("endpoint", v);
                }
            }
            Caption {
                visible: String(root.asrDraft.endpoint).indexOf("http://") === 0
                text: "此地址使用 HTTP，传输未加密。"
            }
            Column {
                width: parent.width
                spacing: 8
                visible: root.asrDraft.provider !== "sensevoice"
                Row {
                    width: parent.width
                    spacing: 6
                    Caption {
                        width: parent.width - 174
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.removeAsrKey ? "密钥将在保存后移除" : root.asrDraft.key_present ? "已配置密钥" : "尚未配置密钥"
                    }
                    Action {
                        text: root.editAsrKey ? "收起" : root.asrDraft.key_present ? "更换密钥" : "填写密钥"
                        onClicked: root.editAsrKey = !root.editAsrKey
                    }
                    Action {
                        text: "移除"
                        enabled: !!root.asrDraft.key_present && !root.removeAsrKey
                        onClicked: root.confirm = "asrKey"
                    }
                }
                Field {
                    visible: root.editAsrKey || (!root.editingId && !root.asrDraft.key_present)
                    label: "API Key · 留空保留已有密钥"
                    secret: true
                    value: root.asrSecret
                    limit: 8192
                    onEdited: function (v) {
                        root.asrSecret = v;
                        if (v)
                            root.removeAsrKey = false;
                    }
                }
            }
            Action {
                width: parent.width
                leftAlign: true
                text: (root.advanced ? "▾ " : "▸ ") + "高级参数"
                onClicked: root.advanced = !root.advanced
            }
            Column {
                width: parent.width
                spacing: 14
                visible: root.advanced
                Field {
                    label: "请求超时（秒）"
                    value: String(root.asrDraft.timeout || "")
                    inputValidator: IntValidator {
                        bottom: 1
                        top: 600
                    }
                    onEdited: function (v) {
                        root.updateAsr("timeout", Number(v));
                    }
                }
                Dropdown {
                    width: parent.width
                    label: "识别语言"
                    value: root.normalizedLanguage(root.asrDraft.language)
                    options: root.languageChoices(root.asrDraft, root.asrDraft.language)
                    enabled: root.languageSupported(root.asrDraft)
                    onChanged: function (v) {
                        root.updateAsr("language", v);
                        value = Qt.binding(function() { return root.normalizedLanguage(root.asrDraft.language); });
                    }
                }
                Field {
                    visible: root.draftLanguageCapability.mode === "hints" || (root.languageSupported(root.asrDraft) && !root.draftLanguageCapability.verified)
                    label: root.draftLanguageCapability.mode === "hints" ? "语言提示（可选）" : "识别语言代码（可选）"
                    value: root.asrDraft.language || ""
                    placeholder: "留空使用自动识别"
                    limit: 32
                    onEdited: function (v) {
                        root.updateAsr("language", v);
                    }
                }
                Caption {
                    visible: root.draftLanguageCapability.mode === "hints"
                    text: "最多 " + root.draftLanguageCapability.max_hints + " 个，使用英文逗号分隔。"
                }
                Caption {
                    visible: root.languageSupported(root.asrDraft) && !root.draftLanguageCapability.verified
                    text: "尚未确认此模型的可选语言。优先使用自动识别；如需手动指定，请先核对服务的语言支持。"
                }
                Caption {
                    visible: !root.languageSupported(root.asrDraft)
                    text: "此协议没有独立语言字段，请在支持时通过上下文提示。"
                }
                Field {
                    label: root.asrDraft.provider === "aliyun-asr" ? "专业术语与上下文（最多 400 字）" : "识别提示（ASR Prompt）"
                    value: root.asrDraft.prompt || ""
                    enabled: ["openai", "qwen3-asr-vllm", "aliyun-asr"].indexOf(root.asrDraft.provider) >= 0
                    limit: root.asrDraft.provider === "aliyun-asr" ? 400 : 16000
                    onEdited: function (v) {
                        root.updateAsr("prompt", v);
                    }
                }
                Caption {
                    text: ({
                            "openai": "音频转写接口；兼容服务需真正支持音频上传。",
                            "aliyun-asr": "百炼原生音频接口；使用完整 /api/v1 服务地址。",
                            "doubao": "豆包 Flash 专用认证，固定 bigmodel，不支持独立语言及提示。",
                            "sensevoice": "SenseVoice FastAPI 音频上传；当前适配器不发送认证头。",
                            "qwen3-asr-vllm": "音频 Chat 请求；不是普通文本聊天接口。"
                        }[root.asrDraft.provider] || "此协议需要额外适配器。")
                }
                Caption {
                    text: "其他原生协议和实时流式识别需独立适配器，目前不支持。"
                }
            }
            Divider {}
            Flow {
                width: parent.width
                spacing: 8
                Action {
                    text: "检查配置"
                    enabled: !root.working
                    onClicked: root.send("check", root.asrPayload())
                    tooltipText: "仅校验字段，不联网、不发送音频"
                }
                Action {
                    text: "测试识别…"
                    enabled: !root.working && !root.inFlight && !root.removeAsrKey
                    onClicked: root.confirm = "test"
                    tooltipText: "确认后向当前表单中的服务上传合成测试音频"
                }
            }
            Caption {
                text: "保存并应用会更新当前模型，不改变默认模型标记。留空的密钥不会被清除。"
            }
        }
    }
    Component {
        id: llmPage
        Column {
            width: parent.width
            spacing: 14
            Row {
                width: parent.width
                Heading {
                    width: parent.width - llmToggle.implicitWidth
                    text: "启用 AI 文本纠错"
                    anchors.verticalCenter: parent.verticalCenter
                }
                Switch {
                    id: llmToggle
                    checked: !!root.llmDraft.enabled
                    onToggled: root.updateLlm("enabled", !checked)
                }
            }
            Caption {
                text: "识别完成后再优化标点和表达，会增加一次模型请求。关闭时保留连接、密钥和指令。"
            }
            Action {
                visible: !root.llmDraft.enabled
                width: parent.width
                text: root.showLlmConnection ? "收起连接设置" : "查看已保存的连接设置"
                onClicked: root.showLlmConnection = !root.showLlmConnection
            }
            Column {
                width: parent.width
                spacing: 14
                visible: root.llmDraft.enabled || root.showLlmConnection
                Dropdown {
                    width: parent.width
                    label: "纠错接口类型"
                    value: root.llmDraft.endpoint_type || "chat"
                    options: [
                        {
                            value: "chat",
                            label: "兼容聊天接口"
                        },
                        {
                            value: "responses",
                            label: "OpenAI 响应接口"
                        }
                    ]
                    onChanged: function (v) {
                        root.updateLlm("endpoint_type", v);
                    }
                }
                Field {
                    label: "LLM Endpoint · 独立服务地址"
                    value: root.llmDraft.endpoint || ""
                    onEdited: function (v) {
                        root.updateLlm("endpoint", v);
                    }
                }
                Field {
                    label: "纠错模型名称"
                    value: root.llmDraft.model || ""
                    limit: 256
                    onEdited: function (v) {
                        root.updateLlm("model", v);
                    }
                }
                Row {
                    width: parent.width
                    spacing: 6
                    Caption {
                        width: parent.width - 174
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.removeLlmKey ? "密钥将在保存后移除" : root.llmDraft.key_present ? "已配置独立密钥" : "尚未配置密钥"
                    }
                    Action {
                        text: root.editLlmKey ? "收起" : "更换密钥"
                        onClicked: root.editLlmKey = !root.editLlmKey
                    }
                    Action {
                        text: "移除"
                        enabled: !!root.llmDraft.key_present && !root.removeLlmKey
                        onClicked: root.confirm = "llmKey"
                    }
                }
                Field {
                    visible: root.editLlmKey
                    label: "LLM API Key · 留空保留已有密钥"
                    secret: true
                    value: root.llmSecret
                    limit: 8192
                    onEdited: function (v) {
                        root.llmSecret = v;
                        if (v)
                            root.removeLlmKey = false;
                    }
                }
                Field {
                    label: "纠错请求超时（秒）"
                    value: String(root.llmDraft.timeout || "")
                    inputValidator: IntValidator {
                        bottom: 1
                        top: 600
                    }
                    onEdited: function (v) {
                        root.updateLlm("timeout", Number(v));
                    }
                }
                Action {
                    width: parent.width
                    leftAlign: true
                    text: (root.promptExpanded ? "▾ " : "▸ ") + "自定义纠错指令"
                    onClicked: root.promptExpanded = !root.promptExpanded
                }
                Column {
                    width: parent.width
                    spacing: 8
                    visible: root.promptExpanded
                    QQC.TextArea {
                        width: parent.width
                        implicitHeight: 150
                        text: root.llmDraft.prompt || ""
                        color: root.ink
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                        font.family: Style.font.family
                        font.pixelSize: Style.font.body
                        onTextChanged: root.updateLlm("prompt", text)
                        background: Rectangle {
                            color: Util.alpha(root.ink, 0.04)
                            border.color: Util.alpha(root.ink, 0.24)
                            radius: Style.cornerRadius
                        }
                    }
                    Caption {
                        text: "{{.Dictionary}} 会由 Coe 展开为个人词典。保留此变量以继续使用词典；场景能力不受影响。"
                    }
                }
            }
        }
    }
    Component {
        id: diagnosticsPage
        Column {
            width: parent.width
            spacing: 16
            Heading {
                text: "Coe 服务 · " + root.stateLabel
            }
            Caption {
                text: root.hostWidget && root.hostWidget.bridgeConnected ? "界面桥接层已连接" : "界面桥接层未连接"
            }
            Caption {
                text: root.dictationState !== "offline" ? "D-Bus 状态同步正常" : "D-Bus 服务未连接，请启动服务"
            }
            Caption {
                text: "当前快捷键：" + root.shortcutLabel
            }
            Caption {
                text: "按住右 Alt 开始录音，松开后自动识别。快捷键和触发方式由插件固定管理。"
            }
            Caption {
                text: "文本自动智能粘贴：终端使用 Shift+Insert，普通应用使用 Ctrl+V。录音期间切换窗口或无法确认输入目标时，仅复制到剪贴板。"
            }
            Caption {
                text: "与官方语音输入共存：保留其服务和快捷键。右 Alt 被占用时不会接管；官方语音正在工作时不会开始 Coe 录音。请勿同时使用两套录音。"
            }
            Divider {}
            Caption {
                text: "默认不记录识别正文、录音或完整密钥。错误提示已去除远端响应正文。"
            }
            Action {
                text: "刷新状态"
                enabled: !root.working
                onClicked: root.send("get")
            }
            Action {
                text: root.dictationState === "offline" ? "启动服务" : "重启服务…"
                enabled: !root.working && !root.inFlight
                onClicked: root.dictationState === "offline" ? root.send("service", {
                    verb: "start"
                }) : root.confirm = "restart"
            }
            Action {
                text: "取消当前录音"
                foreground: Color.urgent
                enabled: !root.working && root.dictationState === "recording"
                onClicked: root.send("cancel")
            }
            Caption {
                text: root.inFlight ? "等待当前录音或识别结束后才能重启。" : "配置应用失败时，桥接层会恢复上一次有效配置。"
            }
        }
    }
    Component {
        id: languagePage
        Column {
            width: parent.width
            spacing: 16
            Dropdown {
                width: parent.width
                objectName: "识别语言选择"
                label: "识别语言"
                value: root.languageDraft
                options: root.languageOptions
                enabled: !root.working && !root.inFlight && root.languageSupported(root.activeProfile)
                onChanged: function (v) {
                    if (root.languageSelectable(v))
                        root.languageDraft = v;
                    value = Qt.binding(function() { return root.languageDraft; });
                }
            }
            Caption {
                text: !root.languageSupported(root.activeProfile) ? "当前模型自动识别语言，无需手动设置。" : !root.activeLanguageCapability.verified ? "当前模型的可选语言尚未确认，建议使用自动识别。已保存的设置会保留。" : "建议使用自动识别，无需随讲话内容反复切换。"
            }
            Caption {
                visible: !!root.normalizedLanguage(root.activeProfile.language) && root.activeLanguageCapability.codes.indexOf(root.normalizedLanguage(root.activeProfile.language)) < 0
                text: "正在使用已保存的高级语言设置，可在模型高级参数中查看。"
            }
            Action {
                width: parent.width
                text: "应用语言"
                bordered: true
                enabled: !root.working && !root.inFlight && root.languageSelectable(root.languageDraft) && root.languageProfileId === root.activeProfile.id && root.languageDraft !== root.normalizedLanguage(root.activeProfile.language)
                onClicked: root.selectLanguage(root.languageDraft)
            }
        }
    }
}
