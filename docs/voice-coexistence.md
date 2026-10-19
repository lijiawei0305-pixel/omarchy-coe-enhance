# 与官方语音输入共存

官方默认 F9 / Super+Ctrl+X 与 Coe 右 Alt 分开。插件不卸载、停用或改写官方 Voxtype，不恢复用户已经删除的官方绑定，不占用其默认 Socket。

## 实际保护

- 安装写入前检查 Hyprland Alt_R 按下/松开绑定，以及 Voxtype `[hotkey] enabled/key` 的 evdev 监听。冲突或配置无法确认时停止，不抢绑。
- 既有 10 秒维护周期重新检查绑定；新增冲突时只移除当前 bridge owner 的 Lua handles，不执行全局解绑。
- 面板按钮和右 Alt 共用同一个开始录音入口。调用 Coe D-Bus Start 前执行一次本机 `voxtype status --format text`，最多等待 1 秒；只有 idle/stopped/未安装才放行。忙、未知状态或超时拒绝开始。
- 状态查询由已安装版本解析自己的状态文件和 PID。若运行 daemon 使用 `--config` / `-c`，查询沿用该配置路径；完整配置和命令行不进入 UI/日志。
- Stop/Cancel 不受官方状态检查阻挡。没有新增高频轮询或第二次录音。
- 原版 Voxtype GTK4 OSD 在插件私有 D-Bus 会话中运行，读取 `$XDG_RUNTIME_DIR/coe-enhance/osd/audio.sock`。只管理 Coe 启动的子进程。

## 边界

这是单向避让，不是两个 daemon 共同使用的原子锁。Coe 录音开始后，官方快捷键仍可能启动 Voxtype；同时按两套快捷键也有竞争窗口。请勿同时使用两套录音。

不保证任意第三方脚本、按硬件 keycode 绑定、自定义 submap、不同会话/运行目录或 Voxtype meeting 等额外入口都被识别。修改磁盘配置但未重载 daemon 也可能与生效配置不一致。无法确认官方状态时会拒绝开始，需先看诊断。

若未来需要严格单入口，应在明确授权下设计官方入口的接管和恢复；当前安装器不会擅自这样做。

## 验证

单元测试覆盖默认官方绑定、外来右 Alt、原生监听启停、自定义配置、未知状态/超时和只清理自己的绑定。隔离 D-Bus 测试在保护入口模拟官方忙碌，确认真实 Coe 保持空闲；放行后用合成录音和本地 Mock 验证一次 Start/Stop 只产生一次识别和输出。没有为测试启动官方录音或调用付费 API。
