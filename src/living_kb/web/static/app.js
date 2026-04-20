const state = {
  rawDocuments: [],
  jobs: [],
  reviewQueue: [],
  pages: [],
  activity: [],
  selectedRawId: null,
  selectedPageSlug: null,
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function apiForm(path, formData, options = {}) {
  const response = await fetch(path, {
    method: options.method || "POST",
    body: formData,
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(value) {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function button(label, onClick, variant = "ghost small") {
  return `<button class="button ${variant}" data-action="${onClick.action}" data-id="${onClick.id ?? ""}" data-extra="${onClick.extra ?? ""}">${escapeHtml(label)}</button>`;
}

function renderMetrics(dashboard) {
  const entries = [
    ["Sources", dashboard.total_sources, "Connected inputs"],
    ["RAW Docs", dashboard.total_raw_documents, "Captured raw material"],
    ["Pages", dashboard.total_pages, "Compiled knowledge pages"],
    ["Links", dashboard.total_links, "Graph edges"],
    ["Open Findings", dashboard.open_findings, "Needs review"],
    ["Queue", dashboard.queued_jobs, `Running ${dashboard.running_jobs}`],
  ];

  document.getElementById("metrics").innerHTML = entries
    .map(
      ([label, value, subtle]) => `
        <article class="metric-card">
          <span class="label">${escapeHtml(label)}</span>
          <div class="value">${escapeHtml(value)}</div>
          <div class="subtle">${escapeHtml(subtle)}</div>
        </article>
      `
    )
    .join("");
}

function renderRawDocuments() {
  const root = document.getElementById("raw-list");
  if (!state.rawDocuments.length) {
    root.innerHTML = `<div class="empty">No raw documents yet.</div>`;
    return;
  }

  root.innerHTML = state.rawDocuments
    .map(
      (item) => `
        <article class="list-card">
          <h3>${escapeHtml(item.title || `Raw ${item.raw_id}`)}</h3>
          <div class="meta">
            <span class="pill">${escapeHtml(item.source_type)}</span>
            <span class="pill status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
            <span class="pill">${escapeHtml(formatDate(item.created_at))}</span>
          </div>
          <div class="actions">
            ${button("Inspect", { action: "inspect-raw", id: item.raw_id }, "ghost small")}
            ${button("Queue Compile", { action: "queue-compile", id: item.raw_id }, "primary small")}
            ${button("Compile Now", { action: "compile-now", id: item.raw_id })}
          </div>
        </article>
      `
    )
    .join("");
}

async function loadRawViewer(rawId) {
  const raw = await api(`/api/raw-documents/${rawId}`);
  state.selectedRawId = rawId;
  document.getElementById("raw-viewer-empty").classList.add("hidden");
  document.getElementById("raw-viewer").classList.remove("hidden");
  document.getElementById("raw-viewer-meta").innerHTML = `
    <span class="pill">${escapeHtml(raw.source_type)}</span>
    <span class="pill status-${escapeHtml(raw.status)}">${escapeHtml(raw.status)}</span>
    <span class="pill">${escapeHtml(formatDate(raw.created_at))}</span>
    <span class="pill">raw #${escapeHtml(raw.raw_id)}</span>
    <span class="pill">parser ${escapeHtml(raw.parser_version)}</span>
    <span class="pill">collected ${escapeHtml(formatDate(raw.collected_at))}</span>
  `;
  document.getElementById("raw-viewer-uri").innerHTML = raw.uri
    ? `<a href="${escapeHtml(raw.uri)}" target="_blank" rel="noreferrer">${escapeHtml(raw.uri)}</a>`
    : "No source URL attached.";
  document.getElementById("raw-viewer-paths").innerHTML = `
    <div>checksum: <code>${escapeHtml(raw.checksum)}</code></div>
    <div>snapshot: <code>${escapeHtml(raw.snapshot_path || "n/a")}</code></div>
    <div>asset: <code>${escapeHtml(raw.asset_path || "n/a")}</code></div>
  `;
  document.getElementById("raw-viewer-linked-page").innerHTML = raw.linked_page_slug
    ? `Linked page: <a href="#" data-action="inspect-page" data-id="${escapeHtml(raw.linked_page_slug)}">${escapeHtml(raw.linked_page_title || raw.linked_page_slug)}</a> <span class="pill status-${escapeHtml(raw.linked_page_review_status || "")}">${escapeHtml(raw.linked_page_review_status || "unknown")}</span>`
    : "No linked page yet.";
  document.getElementById("raw-viewer-content").textContent = raw.content_preview || "No content preview available.";
  document.getElementById("raw-viewer-queue").dataset.rawId = String(rawId);
  document.getElementById("raw-viewer-compile").dataset.rawId = String(rawId);
  document.getElementById("raw-viewer-open-page").dataset.pageSlug = raw.linked_page_slug || "";
  document.getElementById("raw-viewer-open-page").disabled = !raw.linked_page_slug;
}

function renderJobs() {
  const root = document.getElementById("job-list");
  if (!state.jobs.length) {
    root.innerHTML = `<div class="empty">No jobs yet.</div>`;
    return;
  }

  root.innerHTML = state.jobs
    .map(
      (job) => `
        <article class="list-card">
          <h3>${escapeHtml(job.job_type)}</h3>
          <div class="meta">
            <span class="pill status-${escapeHtml(job.status)}">${escapeHtml(job.status)}</span>
            <span class="pill">job #${escapeHtml(job.id)}</span>
            <span class="pill">${escapeHtml(formatDate(job.created_at))}</span>
          </div>
          <div>${escapeHtml(job.error_text || JSON.stringify(job.result || {}, null, 2) || "No result yet.")}</div>
          <div class="actions">
            ${job.status === "queued" ? button("Run", { action: "run-job", id: job.id }, "primary small") : ""}
          </div>
        </article>
      `
    )
    .join("");
}

function renderReviewQueue() {
  const root = document.getElementById("review-list");
  if (!state.reviewQueue.length) {
    root.innerHTML = `<div class="empty">Review queue is clear.</div>`;
    return;
  }

  root.innerHTML = state.reviewQueue
    .map((item) => {
      const actions =
        item.item_type === "page"
          ? `
            ${button("Approve", { action: "approve-page", id: item.id }, "primary small")}
            ${button("Reject", { action: "reject-page", id: item.id })}
          `
          : `
            ${button("Resolve", { action: "resolve-finding", id: item.id }, "primary small")}
            ${button("Dismiss", { action: "dismiss-finding", id: item.id })}
          `;

      return `
        <article class="list-card">
          <h3>${escapeHtml(item.title)}</h3>
          <div class="meta">
            <span class="pill">${escapeHtml(item.item_type)}</span>
            <span class="pill status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
            ${item.severity ? `<span class="pill">${escapeHtml(item.severity)}</span>` : ""}
            ${item.page_slug ? `<span class="pill">${escapeHtml(item.page_slug)}</span>` : ""}
          </div>
          <div>${escapeHtml(JSON.stringify(item.details || {}, null, 2))}</div>
          <div class="actions">${actions}</div>
        </article>
      `;
    })
    .join("");
}

function renderPages() {
  const root = document.getElementById("page-list");
  if (!state.pages.length) {
    root.innerHTML = `<div class="empty">No pages compiled yet.</div>`;
    return;
  }

  root.innerHTML = state.pages
    .map(
      (page) => `
        <article class="list-card">
          <h3>${escapeHtml(page.title)}</h3>
          <div class="meta">
            <span class="pill">${escapeHtml(page.page_type)}</span>
            <span class="pill status-${escapeHtml(page.review_status)}">${escapeHtml(page.review_status)}</span>
            <span class="pill">${escapeHtml(formatDate(page.updated_at))}</span>
          </div>
          <div class="actions">
            ${button("Inspect", { action: "inspect-page", id: page.slug }, "primary small")}
            <a class="button ghost small" href="/api/pages/${encodeURIComponent(page.slug)}" target="_blank" rel="noreferrer">Open JSON</a>
          </div>
        </article>
      `
    )
    .join("");
}

function renderActivity() {
  const root = document.getElementById("activity-feed");
  if (!state.activity.length) {
    root.innerHTML = "";
    document.getElementById("activity-empty").classList.remove("hidden");
    return;
  }

  document.getElementById("activity-empty").classList.add("hidden");
  root.innerHTML = state.activity
    .map((item) => {
      if (item.kind === "compile") {
        return `
          <article class="list-card">
            <h3>Compile Run</h3>
            <div class="meta">
              <span class="pill status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
              <span class="pill">${escapeHtml(item.provider)}</span>
              <span class="pill">${escapeHtml(item.model_name)}</span>
              <span class="pill">${escapeHtml(formatDate(item.created_at))}</span>
            </div>
            <div>quality: ${escapeHtml(item.quality_score ?? "n/a")} | duration: ${escapeHtml(item.duration_ms ?? "n/a")} ms</div>
            <div>${escapeHtml(item.error_text || "")}</div>
          </article>
        `;
      }
      if (item.kind === "review") {
        return `
          <article class="list-card">
            <h3>Review Event</h3>
            <div class="meta">
              <span class="pill">${escapeHtml(item.item_type)}</span>
              <span class="pill">${escapeHtml(item.action)}</span>
              <span class="pill">${escapeHtml(formatDate(item.created_at))}</span>
            </div>
            <div>${escapeHtml(item.notes || "No notes.")}</div>
          </article>
        `;
      }
      return `
        <article class="list-card">
          <h3>Query Event</h3>
          <div class="meta">
            <span class="pill">${escapeHtml(formatDate(item.created_at))}</span>
            <span class="pill">confidence ${escapeHtml(item.confidence_score ?? "n/a")}</span>
          </div>
          <div>${escapeHtml(item.question)}</div>
        </article>
      `;
    })
    .join("");
}

async function loadPageViewer(slug) {
  const [page, revisions, lineage] = await Promise.all([
    api(`/api/pages/${encodeURIComponent(slug)}`),
    api(`/api/pages/${encodeURIComponent(slug)}/revisions`),
    api(`/api/pages/${encodeURIComponent(slug)}/lineage`),
  ]);

  state.selectedPageSlug = slug;
  document.getElementById("page-viewer-empty").classList.add("hidden");
  document.getElementById("page-viewer").classList.remove("hidden");
  document.getElementById("viewer-title").textContent = page.title;
  document.getElementById("viewer-meta").innerHTML = `
    <span class="pill">${escapeHtml(page.page_type)}</span>
    <span class="pill status-${escapeHtml(page.review_status)}">${escapeHtml(page.review_status)}</span>
    <span class="pill">v${escapeHtml(page.version)}</span>
    <span class="pill">${escapeHtml(formatDate(page.updated_at))}</span>
  `;
  document.getElementById("viewer-markdown").textContent = page.markdown;
  document.getElementById("viewer-revisions").innerHTML = revisions.length
    ? revisions
        .map(
          (revision) => `
            <article class="list-card compact-card">
              <div class="meta">
                <span class="pill">v${escapeHtml(revision.version)}</span>
                <span class="pill">${escapeHtml(formatDate(revision.created_at))}</span>
              </div>
              <div>${escapeHtml(revision.summary)}</div>
            </article>
          `
        )
        .join("")
    : `<div class="empty">No revisions saved yet.</div>`;

  const diffRoot = document.getElementById("viewer-diff");
  if (revisions.length < 2) {
    diffRoot.textContent = "No diff yet. Compile the page again to create a second revision.";
    return;
  }

  const latest = revisions[0];
  const previous = revisions[1];
  const diff = await api(
    `/api/pages/${encodeURIComponent(slug)}/diff?from_version=${previous.version}&to_version=${latest.version}`
  );
  diffRoot.textContent = diff.diff;
  state.activity = [
    ...lineage.compile_runs.map((item) => ({ kind: "compile", ...item })),
    ...lineage.review_events.map((item) => ({ kind: "review", ...item })),
    ...lineage.recent_queries.map((item) => ({ kind: "query", ...item })),
  ]
    .sort((left, right) => new Date(right.created_at || 0) - new Date(left.created_at || 0))
    .slice(0, 18);
  renderActivity();
}

async function refreshAll() {
  const jobStatus = document.getElementById("job-status-filter")?.value || "";
  const jobType = document.getElementById("job-type-filter")?.value || "";
  const reviewItem = document.getElementById("review-item-filter")?.value || "";
  const reviewSeverity = document.getElementById("review-severity-filter")?.value || "";
  const params = new URLSearchParams();
  if (jobStatus) params.set("status", jobStatus);
  if (jobType) params.set("job_type", jobType);
  const reviewParams = new URLSearchParams();
  if (reviewItem) reviewParams.set("item_type", reviewItem);
  if (reviewSeverity) reviewParams.set("severity", reviewSeverity);

  const [dashboard, rawDocuments, jobs, reviewQueue, pages, compileRuns, reviewEvents, queryEvents] = await Promise.all([
    api("/api/dashboard"),
    api("/api/raw-documents"),
    api(`/api/jobs${params.toString() ? `?${params.toString()}` : ""}`),
    api(`/api/review-queue${reviewParams.toString() ? `?${reviewParams.toString()}` : ""}`),
    api("/api/pages"),
    api("/api/compile-runs?limit=8"),
    api("/api/review-events?limit=8"),
    api("/api/query-events?limit=8"),
  ]);

  state.rawDocuments = rawDocuments;
  state.jobs = jobs;
  state.reviewQueue = reviewQueue;
  state.pages = pages;
  state.activity = [
    ...compileRuns.map((item) => ({ kind: "compile", ...item })),
    ...reviewEvents.map((item) => ({ kind: "review", ...item })),
    ...queryEvents.map((item) => ({ kind: "query", ...item })),
  ]
    .sort((left, right) => new Date(right.created_at || 0) - new Date(left.created_at || 0))
    .slice(0, 18);

  renderMetrics(dashboard);
  renderRawDocuments();
  renderJobs();
  renderReviewQueue();
  renderPages();
  renderActivity();
  if (state.selectedRawId) {
    try {
      await loadRawViewer(state.selectedRawId);
    } catch {
      state.selectedRawId = null;
      document.getElementById("raw-viewer").classList.add("hidden");
      document.getElementById("raw-viewer-empty").classList.remove("hidden");
    }
  }
  if (state.selectedPageSlug) {
    try {
      await loadPageViewer(state.selectedPageSlug);
    } catch {
      state.selectedPageSlug = null;
      document.getElementById("page-viewer").classList.add("hidden");
      document.getElementById("page-viewer-empty").classList.remove("hidden");
    }
  }
}

function showNotice(message, isError = false) {
  const root = document.getElementById("ingest-result");
  root.classList.remove("hidden");
  root.textContent = message;
  root.style.borderColor = isError ? "rgba(140,45,45,0.25)" : "rgba(47,108,82,0.25)";
}

async function handleAction(event) {
  const target = event.target.closest("[data-action]");
  if (!target) return;

  const action = target.dataset.action;
  const id = target.dataset.id;

  try {
    if (action === "inspect-raw") {
      await loadRawViewer(id);
      return;
    }
    if (action === "queue-compile") await api(`/api/jobs/compile/${id}`, { method: "POST", body: "{}" });
    if (action === "compile-now") {
      const compiled = await api(`/api/compile/${id}`, { method: "POST" });
      await refreshAll();
      await loadPageViewer(compiled.slug);
      return;
    }
    if (action === "run-job") await api(`/api/jobs/${id}/run`, { method: "POST" });
    if (action === "approve-page") await api(`/api/review/pages/${id}/approve`, { method: "POST", body: JSON.stringify({ notes: "Approved from control room" }) });
    if (action === "reject-page") await api(`/api/review/pages/${id}/reject`, { method: "POST", body: JSON.stringify({ notes: "Rejected from control room" }) });
    if (action === "resolve-finding") await api(`/api/review/findings/${id}/resolve`, { method: "POST", body: JSON.stringify({ notes: "Resolved from control room" }) });
    if (action === "dismiss-finding") await api(`/api/review/findings/${id}/dismiss`, { method: "POST", body: JSON.stringify({ notes: "Dismissed from control room" }) });
    if (action === "inspect-page") {
      await loadPageViewer(id);
      return;
    }
    await refreshAll();
  } catch (error) {
    showNotice(error.message || "Action failed", true);
  }
}

async function setup() {
  document.body.addEventListener("click", handleAction);

  document.getElementById("refresh-all").addEventListener("click", refreshAll);
  document.getElementById("job-status-filter").addEventListener("change", refreshAll);
  document.getElementById("job-type-filter").addEventListener("change", refreshAll);
  document.getElementById("review-item-filter").addEventListener("change", refreshAll);
  document.getElementById("review-severity-filter").addEventListener("change", refreshAll);
  document.getElementById("run-one-job").addEventListener("click", async () => {
    await api("/api/jobs/run-once", { method: "POST" });
    await refreshAll();
  });
  document.getElementById("run-all-jobs").addEventListener("click", async () => {
    await api("/api/jobs/run-all", { method: "POST" });
    await refreshAll();
  });
  document.getElementById("queue-health").addEventListener("click", async () => {
    await api("/api/jobs/health-check", { method: "POST", body: "{}" });
    await refreshAll();
  });
  document.getElementById("raw-viewer-queue").addEventListener("click", async (event) => {
    const rawId = event.currentTarget.dataset.rawId;
    if (!rawId) return;
    await api(`/api/jobs/compile/${rawId}`, { method: "POST", body: "{}" });
    showNotice(`Queued compile job for raw document #${rawId}.`);
    await refreshAll();
  });
  document.getElementById("raw-viewer-compile").addEventListener("click", async (event) => {
    const rawId = event.currentTarget.dataset.rawId;
    if (!rawId) return;
    const compiled = await api(`/api/compile/${rawId}`, { method: "POST" });
    showNotice(`Compiled raw document #${rawId} into page ${compiled.slug}.`);
    await refreshAll();
    await loadPageViewer(compiled.slug);
  });
  document.getElementById("raw-viewer-open-page").addEventListener("click", async (event) => {
    const slug = event.currentTarget.dataset.pageSlug;
    if (!slug) return;
    await loadPageViewer(slug);
  });

  document.getElementById("ingest-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    try {
      const raw = await api("/api/ingest/text", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showNotice(`Ingested raw document #${raw.raw_id}. Queue it from the RAW list or compile immediately.`);
      event.currentTarget.reset();
      await refreshAll();
      await loadRawViewer(raw.raw_id);
    } catch (error) {
      showNotice(error.message || "Ingest failed", true);
    }
  });

  document.getElementById("ingest-url-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form.entries());
    try {
      const raw = await api("/api/ingest/url", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showNotice(`Fetched URL into raw document #${raw.raw_id}.`);
      event.currentTarget.reset();
      await refreshAll();
      await loadRawViewer(raw.raw_id);
    } catch (error) {
      showNotice(error.message || "URL ingest failed", true);
    }
  });

  document.getElementById("ingest-file-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const raw = await apiForm("/api/ingest/file", form);
      showNotice(`Uploaded file into raw document #${raw.raw_id}.`);
      event.currentTarget.reset();
      await refreshAll();
      await loadRawViewer(raw.raw_id);
    } catch (error) {
      showNotice(error.message || "File ingest failed", true);
    }
  });

  document.getElementById("query-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      question: form.get("question"),
      top_k: 5,
    };
    try {
      const result = await api("/api/query", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      document.getElementById("query-result").textContent = JSON.stringify(result, null, 2);
    } catch (error) {
      document.getElementById("query-result").textContent = error.message || "Query failed";
    }
  });

  await refreshAll();
}

setup();
