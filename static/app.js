/* pcull review UI — vanilla JS, no build step */
"use strict";

const state = {
  tab: "todo",
  sort: "score_desc",
  items: [],
  selected: new Set(),
  focusIndex: -1,
  offset: 0,
  limit: 60,
  total: 0,
  drawerId: null,
  drawerGroupItems: [],
  analyzeTimer: null,
  library: null,
  browserPath: "",
  openTimer: null,
};

const $ = (id) => document.getElementById(id);
const REC_LABEL = { keep: "推荐保留", review: "待复核", delete: "建议删除" };

function fmtSize(bytes) {
  if (bytes == null) return "";
  if (bytes > 1e9) return (bytes / 1e9).toFixed(1) + " GB";
  if (bytes > 1e6) return (bytes / 1e6).toFixed(1) + " MB";
  return Math.round(bytes / 1e3) + " KB";
}
function fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function scoreClass(s) {
  if (s == null) return "s-bad";
  if (s < 30) return "s-bad";
  if (s < 55) return "s-mid";
  return "s-good";
}

function toast(msg, ms = 3500) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), ms);
}

async function api(path, opts) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

/* ---------- stats ---------- */
async function refreshStats() {
  const s = await api("/api/stats");
  const parts = [
    `总 <b>${s.photos}</b>`,
    `已分析 <b>${s.analyzed}</b>`,
    `<span class="red">建议删除 <b>${s.recommendations.delete || 0}</b></span>`,
    `待复核 <b>${s.recommendations.review || 0}</b>`,
    `<span class="green">推荐保留 <b>${s.recommendations.keep || 0}</b></span>`,
    `重复组 <b>${s.groups}</b>`,
    `已标记删除 <b>${s.decided.delete || 0}</b> · 可释放 <b>${fmtSize(s.reclaimable_bytes)}</b>`,
    `库大小 <b>${fmtSize(s.total_bytes)}</b>`,
  ];
  $("stats").innerHTML = parts.join('<span style="opacity:.3">·</span>');
  $("btn-apply").disabled = !(s.decided.delete > 0);
}

/* ---------- grid ---------- */
async function loadItems(append = false) {
  if (!append) {
    state.offset = 0;
    state.items = [];
    state.selected.clear();
    state.focusIndex = -1;
  }
  if (state.tab === "groups") return renderGroups();

  const q = new URLSearchParams({
    tab: state.tab, sort: state.sort,
    limit: state.limit, offset: state.offset,
  });
  const data = await api(`/api/photos?${q}`);
  state.total = data.total;
  state.items = append ? state.items.concat(data.items) : data.items;
  renderGrid();
  // auto-focus the first card so X/A work immediately without pressing J first
  if (!append && state.focusIndex < 0 && state.items.length) setFocus(0, false);
}

function reasonBadge(reason) {
  const cls = /重复|连拍/.test(reason) ? "b-info" : /欠锐|平淡/.test(reason) ? "b-warn" : "";
  const span = document.createElement("span");
  span.className = "badge " + cls;
  span.textContent = reason;
  return span;
}

function buildCard(item, idx, small = false) {
  const card = document.createElement("div");
  card.className = "card" + (idx === state.focusIndex ? " focused" : "");
  card.dataset.idx = idx;
  if (state.selected.has(item.id)) card.classList.add("selected");

  if (item.score != null || item.analyzed) {
    const img = document.createElement("img");
    img.className = "thumb";
    img.loading = "lazy";
    img.src = `/thumb/${item.id}`;
    img.onerror = () => {
      const ph = document.createElement("div");
      ph.className = "thumb-placeholder";
      ph.textContent = "⚠";
      img.replaceWith(ph);
    };
    card.appendChild(img);
  } else {
    const ph = document.createElement("div");
    ph.className = "thumb-placeholder";
    ph.textContent = "?";
    card.appendChild(ph);
  }

  if (item.score != null) {
    const score = document.createElement("div");
    score.className = "score " + scoreClass(item.score);
    score.textContent = Math.round(item.score);
    card.appendChild(score);
  }
  if (item.decision) {
    const mark = document.createElement("div");
    mark.className = "mark " + (item.decision === "delete" ? "m-delete" : "m-keep");
    mark.textContent = item.decision === "delete" ? "🗑 删除" : "✔ 保留";
    card.appendChild(mark);
  }

  const meta = document.createElement("div");
  meta.className = "meta";
  const badges = document.createElement("div");
  badges.className = "badges";
  for (const r of item.reasons || []) badges.appendChild(reasonBadge(r));
  if (item.is_video) {
    const b = document.createElement("span");
    b.className = "badge b-info";
    b.textContent = `视频 ${item.duration ? item.duration.toFixed(0) + "s" : ""}`;
    badges.appendChild(b);
  }
  meta.appendChild(badges);
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = `${fmtDate(item.taken_at)} · ${fmtSize(item.size)} · ${item.filename}`;
  meta.appendChild(name);
  card.appendChild(meta);
  return card;
}

