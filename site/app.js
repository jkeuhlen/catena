// Catena — canvas renderer for the citation web.
// Layout is precomputed at build time; this draws static coordinates with a
// small camera (pan/zoom), hover tracing, and a detail panel. No graph library.

const TYPE_COLOR = {
  source:    "#f1d486",
  document:  "#b98f3e",
  author:    "#c05a44",
  scripture: "#5a82c4",
};

const KIND_LABEL = {
  author: "Author · Council",
  scripture: "Scripture",
};

const canvas = document.getElementById("graph");
const ctx = canvas.getContext("2d");
let DPR = Math.min(window.devicePixelRatio || 1, 2);

const cam = { x: 0, y: 0, scale: 1 };       // world→screen: screen = (world - cam)*scale + center
let nodes = [], edges = [], adj = new Map(), nodeById = new Map();
let hovered = null;
const selectedIds = new Set();                // pinned nodes (multi-select)
const activeFilters = new Set();               // legend category filters
let detailNode = null;                         // node shown in the detail panel
let highlight = null;                         // Set of node ids to keep lit
let connectors = new Set();                    // bridge nodes linking 2+ selected
let intro = 0;                                // 0→1 entrance progress
let dirty = true;
let tween = null;                             // active camera fly-to, or null
let pulse = null;                             // {node, t0} expanding ring on focus

// ---- node visual scale ----------------------------------------------------
const radius = (n) => {
  if (n.type === "scripture") return 3 + Math.sqrt(n.degree) * 1.1;
  if (n.type === "author")    return 3.5 + Math.sqrt(n.degree) * 1.3;
  const base = n.is_source ? 14 : 3.2;
  return base + Math.sqrt(n.degree) * 1.5;
};
const colorOf = (n) => (n.is_source ? TYPE_COLOR.source : TYPE_COLOR[n.type]);

// ---- load -----------------------------------------------------------------
init();
async function init() {
  const data = await fetch("data/graph.json").then((r) => r.json());
  nodes = data.nodes;
  edges = data.edges;
  nodes.forEach((n) => nodeById.set(n.id, n));
  nodes.forEach((n) => adj.set(n.id, new Set()));
  edges.forEach((e) => { adj.get(e.source)?.add(e.target); adj.get(e.target)?.add(e.source); });

  buildStats(data.meta);
  buildSearch();
  buildLegend();
  resize();
  fitToContent();
  bindEvents();

  // entrance
  const loading = document.getElementById("loading");
  loading.classList.add("gone");
  setTimeout(() => loading.remove(), 800);
  const t0 = performance.now();
  (function step(t) {
    intro = Math.min(1, (t - t0) / 1400);
    dirty = true;
    draw();
    if (intro < 1) requestAnimationFrame(step);
  })(t0);

  // keep drawing only when needed
  (function loop(t) {
    if (tween) tween(t);
    if (pulse && t - pulse.t0 < PULSE_MS) dirty = true;
    if (dirty) draw();
    requestAnimationFrame(loop);
  })();
}

const PULSE_MS = 1100;

// smoothly move the camera to (wx, wy) at the given scale
function flyTo(wx, wy, scale, dur = 680) {
  const from = { x: cam.x, y: cam.y, scale: cam.scale };
  const to = { x: wx, y: wy, scale };
  const t0 = performance.now();
  tween = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = ease(k);
    cam.x = from.x + (to.x - from.x) * e;
    cam.y = from.y + (to.y - from.y) * e;
    cam.scale = from.scale + (to.scale - from.scale) * e;
    dirty = true;
    if (k >= 1) tween = null;
  };
}

// ---- camera helpers -------------------------------------------------------
const toScreen = (wx, wy) => [
  (wx - cam.x) * cam.scale + canvas.clientWidth / 2,
  (wy - cam.y) * cam.scale + canvas.clientHeight / 2,
];
const toWorld = (sx, sy) => [
  (sx - canvas.clientWidth / 2) / cam.scale + cam.x,
  (sy - canvas.clientHeight / 2) / cam.scale + cam.y,
];

