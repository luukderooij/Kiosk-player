/* Kiosk Player — webinterface */
"use strict";

// ---------------------------------------------------------------- helpers
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const enc = encodeURIComponent;

const S = {
  all: null, media: [], mediaByName: {}, disk: null, ffmpeg: true, allowed: [],
  state: null, events: [], vlcLog: "", view: null,
  tzOffsetMin: 0, clockOffset: 0, tc: null,
  queueSel: null, draft: null, dirty: false,
  week: null, timeline: null,
  uploads: [], uploading: false, mediaFilter: "all", mediaSearch: "",
  upd: null, updBranches: null, updCommit: null, updSel: null, updErr: null, updWatch: false,
};

async function api(method, url, body) {
  const opts = { method, headers: { "X-Requested-With": "kiosk" }, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch {
    throw Object.assign(new Error("De kiosk is niet bereikbaar"), { offline: true });
  }
  if (res.status === 401) {
    location.href = "/login";
    throw new Error("Niet ingelogd");
  }
  let data = {};
  try { data = await res.json(); } catch { /* geen JSON */ }
  if (!res.ok) throw Object.assign(new Error(data.error || `Fout ${res.status}`), { status: res.status, data });
  return data;
}

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = msg;
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? 7000 : 3500);
}
const fail = (e) => toast(e.message || String(e), "error");

const ICONS = {
  prev: '<path d="M19 20 9 12l10-8z"/><path d="M5 19V5"/>',
  next: '<path d="m5 4 10 8-10 8z"/><path d="M19 5v14"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  play: '<path d="m6 4 14 8-14 8z"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
  restart: '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
  left: '<path d="m15 18-6-6 6-6"/>',
  right: '<path d="m9 18 6-6-6-6"/>',
  upload: '<path d="M12 16V4M6 10l6-6 6 6"/><path d="M4 20h16"/>',
};
const icon = (n) => `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[n]}</svg>`;

function fmtDur(s) {
  if (s == null || isNaN(s)) return "–";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h}:${pad(m)}:${pad(x)}` : `${m}:${pad(x)}`;
}
function fmtBytes(b) {
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toLocaleString("nl-NL", { maximumFractionDigits: i >= 2 ? 1 : 0 })} ${u[i]}`;
}
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// --------------------------------------------------- datums (als tekst, tijdzone-vast)
const DAY_SHORT = ["ma", "di", "wo", "do", "vr", "za", "zo"];
const DAY_LONG = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"];
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const D = {
  parts: (ds) => ds.split("-").map(Number),
  utc: (ds) => { const [y, m, d] = D.parts(ds); return new Date(Date.UTC(y, m - 1, d)); },
  add: (ds, n) => { const t = D.utc(ds); t.setUTCDate(t.getUTCDate() + n); return t.toISOString().slice(0, 10); },
  dow: (ds) => (D.utc(ds).getUTCDay() + 6) % 7,
  monday: (ds) => D.add(ds, -D.dow(ds)),
  fmt: (ds, o) => new Intl.DateTimeFormat("nl-NL", { ...o, timeZone: "UTC" }).format(D.utc(ds)),
  isoWeek: (ds) => {
    const t = D.utc(ds); t.setUTCDate(t.getUTCDate() + 3 - ((t.getUTCDay() + 6) % 7));
    const y = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
    return 1 + Math.round(((t - y) / 864e5 - 3 + ((y.getUTCDay() + 6) % 7)) / 7);
  },
};
const minOf = (iso) => { const t = iso.slice(11, 16); return +t.slice(0, 2) * 60 + +t.slice(3, 5); };

function serverNow() {
  const t = new Date(Date.now() + S.clockOffset + S.tzOffsetMin * 60000);
  const date = t.toISOString().slice(0, 10);
  return { date, hh: t.getUTCHours(), mm: t.getUTCMinutes(), min: t.getUTCHours() * 60 + t.getUTCMinutes() };
}
function whenLabel(iso) {
  const day = iso.slice(0, 10), time = iso.slice(11, 16), today = serverNow().date;
  if (day === today) return { day: "Vandaag", time };
  if (day === D.add(today, 1)) return { day: "Morgen", time };
  return { day: cap(D.fmt(day, { weekday: "short", day: "numeric", month: "short" })), time };
}
function fmtDays(days) {
  const d = [...days].sort((a, b) => a - b);
  const key = d.join();
  if (d.length === 7) return "Elke dag";
  if (key === "0,1,2,3,4") return "Ma t/m vr";
  if (key === "5,6") return "Za en zo";
  if (d.length >= 3 && d[d.length - 1] - d[0] === d.length - 1) return `${cap(DAY_SHORT[d[0]])} t/m ${DAY_SHORT[d[d.length - 1]]}`;
  return cap(d.map((i) => DAY_SHORT[i]).join(", "));
}
function fmtTimes(r) {
  if (r.start === "00:00" && r.end === "00:00") return "hele dag";
  return `${r.start}–${r.end}${r.end <= r.start ? " (tot de volgende dag)" : ""}`;
}
function fmtPeriod(r) {
  const f = (ds) => D.fmt(ds, { day: "numeric", month: "short", year: "numeric" });
  if (r.date_from && r.date_to) return r.date_from === r.date_to ? `alleen op ${D.fmt(r.date_from, { weekday: "short" })} ${f(r.date_from)}` : `${f(r.date_from)} t/m ${f(r.date_to)}`;
  if (r.date_from) return `vanaf ${f(r.date_from)}`;
  if (r.date_to) return `t/m ${f(r.date_to)}`;
  return "";
}

// ---------------------------------------------------------- wachtrijen
const PALETTE = ["#2347C6", "#0F8A6E", "#B4467A", "#7C4FD0", "#B86E00", "#1F7FA6", "#5E7A1C", "#A2462A"];
const queues = () => (S.all ? S.all.queues : []);
const queueById = (id) => queues().find((q) => q.id === id);
function qColor(id) {
  const i = queues().findIndex((q) => q.id === id);
  return i < 0 ? "#7C8794" : PALETTE[i % PALETTE.length];
}
function queueDuration(q) {
  let total = 0, unknown = false;
  const def = S.all?.settings?.default_image_duration || 10;
  for (const it of q.items) {
    const m = S.mediaByName[it.file];
    if (!m) { unknown = true; continue; }
    if (m.kind === "image") total += it.duration || def;
    else if (m.duration) total += m.duration;
    else unknown = true;
  }
  return { total, unknown };
}
function queueSummary(q) {
  const { total, unknown } = queueDuration(q);
  const parts = [plural(q.items.length, "item", "items")];
  if (q.items.length) parts.push(`${unknown ? "ca. " : ""}${fmtDur(total)}`);
  if (q.loop === false) parts.push("één keer");
  return parts.join(", ");
}
const qChip = (id) => {
  const q = queueById(id);
  if (!q) return `<span class="chip"><span class="label">Niets (scherm leeg)</span></span>`;
  return `<span class="chip"><span class="dot" style="background:${qColor(id)}"></span><span class="label">${esc(q.name)}</span></span>`;
};
function thumbUrl(name) {
  const m = S.mediaByName[name];
  if (!m) return null;
  if (m.thumb) return `/thumb/${enc(name)}?v=${m.mtime}`;
  if (m.kind === "image") return `/media/${enc(name)}?v=${m.mtime}`;
  return null;
}
const thumbHtml = (name, label) => {
  const url = thumbUrl(name);
  const m = S.mediaByName[name];
  return `<div class="thumb">${url ? `<img src="${url}" alt="" loading="lazy">` : `<span class="ph">${m?.probing ? "Analyseren…" : "Geen voorbeeld"}</span>`}${label ? `<span class="kind">${label}</span>` : ""}</div>`;
};

// ---------------------------------------------------------- dialogen
function openDialog({ title, body, foot = "", wide = false, onClick, onOpen, onClose }) {
  const d = document.createElement("dialog");
  if (wide) d.className = "wide";
  d.innerHTML = `<div class="dlg-head"><h2>${esc(title)}</h2><button class="btn ghost icon small" type="button" data-close aria-label="Sluiten">${icon("x")}</button></div>
    <div class="dlg-body">${body}</div>${foot ? `<div class="dlg-foot">${foot}</div>` : ""}`;
  document.body.append(d);
  d.addEventListener("click", (e) => {
    if (e.target === d || e.target.closest("[data-close]")) { d.close(); return; }
    onClick && onClick(e, d);
  });
  d.addEventListener("close", () => { onClose && onClose(d); d.remove(); });
  d.showModal();
  onOpen && onOpen(d);
  return d;
}
function confirmBox({ title, text, ok = "Verwijderen", danger = true }) {
  return new Promise((resolve) => {
    let answer = false;
    openDialog({
      title, body: `<p>${text}</p>`,
      foot: `<button class="btn" type="button" data-close>Annuleren</button><button class="btn ${danger ? "danger solid" : "primary"}" type="button" data-ok>${esc(ok)}</button>`,
      onClick: (e, d) => { if (e.target.closest("[data-ok]")) { answer = true; d.close(); } },
      onClose: () => resolve(answer),
    });
  });
}