function renderGrid() {
  const main = $("main");
  main.innerHTML = "";
  if (!state.items.length) {
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = state.tab === "todo"
      ? "没有待处理项 — 全部标记完成 🎉"
      : "此项为空";
    main.appendChild(div);
    $("load-more-wrap").classList.add("hidden");
    return;
  }
  const grid = document.createElement("div");
  grid.className = "grid";
  state.items.forEach((item, idx) => grid.appendChild(buildCard(item, idx)));
  main.appendChild(grid);

  const wrap = $("load-more-wrap");
  if (state.items.length < state.total) {
    wrap.classList.remove("hidden");
    $("load-more").textContent = `加载更多 (${state.items.length}/${state.total})`;
  } else {
    wrap.classList.add("hidden");
  }
  updateSelectionInfo();
}

/* ---------- groups tab ---------- */
async function renderGroups() {
  const main = $("main");
  main.innerHTML = "";
  $("load-more-wrap").classList.add("hidden");
  const data = await api("/api/groups");
  if (!data.groups.length) {
    const div = document.createElement("div");
    div.className = "empty";
    div.textContent = "没有检测到重复 / 连拍组";
    main.appendChild(div);
    return;
  }
  for (const g of data.groups) {
    const sec = document.createElement("div");
    sec.className = "group-sec";
    const head = document.createElement("div");
    head.className = "group-head";
    const title = document.createElement("b");
    title.textContent = `组 #${g.group_id}`;
    head.appendChild(title);
    head.append(`${g.count} 张 · 保留组内最高分，其余可删`);

    const btn = document.createElement("button");
    btn.className = "danger sm";
    btn.textContent = "其余标记删除";
    const rest = g.items.slice(1).filter((i) => i.decision !== "keep");
    btn.disabled = rest.length === 0;
    btn.onclick = async () => {
      await api("/api/decisions", {
        method: "POST",
        body: JSON.stringify({ ids: rest.map((i) => i.id), decision: "delete" }),
      });
      toast(`已标记 ${rest.length} 张为删除（组 #${g.group_id}）`);
      await Promise.all([renderGroups(), refreshStats()]);
    };
    head.appendChild(btn);
    sec.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "grid";
    g.items.forEach((item, i) => {
      const card = buildCard(item, -1);
      if (i === 0) {
        const star = document.createElement("div");
        star.className = "keepstar";
        star.textContent = "★ 组内最佳";
        card.querySelector(".meta").prepend(star);
      }
      card.onclick = () => openDrawer(item.id, item);
      grid.appendChild(card);
    });
    sec.appendChild(grid);
    main.appendChild(sec);
  }
}

/* ---------- selection & focus ---------- */
function updateSelectionInfo() {
  $("selection-info").textContent = state.selected.size
    ? `已选 ${state.selected.size} 项`
    : "";
}

function setFocus(idx, scroll = true) {
  state.focusIndex = Math.max(0, Math.min(idx, state.items.length - 1));
  document.querySelectorAll(".card.focused").forEach((c) => c.classList.remove("focused"));
  const el = document.querySelector(`.card[data-idx="${state.focusIndex}"]`);
  if (el) {
    el.classList.add("focused");
    if (scroll) el.scrollIntoView({ block: "nearest" });
  }
}

function cardClick(e, item, idx) {
  if (e.shiftKey && state.focusIndex >= 0) {
    const [a, b] = [Math.min(state.focusIndex, idx), Math.max(state.focusIndex, idx)];
    for (let i = a; i <= b; i++) state.selected.add(state.items[i].id);
  } else if (e.ctrlKey || e.metaKey) {
    state.selected.has(item.id) ? state.selected.delete(item.id) : state.selected.add(item.id);
    setFocus(idx);
  } else if (state.selected.size > 0) {
    state.selected.clear();
    state.selected.add(item.id);
    setFocus(idx);
  } else {
    openDrawer(item.id);
  }
  renderGrid();
}

