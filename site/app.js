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
// Directed adjacency, split by edge type. Needed because "References" vs
// "Cited by" depends on edge direction, not just neighbour category — two
// source encyclicals citing each other would otherwise fall into the gap.
const outBy = new Map();   // id -> { cites:Set, authored_by:Set, cites_scripture:Set }
const inBy  = new Map();   // id -> same shape; incoming edges
let hovered = null;
const selectedIds = new Set();                // pinned nodes (multi-select)
const activeFilters = new Set();               // legend category filters
let detailNode = null;                         // node shown in the detail panel
const detailFilters = new Set();               // category filters scoped to detailNode
let detailRowIds = new Map();                  // cat -> Set<id> for the rows currently in the panel
let highlight = null;                         // Set of node ids to keep lit
let connectors = new Set();                    // bridge nodes linking 2+ selected
let intro = 0;                                // 0→1 entrance progress
let dirty = true;
let tween = null;                             // active camera fly-to, or null
let pulse = null;                             // {node, t0} expanding ring on focus

// ---- views ----------------------------------------------------------------
// Two views share one corpus and one renderer; only the layout, the camera,
// and the visibility rules change. Each node carries its precomputed Explore
// coordinates in (n.x, n.y) — immutable. Per-view targets live in `targets`
// keyed by view, and the renderer reads from (n._x, n._y, n._op) which we
// lerp toward the active view's target each frame on view-switch.
const VIEWS = ["explore", "timeline"];
const state = { view: "explore" };
const targets = { explore: new Map(), timeline: new Map() };
let viewTween = null;        // {from:Map, t0, dur} during a view transition
const VIEW_TWEEN_MS = 600;
// Year window used for the Timeline vertical axis.
let YEAR_MIN = 1500, YEAR_MAX = 2030;
// World height of the chronological layout — chosen so the existing camera
// scale ≈ 1 frames a comfortable couple of centuries on screen.
const TIMELINE_H = 4200;
const TIMELINE_W = 2400;     // horizontal spread within the widest year

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
  nodes.forEach((n) => {
    adj.set(n.id, new Set());
    outBy.set(n.id, { cites: new Set(), authored_by: new Set(), cites_scripture: new Set() });
    inBy.set(n.id,  { cites: new Set(), authored_by: new Set(), cites_scripture: new Set() });
  });
  edges.forEach((e) => {
    adj.get(e.source)?.add(e.target); adj.get(e.target)?.add(e.source);
    outBy.get(e.source)?.[e.type]?.add(e.target);
    inBy.get(e.target)?.[e.type]?.add(e.source);
  });

  // initialise per-node draw state from the precomputed Explore layout
  for (const n of nodes) {
    n._x = n.x; n._y = n.y; n._op = 1;
    targets.explore.set(n.id, { x: n.x, y: n.y, op: 1 });
  }
  // Year window for the timeline axis. Anchored to the earliest *seed* — the
  // citation corpus reaches back to the 1500s, but the seeds (the works the
  // visualisation is actually about) all live 1891→now, so this is where the
  // axis density should pay off. Older citations clamp to the top of the axis;
  // a small "before 1880" marker would be a nice follow-up.
  const seedYears = nodes.filter((n) => n.is_source && n.year).map((n) => n.year);
  const allYears = nodes.filter((n) => n.type === "document" && n.year).map((n) => n.year);
  if (seedYears.length) {
    YEAR_MIN = Math.floor(Math.min(...seedYears) / 10) * 10;
    YEAR_MAX = Math.max(new Date().getFullYear(), Math.max(...allYears)) + 1;
  }
  buildTimelineTargets();

  buildStats(data.meta);
  buildSearch();
  buildLegend();
  buildViewSwitcher();
  resize();
  fitToContent();
  bindEvents();
  readHashView();   // restore #view=… on load

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
  requestAnimationFrame(function loop(t) {
    const camMoving = !!tween;
    if (tween) tween(t);
    tickPositions(t);
    if (pulse && t - pulse.t0 < PULSE_MS) dirty = true;
    if (dirty) draw();
    // the in-canvas time axis redraws each frame; no DOM ruler to update.
    requestAnimationFrame(loop);
  });
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
    clampCamera();
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

  // Chronological views: paint the time axis BEFORE nodes so labels and
  // gridlines sit behind the data, hugging the swarm column.
  if (state.view !== "explore") drawTimeAxis(W, H);

  const lit = (id) => !highlight || highlight.has(id);

  // Edges, drawn in three z-tiers so the selection's threads paint on top of
  // the background instead of being criss-crossed by it:
  //   tier 0 — unlit (faint wash)
  //   tier 1 — lit but not touching the pinned selection (neighbour↔neighbour)
  //   tier 2 — incident to a pinned/hovered focus node (the "selection web")
  // When nothing is pinned, hovered/filter-only highlights fall through tier 1.
  const focusIds = selectedIds.size ? selectedIds
                 : (hovered && !activeFilters.size && !detailNode ? new Set([hovered.id]) : null);
  const tiers = [[], [], []];
  for (const e of edges) {
    const on = lit(e.source) && lit(e.target);
    let tier = on ? 1 : 0;
    if (on && focusIds && (focusIds.has(e.source) || focusIds.has(e.target))) tier = 2;
    tiers[tier].push(e);
  }
  for (let t = 0; t < 3; t++) {
    for (const e of tiers[t]) {
      const a = nodeById.get(e.source), b = nodeById.get(e.target);
      const [ax, ay] = toScreen(a._x, a._y), [bx, by] = toScreen(b._x, b._y);
      const tgt = nodeById.get(e.target);
      const col = colorOf(tgt.is_source ? a : tgt);
      const baseAlpha = e.type === "cites" ? 0.22 : 0.13;
      let alpha, width;
      if (t === 0)      { alpha = highlight ? 0.012 : baseAlpha; width = 0.7; }
      else if (t === 1) { alpha = baseAlpha * 0.9;               width = 1.1; }
      else              { alpha = Math.min(0.95, baseAlpha * 2.6); width = 1.7; }
      // edges fade with whichever endpoint is more hidden — keeps the threads
      // from being visible while their nodes are gone in Timeline.
      const endpointOp = Math.min(a._op ?? 1, b._op ?? 1);
      ctx.strokeStyle = hexA(t === 2 ? "#f4e4bd" : col, alpha * intro * endpointOp);
      ctx.lineWidth = width;
      // gentle arc for an organic, manuscript feel
      const mx = (ax + bx) / 2, my = (ay + by) / 2;
      const dx = bx - ax, dy = by - ay;
      const off = 0.07;
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.quadraticCurveTo(mx - dy * off, my + dx * off, bx, by);
      ctx.stroke();
    }
  }

  // nodes
  const smallNeighbourhood = highlight && highlight.size <= 30;
  for (const n of nodes) {
    if ((n._op ?? 1) <= 0.01) continue;
    const [x, y] = toScreen(n._x, n._y);
    const r = radius(n) * (0.4 + 0.6 * ease(intro));
    const on = lit(n.id);
    const col = colorOf(n);
    const isSel = selectedIds.has(n.id);
    const isBridge = connectors.has(n.id);
    const op = n._op ?? 1;

    if (n.is_source || isSel || (on && n === hovered)) {
      const glow = ctx.createRadialGradient(x, y, 0, x, y, r * 4.5);
      glow.addColorStop(0, hexA(col, 0.5 * intro * op));
      glow.addColorStop(1, hexA(col, 0));
      ctx.fillStyle = glow;
      ctx.beginPath(); ctx.arc(x, y, r * 4.5, 0, Math.PI * 2); ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = hexA(col, (on ? 1 : 0.16) * intro * op);
    ctx.fill();
    if (on) {
      ctx.lineWidth = 1;
      ctx.strokeStyle = hexA("#0c0a07", 0.6 * intro * op);
      ctx.stroke();
    }
    // pinned nodes get a bright ring; bridge nodes a subtler gold ring
    if (isSel) {
      ctx.beginPath(); ctx.arc(x, y, r + 3.5, 0, Math.PI * 2);
      ctx.strokeStyle = hexA("#f4e4bd", 0.95 * intro * op); ctx.lineWidth = 2; ctx.stroke();
    } else if (isBridge) {
      ctx.beginPath(); ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
      ctx.strokeStyle = hexA("#d8b65f", 0.7 * intro * op); ctx.lineWidth = 1.2; ctx.stroke();
    }
  }

  // labels — major works always; plus pinned, bridges, hovered, the inspected
  // node, and (for a single small neighbourhood) its members.
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  // In the chronological views the per-year swarm gets crowded fast, so we
  // suppress the "always-label big works" rule and let users surface labels
  // by zooming, hovering, or selecting. Sources stay labelled — they're the
  // narrative spine of the view.
  const inChrono = state.view !== "explore";
  for (const n of nodes) {
    const big = n.type === "document" && n.degree >= 16;
    const isSel = selectedIds.has(n.id);
    const isBridge = connectors.has(n.id);
    const member = highlight && highlight.has(n.id);
    const neighbourLabel = smallNeighbourhood && member && selectedIds.size <= 1;
    const filterLabel = activeFilters.size && member && n.degree >= 12;
    const ambientLabel = inChrono
      ? (n.is_source && cam.scale > 0.45)        // sources only, and only once zoomed in a bit
      : (big && (!highlight || member));
    const show = isSel || isBridge || n === hovered || n === detailNode ||
                 neighbourLabel || filterLabel || ambientLabel;
    if (!show) continue;
    if ((n._op ?? 1) <= 0.01) continue;
    const [x, y] = toScreen(n._x, n._y);
    const r = radius(n);
    const label = n.label || n.id;
    const emphatic = isSel || isBridge || n === hovered || n === detailNode;
    const size = n.is_source ? 19 : (big || emphatic) ? 14.5 : 13;
    ctx.font = `${n.is_source || isSel ? 600 : 500} ${size}px "Cormorant Garamond", serif`;
    const alpha = (emphatic ? 1 : 0.75) * intro * (n._op ?? 1);
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
      const [px, py] = toScreen(pulse.node._x, pulse.node._y);
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

// In-canvas time axis: horizontal decade lines across the viewport plus a
// labeled stack of year ticks on the left edge of the screen (pinned in
// screen-space, drifting only in y). Years are picked so roughly 8-14 ticks
// are visible at the current zoom.
function drawTimeAxis(W, H) {
  const years = Math.max(1, (H / cam.scale) * (YEAR_MAX - YEAR_MIN) / TIMELINE_H);
  let step = 10;
  if (years > 350) step = 100;
  else if (years > 140) step = 50;
  else if (years > 60) step = 20;
  else if (years > 30) step = 10;
  else step = 5;
  const yStart = Math.ceil(YEAR_MIN / step) * step;
  // gridlines first (very faint)
  ctx.lineWidth = 1;
  for (let y = yStart; y <= YEAR_MAX; y += step) {
    const [, sy] = toScreen(0, yearToY(y));
    if (sy < -1 || sy > H + 1) continue;
    const major = (y % 100 === 0);
    ctx.strokeStyle = `rgba(216,182,95,${major ? 0.16 : 0.08})`;
    ctx.beginPath();
    ctx.moveTo(0, sy);
    ctx.lineTo(W, sy);
    ctx.stroke();
  }
  // labels — left-edge column, padded clear of the masthead and the legend
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  for (let y = yStart; y <= YEAR_MAX; y += step) {
    const [, sy] = toScreen(0, yearToY(y));
    if (sy < 80 || sy > H - 80) continue;
    const major = (y % 100 === 0);
    const px = 22;
    ctx.font = `${major ? 600 : 500} ${major ? 13 : 11}px "Cormorant Garamond", serif`;
    ctx.fillStyle = `rgba(${major ? "244,228,189" : "182,169,136"},${major ? 0.85 : 0.55})`;
    ctx.fillText(`${y}`, px, sy);
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
    if ((n._op ?? 1) <= 0.05) continue;
    const [x, y] = toScreen(n._x, n._y);
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

// Connection rows for the detail panel, computed from directed edges so that
// "References" follows outgoing cites (incl. to source encyclicals) and "Cited
// by" follows incoming cites from source encyclicals. Returned as {cat, ids}
// pairs — `cat` still drives the swatch color and the legend category.
function detailRows(n) {
  const rows = [];
  const o = outBy.get(n.id), i = inBy.get(n.id);
  if (n.type === "document") {
    // Incoming citations from source encyclicals → "Cited by"
    const citedBy = new Set();
    for (const id of i.cites) if (nodeById.get(id)?.is_source) citedBy.add(id);
    if (citedBy.size) rows.push({ key: "source", label: "Cited by", unit: "encyclical", cat: "source", ids: citedBy });
    // Outgoing citations to any document (source or not) → "References"
    if (o.cites.size) rows.push({ key: "document", label: "References", unit: "work", cat: "document", ids: new Set(o.cites) });
    if (o.authored_by.size) rows.push({ key: "author", label: "Authors & councils", unit: "person", cat: "author", ids: new Set(o.authored_by) });
    if (o.cites_scripture.size) rows.push({ key: "scripture", label: "Scripture", unit: "passage", cat: "scripture", ids: new Set(o.cites_scripture) });
    return rows;
  }
  // For author / scripture nodes the only edges are incoming from documents;
  // bucket those incoming sources by whether they're encyclical seeds or not.
  const incoming = n.type === "author" ? i.authored_by : i.cites_scripture;
  const srcs = new Set(), docs = new Set();
  for (const id of incoming) (nodeById.get(id)?.is_source ? srcs : docs).add(id);
  if (srcs.size) rows.push({ key: "source", label: "Cited in", unit: "encyclical", cat: "source", ids: srcs });
  if (docs.size) rows.push({ key: "document", label: "Cited in", unit: "work", cat: "document", ids: docs });
  return rows;
}

// Neighbours of `n` grouped by legend category, used by the detail panel.
function neighboursByCategory(n) {
  const out = { source: [], document: [], author: [], scripture: [] };
  for (const id of adj.get(n.id)) {
    const m = nodeById.get(id);
    out[nodeCategory(m)].push(m);
  }
  return out;
}

// Recompute what stays lit by combining the pin-selection, the legend filters,
// detail-panel category filters, and (when nothing else is active) a hover
// preview. The detail filters narrow the detail node's neighbourhood to just
// the chosen categories — they replace the size-1 selection's full halo.
function computeHighlight() {
  const sel = selectionHighlight();   // also populates `connectors`
  let filt = null;
  if (activeFilters.size) {
    filt = new Set();
    for (const n of nodes) if (matchesFilter(n)) filt.add(n.id);
  }
  let detailH = null;
  if (detailNode && detailFilters.size) {
    // Use the exact id sets stashed when the panel was rendered, so the
    // "References" toggle on a source encyclical still includes other source
    // encyclicals it cites (those have category "source", not "document").
    detailH = new Set([detailNode.id]);
    for (const cat of detailFilters) {
      const ids = detailRowIds.get(cat);
      if (ids) for (const id of ids) detailH.add(id);
    }
  }
  // detailH narrows: if it's active and the selection is just the detail node,
  // prefer the narrower set over the full neighbourhood.
  let base = sel;
  if (detailH && sel && selectedIds.size === 1 && selectedIds.has(detailNode.id)) {
    base = detailH;
  } else if (detailH && sel) {
    base = new Set([...sel, ...detailH]);
  } else if (detailH) {
    base = detailH;
  }
  if (base && filt) highlight = new Set([...base, ...filt]);
  else if (base) highlight = base;
  else if (filt) highlight = filt;
  else highlight = hovered ? new Set([hovered.id, ...adj.get(hovered.id)]) : null;
}

// ---- view targets / layout solvers ---------------------------------------
// Map each node to its (x, y, opacity) for the given view. Authors/scripture
// don't sit on the chronological axis — they fade out in Timeline
// but their last position is preserved so they animate gently to the wings.
const yearToY = (year) =>
  (TIMELINE_H * (year - YEAR_MIN)) / (YEAR_MAX - YEAR_MIN) - TIMELINE_H / 2;

// Beeswarm packing: place each year-bucket as a horizontal swarm centered on
// the year's y-coordinate, stacking into a small number of lanes when one
// row would overflow `maxWidth`. Bigger-degree (more cited) works sort first
// so they end up nearest the axis center — the eye lands on what matters.
function beeswarmLayout(buckets, target, { pitch, lanePitch, maxWidth, rootId = null }) {
  const maxCols = Math.max(2, Math.floor(maxWidth / pitch));
  for (const [year, row] of buckets) {
    row.sort((a, b) => (b.degree || 0) - (a.degree || 0));
    if (rootId) {                            // root claims the center slot
      const i = row.findIndex((n) => n.id === rootId);
      if (i > 0) row.unshift(row.splice(i, 1)[0]);
    }
    const baseY = yearToY(year);
    const lanes = Math.max(1, Math.ceil(row.length / maxCols));
    for (let i = 0; i < row.length; i++) {
      // weave through lanes so each lane fills uniformly: lane 0 first, then 1, …
      const lane = i % lanes;
      const colIdx = Math.floor(i / lanes);
      const colsInLane = Math.ceil((row.length - lane) / lanes);
      const x = (colIdx - (colsInLane - 1) / 2) * pitch;
      const y = baseY + (lane - (lanes - 1) / 2) * lanePitch;
      target.set(row[i].id, { x, y, op: 1 });
    }
  }
}

function buildTimelineTargets() {
  const buckets = new Map();
  for (const n of nodes) {
    if (n.type !== "document" || !n.year) continue;
    // Clamp pre-seed-era citations to the top of the axis so they pile up
    // without ranging off-screen.
    const y = Math.max(YEAR_MIN, n.year);
    if (!buckets.has(y)) buckets.set(y, []);
    buckets.get(y).push(n);
  }
  const t = targets.timeline;
  t.clear();
  beeswarmLayout(buckets, t, { pitch: 28, lanePitch: 22, maxWidth: TIMELINE_W });
  // Hide everything else; the explore-position fallback keeps the transition
  // looking like a collapse into the timeline, not a teleport to (0, 0).
  for (const n of nodes) {
    if (!t.has(n.id)) t.set(n.id, { x: n.x, y: n.y, op: 0 });
  }
}

function setView(next) {
  if (!VIEWS.includes(next)) return;
  // snapshot current positions as the animation source
  const from = new Map();
  for (const n of nodes) from.set(n.id, { x: n._x, y: n._y, op: n._op });
  state.view = next;
  viewTween = { from, t0: performance.now(), dur: VIEW_TWEEN_MS };
  reflectViewChrome();
  // Reset camera to a sensible frame for the new view.
  const frame = frameForView(next);
  flyTo(frame.x, frame.y, frame.scale, 700);
  writeHashView();
  dirty = true;
}

function reflectViewChrome() {
  for (const btn of document.querySelectorAll(".viewswitch__btn")) {
    btn.setAttribute("aria-pressed", String(btn.dataset.view === state.view));
  }
}

// Keep the camera anchored to content in the chronological views — nothing
// off-axis is interesting to scroll to, and zooming all the way out makes the
// nodes sub-pixel. Called from every code path that moves cam.x/y/scale.
function clampCamera() {
  if (state.view === "explore") return;
  // Scale: a floor that keeps the smallest dot ≥ 1px on screen, a ceiling that
  // prevents zooming so deep a single year row leaves the viewport.
  const minScale = Math.max(0.25, canvas.clientHeight / (TIMELINE_H * 1.4));
  cam.scale = Math.max(minScale, Math.min(6, cam.scale));
  // Vertical: a small slack past the YEAR_MIN/MAX rows so the top/bottom
  // labels don't sit flush against the edge.
  const halfViewY = canvas.clientHeight / 2 / cam.scale;
  const slack = 120;
  cam.y = Math.max(-TIMELINE_H / 2 - slack + halfViewY * 0.0,
                   Math.min(TIMELINE_H / 2 + slack - halfViewY * 0.0, cam.y));
  // Horizontal: stay near the swarm column.
  const halfViewX = canvas.clientWidth / 2 / cam.scale;
  const xSlack = TIMELINE_W * 0.6;
  cam.x = Math.max(-xSlack, Math.min(xSlack, cam.x));
}

function frameForView(view) {
  if (view === "explore") {
    return frameOfPoints(nodes.map((n) => ({ x: n.x, y: n.y })));
  }
  // Timeline: zooming out to fit 1880→2026 makes individual dots sub-pixel and
  // hides the labels. Instead, frame ~50 years around an anchor — the pinned
  // doc if you have one, else the most-recent encyclical (currently Magnifica
  // Humanitas). Lets you read titles immediately and scroll outward for context.
  const t = targets.timeline;
  const pinned = [...selectedIds]
    .map((id) => nodeById.get(id))
    .find((n) => n && n.type === "document" && n.year);
  const sources = nodes
    .filter((n) => n.is_source && n.year)
    .sort((a, b) => b.year - a.year);
  const anchor = pinned || sources[0];
  if (!anchor) return frameOfPoints([{ x: 0, y: 0 }]);
  const pos = t.get(anchor.id) || { x: 0, y: yearToY(anchor.year) };
  // ~50-year window vertically; horizontally centered on the anchor's column.
  const winYears = 55;
  const scale = canvas.clientHeight / ((winYears / (YEAR_MAX - YEAR_MIN)) * TIMELINE_H);
  return { x: pos.x, y: pos.y, scale };
}

function frameOfPoints(pts, pad = 1.18) {
  const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const scale = Math.min(
    canvas.clientWidth / Math.max(1, (maxX - minX) * pad),
    canvas.clientHeight / Math.max(1, (maxY - minY) * pad)
  );
  return { x: cx, y: cy, scale };
}

function jumpToYear(year) {
  const targetY = yearToY(year);
  flyTo(cam.x, targetY, cam.scale, 600);
}

function buildViewSwitcher() {
  for (const btn of document.querySelectorAll(".viewswitch__btn")) {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  }
  window.addEventListener("keydown", (e) => {
    if (document.activeElement?.tagName === "INPUT") return;
    if (e.key === "1") setView("explore");
    else if (e.key === "2") setView("timeline");
  });
}

function readHashView() {
  const m = /^#view=(explore|timeline)\b/.exec(window.location.hash);
  if (m) setView(m[1]);
}

function writeHashView() {
  if (state.view === "explore") {
    history.replaceState(null, "", window.location.pathname);
  } else {
    history.replaceState(null, "", `#view=${state.view}`);
  }
}

// Per-frame node animation toward the active view's targets. Also handles the
// view-tween (a one-time 600ms easing from the snapshot taken at switch).
function tickPositions(t) {
  const T = targets[state.view];
  if (viewTween) {
    const k = Math.min(1, (t - viewTween.t0) / viewTween.dur);
    const e = ease(k);
    for (const n of nodes) {
      const from = viewTween.from.get(n.id);
      const to = T.get(n.id) || from;
      n._x = from.x + (to.x - from.x) * e;
      n._y = from.y + (to.y - from.y) * e;
      n._op = from.op + (to.op - from.op) * e;
    }
    dirty = true;
    if (k >= 1) viewTween = null;
  } else {
    // No tween — make sure positions match the current target (idempotent).
    for (const n of nodes) {
      const to = T.get(n.id);
      if (!to) continue;
      if (n._x !== to.x || n._y !== to.y || n._op !== to.op) {
        n._x = to.x; n._y = to.y; n._op = to.op; dirty = true;
      }
    }
  }
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
      // In Timeline the y-axis is time — lock vertical pan to the wheel
      // (and keep horizontal drag for browsing within a year).
      const lockY = state.view !== "explore";
      cam.x -= dx / cam.scale;
      if (!lockY) cam.y -= dy / cam.scale;
      clampCamera();
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
    // Chronological views: wheel = scroll through time. Pinch / ctrl-wheel still
    // zooms (mac trackpads dispatch pinch as `ctrlKey + wheel`). Shift inverts
    // axis for trackpads that send horizontal deltas.
    if (state.view !== "explore" && !e.ctrlKey && !e.metaKey) {
      const dy = (e.shiftKey && e.deltaX) ? e.deltaX : e.deltaY;
      cam.y += dy / cam.scale;
      clampCamera();
      dirty = true;
      return;
    }
    const [wx, wy] = toWorld(e.clientX - rect.left, e.clientY - rect.top);
    const factor = Math.exp(-e.deltaY * 0.0012);
    cam.scale = Math.max(0.05, Math.min(8, cam.scale * factor));
    // keep the cursor anchored over the same world point
    const [sx, sy] = toScreen(wx, wy);
    cam.x += (e.clientX - rect.left - sx) / -cam.scale;
    cam.y += (e.clientY - rect.top - sy) / -cam.scale;
    clampCamera();
    dirty = true;
  }, { passive: false });

  // ---- touch: one-finger pan/tap, two-finger pinch-zoom ----------------
  // No hover on touch; a finger drag pans both axes (the natural way to scroll
  // the timeline, replacing the wheel), and pinch zooms anchored at the
  // midpoint. clampCamera keeps the chronological views in bounds.
  let tMoved = false, pinching = false;
  let tLastX = 0, tLastY = 0;                 // one-finger pan anchor
  let pinchDist = 0, pinchMX = 0, pinchMY = 0; // two-finger state
  const touchPt = (t) => {
    const rect = canvas.getBoundingClientRect();
    return [t.clientX - rect.left, t.clientY - rect.top];
  };

  canvas.addEventListener("touchstart", (e) => {
    if (e.touches.length === 1) {
      pinching = false; tMoved = false;
      [tLastX, tLastY] = touchPt(e.touches[0]);
    } else if (e.touches.length === 2) {
      pinching = true; tMoved = true;
      const [ax, ay] = touchPt(e.touches[0]);
      const [bx, by] = touchPt(e.touches[1]);
      pinchDist = Math.hypot(ax - bx, ay - by) || 1;
      pinchMX = (ax + bx) / 2; pinchMY = (ay + by) / 2;
    }
  }, { passive: false });

  canvas.addEventListener("touchmove", (e) => {
    e.preventDefault();
    if (e.touches.length >= 2) {
      const [ax, ay] = touchPt(e.touches[0]);
      const [bx, by] = touchPt(e.touches[1]);
      const dist = Math.hypot(ax - bx, ay - by) || 1;
      const mx = (ax + bx) / 2, my = (ay + by) / 2;
      // two-finger drag pans by the midpoint translation
      cam.x -= (mx - pinchMX) / cam.scale;
      cam.y -= (my - pinchMY) / cam.scale;
      // pinch ratio zooms, keeping the world point under the midpoint anchored
      const [wx, wy] = toWorld(mx, my);
      cam.scale = Math.max(0.05, Math.min(8, cam.scale * (dist / pinchDist)));
      const [sx, sy] = toScreen(wx, wy);
      cam.x += (mx - sx) / -cam.scale;
      cam.y += (my - sy) / -cam.scale;
      pinchDist = dist; pinchMX = mx; pinchMY = my;
      clampCamera(); dirty = true;
      return;
    }
    if (e.touches.length === 1 && !pinching) {
      const [x, y] = touchPt(e.touches[0]);
      const dx = x - tLastX, dy = y - tLastY;
      if (Math.abs(dx) + Math.abs(dy) > 2) tMoved = true;
      cam.x -= dx / cam.scale;
      cam.y -= dy / cam.scale;
      clampCamera();
      tLastX = x; tLastY = y; dirty = true;
    }
  }, { passive: false });

  canvas.addEventListener("touchend", (e) => {
    // a clean single tap (no drag, no pinch) selects the node under the finger
    if (!tMoved && !pinching && e.changedTouches.length) {
      const [x, y] = touchPt(e.changedTouches[0]);
      toggleSelect(nodeAt(x, y));   // null (empty space) clears the selection
    }
    if (e.touches.length === 0) pinching = false;
    // lifting one of two fingers: re-anchor the survivor for pan, don't tap
    if (e.touches.length === 1) {
      pinching = false; tMoved = true;
      [tLastX, tLastY] = touchPt(e.touches[0]);
    }
  }, { passive: false });

  // closing the detail panel hides it but keeps the pinned selection
  document.getElementById("detail-close").addEventListener("click", () => {
    detailNode = null; detailFilters.clear();
    showDetail(null); computeHighlight(); dirty = true;
  });

  // connection rows act as per-node category filters
  document.getElementById("detail-connections").addEventListener("click", (e) => {
    const btn = e.target.closest(".detail__conn");
    if (btn) toggleDetailFilter(btn.dataset.cat);
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
    detailFilters.clear();
    clearSelection();   // also recomputes highlight & redraws
  });
}

// ---- selection -----------------------------------------------------------
// Clicking a node pins it; clicking again unpins it. The detail panel always
// reflects the most recently clicked node, without disturbing the pinned set.
function toggleSelect(n) {
  if (!n) { clearSelection(); return; }
  const prevDetail = detailNode;
  if (selectedIds.has(n.id)) {
    selectedIds.delete(n.id);
    detailNode = selectedIds.size ? nodeById.get([...selectedIds].at(-1)) : null;
  } else {
    selectedIds.add(n.id);
    detailNode = n;
  }
  if (detailNode !== prevDetail) detailFilters.clear();
  afterSelectionChange();
}

function pin(n) {                 // add (if absent) and inspect — used by search
  if (!n) return;
  if (detailNode !== n) detailFilters.clear();
  selectedIds.add(n.id);
  detailNode = n;
  afterSelectionChange();
}

function clearSelection() {
  selectedIds.clear();
  detailNode = null;
  detailFilters.clear();
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
    n.is_source ? "Encyclical" :
    n.pontiff ? "Pontiff" :
    n.type === "document" ? (n.doc_type || "Magisterial work") :
    KIND_LABEL[n.type] || n.type;
  document.getElementById("detail-title").textContent = n.label || n.id;

  // Pontiff subtitle: e.g. "267th Pontiff · 2025–present"
  const subtitle = document.getElementById("detail-subtitle");
  if (n.pontiff) {
    subtitle.textContent = `${n.pontiff.ordinal_label} · ${n.pontiff.reign_label}`;
    subtitle.hidden = false;
  } else {
    subtitle.hidden = true;
  }

  // Intrinsic facts (date, author, testament) — distinct from connection rows.
  const meta = document.getElementById("detail-meta");
  meta.innerHTML = "";
  const facts = [];
  if (n.type === "document" && n.author) facts.push(["Author", n.author]);
  if (n.type === "document" && n.date) facts.push(["Promulgated", n.date]);
  if (n.type === "scripture") facts.push(["Testament", n.testament === "OT" ? "Old Testament" : "New Testament"]);
  for (const [k, v] of facts) {
    const div = document.createElement("div");
    div.innerHTML = `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`;
    meta.appendChild(div);
  }

  // Connection rows — built from directed edges so source-to-source citations
  // are surfaced correctly under References (outgoing) and Cited by (incoming).
  const conns = document.getElementById("detail-connections");
  conns.innerHTML = "";
  const items = detailRows(n);
  detailRowIds = new Map(items.map((it) => [it.cat, it.ids]));
  for (const it of items) {
    it.count = it.ids.size;
    const pressed = detailFilters.has(it.cat);
    const plural = it.count === 1 ? it.unit : it.unit + "s";
    const btn = document.createElement("button");
    btn.className = "detail__conn";
    btn.dataset.cat = it.cat;
    btn.setAttribute("aria-pressed", String(pressed));
    btn.title = `Highlight the ${it.count} ${plural} connected to this node`;
    btn.innerHTML =
      `<span class="swatch swatch--${it.cat}"></span>` +
      `<span class="detail__conn-label">${it.label}</span>` +
      `<span class="detail__conn-count">${it.count.toLocaleString()} ${plural}</span>`;
    conns.appendChild(btn);
  }
  conns.hidden = items.length === 0;

  const links = document.getElementById("detail-links");

  // Outbound buttons. Encyclicals get the existing "Read at the Vatican" pill;
  // pontiffs get profile + Wikipedia buttons instead. The container clears any
  // pontiff buttons from a previous render so they don't bleed across nodes.
  for (const el of links.querySelectorAll(".detail__link--pontiff")) el.remove();
  const link = document.getElementById("detail-link");
  if (n.pontiff) {
    link.hidden = true;
    if (n.pontiff.vatican_url) {
      const a = document.createElement("a");
      a.className = "detail__link detail__link--pontiff";
      a.target = "_blank"; a.rel = "noopener";
      a.href = n.pontiff.vatican_url;
      a.textContent = "Vatican profile ↗";
      links.appendChild(a);
    }
    if (n.pontiff.wikipedia_url) {
      const a = document.createElement("a");
      a.className = "detail__link detail__link--pontiff detail__link--ghost";
      a.target = "_blank"; a.rel = "noopener";
      a.href = n.pontiff.wikipedia_url;
      a.textContent = "Wikipedia ↗";
      links.appendChild(a);
    }
  } else if (n.url) {
    link.href = n.url; link.hidden = false;
  } else {
    link.hidden = true;
  }

  panel.hidden = false;
}

// Toggle a category in the detail-scoped filter set.
function toggleDetailFilter(cat) {
  if (detailFilters.has(cat)) detailFilters.delete(cat);
  else detailFilters.add(cat);
  for (const btn of document.querySelectorAll("#detail-connections .detail__conn")) {
    btn.setAttribute("aria-pressed", String(detailFilters.has(btn.dataset.cat)));
  }
  computeHighlight();
  dirty = true;
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
  const T = targets[state.view];
  const pts = nodes
    .filter((m) => ids.has(m.id))
    .map((m) => { const v = T.get(m.id); return v && v.op > 0.2 ? v : { x: m._x, y: m._y }; });
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
