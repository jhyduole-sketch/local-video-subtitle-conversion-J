const form = document.querySelector("#jobForm");
const runButton = document.querySelector("#runButton");
const stopButton = document.querySelector("#stopButton");
const copyLogButton = document.querySelector("#copyLogButton");
const refreshHealth = document.querySelector("#refreshHealth");
const healthList = document.querySelector("#healthList");
const healthSummary = document.querySelector("#healthSummary");
const jobBadge = document.querySelector("#jobBadge");
const activeJobId = document.querySelector("#activeJobId");
const logBox = document.querySelector("#logBox");
const results = document.querySelector("#results");
const resultSummary = document.querySelector("#resultSummary");
const resultsPanel = document.querySelector(".results-panel");
const targetLangsInput = document.querySelector("#targetLangs");
const languagePicker = document.querySelector("#languagePicker");
const languagePickerToggle = document.querySelector("#languagePickerToggle");
const languagePickerPanel = document.querySelector("#languagePickerPanel");
const languagePickerHint = document.querySelector("#languagePickerHint");
const clearLanguagesButton = document.querySelector("#clearLanguagesButton");
const translatorSelect = document.querySelector("#translator");
const progressBar = document.querySelector("#progressBar");
const progressMessage = document.querySelector("#progressMessage");
const progressPercent = document.querySelector("#progressPercent");
const videoFileInput = document.querySelector("#videoFile");
const whisperPreset = document.querySelector("#whisperPreset");
const whisperModelInput = document.querySelector("#whisperModel");
const cacheSummaryLabel = document.querySelector("#cacheSummary");
const cacheList = document.querySelector("#cacheList");
const refreshCacheButton = document.querySelector("#refreshCacheButton");
const clearAllCacheButton = document.querySelector("#clearAllCacheButton");
const historyList = document.querySelector("#historyList");
const refreshHistoryButton = document.querySelector("#refreshHistoryButton");
const clearHistoryButton = document.querySelector("#clearHistoryButton");
const subtitleVideoMode = document.querySelector("#subtitleVideoMode");
const subtitleEncodingProfile = document.querySelector("#subtitleEncodingProfile");
const subtitlePosition = document.querySelector("#subtitlePosition");
const subtitleVideoModeHint = document.querySelector("#subtitleVideoModeHint");
const subtitleEncodingHint = document.querySelector("#subtitleEncodingHint");
const avoidSubtitleOverlap = document.querySelector("#avoidSubtitleOverlap");
const subtitleEditorDialog = document.querySelector("#subtitleEditorDialog");
const subtitleEditorPath = document.querySelector("#subtitleEditorPath");
const subtitleEditorRows = document.querySelector("#subtitleEditorRows");
const subtitleEditorMessage = document.querySelector("#subtitleEditorMessage");
const closeSubtitleEditorButton = document.querySelector("#closeSubtitleEditorButton");
const saveSubtitleButton = document.querySelector("#saveSubtitleButton");
const saveRenderSubtitleButton = document.querySelector("#saveRenderSubtitleButton");
const subtitlePreviewPane = document.querySelector("#subtitlePreviewPane");
const subtitlePreviewVideo = document.querySelector("#subtitlePreviewVideo");
const subtitlePreviewOverlay = document.querySelector("#subtitlePreviewOverlay");
const subtitlePreviewPosition = document.querySelector("#subtitlePreviewPosition");
const subtitlePreviewTime = document.querySelector("#subtitlePreviewTime");
const confirmationDialog = document.querySelector("#confirmationDialog");
const confirmationTitle = document.querySelector("#confirmationTitle");
const confirmationMessage = document.querySelector("#confirmationMessage");
const confirmationSafetyNote = document.querySelector("#confirmationSafetyNote");
const cancelConfirmationButton = document.querySelector("#cancelConfirmationButton");
const confirmActionButton = document.querySelector("#confirmActionButton");
const whisperModelPaths = {
  base: "models/ggml-base.bin",
  small: "models/ggml-small.bin",
  medium: "models/ggml-medium.bin",
};
const cloudLanguages = [
  ["zh-CN", "中文"],
  ["zh-TW", "繁中"],
  ["en", "英语"],
  ["ja", "日语"],
  ["ko", "韩语"],
  ["fr", "法语"],
  ["de", "德语"],
  ["es", "西班牙语"],
  ["pt", "葡萄牙语"],
  ["it", "意大利语"],
  ["ru", "俄语"],
  ["ar", "阿拉伯语"],
  ["th", "泰语"],
  ["vi", "越南语"],
  ["id", "印尼语"],
  ["tr", "土耳其语"],
  ["nl", "荷兰语"],
  ["pl", "波兰语"],
  ["uk", "乌克兰语"],
  ["hi", "印地语"],
  ["ms", "马来语"],
  ["sv", "瑞典语"],
  ["el", "希腊语"],
  ["he", "希伯来语"],
  ["fa", "波斯语"],
  ["cs", "捷克语"],
  ["ro", "罗马尼亚语"],
  ["hu", "匈牙利语"],
  ["fi", "芬兰语"],
  ["da", "丹麦语"],
  ["no", "挪威语"],
  ["sk", "斯洛伐克语"],
  ["bg", "保加利亚语"],
  ["hr", "克罗地亚语"],
  ["sr", "塞尔维亚语"],
  ["sl", "斯洛文尼亚语"],
  ["lt", "立陶宛语"],
  ["lv", "拉脱维亚语"],
  ["et", "爱沙尼亚语"],
  ["bn", "孟加拉语"],
  ["ur", "乌尔都语"],
  ["ta", "泰米尔语"],
  ["te", "泰卢固语"],
  ["sw", "斯瓦希里语"],
];
const fastLocalLanguages = [
  ["zh-CN", "中文"],
  ["ja", "日语"],
  ["en", "英语"],
];
const nllbLanguages = [
  ["zh-CN", "中文"],
  ["zh-TW", "繁中"],
  ["en", "英语"],
  ["ja", "日语"],
  ["ko", "韩语"],
  ["fr", "法语"],
  ["de", "德语"],
  ["es", "西班牙语"],
  ["pt", "葡萄牙语"],
  ["it", "意大利语"],
  ["ru", "俄语"],
  ["ar", "阿拉伯语"],
  ["th", "泰语"],
  ["vi", "越南语"],
  ["id", "印尼语"],
];
const languagePickerModes = {
  "local-transformer": {
    languages: fastLocalLanguages,
    allowCustom: false,
    hint: "本地快速模型只建议选择中文、日语、英语；更多语言请切换 z.ai、OpenAI 或 NLLB。",
  },
  "local-nllb": {
    languages: nllbLanguages,
    allowCustom: false,
    hint: "旧任务兼容模式，实际使用 NLLB 1.3B；异常字幕会自动单句重试。",
  },
  "local-nllb-quality": {
    languages: nllbLanguages,
    allowCustom: false,
    hint: "NLLB 1.3B 覆盖更多本地语言，质量优先；异常字幕会自动单句重试。",
  },
  "z-ai": {
    languages: cloudLanguages,
    allowCustom: true,
    hint: "z.ai 适合多语言翻译；快捷按钮只是常用语言，也可以在输入框手动填其它语言代码。",
  },
  openai: {
    languages: cloudLanguages,
    allowCustom: true,
    hint: "OpenAI 适合多语言高质量翻译；快捷按钮只是常用语言，也可以在输入框手动填其它语言代码。",
  },
};
let pollTimer = null;
let elapsedTimer = null;
let activeJob = null;
let currentJobId = "";
let submitInFlight = false;
let copyLogResetTimer = null;
let editingSubtitlePath = "";
let editingVideoPath = "";
let lastResult = null;
let confirmationResolver = null;

