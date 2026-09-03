/* ============================================================
   Supply Chain & Demand Intelligence Platform — Phase 6
   Application shell (Steps 1–2)
   Hash router + nav + fetch wrapper + reusable render helpers.
   ============================================================ */

"use strict";

const VIEWS = ["executive", "demand", "forecast", "inventory", "scenario", "risk"];

/* ---------- fetch wrapper: loading / error / empty states ---------- */
async function api(path, { loadingEl, onError } = {}) {
  if (loadingEl) loadingEl.innerHTML = '<div class="state"><div class="spinner"></div><span>Loading…</span></div>';
  try {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) {
      let detail = "";
      try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch {}
      throw new Error(`HTTP ${res.status}${detail ? ": " + detail : ""}`);
    }
    return await res.json();
  } catch (err) {
    if (loadingEl) {
      loadingEl.innerHTML =
        `<div class="state state--error"><h4>Could not load data</h4><p>${escapeHtml(err.message)}</p></div>`;
    }
    if (onError) onError(err);
    throw err;
  } finally {
    if (loadingEl && loadingEl.dataset.preserveLoader !== "1") {
      // leave the rendered result in place after success; errors already replaced it.
    }
  }
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- reusable render helpers ---------- */

function metricValue(m) {
  // m: {value, unit, provenance, undefined}. Renders literal "—" when undefined.
  if (!m || m.undefined || m.value === null || m.value === undefined) {
    return '<span class="dash">—</span>';
  }
  return `<span class="metric-value">${escapeHtml(fmtNum(m.value))}</span>`;
}

function metricValueUnit(m) {
  if (!m || m.undefined || m.value === null || m.value === undefined) return '<span class="dash">—</span>';
  return `<span class="metric-value">${escapeHtml(fmtNum(m.value))}</span> <span class="caption">${escapeHtml(m.unit || "")}</span>`;
}

