# 排错

## 基础诊断

```bash
~/.local/share/omarchy-coe-enhance/venv/bin/python -B scripts/coe-diagnostics.py
systemctl --user status coe.service
omarchy plugin validate ~/.config/omarchy/plugins/cc.coe-enhance
```

诊断脚本输出脱敏状态，不要另外公开 config/env、完整 Endpoint 或服务端响应正文。提交问题前再次检查输出和截图。

## 图标离线或无法加载

确认使用了安装器，而不是只克隆并启用 QML。检查 venv、Coe 服务和 D-Bus 是否可用。当前只支持 Quattro 和 Hyprland Lua API。修复后可执行 `omarchy-shell shell rescanPlugins`；不需要启动另一个 Shell。

本机兼容 QML 检查使用 `python3 scripts/lint.py`。Shell 日志可用 `quickshell log --pid <Shell-PID> --tail 100 --no-color`，先脱敏再分享。

## 右 Alt 没有开始录音

检查面板错误和诊断中的 `hotkey_error`、`voxtype_state`。冲突会拒绝接管；官方语音尚未空闲或状态查询超时也会阻止开始。不要为了安装而盲目删除其他绑定或停止官方服务。参见[共存机制](voice-coexistence.md)。

## 认证、模型或网络错误

401：密钥/地域/模型权限；429：额度或限流；5xx：服务临时异常。确认 Endpoint 对应真实音频协议。豆包、vLLM、阿里云原生接口不是普通 OpenAI Multipart 接口。模型名可编辑并不代表任何模型都兼容。

「测试识别」发送合成音频；空文本不能直接解释为认证失败。真实语音识别准确率需要另行验证，并会受服务计费规则影响。

## 只复制，没有粘贴

焦点变化、面板打开、交互 Layer 或目标无法确认时，这是安全降级。回到目标应用手动粘贴。终端默认 Shift+Insert；特殊 TUI 可能自行拦截该组合。不使用逐字中文按键模拟。

## 保存/升级失败

等待当前录音/识别结束。配置应用失败会恢复原事务。已有非本项目管理的 `coe.service` 会被拒绝覆盖；请审阅服务来源后再处理，不要直接删除配置。固定 Coe 构建目录被未知修改时，将其改名备份，再重新运行安装器。

## 当前限制

没有 Streaming ASR，不提供用户自定义快捷键/输出方式，不接管官方所有录音入口。未提供 Fcitx 原生 CommitString 模块；当前是保留 Fcitx/Rime 的 Clipboard 路径。完整注销登录、多屏、不同缩放、不同应用和键盘布局仍需按具体环境验证。
