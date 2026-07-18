# 阶段二与阶段三实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精简翻译与 Web 配置，并为 NLLB 增加自适应批次、断点保存和ETA。

**Architecture:** 新增翻译引擎目录和独立健康检查模块；前端语言数据独立加载。扩展 NLLB 批处理接口，使其接收已有翻译、批次回调并在内存不足时缩小批次。

**Tech Stack:** Python 3、`unittest`、Transformers/PyTorch、原生 HTML/JavaScript。

## Global Constraints

- 保持现有 CLI 参数与任务历史兼容。
- 不增加第三方依赖。
- 稳定优先，不并行执行多个本地大模型翻译。
- 本轮不提交或推送 GitHub。

---

### Task 1: 统一引擎配置与健康检查

**Files:**
- Create: `src/subtitle_tool/translation_engines.py`
- Create: `src/subtitle_tool/health.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/cli.py`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_translation_engines.py`
- Test: `tests/test_web.py`

- [x] 先写兼容别名、缓存身份和健康检查测试并确认失败。
- [x] 实现统一目录，提取健康检查并保留 `web.collect_health`兼容导出。
- [x] 运行相关测试并确认通过。

### Task 2: 精简前端配置

**Files:**
- Create: `src/subtitle_tool/web_assets/language_catalog.js`
- Modify: `src/subtitle_tool/web_assets/app.js`
- Modify: `src/subtitle_tool/web_assets/index.html`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_web.py`

- [x] 先写静态资源与高级设置结构测试并确认失败。
- [x] 提取语言目录，增加高级设置折叠区并允许服务静态资源。
- [x] 运行 Web 测试和 JavaScript 语法检查。

### Task 3: NLLB自适应批次和ETA

**Files:**
- Modify: `src/subtitle_tool/local_translate.py`
- Test: `tests/test_local_translate.py`

- [x] 先写默认批次、环境变量覆盖、内存不足减半和ETA日志测试。
- [x] 实现自适应批次与安全重试。
- [x] 运行本地翻译测试并确认通过。

### Task 4: NLLB批次级断点恢复

**Files:**
- Modify: `src/subtitle_tool/local_translate.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/translation_cache.py`
- Test: `tests/test_local_translate.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_translation_cache.py`

- [x] 先写已有字幕跳过、批次回调和兼容参数共享缓存测试。
- [x] 扩展翻译接口并在 Pipeline 中连接部分缓存。
- [x] 运行相关测试并确认通过。

### Task 5: 文档、回归与服务验证

**Files:**
- Modify: `README.md`
- Modify: `docs/使用指南.md`
- Modify: `docs/更新记录.md`

- [x] 更新阶段二、三说明和可调环境变量。
- [ ] 运行全量测试、编译、JavaScript检查和差异检查。
- [ ] 重启 `0.0.0.0:7860` 并验证健康接口。