function gridClickDelegator(e) {
  const card = e.target.closest(".card");
  if (!card) return;
  const idx = parseInt(card.dataset.idx, 10);
  if (idx >= 0 && state.items[idx]) cardClick(e, state.items[idx], idx);
}

/* ---------- decisions ---------- */
function targetIds() {
  if (state.drawerId != null) return [state.drawerId];
  if (state.selected.size) return [...state.selected];
  if (state.focusIndex >= 0 && state.items[state.focusIndex])
    return [state.items[state.focusIndex].id];
  return [];
}

async function mark(decision) {
  const ids = targetIds();
  if (!ids.length) return;
  await api("/api/decisions", {
    method: "POST",
    body: JSON.stringify({ ids, decision }),
  });
  // keyboard triage flow: after marking a single focused item, move to the next
  const advance = state.drawerId == null && decision !== null &&
    state.selected.size === 0 && state.focusIndex >= 0;
  const nextFocus = Math.min(state.focusIndex + (advance ? 1 : 0),
                             Math.max(0, state.items.length - 1));
  state.selected.clear();
  closeDrawer();
  await loadItems();
  if (state.tab !== "groups") setFocus(nextFocus);
  refreshStats();
}

/* ---------- drawer ---------- */
function closeDrawer() {
  state.drawerId = null;
  $("drawer").classList.add("hidden");
}

function metricRow(label, val, warn = false) {
  const row = document.createElement("div");
  row.className = "m-row";
  const lab = document.createElement("div");
  lab.className = "m-label";
  lab.textContent = label;
  const bar = document.createElement("div");
  bar.className = "m-bar";
  const fill = document.createElement("div");
  fill.className = "m-fill";
  fill.style.width = Math.max(0, Math.min(100, val == null ? 0 : val)) + "%";
  if (warn) fill.style.background = "var(--red)";
  bar.appendChild(fill);
  const num = document.createElement("div");
  num.className = "m-val";
  num.textContent = val == null ? "—" : Math.round(val);
  row.append(lab, bar, num);
  return row;
}

async function openDrawer(id, fallbackItem) {
  let item = fallbackItem || state.items.find((i) => i.id === id);
  let groupItems = [];
  if (item && item.group_id != null) {
    const data = await api("/api/groups");
    const g = data.groups.find((g) => g.group_id === item.group_id);
    groupItems = g ? g.items : [];
  }
  if (!item) {
    // deep link (#photo=id) or an id not in the current grid: try its group,
    // then the single-photo endpoint
    const data = await api("/api/groups");
    for (const g of data.groups) {
      const hit = g.items.find((i) => i.id === id);
      if (hit) { item = hit; groupItems = g.items; break; }
    }
    if (!item) {
      try { item = await api(`/api/photo/${id}`); } catch (e) { /* not found */ }
    }
  }
  if (!item) { toast("找不到该照片"); return; }
  state.drawerId = id;
  state.drawerGroupItems = groupItems;
  renderDrawer(item, groupItems);
  $("drawer").classList.remove("hidden");
}