// ---------------------------------------------------------- data laden
async function loadAll() { S.all = await api("GET", "/api/all"); }
async function loadMedia() {
  const r = await api("GET", "/api/media");
  S.media = r.media;
  S.disk = r.disk;
  S.ffmpeg = r.ffmpeg;
  S.allowed = r.allowed;
  S.mediaByName = Object.fromEntries(r.media.map((m) => [m.name, m]));
}
async function loadState() {
  try {
    const st = await api("GET", "/api/state");
    S.state = st;
    const m = st.now.match(/([+-])(\d\d):(\d\d)$/);
    S.tzOffsetMin = m ? (m[1] === "-" ? -1 : 1) * (+m[2] * 60 + +m[3]) : 0;
    S.clockOffset = Date.parse(st.now) - Date.now();
    const v = st.vlc;
    S.tc = v && v.length != null ? { time: v.time || 0, length: v.length || 0, at: Date.now(), playing: v.state === "playing" } : null;
    renderTop();
    if (S.view === "nu") updateNu();
  } catch (e) {
    if (e.offline) {
      $("#topStatus").innerHTML = `<span class="tally error"></span><b>Kiosk niet bereikbaar</b>`;
    }
  }
}
async function loadEvents() {
  try {
    const r = await api("GET", "/api/events");
    S.events = r.events;
    S.vlcLog = r.vlc_log;
    if (S.view === "nu") renderLog();
  } catch { /* volgende keer */ }
}

// ---------------------------------------------------------- bovenbalk
function nowMode(st) {
  if (!st) return "off";
  if (!st.running) return st.error ? "error" : "off";
  if (st.source === "idle") return "off";
  return st.vlc && st.vlc.state === "paused" ? "paused" : "live";
}
function renderTop() {
  const st = S.state;
  if (!st) return;
  const mode = nowMode(st);
  const text = {
    live: `Op het scherm: <b>${esc(st.queue_name)}</b>`,
    paused: `Gepauzeerd: <b>${esc(st.queue_name)}</b>`,
    error: `<b>Storing</b>`,
    off: st.source === "idle" ? `<b>Zwart scherm</b>` : `<b>Niets op het scherm</b>`,
  }[mode];
  $("#topStatus").innerHTML = `<span class="tally ${mode}"></span><span>${text}</span>`;
}
function tickClock() {
  if (!S.state) return;
  const n = serverNow();
  $("#clock").textContent = `${pad(n.hh)}:${pad(n.mm)}`;
}

// ================================================================== NU
function renderNu() {
  view.innerHTML = `
  <div class="now-grid">
    <section aria-label="Het scherm">
      <div class="monitor">
        <div class="screen" id="scr">
          <img id="scrImg" alt="" hidden>
          <div class="off" id="scrOff"></div>
          <div class="badge"><span class="tally" id="scrTally"></span><span id="scrBadge"></span></div>
        </div>
        <div class="monitor-foot">
          <div class="timecode" id="tc" aria-label="Afspeelpositie"></div>
          <div class="scrub" id="scrub"><div></div></div>
        </div>
      </div>
      <div class="now-info">
        <h1 class="now-title" id="nowTitle"></h1>
        <p class="now-meta" id="nowMeta"></p>
        <div class="transport">
          <button class="btn" type="button" data-act="prev" title="Vorige">${icon("prev")}<span>Vorige</span></button>
          <button class="btn" type="button" data-act="pause" id="btnPause"></button>
          <button class="btn" type="button" data-act="next" title="Volgende">${icon("next")}<span>Volgende</span></button>
          <button class="btn danger" type="button" data-act="stop">${icon("stop")}<span>Stop</span></button>
          <button class="btn ghost" type="button" data-act="restart" title="VLC opnieuw starten">${icon("restart")}<span>Herstart VLC</span></button>
        </div>
        <div id="banners"></div>
      </div>
    </section>
    <aside class="stack">
      <section class="panel"><h2>Wachtrij starten</h2><ul class="qlist" id="quick"></ul></section>
      <section class="panel"><h2>Komende wissels</h2><ul class="changes" id="changes"></ul></section>
    </aside>
  </div>
  <section class="panel" style="margin-top:24px">
    <h2>Logboek</h2>
    <ul class="log" id="log"></ul>
    <details class="tech"><summary>Technische details</summary><div id="tech"></div></details>
  </section>`;
  updateNu();
  renderLog();
  loadEvents();
}

function sourceText(st) {
  const next = st.next_changes?.[0];
  const until = next ? ` tot ${whenLabel(next.at).day === "Vandaag" ? "" : whenLabel(next.at).day.toLowerCase() + " "}${whenLabel(next.at).time}` : "";
  switch (st.source) {
    case "schedule": return `volgens planning${st.slot.rule_name ? ` (${esc(st.slot.rule_name)})` : ""}${until}`;
    case "default": return `standaardwachtrij${until}`;
    case "manual": return "handmatig gestart";
    default: return "";
  }
}

function updateNu() {
  const st = S.state;
  if (!st || !$("#scr")) return;
  const mode = nowMode(st);
  const v = st.vlc;
  const idle = st.running && st.source === "idle";
  const file = v?.filename || null;

  // scherm
  const img = $("#scrImg"), off = $("#scrOff");
  const url = st.running && !idle && file ? thumbUrl(file) : null;
  if (url) {
    if (img.getAttribute("src") !== url) img.src = url;
    img.hidden = false;
    off.textContent = "";
  } else {
    img.hidden = true;
    img.removeAttribute("src");
    off.textContent = idle ? "Zwart scherm" : st.running ? "Geen voorbeeld van dit bestand" :
      mode === "error" ? "VLC start niet. Zie de melding hieronder." : "Er speelt niets. Het scherm toont het bureaublad.";
  }
  $("#scr").classList.toggle("paused", mode === "paused");
  $("#scrTally").className = `tally ${mode}`;
  $("#scrBadge").textContent = { live: "Op het scherm", paused: "Gepauzeerd", error: "Storing", off: idle ? "Zwart scherm" : "Niet actief" }[mode];

  // titel
  $("#nowTitle").textContent = idle ? "Zwart scherm" : st.running ? (file || st.queue_name) : "Niets op het scherm";
  $("#nowMeta").innerHTML = st.running && !idle ? `Uit wachtrij ${esc(st.queue_name)}, ${sourceText(st)}` :
    idle ? "Er staat niets gepland." : st.desired.queue_id ? "Wacht op VLC." : "Er staat nu niets gepland.";
  updateTimecode();

  // knoppen
  const controllable = st.running && !idle && !!v;
  for (const act of ["prev", "next"]) view.querySelector(`[data-act="${act}"]`).disabled = !controllable;
  const bp = $("#btnPause");
  bp.disabled = !controllable;
  const paused = v?.state === "paused";
  bp.dataset.act = paused ? "play" : "pause";
  bp.innerHTML = paused ? `${icon("play")}<span>Verder</span>` : `${icon("pause")}<span>Pauze</span>`;
  view.querySelector('[data-act="stop"]').disabled = !st.running;

  // meldingen
  const b = [];
  if (st.error) b.push(`<div class="banner error" role="alert"><p><b>${esc(st.error)}</b><br><span class="small">Controleer het VLC-commando en de display onder Instellingen, of bekijk de technische details hieronder.</span></p><button class="btn small" data-act="restart">Opnieuw proberen</button></div>`);
  if (!st.scheduler_enabled) {
    b.push(`<div class="banner warn"><p>De planning staat uit. Alleen wat je hier start, komt op het scherm.</p><button class="btn small" data-act="sched-on">Planning aanzetten</button></div>`);
  } else if (st.override) {
    const next = st.next_changes?.[0];
    const back = next ? ` De planning neemt het weer over: ${whenLabel(next.at).day.toLowerCase()} om ${whenLabel(next.at).time}.` : "";
    b.push(`<div class="banner"><p>${st.override.queue_id ? "Handmatig gekozen." : "Handmatig gestopt."}${back}</p><button class="btn small primary" data-act="resume">Terug naar planning</button></div>`);
  }
  $("#banners").innerHTML = b.join("");

  // snel starten
  const qs = queues();
  $("#quick").innerHTML = qs.length ? qs.map((q) => {
    const playing = st.running && st.queue_id === q.id;
    return `<li><span class="lane" style="background:${qColor(q.id)}"></span>
      <div class="grow"><b>${esc(q.name)}</b><small>${esc(queueSummary(q))}</small></div>
      ${playing ? `<span class="onair"><span class="tally ${mode}"></span>Speelt nu</span>` :
        `<button class="btn small" data-act="start" data-id="${q.id}" ${q.items.length ? "" : "disabled title=\"Deze wachtrij is leeg\""}>${icon("play")}Start</button>`}</li>`;
  }).join("") : `<li class="empty">Nog geen wachtrijen. <a href="#wachtrijen">Maak een wachtrij</a> met je video's en afbeeldingen.</li>`;

  // komende wissels
  const ch = st.next_changes || [];
  $("#changes").innerHTML = !st.scheduler_enabled ? `<li class="empty">De planning staat uit.</li>` :
    ch.length ? ch.map((c) => { const w = whenLabel(c.at); return `<li><time><b>${w.time}</b>${esc(w.day)}</time><div>${qChip(c.queue_id)}</div></li>`; }).join("") :
      `<li class="empty">Geen wissels in de komende week. <a href="#planning">Planning bekijken</a></li>`;

  // technisch
  $("#tech").innerHTML = `
    ${st.running ? `<p class="small muted" style="margin-top:10px">VLC draait als proces ${st.pid}, gestart om ${st.started_at.slice(11, 16)}.</p>` : ""}
    <pre class="code">${esc(st.command || "VLC draait niet.")}</pre>
    <p class="small muted" style="margin-top:12px">Laatste uitvoer van VLC</p>
    <pre class="code">${esc(S.vlcLog || "–")}</pre>`;
}