const cacheCategoryLabels = {
  videos: "视频",
  audio: "音频",
  sourceSubtitles: "内置字幕",
  transcripts: "语音转写",
  translations: "字幕翻译",
  analysis: "画面字幕检测",
};

refreshHealth.addEventListener("click", loadHealth);
stopButton.addEventListener("click", cancelCurrentJob);
copyLogButton.addEventListener("click", copyCurrentLog);
form.addEventListener("submit", submitJob);
targetLangsInput.addEventListener("input", renderLanguagePicker);
languagePickerToggle.addEventListener("click", toggleLanguagePickerPanel);
clearLanguagesButton.addEventListener("click", clearLanguageSelection);
document.addEventListener("click", closeLanguagePickerOnOutsideClick);
document.addEventListener("keydown", closeLanguagePickerOnEscape);
translatorSelect.addEventListener("change", handleTranslatorChange);
whisperPreset.addEventListener("change", applyWhisperPreset);
whisperModelInput.addEventListener("input", syncWhisperPreset);
refreshCacheButton.addEventListener("click", loadCache);
clearAllCacheButton.addEventListener("click", clearAllCache);
refreshHistoryButton.addEventListener("click", loadHistory);
clearHistoryButton.addEventListener("click", clearHistory);
subtitleVideoMode.addEventListener("change", handleSubtitleVideoModeChange);
subtitleEncodingProfile.addEventListener("change", updateSubtitleEncodingHint);
avoidSubtitleOverlap.addEventListener("change", handleAvoidOverlapChange);
closeSubtitleEditorButton.addEventListener("click", closeSubtitleEditor);
saveSubtitleButton.addEventListener("click", () => saveEditedSubtitles(false));
saveRenderSubtitleButton.addEventListener("click", () => saveEditedSubtitles(true));
subtitlePreviewVideo.addEventListener("timeupdate", syncSubtitlePreview);
subtitlePreviewVideo.addEventListener("loadedmetadata", syncSubtitlePreview);
subtitlePreviewVideo.addEventListener("error", handleSubtitlePreviewError);
subtitlePreviewPosition.addEventListener("change", updateSubtitlePreviewPosition);
subtitleEditorRows.addEventListener("click", handleSubtitleRowClick);
subtitleEditorRows.addEventListener("input", syncSubtitlePreview);
subtitleEditorDialog.addEventListener("close", releaseSubtitlePreview);
cancelConfirmationButton.addEventListener("click", () => closeConfirmationDialog(false));
confirmActionButton.addEventListener("click", () => closeConfirmationDialog(true));
confirmationDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeConfirmationDialog(false);
});

