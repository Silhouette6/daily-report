---
name: daily-report
description: 汇总用户当天有价值的浏览信息和 Git 工作区变更，并生成带日期的工作日报。当用户要求整理日报、总结今日工作、分析 Chrome 历史记录、汇总浏览看点，或基于 ./config.md 中的仓库生成工作总结时使用。
---

# 每日工作总结

## 快速开始

1. 获取本地日期，将 `TODAY` 设置为 `YYYY-MM-DD` 格式。
2. 在当前目录创建 `./Report/DailyReport${TODAY}` 文件夹；如果已经存在，则直接复用。
3. 在该文件夹中生成以下文件：
   - `chrome_view${TODAY}.json`
   - `browser_view.md`
   - `workspace_view.md`
   - `daily_report.md`

## 输入

- `./config.md`：以 Markdown 列表形式配置需要处理的 Git 工作区绝对路径。
- Chrome 历史数据库：`~/Library/Application Support/Google/Chrome/Default/History`
- Python 运行环境：当前目录下由 `uv` 管理的 `.venv`。

## 环境准备

1. 检查当前目录是否存在 `.venv`。如果不存在，执行：
   ```bash
   uv sync
   ```
2. 后续 Python 脚本统一通过 `uv run python` 执行，不使用系统 `python3`。

## 工作流程

### 1. 整理浏览记录

1. 执行以下命令，导出当天的 Chrome 浏览记录：
   ```bash
   uv run python scripts/export_chrome_history.py --date "$TODAY" --output "./Report/DailyReport$TODAY/chrome_view$TODAY.json"
   ```
2. 读取导出的 JSON，只保留有价值的信息：
   - 工作文档、PR、Issue、设计文档、技术文章、版本说明和厂商文档。
   - 忽略搜索结果页、登录跳转、广告、娱乐内容和重复打开的页面。
3. 调用子智能体探索筛选后的 URL，并明确要求它：
   - 首先读取当前目录下的 [`agent-reach/SKILL.md`](agent-reach/SKILL.md)。
   - 根据该文档的路由表，按需读取 `agent-reach/references/` 下的对应文档。
   - 严格使用文档中的 `uv` 命令管理 Python 工具，禁止使用 `pipx`、`pip install` 或系统 `python3`。
   - 将当前目录中的 Agent Reach 文档视为本任务的最高优先级操作说明。
4. 将结果写入 `browser_view.md`，包含：
   - `## 今日看点`
   - 每个主题使用一个条目，说明页面内容、今天为什么值得关注，以及它与当前工作的可能关系。
   - `## 值得跟进`
   - 记录尚未解决的问题、需要做出的决定，以及明天值得继续查看的链接。

### 2. 整理工作区内容

1. 读取 `./config.md`，提取所有需要处理的工作区路径。
2. 对每个 Git 仓库检查当天的提交和未提交变更，可使用：
   ```bash
   git -C <repo> log --since "$TODAY 00:00" --date=iso --stat --oneline
   git -C <repo> status --short
   git -C <repo> diff --stat
   git -C <repo> diff --cached --stat
   ```
3. 根据需要读取关键文件的具体 diff。不能只根据文件名推断功能变化。而且可以积极地去读取相关文件代码来获取语义。
4. 聚焦功能和行为变化，不要简单罗列文件增删：
   - 新增的功能或用户行为。
   - 修复的问题或降低的风险。
   - API、数据结构、配置、工作流程或用户体验变化。
   - 新增的测试，以及仍然缺失的测试覆盖。
5. 将结果写入 `workspace_view.md`。每个仓库单独一个章节，包含：
   - 仓库路径。
   - 今天发生的功能性变化。
   - 对应的提交、diff 或文件证据。
   - 未完成的工作和潜在风险。

### 3. 生成最终日报

合并浏览记录和工作区总结，生成 `daily_report.md`，结构如下：

- `## 今日产出`
- `## 浏览看点`
- `## 工作区变更`
- `## 风险与明日跟进`

内容应简洁、具体，并以实际浏览记录、提交和代码变更为依据。

## 执行规则

- 所有日报生成文件必须存放在 `./Report/` 下，禁止写入项目根目录。
- 始终创建或复用 `./Report/DailyReport${TODAY}` 作为当日工作目录。
- 所有 Python 脚本必须使用当前项目的 uv 环境运行。
- 访问网页、GitHub 或远程资源时，如果遇到连接超时、连接重置、DNS、TLS 或国内网络访问限制，可灵活使用 Clash 的 `7897` 端口代理。优先仅为当前命令设置 `HTTP_PROXY=http://127.0.0.1:7897`、`HTTPS_PROXY=http://127.0.0.1:7897` 和 `ALL_PROXY=http://127.0.0.1:7897`，不要永久修改系统代理。
- 优先记录准确的 URL、仓库路径、提交 ID 和文件名，避免含糊描述。
- 如果网页无法访问或仓库不可用，明确记录缺失信息，然后继续处理其他内容。
- 在总结前合并重复访问记录，避免同一内容反复出现。
- 重点说明这些变化对用户、产品、工作流程或工程方向产生了什么影响。