function updateTimecode() {
  const tc = $("#tc");
  if (!tc) return;
  const t = S.tc;
  if (!t || !S.state?.running || S.state.source === "idle") {
    tc.innerHTML = `–:––`;
    $("#scrub").firstElementChild.style.width = "0";
    return;
  }
  const now = t.playing ? Math.min(t.length || Infinity, t.time + (Date.now() - t.at) / 1000) : t.time;
  tc.innerHTML = `${fmtDur(now)}${t.length ? `<span class="len">/ ${fmtDur(t.length)}</span>` : ""}`;
  $("#scrub").classList.toggle("paused", !t.playing);
  $("#scrub").firstElementChild.style.width = t.length ? `${Math.min(100, (now / t.length) * 100)}%` : "0";
}

function renderLog() {
  const el = $("#log");
  if (!el) return;
  el.innerHTML = S.events.length ? S.events.slice(0, 60).map((e) =>
    `<li><time>${e.ts.slice(11, 16)}</time><span class="${e.level}">${esc(e.message)}</span></li>`).join("") :
    `<li class="empty">Nog geen gebeurtenissen.</li>`;
  if (S.state) {
    const pres = $("#tech")?.querySelectorAll("pre");
    if (pres && pres[1]) pres[1].textContent = S.vlcLog || "–";
  }
}

async function playerAction(act, body) {
  try {
    await api("POST", `/api/player/${act}`, body || {});
    await loadState();
    loadEvents();
  } catch (e) { fail(e); }
}

// ================================================================ MEDIA
function renderMedia() {
  const free = S.disk ? S.disk.free : 0, total = S.disk ? S.disk.total : 1;
  const accept = S.allowed.join(",");
  view.innerHTML = `
  <div class="page-head">
    <div><h1>Media</h1><p>Video's en afbeeldingen die op het scherm kunnen komen.</p></div>
    <div class="spacer"></div>
    ${S.disk ? `<div class="disk" title="Schijfruimte op de kiosk"><div class="bar"><div style="width:${((total - free) / total) * 100}%"></div></div>${fmtBytes(free)} vrij van ${fmtBytes(total)}</div>` : ""}
  </div>
  <div class="dropzone" id="drop">
    <div class="what"><b>Sleep bestanden hierheen</b>
      <span class="muted">Video (mp4, mkv, mov, avi, webm) of afbeelding (png, jpg, bmp, gif). Meerdere tegelijk kan.</span></div>
    <button class="btn primary" type="button" data-act="pick">${icon("upload")}Bestanden kiezen</button>
    <input type="file" id="fileIn" multiple accept="${esc(accept)}" hidden>
  </div>
  <ul class="uploads" id="uploads"></ul>
  ${!S.ffmpeg ? `<div class="banner warn"><p>ffmpeg is niet geïnstalleerd, dus er zijn geen voorbeeldplaatjes en videoduur. Installeer het met <b>sudo apt install ffmpeg</b>.</p></div>` : ""}
  <div class="toolbar">
    <div class="segmented" role="group" aria-label="Filter">
      ${[["all", "Alles"], ["video", "Video's"], ["image", "Afbeeldingen"]].map(([k, l]) => `<button type="button" data-act="filter" data-v="${k}" aria-pressed="${S.mediaFilter === k}">${l}</button>`).join("")}
    </div>
    <input type="search" id="msearch" placeholder="Zoeken op naam" value="${esc(S.mediaSearch)}" aria-label="Zoeken op naam">
    <span class="muted small" id="mcount"></span>
  </div>
  <div class="mgrid" id="mgrid"></div>`;

  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => addUploads(e.dataTransfer.files));
  $("#fileIn").addEventListener("change", (e) => { addUploads(e.target.files); e.target.value = ""; });
  $("#msearch").addEventListener("input", (e) => { S.mediaSearch = e.target.value; renderMediaGrid(); });
  renderUploads();
  renderMediaGrid();
}

function renderMediaGrid() {
  const grid = $("#mgrid");
  if (!grid) return;
  const q = S.mediaSearch.trim().toLowerCase();
  const list = S.media.filter((m) => (S.mediaFilter === "all" || m.kind === S.mediaFilter) && (!q || m.name.toLowerCase().includes(q)));
  $("#mcount").textContent = plural(list.length, "bestand", "bestanden");
  if (!S.media.length) {
    grid.innerHTML = `<p class="empty"><b>Nog geen media.</b> Upload je eerste video of afbeelding hierboven.</p>`;
    return;
  }
  grid.innerHTML = list.length ? list.map((m) => {
    const label = m.kind === "video" ? `Video${m.duration ? " " + fmtDur(m.duration) : ""}` : "Afbeelding";
    const res = m.width ? `${m.width}×${m.height}, ` : "";
    const used = m.used_in.length ? `In ${esc(m.used_in.join(", "))}` : "Nog in geen wachtrij";
    return `<article class="mcard">${thumbHtml(m.name, label)}
      <div class="body"><b>${esc(m.name)}</b><span class="meta">${res}${fmtBytes(m.size)}</span><span class="meta">${used}</span>
      <div class="actions"><button class="btn small" data-act="preview" data-name="${esc(m.name)}">Bekijken</button>
      <button class="btn small ghost danger" data-act="del-media" data-name="${esc(m.name)}">Verwijderen</button></div></div></article>`;
  }).join("") : `<p class="empty">Niets gevonden voor deze zoekopdracht.</p>`;
  if (S.media.some((m) => m.probing)) setTimeout(async () => { if (S.view === "media") { await loadMedia(); renderMediaGrid(); } }, 2500);
}

function addUploads(fileList) {
  const allowed = new Set(S.allowed);
  for (const file of fileList) {
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!allowed.has(ext)) { toast(`${file.name}: dit bestandstype wordt niet ondersteund`, "error"); continue; }
    S.uploads.push({ id: Math.random().toString(36).slice(2), file, loaded: 0, status: "wacht" });
  }
  renderUploads();
  runUploads();
}

function renderUploads() {
  const el = $("#uploads");
  if (!el) return;
  el.innerHTML = S.uploads.map((u) => {
    const pct = u.status === "klaar" ? 100 : u.file.size ? Math.round((u.loaded / u.file.size) * 100) : 0;
    const label = { wacht: "In de wacht", bezig: `${pct}%`, klaar: "Geüpload", fout: "Mislukt" }[u.status];
    return `<li><span class="name" title="${esc(u.error || "")}">${esc(u.file.name)}${u.error ? ` <span class="small" style="color:var(--live)">${esc(u.error)}</span>` : ""}</span>
      <div class="bar ${u.status === "klaar" ? "done" : u.status === "fout" ? "fail" : ""}"><div style="width:${u.status === "fout" ? 100 : pct}%"></div></div>
      <span class="small muted state">${label}</span></li>`;
  }).join("");
}

async function runUploads() {
  if (S.uploading) return;
  S.uploading = true;
  let done = 0;
  for (let u = S.uploads.find((x) => x.status === "wacht"); u; u = S.uploads.find((x) => x.status === "wacht")) {
    u.status = "bezig";
    renderUploads();
    await new Promise((resolve) => {
      const x = new XMLHttpRequest();
      x.open("PUT", "/api/media/upload");
      x.setRequestHeader("X-Requested-With", "kiosk");
      x.setRequestHeader("X-Filename", enc(u.file.name));
      let last = 0;
      x.upload.onprogress = (e) => { u.loaded = e.loaded; if (Date.now() - last > 200) { last = Date.now(); renderUploads(); } };
      x.onload = () => {
        if (x.status === 200) { u.status = "klaar"; done++; }
        else { u.status = "fout"; try { u.error = JSON.parse(x.responseText).error; } catch { u.error = `Fout ${x.status}`; } }
        resolve();
      };
      x.onerror = () => { u.status = "fout"; u.error = "Verbinding verbroken"; resolve(); };
      x.send(u.file);
    });
    renderUploads();
  }
  S.uploading = false;
  if (done) {
    toast(`${plural(done, "bestand", "bestanden")} geüpload`);
    await loadMedia();
    if (S.view === "media") renderMedia();
    setTimeout(() => { S.uploads = S.uploads.filter((u) => u.status !== "klaar"); renderUploads(); }, 5000);
  }
}

function previewMedia(name) {
  const m = S.mediaByName[name];
  if (!m) return;
  const src = `/media/${enc(name)}`;
  openDialog({
    title: name, wide: true,
    body: `<div class="preview">${m.kind === "video" ? `<video src="${src}" controls autoplay muted playsinline></video>` : `<img src="${src}" alt="">`}</div>
      <p class="muted small">${m.width ? `${m.width}×${m.height}, ` : ""}${m.duration ? fmtDur(m.duration) + ", " : ""}${fmtBytes(m.size)}. Sommige videoformaten (zoals mkv) spelen niet in elke browser af, maar wel in VLC.</p>`,
  });
}