function fmtNum(v, digits = 2) {
  if (typeof v !== "number") return String(v ?? "—");
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function provenanceChip(p) {
  const key = (p || "").toLowerCase();
  const cls =
    key === "observed" ? "chip--observed"
    : key === "derived" ? "chip--derived"
    : key === "simulated" ? "chip--simulated"
    : "chip--derived";
  return `<span class="chip ${cls}">${escapeHtml(key || "derived")}</span>`;
}

function tierChip(t) {
  const cls = { Critical: "tier--critical", High: "tier--high", Medium: "tier--medium", Low: "tier--low" }[t] || "";
  return `<span class="tier ${cls}">${escapeHtml(t)}</span>`;
}

function kpiCard(label, valueHtml, sub, variant = "") {
  return `<div class="kpi ${variant}"><span class="kpi__label">${escapeHtml(label)}</span><div class="kpi__value">${valueHtml}</div><span class="kpi__sub">${sub || ""}</span></div>`;
}

function state(icon, title, detail) {
  return `<div class="state"><span><b>${escapeHtml(title)}</b></span><span>${escapeHtml(detail || "")}</span></div>`;
}

/* ---------- view renderers ---------- */

/* ---- shared helpers ---- */
function growArrow(pct) {
  const v = parseFloat(pct);
  if (!Number.isFinite(v)) return `<span class="arrow-flat">→</span>`;
  if (v > 0.05) return `<span class="arrow-up">▲</span>`;
  if (v < -0.05) return `<span class="arrow-down">▼</span>`;
  return `<span class="arrow-flat">→</span>`;
}

function pctSign(pct) {
  const v = parseFloat(pct);
  if (!Number.isFinite(v)) return "";
  const s = (v > 0 ? "+" : "") + fmtNum(v) + "%";
  return `<span class="direction ${v > 0 ? "arrow-up" : v < 0 ? "arrow-down" : "arrow-flat"}">${escapeHtml(s)}</span>`;
}

function pctOf100(v) {
  const f = parseFloat(v);
  if (!Number.isFinite(f)) return 0;
  return Math.max(0, Math.min(100, f));
}

/* ---- Section 1: KPI header ---- */
function renderKpis(host, exec, inv, sig) {
  const h = exec.headline || {};
  const cards = [
    kpiCard("Total Revenue", metricValueUnit(h.revenue), "Derived · full portfolio"),
    kpiCard("Total Units", metricValueUnit(h.units), "Derived · full portfolio"),
    kpiCard("Revenue WoW", metricValue(h.revenue_wow_pct) + " " + growArrow(h.revenue_wow_pct?.value), "vs prior week", "kpi--neutral"),
    kpiCard("Units WoW", metricValue(h.units_wow_pct) + " " + growArrow(h.units_wow_pct?.value), "vs prior week"),
    kpiCard("Revenue QoQ", metricValue(h.revenue_qoq_pct) + " " + growArrow(h.revenue_qoq_pct?.value), "vs prior quarter"),
    kpiCard("Revenue YoY", metricValue(h.revenue_yoy_pct) + " " + growArrow(h.revenue_yoy_pct?.value), "vs prior year"),
    kpiCard("Avg Days of Inventory", metricValue(invDaysMetric(inv)), tooltip("Simulated · avg over the 28-day horizon", "Average days of inventory held across the forecast horizon. Simulated."), "kpi--neutral"),
    kpiCard("Avg Service Level", metricValue(invServiceMetric(inv)), tooltip("Simulated · target ~95%", "Share of demand fulfilled without stocking out, averaged over the simulated horizon."), "kpi--neutral"),
    kpiCard("Series at Stockout Risk", metricNumber(sig ? sig.stockout_at_risk : null), "High/Critical tier · simulated", "kpi--risk"),
    kpiCard("Series at Excess Risk", metricNumber(sig ? sig.excess_at_risk : null), "High/Critical tier · simulated", "kpi--risk"),
  ].join("");
  host.innerHTML = cards;
}

function invDaysMetric(inv) {
  if (!inv || inv.days_of_inventory === null || inv.days_of_inventory === undefined)
    return { value: null, undefined: true, provenance: "simulated", unit: "days" };
  return { value: Math.round(inv.days_of_inventory * 10) / 10, unit: "days", provenance: "simulated", undefined: false };
}
function invServiceMetric(inv) {
  if (!inv || inv.service_level_achieved === null || inv.service_level_achieved === undefined)
    return { value: null, undefined: true, provenance: "simulated" };
  return { value: Math.round(inv.service_level_achieved * 1000) / 10, unit: "%", provenance: "simulated", undefined: false };
}

function metricNumber(v) {
  if (v === null || v === undefined) return '<span class="dash">—</span>';
  return `<span class="metric-value">${escapeHtml(fmtNum(v))}</span>`;
}

function tooltip(visible, detail) {
  return `<span data-tip="${escapeHtml(detail)}">${escapeHtml(visible)}</span>`;
}

/* ---- Section 2: Demand performance ---- */
function renderDemand(host, exec, contrib, filters) {
  const h = exec.headline || {};
  const trend = exec.revenue_trend || [];
  const maxRev = Math.max(1, ...trend.map((t) => t.revenue || 0));
  const maxUnits = Math.max(1, ...trend.map((t) => t.units || 0));

  const growth = [
    ["Revenue WoW", h.revenue_wow_pct],
    ["Revenue QoQ", h.revenue_qoq_pct],
    ["Revenue YoY", h.revenue_yoy_pct],
    ["Units YoY", h.units_yoy_pct],
  ].filter(([, m]) => m && !m.undefined);

  const bars = trend.map((t) => {
    const rp = ((t.revenue || 0) / maxRev) * 100;
    const up = ((t.units || 0) / maxUnits) * 100;
    return `<div class="bar" style="height:${Math.max(2, rp)}%" title="wk ${escapeHtml(t.period)} · revenue ${escapeHtml(fmtNum(t.revenue))}"><span></span></div>`;
  }).join("");
  const unitBars = trend.map((t) => {
    const up = ((t.units || 0) / maxUnits) * 100;
    return `<div class="bar units" style="height:${Math.max(2, up)}%" title="wk ${escapeHtml(t.period)} · units ${escapeHtml(fmtNum(t.units))}"></div>`;
  }).join("");

  const contribHtml = renderContribution("Top products by revenue", contrib.by_product, true)
    + renderContribution("Department revenue share", contrib.by_department, false)
    + renderContribution("State revenue share", contrib.by_state, false);

  const growthHtml = growth.length
    ? `<div class="chiplist">${growth.map(([lbl, m]) => `<span class="chip chip--derived">${escapeHtml(lbl)} ${escapeHtml(pctSign(m.value))}</span>`).join(" ")}</div>`
    : `<div class="state">${state("empty", "Growth metrics unavailable", "No prior-period basis for the selection.")}</div>`;

  host.innerHTML = `
    <div class="card__title">Demand performance</div>
    <div class="card__foot" style="margin-top:0">${provenanceChip("derived")} Weekly rollup; never the 59M daily fact.</div>
    <div class="grid grid-2 mt-2">
      <div class="trend">
        <h4>Revenue trend (last 12 weeks)</h4>
        <div class="trend__bars">${trend.length ? bars : ""}</div>
      </div>
      <div class="trend">
        <h4>Units trend</h4>
        <div class="trend__bars">${trend.length ? unitBars : ""}</div>
        ${trend.length ? "" : `<div class="state">${state("empty", "No trend data", "No weekly rows for the selection.")}</div>`}
      </div>
    </div>
    <div class="mt-4"><h4>Growth direction</h4>${growthHtml}</div>
    <div class="mt-4">
      <h4>Revenue concentration ${activeFilterLabel(filters)}</h4>
      <div class="grid grid-2 mt-2">${contribHtml}</div>
    </div>
  `;
}

function activeFilterLabel(filters) {
  const parts = [];
  for (const key of ["department", "category", "product", "store", "state", "region"]) {
    if (filters[key]) parts.push(`${key}: ${filters[key]}`);
  }
  return parts.length ? `<span class="caption">(filtered by ${escapeHtml(parts.join(", "))})</span>` : "";
}

function renderContribution(title, rows, isRank) {
  if (!rows || !rows.length) {
    return `<div><h4>${escapeHtml(title)}</h4>${state("empty", "No contribution", "No rows match the current filters.")}</div>`;
  }
  const max = Math.max(1, ...rows.map((r) => r.share_pct || 0));
  const body = rows.map((r, i) => {
    const w = Math.max(2, ((r.share_pct || 0) / max) * 100);
    return `<div class="row">
      <span class="ent">${isRank ? (r.rank) + ". " : ""}${escapeHtml(r.entity)}</span>
      <div class="bar-track"><div class="bar-fill ${i % 2 ? "alt" : ""}" style="width:${w}%"></div></div>
      <span class="share">${escapeHtml(fmtNum(r.share_pct))}%</span>
    </div>`;
  }).join("");
  return `<div>
    <h4>${escapeHtml(title)} <span class="caption">· ${provenanceChip("derived")}</span></h4>
    <div class="contribution mt-2">${body}</div>
  </div>`;
}

/* ---- Section 3: Inventory health ---- */
function renderInventory(host, inv, sig) {
  const sl = inv && inv.service_level_achieved != null ? Math.round(inv.service_level_achieved * 1000) / 10 : null;
  const slPct = sl != null ? Math.round((sl / 100) * 100) : 0;
  const slClass = sl == null ? "" : sl >= 90 ? "" : sl >= 75 ? "warn" : "danger";

  const dio = inv && inv.days_of_inventory != null ? (Math.round(inv.days_of_inventory * 10) / 10) : null;
  const dioClass = dio == null ? "" : dio >= 14 ? "" : dio >= 7 ? "warn" : "danger";

  const stockout = sig ? sig.stockout_at_risk : null;
  const excess = sig ? sig.excess_at_risk : null;

  const healthWords =
    (sl == null && dio == null) ? "Inventory health metrics are undefined for this selection."
    : sl != null && sl >= 90 ? "Service level is healthy; overall exposure is low."
    : sl != null && sl >= 75 ? "Service level is moderate; review below-target series."
    : "Service level is below target — prioritize the stockout signals below.";

  host.innerHTML = `
    <div class="card__title">Inventory health<span class="caption" style="float:right">${provenanceChip("simulated")}</span></div>
    <div class="card__foot" style="margin-top:0">Simulated under the baseline assumption set (28-day horizon).</div>
    <div class="health mt-4">
      <div class="meter">
        <span>Service level ${sl == null ? '<span class="dash">—</span>' : escapeHtml(fmtNum(sl)) + "%"}</span>
        <div class="meter__track"><div class="meter__fill ${slClass}" style="width:${slPct}%"></div></div>
      </div>
      <div class="meter">
        <span>Days of inventory ${dio == null ? '<span class="dash">—</span>' : escapeHtml(fmtNum(dio)) + " days"}</span>
        <div class="meter__track"><div class="meter__fill ${dioClass}" style="width:${Math.min(100, (dio || 0) / 28 * 100)}%"></div></div>
      </div>
    </div>
    <div class="grid grid-2 mt-4">
      <div class="kpi kpi--risk"><span class="kpi__label">Stockout exposure</span><div class="kpi__value">${metricNumber(stockout)}</div><span class="kpi__sub">series at risk (High/Critical)</span></div>
      <div class="kpi kpi--neutral"><span class="kpi__label">Excess exposure</span><div class="kpi__value">${metricNumber(excess)}</div><span class="kpi__sub">series with excess inventory</span></div>
    </div>
    <p class="mt-2">${escapeHtml(healthWords)}</p>
  `;
}

/* ---- Section 4: Operational signals ---- */
function renderSignals(host, sig) {
  const signals = sig && sig.signals ? sig.signals : [];
  host.innerHTML = `
    <div class="card__title">Operational signals <span class="caption">· ${provenanceChip("simulated")}</span></div>
    <div class="card__foot" style="margin-top:0">Ranked from the stockout/excess risk runs. Simulated priority; review before action.</div>
    ${signals.length ? renderSignalList(signals) : `
      <div class="mt-4">${state("empty", "No high-priority signals", "No High/Critical risk series for the current selection.")}</div>`}
    <div class="mt-4">${renderSignalLegend()}</div>
  `;
}

function signalExplanation(s) {
  const driver = s.primary_driver || "aggregate risk score";
  if (s.risk_type === "stockout")
    return `At risk of running out of stock — ${driver} is the dominant driver; service gap ${s.score != null ? fmtNum(Math.round(s.score * 1000) / 10) : "—"}%, below target.`;
  return `Carrying excess inventory — ${driver} is the dominant driver; expected average inventory exceeds demand this horizon.`;
}

function renderSignalList(signals) {
  const rows = signals.map((s) => `
    <div class="signal">
      <div style="min-width:110px">${tierChip(s.tier || "Unknown")} <span class="caption">#${escapeHtml(fmtNum(s.rank))}</span></div>
      <div style="flex:1">
        <div class="signal__entity">${escapeHtml(s.product)} · ${escapeHtml(s.store)}</div>
        <div class="signal__meta">${escapeHtml(s.risk_type)} risk · score ${escapeHtml(fmtNum(s.score))}</div>
        <div class="signal__why">${escapeHtml(signalExplanation(s))}</div>
      </div>
    </div>`).join("");
  return `<div>${rows}</div>`;
}

function renderSignalLegend() {
  return `<p class="caption"><b>How to read:</b> <span class="tier tier--critical">Critical</span> act now · <span class="tier tier--high">High</span> act this week. Priority = risk tier then rank. Supporting metric = risk score (0–1). Simulated severity, and stock relative to seasonality is not modeled.</p>`;
}

/* ---- Executive loader (parallel fetch + cache + filters) ---- */
const execState = { filter: null, cache: {}, seq: 0 };

function execFilterFromForm() {
  const val = (sel) => (sel && sel.value) || "";
  return {
    department: val(document.getElementById("f-department")) || undefined,
    category: val(document.getElementById("f-category")) || undefined,
    product: document.getElementById("f-product") ? document.getElementById("f-product").value.trim() || undefined : undefined,
    store: val(document.getElementById("f-store")) || undefined,
    state: val(document.getElementById("f-state")) || undefined,
    top_n: parseInt(val(document.getElementById("f-topn")), 10) || 10,
  };
}

async function fetchContributions(filter) {
  const q = new URLSearchParams({ top_n: filter.top_n || 10 });
  for (const k of ["department", "category", "product", "store", "state"]) {
    if (filter[k]) q.set(k, filter[k]);
  }
  return api(`/api/kpis/contributions?${q.toString()}`);
}

async function loadExecutive() {
  const host = document.getElementById("view-executive");
  if (!host) return;
  document.getElementById("view-sub-executive").textContent =
    "What is happening, where is the risk, and where should management look first. Derived metrics from the weekly rollup; inventory and risk figures are simulated.";
  const mySeq = ++execState.seq;
  const contribEl = document.getElementById("exec-demand");
  const invEl = document.getElementById("exec-inventory");
  const sigEl = document.getElementById("exec-signals");

  try {
    // Parallel, cached where stable across the session.
    const invPromise = (execState.cache.inv ?? api("/api/inventory/summary")).catch(() => null);
    const sigPromise = (execState.cache.sig ?? api("/api/executive/signals")).catch(() => null);
    const kpisPromise = (execState.cache.kpis ?? api("/api/kpis/executive")).catch(() => null);
    const contribPromise = fetchContributions(execState.filter || execFilterFromForm()).catch(() => null);

    const [exec, inv, sig, contrib] = await Promise.all([kpisPromise, invPromise, sigPromise, contribPromise]);
    if (mySeq !== execState.seq) return; // stale response

    // Cache the stable aggregate calls so repeats don't re-hit the DB.
    if (exec) execState.cache.kpis = Promise.resolve(exec);
    if (inv) execState.cache.inv = Promise.resolve(inv);
    if (sig) execState.cache.sig = Promise.resolve(sig);

    renderKpis(document.getElementById("exec-kpis"), exec || {}, inv, sig);
    renderDemand(contribEl, exec || {}, contrib, execState.filter || {});
    renderInventory(invEl, inv, sig);
    renderSignals(sigEl, sig);
  } catch (err) {
    if (mySeq !== execState.seq) return;
    const msg = `<div class="state state--error"><h4>Could not build the executive dashboard</h4><p>${escapeHtml(err.message)}</p></div>`;
    document.getElementById("exec-kpis").innerHTML = msg;
  }
}

/* ---------- router ---------- */

function activeView() {
  const m = location.hash.match(/^#\/([a-z]+)/);
  return m && VIEWS.includes(m[1]) ? m[1] : "executive";
}

function renderNav() {
  const current = activeView();
  document.querySelectorAll(".nav-link").forEach((a) => {
    const active = a.dataset.view === current;
    a.setAttribute("aria-current", active ? "page" : "false");
    a.classList.toggle("is-active", active);
  });
}

function route() {
  renderNav();
  const view = activeView();
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("is-active", s.id === `view-${view}`));
  document.title = `${document.querySelector(`#view-${view}`).dataset.title} · Supply Chain & Demand Intelligence`;

  if (view === "executive") loadExecutive();
  else if (view === "demand") loadDemand();
  else if (view === "forecast") loadForecast();
  else if (view === "inventory") loadInventory();
  else if (view === "scenario") loadScenario();
  else if (view === "risk") loadRisk();
}

/* ---- filter wiring ---- */
function populateSelect(selId, values, emptyLabel) {
  const sel = document.getElementById(selId);
  if (!sel) return;
  const opts = [`<option value="">${emptyLabel}</option>`].concat(
    values.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`)
  ).join("");
  sel.innerHTML = opts;
}

async function loadDimensionOptions() {
  let dims = null;
  try { dims = await api("/api/meta/dimensions"); } catch { return; }
  const states = (dims.states || []).concat((dims.regions || []).filter((r) => !(dims.states || []).includes(r)));
  populateSelect("f-department", dims.departments || [], "All departments");
  populateSelect("f-category", dims.categories || [], "All categories");
  populateSelect("f-state", states, "All states / regions");
  populateSelect("f-store", dims.stores || [], "All stores");
  // Demand page mirrors the same dimension option lists.
  populateSelect("d-department", dims.departments || [], "All departments");
  populateSelect("d-category", dims.categories || [], "All categories");
  populateSelect("d-state", states, "All states / regions");
  populateSelect("d-store", dims.stores || [], "All stores");
  // Risk page mirrors the same dimension option lists.
  populateSelect("rk-department", dims.departments || [], "All departments");
  populateSelect("rk-category", dims.categories || [], "All categories");
  populateSelect("rk-state", states, "All states / regions");
  populateSelect("rk-store", dims.stores || [], "All stores");
}

function wireFilters() {
  const refresh = () => {
    execState.filter = execFilterFromForm();
    execState.seq++; // invalidate any in-flight render, but keep caches so KPIs don't reload
    const contribEl = document.getElementById("exec-demand");
    contribEl.innerHTML = `<div class="state"><div class="spinner"></div><span>Refreshing concentration…</span></div>`;
    fetchContributions(execState.filter)
      .then((contrib) => {
        // Reuse cached headline data from the last full load if present.
        const cachedExec = execState.cache.kpis || Promise.resolve(null);
        cachedExec.then((exec) => {
          renderDemand(contribEl, exec || {}, contrib, execState.filter || {});
        }).catch(() => {
          renderDemand(contribEl, null, contrib, execState.filter || {});
        });
      })
      .catch((err) => {
        contribEl.innerHTML = `<div class="state state--error"><h4>Could not apply filters</h4><p>${escapeHtml(err.message)}</p></div>`;
      });
  };

  const ids = ["f-department", "f-category", "f-state", "f-store", "f-topn"];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", refresh);
  });
  const prod = document.getElementById("f-product");
  if (prod) prod.addEventListener("change", refresh);

  const reset = document.getElementById("filter-reset");
  if (reset) reset.addEventListener("click", () => {
    ids.forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
    if (prod) prod.value = "";
    const topn = document.getElementById("f-topn");
    if (topn) topn.value = "10";
    execState.filter = null;
    refresh();
  });
}

/* ============================================================
   Step 5 — Demand / Forecast / Inventory pages
   ============================================================ */

/* ---- shared formatting ---- */
function pct(v, digits = 1) {
  if (v === null || v === undefined) return '<span class="dash">—</span>';
  return escapeHtml(fmtNum(v * 100, digits)) + "%";
}
function plainNum(v) {
  if (v === null || v === undefined) return '<span class="dash">—</span>';
  return escapeHtml(fmtNum(v));
}
function rowKey(id, name) {
  return `#${escapeHtml(id)} · ${escapeHtml(name)}`;
}

function numberInCell(v, digits = 2) {
  if (v === null || v === undefined) return '<span class="dash">—</span>';
  const d = typeof v === "number" && Number.isInteger(v) ? 0 : digits;
  return escapeHtml(fmtNum(v, d));
}

/* ============================================================
   DEMAND INTELLIGENCE
   ============================================================ */
const demState = { page: 1, pageSize: 25, seq: 0, matrixSeq: 0, lastKey: null };

function demFilterFromForm() {
  const v = (id) => (document.getElementById(id) ? document.getElementById(id).value : "") || undefined;
  return {
    department: v("d-department"),
    category: v("d-category"),
    state: v("d-state"),
    store: v("d-store"),
    trend_direction: v("d-trend"),
    volatility_class: v("d-volatility"),
    volume_class: v("d-volume"),
    risk_category: v("d-risk"),
    product: document.getElementById("d-product") ? document.getElementById("d-product").value.trim() || undefined : undefined,
  };
}
function demFilterQuery(filter) {
  const q = new URLSearchParams();
  for (const k of ["department", "category", "state", "store", "trend_direction", "volatility_class", "volume_class", "risk_category", "product"]) {
    if (filter[k]) q.set(k, filter[k]);
  }
  return q;
}

function loadDemand() {
  const host = document.getElementById("view-demand");
  if (!host) return;
  document.getElementById("view-sub-demand").textContent =
    "Pattern of demand per product × store: mean daily volume, volatility, trend, and seasonality. Derived from the observed demand-analysis window; risk cells are derived, not observed inventory risk.";
  const key = demFilterQuery(demFilterFromForm()).toString();
  if (key === demState.lastKey) return; // avoid duplicate identical fetches
  demState.lastKey = key;
  loadDemandData();
}

async function loadDemandData() {
  const mySeq = ++demState.seq;
  const filter = demFilterFromForm();
  const q = demFilterQuery(filter);
  q.set("page", String(demState.page));
  q.set("page_size", String(demState.pageSize));
  const matrixEl = document.getElementById("demand-matrix");
  const riskEl = document.getElementById("demand-risk");

  // Segments (matrix + risk breaks) update on every filter change; rows follow page.
  matrixEl.innerHTML = spinner();
  riskEl.innerHTML = spinner();
  const segPromise = api(`/api/analytics/demand/segments?${demFilterQuery(filter).toString()}`)
    .catch(() => null);
  segPromise.then((seg) => {
    if (mySeq !== demState.seq) return;
    renderMatrix(matrixEl, seg);
    renderRiskBreaks(riskEl, seg);
  }).catch(() => {
    if (mySeq !== demState.seq) return;
    matrixEl.innerHTML = errorState("Could not load the volume × volatility matrix.");
    riskEl.innerHTML = errorState("Could not load the risk breakdown.");
  });

  await renderDemandTable(q);

  // Fill the lightweight KPI summary from the segments (bounded counts) once the
  // risk breaks are available.
  segPromise.then((seg) => {
    if (mySeq !== demState.seq) return;
    showDemandSummary(document.getElementById("demand-summary"), seg);
  });
}

function spinner() {
  return '<div class="state"><div class="spinner"></div><span>Loading…</span></div>';
}
function errorState(msg) {
  return `<div class="state state--error"><h4>Could not load data</h4><p>${escapeHtml(msg)}</p></div>`;
}

function compactKpi(label, valueHtml, sub) {
  return `<div class="metric"><span class="metric__label">${escapeHtml(label)}</span><div class="metric__value">${valueHtml}</div>${sub ? `<span class="caption">${escapeHtml(sub)}</span>` : ""}</div>`;
}

function cellLevel(cell) {
  // Risk cell hot/warm based on risk_cell marker (e.g. "Medium*High" -> High volatility).
  if (!cell) return "";
  const seg = String(cell).split("*").pop().toLowerCase();
  if (seg === "high" || seg === "critical") return "cell--hot";
  if (seg === "medium") return "cell--warm";
  return "";
}

function renderMatrix(host, seg) {
  if (!seg || !seg.matrix || !seg.matrix.length) {
    host.innerHTML = `<div class="card__title">Volume × volatility matrix</div>${state("empty", "No segments", "No demand rows match the current filters.")}`;
    return;
  }
  const vols = seg.volume_classes;
  const volatilities = seg.volatility_classes;
  const map = {};
  seg.matrix.forEach((m) => { map[`${m.volume}|${m.volatility}`] = m.count; });
  const header = `<div class="matrix__header" style="grid-template-columns: repeat(${volatilities.length + 1}, 1fr)"><span></span>${volatilities.map((v) => `<span>${escapeHtml(v)} vol</span>`).join("")}</div>`;
  const rows = vols.map((vol) => {
    const cells = volatilities.map((vv) => {
      const n = map[`${vol}|${vv}`] || 0;
      const cls = n === 0 ? "cell--zero" : cellLevel(String(vol) + "*" + String(vv));
      return `<div class="matrix__cell ${cls}"><span>${escapeHtml(vol)}</span><span class="n">${n}</span></div>`;
    }).join("");
    return `<div class="matrix__row" style="grid-template-columns: repeat(${volatilities.length + 1}, 1fr)"><span class="caption" style="padding-top:var(--space-2)">${escapeHtml(vol)} volume</span>${cells}</div>`;
  }).join("");
  host.innerHTML = `<div class="card__title">Volume × volatility matrix <span class="caption">· ${provenanceChip("derived")}</span></div>
    <div class="matrix mt-4">${header}${rows}</div>
    <div class="card__foot">Concentration of series by segment; darker cells = higher volatility risk mix. Segments are derived risk classifications, not observed loss.</div>`;
}

function renderRiskBreaks(host, seg) {
  if (!seg || !seg.risk_breaks || !seg.risk_breaks.length) {
    host.innerHTML = `<div class="card__title">Risk category</div>${state("empty", "No risk breaks", "No series match the current filters.")}`;
    return;
  }
  const order = { Critical: 0, High: 1, Moderate: 2 };
  const rows = segmentSortable(seg.risk_breaks).sort((a, b) => (order[a.risk_category] ?? 9) - (order[b.risk_category] ?? 9));
  const total = rows.reduce((s, r) => s + (r.count || 0), 0) || 1;
  const bars = rows.map((r) => {
    const cls = r.risk_category === "Critical" ? "cell--hot" : r.risk_category === "High" ? "cell--warm" : "";
    return `<div class="matrix__row" style="grid-template-columns: 140px 1fr 56px">
      <span class="caption">${escapeHtml(r.risk_category)}</span>
      <div class="bar-track"><div class="bar-fill ${r.risk_category === "Critical" ? "" : r.risk_category === "High" ? "alt" : ""}" style="width:${(r.count / total) * 100}%"></div></div>
      <span class="share">${escapeHtml(fmtNum(r.count))}</span>
    </div>`;
  }).join("");
  host.innerHTML = `<div class="card__title">Risk category break <span class="caption">· ${provenanceChip("derived")}</span></div>
    <div class="mt-4">${bars}</div>
    <div class="card__foot">Count of product × store series per derived risk category over the observed window.</div>`;
}

function segmentSortable(arr) {
  return Array.isArray(arr) ? arr.slice() : [];
}

function showDemandSummary(sumEl, seg) {
  const breaks = (seg && seg.risk_breaks) || [];
  const total = breaks.reduce((s, r) => s + (r.count || 0), 0);
  sumEl.innerHTML = `<div class="kpi-row">
    ${compactKpi("Series count", total ? escapeHtml(fmtNum(total)) : '<span class="dash">—</span>', "filtered demand rows")}
    ${compactKpi("Mean daily demand", '<span class="dash">—</span>', "avg units/day (see table)")}
    ${compactKpi("Avg CV / volatility", '<span class="dash">—</span>', "coefficient of variation (see table)")}
    ${compactKpi("Seasonal series", '<span class="dash">—</span>', "with meaningful seasonality (see table)")}
  </div>
  <div class="card__foot">Series counts are derived from the observed demand-analysis window and reflect the current filters. Mean daily demand / CV / seasonality are shown per series in the table below; they are not recomputed here.</div>`;
}

async function renderDemandTable(q, seq = demState.seq) {
  const host = document.getElementById("demand-table");
  host.innerHTML = spinner();
  let data;
  try {
    data = await api(`/api/analytics/demand?${q.toString()}`);
  } catch (err) {
    if (seq === demState.seq) host.innerHTML = errorState(err.message);
    return;
  }
  if (seq !== demState.seq) return; // stale response — a newer load owns the table
  host.innerHTML = renderDemandTableHtml(data);
  wireDemandPagination();
}

function renderDemandTableHtml(data) {
  const items = (data && data.items) || [];
  const rows = items.map((r) => {
    const trend = r.trend_direction == null ? "—" : escapeHtml(String(r.trend_direction));
    return `<tr>
      <td class="td-key">${rowKey(r.product, r.store)}</td>
      <td class="num">${numberInCell(r.mean_daily_units, 1)}</td>
      <td class="num">${numberInCell(r.cv, 2)}</td>
      <td class="num">${pct(r.demand_growth_rate, 1)}</td>
      <td>${trend} ${r.trend_effect_pct != null ? `<span class="caption">(${escapeHtml(fmtNum(r.trend_effect_pct, 0))}%)</span>` : ""}</td>
      <td class="num">${numberInCell(r.seasonality_strength, 2)}</td>
      <td>${r.peak_month != null ? `<span class="peak">${MONTHS[r.peak_month - 1] || "—"}</span>` : '<span class="dash">—</span>'} · ${r.trough_month != null ? `<span class="trough">${MONTHS[r.trough_month - 1] || "—"}</span>` : '<span class="dash">—</span>'}</td>
      <td>${r.volatility_class || "—"} / ${r.volume_class || "—"}</td>
      <td>${r.risk_category ? tierChip(r.risk_category === "Moderate" ? "Medium" : r.risk_category) : '<span class="dash">—</span>'}</td>
    </tr>`;
  }).join("");
  const tbody = rows || `<tr class="tbody-empty"><td colspan="9">No demand series match the current filters.</td></tr>`;
  const pg = (data && data.pagination) || {};
  const total = pg.total || 0;
  const page = pg.page || 1;
  const per = pg.page_size || demState.pageSize;
  const pages = Math.max(1, Math.ceil(total / per));
  const sortSel = `
    <select id="demand-sort" aria-label="Sort">
      <option value="">Sort: product</option>
      <option value="cv_desc">Avg CV (high→low)</option>
      <option value="mean_daily_units">Mean daily units (low→high)</option>
      <option value="risk">Risk (worst first)</option>
    </select>`;
  return `<div class="card__title">Demand series <span class="caption">· ${provenanceChip("derived")}</span></div>
    <div class="table-wrap mt-4">
      <table>
        <thead><tr><th scope="col">Product · Store</th><th scope="col" class="num">Mean daily<br/>units</th><th scope="col" class="num">CV</th><th scope="col" class="num">Growth</th><th scope="col">Trend</th><th scope="col" class="num">Seasonality<br/>strength</th><th scope="col">Peak · Trough</th><th scope="col">Vol / Volume</th><th scope="col">Risk</th></tr></thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>
    <div class="table-toolbar mt-4">
      ${sortSel}
      <div class="pagination">
        <button ${page <= 1 ? "disabled" : ""} data-demand-page="${page - 1}">‹ Prev</button>
        <span class="pagination__info">Page ${page} of ${pages} · ${escapeHtml(fmtNum(total))} series</span>
        <button ${page >= pages ? "disabled" : ""} data-demand-page="${page + 1}">Next ›</button>
      </div>
    </div>`;
}

async function applyDemandSort(sort) {
  const filter = demFilterFromForm();
  const q = demFilterQuery(filter);
  q.set("sort", sort || "");
  q.set("page", "1");
  q.set("page_size", String(demState.pageSize));
  await renderDemandTable(q, demState.seq);
}

function wireDemandPagination() {
  const sortSel = document.getElementById("demand-sort");
  if (sortSel) {
    sortSel.onchange = (e) => { demState.page = 1; applyDemandSort(e.target.value); };
  }
  document.querySelectorAll("[data-demand-page]").forEach((btn) => {
    btn.onclick = () => {
      demState.page = parseInt(btn.dataset.demandPage, 10);
      loadDemandData();
    };
  });
}

function demPatchMatrix() {
  // A filter/page change re-runs the bounded segments + paginated table in one.
  loadDemandData();
}

function wireDemandFilters() {
  const ids = ["d-department", "d-category", "d-state", "d-store", "d-trend", "d-volatility", "d-volume", "d-risk"];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => { demState.lastKey = ""; demPatchMatrix(); });
  });
  const prod = document.getElementById("d-product");
  if (prod) prod.addEventListener("change", () => { demState.lastKey = ""; demPatchMatrix(); });
  const pageSize = document.getElementById("d-page-size");
  if (pageSize) pageSize.addEventListener("change", () => {
    demState.pageSize = parseInt(pageSize.value, 10) || 25;
    demState.page = 1;
    demState.lastKey = "";
    loadDemandData();
  });
  const reset = document.getElementById("d-reset");
  if (reset) reset.addEventListener("click", () => {
    ids.forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
    if (prod) prod.value = "";
    demState.page = 1;
    demState.pageSize = 25;
    const ps = document.getElementById("d-page-size");
    if (ps) ps.value = "25";
    demState.lastKey = "";
    demPatchMatrix();
  });
}

