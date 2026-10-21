/* NetzwerkScanner Dashboard */
"use strict";

const S = { scans: [], scan: null, plan: {}, dev: {}, sw: {}, cfg: null, topo: null, logPos: 0, poll: null };

const STATUS = {
  "belegt": "Belegt", "uplink": "Uplink (Switch)", "nachbar": "Nachbar (LLDP/CDP)",
  "aktiv-ohne-geraet": "Link aktiv, kein Geraet", "down-beschriftet": "Down, aber beschriftet",
  "deaktiviert": "Deaktiviert", "frei": "Frei",
};
const PATCH = ["belegt", "uplink", "nachbar", "aktiv-ohne-geraet", "down-beschriftet"];
const BAR_COLORS = { "belegt": "#4caf50", "uplink": "#2f6fd6", "nachbar": "#6fa8dc", "aktiv-ohne-geraet": "#d4a017",
  "down-beschriftet": "#e07b39", "deaktiviert": "#9e9e9e", "frei": "#c9ced6" };
const VLAN_COLORS = ["#2f6fd6", "#e07b39", "#2e9e5b", "#9c4dcc", "#d64550", "#1b9aaa", "#c49a00", "#6d6875",
  "#ef476f", "#118ab2", "#8ac926", "#ff924c"];

// ------------------------------------------------------------------ Helfer
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function natKey(s) { return String(s || "").split(/(\d+)/).map(t => /^\d+$/.test(t) ? t.padStart(8, "0") : t.toLowerCase()).join(""); }
function ipNum(ip) { const p = String(ip || "").split("."); return p.length === 4 ? ((+p[0] * 256 + +p[1]) * 256 + +p[2]) * 256 + +p[3] : 0; }
function fmtDate(s) { if (!s) return ""; const d = new Date(s); return isNaN(d) ? s : d.toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" }); }
function speed(m) { return !m ? "" : m >= 1000 ? (m / 1000) + "G" : m + "M"; }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function toast(msg, ms = 3000) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove("show"), ms); }
function stDot(st) { return `<span class="st st-${st}"></span>`; }
function devName(d) { return d.hostname || d.lldp_name || d.netbios_name || ""; }
function planKey(swName, portName) { return swName + "|" + portName; }
function vlanColor(v) { return v ? VLAN_COLORS[Math.abs(+v) % VLAN_COLORS.length] : "#8a94a6"; }