async function deleteMedia(name) {
  const m = S.mediaByName[name];
  const used = m?.used_in || [];
  const ok = await confirmBox({
    title: "Bestand verwijderen?",
    text: `<b>${esc(name)}</b> wordt van de kiosk verwijderd.${used.length ? ` Het wordt ook uit ${used.length === 1 ? "de wachtrij" : "de wachtrijen"} ${esc(used.join(", "))} gehaald.` : ""}`,
  });
  if (!ok) return;
  try {
    await api("DELETE", `/api/media/${enc(name)}?force=1`);
    toast("Verwijderd");
    await Promise.all([loadMedia(), loadAll()]);
    renderMedia();
  } catch (e) { fail(e); }
}

// ============================================================ WACHTRIJEN
function selectQueue(id) {
  S.queueSel = id;
  const q = id === "new" ? { id: null, name: "", items: [], loop: true, shuffle: false, mute: false } : queueById(id);
  S.draft = q ? JSON.parse(JSON.stringify(q)) : null;
  S.dirty = false;
}

function renderQueues() {
  if (S.queueSel !== "new" && !queueById(S.queueSel)) selectQueue(queues()[0]?.id || null);
  const qs = queues();
  view.innerHTML = `
  <div class="page-head"><div><h1>Wachtrijen</h1><p>Een wachtrij is een reeks video's en afbeeldingen die na elkaar op het scherm komen.</p></div></div>
  <div class="split">
    <ul class="qnav" aria-label="Wachtrijen">
      ${qs.map((q) => `<li><button type="button" data-act="sel" data-id="${q.id}" aria-current="${S.queueSel === q.id}">
        <span class="qdot" style="background:${qColor(q.id)}"></span><span class="grow"><b>${esc(q.name)}</b><small>${esc(queueSummary(q))}</small></span>
        ${S.state?.running && S.state.queue_id === q.id ? `<span class="tally ${nowMode(S.state)}" title="Speelt nu"></span>` : ""}</button></li>`).join("")}
      <li><button type="button" class="new" data-act="sel" data-id="new" aria-current="${S.queueSel === "new"}">${icon("plus")}Nieuwe wachtrij</button></li>
    </ul>
    <div id="editor"></div>
  </div>`;
  renderEditor();
}

function renderEditor() {
  const el = $("#editor");
  const q = S.draft;
  if (!q) {
    el.innerHTML = `<section class="panel"><p class="empty"><b>Nog geen wachtrijen.</b> Maak er een om video's en afbeeldingen achter elkaar af te spelen.</p>
      <button class="btn primary" data-act="sel" data-id="new">${icon("plus")}Nieuwe wachtrij</button></section>`;
    return;
  }
  el.innerHTML = `
  <section class="panel">
    <div class="grid2"><label class="field"><span>Naam</span><input type="text" id="qName" maxlength="80" value="${esc(q.name)}" placeholder="Bijvoorbeeld: Bedrijfspand november"></label></div>
    <div class="opts" style="margin-top:18px">
      <div><span class="field-label">Afspelen</span>
        <div class="segmented" role="group" aria-label="Afspelen">
          <button type="button" data-act="loop" data-v="1" aria-pressed="${q.loop !== false}">Doorlopend herhalen</button>
          <button type="button" data-act="loop" data-v="0" aria-pressed="${q.loop === false}">Eén keer</button>
        </div>
        <p class="hint" id="loopHint">${q.loop === false ? "Na het laatste item gaat de planning verder, of speelt de standaardwachtrij." : "Begint na het laatste item weer bij het eerste."}</p>
      </div>
      <label class="check"><input type="checkbox" id="qShuffle" ${q.shuffle ? "checked" : ""}><span><b>Willekeurige volgorde</b><small>Elke ronde in een andere volgorde</small></span></label>
      <label class="check"><input type="checkbox" id="qMute" ${q.mute ? "checked" : ""}><span><b>Geluid uit</b><small>Video's spelen zonder geluid</small></span></label>
    </div>
    <div class="panel-head" style="margin-top:28px;margin-bottom:12px"><h2>Inhoud</h2><span class="muted small" id="qTotal"></span>
      <button class="btn small" type="button" data-act="add-media">${icon("plus")}Media toevoegen</button></div>
    <ul class="items" id="items"></ul>
    <div class="editor-foot">
      <span class="status" id="qStatus"></span>
      ${q.id ? `<button class="btn ghost danger" type="button" data-act="q-del">Verwijderen</button>
      <button class="btn" type="button" data-act="q-dup">Dupliceren</button>` : ""}
      <button class="btn" type="button" data-act="q-play">${icon("play")}Nu afspelen</button>
      <button class="btn primary" type="button" data-act="q-save">Opslaan</button>
    </div>
  </section>`;
  $("#qName").addEventListener("input", (e) => { q.name = e.target.value; markDirty(); });
  $("#qShuffle").addEventListener("change", (e) => { q.shuffle = e.target.checked; markDirty(); });
  $("#qMute").addEventListener("change", (e) => { q.mute = e.target.checked; markDirty(); });
  renderItems();
  markDirty(S.dirty);
  if (!q.id && !q.name) $("#qName").focus();
}

function renderItems() {
  const q = S.draft, el = $("#items");
  const def = S.all.settings.default_image_duration;
  if (!q.items.length) {
    el.outerHTML = `<ul class="items" id="items"><li style="display:block;padding:24px" class="empty">Deze wachtrij is nog leeg. Kies <b>Media toevoegen</b> om video's en afbeeldingen toe te voegen.</li></ul>`;
  } else {
    el.innerHTML = q.items.map((it, i) => {
      const m = S.mediaByName[it.file];
      const meta = !m ? `<small class="missing">Bestand ontbreekt, wordt overgeslagen</small>` :
        `<small>${m.kind === "video" ? "Video" : "Afbeelding"}${m.width ? `, ${m.width}×${m.height}` : ""}</small>`;
      const dur = m?.kind === "image" ?
        `<label class="dur"><input type="number" min="1" max="86400" data-dur="${i}" value="${it.duration ?? ""}" placeholder="${def}" aria-label="Seconden in beeld">sec</label>` :
        `<span class="dur num">${m?.duration ? fmtDur(m.duration) : "–"}</span>`;
      return `<li draggable="true" data-i="${i}">
        <span class="handle" title="Sleep om te verplaatsen">${icon("grip")}</span>
        <span class="pos">${i + 1}</span>
        ${thumbHtml(it.file)}
        <div class="name"><b title="${esc(it.file)}">${esc(it.file)}</b>${meta}</div>
        ${dur}
        <div class="ops">
          <button class="btn ghost icon small" type="button" data-act="up" data-i="${i}" aria-label="Omhoog" ${i === 0 ? "disabled" : ""}>${icon("up")}</button>
          <button class="btn ghost icon small" type="button" data-act="down" data-i="${i}" aria-label="Omlaag" ${i === q.items.length - 1 ? "disabled" : ""}>${icon("down")}</button>
          <button class="btn ghost icon small" type="button" data-act="rm" data-i="${i}" aria-label="Uit wachtrij halen">${icon("x")}</button>
        </div></li>`;
    }).join("");
    el.querySelectorAll("[data-dur]").forEach((inp) => inp.addEventListener("input", (e) => {
      const v = parseInt(e.target.value, 10);
      q.items[+e.target.dataset.dur].duration = v > 0 ? v : null;
      markDirty();
    }));
    bindDrag(el);
  }
  updateTotal();
}

function bindDrag(list) {
  let from = null;
  list.querySelectorAll("li[draggable]").forEach((li) => {
    li.addEventListener("dragstart", (e) => {
      if (e.target.closest("input")) { e.preventDefault(); return; }
      from = +li.dataset.i; li.classList.add("dragging"); e.dataTransfer.effectAllowed = "move";
    });
    li.addEventListener("dragend", () => { li.classList.remove("dragging"); list.querySelectorAll(".drag-over").forEach((x) => x.classList.remove("drag-over")); });
    li.addEventListener("dragover", (e) => { e.preventDefault(); li.classList.add("drag-over"); });
    li.addEventListener("dragleave", () => li.classList.remove("drag-over"));
    li.addEventListener("drop", (e) => {
      e.preventDefault();
      const to = +li.dataset.i;
      if (from === null || from === to) return;
      const [it] = S.draft.items.splice(from, 1);
      S.draft.items.splice(to, 0, it);
      from = null;
      markDirty();
      renderItems();
    });
  });
}

function updateTotal() {
  const el = $("#qTotal");
  if (el) el.textContent = S.draft.items.length ? queueSummary(S.draft) : "";
}

function markDirty(flag = true) {
  S.dirty = flag;
  const st = $("#qStatus");
  if (!st) return;
  st.className = `status ${flag ? "dirty" : ""}`;
  st.textContent = flag ? "Niet opgeslagen wijzigingen" : S.draft?.id ? "Alles opgeslagen" : "";
  updateTotal();
}