function fitToContent() {
  const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  cam.x = (minX + maxX) / 2;
  cam.y = (minY + maxY) / 2;
  const pad = 1.18;
  cam.scale = Math.min(
    canvas.clientWidth / ((maxX - minX) * pad),
    canvas.clientHeight / ((maxY - minY) * pad)
  );
  dirty = true;
}

// ---- draw -----------------------------------------------------------------
function resize() {
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = canvas.clientWidth * DPR;
  canvas.height = canvas.clientHeight * DPR;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  dirty = true;
}

function draw() {
  dirty = false;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  ctx.clearRect(0, 0, W, H);

  const lit = (id) => !highlight || highlight.has(id);

  // edges
  ctx.lineWidth = 1;
  for (const e of edges) {
    const a = nodeById.get(e.source), b = nodeById.get(e.target);
    const [ax, ay] = toScreen(a.x, a.y), [bx, by] = toScreen(b.x, b.y);
    const on = lit(e.source) && lit(e.target);
    const tgt = nodeById.get(e.target);
    const col = colorOf(tgt.is_source ? a : tgt);
    const baseAlpha = e.type === "cites" ? 0.22 : 0.13;
    ctx.strokeStyle = hexA(col, (on ? baseAlpha : 0.025) * intro);
    ctx.lineWidth = on && highlight ? 1.3 : 0.8;
    // gentle arc for an organic, manuscript feel
    const mx = (ax + bx) / 2, my = (ay + by) / 2;
    const dx = bx - ax, dy = by - ay;
    const off = 0.07;
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.quadraticCurveTo(mx - dy * off, my + dx * off, bx, by);
    ctx.stroke();
  }

  // nodes
  const smallNeighbourhood = highlight && highlight.size <= 30;
  for (const n of nodes) {
    const [x, y] = toScreen(n.x, n.y);
    const r = radius(n) * (0.4 + 0.6 * ease(intro));
    const on = lit(n.id);
    const col = colorOf(n);
    const isSel = selectedIds.has(n.id);
    const isBridge = connectors.has(n.id);

    if (n.is_source || isSel || (on && n === hovered)) {
      const glow = ctx.createRadialGradient(x, y, 0, x, y, r * 4.5);
      glow.addColorStop(0, hexA(col, 0.5 * intro));
      glow.addColorStop(1, hexA(col, 0));
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(x, y, r * 4.5, 0, Math.PI * 2); ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = hexA(col, (on ? 1 : 0.16) * intro);
    ctx.fill();
    if (on) {
      ctx.lineWidth = 1;
      ctx.strokeStyle = hexA("#0c0a07", 0.6 * intro);
      ctx.stroke();
    }
    // pinned nodes get a bright ring; bridge nodes a subtler gold ring
    if (isSel) {
      ctx.beginPath(); ctx.arc(x, y, r + 3.5, 0, Math.PI * 2);
      ctx.strokeStyle = hexA("#f4e4bd", 0.95 * intro); ctx.lineWidth = 2; ctx.stroke();
    } else if (isBridge) {
      ctx.beginPath(); ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
      ctx.strokeStyle = hexA("#d8b65f", 0.7 * intro); ctx.lineWidth = 1.2; ctx.stroke();
    }
  }

  // labels — major works always; plus pinned, bridges, hovered, the inspected
  // node, and (for a single small neighbourhood) its members.
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  for (const n of nodes) {
    const big = n.type === "document" && n.degree >= 16;
    const isSel = selectedIds.has(n.id);
    const isBridge = connectors.has(n.id);
    const member = highlight && highlight.has(n.id);
    const neighbourLabel = smallNeighbourhood && member && selectedIds.size <= 1;
    const filterLabel = activeFilters.size && member && n.degree >= 12;
    const show = isSel || isBridge || n === hovered || n === detailNode ||
                 neighbourLabel || filterLabel || (big && (!highlight || member));
    if (!show) continue;
    const [x, y] = toScreen(n.x, n.y);
    const r = radius(n);
    const label = n.label || n.id;
    const emphatic = isSel || isBridge || n === hovered || n === detailNode;
    const size = n.is_source ? 19 : (big || emphatic) ? 14.5 : 13;
    ctx.font = `${n.is_source || isSel ? 600 : 500} ${size}px "Cormorant Garamond", serif`;
    const alpha = (emphatic ? 1 : 0.75) * intro;
    ctx.fillStyle = hexA("#0c0a07", 0.85 * alpha);
    ctx.fillText(label, x + r + 6 + 0.6, y + 0.6);  // shadow
    ctx.fillStyle = hexA(isSel ? "#f7ead0" : n.is_source ? "#f4e4bd" : "#ece2cd", alpha);
    ctx.fillText(label, x + r + 6, y);
  }

  // focus pulse — an expanding ring that announces the searched node
  if (pulse) {
    const k = (performance.now() - pulse.t0) / PULSE_MS;
    if (k >= 1) { pulse = null; }
    else {
      const [px, py] = toScreen(pulse.node.x, pulse.node.y);
      const r0 = radius(pulse.node);
      for (const lag of [0, 0.33]) {
        const kk = k - lag;
        if (kk <= 0) continue;
        ctx.beginPath();
        ctx.arc(px, py, r0 + ease(kk) * 46, 0, Math.PI * 2);
        ctx.strokeStyle = hexA("#f1d486", (1 - kk) * 0.55);
        ctx.lineWidth = 1.6;
        ctx.stroke();
      }
    }
  }
}

const ease = (t) => 1 - Math.pow(1 - t, 3);
function hexA(hex, a) {
  const v = parseInt(hex.slice(1), 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${a})`;
}

// ---- hit testing ----------------------------------------------------------
function nodeAt(sx, sy) {
  let best = null, bestD = Infinity;
  for (const n of nodes) {
    const [x, y] = toScreen(n.x, n.y);
    const r = radius(n) + 4;
    const d = (x - sx) ** 2 + (y - sy) ** 2;
    if (d <= r * r && d < bestD) { best = n; bestD = d; }
  }
  return best;
}

// Which legend category a node belongs to.
function nodeCategory(n) {
  if (n.is_source) return "source";
  return n.type;   // "document" | "author" | "scripture"
}
const matchesFilter = (n) => activeFilters.has(nodeCategory(n));

// Highlight from the pinned selection (also fills `connectors`):
//  - one selected: that node + its neighbourhood
//  - 2+ selected:  the connecting subgraph — the selected nodes plus the
//                  "bridge" nodes adjacent to two or more of them
function selectionHighlight() {
  connectors = new Set();
  if (selectedIds.size === 0) return null;
  if (selectedIds.size === 1) {
    const id = [...selectedIds][0];
    return new Set([id, ...adj.get(id)]);
  }
  const h = new Set(selectedIds);
  const seen = new Map();   // candidate -> # of distinct selected it touches
  for (const s of selectedIds) {
    for (const nb of adj.get(s)) {
      if (selectedIds.has(nb)) continue;        // selected↔selected handled by membership
      seen.set(nb, (seen.get(nb) || 0) + 1);
    }
  }
  for (const [nb, c] of seen) {
    if (c >= 2) { connectors.add(nb); h.add(nb); }
  }
  return h;
}

// Recompute what stays lit by combining the pin-selection, the legend filters,
// and (when nothing else is active) a hover preview.
function computeHighlight() {
  const sel = selectionHighlight();   // also populates `connectors`
  let filt = null;
  if (activeFilters.size) {
    filt = new Set();
    for (const n of nodes) if (matchesFilter(n)) filt.add(n.id);
  }
  if (sel && filt) highlight = new Set([...sel, ...filt]);
  else if (sel) highlight = sel;
  else if (filt) highlight = filt;
  else highlight = hovered ? new Set([hovered.id, ...adj.get(hovered.id)]) : null;
}

// ---- interaction ----------------------------------------------------------
function bindEvents() {
  window.addEventListener("resize", () => { resize(); });

  let dragging = false, moved = false, lastX = 0, lastY = 0;
  canvas.addEventListener("mousedown", (e) => {
    dragging = true; moved = false; lastX = e.clientX; lastY = e.clientY;
    canvas.classList.add("dragging");
  });
  window.addEventListener("mouseup", () => { dragging = false; canvas.classList.remove("dragging"); });
  window.addEventListener("mousemove", (e) => {
    if (dragging) {
      const dx = e.clientX - lastX, dy = e.clientY - lastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
      cam.x -= dx / cam.scale; cam.y -= dy / cam.scale;
      lastX = e.clientX; lastY = e.clientY; dirty = true;
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const n = nodeAt(e.clientX - rect.left, e.clientY - rect.top);
    if (n !== hovered) {
      hovered = n;
      // hover preview only when idle (nothing pinned and no filter active)
      if (!selectedIds.size && !activeFilters.size) computeHighlight();
      canvas.classList.toggle("pointing", !!n);
      dirty = true;
    }
  });

  canvas.addEventListener("click", (e) => {
    if (moved) return;
    const rect = canvas.getBoundingClientRect();
    const n = nodeAt(e.clientX - rect.left, e.clientY - rect.top);
    toggleSelect(n);   // null (empty space) clears the selection
  });

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const [wx, wy] = toWorld(e.clientX - rect.left, e.clientY - rect.top);
    const factor = Math.exp(-e.deltaY * 0.0012);
    cam.scale = Math.max(0.05, Math.min(8, cam.scale * factor));
    // keep the cursor anchored over the same world point
    const [sx, sy] = toScreen(wx, wy);
    cam.x += (e.clientX - rect.left - sx) / -cam.scale;
    cam.y += (e.clientY - rect.top - sy) / -cam.scale;
    dirty = true;
  }, { passive: false });

  // closing the detail panel hides it but keeps the pinned selection
  document.getElementById("detail-close").addEventListener("click", () => {
    detailNode = null; showDetail(null);
  });

  // selection bar: remove one chip, or clear all
  document.getElementById("selection").addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) { toggleSelect(nodeById.get(chip.dataset.id)); return; }
    if (e.target.closest("#selection-clear")) clearSelection();
  });

  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (document.activeElement === document.getElementById("search-input")) return;
    clearFilters();
    clearSelection();   // also recomputes highlight & redraws
  });
}

// ---- selection -----------------------------------------------------------
// Clicking a node pins it; clicking again unpins it. The detail panel always
// reflects the most recently clicked node, without disturbing the pinned set.
function toggleSelect(n) {
  if (!n) { clearSelection(); return; }
  if (selectedIds.has(n.id)) {
    selectedIds.delete(n.id);
    detailNode = selectedIds.size ? nodeById.get([...selectedIds].at(-1)) : null;
  } else {
    selectedIds.add(n.id);
    detailNode = n;
  }
  afterSelectionChange();
}

function pin(n) {                 // add (if absent) and inspect — used by search
  if (!n) return;
  selectedIds.add(n.id);
  detailNode = n;
  afterSelectionChange();
}

function clearSelection() {
  selectedIds.clear();
  detailNode = null;
  afterSelectionChange();
}

function afterSelectionChange() {
  computeHighlight();
  showDetail(detailNode);
  renderSelectionBar();
  dirty = true;
}

// ---- detail panel --------------------------------------------------------
function showDetail(n) {
  const panel = document.getElementById("detail");
  if (!n) { panel.hidden = true; return; }

  document.getElementById("detail-kind").textContent =
    n.is_source ? "The reigning encyclical" :
    n.type === "document" ? (n.doc_type || "Magisterial work") :
    KIND_LABEL[n.type] || n.type;
  document.getElementById("detail-title").textContent = n.label || n.id;

  const meta = document.getElementById("detail-meta");
  meta.innerHTML = "";
  // Incoming citations: documents are cited via "cites"; scripture via
  // "cites_scripture". Edge weight is the citing-side multiplicity (e.g. one
  // encyclical referring to a passage in three different footnotes → weight 3),
  // so the source count and total can differ.
  const incomingType = n.type === "scripture" ? "cites_scripture" : "cites";
  const incoming = edges.filter((e) => e.target === n.id && e.type === incomingType);
  const citedBy = incoming.length;
  const citedTimes = incoming.reduce((s, e) => s + (e.weight || 1), 0);
  const cites = edges.filter((e) => e.source === n.id && e.type === "cites").length;
  const unit = n.type === "scripture" ? "encyclical" : "work";
  const rows = [];
  if (n.type === "document" && n.author) rows.push(["Author", n.author]);
  if (n.type === "document" && n.date) rows.push(["Promulgated", n.date]);
  if (n.type === "scripture") rows.push(["Testament", n.testament === "OT" ? "Old Testament" : "New Testament"]);
  if (n.type === "author") rows.push(["Works in view", String(adj.get(n.id).size)]);
  if (citedBy) rows.push(["Cited by",
    citedTimes === citedBy
      ? `${citedBy} ${unit}${citedBy > 1 ? "s" : ""}`
      : `${citedBy} ${unit}${citedBy > 1 ? "s" : ""} (${citedTimes} citations)`]);
  if (cites) rows.push(["References", `${cites} work${cites > 1 ? "s" : ""}`]);
  if (n.type === "document" && !n.in_corpus && !citedBy) rows.push(["Status", "Referenced"]);
  for (const [k, v] of rows) {
    const div = document.createElement("div");
    div.innerHTML = `<dt>${k}</dt><dd>${v}</dd>`;
    meta.appendChild(div);
  }

  const link = document.getElementById("detail-link");
  if (n.url) { link.href = n.url; link.hidden = false; }
  else link.hidden = true;

  panel.hidden = false;
}

// ---- selection bar (chips + connection summary) --------------------------
function renderSelectionBar() {
  const bar = document.getElementById("selection");
  if (!selectedIds.size) { bar.hidden = true; return; }

  const sel = [...selectedIds].map((id) => nodeById.get(id));
  const chips = sel.map((n) => {
    const col = colorOf(n);
    return `<button class="chip" data-id="${escapeHtml(n.id)}" title="Remove from selection">
      <span class="chip__dot" style="background:${col};color:${col}"></span>
      <span class="chip__name">${escapeHtml(n.label || n.id)}</span>
      <span class="chip__x" aria-hidden="true">×</span></button>`;
  }).join("");

  let summary = "";
  if (selectedIds.size >= 2) {
    const links = [...connectors].map((id) => nodeById.get(id));
    summary = links.length
      ? `<p class="selection__summary">Linked through <strong>${links.length}</strong>: `
        + links.slice(0, 6).map((n) => escapeHtml(n.label || n.id)).join(" · ")
        + (links.length > 6 ? " …" : "") + "</p>"
      : `<p class="selection__summary selection__summary--none">No direct connection in this corpus.</p>`;
  }

  bar.innerHTML =
    `<div class="selection__chips">${chips}` +
    `<button class="selection__clear" id="selection-clear">Clear</button></div>${summary}`;
  bar.hidden = false;
}

// fly the camera so the node and its neighbours fill the view; pin + inspect it
function focusNode(n) {
  if (!n) return;
  const ids = new Set([n.id, ...adj.get(n.id)]);
  const pts = nodes.filter((m) => ids.has(m.id));
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const pad = 2.6;
  const span = Math.max(maxX - minX, maxY - minY, 60);
  // keep context: cap the zoom so peripheral nodes don't empty the screen
  const scale = Math.max(0.5, Math.min(1.6,
    Math.min(canvas.clientWidth, canvas.clientHeight) / (span * pad)));
  flyTo(cx, cy, scale);
  pin(n);
  pulse = { node: n, t0: performance.now() };
}

// ---- search ---------------------------------------------------------------
const TAG = {
  source: "Encyclical", author: "Author · Council", scripture: "Scripture",
};
const tagFor = (n) =>
  n.is_source ? "Encyclical" :
  n.type === "document" ? (n.doc_type || "Work") :
  TAG[n.type] || n.type;

function buildSearch() {
  const input = document.getElementById("search-input");
  const list = document.getElementById("search-results");
  const clear = document.getElementById("search-clear");
  let results = [], active = -1;

  const close = () => {
    list.hidden = true; results = []; active = -1;
    input.setAttribute("aria-expanded", "false");
  };

  const run = (raw) => {
    const q = raw.trim().toLowerCase();
    clear.hidden = !raw;
    if (!q) { close(); return; }
    const scored = [];
    for (const n of nodes) {
      const label = (n.label || n.id).toLowerCase();
      const i = label.indexOf(q);
      if (i < 0) continue;
      scored.push([n, (i === 0 ? 0 : 1e6) + i * 1000 - Math.min(n.degree, 99)]);
    }
    scored.sort((a, b) => a[1] - b[1]);
    results = scored.slice(0, 8).map((s) => s[0]);
    active = results.length ? 0 : -1;
    render(q);
  };

  const render = (q) => {
    if (!results.length) {
      list.innerHTML = `<li class="search__empty">Nothing found for “${escapeHtml(q)}”</li>`;
    } else {
      list.innerHTML = results.map((n, idx) => {
        const label = n.label || n.id;
        const i = label.toLowerCase().indexOf(q);
        const mk = i < 0 ? escapeHtml(label)
          : escapeHtml(label.slice(0, i)) + "<b>" + escapeHtml(label.slice(i, i + q.length)) +
            "</b>" + escapeHtml(label.slice(i + q.length));
        const col = colorOf(n);
        return `<li role="option" data-idx="${idx}" aria-selected="${idx === active}">
          <span class="dot" style="background:${col};color:${col}"></span>
          <span class="name">${mk}</span>
          <span class="tag">${tagFor(n)}</span></li>`;
      }).join("");
    }
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };

  const choose = (n) => {
    if (!n) return;
    input.value = n.label || n.id;
    close();
    focusNode(n);
    input.blur();
  };

  input.addEventListener("input", () => run(input.value));
  input.addEventListener("focus", () => { if (input.value.trim()) run(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!results.length) return;
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : results.length - 1)) % results.length;
      render(input.value.trim().toLowerCase());
    } else if (e.key === "Enter") {
      if (active >= 0) choose(results[active]);
    } else if (e.key === "Escape") {
      if (list.hidden) { input.value = ""; clear.hidden = true; input.blur(); }
      else close();
    }
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[data-idx]");
    if (li) { e.preventDefault(); choose(results[+li.dataset.idx]); }
  });
  clear.addEventListener("click", () => { input.value = ""; close(); clear.hidden = true; input.focus(); });
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) close(); });
  // "/" focuses search from anywhere
  window.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); }
  });
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---- legend filters -------------------------------------------------------
function buildLegend() {
  const counts = { source: 0, document: 0, author: 0, scripture: 0 };
  for (const n of nodes) counts[nodeCategory(n)] = (counts[nodeCategory(n)] || 0) + 1;
  for (const btn of document.querySelectorAll(".legend__item")) {
    const cat = btn.dataset.cat;
    const span = btn.querySelector(".legend__count");
    if (span) span.textContent = (counts[cat] || 0).toLocaleString();
    btn.addEventListener("click", () => toggleFilter(cat));
  }
}

function toggleFilter(cat) {
  if (activeFilters.has(cat)) activeFilters.delete(cat);
  else activeFilters.add(cat);
  for (const btn of document.querySelectorAll(".legend__item")) {
    btn.setAttribute("aria-pressed", String(activeFilters.has(btn.dataset.cat)));
  }
  computeHighlight();
  dirty = true;
}

function clearFilters() {
  if (!activeFilters.size) return;
  activeFilters.clear();
  for (const btn of document.querySelectorAll(".legend__item")) btn.setAttribute("aria-pressed", "false");
}

// ---- stats ----------------------------------------------------------------
function buildStats(meta) {
  const el = document.getElementById("stats");
  const items = [
    [meta.documents, "Works"],
    [meta.authors, "Authors"],
    [meta.scripture, "Scriptures"],
    [meta.edges, "Threads"],
  ];
  el.innerHTML = items
    .map(([n, l]) => `<div class="stat"><span class="num">${(n || 0).toLocaleString()}</span><span class="lbl">${l}</span></div>`)
    .join("");
}
