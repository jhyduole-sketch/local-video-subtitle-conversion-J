const form = document.querySelector("#jobForm");
const runButton = document.querySelector("#runButton");
const refreshHealth = document.querySelector("#refreshHealth");
const healthList = document.querySelector("#healthList");
const healthSummary = document.querySelector("#healthSummary");
const jobBadge = document.querySelector("#jobBadge");
const activeJobId = document.querySelector("#activeJobId");
const logBox = document.querySelector("#logBox");
const results = document.querySelector("#results");
const resultSummary = document.querySelector("#resultSummary");
const targetLangsInput = document.querySelector("#targetLangs");
const languagePicker = document.querySelector("#languagePicker");
let pollTimer = null;

refreshHealth.addEventListener("click", loadHealth);
form.addEventListener("submit", submitJob);
targetLangsInput.addEventListener("input", syncLanguageButtons);
languagePicker.querySelectorAll("[data-lang]").forEach((button) => {
  button.addEventListener("click", () => toggleLanguage(button.dataset.lang || ""));
});

loadHealth();

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
  const payload = formPayload();
  setRunningState(true);
  clearResults();
  logBox.textContent = "提交任务...";
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "任务提交失败");
    }
    activeJobId.textContent = data.jobId;
    pollJob(data.jobId);
  } catch (error) {
    setRunningState(false, "失败", "bad");
    logBox.textContent = error.message;
  }
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
    embedSubtitles: Boolean(data.get("embedSubtitles")),
    forceDownload: Boolean(data.get("forceDownload")),
    downloadOnly: Boolean(data.get("downloadOnly")),
  };
}

function toggleLanguage(language) {
  if (!language) return;
  const values = selectedTargetLangs();
  if (values.includes(language)) {
    targetLangsInput.value = values.filter((item) => item !== language).join(", ");
  } else {
    targetLangsInput.value = [...values, language].join(", ");
  }
  syncLanguageButtons();
}

function selectedTargetLangs() {
  return targetLangsInput.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function syncLanguageButtons() {
  const selected = new Set(selectedTargetLangs());
  languagePicker.querySelectorAll("[data-lang]").forEach((button) => {
    button.classList.toggle("selected", selected.has(button.dataset.lang));
  });
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
    if (data.status === "running" || data.status === "queued") {
      pollTimer = window.setTimeout(() => pollJob(jobId), 1500);
    } else {
      setRunningState(false, statusLabel(data.status), statusTone(data.status));
      if (data.result) {
        renderResults(data.result);
      }
    }
  } catch (error) {
    setRunningState(false, "失败", "bad");
    logBox.textContent = error.message;
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
  setRunningState(
    job.status === "running" || job.status === "queued",
    statusLabel(job.status),
    statusTone(job.status),
  );
  const lines = Array.isArray(job.logs) ? job.logs : [];
  logBox.textContent = lines.length ? lines.join("\n") : "等待日志";
  if (job.error) {
    logBox.textContent += `\n${job.error}`;
  }
  logBox.scrollTop = logBox.scrollHeight;
}

function renderResults(result) {
  const items = [];
  if (result.downloadedVideoPath) {
    items.push(["下载视频", result.downloadedVideoPath]);
  }
  if (result.sourceSubtitlePath) {
    items.push([`源字幕 (${result.sourceKind || "source"})`, result.sourceSubtitlePath]);
  }
  Object.entries(result.translatedPaths || {}).forEach(([lang, path]) => {
    items.push([`字幕 ${lang}`, path]);
  });
  Object.entries(result.subtitledVideoPaths || {}).forEach(([lang, path]) => {
    items.push([`视频 ${lang}`, path]);
  });
  Object.entries(result.failedLanguages || {}).forEach(([lang, message]) => {
    items.push([`失败 ${lang}`, message]);
  });
  resultSummary.textContent = items.length ? `${items.length} 个结果` : "暂无结果";
  results.innerHTML = items.map(([kind, path]) => resultItem(kind, path)).join("");
  results.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => copyText(button.dataset.copy || ""));
  });
}

function resultItem(kind, path) {
  const safePath = escapeHtml(path);
  return `
    <article class="result-item">
      <div class="result-kind">${escapeHtml(kind)}</div>
      <div class="result-path">${safePath}</div>
      <button class="copy-button" type="button" data-copy="${escapeAttribute(path)}">复制路径</button>
    </article>
  `;
}

function setRunningState(isRunning, label = "运行中", tone = "running") {
  runButton.disabled = isRunning;
  jobBadge.textContent = label;
  jobBadge.className = `badge ${tone}`;
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

function statusLabel(status) {
  if (status === "queued") return "排队";
  if (status === "running") return "运行中";
  if (status === "succeeded") return "完成";
  if (status === "failed") return "失败";
  return "空闲";
}

function statusTone(status) {
  if (status === "succeeded") return "ok";
  if (status === "failed") return "bad";
  if (status === "running" || status === "queued") return "running";
  return "idle";
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
