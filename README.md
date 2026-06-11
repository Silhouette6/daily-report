# Daily Report

用于根据当天的 Chrome 浏览记录和 Git 工作区变更生成工作日报。

## 依赖与环境

- 本项目使用 `uv` 管理 Python 版本、虚拟环境和依赖。
- 网页搜索与内容读取依赖 [Agent Reach](agent-reach/SKILL.md)。
- Agent Reach 及其 Python CLI 统一使用 `uv tool` 管理，不使用 `pipx`。

首次使用时执行：

```bash
uv sync
uv tool install https://github.com/Panniantong/agent-reach/archive/main.zip
agent-reach install --env=auto
agent-reach doctor
```

详细安装说明见 [agent-reach/references/install.md](agent-reach/references/install.md)。

## 使用方式

1. 在 `config.md` 中配置需要分析的 Git 工作区。
2. 确认 `uv` 环境和 Agent Reach 已完成初始化。
3. 让 Agent 按照 `SKILL.md` 执行日报任务。

日报统一生成到：

```text
Report/DailyReportYYYY-MM-DD/
├── chrome_viewYYYY-MM-DD.json
├── browser_view.md
├── workspace_view.md
└── daily_report.md
```

网页探索规则位于 `agent-reach/`，Chrome 历史导出脚本位于 `scripts/`。
