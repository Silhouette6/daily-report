# Daily Report

用于根据当天的 Chrome 浏览记录和 Git 工作区变更生成工作日报。

## 使用方式

1. 在 `config.md` 中配置需要分析的 Git 工作区。
2. 使用 `uv sync` 初始化 Python 环境。
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