/* ============================================================
   FORECAST INTELLIGENCE
   ============================================================ */
const fcState = { cache: {}, seq: 0 };

async function loadForecast() {
  const host = document.getElementById("view-forecast");
  if (!host) return;
  document.getElementById("view-sub-forecast").textContent =
    "How well each model forecasts demand: MAE / RMSE / WMAE / WRMSE, model selection, and support. ETS/SARIMA were evaluated on a 64-series pilot only — their figures are not comparable to the 30,490-series baselines.";
  const selEl = document.getElementById("forecast-selection");
  const accEl = document.getElementById("forecast-accuracy");
  selEl.innerHTML = spinner();
  accEl.innerHTML = spinner();
  try {
    const [sel, acc] = await Promise.all([api("/api/forecast/models"), api("/api/forecast/accuracy")]);
    renderForecastModels(selEl, sel);
    renderForecastAccuracy(accEl, acc);
  } catch (err) {
    selEl.innerHTML = errorState(err.message);
    accEl.innerHTML = errorState(err.message);
  }
}

function modelPilotBadge(pilot) {
  return pilot ? '<span class="badge badge--pilot">64-series pilot</span>' : '<span class="badge badge--full">30,490 series</span>';
}

function renderForecastModels(host, fm) {
  if (!fm || !fm.models || !fm.models.length) {
    host.innerHTML = `<div class="card__title">Model selection</div>${state("empty", "No models", "No model registry data available.")}`;
    return;
  }
  const cards = fm.models.map((m) => {
    const metrics = m.metrics || {};
    const metricRow = (k, label) => `<div class="model-card__metric"><span>${label}</span><span class="num">${numberInCell(metrics[k], 2)}</span></div>`;
    const classes = [`model-card`, m.is_selected ? "is-selected" : "", m.pilot_limited ? "is-pilot" : ""].join(" ");
    const selBadge = m.is_selected ? '<span class="badge badge--sel">Selected</span>' : "";
    return `<div class="${classes}">
      <div class="model-card__name">${escapeHtml(m.model_name)} ${selBadge}</div>
      <div class="model-card__meta">family: ${escapeHtml(m.model_family || "—")} · ${modelPilotBadge(!!m.pilot_limited)}</div>
      <div class="mt-2">${metricRow("mae", "MAE")}${metricRow("rmse", "RMSE")}${metricRow("wmae", "WMAE")}${metricRow("wrmse", "WRMSE")}${metricRow("bias", "Bias")}</div>
      ${m.selection_rationale ? `<div class="model-card__meta mt-2">${escapeHtml(m.selection_rationale)}</div>` : ""}
    </div>`;
  }).join("");
  host.innerHTML = `<div class="card__title">Model selection <span class="caption">· ${provenanceChip("derived")}</span></div>
    <div class="model-grid mt-4">${cards}</div>
    ${fm.limitation_note ? `<div class="caveat mt-4"><b>Pilot support caveat</b> — ${escapeHtml(fm.limitation_note)}</div>` : ""}
    <div class="card__foot">Selected model: ${escapeHtml(fm.selected_model || "—")}. Model-specific metric values are stored; nothing is recomputed in the browser.</div>`;
}