loadHealth();
loadCache();
loadHistory();
renderLanguagePicker();
syncWhisperPreset();
updateSubtitleVideoModeHint();
updateSubtitleEncodingHint();

function updateSubtitleVideoModeHint() {
  subtitleVideoModeHint.textContent = subtitleVideoMode.value === "hard"
    ? "固定位置并在各播放器一致显示；需要重新编码视频，处理时间更长。"
    : "软字幕可开关并保持原视频流，但具体位置由播放器控制。";
}

function updateSubtitleEncodingHint() {
  const hints = {
    auto: "自动模式优先使用 Apple 硬件编码，失败时切换快速 CPU。",
    hardware: "优先使用 Apple VideoToolbox；不可用或失败时自动切换快速 CPU。",
    fast: "使用 libx264 veryfast，兼容性好，速度明显快于高画质模式。",
    quality: "使用 libx264 medium / CRF 18，画质优先，4K 60fps 视频会很慢。",
  };
  subtitleEncodingHint.textContent = hints[subtitleEncodingProfile.value] || hints.auto;
}

function handleSubtitleVideoModeChange() {
  if (subtitleVideoMode.value === "soft") {
    avoidSubtitleOverlap.checked = false;
  }
  updateSubtitleVideoModeHint();
}

function handleAvoidOverlapChange() {
  if (avoidSubtitleOverlap.checked) {
    subtitleVideoMode.value = "hard";
  }
  updateSubtitleVideoModeHint();
}

async function loadHealth() {
  healthSummary.textContent = "检查中";
  healthSummary.className = "badge";
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    renderHealth(data);
  } catch (error) {
    healthSummary.textContent = "失败";
    healthSummary.className = "badge bad";
    healthList.innerHTML = `<div class="check-row"><span class="check-dot"></span><div><div class="check-name">无法连接服务</div><div class="check-detail">${escapeHtml(error.message)}</div></div></div>`;
  }
}

async function submitJob(event) {
  event.preventDefault();
  if (submitInFlight || runButton.disabled) return;
  submitInFlight = true;
  const payload = formPayload();
  setRunningState(true);
  updateProgress(0, "提交任务");
  clearResults();
  logBox.textContent = "提交任务...";
  try {
    if (videoFileInput.files.length > 0) {
      updateProgress(0, "上传本地视频");
      logBox.textContent = "上传本地视频...";
      const upload = await uploadVideo(videoFileInput.files[0]);
      payload.input = upload.path;
      logBox.textContent = `已上传: ${upload.filename}\n提交任务...`;
    }
    if (!payload.input) {
      throw new Error("请输入视频地址/本地路径，或上传一个本地视频。");
    }
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      if (data.activeJob) {
        adoptActiveJob(data.activeJob);
        logBox.textContent = `${data.error || "已有任务正在运行"}\n已切换到当前任务。`;
        return;
      }
      throw new Error(data.error || "任务提交失败");
    }
    currentJobId = data.jobId;
    activeJobId.textContent = data.jobId;
    setRunningState(true, "运行中", "running");
    startElapsedTimer({ id: data.jobId, createdAt: Date.now() / 1000, elapsedSeconds: 0 });
    pollJob(data.jobId);
  } catch (error) {
    setRunningState(false, "失败", "bad");
    stopElapsedTimer();
    logBox.textContent = error.message;
  } finally {
    submitInFlight = false;
  }
}

