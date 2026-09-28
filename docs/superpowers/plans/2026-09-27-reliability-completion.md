# 本地字幕工具优化收尾 Implementation Plan

**Goal:** 完成八项代码评估优化并验证整合后的实际行为。
**Architecture:** Web 边界独立模块；字幕输入/来源/翻译通过兼容入口拆分；设置、缓存与预估模块保持独立。
**Tech Stack:** Python、unittest、SQLite、FFmpeg、vanilla JavaScript。
**Spec:** ../specs/2026-09-27-reliability-completion-design.md

## Global Constraints

保留用户未提交改动。用户已授权自行实现、自行测试、尽量不中断。原实施阶段不自动提交；用户于 2026-09-28 明确授权补充中英注释、完善文档并提交全部代码。远程推送和大模型下载不在本次授权范围。兼容 CLI/Web 常用流程。

## Review Focus

外部 outDir 与符号链接越界、请求伪造；中断上传/重复运行清理；取消不被翻译回退吞掉；音频短句和多语言来源误判；未知时长和损坏的历史估算文件。

## Tasks

- [x] 1. Web：先写实际 HTTP 边界回归测试；实现服务端目录登记、Host/Origin/令牌检查、上传限额与生命周期；运行 Web/上传测试。
- [x] 2. 来源与翻译：先写语言不匹配、手动低质量、取消与断点回退用例；实现来源/翻译策略并拆分输入准备；运行流水线相关测试。
- [x] 3. 设置/缓存/预估：先写非法设置、中段内容差异、未知时长和历史校准用例；实现模块；运行对应测试。
- [x] 4. 集成：接入历史预估与展示、安全认证页面、首次使用指导；运行全量测试、语法检查、真实视频烟测。
- [x] 5. 独立审查、修复重要问题、更新使用指南和验收记录。

## Execution Notes

采用当前工作区，避免遗漏当前未提交功能。按模块并行实施并由主实现者整合。最终以测试结果更新本文件。


## 验收结果（2026-09-28）

- 完整回归：`env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests`，283 项通过，0 失败。
- Python 编译检查、三个前端 JavaScript 文件语法检查、`git diff --check` 全部通过。
- 真实 FFmpeg 烟测生成短片和英文/日文双字幕轨，验证匹配日文轨、输出软字幕及二次任务复用来源缓存。
- 独立进程通过 `python -m subtitle_tool.web` 在临时工作目录启动，验证首页/静态资源、流式上传、下载任务、输入持久保留、上传临时文件清理；测试完成后服务和临时目录已清理。
- 两轮独立审查发现并修复：快速本地翻译批次取消/断点遗漏、内置字幕抽取中断缓存、空白输入路径绕过、上传保留失败与提交冲突时过早删除。

### 已确认的限制

- 本次未实际调用外部云端模型服务；回退、取消和断点通过受控模拟与实际本地批次循环验证。
- 正在执行的一次同步模型推理或 SDK 网络调用仍需等待该调用返回或超时；取消会阻止下一批次、等待及回退。
- 预估为经验区间与本机同类任务校准，不是统计置信区间。多个独立 CLI 进程同时写校准文件可能丢失一个最新样本，不影响字幕任务。
- 系统 Python 3.9 的现有 urllib3/LibreSSL、SWIG 依赖警告仍存在；测试全部通过，未在本次任务中替换用户 Python 环境。
- 提交范围包含原有未提交功能、本轮可靠性优化、测试及补充的中英注释和维护文档。用户已授权本地 Git 提交，远程推送另行处理。

### 实施路径

```mermaid
flowchart LR
    A[Web 目录与请求边界] --> B[上传生命周期与恢复]
    B --> C[字幕来源与翻译断点]
    C --> D[设置、指纹、历史预估]
    D --> E[模块拆分与页面集成]
    E --> F[独立审查与 283 项回归]
    F --> G[真实视频和 Web 进程烟测通过]
```

## 提交前收尾（2026-09-28） / Pre-commit completion

- 按用户要求为关键逻辑补充中文在前、英文在后的注释，新增双语开发维护文档和处理路径图。
- Added Chinese-first, English-second comments for critical logic, plus bilingual maintenance documentation and a processing diagram.
- 补充注释后重新完整回归：283 项测试，16.187 秒，全部通过；Python 编译、三个 JavaScript 语法检查及差异格式检查通过。
- After comment updates, all 283 tests passed in 16.187 seconds; Python compilation, syntax checks for three JavaScript files, and diff whitespace checks passed.
- 按用户授权，将全部功能、测试、注释和文档共同纳入本地提交。
- All features, tests, comments, and documentation are included in the local commit authorized by the user.