async function saveQueue() {
  const q = S.draft;
  if (!q.name.trim()) { toast("Geef de wachtrij een naam", "error"); $("#qName").focus(); return false; }
  const payload = { name: q.name, items: q.items, loop: q.loop !== false, shuffle: !!q.shuffle, mute: !!q.mute };
  try {
    const r = q.id ? await api("PUT", `/api/queues/${q.id}`, payload) : await api("POST", "/api/queues", payload);
    await loadAll();
    selectQueue(r.queue.id);
    renderQueues();
    toast("Opgeslagen");
    return true;
  } catch (e) { fail(e); return false; }
}

async function deleteQueue() {
  const q = S.draft;
  const rules = S.all.rules.filter((r) => r.queue_id === q.id);
  const isDefault = S.all.settings.default_queue === q.id;
  const extra = [];
  if (rules.length) extra.push(`${plural(rules.length, "regel", "regels")} in de planning ${rules.length === 1 ? "verdwijnt" : "verdwijnen"} ook`);
  if (isDefault) extra.push("dit is de standaardwachtrij; daarna staat er niets als standaard ingesteld");
  const ok = await confirmBox({ title: "Wachtrij verwijderen?", text: `<b>${esc(q.name)}</b> wordt verwijderd. De mediabestanden blijven bewaard.${extra.length ? " Let op: " + extra.join(", en ") + "." : ""}` });
  if (!ok) return;
  try {
    await api("DELETE", `/api/queues/${q.id}?force=1`);
    await loadAll();
    selectQueue(queues()[0]?.id || null);
    renderQueues();
    loadState();
    toast("Verwijderd");
  } catch (e) { fail(e); }
}

function pickMedia() {
  if (!S.media.length) { toast("Upload eerst media onder Media", "error"); return; }
  const chosen = [];
  const card = (m) => {
    const label = m.kind === "video" ? `Video${m.duration ? " " + fmtDur(m.duration) : ""}` : "Afbeelding";
    return `<button type="button" class="pick" data-name="${esc(m.name)}" aria-pressed="false"><span class="order"></span>${thumbHtml(m.name, label)}<div class="cap">${esc(m.name)}</div></button>`;
  };
  openDialog({
    title: "Media toevoegen", wide: true,
    body: `<input type="search" id="psearch" placeholder="Zoeken op naam" aria-label="Zoeken op naam"><div class="picker" id="picker">${S.media.map(card).join("")}</div>`,
    foot: `<span class="muted small" style="margin-right:auto;align-self:center">Klik in de volgorde waarin ze moeten afspelen.</span>
      <button class="btn" type="button" data-close>Annuleren</button><button class="btn primary" type="button" data-add disabled>Toevoegen</button>`,
    onOpen: (d) => {
      $("#psearch", d).addEventListener("input", (e) => {
        const t = e.target.value.toLowerCase();
        d.querySelectorAll(".pick").forEach((p) => { p.hidden = !p.dataset.name.toLowerCase().includes(t); });
      });
    },
    onClick: (e, d) => {
      const p = e.target.closest(".pick");
      if (p) {
        const i = chosen.indexOf(p.dataset.name);
        if (i >= 0) chosen.splice(i, 1); else chosen.push(p.dataset.name);
        d.querySelectorAll(".pick").forEach((x) => {
          const n = chosen.indexOf(x.dataset.name);
          x.setAttribute("aria-pressed", n >= 0);
          x.querySelector(".order").textContent = n >= 0 ? n + 1 : "";
        });
        const add = d.querySelector("[data-add]");
        add.disabled = !chosen.length;
        add.textContent = chosen.length ? `${plural(chosen.length, "bestand", "bestanden")} toevoegen` : "Toevoegen";
      }
      if (e.target.closest("[data-add]")) {
        S.draft.items.push(...chosen.map((file) => ({ file })));
        d.close();
        markDirty();
        renderItems();
      }
    },
  });
}

// ============================================================== PLANNING
async function loadTimeline() {
  try {
    S.timeline = await api("GET", `/api/timeline?start=${S.week}&days=7`);
    renderSched();
  } catch (e) { fail(e); }
}

function renderPlanning() {
  if (!S.week) S.week = D.monday(serverNow().date);
  const st = S.all.settings;
  view.innerHTML = `
  <div class="page-head"><div><h1>Planning</h1><p>Bepaal wanneer welke wachtrij op het scherm komt.</p></div></div>
  <section class="panel">
    <div class="plan-top">
      <label class="switch"><input type="checkbox" id="schedOn" ${st.scheduler_enabled ? "checked" : ""}><span class="track"></span>Planning actief</label>
      <div class="grid2">
        <label class="field"><span>Als er niets gepland staat</span>
          <select id="defQ"><option value="">Niets afspelen</option>${queues().map((q) => `<option value="${q.id}" ${st.default_queue === q.id ? "selected" : ""}>${esc(q.name)}</option>`).join("")}</select>
          <p class="hint">Deze standaardwachtrij vult alle tijd zonder regel.</p></label>
        <label class="check" style="align-self:center"><input type="checkbox" id="idleBlack" ${st.idle_black ? "checked" : ""}>
          <span><b>Zwart scherm als er niets speelt</b><small>In plaats van het bureaublad, ook na Stop</small></span></label>
      </div>
    </div>
  </section>
  <section class="panel" style="margin-top:24px">
    <div class="week-nav">
      <button class="btn icon small" type="button" data-act="wk" data-v="-7" aria-label="Vorige week">${icon("left")}</button>
      <button class="btn icon small" type="button" data-act="wk" data-v="7" aria-label="Volgende week">${icon("right")}</button>
      <h2 id="wkTitle"></h2>
      <button class="btn small ghost" type="button" data-act="wk" data-v="0">Deze week</button>
    </div>
    <div class="sched" id="sched"></div>
  </section>
  <section class="panel" style="margin-top:24px">
    <div class="panel-head"><h2>Regels</h2><button class="btn small primary" type="button" data-act="new-rule">${icon("plus")}Nieuwe regel</button></div>
    <p class="muted small" style="margin:-6px 0 14px">Overlappen twee regels, dan wint de regel die het laatst begon. Zo kun je een regel voor de hele dag hebben en daarbinnen een kortere regel, bijvoorbeeld rond de lunch.</p>
    <ul class="rules" id="rules"></ul>
  </section>`;
  $("#schedOn").addEventListener("change", async (e) => {
    try { await api("POST", "/api/scheduler", { enabled: e.target.checked }); await loadAll(); loadState(); loadTimeline(); toast(e.target.checked ? "Planning aangezet" : "Planning uitgezet"); } catch (err) { fail(err); }
  });
  $("#defQ").addEventListener("change", (e) => saveSettings({ default_queue: e.target.value || null }, "Standaardwachtrij opgeslagen"));
  $("#idleBlack").addEventListener("change", (e) => saveSettings({ idle_black: e.target.checked }, "Opgeslagen"));
  renderSched();
  renderRules();
  loadTimeline();
}

function renderSched() {
  const el = $("#sched");
  if (!el) return;
  const wk = S.week, end = D.add(wk, 6);
  $("#wkTitle").textContent = `Week ${D.isoWeek(wk)}: ${D.fmt(wk, { day: "numeric", month: wk.slice(5, 7) === end.slice(5, 7) ? undefined : "long" })} t/m ${D.fmt(end, { day: "numeric", month: "long", year: "numeric" })}`;
  const segs = S.timeline && S.timeline.start.slice(0, 10) === wk ? S.timeline.segments : [];
  const now = serverNow();
  const ruleName = (id) => { const r = S.all.rules.find((x) => x.id === id); return r ? (r.name || "regel zonder naam") : ""; };
  const rows = [];
  for (let i = 0; i < 7; i++) {
    const day = D.add(wk, i), next = D.add(day, 1);
    const dayStart = `${day}T00:00:00`, dayEnd = `${next}T00:00:00`;
    const blocks = [];
    for (const s of segs) {
      if (!s.queue_id) continue;
      const a = s.start > dayStart ? s.start : dayStart, b = s.end < dayEnd ? s.end : dayEnd;
      if (a >= b) continue;
      const m0 = a === dayStart ? 0 : minOf(a), m1 = b === dayEnd ? 1440 : minOf(b);
      const q = queueById(s.queue_id), color = qColor(s.queue_id);
      const label = `${q ? q.name : "?"}: ${pad(Math.floor(m0 / 60))}:${pad(m0 % 60)}–${pad(Math.floor(m1 / 60))}:${pad(m1 % 60)}${s.rule_id ? ` (${ruleName(s.rule_id)})` : " (standaardwachtrij)"}`;
      const style = `left:${(m0 / 1440) * 100}%;width:${((m1 - m0) / 1440) * 100}%;${s.rule_id ? `background:${color}` : `background:color-mix(in srgb, ${color} 22%, var(--panel));color:var(--ink)`}`;
      blocks.push(s.rule_id ?
        `<button type="button" class="seg" data-act="edit-rule" data-id="${s.rule_id}" style="${style}" title="${esc(label)}"><span>${esc(q?.name || "")}</span></button>` :
        `<div class="seg default" style="${style}" title="${esc(label)}"><span>${esc(q?.name || "")}</span></div>`);
    }
    const isToday = day === now.date;
    rows.push(`<div class="sched-row"><div class="sched-day ${isToday ? "today" : ""}"><b>${cap(DAY_SHORT[i])} ${D.fmt(day, { day: "numeric" })}</b><small class="muted">${isToday ? "vandaag" : D.fmt(day, { month: "short" })}</small></div>
      <div class="lane-track">${[3, 6, 9, 12, 15, 18, 21].map((h) => `<span class="hour" style="left:${(h / 24) * 100}%"></span>`).join("")}
      ${blocks.join("")}${isToday ? `<span class="nowline" style="left:${(now.min / 1440) * 100}%" title="Nu"></span>` : ""}</div></div>`);
  }
  const used = [...new Set(segs.filter((s) => s.queue_id).map((s) => s.queue_id))];
  el.innerHTML = !S.all.settings.scheduler_enabled ?
    `<p class="empty">De planning staat uit. Zet hem aan om het weekoverzicht te zien.</p>` :
    `${rows.join("")}
    <div class="axis"><span></span><div class="ticks">${[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => `<span class="${h % 6 ? "minor" : ""}" style="left:${(h / 24) * 100}%">${pad(h)}:00</span>`).join("")}</div></div>
    <div class="legend">${used.map(qChip).join("")}${segs.some((s) => s.queue_id && !s.rule_id) ? `<span class="chip" style="background:transparent;font-weight:400;color:var(--muted)">Gedempte kleur: standaardwachtrij</span>` : ""}
    ${!segs.some((s) => s.queue_id) ? `<span class="muted">Deze week staat er niets gepland.</span>` : ""}</div>`;
}

