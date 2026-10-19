# 测试与构建

## 不接触桌面的后端构建

```bash
python3 scripts/build_backend.py --output-dir /tmp/coe-test-build
```

需要 Go ≥ 1.24 和 git。脚本从固定 Coe 提交应用当前补丁，构建 `bin/coe` 和 `bin/coe-probe`；不写用户配置、不启用服务、不操作快捷键。输出目录必须在插件源码树之外。支持 `--go /path/to/go` 和用于本地复现的 `--coe-source /path/to/coe-git`。

## 单元及协议测试

使用能够导入 `dbus`、`gi` 和 `ruamel.yaml` 的 Python。安装后的 venv 可以直接复用：

```bash
COE_TEST_PROBE=/tmp/coe-test-build/bin/coe-probe \
  ~/.local/share/omarchy-coe-enhance/venv/bin/python -B -m unittest discover -s tests -v

cd /tmp/coe-test-build/core
go test ./...
go test -race ./...
```

协议测试调用真实编译的 Go Adapter，对 localhost Mock 提交合成 WAV。覆盖成功、空文本、401/429/500、不兼容模型、超时、断开、非法 JSON、缺密钥及语言字段映射。不使用用户 API Key。没有 probe 时会显式跳过协议测试，不能把跳过当成已通过。

## 隔离端到端测试

```bash
COE_TEST_BINARY=/tmp/coe-test-build/bin/coe \
  dbus-run-session -- ~/.local/share/omarchy-coe-enhance/venv/bin/python -B tests/bootstrap_e2e.py

COE_TEST_BINARY=/tmp/coe-test-build/bin/coe \
  dbus-run-session -- ~/.local/share/omarchy-coe-enhance/venv/bin/python -B tests/hold_e2e.py
```

独立 D-Bus、临时配置、合成录音器、本地 ASR Mock 和捕获输出。验证右 Alt 按下/松开逻辑、重复事件去重、中文结果及官方忙/未知状态保护。不会采集真实麦克风或发送云端请求。生成资料在 Git 忽略的 `docs/evidence/`。

## 实际 Omarchy 验证

```bash
omarchy plugin validate .
python3 scripts/lint.py
```

`qmllint` 需要本机 `/usr/share/omarchy/shell` 的 QML 元数据。CI 不假装具有真实桌面；仅执行后端和官方 manifest 检查。

首次发布前，本机已验证 85 项单元测试、上述隔离链路、原版 OSD、真实面板和右 Alt 开始录音后取消；7 个相关配置逐字节不变，Coe/Voxtype/Shell 原进程未被替换。原始本机日志、含私人地址的截图及开发历史未发布。公开截图仅用于展示界面，不是云端准确率证明。

`tests/live_e2e.py`、`ui_live.py`、`lifecycle.py` 等脚本会操作真实窗口、临时配置或服务，不能加入无人值守的通用 CI。`tests/cloud_e2e.py` 会调用付费服务，必须另行获得明确授权和预算；不要在 GitHub Actions 传入真实 ASR/LLM 密钥。