function renderForecastAccuracy(host, fa) {
  if (!fa || !fa.rows || !fa.rows.length) {
    host.innerHTML = `<div class="card__title">Forecast accuracy</div>${state("empty", "No accuracy", "No forecast-evaluation rows available.")}`;
    return;
  }
  const rows = fa.rows.map((r) => {
    const support = r.support_series;
    const isPilot = r.pilot_limited;
    const cls = r.undefined ? "undefined" : "";
    return `<tr class="${cls}">
      <td>${escapeHtml(r.model_name)} ${isPilot ? '<span class="badge badge--pilot">pilot</span>' : ""}${r.model_id === 1 ? '<span class="badge badge--sel">selected</span>' : ""}</td>
      <td class="num ${isPilot ? "support-pilot" : "support-full"}">${escapeHtml(fmtNum(support))}</td>
      <td class="num">${numberInCell(r.mae, 3)}</td>
      <td class="num">${numberInCell(r.rmse, 3)}</td>
      <td class="num">${numberInCell(r.wmae, 3)}</td>
      <td class="num">${numberInCell(r.wrmse, 3)}</td>
      <td class="num">${numberInCell(r.bias, 3)}</td>
    </tr>`;
  }).join("");
  host.innerHTML = `<div class="card__title">Forecast accuracy <span class="caption">· ${provenanceChip("derived")}</span></div>
    <div class="table-wrap mt-4">
      <table>
        <thead><tr><th scope="col">Model</th><th scope="col" class="num">Support<br/>(series)</th><th scope="col" class="num">MAE</th><th scope="col" class="num">RMSE</th><th scope="col" class="num">WMAE</th><th scope="col" class="num">WRMSE</th><th scope="col" class="num">Bias</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${fa.caveat ? `<div class="caveat mt-4"><b>Read carefully</b> — ${escapeHtml(fa.caveat)}</div>` : ""}
    <div class="card__foot">Support = count of series each model was evaluated on. Models 5–6 (ETS/SARIMA) are limited to the 64-series pilot and are <b>not</b> comparable to the 30,490-series models 1–4.</div>`;
}

