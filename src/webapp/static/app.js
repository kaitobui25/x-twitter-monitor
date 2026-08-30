(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    form: $("exportForm"),
    username: $("username"),
    startDate: $("startDate"),
    endDate: $("endDate"),
    exportButton: $("exportButton"),
    buttonLabel: document.querySelector("#exportButton .button-label"),
    serverStatus: $("serverStatus"),
    jobStatus: $("jobStatus"),
    stageBadge: $("stageBadge"),
    jobMessage: $("jobMessage"),
    progressBar: $("progressBar"),
    pageCount: $("pageCount"),
    fetchCount: $("fetchCount"),
    translateCount: $("translateCount"),
    errorBox: $("errorBox"),
    resultPanel: $("resultPanel"),
    resultSummary: $("resultSummary"),
    downloadCsv: $("downloadCsv"),
    previewList: $("previewList"),
    previewEmpty: $("previewEmpty"),
  };

  let activeJobId = null;
  let pollTimer = null;

  function localDateInputValue(date) {
    const offsetMs = date.getTimezoneOffset() * 60_000;
    return new Date(date.getTime() - offsetMs).toISOString().slice(0, 10);
  }

  function setDefaultDates() {
    if (els.endDate.value || els.startDate.value) return;
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - 7);
    els.endDate.value = localDateInputValue(end);
    els.startDate.value = localDateInputValue(start);
  }

  function sanitizeUsername(value) {
    return String(value || "").trim().replace(/^@+/, "").trim();
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (_) {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return payload;
  }

  function setServerState(ok) {
    els.serverStatus.classList.toggle("ready", ok);
    els.serverStatus.classList.toggle("error", !ok);
    const label = els.serverStatus.querySelector("span:last-child");
    label.textContent = ok ? "Web sẵn sàng" : "Mất kết nối";
  }

  async function checkHealth() {
    try {
      await fetchJson("/api/health");
      setServerState(true);
    } catch (_) {
      setServerState(false);
    }
  }

  function setRunning(running) {
    [els.username, els.startDate, els.endDate, els.exportButton].forEach((node) => {
      node.disabled = running;
    });
    els.exportButton.classList.toggle("is-running", running);
    els.buttonLabel.textContent = running ? "Đang xuất..." : "Xuất bài đăng";
  }

  function showError(message) {
    els.errorBox.textContent = message || "Có lỗi xảy ra.";
    els.errorBox.hidden = false;
  }

  function clearError() {
    els.errorBox.textContent = "";
    els.errorBox.hidden = true;
  }

  function progressPercent(job) {
    if (job.status === "done") return 100;
    if (job.stage === "writing") return 96;
    if (job.stage === "translating") {
      const total = Number(job.posts_total || 0);
      const done = Number(job.posts_translated || 0);
      return total > 0 ? 35 + Math.round((done / total) * 55) : 35;
    }
    if (job.stage === "fetching") {
      const page = Math.max(0, Number(job.page || 0));
      return Math.min(32, 8 + page * 2);
    }
    return 6;
  }

  function updateJobStatus(job) {
    els.jobStatus.hidden = false;
    els.stageBadge.textContent = String(job.stage || job.status || "queued").toUpperCase();
    els.jobMessage.textContent = job.message || "Đang xử lý...";
    els.pageCount.textContent = `Trang: ${job.page || 0}`;
    els.fetchCount.textContent = `Đã lấy: ${job.posts_fetched || 0}`;
    const translated = job.posts_translated || 0;
    const total = job.posts_total || 0;
    els.translateCount.textContent = total ? `Đã dịch: ${translated}/${total}` : `Đã dịch: ${translated}`;
    els.progressBar.style.width = `${progressPercent(job)}%`;
  }

  function stopPolling() {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  async function pollJob(jobId) {
    stopPolling();
    try {
      const job = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
      updateJobStatus(job);

      if (job.status === "done") {
        setRunning(false);
        activeJobId = null;
        await loadResults(job);
        return;
      }
      if (job.status === "error") {
        setRunning(false);
        activeJobId = null;
        showError(job.error || job.message || "Xuất dữ liệu thất bại.");
        return;
      }
      pollTimer = window.setTimeout(() => pollJob(jobId), 850);
    } catch (error) {
      setRunning(false);
      activeJobId = null;
      showError(error.message);
    }
  }

  function dateParts(isoValue) {
    const date = new Date(isoValue);
    if (Number.isNaN(date.getTime())) {
      return { key: "unknown", heading: "Không rõ ngày", time: String(isoValue || "") };
    }
    const key = new Intl.DateTimeFormat("sv-SE", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
    const heading = new Intl.DateTimeFormat("vi-VN", {
      weekday: "long",
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    }).format(date);
    const time = new Intl.DateTimeFormat("vi-VN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(date);
    return { key, heading, time };
  }

  function shortDisplayUrl(record) {
    const username = sanitizeUsername(record.username || "user");
    const id = String(record.tweet_id || "");
    const shortId = id.length > 10 ? `${id.slice(0, 10)}…` : id;
    return `x.com/${username}/status/${shortId}`;
  }

  function copyBlock(label, text, extraClass = "") {
    const block = document.createElement("div");
    block.className = `copy-block ${extraClass}`.trim();
    const labelEl = document.createElement("span");
    labelEl.className = "copy-label";
    labelEl.textContent = label;
    const textEl = document.createElement("p");
    textEl.className = "copy-text";
    textEl.textContent = text || "";
    block.append(labelEl, textEl);
    return block;
  }

  function postCard(record) {
    const card = document.createElement("article");
    card.className = "post-card";
    const parts = dateParts(record.created_at);

    const meta = document.createElement("div");
    meta.className = "post-meta";
    const time = document.createElement("span");
    time.textContent = parts.time;
    const type = document.createElement("span");
    type.className = "post-type";
    type.textContent = record.post_type || "tweet";
    meta.append(time, type);

    const link = document.createElement("a");
    link.className = "post-link";
    link.href = record.url || "#";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `${shortDisplayUrl(record)} ↗`;

    card.append(
      meta,
      copyBlock("Original", record.text || ""),
      copyBlock("Tiếng Việt", record.text_vi || "", "translation"),
      link,
    );
    return card;
  }

  function renderRecords(records) {
    els.previewList.replaceChildren();
    els.previewEmpty.hidden = records.length !== 0;
    if (!records.length) return;

    const groups = [];
    for (const record of records) {
      const parts = dateParts(record.created_at);
      let group = groups[groups.length - 1];
      if (!group || group.key !== parts.key) {
        group = { key: parts.key, heading: parts.heading, records: [] };
        groups.push(group);
      }
      group.records.push(record);
    }

    groups.forEach((group, index) => {
      const section = document.createElement("section");
      section.className = `day-group ${index % 2 === 0 ? "day-a" : "day-b"}`;
      const heading = document.createElement("div");
      heading.className = "day-heading";
      heading.textContent = `${group.heading} · ${group.records.length} bài`;
      section.appendChild(heading);
      group.records.forEach((record) => section.appendChild(postCard(record)));
      els.previewList.appendChild(section);
    });
  }

  async function loadResults(job) {
    const result = await fetchJson(`/api/jobs/${encodeURIComponent(job.id)}/results?offset=0&limit=500`);
    const shown = result.records.length;
    const total = result.total || 0;
    els.resultPanel.hidden = false;
    els.downloadCsv.href = job.csv_url || `/api/jobs/${encodeURIComponent(job.id)}/csv`;
    els.resultSummary.textContent = shown < total
      ? `${total} bài · đang hiển thị sơ bộ ${shown} bài mới nhất`
      : `${total} bài · ${job.pages_fetched || job.page || 0} trang dữ liệu`;
    renderRecords(result.records || []);
    els.resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function submitExport(event) {
    event.preventDefault();
    if (activeJobId) return;
    clearError();
    els.resultPanel.hidden = true;
    els.previewList.replaceChildren();

    const username = sanitizeUsername(els.username.value);
    els.username.value = username;
    if (!username) {
      showError("Hãy nhập tài khoản X.");
      return;
    }
    if (!els.startDate.value || !els.endDate.value) {
      showError("Hãy chọn đủ ngày bắt đầu và ngày kết thúc.");
      return;
    }

    setRunning(true);
    updateJobStatus({ status: "queued", stage: "queued", message: "Đang tạo tác vụ..." });

    try {
      const job = await fetchJson("/api/export", {
        method: "POST",
        body: JSON.stringify({
          username,
          start_date: els.startDate.value,
          end_date: els.endDate.value,
        }),
      });
      activeJobId = job.id;
      updateJobStatus(job);
      await pollJob(job.id);
    } catch (error) {
      setRunning(false);
      activeJobId = null;
      showError(error.message);
    }
  }

  els.form.addEventListener("submit", submitExport);
  setDefaultDates();
  checkHealth();
})();
