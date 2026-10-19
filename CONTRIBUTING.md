# Contributing

感谢参与。先阅读 [架构](docs/architecture.md)、[测试](docs/testing.md)及 [SECURITY.md](SECURITY.md)。小范围、可验证的修改更容易审阅。

- 不改用户已有 Profile、密钥、快捷键或词典；保留配置原子写入、备份和失败回滚。
- 新 ASR Provider 必须实现真实协议并覆盖本地 HTTP Mock 的字段和失败场景，不能只因兼容 Chat API 就标为转写兼容。
- 不在 Python/QML 重写 Coe 语音流水线，不新增第二次麦克风采集或仿制 OSD。
- 不在测试中使用真实密钥、自动请求付费 API，或将原始录音/转写正文写入日志。
- QML 修改要在实际 Omarchy Shell 中验证；不要启动第二个 Shell 或更改打包系统源码。

提交前运行 Python 单元测试及相关 Go 测试。桌面集成脚本必须在你自己的空闲会话里明确选择运行；它们可能临时修改配置、操作焦点或重启服务。提交说明应包含问题、改动、验证和剩余限制。

贡献遵循本仓库 Apache-2.0 许可证。修改上游派生部分时保留对应版权和第三方声明。
