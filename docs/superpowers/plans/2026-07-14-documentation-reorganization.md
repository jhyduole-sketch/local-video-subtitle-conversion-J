# 项目文档整理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目文档整理为中文首页、完整中文指南、英文简版和中文更新记录，并用两张 Mermaid 图解释处理流程与系统结构。

**Architecture:** `README.md` 负责快速理解与启动，`docs/使用指南.md` 负责完整参考，`README.en.md` 提供英文辅助入口，`docs/更新记录.md` 汇总阶段性变化。现有详细技术更新文档继续保留，并由总更新记录链接。

**Tech Stack:** Markdown、GitHub Mermaid、Python CLI 命令示例。

## Global Constraints

- 中文是默认阅读路径，英文是辅助入口。
- 本次只调整文档，不改变程序功能。
- 不提交或推送 Git，等待用户后续明确指示。
- 所有功能描述和命令必须来自当前项目实现。

---

### Task 1: 建立完整中文使用指南

**Files:**
- Create: `docs/使用指南.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: 当前 `README.md` 中的安装、配置、Web、CLI、模型、输出和 FAQ 内容。
- Produces: 后续首页和英文简版可链接的中文权威参考。

- [x] **Step 1: 将当前 README 的详细内容迁移到中文使用指南**

保留有效命令和限制说明，新增返回项目首页、英文简版和更新记录的导航。

- [x] **Step 2: 检查关键章节完整性**

Run:

```bash
rg -n '^## (环境要求|启动图形界面|命令行用法|模型选择建议|输出目录|常见问题|当前限制)' docs/使用指南.md
```

Expected: 七个关键章节均存在。

### Task 2: 重写中文项目首页并加入图示

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `docs/使用指南.md`、当前功能列表和输出约定。
- Produces: 中文优先的项目入口、处理流程图、系统架构图和快速启动说明。

- [x] **Step 1: 重写首页信息层级**

顺序固定为：语言导航、项目介绍、核心能力、处理流程图、系统架构图、快速开始、典型使用方式、输出说明、更新摘要、文档导航、限制。

- [x] **Step 2: 加入两张 GitHub Mermaid 图**

处理流程图覆盖输入、字幕来源、转写、翻译、质量检查、输出和校对；架构图覆盖 Web/CLI、任务系统、媒体处理、模型、缓存和成品。

- [x] **Step 3: 检查首页没有失效的相对链接**

Run:

```bash
rg -n '\]\((README\.en\.md|docs/使用指南\.md|docs/更新记录\.md|docs/2026-07-13-performance-and-task-safety\.md)\)' README.md
```

Expected: 四类文档链接均出现。

### Task 3: 增加英文辅助入口和中文更新记录

**Files:**
- Create: `README.en.md`
- Create: `docs/更新记录.md`

**Interfaces:**
- Consumes: 中文首页、`git log` 和现有性能更新文档。
- Produces: 英文快速介绍与中文版本演进说明。

- [x] **Step 1: 编写英文简版**

包含 Overview、Features、Requirements、Quick Start、CLI Example、Outputs、Documentation 和 Limitations，并明确完整文档以中文指南为准。

- [x] **Step 2: 按阶段整理更新记录**

使用最近提交历史归纳性能安全、翻译可靠性、字幕校对、位置检测、通用下载、Web UI 等更新，不逐条复制 commit。

- [x] **Step 3: 检查语言入口互链**

Run:

```bash
rg -n 'README\.md|docs/使用指南\.md|docs/更新记录\.md' README.en.md docs/使用指南.md docs/更新记录.md
```

Expected: 每个辅助文档都能返回中文首页或进入其它主要文档。

### Task 4: 全局文档验证

**Files:**
- Verify: `README.md`
- Verify: `README.en.md`
- Verify: `docs/使用指南.md`
- Verify: `docs/更新记录.md`

**Interfaces:**
- Consumes: Tasks 1-3 的全部文档。
- Produces: 可交付但未提交的文档改动。

- [x] **Step 1: 检查 Markdown 空白错误**

Run:

```bash
git diff --check
```

Expected: 无输出，退出码为 0。

- [x] **Step 2: 检查 Mermaid 与关键命令**

Run:

```bash
rg -n '^```mermaid|python3 -m subtitle_tool\.(web|cli)' README.md README.en.md docs/使用指南.md
```

Expected: README 有两段 Mermaid，三份使用文档包含当前启动或 CLI 命令。

- [x] **Step 3: 检查文档改动范围**

Run:

```bash
git status --short
```

Expected: 仅出现本次文档和 `.superpowers/` 可视化会话文件；不包含源码改动。