function renderRules() {
  const el = $("#rules");
  if (!el) return;
  const rules = [...S.all.rules].sort((a, b) => (b.enabled - a.enabled) || (Math.min(...a.days) - Math.min(...b.days)) || a.start.localeCompare(b.start));
  el.innerHTML = rules.length ? rules.map((r) => {
    const q = queueById(r.queue_id);
    const period = fmtPeriod(r);
    return `<li class="${r.enabled ? "" : "off"}"><span class="lane" style="background:${qColor(r.queue_id)}"></span>
      <div class="what"><b>${esc(r.name || q?.name || "Regel")}</b>
        <div class="when">${fmtDays(r.days)}, ${fmtTimes(r)}</div>
        <small>Wachtrij ${esc(q?.name || "?")}${period ? `, ${period}` : ""}${r.enabled ? "" : ". Staat uit."}</small></div>
      <div class="ops">
        <label class="switch" title="${r.enabled ? "Regel staat aan" : "Regel staat uit"}"><input type="checkbox" data-toggle="${r.id}" ${r.enabled ? "checked" : ""} aria-label="Regel aan of uit"><span class="track"></span></label>
        <button class="btn small" type="button" data-act="edit-rule" data-id="${r.id}">Bewerken</button>
        <button class="btn ghost icon small danger" type="button" data-act="del-rule" data-id="${r.id}" aria-label="Regel verwijderen">${icon("x")}</button>
      </div></li>`;
  }).join("") : `<li class="empty" style="display:block">Nog geen regels. ${S.all.settings.default_queue ? "Nu speelt altijd de standaardwachtrij." : "Kies hierboven een standaardwachtrij of maak een regel."}</li>`;
  el.querySelectorAll("[data-toggle]").forEach((inp) => inp.addEventListener("change", async (e) => {
    const r = S.all.rules.find((x) => x.id === e.target.dataset.toggle);
    try {
      await api("PUT", `/api/rules/${r.id}`, { ...r, enabled: e.target.checked });
      await loadAll(); renderRules(); loadTimeline(); loadState();
    } catch (err) { fail(err); }
  }));
}

function ruleDialog(rule) {
  if (!queues().length) { toast("Maak eerst een wachtrij aan", "error"); return; }
  const r = rule ? { ...rule, days: [...rule.days] } :
    { name: "", queue_id: queues()[0].id, days: [0, 1, 2, 3, 4], start: "09:00", end: "17:00", date_from: "", date_to: "", enabled: true };
  const wholeDay = r.start === "00:00" && r.end === "00:00";
  openDialog({
    title: rule ? "Regel bewerken" : "Nieuwe regel",
    body: `
      <label class="field"><span>Wachtrij</span><select id="rQ">${queues().map((q) => `<option value="${q.id}" ${q.id === r.queue_id ? "selected" : ""}>${esc(q.name)}</option>`).join("")}</select></label>
      <div><span class="field-label">Dagen</span>
        <div class="days" id="rDays">${DAY_SHORT.map((d, i) => `<button type="button" data-day="${i}" aria-pressed="${r.days.includes(i)}" title="${DAY_LONG[i]}">${cap(d)}</button>`).join("")}</div>
        <div class="quick"><button type="button" data-days="0,1,2,3,4">Werkdagen</button><button type="button" data-days="5,6">Weekend</button><button type="button" data-days="0,1,2,3,4,5,6">Elke dag</button></div></div>
      <div><span class="field-label">Tijd</span>
        <label class="check" style="margin-bottom:10px"><input type="checkbox" id="rWhole" ${wholeDay ? "checked" : ""}><span><b>Hele dag</b></span></label>
        <div class="grid2" id="rTimes" ${wholeDay ? "hidden" : ""}>
          <label class="field"><span>Van</span><input type="time" id="rStart" value="${r.start}"></label>
          <label class="field"><span>Tot</span><input type="time" id="rEnd" value="${r.end}"></label>
        </div>
        <p class="hint" id="rTimeHint"></p></div>
      <div><span class="field-label">Periode</span>
        <div class="grid2">
          <label class="field"><span class="muted" style="font-weight:400">Vanaf (leeg = altijd)</span><input type="date" id="rFrom" value="${r.date_from || ""}"></label>
          <label class="field"><span class="muted" style="font-weight:400">Tot en met (leeg = geen einde)</span><input type="date" id="rTo" value="${r.date_to || ""}"></label>
        </div></div>
      <label class="field"><span>Naam (optioneel)</span><input type="text" id="rName" maxlength="80" value="${esc(r.name)}" placeholder="Bijvoorbeeld: Welkom maandagochtend"></label>
      <label class="check"><input type="checkbox" id="rOn" ${r.enabled ? "checked" : ""}><span><b>Regel staat aan</b></span></label>
      <p class="err" id="rErr" role="alert" style="color:var(--live);font-weight:600"></p>`,
    foot: `${rule ? `<button class="btn ghost danger" type="button" data-del style="margin-right:auto">Verwijderen</button>` : ""}
      <button class="btn" type="button" data-close>Annuleren</button><button class="btn primary" type="button" data-save>Opslaan</button>`,
    onOpen: (d) => {
      const hint = () => {
        const s = $("#rStart", d).value, e = $("#rEnd", d).value;
        $("#rTimeHint", d).textContent = $("#rWhole", d).checked ? "Van 00:00 tot 24:00." : e && s && e <= s ? `Loopt door tot ${e} de volgende dag.` : "";
      };
      $("#rWhole", d).addEventListener("change", (e) => { $("#rTimes", d).hidden = e.target.checked; hint(); });
      $("#rStart", d).addEventListener("input", hint);
      $("#rEnd", d).addEventListener("input", hint);
      hint();
    },
    onClick: async (e, d) => {
      const day = e.target.closest("[data-day]");
      if (day) {
        const i = +day.dataset.day;
        r.days = r.days.includes(i) ? r.days.filter((x) => x !== i) : [...r.days, i];
        day.setAttribute("aria-pressed", r.days.includes(i));
      }
      const quick = e.target.closest("[data-days]");
      if (quick) {
        r.days = quick.dataset.days.split(",").map(Number);
        d.querySelectorAll("[data-day]").forEach((b) => b.setAttribute("aria-pressed", r.days.includes(+b.dataset.day)));
      }
      if (e.target.closest("[data-del]")) {
        d.close();
        deleteRule(rule.id);
      }
      if (e.target.closest("[data-save]")) {
        const whole = $("#rWhole", d).checked;
        const payload = {
          name: $("#rName", d).value, queue_id: $("#rQ", d).value, days: r.days,
          start: whole ? "00:00" : $("#rStart", d).value, end: whole ? "00:00" : $("#rEnd", d).value,
          date_from: $("#rFrom", d).value || null, date_to: $("#rTo", d).value || null, enabled: $("#rOn", d).checked,
        };
        try {
          if (rule) await api("PUT", `/api/rules/${rule.id}`, payload); else await api("POST", "/api/rules", payload);
          d.close();
          await loadAll();
          renderRules(); loadTimeline(); loadState();
          toast("Opgeslagen");
        } catch (err) { $("#rErr", d).textContent = err.message; }
      }
    },
  });
}

async function deleteRule(id) {
  const r = S.all.rules.find((x) => x.id === id);
  const ok = await confirmBox({ title: "Regel verwijderen?", text: `<b>${esc(r.name || queueById(r.queue_id)?.name || "Deze regel")}</b> (${fmtDays(r.days)}, ${fmtTimes(r)}) verdwijnt uit de planning.` });
  if (!ok) return;
  try {
    await api("DELETE", `/api/rules/${id}`);
    await loadAll(); renderRules(); loadTimeline(); loadState();
    toast("Verwijderd");
  } catch (e) { fail(e); }
}