async function viewForecastSeries(token) {
  const host = document.getElementById("forecast-series-card");
  host.innerHTML = spinner();
  let data;
  try {
    data = await api(`/api/forecast/series?series=${encodeURIComponent(token)}`);
  } catch (err) {
    host.innerHTML = errorState(err.message);
    return;
  }
  host.innerHTML = renderForecastSeries(data);
}

function renderForecastSeries(fs) {
  if (!fs || !fs.total || !fs.points || !fs.points.length) {
    return `<div class="card__title">Series forecast</div>${state("empty", "No forecast", "No final 28-day forecast for that series token.")}`;
  }
  const pts = fs.points;
  const maxVal = Math.max(1, ...pts.map((p) => p.forecast_value || 0));
  const bars = pts.map((p) => {
    const v = p.forecast_value;
    const h = Math.max(2, ((v || 0) / maxVal) * 100);
    const cls = v === 0 ? "zero" : "fc-bar";
    return `<div class="fc-bar-row" title="${escapeHtml(fmtNum(v))} %"><div class="fc-bar ${v > 0 ? "low" : "zero"}" style="height:${h}%"><span></span></div><span class="caption">${escapeHtml(p.horizon)}</span></div>`;
  }).join("");
  const tableRows = pts.map((p) => `<tr>
    <td>${escapeHtml(fmtNum(p.forecast_date))}</td>
    <td class="num">${numberInCell(p.forecast_value, 2)}</td>
    <td class="num">${numberInCell(p.lower_bound, 2)}</td>
    <td class="num">${numberInCell(p.upper_bound, 2)}</td>
    <td>${escapeHtml(fmtNum(p.horizon))}</td>
  </tr>`).join("");
  const key = fs.series ? `${fs.series.product}:${fs.series.store}` : "—";
  return `<div class="card__title">Series forecast <span class="caption">· ${provenanceChip("derived")}</span></div>
    <div class="card__foot" style="margin-top:0">Final forecast, origin ${escapeHtml(fmtNum(fs.points[0].origin))}, horizons 1–${escapeHtml(Number(fs.total))} (28-day). Bounded to this one series.</div>
    <div class="fc-bars mt-4">${bars}</div>
    <div class="table-wrap mt-4">
      <table>
        <thead><tr><th scope="col">Forecast date</th><th scope="col" class="num">Forecast</th><th scope="col" class="num">Lower</th><th scope="col" class="num">Upper</th><th scope="col">Horizon</th></tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>`;
}

/* ============================================================
   INVENTORY INTELLIGENCE
   ============================================================ */
const invState = { cache: {}, seriesSeq: 0 };

async function loadInventory() {
  const host = document.getElementById("view-inventory");
  if (!host) return;
  document.getElementById("view-sub-inventory").textContent =
    "Simulated inventory under the baseline assumption set: service level, days of inventory, stockout and excess exposure. Not observed inventory — all figures carry simulated provenance.";
  const sEl = document.getElementById("inventory-summary");
  const pEl = document.getElementById("inventory-policy");
  sEl.innerHTML = spinner();
  pEl.innerHTML = spinner();
  try {
    const [sum, pol] = await Promise.all([api("/api/inventory/summary"), api("/api/inventory/policy")]);
    renderInventorySummary(sEl, sum);
    renderInventoryPolicy(pEl, pol);
  } catch (err) {
    sEl.innerHTML = errorState(err.message);
    pEl.innerHTML = errorState(err.message);
  }
}

