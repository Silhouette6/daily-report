# Agent Reach 安装说明（uv）

本机使用 `uv` 管理 Agent Reach 及其 Python CLI。不要改用其他 Python 包管理器。

## 安装 Agent Reach

```bash
uv tool install https://github.com/Panniantong/agent-reach/archive/main.zip
agent-reach install --env=auto
agent-reach doctor
```

如已安装但需要升级：

```bash
uv tool upgrade agent-reach
agent-reach install --env=auto
agent-reach doctor
```

如果 `uv tool upgrade agent-reach` 无法识别从 URL 安装的包，强制重装：

```bash
uv tool install --force https://github.com/Panniantong/agent-reach/archive/main.zip
```

## 安全检查

仅检查环境，不自动安装系统依赖：

```bash
agent-reach install --env=auto --safe
```

预览将执行的操作：

```bash
agent-reach install --env=auto --dry-run
```

## 安装渠道工具

```bash
uv tool install xiaohongshu-cli
uv tool install twitter-cli
uv tool install bilibili-cli
uv tool install 'git+https://github.com/public-clis/rdt-cli.git'
```

安装后直接调用对应命令：

```bash
xhs --help
twitter --help
bili --help
rdt --help
```

## 执行约束

- 不使用系统 Python 安装 Agent Reach 或渠道工具。
- 不在日报项目的 `.venv` 中安装独立 CLI；独立 CLI 使用 `uv tool` 隔离管理。
- 日报项目自身的脚本继续使用 `uv run python`。
- 临时 Python 依赖使用 `uv run --with <package> python ...`。
- Agent Reach 的配置和持久数据放在 `~/.agent-reach/`，临时文件放在 `/tmp/`。
- 下载或安装遇到国内网络限制时，为当前命令临时设置 `HTTP_PROXY=http://127.0.0.1:7897`、`HTTPS_PROXY=http://127.0.0.1:7897` 和 `ALL_PROXY=http://127.0.0.1:7897`。