function renderDrawer(item, groupItems) {
  $("drawer-img").src = `/thumb/${item.id}`;
  $("drawer-title").textContent = `${item.filename} — ${REC_LABEL[item.recommendation] || "未分析"}${item.score != null ? " · " + Math.round(item.score) + " 分" : ""}`;

  const chips = $("drawer-chips");
  chips.innerHTML = "";
  for (const r of item.reasons || []) {
    const chip = document.createElement("span");
    chip.className = /重复|连拍/.test(r) ? "chip c-info" : /欠锐|平淡/.test(r) ? "chip c-warn" : "chip";
    chip.textContent = r;
    chips.appendChild(chip);
  }
  if (item.decision) {
    const chip = document.createElement("span");
    chip.className = "chip c-rec";
    chip.textContent = "已标记：" + (item.decision === "delete" ? "删除" : "保留");
    chips.appendChild(chip);
  }

  const m = $("drawer-metrics");
  m.innerHTML = "";
  m.appendChild(metricRow("清晰", item.blur, item.blur != null && item.blur < 25));
  m.appendChild(metricRow("曝光", item.exposure, item.exposure != null && item.exposure < 45));
  m.appendChild(metricRow("色彩", item.colorfulness));
  if (item.faces != null) {
    const row = document.createElement("div");
    row.className = "m-row";
    row.textContent = item.faces
      ? `人脸 ${item.faces}${item.eye_open_min != null ? " · 最睁眼度 " + item.eye_open_min : ""}${item.closed_eye ? " · ⚠ 闭眼" : ""}`
      : "未检出人脸";
    m.appendChild(row);
  }
  m.appendChild(metricRow("综合", item.score, item.score != null && item.score < 30));

  $("drawer-delete").onclick = () => mark("delete");
  $("drawer-keep").onclick = () => mark("keep");
  $("drawer-clear").onclick = () => mark(null);
  $("drawer-original").href = `/file/${item.id}`;

  const gwrap = $("drawer-group");
  gwrap.innerHTML = "";
  if (groupItems.length) {
    const title = document.createElement("div");
    title.className = "g-title";
    title.textContent = `重复 / 连拍组（${groupItems.length} 张，点击切换）`;
    gwrap.appendChild(title);
    const items = document.createElement("div");
    items.className = "g-items";
    for (const gi of groupItems) {
      const it = document.createElement("div");
      it.className = "g-item" + (gi.id === item.id ? " current" : "");
      const img = document.createElement("img");
      img.src = `/thumb/${gi.id}`;
      const sc = document.createElement("div");
      sc.className = "g-score";
      sc.textContent = gi.score != null ? Math.round(gi.score) : "—";
      it.append(img, sc);
      it.onclick = () => { state.drawerId = gi.id; renderDrawer(gi, groupItems); };
      items.appendChild(it);
    }
    gwrap.appendChild(items);
  }
}

/* ---------- analyze / apply ---------- */
async function pollAnalyze() {
  const s = await api("/api/analyze/status");
  if (s.running) {
    $("progress-bar").classList.remove("hidden");
    $("btn-analyze").disabled = true;
    $("btn-analyze").textContent = `分析中 ${s.done}/${s.total || "?"}`;
    return;
  }
  clearInterval(state.analyzeTimer);
  state.analyzeTimer = null;
  $("progress-bar").classList.add("hidden");
  $("btn-analyze").disabled = false;
  $("btn-analyze").textContent = "分析";
  if (s.error) toast("分析出错: " + s.error, 8000);
  else if (s.done > 0) toast(`分析完成：${s.done} 项`);
  await Promise.all([loadItems(), refreshStats()]);
}

async function startAnalyze() {
  await api("/api/analyze", { method: "POST" });
  if (!state.analyzeTimer) state.analyzeTimer = setInterval(pollAnalyze, 900);
  pollAnalyze();
}

async function applyNow() {
  const s = await api("/api/stats");
  const n = s.decided.delete || 0;
  if (!n) return;
  if (!confirm(`将把 ${n} 个标记为删除的文件（约 ${fmtSize(s.reclaimable_bytes)}）移入回收站目录 _pcull_trash/。\n文件不会被销毁，可随时从回收站找回。继续？`)) return;
  const result = await api("/api/apply", { method: "POST" });
  toast(`${result.summary}\n清单: ${result.manifest}`, 8000);
  await Promise.all([loadItems(), refreshStats()]);
}

/* ---------- library home / picker ---------- */
function homeVisible() {
  return !$("home").classList.contains("hidden");
}

function showHome() {
  closeDrawer();
  state.selected.clear();
  $("home").classList.remove("hidden");
  renderRecent();
}

function hideHome() {
  $("home").classList.add("hidden");
  $("home-progress").classList.add("hidden");
}