function renderInventorySummary(host, sum) {
  if (!sum) { host.innerHTML = `<div class="card__title">Inventory summary</div>${state("empty", "No data", "No baseline inventory state available.")}`; return; }
  const probe = (v) => v === null || v === undefined;
  host.innerHTML = `<div class="card__title">Inventory summary <span style="float:right">${provenanceChip("simulated")}</span></div>
    <div class="card__foot" style="margin-top:0">Simulated aggregate over the 28-day horizon under the baseline assumption set. Not observed inventory.</div>
    <div class="kpi-row mt-4">
      ${compactKpi("On-hand", plainNum(sum.on_hand), "sim units")}
      ${compactKpi("On-order", plainNum(sum.on_order), "sim units")}
      ${compactKpi("Backorder", plainNum(sum.backorder), "sim units")}
      ${compactKpi("Inventory position", plainNum(sum.inventory_position), "on-hand + on-order − backorder")}
      ${compactKpi("Days of inventory", numberInCell(sum.days_of_inventory, 1), "avg over horizon")}
      ${compactKpi("Service level", probe(sum.service_level_achieved) ? '<span class="dash">—</span>' : escapeHtml(fmtNum(sum.service_level_achieved * 100, 1)) + "%", "target ~95%")}
      ${compactKpi("Fill rate", probe(sum.fill_rate) ? '<span class="dash">—</span>' : escapeHtml(fmtNum(sum.fill_rate, 3)), "share of demand fulfilled")}
    </div>
    <div class="kpi-row mt-4">
      ${compactKpi("Safety stock", numberInCell(sum.safety_stock, 2), "avg per series")}
      ${compactKpi("Reorder point", numberInCell(sum.reorder_point, 2), "avg per series")}
      ${compactKpi("Stockout exposure", plainNum(sum.stockout_units), "sim units short", "metric--risk")}
      ${compactKpi("Excess inventory", plainNum(sum.excess_inventory), "sim units in excess", "metric--risk")}
    </div>
    <div class="card__foot">Horizon: ${escapeHtml(fmtNum(sum.horizon_days))} simulated days. Undefined metrics render "—".</div>`;
}

function renderInventoryPolicy(host, pol) {
  if (!pol) { host.innerHTML = `<div class="card__title">Policy assumptions</div>${state("empty", "No policy", "No active assumption set found.")}`; return; }
  const r = pol;
  host.innerHTML = `<div class="card__title">Policy assumptions <span style="float:right">${provenanceChip("simulated")}</span></div>
    <div class="card__foot" style="margin-top:0">Baseline assumption set; these rules drove the simulation.</div>
    <dl class="dl mt-4">
      <dt>Assumption set</dt><dd>${escapeHtml(fmtNum(r.assumption_set_id))} · ${escapeHtml(r.policy_name || "—")}</dd>
      <dt>Safety stock</dt><dd>${escapeHtml(r.safety_stock_formula || "—")}</dd>
      <dt>Reorder policy</dt><dd>${escapeHtml(r.reorder_policy || "—")}</dd>
      <dt>Order quantity</dt><dd>${escapeHtml(r.reorder_quantity_rule || "—")}</dd>
      <dt>Lead time</dt><dd class="num">${numberInCell(r.supplier_lead_time_days, 1)} days</dd>
      <dt>Service target</dt><dd>${numberInCell(r.service_level_target, 2)}</dd>
      <dt>Starting inventory</dt><dd>${escapeHtml(r.starting_inventory_rule || "—")}</dd>
    </dl>`;
}

async function viewInventorySeries(token) {
  const host = document.getElementById("inventory-horizon");
  host.innerHTML = spinner();
  let data;
  try {
    data = await api(`/api/inventory/horizon?series=${encodeURIComponent(token)}`);
  } catch (err) {
    host.innerHTML = errorState(err.message);
    return;
  }
  host.innerHTML = renderInventoryHorizon(data);
}