async function api(path, opts = {}) {
  if (opts.body && typeof opts.body !== "string" && !(opts.body instanceof FormData)) {
    opts.body = JSON.stringify(opts.body);
    opts.headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  }
  const r = await fetch(path, opts);
  if (r.status === 401) { location.href = "/login"; throw new Error("nicht angemeldet"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return data;
}

function sortableTable(table, columns, rows, opts = {}) {
  // columns: [{key, label, render?(row), sort?(row), cls}]
  const state = table._sort || { key: opts.sortKey || null, dir: 1 };
  table._sort = state;
  const col = columns.find(c => c.key === state.key);
  if (col) {
    const f = col.sort || (r => r[col.key]);
    rows = rows.slice().sort((a, b) => {
      const x = f(a), y = f(b);
      if (typeof x === "number" && typeof y === "number") return (x - y) * state.dir;
      return natKey(x).localeCompare(natKey(y)) * state.dir;
    });
  }
  const limit = opts.limit || 3000;
  const head = "<thead><tr>" + columns.map(c => `<th data-k="${c.key}" class="${state.key === c.key ? (state.dir > 0 ? "sorted-asc" : "sorted-desc") : ""}">${esc(c.label)}</th>`).join("") + "</tr></thead>";
  const body = rows.slice(0, limit).map((r, i) => `<tr class="${opts.onClick ? "click" : ""}" data-i="${i}">` +
    columns.map(c => `<td class="${c.cls || ""}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join("") + "</tr>").join("");
  const more = rows.length > limit ? `<tr><td colspan="${columns.length}" class="muted">... ${rows.length - limit} weitere - bitte Filter verwenden</td></tr>` : "";
  table.innerHTML = head + "<tbody>" + (body || `<tr><td colspan="${columns.length}" class="muted">Keine Eintraege</td></tr>`) + more + "</tbody>";
  $$("th", table).forEach(th => th.onclick = () => {
    if (state.key === th.dataset.k) state.dir = -state.dir; else { state.key = th.dataset.k; state.dir = 1; }
    sortableTable(table, columns, rows, opts);
  });
  if (opts.onClick) $$("tbody tr[data-i]", table).forEach(tr => tr.onclick = (e) => {
    if (e.target.closest("input,button,a,select")) return;
    opts.onClick(rows[+tr.dataset.i]);
  });
}

function showModal(html) { $("#modal").innerHTML = html + `<div class="right" style="margin-top:14px"><button onclick="hideModal()">Schliessen</button></div>`; $("#modalBg").classList.add("show"); }
function hideModal() { $("#modalBg").classList.remove("show"); }
$("#modalBg").addEventListener("click", e => { if (e.target.id === "modalBg") hideModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") hideModal(); });

// ------------------------------------------------------------------ Tabs & Theme
function showTab(name) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + name));
  try { localStorage.setItem("ns-tab", name); } catch (e) { /* egal */ }
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  if (name === "topology") renderTopology();
  if (name === "scan") loadScanTab();
}
$$("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
(function theme() {
  let t = null; try { t = localStorage.getItem("ns-theme"); } catch (e) { /* egal */ }
  if (t) document.documentElement.dataset.theme = t;
  $("#themeBtn").onclick = () => {
    const dark = document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
    const n = dark ? "light" : "dark";
    document.documentElement.dataset.theme = n;
    try { localStorage.setItem("ns-theme", n); } catch (e) { /* egal */ }
    if (S.topo) { S.topo.destroy(); S.topo = null; renderTopology(); }
  };
})();
function isDark() {
  const t = document.documentElement.dataset.theme;
  return t === "dark" || (!t && matchMedia("(prefers-color-scheme: dark)").matches);
}

// Report-Menue
$("#reportBtn").onclick = (e) => { e.stopPropagation(); $("#reportDd").classList.toggle("open"); };
document.addEventListener("click", () => $("#reportDd").classList.remove("open"));
$$("#reportDd .menu a").forEach(a => a.onclick = (e) => {
  e.preventDefault();
  if (!S.scan) { toast("Kein Scan geladen"); return; }
  location.href = `/report/${encodeURIComponent(S.scan.id)}/${a.dataset.fmt}`;
});

// ------------------------------------------------------------------ Laden
async function loadScans(selectId) {
  S.scans = await api("/api/scans");
  const sel = $("#scanSelect");
  sel.innerHTML = S.scans.map(s => `<option value="${esc(s.id)}">${esc(s.name || s.id)} - ${esc(fmtDate(s.finished || s.started))}</option>`).join("") || `<option value="">(kein Scan)</option>`;
  const id = selectId || (S.scan && S.scans.find(s => s.id === S.scan.id) ? S.scan.id : (S.scans[0] && S.scans[0].id));
  if (id) { sel.value = id; await loadScan(id); } else { S.scan = null; renderAll(); }
  for (const id2 of ["#cmpA", "#cmpB"]) {
    const prev = $(id2).value;
    $(id2).innerHTML = S.scans.map(s => `<option value="${esc(s.id)}">${esc(s.name || s.id)} (${esc(fmtDate(s.finished))})</option>`).join("");
    if (prev) $(id2).value = prev;
  }
  if (S.scans.length > 1 && !$("#cmpA")._init) { $("#cmpA").value = S.scans[1].id; $("#cmpB").value = S.scans[0].id; $("#cmpA")._init = true; }
}
$("#scanSelect").onchange = (e) => loadScan(e.target.value);

async function loadScan(id) {
  if (!id) return;
  const [scan, plan] = await Promise.all([api("/api/scans/" + encodeURIComponent(id)), api("/api/plan")]);
  S.scan = scan; S.plan = plan;
  S.dev = {}; scan.devices.forEach(d => S.dev[d.id] = d);
  S.sw = {}; scan.switches.forEach(s => S.sw[s.id] = s);
  if (S.topo) { S.topo.destroy(); S.topo = null; }
  // kleine Netze: Endgeraete direkt in der Topologie zeigen, grosse Netze bleiben uebersichtlich
  $("#topoDevices").checked = scan.devices.filter(d => !d.virtual).length <= 400;
  renderAll();
}

async function loadDemo() {
  const r = await api("/api/demo", { method: "POST" });
  await loadScans(r.id);
  toast("Demo-Scan geladen (simulierte Switches)");
}

function renderAll() {
  const has = !!S.scan;
  $("#noScan").style.display = has ? "none" : "";
  $("#overviewBody").style.display = has ? "" : "none";
  $("#scanInfo").textContent = has ? `${S.scan.stats.devices} Geraete, ${S.scan.stats.switches} Switches` : "";
  if (!has) return;
  fillFilters();
  renderOverview();
  renderSwitches();
  renderDevices();
  renderVlans();
  renderPlan();
  if ($("#tab-topology").classList.contains("active")) renderTopology();
}

function legendHtml() {
  return Object.entries(STATUS).map(([k, v]) => `<span>${stDot(k)}${esc(v)}</span>`).join("") +
    `<span><span class="st" style="background:#7b2cbf;border-color:#7b2cbf;height:4px"></span>LAG-Mitglied</span>` +
    `<span><span class="st" style="background:#7b2cbf;border-color:#7b2cbf;border-radius:50%"></span>mehrere Geraete/VMs</span>`;
}

function fillFilters() {
  const vl = S.scan.vlans.map(v => `<option value="${v.id}">VLAN ${v.id}${v.name ? " - " + esc(v.name) : ""}</option>`).join("");
  $("#topoVlan").innerHTML = `<option value="">Alle VLANs</option>` + vl;
  $("#devVlan").innerHTML = `<option value="">Alle VLANs</option><option value="none">ohne VLAN</option>` + vl;
  const sw = S.scan.switches.map(s => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
  $("#swFilter").innerHTML = `<option value="">Alle Switches</option>` + sw;
  $("#devSwitch").innerHTML = `<option value="">Alle Switches</option>` + sw;
  $("#planSwitch").innerHTML = `<option value="">Alle Switches</option>` + sw;
  const types = [...new Set(S.scan.devices.map(d => d.type))].sort();
  $("#devType").innerHTML = `<option value="">Alle Typen</option>` + types.map(t => `<option>${esc(t)}</option>`).join("");
  $("#legend1").innerHTML = legendHtml();
  $("#legend2").innerHTML = legendHtml();
}

// ------------------------------------------------------------------ Uebersicht
function renderOverview() {
  const st = S.scan.stats;
  const k = (v, l, cls = "") => `<div class="kpi ${cls}"><div class="v">${v ?? 0}</div><div class="l">${l}</div></div>`;
  $("#kpis").innerHTML =
    k(st.switches, "Switches / Router") +
    k(st.devices, "Geraete gesamt") +
    k(st.devices_with_port, "mit Switch-Port") +
    k(st.devices_without_port, "ohne Port-Zuordnung", st.devices_without_port ? "alert" : "") +
    k(st.devices_with_hostname, "mit Hostname") +
    k(st.vlans, "VLANs") +
    k(st.ports_patch, "zu patchende Ports") +
    k(st.ports_up_no_device, "Link aktiv, kein Geraet", st.ports_up_no_device ? "attn" : "") +
    k(st.ports_uplink, "Uplink-Ports") +
    k(st.virtual, "virtuelle Maschinen");
  const w = (S.scan.warnings || []);
  let wh = "";
  if (st.devices_without_port) wh += `<div class="card" style="border-left:4px solid var(--danger)"><b>${st.devices_without_port} Geraete ohne Switch-Port-Zuordnung.</b> <span class="muted">Diese haengen vermutlich an nicht gescannten Switches oder ihr MAC-Eintrag ist abgelaufen. Bitte vor dem Umzug pruefen.</span> <a href="#" onclick="showNoPort();return false">Anzeigen</a></div>`;
  if (st.ports_up_no_device) wh += `<div class="card" style="border-left:4px solid var(--warn)"><b>${st.ports_up_no_device} Ports mit aktivem Link, aber ohne erkanntes Geraet</b> <span class="muted">(stille Geraete, z.B. Storage-Replikation, iLO/iDRAC ohne Traffic, Media-Converter). Diese Ports stehen trotzdem in der Patchliste.</span></div>`;
  if (w.length) wh += `<div class="card"><details><summary><b>${w.length} Hinweise aus dem Scan</b></summary><ul class="small">${w.map(x => `<li>${esc(x)}</li>`).join("")}</ul></details></div>`;
  $("#warnings").innerHTML = wh;
  const rows = S.scan.switches.map(s => {
    const phys = s.ports.filter(p => !p.is_lag);
    return Object.assign({}, s, { total: phys.length, up: phys.filter(p => p.oper === "up").length,
      patch: phys.filter(p => PATCH.includes(p.status)).length, counts: s.port_counts });
  });
  sortableTable($("#ovSwitches"), [
    { key: "name", label: "Switch", render: r => `<b>${esc(r.name)}</b>` },
    { key: "ip", label: "IP", cls: "mono", sort: r => ipNum(r.ip) },
    { key: "model", label: "Modell" },
    { key: "location", label: "Standort" },
    { key: "patch", label: "Zu patchen", cls: "right" },
    { key: "up", label: "Up / Ports", cls: "right", render: r => `${r.up} / ${r.total}` },
    { key: "bar", label: "Port-Belegung", render: r => statusBar(r.ports.filter(p => !p.is_lag)) },
  ], rows, { onClick: r => { $("#swFilter").value = r.id; renderSwitches(); showTab("switches"); } });
}
function statusBar(ports) {
  const c = {}; ports.forEach(p => c[p.status] = (c[p.status] || 0) + 1);
  const n = ports.length || 1;
  return `<div class="bar" title="${Object.entries(c).map(([k, v]) => STATUS[k] + ": " + v).join(", ")}">` +
    Object.keys(STATUS).filter(k => c[k]).map(k => `<span style="width:${100 * c[k] / n}%;background:${BAR_COLORS[k]}"></span>`).join("") + "</div>";
}
function showNoPort() { $("#devNoPort").checked = true; renderDevices(); showTab("devices"); }

// ------------------------------------------------------------------ Switches / Frontansicht
function portGroups(ports) {
  const groups = new Map();
  ports.filter(p => !p.is_lag).sort((a, b) => natKey(a.name).localeCompare(natKey(b.name))).forEach(p => {
    const key = p.name.replace(/\d+$/, "") || "Ports";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  });
  return groups;
}
function portNum(name) { const m = String(name).match(/(\d+)$/); return m ? m[1] : String(name).slice(0, 3); }
function portTitle(s, p) {
  const lines = [`${s.name} ${p.name}  [${STATUS[p.status]}]`];
  if (p.alias) lines.push("Beschreibung: " + p.alias);
  lines.push(`Link: ${p.oper}${p.speed ? " " + speed(p.speed) : ""}  Modus: ${p.mode || "-"}  VLAN: ${p.vlans || "-"}`);
  if (p.lag) lines.push("LAG: " + p.lag);
  if (p.uplink_name) lines.push("Uplink zu: " + p.uplink_name);
  (p.neighbors || []).forEach(n => lines.push(`${n.source}: ${n.name || n.chassis_id} ${n.port_id || ""}`));
  p.device_ids.slice(0, 8).forEach(id => { const d = S.dev[id]; if (d) lines.push(`- ${devName(d) || "?"}  ${d.ip || ""}  ${d.mac || ""}`); });
  if (p.device_ids.length > 8) lines.push(`  ... ${p.device_ids.length - 8} weitere`);
  return lines.join("\n");
}
function matchesSearch(p, q) {
  if (!q) return true;
  const hay = [p.name, p.alias, p.uplink_name, ...(p.neighbors || []).map(n => n.name)];
  p.device_ids.forEach(id => { const d = S.dev[id]; if (d) hay.push(devName(d), d.ip, d.mac, d.vendor, ...(d.ips || [])); });
  return hay.some(h => String(h || "").toLowerCase().includes(q));
}
function renderSwitches() {
  const f = $("#swFilter").value, q = $("#swSearch").value.trim().toLowerCase(), showTable = $("#swTable").checked;
  const list = S.scan.switches.filter(s => !f || s.id === f);
  $("#switchList").innerHTML = list.map(s => {
    const groups = portGroups(s.ports);
    const fp = [...groups.entries()].map(([key, ps]) => `<div class="fp-group"><div class="fp-label">${esc(key)}</div><div class="fp-ports">` +
      ps.map(p => {
        const done = (S.plan[planKey(s.name, p.name)] || {}).done;
        const cls = ["port", "p-" + p.status, p.lag ? "lagm" : "", p.device_ids.length > 1 ? "multi" : "", q && !matchesSearch(p, q) ? "dim" : "", done ? "done" : ""].join(" ");
        return `<div class="${cls}" data-sw="${esc(s.id)}" data-p="${esc(p.id)}" title="${esc(portTitle(s, p))}">${esc(portNum(p.name))}</div>`;
      }).join("") + `</div></div>`).join("");
    const lags = s.ports.filter(p => p.is_lag);
    const lagHtml = lags.length ? `<div class="lag-chips">` + lags.map(p => `<span class="pill" style="cursor:pointer" data-sw="${esc(s.id)}" data-p="${esc(p.id)}" title="${esc(portTitle(s, p))}">${stDot(p.status)}${esc(p.name)}: ${esc(p.lag_members.join(", ") || "-")}</span>`).join("") + `</div>` : "";
    const errs = (s.errors || []).length ? `<span class="pill gray" title="${esc(s.errors.join("\n"))}">${s.errors.length} SNMP-Hinweise</span>` : "";
    return `<div class="card switch-card" id="card-${esc(s.id)}">
      <div class="card-head"><h3>${esc(s.name)}</h3><span class="mono">${esc(s.ip)}</span>
        <span class="pill">${esc(s.vendor || "")}</span>${s.is_router ? '<span class="pill gray">L3</span>' : ""}${errs}
        <div style="flex:1"></div>${statusBar(s.ports.filter(p => !p.is_lag))}</div>
      <div class="meta">${esc([s.model, s.serial ? "SN " + s.serial : "", s.sw_version, s.location].filter(Boolean).join(" | "))}</div>
      <div class="faceplate">${fp || '<span class="muted">Keine physischen Ports gefunden</span>'}</div>${lagHtml}
      <div class="port-detail" id="pd-${esc(s.id)}" style="display:none"></div>
      ${showTable ? `<div class="tablewrap" style="margin-top:10px"><table class="data" id="pt-${esc(s.id)}"></table></div>` : ""}
    </div>`;
  }).join("") || `<div class="card empty">Keine Switches im Scan. SNMP-Geraete unter "Scan &amp; Einstellungen" eintragen.</div>`;
  $$("#switchList [data-p]").forEach(el => el.onclick = () => showPort(el.dataset.sw, el.dataset.p, el));
  if (showTable) list.forEach(s => portTable($("#pt-" + CSS.escape(s.id)), s, true));
}
function portTable(table, s, all) {
  const rows = s.ports.filter(p => !p.is_lag && (all || PATCH.includes(p.status))).map(p => {
    const d = S.dev[p.device_ids[0]] || {};
    return Object.assign({}, p, { dev: devName(d), ip: d.ip || "", mac: d.mac || "", more: p.device_ids.length - 1 });
  });
  sortableTable(table, [
    { key: "name", label: "Port", render: r => `${stDot(r.status)}<b>${esc(r.name)}</b>`, sort: r => r.name },
    { key: "alias", label: "Beschreibung" },
    { key: "status", label: "Status", render: r => esc(STATUS[r.status]) },
    { key: "vlans", label: "VLAN" },
    { key: "dev", label: "Geraet", render: r => `<b>${esc(r.dev || r.uplink_name)}</b>${r.more > 0 ? ` <span class="pill">+${r.more}</span>` : ""}` },
    { key: "ip", label: "IP", cls: "mono", sort: r => ipNum(r.ip) },
    { key: "mac", label: "MAC", cls: "mono" },
  ], rows, { onClick: r => showPort(s.id, r.id) });
}
function showPort(swId, portId, el) {
  const s = S.sw[swId], p = s.ports.find(x => x.id === portId);
  $$(".port.sel").forEach(x => x.classList.remove("sel"));
  if (el) el.classList.add("sel");
  const box = $("#pd-" + CSS.escape(swId));
  const devs = p.device_ids.map(id => S.dev[id]).filter(Boolean);
  const pl = S.plan[planKey(s.name, p.name)] || {};
  box.style.display = "";
  box.innerHTML = `<div class="row"><h3 style="margin:0">${stDot(p.status)}${esc(s.name)} - Port ${esc(p.name)}</h3><span class="pill gray">${esc(STATUS[p.status])}</span>
      <div style="flex:1"></div><button class="sm" onclick="this.closest('.port-detail').style.display='none'">Schliessen</button></div>
    <div class="grid g2" style="margin-top:8px">
      <dl class="kv">
        <dt>Beschreibung</dt><dd>${esc(p.alias || "-")}</dd>
        <dt>Link / Admin</dt><dd>${esc(p.oper)} / ${esc(p.admin)} ${p.speed ? "(" + speed(p.speed) + ")" : ""}</dd>
        <dt>Modus / VLAN</dt><dd>${esc(p.mode || "-")} / ${esc(p.vlans || "-")}${p.pvid ? " (PVID " + p.pvid + ")" : ""}</dd>
        ${p.lag ? `<dt>LAG</dt><dd>${esc(p.lag)}</dd>` : ""}
        ${p.lag_members && p.lag_members.length ? `<dt>LAG-Mitglieder</dt><dd>${esc(p.lag_members.join(", "))} - <b>alle Kabel umstecken!</b></dd>` : ""}
        ${p.uplink_name ? `<dt>Uplink zu</dt><dd>${esc(p.uplink_name)}</dd>` : ""}
        <dt>MACs am Port</dt><dd>${p.mac_count}</dd>
        ${(p.neighbors || []).map(n => `<dt>${esc(n.source)}-Nachbar</dt><dd>${esc(n.name || n.chassis_id)} Port ${esc(n.port_id || n.port_desc || "")} ${n.mgmt_ip ? "(" + esc(n.mgmt_ip) + ")" : ""}<br><span class="muted small">${esc((n.caps || []).join(", "))} ${esc(n.descr || "")}</span></dd>`).join("")}
      </dl>
      <dl class="kv">
        <dt>Ziel-Switch</dt><dd>${esc(pl.target_switch || "-")}</dd><dt>Ziel-Port</dt><dd>${esc(pl.target_port || "-")}</dd>
        <dt>Kabel-Label</dt><dd>${esc(pl.label || "-")}</dd><dt>Bemerkung</dt><dd>${esc(pl.note || "-")}</dd>
        <dt>Erledigt</dt><dd>${pl.done ? '<span class="pill green">ja</span>' : "nein"}</dd>
      </dl>
    </div>
    ${devs.length ? `<div class="tablewrap" style="margin-top:10px"><table class="data">
      <thead><tr><th>Hostname</th><th>IP</th><th>MAC</th><th>Hersteller</th><th>Typ</th><th>VLAN</th><th>Zuordnung</th></tr></thead><tbody>
      ${devs.map(d => `<tr class="click" onclick="showDevice('${esc(d.id)}')"><td><b>${esc(devName(d))}</b></td><td class="mono">${esc((d.ips || []).join(", ") || d.ip)}</td><td class="mono">${esc(d.mac)}</td><td>${esc(d.vendor)}</td><td>${esc(d.type)}</td><td>${esc(d.vlan ?? "")}</td><td>${esc(d.assignment)}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="muted">Kein Geraet an diesem Port erkannt.</p>`}`;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
$("#swFilter").onchange = renderSwitches;
$("#swTable").onchange = renderSwitches;
$("#swSearch").oninput = debounce(renderSwitches, 250);

// ------------------------------------------------------------------ Geraete
function renderDevices() {
  const q = $("#devSearch").value.trim().toLowerCase(), vl = $("#devVlan").value, sw = $("#devSwitch").value, ty = $("#devType").value;
  const noPort = $("#devNoPort").checked, hideVm = $("#devHideVm").checked;
  const rows = S.scan.devices.filter(d => {
    if (vl === "none" ? d.vlan != null : (vl && String(d.vlan) !== vl)) return false;
    if (sw && d.switch_id !== sw) return false;
    if (ty && d.type !== ty) return false;
    if (noPort && d.port_id) return false;
    if (hideVm && d.virtual) return false;
    if (q) {
      const hay = [devName(d), d.dns_name, d.netbios_name, d.ip, ...(d.ips || []), d.mac, d.vendor, d.switch_name, d.port_name, d.port_alias, d.type].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  $("#devCount").textContent = `${rows.length} von ${S.scan.devices.length}`;
  sortableTable($("#devTable"), [
    { key: "hostname", label: "Hostname", render: d => `<b>${esc(devName(d))}</b>${d.virtual ? ' <span class="pill gray">VM</span>' : ""}`, sort: d => devName(d) },
    { key: "ip", label: "IP-Adresse", cls: "mono", render: d => esc(d.ip) + (d.ips.length > 1 ? ` <span class="pill gray" title="${esc(d.ips.join(", "))}">+${d.ips.length - 1}</span>` : ""), sort: d => ipNum(d.ip) },
    { key: "mac", label: "MAC", cls: "mono" },
    { key: "vendor", label: "Hersteller" },
    { key: "type", label: "Typ" },
    { key: "vlan", label: "VLAN", sort: d => d.vlan || 0 },
    { key: "switch_name", label: "Switch", render: d => d.switch_name ? esc(d.switch_name) : '<span class="pill red">keine Zuordnung</span>' },
    { key: "port_name", label: "Port", render: d => `<b>${esc(d.port_name)}</b>`, sort: d => (d.switch_name || "") + d.port_name },
    { key: "port_alias", label: "Port-Beschreibung" },
    { key: "assignment", label: "Zuordnung", render: d => assignPill(d.assignment) },
    { key: "alive", label: "Erreichbar", render: d => d.alive ? '<span class="ok">&#10003;</span>' : '<span class="muted">-</span>', sort: d => d.alive ? 1 : 0 },
  ], rows, { onClick: d => showDevice(d.id), sortKey: "ip" });
}
function assignPill(a) {
  if (!a || a === "keine") return '<span class="pill red">keine</span>';
  if (a.startsWith("sicher")) return `<span class="pill green">${esc(a)}</span>`;
  return `<span class="pill yellow">${esc(a)}</span>`;
}
function showDevice(id) {
  const d = S.dev[id]; if (!d) return;
  const port = d.port_id && S.sw[d.switch_id] ? S.sw[d.switch_id].ports.find(p => p.id === d.port_id) : null;
  showModal(`<h2>${esc(devName(d) || d.ip || d.mac)}</h2>
    <dl class="kv">
      <dt>IP-Adresse(n)</dt><dd class="mono">${esc((d.ips || []).join(", ") || "-")}</dd>
      <dt>MAC</dt><dd class="mono">${esc(d.mac || "-")}</dd>
      <dt>Hersteller</dt><dd>${esc(d.vendor || "-")}</dd>
      <dt>Typ</dt><dd>${esc(d.type)}${d.virtual ? " (virtuell)" : ""}</dd>
      <dt>DNS-Name</dt><dd>${esc(d.dns_name || "-")}</dd>
      <dt>NetBIOS</dt><dd>${esc(d.netbios_name || "-")}${d.netbios_domain ? " / " + esc(d.netbios_domain) : ""}</dd>
      ${d.lldp_name ? `<dt>LLDP/CDP-Name</dt><dd>${esc(d.lldp_name)}<br><span class="muted small">${esc(d.lldp_descr || "")}</span></dd>` : ""}
      <dt>VLAN / Netz</dt><dd>${esc(d.vlan ?? "-")} / ${esc(d.subnet || "-")}</dd>
      <dt>Switch / Port</dt><dd><b>${esc(d.switch_name || "-")} ${esc(d.port_name || "")}</b> ${esc(d.port_alias ? "(" + d.port_alias + ")" : "")}</dd>
      ${port && port.lag_members && port.lag_members.length ? `<dt>LAG-Ports</dt><dd>${esc(port.lag_members.join(", "))}</dd>` : ""}
      <dt>Zuordnung</dt><dd>${assignPill(d.assignment)}</dd>
      <dt>Erreichbar</dt><dd>${d.alive ? "ja" : "nein / nicht geprueft"} ${d.os_guess ? "(" + esc(d.os_guess) + ", TTL " + d.ttl + ")" : ""}</dd>
      ${d.open_ports && d.open_ports.length ? `<dt>Offene Ports</dt><dd>${esc(d.open_ports.join(", "))}</dd>` : ""}
      <dt>Gefunden ueber</dt><dd>${esc((d.sources || []).join(", "))}</dd>
      ${(d.notes || []).length ? `<dt>Hinweise</dt><dd class="warn">${esc(d.notes.join("; "))}</dd>` : ""}
    </dl>
    ${port ? `<p><a href="#" onclick="hideModal();gotoPort('${esc(d.switch_id)}','${esc(d.port_id)}');return false">&#8594; Port in der Frontansicht zeigen</a></p>` : ""}`);
}
function gotoPort(swId, portId) {
  $("#swFilter").value = swId; $("#swSearch").value = "";
  renderSwitches(); showTab("switches");
  const el = $(`#switchList .port[data-p="${CSS.escape(portId)}"]`);
  showPort(swId, portId, el);
}
["#devSearch"].forEach(s => $(s).oninput = debounce(renderDevices, 200));
["#devVlan", "#devSwitch", "#devType", "#devNoPort", "#devHideVm"].forEach(s => $(s).onchange = renderDevices);

// ------------------------------------------------------------------ VLANs
function renderVlans() {
  sortableTable($("#vlanTable"), [
    { key: "id", label: "VLAN", render: v => `<span class="st" style="background:${vlanColor(v.id)};border-color:${vlanColor(v.id)}"></span><b>${v.id}</b>`, sort: v => v.id },
    { key: "name", label: "Name" },
    { key: "subnets", label: "Subnetz(e)", cls: "mono", render: v => esc(v.subnets.join(", ")) },
    { key: "device_count", label: "Geraete", cls: "right" },
    { key: "port_count", label: "Access-Ports", cls: "right" },
    { key: "switches", label: "Switches", render: v => `<span class="small">${esc(v.switches.join(", "))}</span>` },
  ], S.scan.vlans, { onClick: showVlan });
  sortableTable($("#netTable"), [
    { key: "network", label: "Netz", cls: "mono", sort: n => ipNum(n.network.split("/")[0]) },
    { key: "vlan", label: "VLAN" },
    { key: "gateways", label: "Gateway", render: n => esc(n.gateways.map(g => `${g.ip} (${g.device} ${g.interface})`).join(", ")) },
    { key: "sources", label: "Quelle", render: n => `<span class="small">${esc(n.sources.join(", "))}</span>` },
  ], S.scan.networks);
}
function showVlan(v) {
  const devs = S.scan.devices.filter(d => d.vlan === v.id);
  const box = $("#vlanDetail");
  box.style.display = "";
  box.innerHTML = `<div class="card-head"><h3>VLAN ${v.id} ${esc(v.name)}</h3><span class="muted">${devs.length} Geraete</span>
    <div style="flex:1"></div><button class="sm" onclick="$('#vlanDetail').style.display='none'">Schliessen</button></div>
    <div class="tablewrap"><table class="data" id="vlanDevs"></table></div>`;
  sortableTable($("#vlanDevs"), [
    { key: "hostname", label: "Hostname", render: d => `<b>${esc(devName(d))}</b>`, sort: d => devName(d) },
    { key: "ip", label: "IP", cls: "mono", sort: d => ipNum(d.ip) },
    { key: "mac", label: "MAC", cls: "mono" },
    { key: "switch_name", label: "Switch" },
    { key: "port_name", label: "Port" },
    { key: "type", label: "Typ" },
  ], devs, { onClick: d => showDevice(d.id), sortKey: "ip" });
  box.scrollIntoView({ behavior: "smooth" });
}

// ------------------------------------------------------------------ Topologie
function renderTopology() {
  if (!S.scan || !window.vis) return;
  const showDev = $("#topoDevices").checked, showVm = $("#topoVirtual").checked, vlan = $("#topoVlan").value;
  const dark = isDark();
  const fg = dark ? "#e6e9ef" : "#1d2433";
  const nodes = [], edges = [];
  const swIds = new Set();
  S.scan.switches.forEach(s => {
    swIds.add(s.id);
    const devCount = s.ports.reduce((a, p) => a + (p.is_lag ? 0 : p.device_ids.length), 0);
    nodes.push({ id: s.id, label: `${s.name}\n${s.ip}`, shape: "box", group: "switch", font: { color: "#fff", face: "Segoe UI", size: 14, multi: false },
      color: { background: s.is_router ? "#14376e" : "#1f4e9c", border: "#0d2550", highlight: { background: "#2f6fd6", border: "#0d2550" } },
      margin: 10, title: `${s.name}\n${s.ip}\n${s.model || ""}\n${devCount} Geraete`, level: 0 });
  });
  const linkSeen = new Set();
  S.scan.links.forEach(l => {
    const k = [l.a, l.b].sort().join("~") + l.a_port;
    if (linkSeen.has(k)) return; linkSeen.add(k);
    edges.push({ from: l.a, to: l.b, label: `${l.a_port} - ${l.b_port}`, width: 3, color: { color: l.source.includes("vermutet") ? "#d4a017" : "#2f6fd6" },
      dashes: l.source.includes("vermutet"), font: { size: 10, color: fg, strokeWidth: 3, strokeColor: dark ? "#171e27" : "#fff", align: "middle" }, title: l.source });
  });
  // Hierarchie-Ebenen ueber Breitensuche ab dem Switch mit den meisten Links
  const adj = {}; S.scan.links.forEach(l => { (adj[l.a] = adj[l.a] || []).push(l.b); (adj[l.b] = adj[l.b] || []).push(l.a); });
  const root = S.scan.switches.slice().sort((a, b) => (adj[b.id] || []).length - (adj[a.id] || []).length)[0];
  const level = {};
  if (root) { const q = [root.id]; level[root.id] = 0; while (q.length) { const x = q.shift(); (adj[x] || []).forEach(y => { if (level[y] == null) { level[y] = level[x] + 1; q.push(y); } }); } }
  const maxLvl = Math.max(0, ...Object.values(level));
  nodes.forEach(n => n.level = level[n.id] ?? maxLvl + 1);
  // Nachbarn (LLDP) und Endgeraete
  let devShown = 0;
  S.scan.switches.forEach(s => s.ports.forEach(p => {
    const swLvl = level[s.id] ?? maxLvl + 1;
    p.device_ids.forEach(id => {
      const d = S.dev[id]; if (!d || d.port_id !== p.id) return;
      const isNeighbor = (d.sources || []).some(x => x === "LLDP" || x === "CDP") && !d.virtual;
      if (!showDev && !isNeighbor) return;
      if (!showVm && d.virtual) return;
      if (vlan && String(d.vlan) !== vlan) return;
      devShown++;
      const col = vlanColor(d.vlan);
      nodes.push({ id: "d:" + d.id, label: `${devName(d) || d.mac}\n${d.ip || ""}`, shape: isNeighbor ? "diamond" : "dot", size: isNeighbor ? 12 : 8,
        color: { background: col, border: col }, font: { size: 11, color: fg }, level: swLvl + 1,
        title: `${devName(d)}\n${d.ip}\n${d.mac}\n${d.vendor}\nVLAN ${d.vlan ?? "-"}\n${s.name} ${p.name}` });
      edges.push({ from: s.id, to: "d:" + d.id, label: p.name, width: 1, color: { color: dark ? "#3a4555" : "#c3cad5" }, font: { size: 9, color: dark ? "#98a2b3" : "#667085", strokeWidth: 0 } });
    });
  }));
  $("#topoInfo").textContent = `${S.scan.switches.length} Switches, ${S.scan.links.length} Verbindungen, ${devShown} Geraete angezeigt`;
  const hier = $("#topoLayout").value === "hier";
  const options = {
    layout: hier ? { hierarchical: { direction: "UD", sortMethod: "directed", levelSeparation: 150, nodeSpacing: 110, treeSpacing: 160 } } : { improvedLayout: nodes.length < 300 },
    physics: hier ? { enabled: false } : { solver: "forceAtlas2Based", stabilization: { iterations: 250 }, forceAtlas2Based: { gravitationalConstant: -60, springLength: 90 } },
    interaction: { hover: true, tooltipDelay: 150, navigationButtons: false, keyboard: true },
    edges: { smooth: hier ? { type: "cubicBezier", forceDirection: "vertical", roundness: .4 } : { type: "continuous" } },
  };
  if (S.topo) S.topo.destroy();
  S.topo = new vis.Network($("#topo"), { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) }, options);
  S.topo.on("click", (e) => {
    if (!e.nodes.length) return;
    const id = e.nodes[0];
    if (S.sw[id]) {
      const s = S.sw[id];
      $("#topoSide").innerHTML = `<h3>${esc(s.name)}</h3><dl class="kv"><dt>IP</dt><dd class="mono">${esc(s.ip)}</dd><dt>Modell</dt><dd>${esc(s.model || "-")}</dd>
        <dt>Standort</dt><dd>${esc(s.location || "-")}</dd><dt>Ports</dt><dd>${statusBar(s.ports.filter(p => !p.is_lag))}</dd></dl>
        <p><a href="#" onclick="$('#swFilter').value='${esc(s.id)}';renderSwitches();showTab('switches');return false">&#8594; Frontansicht oeffnen</a></p>
        <h3>Verbindungen</h3><ul class="small">${S.scan.links.filter(l => l.a === id || l.b === id).map(l => {
          const me = l.a === id ? l.a_port : l.b_port, other = l.a === id ? l.b : l.a, op = l.a === id ? l.b_port : l.a_port;
          return `<li><b>${esc(me)}</b> &#8594; ${esc((S.sw[other] || {}).name || other)} ${esc(op)} <span class="muted">(${esc(l.source)})</span></li>`;
        }).join("") || "<li class='muted'>keine</li>"}</ul>`;
    } else if (id.startsWith("d:")) {
      const d = S.dev[id.slice(2)];
      $("#topoSide").innerHTML = `<h3>${esc(devName(d) || d.mac)}</h3><dl class="kv"><dt>IP</dt><dd class="mono">${esc(d.ips.join(", "))}</dd><dt>MAC</dt><dd class="mono">${esc(d.mac)}</dd>
        <dt>Hersteller</dt><dd>${esc(d.vendor)}</dd><dt>VLAN</dt><dd>${esc(d.vlan ?? "-")}</dd><dt>Port</dt><dd><b>${esc(d.switch_name)} ${esc(d.port_name)}</b></dd></dl>
        <p><a href="#" onclick="showDevice('${esc(d.id)}');return false">Details</a></p>`;
    }
  });
}
["#topoDevices", "#topoVirtual", "#topoVlan", "#topoLayout"].forEach(s => $(s).onchange = renderTopology);
$("#topoFit").onclick = () => S.topo && S.topo.fit({ animation: true });
$("#topoSearch").onkeydown = (e) => {
  if (e.key !== "Enter" || !S.topo) return;
  const q = e.target.value.trim().toLowerCase(); if (!q) return;
  const sw = S.scan.switches.find(s => (s.name + " " + s.ip).toLowerCase().includes(q));
  let id = sw && sw.id;
  if (!id) {
    const d = S.scan.devices.find(d => [devName(d), d.ip, d.mac, ...(d.ips || [])].join(" ").toLowerCase().includes(q));
    if (d) {
      if (!S.topo.body.data.nodes.get("d:" + d.id)) { $("#topoDevices").checked = true; if (d.virtual) $("#topoVirtual").checked = true; $("#topoVlan").value = ""; renderTopology(); }
      id = "d:" + d.id;
    }
  }
  if (id && S.topo.body.data.nodes.get(id)) { S.topo.selectNodes([id]); S.topo.focus(id, { scale: 1.2, animation: true }); S.topo.emit("click", { nodes: [id] }); }
  else toast("Nicht gefunden");
};

// ------------------------------------------------------------------ Umzugsplanung
function planRows() {
  const sw = $("#planSwitch").value, all = $("#planAll").checked;
  const rows = [];
  S.scan.switches.filter(s => !sw || s.id === sw).forEach(s => s.ports.filter(p => !p.is_lag && (all || PATCH.includes(p.status))).forEach(p => {
    const d = S.dev[p.device_ids[0]] || {};
    rows.push({ key: planKey(s.name, p.name), sw: s.name, port: p.name, status: p.status, alias: p.alias, vlans: p.vlans, lag: p.lag,
      dev: devName(d) || p.uplink_name || ((p.neighbors || [])[0] || {}).name || "", ip: d.ip || "", more: Math.max(0, p.device_ids.length - 1) });
  }));
  return rows;
}
function renderPlan() {
  const rows = planRows();
  const inp = (r, f, w) => `<input type="text" data-key="${esc(r.key)}" data-f="${f}" value="${esc((S.plan[r.key] || {})[f] || "")}" style="width:${w}px">`;
  sortableTable($("#planTable"), [
    { key: "sw", label: "Switch" },
    { key: "port", label: "Port", render: r => `${stDot(r.status)}<b>${esc(r.port)}</b>${r.lag ? ` <span class="pill">${esc(r.lag)}</span>` : ""}` },
    { key: "alias", label: "Beschreibung", render: r => `<span class="small">${esc(r.alias)}</span>` },
    { key: "vlans", label: "VLAN" },
    { key: "dev", label: "Geraet", render: r => `<b>${esc(r.dev)}</b>${r.more ? ` <span class="pill gray">+${r.more}</span>` : ""}${r.status === "aktiv-ohne-geraet" ? ' <span class="pill yellow">Link ohne Geraet</span>' : ""}${r.status === "down-beschriftet" ? ' <span class="pill yellow">down</span>' : ""}` },
    { key: "ip", label: "IP", cls: "mono", sort: r => ipNum(r.ip) },
    { key: "t1", label: "Ziel-Switch", render: r => inp(r, "target_switch", 130), sort: r => (S.plan[r.key] || {}).target_switch || "" },
    { key: "t2", label: "Ziel-Port", render: r => inp(r, "target_port", 80), sort: r => (S.plan[r.key] || {}).target_port || "" },
    { key: "t3", label: "Kabel-Label", render: r => inp(r, "label", 100) },
    { key: "t4", label: "Bemerkung", render: r => inp(r, "note", 160) },
    { key: "done", label: "Erledigt", render: r => `<input type="checkbox" data-key="${esc(r.key)}" data-f="done" ${(S.plan[r.key] || {}).done ? "checked" : ""}>`, sort: r => (S.plan[r.key] || {}).done ? 1 : 0 },
  ], rows, { limit: 5000 });
  $$("#planTable input[data-key]").forEach(el => el.onchange = () => savePlan(el.dataset.key, el.dataset.f, el.type === "checkbox" ? el.checked : el.value));
  const done = rows.filter(r => (S.plan[r.key] || {}).done).length;
  $("#planProgress").textContent = `${done} von ${rows.length} Ports erledigt`;
  $("#planBar").style.width = (rows.length ? 100 * done / rows.length : 0) + "%";
}
async function savePlan(key, field, value) {
  try {
    S.plan[key] = await api("/api/plan", { method: "POST", body: { key, values: { [field]: value } } });
    if (field === "done") {
      const rows = planRows(); const done = rows.filter(r => (S.plan[r.key] || {}).done).length;
      $("#planProgress").textContent = `${done} von ${rows.length} Ports erledigt`;
      $("#planBar").style.width = (rows.length ? 100 * done / rows.length : 0) + "%";
    }
  } catch (e) { toast("Speichern fehlgeschlagen: " + e.message); }
}
$("#planSwitch").onchange = renderPlan;
$("#planAll").onchange = renderPlan;
$("#planBulk1").onclick = async () => {
  const v = $("#planBulkSwitch").value.trim(); if (!v) { toast("Ziel-Switch eingeben"); return; }
  const rows = planRows(); if (!confirm(`Ziel-Switch "${v}" fuer ${rows.length} Ports setzen?`)) return;
  for (const r of rows) S.plan[r.key] = await api("/api/plan", { method: "POST", body: { key: r.key, values: { target_switch: v } } });
  renderPlan(); toast("Gespeichert");
};
$("#planBulk2").onclick = async () => {
  const rows = planRows().filter(r => !(S.plan[r.key] || {}).target_port);
  if (!confirm(`Ziel-Port = Quell-Port fuer ${rows.length} Ports uebernehmen?`)) return;
  for (const r of rows) S.plan[r.key] = await api("/api/plan", { method: "POST", body: { key: r.key, values: { target_port: r.port } } });
  renderPlan(); toast("Gespeichert");
};

// ------------------------------------------------------------------ Vergleich
const CMP_LABEL = { fehlt: ["Fehlt nach Umzug", "red"], abweichend: ["Falscher Port", "red"], verschoben: ["Port geaendert", "yellow"],
  geaendert: ["IP/VLAN geaendert", "yellow"], neu: ["Neu", "gray"], korrekt: ["Korrekt gesteckt", "green"], unveraendert: ["Unveraendert", "gray"] };
$("#cmpBtn").onclick = async () => {
  const a = $("#cmpA").value, b = $("#cmpB").value;
  if (!a || !b || a === b) { toast("Bitte zwei verschiedene Scans waehlen"); return; }
  S.cmp = await api(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  $("#cmpFilter").innerHTML = `<option value="">Alle Status</option>` + Object.keys(S.cmp.summary).map(k => `<option value="${k}">${CMP_LABEL[k][0]} (${S.cmp.summary[k]})</option>`).join("");
  $("#cmpSummary").innerHTML = Object.entries(S.cmp.summary).map(([k, v]) => `<span class="pill ${CMP_LABEL[k][1]}" style="font-size:13px;padding:4px 12px">${CMP_LABEL[k][0]}: ${v}</span>`).join("");
  renderCompare();
};
function renderCompare() {
  if (!S.cmp) return;
  const f = $("#cmpFilter").value, hv = $("#cmpHideVm").checked;
  const rows = S.cmp.rows.filter(r => (!f || r.status === f) && (!hv || !r.virtual));
  sortableTable($("#cmpTable"), [
    { key: "status", label: "Status", render: r => `<span class="pill ${CMP_LABEL[r.status][1]}">${CMP_LABEL[r.status][0]}</span>` },
    { key: "hostname", label: "Hostname", render: r => `<b>${esc(r.hostname)}</b>` },
    { key: "mac", label: "MAC", cls: "mono" },
    { key: "ip_old", label: "IP vorher", cls: "mono", sort: r => ipNum(r.ip_old) },
    { key: "ip_new", label: "IP nachher", cls: "mono", sort: r => ipNum(r.ip_new) },
    { key: "loc_old", label: "Port vorher" },
    { key: "expected", label: "Soll (Plan)" },
    { key: "loc_new", label: "Port nachher", render: r => `<b>${esc(r.loc_new)}</b>` },
    { key: "vlan_old", label: "VLAN", render: r => r.vlan_old === r.vlan_new ? esc(r.vlan_old ?? "") : `${esc(r.vlan_old ?? "-")} &#8594; ${esc(r.vlan_new ?? "-")}` },
  ], rows);
}
$("#cmpFilter").onchange = renderCompare;
$("#cmpHideVm").onchange = renderCompare;

// ------------------------------------------------------------------ Scan & Einstellungen
const OPTS = [
  ["lldp_cdp_crawl", "bool", "Weitere Switches automatisch ueber LLDP/CDP finden"],
  ["auto_subnets", "bool", "Subnetze der Router/L3-Switches automatisch scannen"],
  ["auto_subnet_min_prefix", "num", "... nur Netze ab Praefix /n (kleiner = groesser)"],
  ["ping_sweep", "bool", "Ping-Sweep der Netze"],
  ["tcp_fallback", "bool", "TCP-Pruefung fuer Hosts ohne Ping-Antwort (Firewall)"],
  ["use_nmap", "bool", "nmap verwenden, falls installiert (schneller)"],
  ["dns_lookup", "bool", "Hostnamen per DNS (Reverse-Lookup)"],
  ["netbios_lookup", "bool", "Hostnamen per NetBIOS (Windows)"],
  ["snmp_probe_hosts", "bool", "Alle gefundenen Hosts auf SNMP pruefen (findet vergessene Switches, langsamer)"],
  ["port_scan", "bool", "Offene Standard-Ports ermitteln (langsamer)"],
  ["ping_timeout_ms", "num", "Ping-Timeout (ms)"],
  ["workers", "num", "Parallele Abfragen"],
  ["snmp_timeout", "num", "SNMP-Timeout (s)"],
  ["snmp_retries", "num", "SNMP-Wiederholungen"],
  ["uplink_mac_threshold", "num", "MAC-Anzahl, ab der ein Port als 'mehrere MACs' gilt"],
];
async function loadScanTab() {
  if (!S.cfg) {
    S.cfg = await api("/api/config");
    renderCfg();
    api("/api/local-networks").then(r => {
      S.localNets = r.networks;
      $("#localNets").textContent = r.networks.length ? "(" + r.networks.join(", ") + ")" : "";
      $("#dataDir").textContent = `Datenverzeichnis: ${r.data_dir}  |  nmap: ${r.nmap ? "gefunden" : "nicht installiert (Ping-Sweep wird verwendet)"}`;
    });
  }
  renderScanTable();
  pollStatus();
}
function renderCfg() {
  const c = S.cfg;
  $("#cfgSnmp").value = (c.snmp_devices || []).join("\n");
  $("#cfgSubnets").value = (c.subnets || []).join("\n");
  $("#cfgExclude").value = (c.exclude || []).join("\n");
  $("#creds").innerHTML = (c.credentials || []).map((cr, i) => credRow(cr, i)).join("");
  $$("#creds .del").forEach(b => b.onclick = () => { readCfg(); S.cfg.credentials.splice(+b.dataset.i, 1); renderCfg(); });
  $("#vlanDefs").innerHTML = (c.vlans || []).map((v, i) => `<div class="vlanrow" data-i="${i}">
      <input type="number" class="vid" value="${esc(v.id)}" placeholder="ID" min="1" max="4094"><input type="text" class="vname" value="${esc(v.name || "")}" placeholder="Name">
      <input type="text" class="vsub" value="${esc(v.subnet || "")}" placeholder="Subnetz (10.0.10.0/24)"><button class="sm danger vdel" data-i="${i}">&#10005;</button></div>`).join("");
  $$("#vlanDefs .vdel").forEach(b => b.onclick = () => { readCfg(); S.cfg.vlans.splice(+b.dataset.i, 1); renderCfg(); });
  $("#opts").innerHTML = OPTS.map(([k, t, l]) => t === "bool"
    ? `<label class="chk"><input type="checkbox" data-opt="${k}" ${c.options[k] ? "checked" : ""}> ${esc(l)}</label>`
    : `<label class="chk" style="align-items:center"><input type="number" data-opt="${k}" value="${esc(c.options[k])}" style="width:80px" step="any"> ${esc(l)}</label>`).join("");
}
function credRow(cr, i) {
  const v3 = String(cr.version) === "3";
  const sel = (cls, opts, val) => `<select class="${cls}">${opts.map(o => `<option ${String(o) === String(val) ? "selected" : ""}>${o}</option>`).join("")}</select>`;
  return `<div class="cred" data-i="${i}">
    <input type="text" class="cname" value="${esc(cr.name || "")}" placeholder="Name">
    ${sel("cver", ["1", "2c", "3"], cr.version || "2c")}
    <input type="${v3 ? "text" : "password"}" class="cuser" value="${esc(v3 ? cr.user || "" : cr.community || "")}" placeholder="${v3 ? "Benutzer" : "Community"}">
    <input type="password" class="cauth" value="${esc(cr.auth_key || "")}" placeholder="Auth-Passwort" ${v3 ? "" : "disabled"}>
    ${sel("cauthp", ["sha", "sha256", "sha384", "sha512", "sha224", "md5"], cr.auth_protocol || "sha")}
    <input type="password" class="cpriv" value="${esc(cr.priv_key || "")}" placeholder="Priv-Passwort" ${v3 ? "" : "disabled"}>
    ${sel("cprivp", ["aes", "aes192", "aes256", "des", "3des"], cr.priv_protocol || "aes")}
    <button class="sm danger del" data-i="${i}" title="Entfernen">&#10005;</button></div>`;
}
function readCfg() {
  const c = S.cfg;
  const lines = s => $(s).value.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
  c.snmp_devices = lines("#cfgSnmp"); c.subnets = lines("#cfgSubnets"); c.exclude = lines("#cfgExclude");
  c.credentials = $$("#creds .cred").map(r => {
    const ver = $(".cver", r).value;
    const o = { name: $(".cname", r).value.trim() || ("SNMP " + ver), version: ver };
    if (ver === "3") Object.assign(o, { user: $(".cuser", r).value, auth_key: $(".cauth", r).value, auth_protocol: $(".cauthp", r).value, priv_key: $(".cpriv", r).value, priv_protocol: $(".cprivp", r).value });
    else o.community = $(".cuser", r).value;
    return o;
  });
  c.vlans = $$("#vlanDefs .vlanrow").map(r => ({ id: parseInt($(".vid", r).value, 10), name: $(".vname", r).value.trim(), subnet: $(".vsub", r).value.trim() })).filter(v => v.id);
  $$("#opts [data-opt]").forEach(el => c.options[el.dataset.opt] = el.type === "checkbox" ? el.checked : Number(el.value));
  return c;
}
$("#creds").addEventListener("change", e => { if (e.target.classList.contains("cver")) { readCfg(); renderCfg(); } });
$("#addV2").onclick = () => { readCfg(); S.cfg.credentials.push({ name: "v2c " + (S.cfg.credentials.length + 1), version: "2c", community: "" }); renderCfg(); };
$("#addV3").onclick = () => { readCfg(); S.cfg.credentials.push({ name: "v3 " + (S.cfg.credentials.length + 1), version: "3", user: "", auth_protocol: "sha", priv_protocol: "aes" }); renderCfg(); };
$("#addVlan").onclick = () => { readCfg(); S.cfg.vlans.push({ id: "", name: "", subnet: "" }); renderCfg(); };
$("#addLocal").onclick = (e) => { e.preventDefault(); const cur = $("#cfgSubnets").value.trim(); const add = (S.localNets || []).filter(n => !cur.includes(n)); $("#cfgSubnets").value = (cur ? cur + "\n" : "") + add.join("\n"); };
async function saveCfg() {
  S.cfg = await api("/api/config", { method: "POST", body: readCfg() });
  renderCfg();
}
$("#saveCfg").onclick = async () => { try { await saveCfg(); toast("Einstellungen gespeichert"); } catch (e) { toast("Fehler: " + e.message, 6000); } };
$("#testBtn").onclick = async () => {
  const host = $("#testHost").value.trim(); if (!host) return;
  $("#testRes").textContent = "teste ...";
  try {
    await saveCfg();
    const r = await api("/api/test-snmp", { method: "POST", body: { host } });
    $("#testRes").innerHTML = r.ok ? `<span class="ok">&#10003; ${esc(r.sys_name)} (${esc(r.credential)})</span> <span class="muted">${esc(r.sys_descr.slice(0, 80))}</span>` : `<span class="danger">${esc(r.message)}</span>`;
  } catch (e) { $("#testRes").innerHTML = `<span class="danger">${esc(e.message)}</span>`; }
};
$("#startBtn").onclick = async () => {
  try {
    await saveCfg();
    if (!S.cfg.snmp_devices.length && !confirm("Es sind keine Switches (SNMP) eingetragen. Ohne Switch-Daten koennen Geraete keinem Port zugeordnet werden. Trotzdem nur Ping-Scan starten?")) return;
    $("#scanLog").textContent = ""; S.logPos = 0;
    await api("/api/scan/start", { method: "POST", body: { name: $("#scanName").value.trim() } });
    toast("Scan gestartet");
    pollStatus();
  } catch (e) { toast("Fehler: " + e.message, 6000); }
};
$("#cancelBtn").onclick = () => api("/api/scan/cancel", { method: "POST" });
async function pollStatus() {
  clearTimeout(S.poll);
  let st;
  try { st = await api("/api/scan/status?from=" + S.logPos); } catch (e) { return; }
  const running = st.state === "running";
  $("#startBtn").disabled = running; $("#cancelBtn").style.display = running ? "" : "none";
  if (st.state !== "idle") {
    $("#scanBar").style.width = (st.percent || 0) + "%";
    $("#scanPhase").textContent = { running: "Laeuft: " + (st.phase_label || ""), done: "Fertig", error: "Fehler", cancelled: "Abgebrochen" }[st.state] || st.state;
    $("#scanMsg").textContent = st.message || "";
    if (st.log && st.log.length) { const lg = $("#scanLog"); lg.textContent += st.log.join("\n") + "\n"; lg.scrollTop = lg.scrollHeight; S.logPos = st.log_total; }
  }
  if (running) S.poll = setTimeout(pollStatus, 1000);
  else if (st.state === "done" && S._wasRunning) { toast("Scan abgeschlossen"); await loadScans(st.id); renderScanTable(); }
  S._wasRunning = running;
}
function renderScanTable() {
  sortableTable($("#scanTable"), [
    { key: "name", label: "Name", render: s => `<b>${esc(s.name)}</b>` },
    { key: "finished", label: "Datum", render: s => esc(fmtDate(s.finished || s.started)) },
    { key: "st", label: "Switches / Geraete", render: s => s.stats ? `${s.stats.switches} / ${s.stats.devices}` : "" },
    { key: "act", label: "", render: s => `<button class="sm" data-a="show" data-id="${esc(s.id)}">Anzeigen</button> <button class="sm" data-a="ren" data-id="${esc(s.id)}">Umbenennen</button> <button class="sm danger" data-a="del" data-id="${esc(s.id)}">Loeschen</button>` },
  ], S.scans);
  $$("#scanTable button[data-a]").forEach(b => b.onclick = async () => {
    const id = b.dataset.id;
    if (b.dataset.a === "show") { $("#scanSelect").value = id; await loadScan(id); showTab("overview"); }
    if (b.dataset.a === "ren") { const n = prompt("Neuer Name:"); if (n) { await api(`/api/scans/${encodeURIComponent(id)}/rename`, { method: "POST", body: { name: n } }); await loadScans(); renderScanTable(); } }
    if (b.dataset.a === "del" && confirm("Scan wirklich loeschen?")) { await api("/api/scans/" + encodeURIComponent(id), { method: "DELETE" }); if (S.scan && S.scan.id === id) S.scan = null; await loadScans(); renderScanTable(); }
  });
}
$("#importFile").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/api/scans/import", { method: "POST", body: fd }); await loadScans(r.id); renderScanTable(); toast("Scan importiert"); }
  catch (err) { toast("Import fehlgeschlagen: " + err.message, 6000); }
  e.target.value = "";
};

// ------------------------------------------------------------------ Start
(async function init() {
  await loadScans();
  let t = location.hash.slice(1);
  if (!t) { try { t = localStorage.getItem("ns-tab"); } catch (e) { /* egal */ } }
  if (t && $("#tab-" + t)) showTab(t);
  pollStatus();
})();
