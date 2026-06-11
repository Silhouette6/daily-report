---
name: agent-reach
description: >
  MUST USE when user asks to search, browse, read, or interact with content from any of these platforms:
  小红书/xiaohongshu/xhs, Twitter/推特/X, B站/bilibili,
  V2EX, Reddit, LinkedIn/领英, YouTube, GitHub code search,
  小宇宙播客, 雪球/股票行情, RSS feeds, or any web URL.

  Also MUST USE for: web搜索/搜/查/找/look up/research, 招聘/求职/jobs, 分享的链接/URL.
  Routes to CLI tools: xhs-cli, twitter-cli, rdt-cli, gh, yt-dlp, curl+Jina, mcporter.
  13 platforms. Zero config for 6 channels.

  【路由方式】SKILL.md 包含路由表和常用命令，复杂场景需按需阅读对应分类的 references/*.md。
  分类：search / social (小红书/推特/B站/V2EX/Reddit) / career(LinkedIn) / dev(github) / web(网页/文章/RSS) / video(YouTube/B站/播客)。
triggers:
  - search: 搜/查/找/search/搜索/查一下/帮我搜
  - social:
    - 小红书: xiaohongshu/xhs/小红书/红书
    - Twitter: twitter/推特/x.com/推文
    - B站: bilibili/b站/哔哩哔哩
    - V2EX: v2ex
    - Reddit: reddit
  - career: 招聘/职位/求职/linkedin/领英/找工作
  - dev: github/代码/仓库/gh/issue/pr/分支/commit
  - web: 网页/链接/文章/rss/读一下/打开这个
  - video: youtube/视频/播客/字幕/小宇宙/转录/yt
  - finance: 雪球/股票/stock/xueqiu/行情/基金
metadata:
  openclaw:
    homepage: https://github.com/Panniantong/Agent-Reach
---

# Agent Reach — 路由器

13 平台工具集合。根据用户意图选择对应分类。

## Python 工具管理

本机统一使用 `uv` 管理 Python CLI 和临时 Python 依赖。

- 禁止使用 `pipx`、`pip install` 或系统 `python3` 安装和运行工具。
- 安装 CLI：`uv tool install <package>`
- 升级 CLI：`uv tool upgrade <package>`
- 强制安装指定版本：`uv tool install --force '<package>==<version>'`
- 从 Git 仓库安装：`uv tool install 'git+https://...'`
- 运行临时 Python 依赖：`uv run --with <package> python ...`
- 安装后直接调用对应命令，例如 `xhs`、`twitter`、`rdt`、`bili`。
- 如果 `agent-reach` 命令不存在，读取 [安装说明](references/install.md)，使用 `uv tool` 安装。

## 网络代理

访问网页或远程资源失败，且疑似由国内网络限制导致时，可以使用本机 Clash 代理：

```bash
HTTP_PROXY=http://127.0.0.1:7897 \
HTTPS_PROXY=http://127.0.0.1:7897 \
ALL_PROXY=http://127.0.0.1:7897 \
<command>
```

- 可用于 `curl`、`uv`、`git`、`gh`、`yt-dlp` 和其他支持标准代理环境变量的命令。
- 优先按单条命令临时启用，不要永久修改 shell、Git 或系统代理配置。
- 仅在直连失败或明显受网络限制时启用；如果代理也失败，记录错误并继续处理其他资源。

## 路由表

| 用户意图 | 分类 | 详细文档 |
|---------|------|---------|
| 网页搜索/代码搜索 | search | [references/search.md](references/search.md) |
| 小红书/推特/B站/V2EX/Reddit | social | [references/social.md](references/social.md) |
| 招聘/职位/LinkedIn | career | [references/career.md](references/career.md) |
| GitHub/代码 | dev | [references/dev.md](references/dev.md) |
| 网页/文章/RSS | web | [references/web.md](references/web.md) |
| YouTube/B站/播客字幕 | video | [references/video.md](references/video.md) |

## 零配置快速命令

```bash
# Exa 网页搜索
mcporter call 'exa.web_search_exa(query: "query", numResults: 5)'

# 通用网页阅读
curl -s "https://r.jina.ai/URL"

# GitHub 搜索
gh search repos "query" --sort stars --limit 10

# Twitter 搜索
twitter search "query" -n 10

# YouTube/B站字幕
yt-dlp --write-sub --skip-download -o "/tmp/%(id)s" "URL"

# Reddit 搜索
rdt search "query" --limit 10

# Reddit 读帖 + 评论
rdt read POST_ID

# V2EX 热门
curl -s "https://www.v2ex.com/api/topics/hot.json" -H "User-Agent: agent-reach/1.0"
```

## 环境检查

```bash
# 检查可用 channel
agent-reach doctor

# 查看所有 MCP 服务
mcporter_list_servers()
```

## 工作区规则

**不要在 agent workspace 创建文件。** 使用 `/tmp/` 存放临时输出，`~/.agent-reach/` 存放持久数据。

## 详细文档

根据用户需求，阅读对应的详细文档：

- [搜索工具](references/search.md) — Exa AI 搜索
- [社交媒体](references/social.md) — 小红书, Twitter, B站, V2EX, Reddit
- [职场招聘](references/career.md) — LinkedIn
- [开发工具](references/dev.md) — GitHub CLI
- [网页阅读](references/web.md) — Jina Reader, RSS
- [视频播客](references/video.md) — YouTube, B站, 小宇宙

## 配置渠道

如果某个 channel 需要安装或配置，读取本地 [安装说明](references/install.md)。

用户只需提供 cookies，其他配置由 agent 完成。