function fmtWhen(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const today = new Date();
  const days = Math.round((today.setHours(0, 0, 0, 0) - new Date(ts * 1000).setHours(0, 0, 0, 0)) / 86400000);
  if (days <= 0) return "今天";
  if (days === 1) return "昨天";
  if (days < 30) return `${days} 天前`;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function renderRecent() {
  const wrap = $("home-recents");
  wrap.innerHTML = "";
  let data;
  try {
    data = await api("/api/library/recent");
  } catch (e) {
    return;
  }
  if (!data.libraries.length) {
    const div = document.createElement("div");
    div.className = "home-empty";
    div.textContent = "还没有打开过的照片库";
    wrap.appendChild(div);
    return;
  }
  for (const lib of data.libraries) {
    const row = document.createElement("div");
    row.className = "home-lib" + (lib.path === state.library ? " current" : "");

    const meta = document.createElement("div");
    meta.className = "lib-meta";
    const name = document.createElement("div");
    name.className = "lib-name";
    name.textContent = "📁 " + lib.name;
    const path = document.createElement("div");
    path.className = "lib-path";
    path.textContent = lib.path;
    meta.append(name, path);

    const when = document.createElement("div");
    when.className = "lib-when";
    when.textContent = fmtWhen(lib.last_used);

    const openBtn = document.createElement("button");
    openBtn.className = "good sm";
    openBtn.textContent = "打开";
    openBtn.onclick = (e) => { e.stopPropagation(); openLibrary(lib.path); };

    const rmBtn = document.createElement("button");
    rmBtn.className = "ghost sm";
    rmBtn.textContent = "移除";
    rmBtn.onclick = async (e) => {
      e.stopPropagation();
      await api("/api/library/recent/drop", {
        method: "POST",
        body: JSON.stringify({ path: lib.path }),
      });
      renderRecent();
    };

    row.append(meta, when, openBtn, rmBtn);
    row.onclick = () => openLibrary(lib.path);
    wrap.appendChild(row);
  }
}

async function openLibrary(path) {
  if (!path) return;
  $("home-progress").classList.remove("hidden");
  $("home-progress-title").textContent = "打开中… " + path;
  $("home-progress-fill").style.width = "4%";
  $("home-progress-last").textContent = "";
  try {
    await api("/api/library/open", { method: "POST", body: JSON.stringify({ path }) });
  } catch (e) {
    let msg = "打开失败: " + e.message;
    if (/HTTP 409/.test(e.message)) msg = "正在分析中，请等当前分析完成后再切换照片库";
    else if (/HTTP 400/.test(e.message)) msg = "路径不存在或不可访问: " + path;
    toast(msg, 6000);
    $("home-progress").classList.add("hidden");
    return;
  }
  state.library = path;
  pollOpen();
}

function pollOpen() {
  clearInterval(state.openTimer);
  state.openTimer = setInterval(async () => {
    let s;
    try {
      s = await api("/api/analyze/status");
    } catch (e) { return; }
    if (s.running) {
      if (s.phase === "scanning") {
        $("home-progress-title").textContent = "扫描索引中…";
        $("home-progress-fill").style.width = "8%";
      } else {
        const pct = s.total ? Math.round((s.done / s.total) * 92) + 8 : 50;
        $("home-progress-title").textContent = `分析中 ${s.done}/${s.total || "?"}`;
        $("home-progress-fill").style.width = pct + "%";
        $("home-progress-last").textContent = s.last || "";
      }
      return;
    }
    clearInterval(state.openTimer);
    state.openTimer = null;
    if (s.error) {
      toast("处理出错: " + s.error, 8000);
      $("home-progress").classList.add("hidden");
      return;
    }
    $("home-progress-title").textContent = "完成";
    $("home-progress-fill").style.width = "100%";
    await enterLibrary();
    setTimeout(hideHome, 250);
  }, 800);
}

async function enterLibrary() {
  const cur = await api("/api/library/current");
  state.library = cur.library || state.library;
  $("lib-name").textContent = state.library
    ? state.library.split(/[\\/]/).pop() + " · 照片清理工作台"
    : "照片清理工作台";
  await Promise.all([loadItems(), refreshStats()]);
}

/* ---------- folder browser modal ---------- */
async function browseTo(path) {
  let data;
  try {
    data = await api("/api/browse?path=" + encodeURIComponent(path || ""));
  } catch (e) {
    toast("无法打开: " + e.message, 5000);
    return;
  }
  state.browserPath = data.path || "";
  $("browser-path").value = state.browserPath;
  $("browser-select").disabled = data.is_drive_list;
  $("browser-up").disabled = !data.parent;
  const list = $("browser-list");
  list.innerHTML = "";
  if (!data.entries.length) {
    const div = document.createElement("div");
    div.className = "home-empty";
    div.style.padding = "20px";
    div.textContent = "没有子文件夹";
    list.appendChild(div);
  }
  for (const entry of data.entries) {
    const row = document.createElement("div");
    row.className = "browser-item";
    const name = document.createElement("div");
    name.className = "bi-name";
    name.textContent = (data.is_drive_list ? "💽 " : "📁 ") + entry.name;
    const hint = document.createElement("div");
    hint.className = "bi-open";
    hint.textContent = "进入 ›";
    row.append(name, hint);
    row.onclick = () => browseTo(entry.path);
    list.appendChild(row);
  }
}

function openBrowser() {
  $("browser").classList.remove("hidden");
  browseTo(state.browserPath || "");
}

function closeBrowser() {
  $("browser").classList.add("hidden");
}

/* ---------- keyboard ---------- */
function onKeyDown(e) {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (!$("browser").classList.contains("hidden")) {
    if (e.key === "Escape") closeBrowser();
    return;
  }
  if (homeVisible()) return;
  const drawerOpen = !$("drawer").classList.contains("hidden");
  switch (e.key) {
    case "j": case "ArrowDown":
      e.preventDefault();
      if (!drawerOpen) setFocus(state.focusIndex + 1);
      break;
    case "k": case "ArrowUp":
      e.preventDefault();
      if (!drawerOpen) setFocus(state.focusIndex - 1);
      break;
    case "x": case "X":
      mark("delete");
      break;
    case "a": case "A":
      mark("keep");
      break;
    case "u": case "U": case "Backspace":
      mark(null);
      break;
    case "Enter":
      if (!drawerOpen && state.focusIndex >= 0 && state.items[state.focusIndex])
        openDrawer(state.items[state.focusIndex].id);
      break;
    case "Escape":
      closeDrawer();
      break;
  }
}

/* ---------- wiring ---------- */
function init() {
  $("tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-tab]");
    if (!btn) return;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.tab = btn.dataset.tab;
    closeDrawer();
    loadItems();
  });
  $("sort").addEventListener("change", (e) => {
    state.sort = e.target.value;
    loadItems();
  });
  $("main").addEventListener("click", gridClickDelegator);
  $("load-more").addEventListener("click", () => {
    state.offset += state.limit;
    loadItems(true);
  });
  $("bulk-delete").onclick = () => mark("delete");
  $("bulk-keep").onclick = () => mark("keep");
  $("bulk-clear").onclick = () => mark(null);
  $("drawer-close").onclick = closeDrawer;
  $("btn-apply").onclick = applyNow;
  $("btn-analyze").onclick = startAnalyze;
  document.addEventListener("keydown", onKeyDown);

  // library switching
  $("btn-switch").onclick = showHome;
  $("btn-browse").onclick = openBrowser;
  $("browser-close").onclick = closeBrowser;
  $("browser-up").onclick = () => {
    const cur = state.browserPath;
    const parent = cur.replace(/[\\/][^\\/]*[\\/]?$/, "");
    browseTo(parent && parent !== cur ? parent : "");
  };
  $("browser-select").onclick = () => {
    if (!state.browserPath) return;
    closeBrowser();
    openLibrary(state.browserPath);
  };
  $("browser-path").addEventListener("keydown", (e) => {
    if (e.key === "Enter") browseTo(e.target.value.trim());
  });
  $("btn-open-path").onclick = () => openLibrary($("home-path").value.trim());
  $("home-path").addEventListener("keydown", (e) => {
    if (e.key === "Enter") openLibrary(e.target.value.trim());
  });

  // startup: bound library -> review UI; none -> home picker
  (async () => {
    try {
      const cur = await api("/api/library/current");
      if (cur.library) {
        state.library = cur.library;
        $("lib-name").textContent =
          cur.library.split(/[\\/]/).pop() + " · 照片清理工作台";
        const m = location.hash.match(/photo=(\d+)/);
        await loadItems();
        if (m) openDrawer(parseInt(m[1], 10));
        refreshStats();
        // if a scan/analyze is running in the background, follow its progress
        const s = await api("/api/analyze/status");
        if (s.running && !state.analyzeTimer) {
          state.analyzeTimer = setInterval(pollAnalyze, 900);
        }
        return;
      }
    } catch (e) { /* fall through to home */ }
    showHome();
  })();
}

init();