async function saveSettings(changes, msg) {
  try {
    await api("PUT", "/api/settings", changes);
    await loadAll();
    loadState();
    if (S.view === "planning") { renderRules(); loadTimeline(); }
    toast(msg || "Opgeslagen");
    return true;
  } catch (e) { fail(e); return false; }
}

// =========================================================== INSTELLINGEN
function renderSettings() {
  const s = S.all.settings, info = S.all.info;
  view.innerHTML = `
  <div class="page-head"><div><h1>Instellingen</h1><p>Hoe VLC op de kiosk wordt gestart.</p></div></div>
  <div class="settings">
    <section class="panel">
      <h2>Weergave</h2>
      <form id="fVlc">
        <label class="field"><span>VLC-commando</span><input type="text" name="vlc_command" value="${esc(s.vlc_command)}" required>
          <p class="hint">Meestal <b>cvlc</b>. Alleen vlc of cvlc is toegestaan. Opties als volledig scherm en herhalen voegt Kiosk Player zelf toe.</p></label>
        <div class="grid2">
          <label class="field"><span>Display</span><input type="text" name="display" value="${esc(s.display)}" required><p class="hint">Net als DISPLAY=:0 in je ssh-commando.</p></label>
          <label class="field"><span>Afbeeldingen standaard in beeld</span><div class="row" style="flex-wrap:nowrap"><input type="number" name="default_image_duration" min="1" max="86400" value="${s.default_image_duration}" class="narrow"><span class="muted">seconden</span></div>
            <p class="hint">Per afbeelding aan te passen in een wachtrij.</p></label>
        </div>
        <label class="check"><input type="checkbox" name="kill_other_vlc" ${s.kill_other_vlc ? "checked" : ""}><span><b>Andere VLC-vensters sluiten</b><small>Bijvoorbeeld een VLC die je eerder met de hand via ssh startte</small></span></label>
        <label class="field"><span>Extra VLC-opties</span><input type="text" name="extra_args" value="${esc(s.extra_args)}" placeholder="Bijvoorbeeld: --no-audio --aspect-ratio=16:9">
          <p class="hint">Worden aan elk VLC-commando toegevoegd. Alleen opties die met -- beginnen. Laat leeg als je het niet zeker weet.</p></label>
        <label class="field"><span>Interne poort voor VLC-bediening</span><input type="number" name="vlc_http_port" min="1024" max="65535" value="${s.vlc_http_port}" class="narrow" style="width:120px">
          <p class="hint">Alleen bereikbaar op de kiosk zelf.</p></label>
        <div class="row"><button class="btn primary" type="submit">Opslaan</button><span class="muted small">VLC start daarna opnieuw.</span></div>
      </form>
    </section>
    <div class="stack">
      <section class="panel">
        <h2>Wachtwoord wijzigen</h2>
        <form id="fPw">
          <label class="field"><span>Huidig wachtwoord</span><input type="password" name="current" autocomplete="current-password" required></label>
          <div class="grid2">
            <label class="field"><span>Nieuw wachtwoord</span><input type="password" name="new" autocomplete="new-password" minlength="8" required></label>
            <label class="field"><span>Herhaal</span><input type="password" name="again" autocomplete="new-password" minlength="8" required></label>
          </div>
          <button class="btn" type="submit">Wachtwoord wijzigen</button>
        </form>
      </section>
      <section class="panel">
        <h2>Software-update</h2>
        <div id="upd" class="upd"><p class="muted">Laden…</p></div>
      </section>
      <section class="panel">
        <h2>Over deze kiosk</h2>
        <dl class="about">
          <dt>Versie</dt><dd>Kiosk Player ${esc(info.version)}</dd>
          <dt>Gebruiker</dt><dd>${esc(info.user)}</dd>
          <dt>Gegevensmap</dt><dd>${esc(info.data_dir)}</dd>
          <dt>Mediamap</dt><dd>${esc(info.data_dir)}/media</dd>
          <dt>Webpoort</dt><dd>${esc(info.port)}</dd>
          <dt>Max. upload</dt><dd>${esc(info.max_upload_gb)} GB per bestand</dd>
          <dt>ffmpeg</dt><dd>${info.ffmpeg ? "Geïnstalleerd" : "Niet gevonden (geen voorbeeldplaatjes)"}</dd>
        </dl>
      </section>
    </div>
  </div>`;
  $("#fVlc").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    await saveSettings({
      vlc_command: f.get("vlc_command"), display: f.get("display"),
      default_image_duration: +f.get("default_image_duration"), kill_other_vlc: f.get("kill_other_vlc") === "on",
      extra_args: f.get("extra_args"), vlc_http_port: +f.get("vlc_http_port"),
    }, "Instellingen opgeslagen");
  });
  $("#fPw").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    if (f.get("new") !== f.get("again")) { toast("De nieuwe wachtwoorden zijn niet gelijk", "error"); return; }
    try {
      await api("POST", "/api/password", { current: f.get("current"), new: f.get("new") });
      e.target.reset();
      toast("Wachtwoord gewijzigd");
    } catch (err) { fail(err); }
  });
  loadUpdate();
}