function renderInventoryHorizon(hz) {
  if (!hz || !hz.total || !hz.days || !hz.days.length) {
    return `<div class="card__title">Inventory horizon</div>${state("empty", "No horizon", "No simulated 28-day horizon for that series token.")}`;
  }
  const days = hz.days;
  const maxPos = Math.max(1, ...days.map((d) => d.inventory_position || 0));
  const bars = days.map((d) => {
    const h = Math.max(2, ((d.inventory_position || 0) / maxPos) * 100);
    const danger = d.stockout ? " danger" : "";
    return `<div class="hz-bar${danger}" title="day ${escapeHtml(d.day_id)}: position ${escapeHtml(fmtNum(d.inventory_position))}${d.stockout ? " STOCKOUT" : ""}"></div>`;
  }).join("");
  const rows = days.map((d) => `<tr class="${d.stockout ? "danger-row" : ""}">
    <td>${escapeHtml(fmtNum(d.day_id))}</td>
    <td class="num">${numberInCell(d.inventory_position, 2)}</td>
    <td class="num">${numberInCell(d.on_hand, 2)}</td>
    <td class="num">${numberInCell(d.on_order, 2)}</td>
    <td>${d.stockout ? '<span class="badge badge--warn">Stockout</span>' : "—"}</td>
    <td class="num">${numberInCell(d.stockout_units, 2)}</td>
  </tr>`).join("");
  return `<div class="card__title">Inventory horizon <span style="float:right">${provenanceChip("simulated")}</span></div>
    <div class="card__foot" style="margin-top:0">Simulated 28-day horizon for this series (baseline assumption set). Red bars mark stockout days.</div>
    <div class="hz-bars mt-4">${bars}</div>
    <div class="table-wrap mt-4">
      <table>
        <thead><tr><th scope="col">Day</th><th scope="col" class="num">Position</th><th scope="col" class="num">On-hand</th><th scope="col" class="num">On-order</th><th scope="col">Stockout</th><th scope="col" class="num">Stockout units</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* ---------- boot / events ---------- */
window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => {
  loadDimensionOptions();
  wireFilters();
  wireDemandFilters();
  wireSeriesActions();
  wireStep6();
  route();
});

function wireSeriesActions() {
  const fcBtn = document.getElementById("fc-view-series");
  const fcInput = document.getElementById("fc-series");
  if (fcBtn && fcInput) fcBtn.addEventListener("click", () => {
    const t = fcInput.value.trim();
    if (t) viewForecastSeries(t);
  });
  const invBtn = document.getElementById("inv-view-series");
  const invInput = document.getElementById("inv-series");
  if (invBtn && invInput) invBtn.addEventListener("click", () => {
    const t = invInput.value.trim();
    if (t) viewInventorySeries(t);
  });
  // Enter in a series field triggers the lookup too.
  if (fcInput) fcInput.addEventListener("keydown", (e) => { if (e.key === "Enter" && fcInput.value.trim()) { e.preventDefault(); viewForecastSeries(fcInput.value.trim()); } });
  if (invInput) invInput.addEventListener("keydown", (e) => { if (e.key === "Enter" && invInput.value.trim()) { e.preventDefault(); viewInventorySeries(invInput.value.trim()); } });
}

/* ============================================================
   Step 6 — Scenario Intelligence
   ============================================================ */
const scState = { seq: 0 };

// Scenario types that drive the integrated inventory simulation (have deltas)
// versus the two pure ranking/prioritization runs (no delta aggregates).
const SIMULATION_TYPES = new Set(["baseline", "demand_shock", "lead_time_change", "service_level_change", "reorder_policy"]);
const RANK_TYPES = new Set(["stockout_risk_prioritization", "excess_inventory_prioritization"]);

function scenarioKind(type) {
  if (SIMULATION_TYPES.has(type)) return "simulation";
  if (RANK_TYPES.has(type)) return "rank";
  return "simulation";
}

async function loadScenario() {
  const host = document.getElementById("view-scenario");
  if (!host) return;
  document.getElementById("view-sub-scenario").textContent =
    "What would happen under alternate operating assumptions. Simulation scenarios (demand shock, lead time, service level, reorder policy) report deltas vs the baseline; ranking scenarios (stockout / excess risk) refine the risk worklists. All simulated, never observed.";
  const mySeq = ++scState.seq;
  const statusEl = document.getElementById("scenario-status");
  const deltasEl = document.getElementById("scenario-deltas");
  const cmpEl = document.getElementById("scenario-comparison");
  statusEl.innerHTML = spinner();
  deltasEl.innerHTML = spinner();
  cmpEl.innerHTML = spinner();
  try {
    const [runs, deltas, cmp] = await Promise.all([
      api("/api/scenario/runs"),
      api("/api/scenario/deltas"),
      api("/api/scenario/comparison"),
    ]);
    if (mySeq !== scState.seq) return;
    renderScenarioStatus(statusEl, runs);
    renderScenarioDeltas(deltasEl, deltas);
    renderScenarioComparison(cmpEl, cmp);
    populateScenarioNameOptions(runs);
  } catch (err) {
    if (mySeq !== scState.seq) return;
    statusEl.innerHTML = errorState(err.message);
    deltasEl.innerHTML = errorState(err.message);
    cmpEl.innerHTML = errorState(err.message);
  }
}

function populateScenarioNameOptions(runs) {
  const sel = document.getElementById("sc-name");
  if (!sel || !runs || !runs.runs) return;
  sel.innerHTML = `<option value="">All scenarios</option>` +
    runs.runs.map((r) => `<option value="${escapeHtml(r.scenario_name)}">${escapeHtml(r.scenario_name)}</option>`).join("");
}

function scenarioFilterMatch(run) {
  const sType = document.getElementById("sc-type") ? document.getElementById("sc-type").value : "";
  const sName = document.getElementById("sc-name") ? document.getElementById("sc-name").value : "";
  if (sType && scenarioKind(run.scenario_type) !== sType) return false;
  if (sName && run.scenario_name !== sName) return false;
  return true;
}

function renderScenarioStatus(host, runs) {
  const list = (runs && runs.runs) || [];
  if (!list.length) {
    host.innerHTML = `<div class="card__title">Scenario runs</div>${state("empty", "No scenarios", "No scenario runs are present in the production set.")}`;
    return;
  }
  const view = list.filter(scenarioFilterMatch);
  if (!view.length) {
    host.innerHTML = `<div class="card__title">Scenario runs <span class="caption">· ${provenanceChip("simulated")}</span></div>`
      + `<div class="mt-4">${state("empty", "No matches", "No scenario runs match the current filter.")}</div>`;
    return;
  }
  const rows = view.map((r) => {
    const kind = scenarioKind(r.scenario_type);
    const cls = r.scenario_name === "baseline" ? "scen-row--baseline" : kind === "rank" ? "scen-row--rank" : "";
    const statusNote = r.records_processed != null ? `processed ${fmtNum(r.records_processed)} series` : `status: ${r.status}`;
    const kindLabel = kind === "rank" ? "ranking scenario" : r.scenario_name === "baseline" ? "baseline" : "simulation scenario";
    return `<div class="scen-row ${cls}">
      <div>
        <div class="scen-row__name">${escapeHtml(r.scenario_name)}</div>
        <div class="scen-row__meta">${escapeHtml(r.scenario_type)} · ${escapeHtml(kindLabel)} · assumption set ${r.assumption_set_id != null ? escapeHtml(fmtNum(r.assumption_set_id)) : "—"}</div>
      </div>
      <span class="caption">${escapeHtml(statusNote)}</span>
      <span class="scen-row__stat">${r.executed_at ? escapeHtml(String(r.executed_at).slice(0, 10)) : "—"}</span>
    </div>`;
  }).join("");
  host.innerHTML = `<div class="card__title">Scenario runs <span class="caption">· ${provenanceChip("simulated")}</span></div>
    <div class="scen-status mt-4">${rows}</div>
    <div class="card__foot">Run ${escapeHtml(fmtNum(view.length))} of ${escapeHtml(fmtNum(list.length))}. Simulation scenarios feed the baseline &amp; delta table; ranking scenarios feed the Operational Risk worklists. Never observed data.</div>`;
}

const DELTA_FIELDS = [
  ["delta_stockout_days", "Stockout days", "days", false, "bad"],
  ["delta_service_level", "Service level", "pts", true, "good"],
  ["delta_fill_rate", "Fill rate", "pts", true, "good"],
  ["delta_reorder_frequency", "Reorder frequency", "", false, "neutral"],
  ["delta_avg_inventory_position", "Avg inventory position", "units", false, "neutral"],
  ["delta_excess_days", "Excess days", "days", false, "neutral"],
  ["delta_avg_days_of_inventory", "Avg days of inventory", "days", false, "neutral"],
];

function renderScenarioDeltas(host, deltas) {
  const list = (deltas && deltas.deltas) || [];
  if (!list.length) {
    host.innerHTML = `<div class="card__title">Deltas vs baseline</div>${state("empty", "No deltas", "No per-scenario deltas are available.")}`;
    return;
  }
  const view = list.filter((d) => scenarioFilterMatch({ scenario_name: d.name, scenario_type: d.scenario_type }));
  if (!view.length) {
    host.innerHTML = `<div class="card__title">Deltas vs baseline <span class="caption">· ${provenanceChip("simulated")}</span></div>`
      + `<div class="mt-4">${state("empty", "No matches", "No delta rows match the current filter.")}</div>`;
    return;
  }
  const th = DELTA_FIELDS.map(([, label]) => `<th scope="col" class="num">${escapeHtml(label)}</th>`).join("");
  const rows = view.map((d) => {
    const kind = scenarioKind(d.scenario_type);
    const cls = kind === "rank" ? "scen-row--rank" : d.name === "baseline" ? "scen-row--baseline" : "";
    const tds = DELTA_FIELDS.map(([key, , unit, isPct, tone]) => {
      const v = d[key];
      if (v === null || v === undefined) return "<td class=\"num\"><span class=\"dash\">—</span></td>";
      const dir = v > 0.0005 ? "delta-up" : v < -0.0005 ? "delta-down" : "delta-flat";
      const tonal = isPct ? (v > 0 ? "delta-bad" : "delta-good") : (tone === "bad" ? (v > 0 ? "delta-bad" : "delta-good") : "delta-good");
      let shown = fmtNum(v, 3);
      if (isPct) shown = (v > 0 ? "+" : "") + fmtNum((v * 100), 2);
      return `<td class="num ${dir} ${tonal}">${escapeHtml(shown)}</td>`;
    }).join("");
    const rankTag = kind === "rank" ? '<span class="badge badge--pilot">ranking · no delta</span>' : "";
    return `<tr class="${cls}"><td>${escapeHtml(d.name)} ${rankTag}</td>${tds}<td class="num">${escapeHtml(fmtNum(d.series_count))}</td></tr>`;
  }).join("");
  host.innerHTML = `<div class="card__title">Deltas vs baseline <span class="caption">· ${provenanceChip("simulated")}</span></div>
    <div class="table-wrap mt-4">
      <table>
        <thead><tr><th scope="col">Scenario</th>${th}<th scope="col" class="num">Series count</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="card__foot">Average per-series change vs the baseline (run 1) across the simulated horizon. Service level / fill-rate deltas are percentage-point changes (×100); ranking scenarios have no delta aggregates and show "—". Positive stockout/excess days are simulated downside; positive service-level/fill-rate are upside.</div>`;
}

function renderScenarioComparison(host, cmp) {
  if (!cmp) { host.innerHTML = `<div class="card__title">Action tradeoff comparison</div>${state("empty", "Unavailable", "No comparison data.")}`; return; }
  if (cmp.present) {
    host.innerHTML = `<div class="card__title">Action tradeoff comparison <span class="caption">· ${provenanceChip("simulated")}</span></div>`
      + `<div class="mt-4"><b>${escapeHtml(fmtNum(cmp.rows))} comparison rows available.</b> ${escapeHtml(cmp.reason || "")}</div>`;
    return;
  }
  host.innerHTML = `<div class="card__title">Action tradeoff comparison <span class="caption">· ${provenanceChip("simulated")}</span></div>
    <div class="caveat mt-4">No action-tradeoff comparison is currently available.</div>
    <div class="card__foot">fact_scenario_comparison has 0 rows by design. No recommendations are shown because the recommendation surface (fact_replenishment_recommendation) is not yet populated.</div>`;
}

function loadScenarioFiltered() {
  // Client-side filter of the already-fetched scenario lists; re-render in place.
  scState.seq++;
  const statusEl = document.getElementById("scenario-status");
  const deltasEl = document.getElementById("scenario-deltas");
  Promise.all([
    api("/api/scenario/runs").catch(() => null),
    api("/api/scenario/deltas").catch(() => null),
  ]).then(([runs, deltas]) => {
    if (!runs) { statusEl.innerHTML = errorState("Could not reload scenario runs."); return; }
    renderScenarioStatus(statusEl, runs);
    renderScenarioDeltas(deltasEl, deltas);
  });
}

/* ============================================================
   Step 6 — Risk Intelligence
   ============================================================ */
const rkState = { page: 1, pageSize: 25, seq: 0, lastKey: null };

function rkFilterFromForm() {
  const v = (id) => (document.getElementById(id) ? document.getElementById(id).value : "") || undefined;
  return {
    risk_type: v("rk-type") || "stockout",
    tier: v("rk-tier"),
    department: v("rk-department"),
    category: v("rk-category"),
    state: v("rk-state"),
    store: v("rk-store"),
    product: document.getElementById("rk-product") ? document.getElementById("rk-product").value.trim() || undefined : undefined,
  };
}
function rkFilterQuery(filter) {
  const q = new URLSearchParams();
  for (const k of ["risk_type", "tier", "department", "category", "state", "store", "product"]) {
    if (filter[k]) q.set(k, filter[k]);
  }
  q.set("page_size", String(rkState.pageSize));
  return q;
}

function loadRisk() {
  const host = document.getElementById("view-risk");
  if (!host) return;
  document.getElementById("view-sub-risk").textContent =
    "Ranked product × store risk worklists from the simulated stockout and excess-inventory runs (native rank 1..30,490). Open a ranked series to inspect its risk components and evidence.";
  const key = rkFilterQuery(rkFilterFromForm()).toString();
  if (key === rkState.lastKey) return;
  rkState.lastKey = key;
  loadRiskData();
}

async function loadRiskData() {
  const mySeq = ++rkState.seq;
  const filter = rkFilterFromForm();
  const q = rkFilterQuery(filter);
  q.set("page", String(rkState.page));
  const tableEl = document.getElementById("risk-table");
  const distEl = document.getElementById("risk-distribution");
  tableEl.innerHTML = spinner();
  let data = null;
  try {
    data = await api(`/api/risk/rankings?${q.toString()}`);
  } catch (err) {
    if (rkState.seq === mySeq) tableEl.innerHTML = errorState(err.message);
    return;
  }
  if (rkState.seq !== mySeq) return; // stale — a newer load owns the table
  const distQ = rkFilterQuery(filter);
  const distData = await api(`/api/risk/rankings?${distQ.toString()}&page=1&page_size=1`).catch(() => null);
  if (rkState.seq !== mySeq) return;
  renderRiskDistribution(distEl, distData);
  renderRiskTable(tableEl, data, mySeq);
  wireRiskPagination();
  wireRiskRowClick();
}

function renderRiskDistribution(host, r) {
  if (!r) { host.innerHTML = `<div class="card__title">Risk distribution</div>${state("empty", "Unavailable", "Could not load risk distribution.")}`; return; }
  const total = (r.pagination && r.pagination.total) || 0;
  const type = r.risk_type === "stockout" ? "Stockout risk" : "Excess inventory risk";
  host.innerHTML = `<div class="card__title">Risk distribution <span class="caption">· ${provenanceChip("simulated")}</span></div>
    <div class="kpi-row mt-4">
      ${compactKpi("Ranked series", total ? escapeHtml(fmtNum(total)) : '<span class="dash">—</span>', type + " · matching filters")}
      ${compactKpi("Ranking basis", "native rank", "deterministic 1..30,490")}
      ${compactKpi("Tier levels", "4 tiers", "Critical · High · Medium · Low")}
      ${compactKpi("Drill-down", "row click", "opens risk components")}
    </div>
    <div class="card__foot">Tier per ranked series is shown as a chip on each worklist row; select a row to open its risk-component evidence. ${escapeHtml(fmtNum(total))} series match the current filters (server-side).</div>`;
}

function riskEvidenceItems(evidence) {
  const order = [["urgency", "Urgency"], ["service_gap", "Service gap"], ["volume_rank", "Volume rank"], ["stockout_prob", "Stockout probability"], ["volatility_rank", "Volatility rank"], ["dominant", "Dominant driver"]];
  return order
    .filter(([k]) => evidence && evidence[k] !== undefined && evidence[k] !== null)
    .map(([k, label]) => {
      const v = evidence[k];
      const shown = typeof v === "number" ? fmtNum(v, 3) : escapeHtml(String(v));
      return `<div class="evidence__item"><span class="evidence__label">${escapeHtml(label)}</span><div class="evidence__val">${escapeHtml(shown)}</div></div>`;
    }).join("");
}

function renderRiskTable(host, data, seq = rkState.seq) {
  const items = (data && data.items) || [];
  const rows = items.map((r) => {
    const score = r.risk_score == null ? '<span class="dash">—</span>' : `<span class="risk-score-cell">${escapeHtml(fmtNum(Math.round(r.risk_score * 1000) / 10))}%</span>`;
    const driver = r.primary_driver || "—";
    return `<tr class="risk-row" data-series="${escapeHtml(r.product)}:${escapeHtml(r.store)}" tabindex="0">
      <td class="num">${escapeHtml(fmtNum(r.risk_rank))}</td>
      <td>${tierChip(r.risk_tier || "—")}</td>
      <td><span class="series-key">${escapeHtml(r.product)}</span> · ${escapeHtml(r.store)}</td>
      <td>${escapeHtml(r.department || "—")}</td>
      <td>${escapeHtml(r.category || "—")}</td>
      <td>${escapeHtml(r.state || "—")}${r.region ? " / " + escapeHtml(r.region) : ""}</td>
      <td class="num">${score}</td>
      <td>${escapeHtml(driver)}</td>
    </tr>`;
  }).join("");
  const tbody = rows || `<tr class="tbody-empty"><td colspan="8">No ranked series match the current filters.</td></tr>`;
  const pg = (data && data.pagination) || {};
  const total = pg.total || 0;
  const page = pg.page || 1;
  const per = pg.page_size || rkState.pageSize;
  const pages = Math.max(1, Math.ceil(total / per));
  const type = data && data.risk_type;
  host.innerHTML = `<div class="card__title">Risk worklist <span class="caption">· ${provenanceChip("simulated")}</span></div>
    <div class="table-wrap mt-4">
      <table>
        <thead><tr><th scope="col" class="num">Rank</th><th scope="col">Tier</th><th scope="col">Product · Store</th><th scope="col">Department</th><th scope="col">Category</th><th scope="col">State / Region</th><th scope="col" class="num">Risk score</th><th scope="col">Dominant driver</th></tr></thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>
    <div class="table-toolbar mt-4">
      <div class="pagination">
        <button ${page <= 1 ? "disabled" : ""} data-risk-page="${page - 1}">‹ Prev</button>
        <span class="pagination__info">Page ${page} of ${pages} · ${escapeHtml(fmtNum(total))} ranked series</span>
        <button ${page >= pages ? "disabled" : ""} data-risk-page="${page + 1}">Next ›</button>
      </div>
    </div>
    <div class="card__foot">Deterministic by native risk rank; click a row to open its risk-component evidence. ${type === "stockout" ? "Stockout" : "Excess"} risk · ${escapeHtml(fmtNum(total))} series in the current selection.</div>`;
}

async function openRiskDriver(token) {
  const host = document.getElementById("risk-driver");
  host.innerHTML = spinner();
  let data;
  try {
    data = await api(`/api/risk/drivers?series=${encodeURIComponent(token)}`);
  } catch (err) {
    host.innerHTML = errorState(err.message);
    return;
  }
  renderRiskDriver(host, data, token);
}

function renderRiskDriver(host, d, token) {
  if (!d || !d.components || !Object.keys(d.components).length) {
    host.innerHTML = `<div class="card__title">Risk driver — ${escapeHtml(token)} <span class="caption">· ${provenanceChip("simulated")}</span></div>`
      + `<div class="mt-4">${state("empty", "No component detail", "No risk-component evidence stored for that series token.")}</div>`;
    return;
  }
  const rank = d.risk_rank;
  const score = d.risk_score == null ? '<span class="dash">—</span>' : escapeHtml(fmtNum(Math.round(d.risk_score * 1000) / 10)) + "%";
  const tier = tierChip(d.risk_tier || "—");
  const evidence = riskEvidenceItems(d.components);
  host.innerHTML = `<div class="card__title">Risk driver — <span class="series-key">${escapeHtml(token)}</span> <span class="caption">· ${provenanceChip("simulated")}</span></div>
    <div class="kpi-row mt-4">
      ${compactKpi("Native risk rank", rank != null ? escapeHtml(fmtNum(rank)) : '<span class="dash">—</span>', "within the risk type")}
      ${compactKpi("Risk score", score, "0–1 scaled")}
      ${compactKpi("Tier", tier, "prioritization")}
    </div>
    <div class="card__foot" style="margin-top:0">Evidence components for this series from the simulated risk run. Values are rank-normalized 0–1 unless noted.</div>
    <div class="evidence mt-4">${evidence}</div>`;
}

function wireRiskPagination() {
  document.querySelectorAll("[data-risk-page]").forEach((btn) => {
    btn.onclick = () => {
      rkState.page = parseInt(btn.dataset.riskPage, 10);
      loadRiskData();
    };
  });
}

function wireRiskRowClick() {
  function open(btn) {
    const token = btn.getAttribute("data-series");
    if (token) openRiskDriver(token);
  }
  document.querySelectorAll(".risk-row").forEach((row) => {
    row.onclick = () => open(row);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(row); } });
  });
}

function wireStep6() {
  // Scenario filters (client-side re-render of loaded data; comparison stays empty).
  const scSels = ["sc-type", "sc-name"];
  scSels.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", loadScenarioFiltered);
  });
  const scReset = document.getElementById("sc-reset");
  if (scReset) scReset.addEventListener("click", () => {
    scSels.forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
    loadScenarioFiltered();
  });

  // Risk filters (server-side via existing endpoint) + reset.
  const rkIds = ["rk-type", "rk-tier", "rk-department", "rk-category", "rk-state", "rk-store"];
  rkIds.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => { rkState.lastKey = ""; rkState.page = 1; loadRiskData(); });
  });
  const rkProd = document.getElementById("rk-product");
  if (rkProd) rkProd.addEventListener("change", () => { rkState.lastKey = ""; rkState.page = 1; loadRiskData(); });
  const rkTopn = document.getElementById("rk-topn");
  if (rkTopn) rkTopn.addEventListener("change", () => {
    rkState.pageSize = parseInt(rkTopn.value, 10) || 25;
    rkState.page = 1;
    rkState.lastKey = "";
    loadRiskData();
  });
  const rkReset = document.getElementById("rk-reset");
  if (rkReset) rkReset.addEventListener("click", () => {
    rkIds.forEach((id) => { const el = document.getElementById(id); if (el) el.value = ""; });
    if (rkProd) rkProd.value = "";
    const typ = document.getElementById("rk-type");
    if (typ) typ.value = "stockout";
    const topn = document.getElementById("rk-topn");
    if (topn) topn.value = "25";
    rkState.page = 1;
    rkState.pageSize = 25;
    rkState.lastKey = "";
    loadRiskData();
  });
}