# 安装路径、备份与恢复

## 三个独立位置

| 位置 | 内容 |
|---|---|
| 你克隆的源码目录 | Git 仓库，使用 `git pull --ff-only` 更新 |
| `~/.config/omarchy/plugins/cc.coe-enhance/` | 安装器部署的运行副本，使用 Omarchy 管理器启用/禁用 |
| `~/.local/share/omarchy-coe-enhance/` | 固定 Coe 构建副本、bin、venv 和安装备份 |

安装器不能从运行副本目录直接运行，以免删除自己的 Git 源码。仅用 Omarchy 克隆并启用插件不负责构建 Coe 后端，因此首次安装请使用 README 中的克隆 + 安装器流程。

## 用户数据

- `~/.config/coe/config.yaml`：实际 Coe 配置。
- `~/.config/coe/env`：API Key 环境变量，0600。
- `~/.config/omarchy-coe-enhance/profiles.json`：Profile 元数据及密钥引用。
- 同目录 `backups/`、`last-good.yaml`：配置事务备份和有效配置。
- `~/.config/systemd/user/coe.service`：唯一受管 Coe 服务。

不会编辑 `/usr/share/omarchy`、静态 Hyprland 配置、Voxtype 或 Fcitx 配置。快捷键使用当前 Hyprland 会话中的 Lua binding handles，禁用插件会清理自己的 handles。原版波形使用私有运行目录和 D-Bus 会话。

## 失败恢复

保存配置时，config/env/Profiles 在同一事务中备份并原子替换。服务未恢复 D-Bus 就不会显示应用成功，失败时恢复旧文件。不要为排错删除 env 或 Profiles；用户可在诊断页重启服务。

安装备份位于 `~/.local/share/omarchy-coe-enhance/installation-backups/<时间>/`，保留升级前的插件、服务文件和现有 Shell 配置副本。涉及密钥的配置事务备份只在私人配置目录，不应上传。

恢复旧插件时，先结束录音并禁用本插件，备份当前部署副本，再从选定安装备份恢复 `plugin/`，重扫并重新启用。不要整体覆盖 `shell.json`，避免撤销后来其他插件的改动。后端也有变动时，需要同时回到对应源码版本并重建固定 Coe 补丁，不能把未知上游版本混入现有构建目录。

```bash
omarchy plugin disable cc.coe-enhance
# 审阅并恢复你选定的备份，不恢复或删除其他用户配置
omarchy-shell shell rescanPlugins
omarchy plugin enable cc.coe-enhance --section right
```

卸载使用 `python3 scripts/uninstall.py`，保留 Coe、Fcitx5、Voxtype、配置和密钥。是否停止本项目创建的 Coe 服务由用户单独决定。