async function cancelCurrentJob() {
  if (!currentJobId || stopButton.disabled) return;
  setRunningState(true, "取消中", "warn");
  stopButton.disabled = true;
  updateProgress(progressPercent.textContent.replace("%", ""), "正在停止");
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(currentJobId)}/cancel`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "停止任务失败");
    }
    if (data.job) {
      renderJob(data.job);
    }
  } catch (error) {
    logBox.textContent += `\n停止失败: ${error.message}`;
    stopButton.disabled = false;
  }
}

async function uploadVideo(file) {
  const data = new FormData();
  data.append("video", file);
  const response = await fetch("/api/upload", {
    method: "POST",
    body: data,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "视频上传失败");
  }
  return payload;
}

function formPayload() {
  const data = new FormData(form);
  return {
    input: String(data.get("input") || "").trim(),
    sourceLang: String(data.get("sourceLang") || "").trim(),
    targetLangs: String(data.get("targetLangs") || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    source: data.get("source"),
    transcriber: data.get("transcriber"),
    translator: data.get("translator"),
    outDir: String(data.get("outDir") || "output").trim(),
    whisperModel: String(data.get("whisperModel") || "").trim(),
    whisperUseGpu: Boolean(data.get("whisperUseGpu")),
    whisperUseVad: Boolean(data.get("whisperUseVad")),
    whisperVadModel: String(data.get("whisperVadModel") || "").trim(),
    embedSubtitles: Boolean(data.get("embedSubtitles")),
    avoidSubtitleOverlap: Boolean(data.get("avoidSubtitleOverlap")),
    subtitleVideoMode: String(data.get("subtitleVideoMode") || "soft"),
    subtitleEncodingProfile: String(data.get("subtitleEncodingProfile") || "auto"),
    subtitlePosition: String(data.get("subtitlePosition") || "auto"),
    forceDownload: Boolean(data.get("forceDownload")),
    downloadOnly: Boolean(data.get("downloadOnly")),
  };
}

function applyWhisperPreset() {
  const path = whisperModelPaths[whisperPreset.value];
  if (path) {
    whisperModelInput.value = path;
  }
}

function syncWhisperPreset() {
  const currentPath = whisperModelInput.value.trim();
  const matched = Object.entries(whisperModelPaths).find(([, path]) => path === currentPath);
  whisperPreset.value = matched ? matched[0] : "custom";
}

function toggleLanguage(language) {
  if (!language) return;
  const values = selectedTargetLangs();
  if (values.includes(language)) {
    targetLangsInput.value = values.filter((item) => item !== language).join(", ");
  } else {
    targetLangsInput.value = [...values, language].join(", ");
  }
  renderLanguagePicker();
}

function clearLanguageSelection() {
  targetLangsInput.value = "";
  renderLanguagePicker();
}

function selectedTargetLangs() {
  return targetLangsInput.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function syncLanguageButtons() {
  const selected = new Set(selectedTargetLangs());
  languagePicker.querySelectorAll("[data-lang]").forEach((checkbox) => {
    checkbox.checked = selected.has(checkbox.dataset.lang);
  });
  updateLanguagePickerSummary(selected);
}

function renderLanguagePicker() {
  const mode = languagePickerModes[translatorSelect.value] || languagePickerModes["z-ai"];
  const builtInLanguages = new Set(mode.languages.map(([language]) => language));
  const customLanguages = mode.allowCustom
    ? selectedTargetLangs()
        .filter((language) => !builtInLanguages.has(language))
        .map((language) => [language, `${language}（手动输入）`])
    : [];
  const languages = [...mode.languages, ...customLanguages];
  languagePicker.innerHTML = languages
    .map(
      ([language, label]) =>
        `<label class="language-option">
          <input type="checkbox" data-lang="${escapeAttribute(language)}" />
          <span>${escapeHtml(label)}</span>
          <code>${escapeHtml(language)}</code>
        </label>`,
    )
    .join("");
  languagePickerHint.textContent = mode.hint;
  languagePicker.querySelectorAll("[data-lang]").forEach((button) => {
    button.addEventListener("change", () => toggleLanguage(button.dataset.lang || ""));
  });
  syncLanguageButtons();
}

function handleTranslatorChange() {
  const mode = languagePickerModes[translatorSelect.value] || languagePickerModes["z-ai"];
  if (!mode.allowCustom) {
    const supported = new Set(mode.languages.map(([language]) => language));
    const filtered = selectedTargetLangs().filter((language) => supported.has(language));
    targetLangsInput.value = filtered.join(", ");
  }
  renderLanguagePicker();
}

function toggleLanguagePickerPanel() {
  const isOpen = languagePickerToggle.getAttribute("aria-expanded") === "true";
  setLanguagePickerOpen(!isOpen);
}

function setLanguagePickerOpen(isOpen) {
  languagePickerToggle.setAttribute("aria-expanded", String(isOpen));
  languagePickerPanel.hidden = !isOpen;
}

function closeLanguagePickerOnOutsideClick(event) {
  if (languagePickerPanel.hidden) return;
  if (event.target.closest(".language-dropdown")) return;
  setLanguagePickerOpen(false);
}

function closeLanguagePickerOnEscape(event) {
  if (event.key === "Escape") {
    setLanguagePickerOpen(false);
  }
}

function updateLanguagePickerSummary(selected) {
  const mode = languagePickerModes[translatorSelect.value] || languagePickerModes["z-ai"];
  const labelByLanguage = new Map(mode.languages);
  const selectedValues = selectedTargetLangs();
  const labels = selectedValues.map((language) => labelByLanguage.get(language) || language);
  if (!selected.size) {
    languagePickerToggle.textContent = "选择常用语言";
    return;
  }
  const visibleLabels = labels.slice(0, 3).join("、");
  const extraCount = Math.max(0, labels.length - 3);
  languagePickerToggle.textContent =
    extraCount > 0 ? `${visibleLabels} +${extraCount}` : visibleLabels;
}

async function pollJob(jobId) {
  window.clearTimeout(pollTimer);
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "任务读取失败");
    }
    renderJob(data);
    if (data.status === "running" || data.status === "queued" || data.status === "canceling") {
      pollTimer = window.setTimeout(() => pollJob(jobId), 1500);
    } else {
      setRunningState(false, statusLabel(data.status), statusTone(data.status));
      currentJobId = "";
      stopElapsedTimer();
      if (data.result) {
        renderResults(data.result);
        resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      loadHistory();
      loadCache();
    }
  } catch (error) {
    setRunningState(true, "连接重试", "warn");
    logBox.textContent += `\n状态读取失败，稍后重试: ${error.message}`;
    pollTimer = window.setTimeout(() => pollJob(jobId), 3000);
  }
}

function renderHealth(data) {
  const checks = Array.isArray(data.checks) ? data.checks : [];
  healthSummary.textContent = data.ok ? "可用" : "需处理";
  healthSummary.className = data.ok ? "badge ok" : "badge warn";
  healthList.innerHTML = checks
    .map(
      (check) => `
        <div class="check-row">
          <span class="check-dot ${check.ok ? "ok" : ""}"></span>
          <div>
            <div class="check-name">${escapeHtml(check.name)}</div>
            <div class="check-detail">${escapeHtml(check.detail)}</div>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderJob(job) {
  activeJob = job;
  renderElapsed();
  setRunningState(
    job.status === "running" || job.status === "queued" || job.status === "canceling",
    statusLabel(job.status),
    statusTone(job.status),
  );
  if (job.status === "canceling") {
    stopButton.disabled = true;
  }
  updateProgress(job.progress || 0, job.progressMessage || statusLabel(job.status));
  const lines = Array.isArray(job.logs) ? job.logs : [];
  logBox.textContent = lines.length ? lines.join("\n") : "等待日志";
  if (job.error) {
    logBox.textContent += `\n${job.error}`;
  }
  logBox.scrollTop = logBox.scrollHeight;
}