// ------------------------------------------------------------ software-update
const short = (sha) => (sha ? String(sha).slice(0, 7) : "–");
function fmtStamp(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("nl-NL", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
const versionLabel = (v) => (v && (v.sha || v.branch) ? `<b>${esc(v.branch || "?")}</b> · <code>${esc(short(v.sha))}</code>` : "Onbekend");
const updBusy = () => ["busy", "restarting"].includes(S.upd?.job?.status);

async function loadUpdate() {
  if (!$("#upd")) return;
  try {
    S.upd = await api("GET", "/api/update");
  } catch (e) { $("#upd").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  renderUpdate();
  if (updBusy()) { watchUpdate(); return; }
  if (S.upd.problem || S.updBranches) { if (S.updBranches) loadCommit(); return; }
  try {
    S.updBranches = await api("GET", "/api/update/branches");
    S.updErr = null;
    const names = S.updBranches.branches.map((b) => b.name);
    const inst = S.upd.installed.branch;
    if (!names.includes(S.updSel)) S.updSel = names.includes(inst) ? inst : S.updBranches.default || names[0];
  } catch (e) { S.updErr = e.message; }
  renderUpdate();
  loadCommit();
}

async function loadCommit() {
  const sel = S.updSel;
  if (!sel) return;
  S.updCommit = null;
  renderUpdate();
  let c;
  try { c = await api("GET", `/api/update/commit?branch=${enc(sel)}`); } catch (e) { c = { error: e.message }; }
  if (sel !== S.updSel) return;
  S.updCommit = c;
  renderUpdate();
}

function renderUpdate() {
  const el = $("#upd");
  if (!el || !S.upd) return;
  const u = S.upd, v = u.installed || {}, job = u.job || {}, last = u.last || {}, busy = updBusy();
  const banner = (kind, html) => `<div class="banner ${kind}"><p>${html}</p></div>`;
  const h = [`<dl class="about">
    <dt>Geïnstalleerd</dt><dd>${versionLabel(v)}${v.source === "install.sh" ? ' <span class="muted small">via install.sh</span>' : ""}</dd>
    ${v.message ? `<dt>Wijziging</dt><dd>${esc(v.message)}</dd>` : ""}
    ${v.installed_at ? `<dt>Sinds</dt><dd>${esc(fmtStamp(v.installed_at))}</dd>` : ""}
    <dt>Repository</dt><dd>${esc(u.repo)}</dd></dl>`];
  if (last.status === "rolled_back") h.push(banner("error", `De update naar <b>${esc(last.failed_branch)}</b> (${esc(short(last.failed_sha))}) startte niet. De vorige versie is automatisch teruggezet.`));
  if (last.status === "failed_no_backup") h.push(banner("error", "De nieuwe versie start niet goed en er was geen vorige versie om terug te zetten. Bekijk op de kiosk <code>journalctl -u kiosk-player</code>."));
  if (job.status === "error") h.push(banner("error", `<b>Update mislukt.</b> ${esc(job.error)}`));
  if (busy) h.push(banner("", `<b>${esc(job.step || "Bezig")}…</b><br><span class="small">Na het installeren herstart Kiosk Player. Het scherm is dan ongeveer 10 seconden zwart.</span>`));
  if (u.problem) {
    h.push(banner("warn", esc(u.problem)));
    el.innerHTML = h.join("");
    return;
  }
  const prev = v.previous ? ` (${esc(v.previous.branch || "?")} ${esc(short(v.previous.sha))})` : "";
  const back = u.rollback_available ? `<button class="btn ghost" type="button" data-act="upd-back" ${busy ? "disabled" : ""}>Vorige versie terugzetten${prev}</button>` : "";
  if (S.updErr) h.push(`<p class="muted small">${esc(S.updErr)}</p>`);
  if (S.updBranches) {
    const br = S.updBranches;
    const opts = br.branches.map((b) => `<option value="${esc(b.name)}" ${b.name === S.updSel ? "selected" : ""}>${esc(b.name)}${b.name === br.default ? " (standaard)" : ""}${b.name === v.branch ? " (geïnstalleerd)" : ""}</option>`).join("");
    h.push(`<label class="field"><span>Branch</span><select id="updBranch" ${busy ? "disabled" : ""}>${opts}</select>
      <p class="hint">Kies een andere branch om een testversie te proberen. Met <b>Vorige versie terugzetten</b> ga je daarna terug.</p></label>`);
    const c = S.updCommit;
    if (!c) h.push(`<p class="muted small">Laatste versie ophalen…</p>`);
    else if (c.error) h.push(`<p class="muted small">${esc(c.error)}</p>`);
    else {
      const cmp = c.compare;
      let rel = "";
      if (c.same) rel = "Dit is de versie die nu draait.";
      else if (cmp?.status === "ahead") rel = `${plural(cmp.ahead_by, "nieuwe wijziging", "nieuwe wijzigingen")} ten opzichte van wat nu draait.`;
      else if (cmp?.status === "behind") rel = `Ouder dan wat nu draait: ${plural(cmp.behind_by, "wijziging", "wijzigingen")} terug.`;
      else if (cmp?.status === "diverged") rel = `Een andere tak: ${cmp.ahead_by} nieuw, ${cmp.behind_by} van wat nu draait zit er niet in.`;
      h.push(`<p class="small">Laatste versie: <code>${esc(short(c.sha))}</code> ${esc(c.message)}<br><span class="muted">${esc(c.author || "")}${c.date ? ` · ${esc(fmtStamp(c.date))}` : ""}</span>${rel ? `<br>${rel}` : ""}</p>`);
    }
    const ready = c && !c.error;
    const label = ready && c.same ? "Opnieuw installeren" : S.updSel === br.default ? "Bijwerken" : "Deze versie testen";
    h.push(`<div class="row"><button class="btn ${ready && c.same ? "" : "primary"}" type="button" data-act="upd-go" ${busy || !ready ? "disabled" : ""}>${label}</button>${back}
      <button class="btn ghost small" type="button" data-act="upd-refresh" ${busy ? "disabled" : ""}>Vernieuwen</button></div>`);
  } else if (back) h.push(`<div class="row">${back}</div>`);
  el.innerHTML = h.join("");
  $("#updBranch")?.addEventListener("change", (e) => { S.updSel = e.target.value; loadCommit(); });
}

async function startUpdate() {
  const sel = S.updSel, c = S.updCommit, isDefault = sel === S.updBranches?.default;
  const ok = await confirmBox({
    title: isDefault ? "Kiosk Player bijwerken?" : "Testversie installeren?",
    text: `Kiosk Player installeert <b>${esc(sel)}</b> (${esc(short(c?.sha))}) en herstart daarna. Het scherm is ongeveer 10 seconden zwart.${isDefault ? "" : "<br><br>Dit is niet de standaardbranch. Met <b>Vorige versie terugzetten</b> ga je terug."}`,
    ok: isDefault ? "Bijwerken" : "Installeren", danger: false,
  });
  if (!ok) return;
  try { await api("POST", "/api/update", { branch: sel }); } catch (e) { fail(e); return; }
  watchUpdate();
}

async function rollbackUpdate() {
  const p = S.upd?.installed?.previous;
  const ok = await confirmBox({
    title: "Vorige versie terugzetten?",
    text: `Kiosk Player gaat terug naar ${p ? `<b>${esc(p.branch || "?")}</b> (${esc(short(p.sha))})` : "de vorige versie"} en herstart daarna. Het scherm is ongeveer 10 seconden zwart.`,
    ok: "Terugzetten", danger: false,
  });
  if (!ok) return;
  try { await api("POST", "/api/update/rollback"); } catch (e) { fail(e); return; }
  watchUpdate();
}

async function watchUpdate() {
  if (S.updWatch) return;
  S.updWatch = true;
  const before = S.upd?.installed?.installed_at, t0 = Date.now();
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  try {
    while (Date.now() - t0 < 180000) {
      await wait(1500);
      let u;
      try { u = await api("GET", "/api/update"); } catch { continue; } // herstart: even onbereikbaar
      if (u.installed?.installed_at !== before && !["busy", "restarting"].includes(u.job.status)) {
        toast("Kiosk Player is opnieuw gestart");
        setTimeout(() => location.reload(), 800);
        return;
      }
      S.upd = u;
      if (S.view === "instellingen") renderUpdate();
      if (!["busy", "restarting"].includes(u.job.status)) return;
    }
    toast("De update duurt erg lang. Kijk op de kiosk met: journalctl -u kiosk-player", "error");
  } finally { S.updWatch = false; }
}

// =============================================================== acties
view.addEventListener("click", async (e) => {
  const t = e.target.closest("[data-act]");
  if (!t || t.disabled) return;
  const act = t.dataset.act, id = t.dataset.id;
  switch (act) {
    // nu
    case "prev": case "next": case "pause": case "play": case "stop": case "restart": case "resume":
      return playerAction(act);
    case "start": return playerAction("start", { queue_id: id });
    case "sched-on":
      try { await api("POST", "/api/scheduler", { enabled: true }); await loadAll(); loadState(); } catch (err) { fail(err); }
      return;
    // media
    case "pick": return $("#fileIn").click();
    case "filter":
      S.mediaFilter = t.dataset.v;
      t.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === t));
      return renderMediaGrid();
    case "preview": return previewMedia(t.dataset.name);
    case "del-media": return deleteMedia(t.dataset.name);
    // wachtrijen
    case "sel":
      if (id === S.queueSel) return;
      if (S.dirty && !(await confirmBox({ title: "Wijzigingen weggooien?", text: "Je hebt deze wachtrij aangepast maar nog niet opgeslagen.", ok: "Weggooien" }))) return;
      selectQueue(id);
      return renderQueues();
    case "loop":
      S.draft.loop = t.dataset.v === "1";
      t.parentElement.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", b === t));
      $("#loopHint").textContent = S.draft.loop ? "Begint na het laatste item weer bij het eerste." : "Na het laatste item gaat de planning verder, of speelt de standaardwachtrij.";
      return markDirty();
    case "add-media": return pickMedia();
    case "up": case "down": {
      const i = +t.dataset.i, j = act === "up" ? i - 1 : i + 1;
      const items = S.draft.items;
      [items[i], items[j]] = [items[j], items[i]];
      markDirty(); renderItems();
      $(`[data-act="${act}"][data-i="${j}"]`)?.focus();
      return;
    }
    case "rm":
      S.draft.items.splice(+t.dataset.i, 1);
      markDirty(); return renderItems();
    case "q-save": return saveQueue();
    case "q-play":
      if ((S.dirty || !S.draft.id) && !(await saveQueue())) return;
      if (!S.draft.items.length) { toast("Deze wachtrij is leeg", "error"); return; }
      await playerAction("start", { queue_id: S.draft.id });
      toast(`${S.draft.name} staat op het scherm`);
      return;
    case "q-dup":
      try {
        const r = await api("POST", `/api/queues/${S.draft.id}/duplicate`);
        await loadAll(); selectQueue(r.queue.id); renderQueues(); toast("Kopie gemaakt");
      } catch (err) { fail(err); }
      return;
    case "q-del": return deleteQueue();
    // planning
    case "wk":
      S.week = t.dataset.v === "0" ? D.monday(serverNow().date) : D.add(S.week, +t.dataset.v);
      S.timeline = null;
      renderSched();
      return loadTimeline();
    case "new-rule": return ruleDialog(null);
    case "edit-rule": return ruleDialog(S.all.rules.find((r) => r.id === id));
    case "del-rule": return deleteRule(id);
    // software-update
    case "upd-go": return startUpdate();
    case "upd-back": return rollbackUpdate();
    case "upd-refresh":
      S.updBranches = null; S.updCommit = null;
      return loadUpdate();
  }
});

// ================================================================ router
const VIEWS = { nu: renderNu, media: renderMedia, wachtrijen: renderQueues, planning: renderPlanning, instellingen: renderSettings };
function route() {
  let v = location.hash.slice(1) || "nu";
  if (!VIEWS[v]) v = "nu";
  if (S.view === "wachtrijen" && v !== "wachtrijen" && S.dirty) {
    if (!window.confirm("Je wachtrij heeft niet opgeslagen wijzigingen. Toch weggaan?")) {
      history.replaceState(null, "", "#wachtrijen");
      return;
    }
    S.dirty = false;
    selectQueue(S.queueSel === "new" ? null : S.queueSel);
  }
  if (v === S.view && view.childElementCount) return;
  S.view = v;
  document.querySelectorAll(".tabs a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === `#${v}` ? "page" : "false"));
  VIEWS[v]();
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", (e) => { if (S.dirty || S.uploading) e.preventDefault(); });
$("#logout").addEventListener("click", async () => { await api("POST", "/api/logout").catch(() => {}); location.href = "/login"; });

(async function init() {
  try {
    await Promise.all([loadAll(), loadMedia(), loadState()]);
  } catch (e) { fail(e); return; }
  selectQueue(queues()[0]?.id || null);
  route();
  tickClock();
  setInterval(() => { tickClock(); if (S.view === "nu") updateTimecode(); }, 1000);
  setInterval(() => { if (!document.hidden) loadState(); }, 2500);
  setInterval(() => { if (!document.hidden && S.view === "nu") loadEvents(); }, 5000);
  setInterval(() => { if (!document.hidden && S.view === "planning") { renderSched(); } }, 60000);
  setInterval(async () => { if (!document.hidden && S.view === "nu") { await loadMedia().catch(() => {}); } }, 30000);
})();
