# 架构与接口

三层：Quattro中的单个原生BarWidget/Panel → 随组件生命周期运行的Python bridge → 唯一Coe Go用户服务。没有额外Quickshell实例、Python ASR流水线或逐字中文模拟。

固定Coe提交 `1345eccb5129cb067a49646e6b73572562d38521`。ASR Client提供Transcribe(context.Context,audio.Result)与Name；复用Coe PCM→WAV。面板协议测试通过Go probe调用同一Adapter发送合成音，不证明语音准确率。

D-Bus：com.mistermorph.Coe，路径/com/mistermorph/Coe，接口com.mistermorph.Coe.Dictation1。启动查Status，订阅StateChanged/ResultReady/ErrorRaised/NameOwnerChanged，状态idle/recording/processing/completed/error。离线由NameOwner推导。10秒维护修复绑定/刷新配置，不循环查询Status。重连清除旧session去重集合。

bridge socket位于$XDG_RUNTIME_DIR/coe-enhance/bridge.sock，目录0700/socket0600，fcntl锁防止多个owner。QML Process.stdin JSON传递密钥，argv只有脚本路径与实例token。GLib接收事件、线程执行阻塞操作，面板开关可即时越过识别阻塞。

配置切换要求Coe空闲；进行中直接拒绝提示稍后应用。config/env/Profiles同一事务备份/回滚；D-Bus恢复才显示有效配置。保留无关YAML/词典/场景，inline Prompt未改时保留prompt_file。

bridge是唯一最终输出者。COE_ENHANCE_BRIDGE=1时补丁禁用Pipeline.Output并跳过GNOME Portal绑定。Start保存address/pid/class，跟踪activewindowv2；任何切窗、面板打开或目标缺失都只复制。ResultReady必须匹配主动开始的expected_session且只提交一次；重载不重放旧结果。外部coe trigger没有插件捕获的安全目标，不会自动粘贴。

wl-copy整段UTF-8后核验wl-paste，复制失败/内容变化不粘贴。根据Omarchy terminal标签及稳定class选择Shift+Insert，否则Ctrl+V。Lua在按键前再次核验窗口与交互layer。跨进程极短竞态不能完全消除，默认倾向只复制。

补丁拆分：privacy-output修正正文日志、唯一输出者、pw-record --raw；aliyun工厂补丁注册Provider，core/aliyun.go为独立Native Adapter，core测试随安装器复制入固定构建副本。不会修改打包Shell源码。

扩展协议须新增Go Client、工厂注册、Python模板/验证、QML选项和请求/失败矩阵测试，不能假装套用现有Adapter。