function renderResults(result) {
  lastResult = result;
  const items = [];
  if (result.downloadedVideoPath) {
    items.push(["下载视频", result.downloadedVideoPath]);
  }
  if (result.sourceSubtitlePath) {
    items.push([`源字幕 (${result.sourceKind || "source"})`, result.sourceSubtitlePath]);
  }
  Object.entries(result.translatedPaths || {}).forEach(([lang, path]) => {
    const engine = result.translationEngines?.[lang];
    items.push([`字幕 ${lang}${engine ? ` · ${engine}` : ""}`, path, "edit"]);
  });
  Object.entries(result.subtitledVideoPaths || {}).forEach(([lang, path]) => {
    const engine = result.translationEngines?.[lang];
    const videoKind = path.endsWith(".fixed-sub.mp4") ? "稳定硬字幕视频" : "软字幕视频";
    items.push([`${videoKind} ${lang}${engine ? ` · ${engine}` : ""}`, path]);
  });
  Object.entries(result.failedLanguages || {}).forEach(([lang, message]) => {
    items.push([`失败 ${lang}`, message]);
  });
  resultSummary.textContent = items.length ? `${items.length} 个结果` : "暂无结果";
  results.innerHTML = items.map(([kind, path, action]) => resultItem(kind, path, action)).join("");
  results.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyText(button.dataset.copy || ""));
  });
  results.querySelectorAll("[data-edit-subtitle]").forEach((button) => {
    button.addEventListener("click", () => openSubtitleEditor(button.dataset.editSubtitle || ""));
  });
}

async function openSubtitleEditor(path) {
  if (!path) return;
  editingSubtitlePath = path;
  editingVideoPath = String(lastResult?.inputVideoPath || lastResult?.downloadedVideoPath || "");
  subtitleEditorPath.textContent = path;
  subtitleEditorMessage.textContent = "读取字幕...";
  subtitleEditorRows.innerHTML = "";
  configureSubtitlePreview();
  subtitleEditorDialog.showModal();
  try {
    const outDir = String(document.querySelector("#outDir").value || "output").trim();
    const response = await fetch(`/api/subtitles?outDir=${encodeURIComponent(outDir)}&path=${encodeURIComponent(path)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "字幕读取失败");
    subtitleEditorRows.innerHTML = data.segments.map(subtitleEditorRow).join("");
    subtitleEditorMessage.textContent = `${data.segments.length} 条字幕`;
    saveRenderSubtitleButton.disabled = !editingVideoPath;
    syncSubtitlePreview();
  } catch (error) {
    subtitleEditorMessage.textContent = error.message;
  }
}

function configureSubtitlePreview() {
  const selectedPosition = subtitlePosition.value === "auto" ? "above-bottom" : subtitlePosition.value;
  subtitlePreviewPosition.value = selectedPosition;
  updateSubtitlePreviewPosition();
  subtitlePreviewOverlay.hidden = true;
  subtitlePreviewTime.textContent = "00:00 / 00:00";
  subtitlePreviewPane.hidden = !editingVideoPath;
  if (!editingVideoPath) return;
  const outDir = String(document.querySelector("#outDir").value || "output").trim();
  subtitlePreviewVideo.src = `/api/media?outDir=${encodeURIComponent(outDir)}&path=${encodeURIComponent(editingVideoPath)}`;
  subtitlePreviewVideo.load();
}

function closeSubtitleEditor() {
  subtitleEditorDialog.close();
}

function releaseSubtitlePreview() {
  subtitlePreviewVideo.pause();
  subtitlePreviewVideo.removeAttribute("src");
  subtitlePreviewVideo.load();
  subtitlePreviewOverlay.hidden = true;
}

function handleSubtitlePreviewError() {
  if (!editingVideoPath) return;
  subtitleEditorMessage.textContent = "浏览器无法播放该视频格式，但仍可编辑字幕并重新生成视频";
}

function updateSubtitlePreviewPosition() {
  subtitlePreviewOverlay.className = `subtitle-preview-overlay ${subtitlePreviewPosition.value}`;
}

function handleSubtitleRowClick(event) {
  if (event.target.closest("input, textarea")) return;
  const row = event.target.closest(".subtitle-edit-row");
  if (!row || !editingVideoPath) return;
  const startMs = parseSubtitleTimestamp(row.querySelector("[data-subtitle-start]").value);
  if (startMs === null) return;
  subtitlePreviewVideo.currentTime = startMs / 1000;
  renderSubtitlePreviewRow(row);
}

function syncSubtitlePreview() {
  const currentMs = Math.round((subtitlePreviewVideo.currentTime || 0) * 1000);
  const duration = Number.isFinite(subtitlePreviewVideo.duration) ? subtitlePreviewVideo.duration : 0;
  subtitlePreviewTime.textContent = `${formatPreviewTime(currentMs / 1000)} / ${formatPreviewTime(duration)}`;
  const row = Array.from(subtitleEditorRows.querySelectorAll(".subtitle-edit-row")).find((item) => {
    const start = parseSubtitleTimestamp(item.querySelector("[data-subtitle-start]").value);
    const end = parseSubtitleTimestamp(item.querySelector("[data-subtitle-end]").value);
    return start !== null && end !== null && currentMs >= start && currentMs < end;
  });
  renderSubtitlePreviewRow(row || null);
}

function renderSubtitlePreviewRow(row) {
  subtitleEditorRows.querySelectorAll(".subtitle-edit-row.is-active").forEach((item) => {
    item.classList.remove("is-active");
  });
  const text = row?.querySelector("[data-subtitle-text]")?.value.trim() || "";
  if (row) row.classList.add("is-active");
  subtitlePreviewOverlay.textContent = text;
  subtitlePreviewOverlay.hidden = !text;
}

function parseSubtitleTimestamp(value) {
  const match = String(value || "").trim().match(/^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/);
  if (!match) return null;
  const [, hours, minutes, seconds, milliseconds] = match.map(Number);
  if (minutes > 59 || seconds > 59) return null;
  return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds;
}

function formatPreviewTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function subtitleEditorRow(segment) {
  return `
    <div class="subtitle-edit-row">
      <span class="subtitle-edit-index">${Number(segment.index) || ""}</span>
      <input data-subtitle-start value="${escapeAttribute(segment.start || "")}" aria-label="开始时间" />
      <input data-subtitle-end value="${escapeAttribute(segment.end || "")}" aria-label="结束时间" />
      <textarea data-subtitle-text rows="2" aria-label="字幕文字">${escapeHtml(segment.text || "")}</textarea>
    </div>
  `;
}

function collectEditedSegments() {
  return Array.from(subtitleEditorRows.querySelectorAll(".subtitle-edit-row")).map((row) => ({
    start: row.querySelector("[data-subtitle-start]").value.trim(),
    end: row.querySelector("[data-subtitle-end]").value.trim(),
    text: row.querySelector("[data-subtitle-text]").value.trim(),
  }));
}

async function saveEditedSubtitles(regenerate) {
  const outDir = String(document.querySelector("#outDir").value || "output").trim();
  subtitleEditorMessage.textContent = "保存字幕...";
  saveSubtitleButton.disabled = true;
  saveRenderSubtitleButton.disabled = true;
  try {
    const response = await fetch("/api/subtitles", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({outDir, path: editingSubtitlePath, segments: collectEditedSegments()}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "字幕保存失败");
    subtitleEditorMessage.textContent = `已保存 ${data.count} 条字幕，原文件已备份`;
    if (regenerate) {
      if (!editingVideoPath) throw new Error("当前任务没有可用于重新生成的视频路径");
      const selectedPosition = subtitlePreviewPosition.value;
      const renderResponse = await fetch("/api/subtitles/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          outDir,
          videoPath: editingVideoPath,
          subtitlePath: editingSubtitlePath,
          mode: subtitleVideoMode.value,
          position: selectedPosition,
          encodingProfile: subtitleEncodingProfile.value,
        }),
      });
      const renderData = await renderResponse.json();
      if (!renderResponse.ok) throw new Error(renderData.error || "重新生成任务提交失败");
      subtitleEditorDialog.close();
      currentJobId = renderData.jobId;
      activeJobId.textContent = renderData.jobId;
      setRunningState(true, "排队", "running");
      startElapsedTimer({id: renderData.jobId, createdAt: Date.now() / 1000, elapsedSeconds: 0});
      pollJob(renderData.jobId);
    }
  } catch (error) {
    subtitleEditorMessage.textContent = error.message;
  } finally {
    saveSubtitleButton.disabled = false;
    saveRenderSubtitleButton.disabled = !editingVideoPath;
  }
}

async function loadCache() {
  const outDir = String(document.querySelector("#outDir").value || "output").trim();
  try {
    const response = await fetch(`/api/cache?outDir=${encodeURIComponent(outDir)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "缓存读取失败");
    renderCache(data);
  } catch (error) {
    cacheSummaryLabel.textContent = "读取失败";
    cacheList.innerHTML = `<div class="empty-row">${escapeHtml(error.message)}</div>`;
  }
}

function renderCache(data) {
  cacheSummaryLabel.textContent = formatBytes(data.totalBytes || 0);
  cacheList.innerHTML = Object.entries(data.categories || {})
    .map(([category, detail]) => `
      <div class="data-row">
        <div class="row-main">
          <strong>${escapeHtml(cacheCategoryLabels[category] || category)}</strong>
          <span>${detail.files || 0} 个文件 · ${formatBytes(detail.bytes || 0)}</span>
        </div>
        <button class="small-button" type="button" data-clear-cache="${escapeAttribute(category)}">清理</button>
      </div>
    `)
    .join("");
  cacheList.querySelectorAll("[data-clear-cache]").forEach((button) => {
    button.addEventListener("click", () => clearCacheCategory(button.dataset.clearCache));
  });
}

async function clearCacheCategory(category) {
  if (!category) return;
  const label = cacheCategoryLabels[category] || category;
  const confirmed = await openConfirmationDialog({
    title: `清理${label}缓存？`,
    message: `将删除当前保存的${label}缓存。`,
    safetyNote: "不会删除 output 中生成的视频、字幕或任务历史。下次处理时可能需要重新生成这些缓存。",
  });
  if (!confirmed) return;
  const outDir = String(document.querySelector("#outDir").value || "output").trim();
  try {
    const response = await fetch("/api/cache/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outDir, categories: [category] }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "清理失败");
    renderCache(data);
  } catch (error) {
    cacheSummaryLabel.textContent = error.message;
  }
}

async function clearAllCache() {
  const confirmed = await openConfirmationDialog({
    title: "清空全部缓存？",
    message: "将删除视频、音频、内置字幕、语音转写、字幕翻译和画面分析缓存。",
    safetyNote: "不会删除 output 中生成的视频、字幕或任务历史。下次任务可能需要重新下载、转写和翻译。",
  });
  if (!confirmed) return;
  clearAllCacheButton.disabled = true;
  clearAllCacheButton.textContent = "清理中";
  const outDir = String(document.querySelector("#outDir").value || "output").trim();
  try {
    const response = await fetch("/api/cache/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outDir, categories: Object.keys(cacheCategoryLabels) }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "清理失败");
    renderCache(data);
  } catch (error) {
    cacheSummaryLabel.textContent = error.message;
  } finally {
    clearAllCacheButton.disabled = false;
    clearAllCacheButton.textContent = "清空全部";
  }
}

async function loadHistory() {
  try {
    const response = await fetch("/api/jobs");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "历史读取失败");
    renderHistory(Array.isArray(data.jobs) ? data.jobs : []);
    if (data.activeJob) {
      adoptActiveJob(data.activeJob);
    } else if (!currentJobId) {
      setRunningState(false, "空闲", "idle");
    }
  } catch (error) {
    historyList.innerHTML = `<div class="empty-row">${escapeHtml(error.message)}</div>`;
  }
}

function renderHistory(jobs) {
  if (!jobs.length) {
    historyList.innerHTML = `<div class="empty-row">暂无历史任务</div>`;
    return;
  }
  historyList.innerHTML = jobs
    .map((job) => {
      const canResume = ["failed", "canceled", "interrupted"].includes(job.status);
      return `
        <div class="data-row">
          <div class="row-main">
            <strong>${escapeHtml(statusLabel(job.status))} · ${escapeHtml(job.id)}</strong>
            <span>${escapeHtml(formatJobTime(job.createdAt))} · ${job.progress || 0}%</span>
          </div>
          <div class="row-actions">
            <button class="small-button" type="button" data-view-job="${escapeAttribute(job.id)}">查看</button>
            ${canResume ? `<button class="small-button" type="button" data-resume-job="${escapeAttribute(job.id)}">继续</button>` : ""}
          </div>
        </div>
      `;
    })
    .join("");
  historyList.querySelectorAll("[data-view-job]").forEach((button) => {
    button.addEventListener("click", () => viewHistoryJob(button.dataset.viewJob));
  });
  historyList.querySelectorAll("[data-resume-job]").forEach((button) => {
    button.addEventListener("click", () => resumeHistoryJob(button.dataset.resumeJob));
  });
}

async function clearHistory() {
  const confirmed = await openConfirmationDialog({
    title: "清空任务历史？",
    message: "将删除所有已完成、失败、停止和中断的任务记录。",
    safetyNote: "不会删除 output 中生成的视频、字幕或任何缓存；正在排队和运行的任务会保留。",
  });
  if (!confirmed) return;
  clearHistoryButton.disabled = true;
  clearHistoryButton.textContent = "清理中";
  try {
    const response = await fetch("/api/jobs/clear", { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "历史清理失败");
    await loadHistory();
  } catch (error) {
    historyList.innerHTML = `<div class="empty-row">${escapeHtml(error.message)}</div>`;
  } finally {
    clearHistoryButton.disabled = false;
    clearHistoryButton.textContent = "清空历史";
  }
}

function openConfirmationDialog({ title, message, safetyNote, confirmLabel = "确认清空" }) {
  if (confirmationResolver) closeConfirmationDialog(false);
  confirmationTitle.textContent = title;
  confirmationMessage.textContent = message;
  confirmationSafetyNote.textContent = safetyNote;
  confirmActionButton.textContent = confirmLabel;
  confirmationDialog.showModal();
  return new Promise((resolve) => {
    confirmationResolver = resolve;
  });
}

function closeConfirmationDialog(confirmed) {
  const resolve = confirmationResolver;
  confirmationResolver = null;
  if (confirmationDialog.open) confirmationDialog.close();
  if (resolve) resolve(confirmed);
}

async function viewHistoryJob(jobId) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
  const job = await response.json();
  if (!response.ok) return;
  renderJob(job);
  if (job.result) renderResults(job.result);
}

async function resumeHistoryJob(jobId) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
  const data = await response.json();
  if (!response.ok) {
    if (data.activeJob) adoptActiveJob(data.activeJob);
    return;
  }
  currentJobId = data.jobId;
  activeJobId.textContent = data.jobId;
  setRunningState(true, "排队", "running");
  startElapsedTimer({ id: data.jobId, createdAt: Date.now() / 1000, elapsedSeconds: 0 });
  pollJob(data.jobId);
  loadHistory();
}

function adoptActiveJob(job) {
  if (!job || !job.id) return;
  const changedJob = currentJobId !== job.id;
  currentJobId = job.id;
  activeJobId.textContent = job.id;
  renderJob(job);
  startElapsedTimer(job);
  if (changedJob) pollJob(job.id);
}

function resultItem(kind, path, action = "") {
  const safePath = escapeHtml(path);
  return `
    <article class="result-item">
      <div class="result-kind">${escapeHtml(kind)}</div>
      <div class="result-path">${safePath}</div>
      <div class="row-actions">
        ${action === "edit" ? `<button class="preview-subtitle-button" type="button" data-edit-subtitle="${escapeAttribute(path)}">预览并校对字幕</button>` : ""}
        <button class="copy-button" type="button" data-copy="${escapeAttribute(path)}">复制路径</button>
      </div>
    </article>
  `;
}

function setRunningState(isRunning, label = "运行中", tone = "running") {
  runButton.disabled = isRunning;
  runButton.textContent = isRunning ? "任务进行中" : "开始任务";
  stopButton.disabled = !isRunning || !currentJobId;
  jobBadge.textContent = label;
  jobBadge.className = `badge ${tone}`;
}

function startElapsedTimer(job) {
  activeJob = job;
  renderElapsed();
  window.clearInterval(elapsedTimer);
  elapsedTimer = window.setInterval(renderElapsed, 1000);
}

function stopElapsedTimer() {
  renderElapsed();
  window.clearInterval(elapsedTimer);
  elapsedTimer = null;
}

function renderElapsed() {
  if (!activeJob) return;
  const startedAt = Number(activeJob.createdAt || 0);
  const elapsed =
    startedAt > 0
      ? Math.max(0, Math.round(Date.now() / 1000 - startedAt))
      : Number(activeJob.elapsedSeconds || 0);
  activeJobId.textContent = `${activeJob.id || ""} · 已用时 ${formatDuration(elapsed)}`;
}

function updateProgress(value, message) {
  const percent = Math.max(0, Math.min(100, Number(value) || 0));
  progressBar.style.width = `${percent}%`;
  progressPercent.textContent = `${percent}%`;
  progressMessage.textContent = message || "等待开始";
}

function clearResults() {
  resultSummary.textContent = "暂无结果";
  results.innerHTML = "";
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const input = document.createElement("textarea");
    input.value = text;
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
}

async function copyCurrentLog() {
  const text = logBox.textContent.trim();
  if (!text) {
    setCopyLogLabel("暂无日志");
    return;
  }
  await copyText(text);
  setCopyLogLabel("已复制");
}

function setCopyLogLabel(label) {
  const original = "复制日志";
  copyLogButton.textContent = label;
  window.clearTimeout(copyLogResetTimer);
  copyLogResetTimer = window.setTimeout(() => {
    copyLogButton.textContent = original;
  }, 1400);
}

function statusLabel(status) {
  if (status === "queued") return "排队";
  if (status === "running") return "运行中";
  if (status === "canceling") return "取消中";
  if (status === "canceled") return "已停止";
  if (status === "succeeded") return "完成";
  if (status === "failed") return "失败";
  if (status === "interrupted") return "已中断";
  return "空闲";
}

function statusTone(status) {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "bad";
  if (status === "canceling" || status === "canceled" || status === "interrupted") return "warn";
  if (status === "running" || status === "queued") return "running";
  return "idle";
}

function formatDuration(seconds) {
  const total = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function formatBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  return `${(value / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function formatJobTime(timestamp) {
  const value = Number(timestamp || 0);
  return value > 0 ? new Date(value * 1000).toLocaleString() : "未知时间";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replaceAll("\n", " ");
}
