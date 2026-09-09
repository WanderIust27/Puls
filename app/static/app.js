/* PULS Frontend — Vanilla JS, keine Abhängigkeiten. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const SPORT_KIND = { running: "Lauf", strength: "Gym", cardio: "Cardio",
  mobility: "Yoga", other: "Sonst", hiit: "HIIT" };
const SPORT_CLASS = { running: "run", strength: "gym", cardio: "run",
  mobility: "yoga", other: "", hiit: "gym" };
function kindTag(sport) {
  return `<div class="kind ${SPORT_CLASS[sport] || ""}">${SPORT_KIND[sport] || "–"}</div>`;
}
const STEP_LABEL = { warmup: "Aufwärmen", cooldown: "Auslaufen", work: "Belastung", recovery: "Erholung", rest: "Pause" };
const SPORT_LABEL = { running: "Laufen", strength: "Kraft", cardio: "Cardio", mobility: "Mobilität", other: "Sonstiges", hiit: "HIIT" };
const GOALS = [
  ["muscle", "Muskelaufbau"], ["endurance", "Ausdauer"],
  ["general", "Fitness & Routine"], ["weight_gain", "Gewicht zunehmen"],
  ["weight_loss", "Gewicht abnehmen"],
];

/* ------------------------------------------------------------------ Utils */

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* egal */ }
    throw new Error(msg);
  }
  return res.json();
}


/* Das Modell schreibt Markdown — **fett**, Listen, Absätze. Ungerendert steht
   das als Sternchen im Text. Hier wird nur das übersetzt, was tatsächlich
   vorkommt; alles andere bleibt Text. Der Eingabetext wird vorher maskiert,
   damit aus einer Modellantwort kein Markup werden kann. */
function mdToHtml(text) {
  if (!text) return "";
  const lines = esc(String(text)).split(/\r?\n/);
  const out = [];
  let list = null;

  const inline = (t) => t
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:!?)]|$)/g, "$1<em>$2</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");

  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) { closeList(); continue; }

    const heading = line.match(/^#{1,4}\s+(.*)$/);
    if (heading) { closeList(); out.push(`<h4>${inline(heading[1])}</h4>`); continue; }

    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    if (numbered) {
      if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
      out.push(`<li>${inline(numbered[1])}</li>`);
      continue;
    }
    closeList();
    out.push(`<p>${inline(line)}</p>`);
  }
  closeList();
  return out.join("");
}

function toast(msg, err = false) {
  const el = document.createElement("div");
  el.className = "toast" + (err ? " err" : "");
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), err ? 5200 : 2800);
}

async function withSpinner(btn, fn) {
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Moment …';
  try { return await fn(); }
  catch (e) { toast(e.message || String(e), true); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}

function fmtDur(s) {
  if (!s) return "–";
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h}:${String(m).padStart(2, "0")} h` : `${m} min`;
}
function fmtDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "short" });
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ------------------------------------------------------------------ Charts
   Handgebaute SVG-Charts: eine Serie pro Chart, Tooltip beim Hover,
   dezente Achsen, Tabellenansicht für Screenreader/Nachlesen. */

const tooltip = $("#tooltip");
function showTip(x, y, html) {
  tooltip.innerHTML = html;
  tooltip.style.left = x + "px";
  tooltip.style.top = y + "px";
  tooltip.style.display = "block";
}
function hideTip() { tooltip.style.display = "none"; }

function barChart(container, points, { color = "var(--accent)", unit = "" } = {}) {
  const W = 720, H = 170, padL = 34, padB = 22, padT = 8;
  const max = Math.max(1, ...points.map((p) => p.value));
  const iw = (W - padL - 8) / points.length;
  const bw = Math.max(2, Math.min(9, iw - 3));
  let bars = "", labels = "";
  points.forEach((p, i) => {
    const h = Math.round(((H - padB - padT) * p.value) / max);
    const x = padL + i * iw + (iw - bw) / 2;
    const y = H - padB - h;
    bars += `<rect data-i="${i}" x="${x.toFixed(1)}" y="${h ? y : H - padB - 1}" width="${bw.toFixed(1)}"
      height="${Math.max(h, p.value ? 2 : 1)}" rx="1" fill="${p.value ? color : "var(--border)"}"></rect>`;
    if (p.label) labels += `<text x="${(x + bw / 2).toFixed(1)}" y="${H - 6}" font-size="10"
      fill="var(--ink-3)" text-anchor="middle">${p.label}</text>`;
  });
  const grid = [0.5, 1].map((f) => {
    const y = H - padB - (H - padB - padT) * f;
    return `<line x1="${padL}" y1="${y}" x2="${W - 4}" y2="${y}" stroke="var(--border)" stroke-width="1"></line>
      <text x="2" y="${y + 3}" font-size="10" fill="var(--ink-3)">${Math.round(max * f)}</text>`;
  }).join("");
  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">${grid}${bars}${labels}</svg>`;
  container.querySelectorAll("rect").forEach((r) => {
    r.addEventListener("pointerenter", (ev) => {
      const p = points[+r.dataset.i];
      const rect = r.getBoundingClientRect();
      showTip(rect.left + rect.width / 2, rect.top,
        `<span class="t-label">${esc(p.tip || p.label || "")}</span><br><b>${p.value}${unit}</b>`);
    });
    r.addEventListener("pointerleave", hideTip);
  });
}

function lineChart(container, points, { color = "var(--teal)", unit = "" } = {}) {
  if (!points.length) { container.innerHTML = '<p class="muted">Noch keine Daten.</p>'; return; }
  const W = 720, H = 170, padL = 40, padB = 20, padT = 10, padR = 10;
  const vals = points.map((p) => p.value);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (max - min < 1) { min -= 0.5; max += 0.5; }
  const span = max - min;
  min -= span * 0.1; max += span * 0.1;
  const X = (i) => padL + (i * (W - padL - padR)) / Math.max(1, points.length - 1);
  const Y = (v) => H - padB - ((v - min) * (H - padB - padT)) / (max - min);
  const path = points.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`).join(" ");
  const area = `${path} L${X(points.length - 1).toFixed(1)},${H - padB} L${padL},${H - padB} Z`;
  const grid = [min + (max - min) * 0.15, (min + max) / 2, max - (max - min) * 0.15].map((v) =>
    `<line x1="${padL}" y1="${Y(v)}" x2="${W - padR}" y2="${Y(v)}" stroke="var(--border)"></line>
     <text x="2" y="${Y(v) + 3}" font-size="10" fill="var(--ink-3)">${v.toFixed(1)}</text>`).join("");
  const first = points[0], last = points[points.length - 1];
  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img">
    ${grid}
    <path d="${area}" fill="${color}" opacity="0.07"></path>
    <path d="${path}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"></path>
    <circle cx="${X(points.length - 1)}" cy="${Y(last.value)}" r="3" fill="${color}"></circle>
    <text x="${W - padR}" y="${Math.max(12, Y(last.value) - 8)}" font-size="11" font-weight="700"
      fill="var(--ink)" text-anchor="end">${last.value}${unit}</text>
    <text x="${padL}" y="${H - 4}" font-size="10" fill="var(--ink-3)">${esc(first.label || "")}</text>
    <text x="${W - padR}" y="${H - 4}" font-size="10" fill="var(--ink-3)" text-anchor="end">${esc(last.label || "")}</text>
    <rect id="hover" x="${padL}" y="0" width="${W - padL - padR}" height="${H}" fill="transparent"></rect>
  </svg>`;
  const svg = container.querySelector("svg");
  const hover = svg.querySelector("#hover");
  hover.addEventListener("pointermove", (ev) => {
    const box = svg.getBoundingClientRect();
    const relX = ((ev.clientX - box.left) / box.width) * W;
    const i = Math.round(((relX - padL) / (W - padL - padR)) * (points.length - 1));
    const p = points[Math.max(0, Math.min(points.length - 1, i))];
    if (!p) return;
    showTip(ev.clientX, box.top + (Y(p.value) / H) * box.height,
      `<span class="t-label">${esc(p.tip || p.label || "")}</span><br><b>${p.value}${unit}</b>`);
  });
  hover.addEventListener("pointerleave", hideTip);
}

function ringChart(svg, count, target) {
  const r = 42, c = 2 * Math.PI * r;
  const frac = Math.min(1, target ? count / target : 0);
  svg.innerHTML = `
    <circle cx="48" cy="48" r="${r}" fill="none" stroke="var(--surface-2)" stroke-width="3"></circle>
    <circle cx="48" cy="48" r="${r}" fill="none" stroke="var(--accent)" stroke-width="3"
      stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - frac)}"
      style="transition: stroke-dashoffset .6s ease"></circle>`;
}

/* --------------------------------------------------------------- Dashboard */


function renderComposition(c) {
  const box = $("#compRow");
  if (!box) return;
  if (!c || !c.latest) {
    box.innerHTML = '<div class="muted" style="grid-column:1/-1">Noch keine Messung.</div>';
    return;
  }
  const l = c.latest, d = c.delta || {};
  const cell = (value, unit, label, delta, betterUp) => {
    if (value === null || value === undefined) return "";
    let dTxt = "", cls = "";
    if (delta !== null && delta !== undefined && Math.abs(delta) >= 0.05) {
      const up = delta > 0;
      cls = (up === betterUp) ? "up" : "down";
      dTxt = `${up ? "+" : ""}${delta.toFixed(1)} ${unit} in 30 Tagen`;
    }
    return `<div class="comp">
      <div class="v">${value}<small> ${unit}</small></div>
      <div class="l">${label}</div>
      ${dTxt ? `<div class="d ${cls}">${dTxt}</div>` : ""}
    </div>`;
  };
  const cells = [
    cell(l.weight_kg, "kg", "Gewicht", d.weight_kg, true),
    cell(l.body_fat_pct, "%", "Körperfett", d.body_fat_pct, false),
    cell(l.muscle_kg, "kg", "Muskelmasse", d.muscle_kg, true),
    cell(l.water_pct, "%", "Wasser", d.water_pct, true),
  ].filter(Boolean);
  box.innerHTML = cells.join("");
  if (!l.body_fat_pct) {
    box.innerHTML += `<div class="muted" style="grid-column:1/-1;margin-top:4px">
      Nur das Gewicht angekommen. Körperfett misst die Waage lediglich bei
      barfüßigem Kontakt — Socken aus und ein paar Sekunden ruhig stehen bleiben.</div>`;
  }
}

function renderGoals(gp) {
  if (!gp) return;
  const run = gp.run || {};
  if (run.predicted_text) {
    $("#goalRunNow").textContent = run.predicted_text;
    const pct = Math.max(0, Math.min(100, run.progress_pct || 0));
    const bar = $("#goalRunBar");
    bar.style.width = pct + "%";
    bar.classList.toggle("done", !!run.reached);
    $("#goalRunHint").textContent = run.verdict || "";
  } else {
    $("#goalRunNow").textContent = "\u2013";
    $("#goalRunHint").innerHTML = 'Noch nicht kalibriert — <a href="#" data-goto="plan" style="color:var(--accent)">Benchmark-Lauf machen</a>.';
  }
  const pu = gp.pullup || {};
  if (pu.best) {
    $("#goalPullNow").textContent = `${pu.best} / ${pu.goal}`;
    const pct = Math.max(0, Math.min(100, (pu.best / pu.goal) * 100));
    const bar = $("#goalPullBar");
    bar.style.width = pct + "%";
    bar.classList.toggle("done", pu.best >= pu.goal);
    $("#goalPullHint").textContent = pu.hint || "";
  } else {
    $("#goalPullNow").textContent = `? / ${pu.goal || 10}`;
    $("#goalPullHint").innerHTML = 'Trag dein Maximum ein \u2014 <a href="#" data-goto="plan" style="color:var(--accent)">unter Kalibrierung</a>.';
  }
}



async function loadDashboard() {
  loadSupplements();
  const d = await api("/dashboard");
  renderScore(d.score);
  renderRecentActivities(d.recent_activities);
  renderSleepAndHeart(d.recovery);
  renderSuggestions(d.suggestions);
  renderToday(d.today);
  renderTodayTiles(d.recovery);
  renderBoosters(d.boosters);
  renderFeedback(d.pending_feedback);
  renderInsights(d.insights);
  loadReadout();
  loadMemory();

  ringChart($("#weekRing"), d.week.workouts, d.week.target);
  $("#ringCount").textContent = d.week.workouts;
  $("#ringTarget").textContent = d.week.target;
  $("#statStreak").textContent = d.streak_weeks;
  $("#statDuration").innerHTML = fmtDur(d.week.duration_s);
  $("#statAcwr").textContent = d.acwr ?? "–";
  $("#statAcwr").style.color = d.acwr > 1.5 ? "var(--bad)" : d.acwr >= 0.8 ? "var(--good)" : "var(--ink)";
  $("#statReadiness").textContent = d.latest_daily?.training_readiness ?? "–";

  if (d.coach_message) {
    $("#coachMessage").innerHTML = esc(d.coach_message.content) +
      `<div class="when">${fmtDate(d.coach_message.created_at)}</div>`;
  }
  if (d.research_tip) {
    $("#researchTip").innerHTML = `<b>${esc(d.research_tip.topic || "")}</b><br>${esc(d.research_tip.content)}`;
  }

  barChart($("#loadChart"), d.load_series.map((p, i) => ({
    value: Math.round(p.load), tip: `${p.day} · ${p.count} Training(s)`,
    label: i % 7 === 0 ? p.day.slice(8) + "." + p.day.slice(5, 7) : "",
  })));

  renderComposition(d.body_composition);

  const ws = d.weight_series.map((p) => ({ value: p.weight_kg, label: p.day.slice(5), tip: p.day }));
  lineChart($("#weightChart"), ws, { unit: " kg" });
  if (ws.length >= 2) {
    const diff = (ws[ws.length - 1].value - ws[0].value).toFixed(1);
    $("#weightDelta").textContent =
      `${diff > 0 ? "+" : ""}${diff} kg seit ${fmtDate(d.weight_series[0].day)}` +
      (d.goals.includes("weight_gain") && diff > 0 ? " — geht in die richtige Richtung" : "");
  }

  // Heute anstehende Einheiten
  const today = new Date().toISOString().slice(0, 10);
  const todays = d.upcoming_workouts.filter((w) => w.planned_date === today);
  $("#todayList").innerHTML = todays.length ? todays.map((w) => `
    <div class="list-item">
      ${kindTag(w.sport)}
      <div class="grow"><div class="title">${esc(w.name)}</div>
        <div class="meta">${esc(w.time_of_day || "")}${w.status === "pushed" ? " · auf der Uhr" : ""}</div></div>
      <button class="btn small ghost" data-done-today="${w.id}">Erledigt</button>
    </div>`).join("")
    : 'Nichts geplant \u2014 <a href="#" data-goto="plan" style="color:var(--accent)">Woche planen</a>.';
  $$("[data-done-today]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/workouts/${b.dataset.doneToday}`, { method: "PATCH",
      body: JSON.stringify({ status: "done" }) });
    toast("Erledigt"); loadDashboard();
  }));

  renderGoals(d.goal_progress);

  $("#upcomingList").innerHTML = d.upcoming_workouts.length
    ? '<div class="mini-list">' + d.upcoming_workouts.slice(0, 6).map((w) => `
      <div class="mini${w.planned_date && w.planned_date <= today ? " due" : ""}">
        ${kindTag(w.sport)}
        <div class="mt">${esc(w.name)}</div>
        <div class="mm">${w.status === "pushed" ? "auf der Uhr" : "geplant"}</div>
        <div class="mr">${w.planned_date ? esc(relDay(w.planned_date)) : "ohne Datum"}</div>
      </div>`).join("") + "</div>"
    : 'Keine geplant — lass dir eine <a href="#" data-goto="plan" style="color:var(--accent)">vom Coach bauen</a>.';

  const badge = $("#syncBadge");
  if (!d.garmin_linked) { badge.textContent = "Garmin nicht verbunden"; badge.className = ""; }
  else if (d.last_sync?.ok) { badge.textContent = "Sync " + new Date(d.last_sync.ts.replace(" ", "T") + "Z").toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }); badge.className = "ok"; }
  else { badge.textContent = "Sync-Fehler"; badge.className = "err"; }
}

$("#btnDaily").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/coach/daily", { method: "POST" });
  $("#coachMessage").innerHTML = mdToHtml(r.message);
}));
$("#btnRest").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/coach/rest", { method: "POST" });
  $("#coachMessage").innerHTML = mdToHtml(r.message);
}));
$("#btnResearch").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/coach/research", { method: "POST", body: "{}" });
  $("#researchTip").innerHTML = mdToHtml(r.tip);
}));
$("#syncBadge").addEventListener("click", async () => {
  try { toast("Sync läuft …"); const r = await api("/garmin/sync", { method: "POST" }); toast(r.ok ? "Sync fertig: " + r.detail : r.detail, !r.ok); loadDashboard(); }
  catch (e) { toast(e.message, true); }
});

/* ------------------------------------------------------------------- Plan */

const TOD_ORDER = { "morgens": 0, "abends": 1, "vor dem Schlafen": 2 };

function stepsToHtml(steps, depth = 0) {
  return (steps || []).map((s) => {
    if (s.type === "repeat") {
      return `<li>${s.count}× :<ul class="steps">${stepsToHtml(s.steps, depth + 1)}</ul></li>`;
    }
    const bits = [];
    if (s.reps) bits.push(s.reps + " Wdh.");
    if (s.duration_s) bits.push(Math.round(s.duration_s / 60 * 10) / 10 + " min");
    if (s.distance_m) bits.push((s.distance_m / 1000).toFixed(1) + " km");
    if (s.weight_kg) bits.push(s.weight_kg + " kg");
    if (s.pace_min_km) bits.push("Pace " + s.pace_min_km.join("–"));
    if (s.hr_zone) bits.push("HF-Zone " + s.hr_zone);
    return `<li>${esc(s.name || STEP_LABEL[s.type] || s.type)} — ${bits.join(", ") || "frei"}` +
      `${s.notes ? ` <span class="muted">(${esc(s.notes)})</span>` : ""}</li>`;
  }).join("");
}

function renderWeekGrid(workouts) {
  const today = new Date().toISOString().slice(0, 10);
  const byDay = {};
  workouts.forEach((w) => {
    const d = w.planned_date || "ohne Datum";
    (byDay[d] = byDay[d] || []).push(w);
  });
  const days = Object.keys(byDay).sort();
  if (!days.length) return '<p class="muted">Noch nichts geplant — tipp auf „Woche planen".</p>';
  return '<div class="week-grid">' + days.map((d) => {
    const items = byDay[d].sort((a, b) =>
      (TOD_ORDER[a.time_of_day] ?? 9) - (TOD_ORDER[b.time_of_day] ?? 9));
    const date = d === "ohne Datum" ? null : new Date(d);
    const wd = date ? date.toLocaleDateString("de-DE", { weekday: "short" }) : "–";
    const dm = date ? date.toLocaleDateString("de-DE", { day: "numeric", month: "numeric" }) : "";
    return `<div class="week-day ${d === today ? "today" : ""}">
      <div class="wd">${wd}<small>${dm}</small></div>
      <div class="week-items">${items.map((w) => `
        <div class="week-item">
          <span class="pill">${SPORT_KIND[w.sport] || ""}</span>
          <span class="tod">${esc(w.time_of_day || "")}</span>
          <span class="grow">${esc(w.name)}</span>
          ${w.status === "pushed" ? '<span class="pill">Uhr</span>' : ""}
        </div>`).join("")}</div>
    </div>`;
  }).join("") + "</div>";
}

async function loadPoses() {
  let d;
  try { d = await api("/yoga/poses"); } catch (e) { return; }
  $("#poseList").innerHTML = d.poses.map((p) => `
    <details class="pose">
      <summary><b style="color:var(--ink)">${esc(p.name)}</b>
        ${p.sanskrit ? `<span class="muted"> · ${esc(p.sanskrit)}</span>` : ""}
        <span class="muted"> · ${Math.round(p.duration_s / 60 * 10) / 10} min</span></summary>
      <div class="pose-body">
        ${p.focus ? `<div class="pose-focus">Wirkt auf: ${esc(p.focus)}</div>` : ""}
        <ol class="pose-steps">${(p.how || []).map((h) => `<li>${esc(h)}</li>`).join("")}</ol>
        ${p.cue ? `<div class="pose-cue">Auf der Uhr: „${esc(p.cue)}"</div>` : ""}
      </div>
    </details>`).join("");
}

async function loadPlan() {
  const [overview, workouts, bench] = await Promise.all([
    api("/plan/overview"), api("/workouts?limit=80"), api("/benchmark/status"),
  ]);

  const open = workouts.filter((w) => ["planned", "pushed"].includes(w.status));
  const wd = (arr) => (arr && arr.length ? arr.join(", ") : "keine");
  $("#weekStructure").innerHTML = `
    <div><b>Laufen</b> ${wd(overview.run_days)} · ${overview.run_minutes} min morgens</div>
    <div><b>Gym</b> ${wd(overview.gym_days)} · ${overview.gym_minutes} min abends</div>
    ${overview.evening_mobility ? "<div><b>Yoga</b> jeden Abend vor dem Schlafen</div>" : ""}
    <div style="margin-top:12px">Ziel: ${esc(overview.run_goal)}
      ${overview.calibrated ? `· locker ${overview.paces.easy}/km · Tempo ${overview.paces.tempo}/km` : "· noch nicht kalibriert"}</div>
    <div>Klimmzüge: ${overview.pullup_best ? `${overview.pullup_best} → Ziel ${overview.pullup_goal}` : `Ziel ${overview.pullup_goal}, Ausgangswert fehlt`}</div>
    <div style="margin-top:12px">${renderWeekGrid(open)}</div>`;

  const b = bench;
  const fmtLast = (x) => x.last ? `zuletzt vor ${x.days_ago} Tagen` : "noch nie";
  $("#benchmarkStatus").innerHTML = `
    <div>Lauf-Benchmark: ${fmtLast(b.run)}${b.run.due ? ' <span style="color:var(--warn)">— fällig</span>' : ""}
      ${b.run.cooper_distance_m ? `<br><span class="muted">${b.run.cooper_distance_m} m im Cooper-Test · locker ${b.run.paces.easy}/km</span>` : ""}</div>
    <div style="margin-top:6px">Kraft-Benchmark: ${fmtLast(b.strength)}${b.strength.due ? ' <span style="color:var(--warn)">— fällig</span>' : ""}</div>
    ${b.pullup_best ? `<div style="margin-top:6px">Klimmzug-Maximum: ${b.pullup_best}</div>` : ""}`;

  renderPlanned(open);
  loadPoses();
}

function renderPlanned(open) {
  $("#plannedList").innerHTML = open.length ? open.map((w) => `
    <div class="list-item" style="align-items:flex-start">
      ${kindTag(w.sport)}
      <div class="grow">
        <div class="title">${esc(w.name)}
          ${w.status === "pushed" ? '<span class="badge pushed">auf der Uhr</span>' : ""}</div>
        <div class="meta">${w.planned_date ? fmtDate(w.planned_date) : "kein Datum"}
          ${w.time_of_day ? " · " + esc(w.time_of_day) : ""} · ${SPORT_LABEL[w.sport] || w.sport}</div>
        ${w.description ? `<div class="muted">${esc(w.description)}</div>` : ""}
        <details><summary class="muted" style="cursor:pointer;font-size:12px;margin-top:4px">Ablauf anzeigen</summary>
          <ul class="steps">${stepsToHtml(w.steps)}</ul></details>
        <div class="ex-actions">
          ${w.status !== "pushed" ? `<button class="btn small teal" data-push="${w.id}">An Garmin</button>` : ""}
          <a class="btn small ghost" href="/api/workouts/${w.id}/fit" download>FIT</a>
          <button class="btn small ghost" data-done="${w.id}">Erledigt</button>
          <button class="btn small ghost" data-del="${w.id}">🗑</button>
        </div>
      </div>
    </div>`).join("") : "Nichts geplant.";

  $$("#plannedList [data-push]").forEach((b) => b.addEventListener("click", (e) =>
    withSpinner(e.currentTarget, async () => {
      await api(`/workouts/${b.dataset.push}/push`, {
        method: "POST", body: JSON.stringify({}) });
      toast("Ist auf dem Weg zu deiner Fenix");
      loadPlan();
    })));
  $$("#plannedList [data-done]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/workouts/${b.dataset.done}`, { method: "PATCH", body: JSON.stringify({ status: "done" }) });
    toast("Erledigt"); loadPlan();
  }));
  $$("#plannedList [data-del]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/workouts/${b.dataset.del}`, { method: "DELETE" }); loadPlan();
  }));
}

$("#btnPlanWeek").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/plan/week", { method: "POST", body: JSON.stringify({ replace: true }) });
  toast(`${r.count} Einheiten geplant`); loadPlan();
}));

$("#btnPushAll").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const workouts = await api("/workouts?limit=80");
  const todo = workouts.filter((w) => w.status === "planned");
  if (!todo.length) return toast("Nichts zu senden.");
  let ok = 0, failed = 0;
  for (const w of todo) {
    try { await api(`/workouts/${w.id}/push`, { method: "POST", body: JSON.stringify({}) }); ok++; }
    catch (err) { failed++; }
  }
  toast(`${ok} an Garmin gesendet${failed ? `, ${failed} fehlgeschlagen` : ""}`, failed > 0);
  loadPlan();
}));

$$("[data-run]").forEach((b) => b.addEventListener("click", (e) =>
  withSpinner(e.currentTarget, async () => {
    const r = await api("/plan/run", { method: "POST",
      body: JSON.stringify({ kind: b.dataset.run }) });
    toast(`„${r.name}" erstellt`); loadPlan();
  })));

$("#btnGymSession").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/plan/gym-session", { method: "POST" });
  toast(`„${r.name}" erstellt`); loadPlan();
}));

$("#btnYoga").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/plan/evening-yoga", { method: "POST" });
  toast(`„${r.name}" erstellt`); loadPlan();
}));

/* -------------------------------------------------------------- Benchmark */

$("#btnBenchRun").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/benchmark/run/create", { method: "POST" });
  toast("Benchmark-Lauf erstellt — schick ihn an die Uhr");
  loadPlan();
}));

$("#btnBenchStrength").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/benchmark/strength/create", { method: "POST" });
  toast("Kraft-Test erstellt — schick ihn an die Uhr");
  loadPlan();
}));

$("#btnCooperSave").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const m = +$("#cooperInput").value;
  if (!m || m < 500) return toast("Bitte die Distanz in Metern eintragen.", true);
  const r = await api("/benchmark/cooper", { method: "POST", body: JSON.stringify({ distance_m: m }) });
  const g = r.goal;
  const box = $("#benchResult");
  box.hidden = false;
  box.innerHTML = `
    <div class="big-num">VO₂max ≈ ${r.vo2max}</div>
    <div>Prognose ${g.distance_km} km: <b>${r.predicted_10k_text}</b>
      (Ziel ${g.time_min} min, ${g.required_pace}/km)</div>
    <div class="muted" style="margin-top:6px">${esc(g.verdict)}</div>
    <table>
      <tr><td>Locker / Grundlage</td><td>${r.paces.easy.text} /km</td></tr>
      <tr><td>Langer Lauf</td><td>${r.paces.long.text} /km</td></tr>
      <tr><td>Tempolauf (Schwelle)</td><td>${r.paces.tempo.text} /km</td></tr>
      <tr><td>Intervalle</td><td>${r.paces.interval.text} /km</td></tr>
    </table>
    <div class="muted" style="margin-top:8px">Alle künftigen Laufeinheiten bekommen diese Tempi als Vorgabe auf die Uhr.</div>`;
  toast("Laufprofil kalibriert");
  loadPlan();
}));

$("#btnPullupSave").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const reps = +$("#pullupInput").value;
  if (reps < 0 || $("#pullupInput").value === "") return toast("Bitte Anzahl eintragen.", true);
  const r = await api("/benchmark/pullup", { method: "POST", body: JSON.stringify({ reps }) });
  const box = $("#benchResult");
  box.hidden = false;
  box.innerHTML = `<div class="big-num">${r.max_reps} Klimmzüge</div>
    <div>${esc(r.focus)}</div>`;
  toast("Klimmzug-Plan angepasst");
  loadPlan();
}));

/* --------------------------------------------------------------- Übungen */

let exerciseData = { exercises: [], slot_labels: {}, muscle_labels: {}, equipment_labels: {} };
let editingId = null;
let setExerciseId = null;
let setFeeling = null;

function exTargetText(e) {
  if (e.mode === "time") return `${e.target_duration_s || 30}<small> s</small>`;
  const w = e.weight_kg ? `${e.weight_kg}<small> kg</small> × ` : "";
  return `${w}${e.target_reps}<small> Wdh.</small>`;
}

async function loadExercises() {
  exerciseData = await api("/exercises");
  renderExercises();
  loadActivityLog();
}

function renderExercises() {
  const filter = $("#slotFilter").value;
  const slots = ["cardio", "kettlebell", "pullup", "main", "stretch"];
  const list = exerciseData.exercises;
  let html = "";
  for (const slot of slots) {
    if (filter && filter !== slot) continue;
    const items = list.filter((e) => (e.slot || "main") === slot);
    if (!items.length) continue;
    html += `<div class="slot-head">${esc(exerciseData.slot_labels[slot] || slot)}</div>`;
    html += items.map((e) => `
      <div class="ex-card ${e.active ? "" : "inactive"}">
        <div class="ex-top">
          <div class="grow">
            <div class="name">${esc(e.name)}${e.active ? "" : " <span class='badge'>aus</span>"}</div>
            <div class="ex-meta">
              <span>${esc(exerciseData.muscle_labels[e.muscle_group] || e.muscle_group)}</span>
              <span>${esc(exerciseData.equipment_labels[e.equipment] || e.equipment)}</span>
              <span>${e.sets}×</span>
              ${e.mode === "reps" ? `<span>Spanne ${e.rep_min}–${e.rep_max}</span>` : ""}
              ${e.machine_setting ? `<span>${esc(e.machine_setting)}</span>` : ""}
              ${e.days_since !== null && e.days_since !== undefined
                ? `<span>vor ${e.days_since} T.</span>` : "<span>noch nie</span>"}
            </div>
          </div>
          <div class="ex-target">${exTargetText(e)}</div>
        </div>
        <div class="ex-actions">
          <button class="btn small ghost" data-ex-edit="${e.id}">Bearbeiten</button>
          <button class="btn small ghost" data-ex-set="${e.id}">Satz eintragen</button>
          <button class="btn small ghost" data-ex-hist="${e.id}">Verlauf</button>
        </div>
        <div class="ex-prog" id="exProg${e.id}"></div>
      </div>`).join("");
  }
  $("#exerciseList").innerHTML = html || '<p class="muted">Keine Übungen in diesem Block.</p>';

  $$("[data-ex-edit]").forEach((b) => b.addEventListener("click", () =>
    openExerciseDialog(+b.dataset.exEdit)));
  $$("[data-ex-set]").forEach((b) => b.addEventListener("click", () =>
    openSetDialog(+b.dataset.exSet)));
  $$("[data-ex-hist]").forEach((b) => b.addEventListener("click", async () => {
    const id = +b.dataset.exHist;
    const target = $("#exProg" + id);
    if (target.dataset.open === "1") { target.innerHTML = ""; target.dataset.open = "0"; return; }
    const h = await api(`/exercises/${id}/history`);
    const prog = h.progression.slice(0, 4).map((p) =>
      `<div>${fmtDate(p.ts)}: ${esc(p.reason || p.action)}</div>`).join("");
    const sets = h.sets.slice(0, 8).map((s) =>
      `<div>${fmtDate(s.day)} — Satz ${s.set_index}: ${s.reps ? s.reps + " Wdh." : ""}` +
      `${s.weight_kg ? " @ " + s.weight_kg + " kg" : ""}${s.duration_s ? Math.round(s.duration_s) + " s" : ""}` +
      ` <span class="muted">(${s.source})</span></div>`).join("");
    target.innerHTML = (prog || sets)
      ? `${prog}<div class="muted" style="margin-top:6px">${sets || "Noch keine Sätze."}</div>`
      : '<span class="muted">Noch nichts aufgezeichnet.</span>';
    target.dataset.open = "1";
  }));
}

$("#slotFilter").addEventListener("change", renderExercises);

function openExerciseDialog(id) {
  editingId = id;
  const e = id ? exerciseData.exercises.find((x) => x.id === id) : null;
  $("#exDialogTitle").textContent = e ? e.name : "Neue Übung";
  $("#exName").value = e?.name || "";
  $("#exMuscle").value = e?.muscle_group || "legs";
  $("#exEquipment").value = e?.equipment || "machine";
  $("#exSlot").value = e?.slot || "main";
  $("#exMode").value = e?.mode || "reps";
  $("#exWeight").value = e?.weight_kg ?? "";
  $("#exIncrement").value = e?.weight_increment ?? "";
  $("#exSets").value = e?.sets ?? 3;
  $("#exRepMin").value = e?.rep_min ?? 12;
  $("#exRepMax").value = e?.rep_max ?? 15;
  $("#exRest").value = e?.rest_s ?? 90;
  $("#exDuration").value = e?.target_duration_s ?? 30;
  $("#exSetting").value = e?.machine_setting || "";
  $("#exNotes").value = e?.notes || "";
  $("#exDelete").hidden = !id;
  $("#exTimeRow").hidden = $("#exMode").value !== "time";
  $("#exDialog").hidden = false;
}

$("#exMode").addEventListener("change", () => {
  $("#exTimeRow").hidden = $("#exMode").value !== "time";
});
$("#exCancel").addEventListener("click", () => { $("#exDialog").hidden = true; });
$("#exDialog").addEventListener("click", (e) => {
  if (e.target.id === "exDialog") $("#exDialog").hidden = true;
});

$("#exSave").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const body = {
    name: $("#exName").value.trim(),
    muscle_group: $("#exMuscle").value,
    equipment: $("#exEquipment").value,
    slot: $("#exSlot").value,
    mode: $("#exMode").value,
    weight_kg: $("#exWeight").value === "" ? null : +$("#exWeight").value,
    weight_increment: $("#exIncrement").value === "" ? null : +$("#exIncrement").value,
    sets: +$("#exSets").value || 3,
    rep_min: +$("#exRepMin").value || 12,
    rep_max: +$("#exRepMax").value || 15,
    rest_s: +$("#exRest").value || 90,
    target_duration_s: +$("#exDuration").value || null,
    machine_setting: $("#exSetting").value || null,
    notes: $("#exNotes").value || null,
  };
  if (!body.name) return toast("Name fehlt.", true);
  Object.keys(body).forEach((k) => body[k] === null && delete body[k]);
  if (editingId) await api(`/exercises/${editingId}`, { method: "PATCH", body: JSON.stringify(body) });
  else await api("/exercises", { method: "POST", body: JSON.stringify(body) });
  $("#exDialog").hidden = true;
  toast("Gespeichert");
  loadExercises();
}));

$("#exDelete").addEventListener("click", async () => {
  if (!editingId || !confirm("Übung wirklich löschen? Die aufgezeichneten Sätze gehen mit.")) return;
  await api(`/exercises/${editingId}`, { method: "DELETE" });
  $("#exDialog").hidden = true;
  toast("Gelöscht"); loadExercises();
});

$("#btnNewExercise").addEventListener("click", () => openExerciseDialog(null));

function openSetDialog(id) {
  setExerciseId = id;
  setFeeling = null;
  const e = exerciseData.exercises.find((x) => x.id === id);
  $("#setDialogTitle").textContent = e ? e.name : "Satz eintragen";
  $("#setReps").value = e?.target_reps ?? "";
  $("#setWeight").value = e?.weight_kg ?? "";
  $("#setIndex").value = 1;
  $$("#feelingRow [data-feeling]").forEach((b) => b.classList.remove("on"));
  $("#setDialog").hidden = false;
}

$$("#feelingRow [data-feeling]").forEach((b) => b.addEventListener("click", () => {
  setFeeling = b.dataset.feeling;
  $$("#feelingRow [data-feeling]").forEach((x) => x.classList.toggle("on", x === b));
}));

$("#setCancel").addEventListener("click", () => { $("#setDialog").hidden = true; });
$("#setDialog").addEventListener("click", (e) => {
  if (e.target.id === "setDialog") $("#setDialog").hidden = true;
});

$("#setSave").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/sets", { method: "POST", body: JSON.stringify({
    exercise_id: setExerciseId,
    reps: +$("#setReps").value || null,
    weight_kg: +$("#setWeight").value || null,
    set_index: +$("#setIndex").value || 1,
    feeling: setFeeling,
  }) });
  const next = (+$("#setIndex").value || 1) + 1;
  $("#setIndex").value = next;
  toast(`Satz ${next - 1} gespeichert`);
  loadExercises();
}));

$("#btnAddActivity").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/activities", { method: "POST", body: JSON.stringify({
    name: $("#actName").value || null, sport: $("#actSport").value,
    duration_min: +$("#actDur").value || null, distance_km: +$("#actDist").value || null,
    notes: $("#actNotes").value || null }) });
  $("#actName").value = $("#actDur").value = $("#actDist").value = $("#actNotes").value = "";
  toast("Training gespeichert"); loadExercises(); loadDashboard();
}));

$("#fitFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/activities/fit", { method: "POST", body: fd });
    toast(`Importiert: ${r.name} (${fmtDur(r.duration_s)})`); loadExercises(); loadDashboard(); }
  catch (err) { toast(err.message, true); }
  e.target.value = "";
});



/* --------------------------------------------------------- Laufanalyse */

const LEVEL_WORD = { good: "Gut", ok: "Okay", warn: "Achtung" };


function renderDetailFeedback(activityId, existing) {
  const box = $("#detailFeedback");
  if (!box) return;
  const draft = { rating: existing?.rating ?? null, effort: existing?.effort ?? null };
  const dots = (label, field) => `<div class="fb-scale"><span class="lb">${label}</span>
    ${[1, 2, 3, 4, 5].map((n) =>
      `<button class="dot${draft[field] === n ? " on" : ""}" data-dfb="${field}"
        data-value="${n}">${n}</button>`).join("")}</div>`;

  const paint = () => {
    box.innerHTML = dots("Wie war es?", "rating") + dots("Anstrengung", "effort") +
      `<input class="grow" id="detailNote" placeholder="Notiz (optional)"
        value="${esc(existing?.note || "")}">
       <div class="row" style="margin-top:6px">
         <button class="btn small" id="btnDetailFb">
           ${existing ? "Aktualisieren" : "Speichern"}</button>
       </div>`;
    $$("[data-dfb]").forEach((b) => b.addEventListener("click", () => {
      draft[b.dataset.dfb] = +b.dataset.value;
      paint();
    }));
    $("#btnDetailFb").addEventListener("click", (e) =>
      withSpinner(e.currentTarget, async () => {
        await api(`/activities/${activityId}/feedback`, { method: "POST",
          body: JSON.stringify({ ...draft,
            note: $("#detailNote").value.trim() || null }) });
        toast("Danke — das fließt in die Auswertung ein.");
        loadDashboard();
      }));
  };
  paint();
}

async function openRunAnalysis(activityId) {
  $("#runContent").innerHTML = '<p class="muted"><span class="spin"></span> Wird ausgewertet …</p>';
  $("#runDialog").hidden = false;

  /* Bewertung und Detaildaten parallel holen — die Detaildaten dürfen fehlen,
     ohne dass die Ansicht deswegen leer bleibt. */
  let d, det = null;
  try { d = await api(`/activities/${activityId}/analysis`); }
  catch (e) { $("#runContent").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  try { det = await api(`/activities/${activityId}/details`); }
  catch (e) { /* ohne Details geht es auch */ }

  const a = d.activity, an = d.analysis;
  const isGym = a.sport === "strength";
  $("#runDialogTitle").textContent = a.name || (isGym ? "Gym-Einheit" : "Laufanalyse");

  const km = a.distance_m ? (a.distance_m / 1000).toFixed(2) : null;
  const facts = (isGym ? [
    a.duration_s ? { v: fmtDur(a.duration_s), l: "Dauer" } : null,
    d.gym?.sets ? { v: d.gym.sets, l: "Sätze" } : null,
    d.gym?.volume_kg ? { v: Math.round(d.gym.volume_kg).toLocaleString("de-DE"), l: "Volumen kg" } : null,
    d.gym?.exercises ? { v: d.gym.exercises, l: "Übungen" } : null,
    a.avg_hr ? { v: Math.round(a.avg_hr), l: "Ø Puls" } : null,
    a.calories ? { v: Math.round(a.calories), l: "Kalorien" } : null,
  ] : [
    km ? { v: km, l: "Kilometer" } : null,
    a.duration_s ? { v: fmtDur(a.duration_s), l: "Dauer" } : null,
    an?.pace_text ? { v: an.pace_text, l: "Tempo /km" } : null,
    a.avg_hr ? { v: Math.round(a.avg_hr), l: "Ø Puls" } : null,
    a.max_hr ? { v: Math.round(a.max_hr), l: "Max Puls" } : null,
    a.avg_cadence ? { v: Math.round(a.avg_cadence), l: "Schritte/min" } : null,
    a.avg_stride_m ? { v: a.avg_stride_m.toFixed(2), l: "Schrittlänge m" } : null,
    a.elevation_gain ? { v: Math.round(a.elevation_gain), l: "Höhenmeter" } : null,
    a.ground_contact_ms ? { v: Math.round(a.ground_contact_ms), l: "Bodenkontakt ms" } : null,
    a.vertical_osc_cm ? { v: a.vertical_osc_cm.toFixed(1), l: "Vertikal cm" } : null,
    a.aerobic_te ? { v: a.aerobic_te.toFixed(1), l: "Trainingseffekt" } : null,
    a.avg_power ? { v: Math.round(a.avg_power), l: "Watt" } : null,
  ]).filter(Boolean);

  let html = "";
  if (an) {
    html += `<div class="run-verdict">
      <span class="badge ${an.level === "good" ? "done" : ""}">${LEVEL_WORD[an.level] || ""}</span>
      <span class="txt">${esc(an.verdict)}</span></div>`;
  }
  html += `<div class="run-facts">${facts.map((f) =>
    `<div class="f"><div class="v">${esc(String(f.v))}</div><div class="l">${f.l}</div></div>`
  ).join("")}</div>`;

  if (a.hr_zones) {
    const z = a.hr_zones;
    const total = Object.values(z).reduce((s, x) => s + Number(x), 0);
    if (total > 0) {
      html += '<div class="zone-bar">' + [1, 2, 3, 4, 5].map((i) => {
        const pct = (Number(z[i] || 0) / total) * 100;
        return pct > 0 ? `<span class="z${i}" style="width:${pct}%"></span>` : "";
      }).join("") + "</div>";
      html += '<div class="zone-legend">' + [1, 2, 3, 4, 5].map((i) => {
        const pct = Math.round((Number(z[i] || 0) / total) * 100);
        return pct > 0 ? `<span>Zone ${i}: ${pct} %</span>` : "";
      }).join("") + "</div>";
    }
  }

  const hasTrack = det?.track?.length > 1;
  const hasSeries = det?.series?.t?.length > 1;
  const hasSplits = det?.splits?.length > 1;

  if (hasTrack) {
    html += `<div class="detail-section"><h4>Strecke</h4>
      <div id="runMap"></div>
      <label class="map-toggle"><input type="checkbox" id="mapTiles">
        Kartenhintergrund laden (fragt bei OpenStreetMap an)</label></div>`;
  }
  if (hasSeries) html += '<div class="detail-section"><h4>Verlauf</h4><div id="runProfile"></div></div>';
  if (hasSplits) html += '<div class="detail-section"><h4>Kilometer</h4><div id="runSplits"></div></div>';

  if (isGym && d.gym) {
    const g = d.gym;
    if (g.detail?.length) {
      html += '<div class="detail-section"><h4>Übungen</h4><div class="gym-list">' +
        g.detail.map((e) => {
          const sets = e.reps.map((r, i) => {
            const w = e.weights[i];
            return r == null ? "–" : `${r}${w ? `×${w} kg` : ""}`;
          }).join(" · ");
          const ch = e.change;
          const cls = !ch ? "" : ch.kind === "weight" || ch.kind === "reps" ? "up"
            : ch.kind === "hold" ? "hold" : "down";
          return `<div class="gym-ex">
            <div class="n">${esc(e.name)}</div>
            <div class="s">${esc(sets)}</div>
            ${ch ? `<div class="c ${cls}">${esc(ch.text)}</div>` : ""}
          </div>`;
        }).join("") + "</div></div>";
    }
    if (g.tips?.length) {
      html += '<div class="detail-section"><h4>Hinweise</h4>' + g.tips.map((t) =>
        `<div class="finding ${t.level}"><div class="d">${esc(t.text)}</div></div>`
      ).join("") + "</div>";
    }
  }

  if (an?.findings?.length) {
    html += '<div class="detail-section"><h4>Bewertung</h4>' + an.findings.map((f) => `
      <div class="finding ${f.level}">
        <div class="t">${esc(f.title)}${f.value ? ` — ${esc(f.value)}` : ""}</div>
        <div class="d">${esc(f.detail)}</div>
      </div>`).join("") + "</div>";
  } else if (!isGym) {
    html += '<p class="muted">Für eine Bewertung fehlen noch Daten. Nach dem nächsten Garmin-Sync klappt es.</p>';
  }

  if (det && !det.has_details && det.hint) {
    html += `<p class="muted">${esc(det.hint)}</p>`;
  }

  /* Rückmeldung direkt hier, nicht nur auf dem Dashboard — hier ist man
     ohnehin, wenn man über die Einheit nachdenkt. */
  html += `<div class="detail-section"><h4>Wie hat es sich angefühlt?</h4>
    <div id="detailFeedback"></div></div>`;
  $("#runContent").innerHTML = html;

  renderDetailFeedback(activityId, d.feedback);

  /* --- Diagramme zeichnen, nachdem das Gerüst im Dokument steht --- */
  let moveDot = null;
  if (hasTrack) {
    const paint = (tiles) => {
      moveDot = routeMap($("#runMap"), det.track, det.bounds, {
        tiles, values: det.series?.hr,
        /* Im breiten Fenster darf die Karte mehr Höhe bekommen — auf dem
           Handy bliebe sie sonst ein Briefschlitz. */
        height: window.innerWidth >= 900 ? 460 : 340,
      });
    };
    paint(localStorage.getItem("mapTiles") === "1");
    const box = $("#mapTiles");
    box.checked = localStorage.getItem("mapTiles") === "1";
    box.addEventListener("change", () => {
      localStorage.setItem("mapTiles", box.checked ? "1" : "0");
      paint(box.checked);
    });
  }

  if (hasSeries) {
    const tracks = [
      { key: "hr", label: "Puls", color: "var(--bad)", fill: true },
      { key: "pace", label: "Tempo", color: "var(--teal)",
        fmt: (v) => `${Math.floor(v / 60)}:${String(Math.round(v % 60)).padStart(2, "0")} /km`,
        fmtAxis: (v) => `${Math.floor(v / 60)}:${String(Math.round(v % 60)).padStart(2, "0")}` },
      { key: "ele", label: "Höhe", color: "var(--ink-3)", fill: true,
        fmt: (v) => `${Math.round(v)} m` },
      { key: "cadence", label: "Schrittfrequenz", color: "var(--accent)" },
    ];
    runProfile($("#runProfile"), det.series, {
      tracks,
      onHover: (i) => { if (moveDot) moveDot(i == null ? null : i / (det.series.t.length - 1)); },
    });
  }

  if (hasSplits) splitChart($("#runSplits"), det.splits);
}

$("#runClose").addEventListener("click", () => { $("#runDialog").hidden = true; });
$("#runDialog").addEventListener("click", (e) => {
  if (e.target.id === "runDialog") $("#runDialog").hidden = true;
});

/* --------------------------------------------------------------- Ernährung */

async function loadNutrition() {
  loadRecipes();
  loadMeals();
  const [list, s] = await Promise.all([api("/nutrition?days=14"), api("/settings")]);
  const kcalT = s.kcal_target, protT = s.protein_target;
  $("#nutTargetInfo").textContent = kcalT || protT
    ? `Ziel: ${kcalT ? kcalT + " kcal" : ""}${kcalT && protT ? " \u00b7 " : ""}${protT ? protT + " g Protein" : ""}`
    : "";
  $("#nutritionList").innerHTML = list.length ? `
    <table class="datatable"><tr><th>Tag</th><th>kcal</th><th>Protein</th><th></th></tr>
    ${list.map((n) => {
      const okK = kcalT && n.kcal ? (n.kcal >= kcalT * 0.95 ? "erreicht" : "") : "";
      return `<tr><td>${fmtDate(n.day)}</td><td>${n.kcal ?? "\u2013"}</td>
        <td>${n.protein_g ?? "\u2013"} g</td><td>${okK}</td></tr>`;
    }).join("")}</table>` : "Noch keine Eintr\u00e4ge.";
}

$("#btnSaveNutrition").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/nutrition", { method: "POST", body: JSON.stringify({
    day: $("#nutDay").value || null, kcal: +$("#nutKcal").value || null,
    protein_g: +$("#nutProt").value || null, notes: $("#nutNotes").value || null }) });
  toast("Gespeichert"); loadNutrition();
}));

$("#btnNutritionAdvice").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/coach/nutrition", { method: "POST" });
  $("#nutritionAdvice").innerHTML = mdToHtml(r.message);
}));

/* ------------------------------------------------------------------ K\u00f6rper */

async function loadBody() {
  const [summary, list] = await Promise.all([
    api("/body/summary?days=365"), api("/body?days=365"),
  ]);

  /* Kopfzeile: aktuelle Werte mit Veränderung */
  const arrow = (v) => v == null ? "" :
    `<span class="d ${v < 0 ? "down" : v > 0 ? "up" : ""}">${v > 0 ? "+" : ""}${v.toFixed(1)} kg</span>`;
  const l = summary.latest || {};
  const est = new Set(summary.estimated_fields || []);
  const cells = [
    { v: summary.current_kg?.toFixed(1), u: "kg", l: "Gewicht", extra: arrow(summary.delta_7d) },
    { v: l.body_fat_pct, u: "%", l: "Körperfett", f: "body_fat_pct" },
    { v: l.muscle_kg, u: "kg", l: "Muskeln", f: "muscle_kg" },
    { v: l.water_pct, u: "%", l: "Wasser", f: "water_pct" },
    { v: l.bone_kg, u: "kg", l: "Knochen", f: "bone_kg" },
    { v: l.visceral_fat, u: "", l: "Viszeralfett", f: "visceral_fat" },
    { v: l.bmi, u: "", l: "BMI" },
  ].filter((c) => c.v != null && c.v !== "");
  $("#bodyFacts").innerHTML = cells.map((c) => `
    <div class="f${est.has(c.f) ? " est" : ""}">
      <div class="v">${esc(String(c.v))}<span class="u">${c.u}</span></div>
      <div class="l">${c.l}${est.has(c.f) ? '<span title="aus der Impedanz geschätzt, nicht gemessen"> ≈</span>' : ""}</div>
      ${c.extra || ""}
    </div>`).join("") || '<p class="muted">Noch keine Messung.</p>';

  /* Trendlinie aus den Referenzmessungen */
  const points = (summary.points || [])
    .filter((p) => p.smooth_kg != null)
    .map((p) => ({ value: p.smooth_kg, label: p.day.slice(5),
                   tip: `${p.day}${p.measured ? "" : " (umgerechnet)"}` }));
  lineChart($("#bodyChart"), points, { unit: " kg" });

  const disc = summary.discipline || {};
  const deltas = [
    summary.delta_30d != null ? `30 Tage ${summary.delta_30d > 0 ? "+" : ""}${summary.delta_30d.toFixed(1)} kg` : null,
    summary.delta_90d != null ? `90 Tage ${summary.delta_90d > 0 ? "+" : ""}${summary.delta_90d.toFixed(1)} kg` : null,
  ].filter(Boolean).join(" · ");
  $("#bodyDiscipline").innerHTML = [
    deltas,
    disc.total ? `${disc.in_window} von ${disc.total} Messungen im Fenster ${esc(disc.window)}` : "",
    disc.factor && disc.factor !== 1 ? `Tagesgang auf dich kalibriert (Faktor ${disc.factor})` : "",
    disc.hint ? `<br>${esc(disc.hint)}` : "",
  ].filter(Boolean).join(" · ");

  /* Einzelmessungen — löschbar, mit Uhrzeit und Fenster-Kennzeichnung */
  $("#bodyList").innerHTML = list.length ? `
    <table class="datatable">
      <tr><th>Zeitpunkt</th><th>Gewicht</th><th>Fett %</th><th>Quelle</th><th></th></tr>
      ${list.slice(0, 30).map((b) => {
        const when = b.time_known
          ? `${fmtDate(b.day)}, ${b.measured_at.slice(11, 16)}`
          : `${fmtDate(b.day)} <span class="muted">(Zeit unbekannt)</span>`;
        const mark = b.in_window ? '<span class="in-win" title="im Referenzfenster">●</span> ' : "";
        const adj = !b.in_window && b.time_known && b.weight_adj_kg != null
          && Math.abs(b.weight_adj_kg - b.weight_kg) > 0.05
          ? ` <span class="muted">→ ${b.weight_adj_kg.toFixed(1)}</span>` : "";
        return `<tr>
          <td>${mark}${when}</td>
          <td>${b.weight_kg ?? "\u2013"} kg${adj}</td>
          <td>${b.body_fat_pct ?? "\u2013"}</td>
          <td>${b.source === "miscale" ? "Waage" : b.source === "garmin" ? "Garmin" : b.source}</td>
          <td><button class="link-del" data-del-body="${b.id}" title="Messung löschen">×</button></td>
        </tr>`;
      }).join("")}
    </table>
    <p class="muted">● = im Referenzfenster gemessen. Der Pfeil zeigt den auf das
      Fenster umgerechneten Wert.</p>` : "";

  $$("[data-del-body]").forEach((btn) => btn.addEventListener("click", async () => {
    if (!confirm("Diese Messung löschen?")) return;
    try {
      await api(`/body/${btn.dataset.delBody}`, { method: "DELETE" });
      toast("Gelöscht"); loadBody(); loadDashboard();
    } catch (e) { toast(e.message, true); }
  }));

  if (disc.window) {
    const [a, b] = disc.window.split("\u2013");
    if (a && b) { $("#winStart").value = a; $("#winEnd").value = b; }
  }
  return list;
}

$("#btnSaveBody").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const day = $("#bodyDay").value || null;
  const time = $("#bodyTime").value;
  await api("/body", { method: "POST", body: JSON.stringify({
    day,
    measured_at: day && time ? `${day}T${time}:00` : null,
    weight_kg: +$("#bodyWeight").value || null,
    body_fat_pct: +$("#bodyFat").value || null }) });
  toast("Gespeichert"); loadBody(); loadDashboard();
}));

$("#btnSaveWindow").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/body/window", { method: "POST", body: JSON.stringify({
    start: $("#winStart").value, end: $("#winEnd").value }) });
  toast(`Fenster ${r.window} — ${r.recomputed} Messungen neu eingeordnet`);
  loadBody();
}));

$("#bodyCsv").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("/body/import", { method: "POST", body: fd });
    toast(`${r.imported} Eintr\u00e4ge importiert`); loadBody(); }
  catch (err) { toast(err.message, true); }
  e.target.value = "";
});

/* ---------------------------------------------------- Verlaufs-Import */

let backfillTimer = null;

async function pollBackfill() {
  let st;
  try { st = await api("/garmin/backfill/status"); }
  catch (e) { return; }
  const box = $("#backfillProgress");
  if (!st.running && !st.summary && !st.error) { box.hidden = true; return; }
  box.hidden = false;

  const counted = Object.entries(st.counts || {})
    .filter(([, v]) => v).map(([k, v]) => `${v} ${k}`).join(" · ");

  if (st.error) {
    box.innerHTML = `<p class="muted">Abgebrochen: ${esc(st.error)}</p>` +
      (counted ? `<p class="muted">Vorher geladen: ${esc(counted)}</p>` : "");
  } else if (st.running) {
    box.innerHTML = `
      <div class="bf-head">
        <span>Schritt ${st.phase_no}/${st.phase_count}: ${esc(st.phase)}</span>
        <span>${st.percent} %</span>
      </div>
      <div class="bf-bar"><span style="width:${st.percent}%"></span></div>
      <p class="muted">${esc(st.detail || "")}${counted ? ` — ${esc(counted)}` : ""}</p>
      <button class="btn ghost small" id="btnBackfillCancel">Abbrechen</button>`;
    const cancel = $("#btnBackfillCancel");
    if (cancel) cancel.addEventListener("click", async () => {
      try { await api("/garmin/backfill/cancel", { method: "POST" });
        toast("Wird abgebrochen — das Geladene bleibt."); }
      catch (e) { toast(e.message, true); }
    });
  } else {
    box.innerHTML = `<p class="muted">${esc(st.summary || "Fertig.")}</p>`;
  }

  /* Solange etwas läuft, alle zwei Sekunden nachfragen. Die Phasen dauern
     unterschiedlich lang — ohne Nachfragen sähe es aus, als hinge es. */
  if (st.running && !backfillTimer) {
    backfillTimer = setInterval(pollBackfill, 2000);
  } else if (!st.running && backfillTimer) {
    clearInterval(backfillTimer); backfillTimer = null;
    loadDashboard();
  }
}

$("#btnBackfill").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/garmin/backfill", { method: "POST" });
  toast(r.status === "gestartet"
    ? "Verlauf wird geladen — das dauert ein paar Minuten."
    : "Der Import läuft bereits.");
  pollBackfill();
}));


/* ------------------------------------------------------ Gemütszustand */

const SCALE_WORDS = {
  mood: ["mies", "gedrückt", "geht so", "gut", "bestens"],
  energy: ["leer", "schlapp", "mittel", "frisch", "voll da"],
  stress: ["ruhig", "entspannt", "mittel", "angespannt", "am Anschlag"],
};
let moodScales = { mood: null, energy: null, stress: null };
let moodComplaints = [];
let moodMeta = { regions: {}, kinds: {} };

function renderScales() {
  $$(".scale").forEach((box) => {
    const key = box.dataset.scale;
    const value = moodScales[key];
    /* Das Wort steht UNTER den Punkten und hat feste Höhe — stünde es
       daneben, würde die Reihe bei jeder Auswahl verrutschen. */
    box.querySelector(".dots").innerHTML = [1, 2, 3, 4, 5].map((n) =>
      `<button class="dot${value === n ? " on" : ""}" data-scale-set="${key}"
        data-value="${n}" title="${SCALE_WORDS[key][n - 1]}">${n}</button>`
    ).join("");
    box.querySelector(".word").textContent = value ? SCALE_WORDS[key][value - 1] : "";
  });
  $$("[data-scale-set]").forEach((b) => b.addEventListener("click", () => {
    const key = b.dataset.scaleSet;
    /* Nochmal antippen hebt die Auswahl auf — nicht jeder Regler muss gesetzt sein */
    moodScales[key] = moodScales[key] === +b.dataset.value ? null : +b.dataset.value;
    renderScales();
  }));
}

/* Nur die Körperstellen, die im Alltag wirklich vorkommen — die vollständige
   Liste kommt über „mehr“. */
const QUICK_REGIONS = ["back_low", "neck", "shoulder", "knee", "thigh", "calf"];

function renderComplaintPicker(all = false) {
  const regions = all ? Object.keys(moodMeta.regions) : QUICK_REGIONS;
  $("#complaintPicker").innerHTML = regions.map((r) =>
    `<button class="chip" data-region="${r}">${esc(moodMeta.regions[r] || r)}</button>`
  ).join("") + (all ? "" :
    '<button class="chip ghost" id="moreRegions">mehr …</button>');

  $$("[data-region]").forEach((b) => b.addEventListener("click", () => pickKind(b.dataset.region)));
  const more = $("#moreRegions");
  if (more) more.addEventListener("click", () => renderComplaintPicker(true));
}

function pickKind(region) {
  const kinds = Object.entries(moodMeta.kinds);
  $("#complaintPicker").innerHTML =
    `<span class="muted" style="align-self:center">${esc(moodMeta.regions[region])}:</span>` +
    kinds.map(([k, label]) => `<button class="chip" data-kind="${k}">${esc(label)}</button>`).join("") +
    '<button class="chip ghost" id="cancelKind">zurück</button>';
  $$("[data-kind]").forEach((b) => b.addEventListener("click", () => {
    if (!moodComplaints.some((c) => c.region === region && c.kind === b.dataset.kind)) {
      moodComplaints.push({ region, kind: b.dataset.kind, severity: 2 });
    }
    renderChosen(); renderComplaintPicker();
  }));
  $("#cancelKind").addEventListener("click", () => renderComplaintPicker());
}

const SEVERITY_WORDS = ["", "leicht", "deutlich", "stark"];

function renderChosen() {
  $("#complaintChosen").innerHTML = moodComplaints.map((c, i) => `
    <span class="chip on">
      ${esc(moodMeta.regions[c.region])}: ${esc(moodMeta.kinds[c.kind])}
      <button class="sev" data-sev="${i}" title="Stärke ändern">${SEVERITY_WORDS[c.severity]}</button>
      <button class="x" data-drop="${i}" title="Entfernen">×</button>
    </span>`).join("");
  $$("[data-drop]").forEach((b) => b.addEventListener("click", () => {
    moodComplaints.splice(+b.dataset.drop, 1); renderChosen();
  }));
  $$("[data-sev]").forEach((b) => b.addEventListener("click", () => {
    const c = moodComplaints[+b.dataset.sev];
    c.severity = c.severity >= 3 ? 1 : c.severity + 1;
    renderChosen();
  }));
}

/* Freitext vom Modell lesen lassen — nur als Vorschlag. Erst nach einer Pause,
   damit nicht bei jedem Tastendruck eine Anfrage losgeht. */
let suggestTimer = null;
function watchNote() {
  clearTimeout(suggestTimer);
  const text = $("#moodNote").value.trim();
  if (text.length < 10) { $("#moodSuggest").hidden = true; return; }
  suggestTimer = setTimeout(async () => {
    let found = [];
    try { found = (await api("/mood/suggest", { method: "POST",
      body: JSON.stringify({ note: text }) })).complaints; }
    catch (e) { return; }
    const fresh = found.filter((f) =>
      !moodComplaints.some((c) => c.region === f.region));
    const box = $("#moodSuggest");
    if (!fresh.length) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = "Aus deiner Notiz gelesen: " + fresh.map((f, i) =>
      `<button class="chip" data-take="${i}">${esc(f.region_label)}: ${esc(f.kind_label)} +</button>`
    ).join(" ");
    $$("[data-take]").forEach((b) => b.addEventListener("click", () => {
      moodComplaints.push(fresh[+b.dataset.take]);
      renderChosen(); watchNote();
    }));
  }, 900);
}

async function loadMood() {
  loadRecovery();
  const d = await api("/mood?days=30");
  moodMeta = { regions: d.regions, kinds: d.kinds };
  renderScales(); renderComplaintPicker(); renderChosen();

  const pts = (d.trend.points || []);
  lineChart($("#moodChart"), pts.filter((p) => p.mood != null)
    .map((p) => ({ value: p.mood, label: p.day.slice(5), tip: p.day })), { unit: "/5" });

  $("#moodList").innerHTML = d.entries.length ? d.entries.slice(0, 20).map((e) => `
    <div class="mood-row">
      <div class="when">${fmtDate(e.day)}, ${e.recorded_at.slice(11, 16)}</div>
      <div class="vals">${[
        e.mood != null ? `Stimmung ${e.mood}` : null,
        e.energy != null ? `Energie ${e.energy}` : null,
        e.stress != null ? `Stress ${e.stress}` : null,
      ].filter(Boolean).join(" · ")}</div>
      ${e.complaint_labels.length ? `<div class="cmp">${e.complaint_labels.map(esc).join(" · ")}</div>` : ""}
      ${e.note ? `<div class="note">${esc(e.note)}</div>` : ""}
      <button class="link-del" data-del-mood="${e.id}" title="Eintrag löschen">×</button>
    </div>`).join("") : '<p class="muted">Noch nichts eingetragen.</p>';

  $$("[data-del-mood]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/mood/${b.dataset.delMood}`, { method: "DELETE" });
      toast("Gelöscht"); loadMood(); }
    catch (e) { toast(e.message, true); }
  }));

  const a = d.adaptations;
  const card = $("#adaptCard");
  if (a.complaints.length) {
    card.hidden = false;
    $("#adaptBody").innerHTML = `
      <ul class="plain">${a.summary.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
      ${a.relief_poses.length ? `<p>Beim Abend-Yoga zuerst: <b>${a.relief_poses.map(esc).join(", ")}</b>.</p>` : ""}
      ${a.spare_groups.length ? '<p class="muted">Die betroffenen Muskelgruppen fallen aus der nächsten Gym-Einheit heraus — bleibt dann zu wenig übrig, plant PULS wieder normal.</p>' : ""}
      ${a.nutrition.length ? a.nutrition.map((n) => `<p>${esc(n)}</p>`).join("") : ""}`;
  } else {
    card.hidden = true;
  }
}

$("#btnSaveMood").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  if (moodScales.mood == null && moodScales.energy == null &&
      moodScales.stress == null && !moodComplaints.length && !$("#moodNote").value.trim()) {
    toast("Nichts einzutragen.", true); return;
  }
  await api("/mood", { method: "POST", body: JSON.stringify({
    ...moodScales, note: $("#moodNote").value.trim() || null,
    complaints: moodComplaints }) });
  moodScales = { mood: null, energy: null, stress: null };
  moodComplaints = []; $("#moodNote").value = ""; $("#moodSuggest").hidden = true;
  toast("Eingetragen"); loadMood(); loadDashboard();
}));

$("#moodNote").addEventListener("input", watchNote);

/* ------------------------------------------------------ Supplements */

async function loadSupplements() {
  let d;
  try { d = await api("/supplements"); } catch (e) { return; }
  const card = $("#suppCard");
  if (!d.total) { card.hidden = true; return; }
  card.hidden = false;
  $("#suppList").innerHTML = d.items.map((i) => `
    <label class="supp-row${i.taken ? " done" : ""}${i.overdue ? " over" : ""}">
      <input type="checkbox" data-supp="${i.id}" ${i.taken ? "checked" : ""}
        ${i.waiting_for ? "disabled" : ""}>
      <span class="n">${esc(i.name)}${i.dose ? ` <span class="muted">${esc(i.dose)}</span>` : ""}</span>
      <span class="t">${esc(i.due_label)}</span>
    </label>`).join("") +
    (d.overdue.length ? `<p class="muted">Überfällig: ${d.overdue.map(esc).join(", ")}.</p>` : "");

  $$("[data-supp]").forEach((box) => box.addEventListener("change", async () => {
    try {
      await api(`/supplements/${box.dataset.supp}/taken?taken=${box.checked}`,
                { method: "POST" });
      loadSupplements();
    } catch (e) { toast(e.message, true); box.checked = !box.checked; }
  }));
}

const TRIGGER_WORDS = { time: "", after_gym: "nach dem Gym", after_run: "nach dem Lauf" };

async function loadSupplementManager() {
  let list;
  try { list = await api("/supplements/all"); } catch (e) { return; }
  $("#suppManage").innerHTML = list.length ? list.map((s) => `
    <div class="list-item">
      <div class="grow">
        <div class="title">${esc(s.name)}${s.dose ? ` — ${esc(s.dose)}` : ""}</div>
        <div class="meta">${s.trigger_kind === "time" ? esc(s.at_time || "")
          : esc(TRIGGER_WORDS[s.trigger_kind] || s.trigger_kind)}
          ${s.note ? ` · ${esc(s.note)}` : ""}</div>
      </div>
      <button class="link-del" data-del-supp="${s.id}" title="Entfernen">×</button>
    </div>`).join("") : '<p class="muted">Noch keine angelegt.</p>';

  $$("[data-del-supp]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Dieses Supplement entfernen?")) return;
    try { await api(`/supplements/${b.dataset.delSupp}`, { method: "DELETE" });
      loadSupplementManager(); loadSupplements(); }
    catch (e) { toast(e.message, true); }
  }));
}

$("#btnAddSupp").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const kind = $("#suppTrigger").value;
  await api("/supplements", { method: "POST", body: JSON.stringify({
    name: $("#suppName").value.trim(),
    dose: $("#suppDose").value.trim() || null,
    trigger_kind: kind,
    at_time: kind === "time" ? $("#suppTime").value : null,
    note: $("#suppNote").value.trim() || null }) });
  $("#suppName").value = ""; $("#suppDose").value = ""; $("#suppNote").value = "";
  toast("Angelegt"); loadSupplementManager(); loadSupplements();
}));

$("#suppTrigger").addEventListener("change", () => {
  $("#suppTime").disabled = $("#suppTrigger").value !== "time";
});


/* ----------------------------------------------------------- Erholung */

function fmtSleep(sec) {
  if (!sec) return "–";
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")} h`;
}

/* Ein Wert im Verhältnis zur eigenen Basislinie sagt mehr als die nackte
   Zahl: 58 ms HRV sind gut oder schlecht, je nachdem, was für dich normal ist. */
function baselineNote(b, invert = false) {
  if (!b || b.delta == null) return "";
  const better = invert ? b.delta < 0 : b.delta > 0;
  const cls = Math.abs(b.delta) < 0.5 ? "" : better ? "down" : "up";
  const sign = b.delta > 0 ? "+" : "";
  return `<span class="d ${cls}">${sign}${b.delta} ggü. Schnitt</span>`;
}

async function loadRecovery() {
  let d;
  try { d = await api("/recovery?days=60"); } catch (e) { return; }
  const series = d.series || [];
  const l = d.latest || {};
  const b = d.baselines || {};

  const facts = [
    { v: l.hrv_avg != null ? Math.round(l.hrv_avg) : null, u: "ms", l: "HRV",
      extra: baselineNote(b.hrv_avg) },
    { v: l.resting_hr != null ? Math.round(l.resting_hr) : null, u: "", l: "Ruhepuls",
      extra: baselineNote(b.resting_hr, true) },
    { v: l.sleep_seconds ? fmtSleep(l.sleep_seconds) : null, u: "", l: "Schlaf" },
    { v: l.sleep_score != null ? Math.round(l.sleep_score) : null, u: "", l: "Schlafscore" },
    { v: l.body_battery_max != null ? Math.round(l.body_battery_max) : null,
      u: "", l: "Body Battery" },
    { v: l.stress_avg != null ? Math.round(l.stress_avg) : null, u: "", l: "Stress Ø" },
    { v: l.training_readiness != null ? Math.round(l.training_readiness) : null,
      u: "", l: "Bereitschaft" },
    { v: l.respiration_avg != null ? l.respiration_avg.toFixed(1) : null,
      u: "/min", l: "Atmung" },
  ].filter((f) => f.v != null);

  $("#recoveryFacts").innerHTML = facts.length ? facts.map((f) => `
    <div class="f"><div class="v">${esc(String(f.v))}<span class="u">${f.u}</span></div>
      <div class="l">${f.l}</div>${f.extra || ""}</div>`).join("")
    : `<p class="muted">${esc(d.hint || "Noch keine Erholungsdaten.")}</p>`;

  $("#recoveryNotes").innerHTML = (d.observations || []).map((o) =>
    `<div class="finding ${o.level}"><div class="d">${esc(o.text)}</div></div>`).join("");

  const pick = (key) => series.filter((r) => r[key] != null)
    .map((r) => ({ value: r[key], label: r.day.slice(5), tip: r.day }));

  lineChart($("#hrvChart"), pick("hrv_avg"), { unit: " ms" });
  lineChart($("#sleepChart"), series.filter((r) => r.sleep_seconds)
    .map((r) => ({ value: +(r.sleep_seconds / 3600).toFixed(2),
                   label: r.day.slice(5), tip: r.day })), { unit: " h" });

  /* Schlafphasen der letzten Nacht als Anteilsbalken */
  const stages = [["sleep_deep_s", "Tief", "z4"], ["sleep_rem_s", "REM", "z3"],
                  ["sleep_light_s", "Leicht", "z2"], ["sleep_awake_s", "Wach", "z1"]];
  const total = stages.reduce((sum, [k]) => sum + (l[k] || 0), 0);
  $("#sleepStages").innerHTML = total > 0 ? `
    <div class="zone-bar">${stages.map(([k, , cls]) => {
      const pct = ((l[k] || 0) / total) * 100;
      return pct > 0.5 ? `<span class="${cls}" style="width:${pct}%"></span>` : "";
    }).join("")}</div>
    <div class="zone-legend">${stages.map(([k, label]) =>
      l[k] ? `<span>${label}: ${fmtSleep(l[k])}</span>` : "").join("")}</div>` : "";

  barChart($("#stressChart"), series.filter((r) => r.stress_avg != null)
    .map((r) => ({ value: Math.round(r.stress_avg), label: r.day.slice(8),
                   tip: `${r.day} — Stress Ø` })), { color: "var(--warn)" });
  lineChart($("#batteryChart"), pick("body_battery_max"), { color: "var(--good)" });
}

/* ------------------------------------------------------------ Rezepte */

let recipeCache = [];

async function loadRecipes() {
  const meal = $("#recipeMeal").value;
  let d;
  try { d = await api(`/recipes/suggest?count=3${meal ? `&meal=${meal}` : ""}`); }
  catch (e) { return; }
  recipeCache = d.recipes;
  $("#recipeReason").textContent = d.reason || "";
  $("#recipeList").innerHTML = d.recipes.map((r, i) => `
    <div class="list-item recipe" data-recipe="${i}" style="cursor:pointer">
      <div class="grow">
        <div class="title">${esc(r.name)}</div>
        <div class="meta">${r.kcal} kcal · ${r.protein} g Eiweiß ·
          ${r.carbs} g KH · ${r.minutes} min
          ${r.tags.includes("mealprep") ? ' · <span class="badge">vorkochbar</span>' : ""}
          ${r.tags.includes("vegan") ? ' · <span class="badge">vegan</span>'
            : r.tags.includes("veg") ? ' · <span class="badge">vegetarisch</span>' : ""}</div>
      </div>
      <span class="muted">Rezept ›</span>
    </div>`).join("") || '<p class="muted">Keine passenden Rezepte gefunden.</p>';

  $$("[data-recipe]").forEach((el) => el.addEventListener("click", () =>
    openRecipe(recipeCache[+el.dataset.recipe])));
}

function openRecipe(r) {
  if (!r) return;
  $("#recipeTitle").textContent = r.name;
  $("#recipeBody").innerHTML = `
    <div class="run-facts">
      <div class="f"><div class="v">${r.kcal}</div><div class="l">kcal</div></div>
      <div class="f"><div class="v">${r.protein}</div><div class="l">g Eiweiß</div></div>
      <div class="f"><div class="v">${r.carbs}</div><div class="l">g Kohlenhydrate</div></div>
      <div class="f"><div class="v">${r.fat}</div><div class="l">g Fett</div></div>
      <div class="f"><div class="v">${r.minutes}</div><div class="l">Minuten</div></div>
    </div>
    <div class="detail-section"><h4>Zutaten</h4>
      <ul class="plain">${r.ingredients.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></div>
    <div class="detail-section"><h4>Zubereitung</h4>
      <ol class="plain">${r.steps.map((i) => `<li>${esc(i)}</li>`).join("")}</ol></div>
    ${r.note ? `<p class="muted">${esc(r.note)}</p>` : ""}
    <div class="row" style="margin-top:12px">
      <button class="btn" id="btnEatRecipe">Gegessen — eintragen</button>
      <select id="eatPortions" class="small">
        <option value="0.5">halbe Portion</option>
        <option value="1" selected>1 Portion</option>
        <option value="1.5">1,5 Portionen</option>
        <option value="2">2 Portionen</option>
      </select>
    </div>`;
  $("#btnEatRecipe").addEventListener("click", (e) =>
    withSpinner(e.currentTarget, async () => {
      await api("/nutrition/meals/from-recipe", { method: "POST",
        body: JSON.stringify({ recipe_id: r.id,
                               portions: +$("#eatPortions").value }) });
      toast("Eingetragen");
      $("#recipeDialog").hidden = true;
      loadMeals(); loadDashboard();
    }));
  $("#recipeDialog").hidden = false;
}

$("#recipeClose").addEventListener("click", () => { $("#recipeDialog").hidden = true; });
$("#recipeMeal").addEventListener("change", loadRecipes);
$("#btnRecipeExplain").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const meal = $("#recipeMeal").value;
  const r = await api(`/recipes/explain${meal ? `?meal=${meal}` : ""}`, { method: "POST" });
  $("#recipeAdvice").hidden = false;
  $("#recipeAdvice").innerHTML = mdToHtml(r.text);
}));


/* --------------------------------------------------------- Laufform */

function paceStr(sec) {
  if (!sec) return "–";
  return `${Math.floor(sec / 60)}:${String(Math.round(sec % 60)).padStart(2, "0")}`;
}

async function loadRunTrend() {
  let t;
  try { t = await api("/running/trend?days=365"); } catch (e) { return; }
  const card = $("#runTrendCard");
  if (!t.runs) {
    card.hidden = false;
    $("#trendFacts").innerHTML = `<p class="muted">${esc(t.hint || "Noch keine Läufe.")}</p>`;
    $("#trendHints").innerHTML = "";
    return;
  }
  card.hidden = false;

  const totalKm = t.weeks.reduce((s, w) => s + w.km, 0);
  const facts = [
    { v: t.runs, u: "", l: "Läufe" },
    { v: Math.round(totalKm), u: "km", l: "gesamt" },
    t.change ? { v: `${t.change.percent > 0 ? "+" : ""}${t.change.percent}`, u: "%",
                 l: "Effizienz", cls: t.change.percent >= 0 ? "down" : "up" } : null,
    t.easy_share != null ? { v: t.easy_share, u: "%", l: "locker gelaufen" } : null,
  ].filter(Boolean);
  $("#trendFacts").innerHTML = facts.map((f) => `
    <div class="f"><div class="v">${esc(String(f.v))}<span class="u">${f.u}</span></div>
      <div class="l">${f.l}</div></div>`).join("");

  $("#trendHints").innerHTML = (t.hints || []).map((h) =>
    `<div class="finding ${h.level}"><div class="d">${esc(h.text)}</div></div>`).join("");

  /* Die geglättete Linie zeigt den Trend, die Rohwerte wären zu unruhig */
  lineChart($("#trendEffChart"), t.efficiency.map((p) => ({
    value: p.smooth, label: p.day.slice(5),
    tip: `${p.day} — ${p.km} km, ${paceStr(p.pace_s)}/km, ${p.hr || "?"} bpm`,
  })));

  barChart($("#trendWeekChart"), t.weeks.map((w) => ({
    value: Math.round(w.km), label: w.week.slice(-2),
    tip: `${w.week}: ${w.runs} Läufe`,
  })), { color: "var(--teal)", unit: " km" });

  $("#trendBests").innerHTML = t.bests.length ? `
    <div class="bests">${t.bests.map((b) => `
      <div class="best" data-run-id="${b.id}" style="cursor:pointer">
        <div class="bl">${esc(b.label)}</div>
        <div class="bv">${paceStr(b.pace_s)}<span class="u">/km</span></div>
        <div class="bd">${fmtDate(b.day)}</div>
      </div>`).join("")}</div>
    <p class="muted">Bestes Durchschnittstempo über die jeweilige Distanz —
      hochgerechnet, nicht als Wettkampfzeit gelaufen.</p>`
    : '<p class="muted">Noch keine Distanz oft genug gelaufen.</p>';

  $$("#trendBests [data-run-id]").forEach((el) => el.addEventListener("click", () =>
    openRunAnalysis(+el.dataset.runId)));
}

/* -------------------------------------------------- Aktivitätsprotokoll */

async function loadActivityLog() {
  loadRunTrend();
  const sport = $("#logSport").value;
  const days = $("#logDays").value;
  let d;
  try { d = await api(`/activities/log?days=${days}${sport ? `&sport=${sport}` : ""}`); }
  catch (e) { return; }

  $("#logTotals").innerHTML = d.totals.map((t) =>
    `${SPORT_LABEL[t.sport] || t.sport}: ${t.n}× · ${fmtDur(t.seconds)}` +
    (t.meters ? ` · ${(t.meters / 1000).toFixed(0)} km` : "")).join(" &nbsp;·&nbsp; ")
    || "Keine Einträge in diesem Zeitraum.";

  $("#activityList").innerHTML = d.activities.length ? d.activities.map((a) => `
    <div class="list-item" data-run-id="${a.id}" style="cursor:pointer">
      ${kindTag(a.sport)}
      <div class="grow">
        <div class="title">${esc(a.name || SPORT_LABEL[a.sport] || "Training")}</div>
        <div class="meta">${fmtDate(a.start_time)} · ${fmtDur(a.duration_s)}
          ${a.distance_m ? " · " + (a.distance_m / 1000).toFixed(1) + " km" : ""}
          ${a.avg_hr ? " · Ø " + Math.round(a.avg_hr) + " bpm" : ""}
          ${a.elevation_gain ? " · " + Math.round(a.elevation_gain) + " hm" : ""}
          ${a.has_details ? ' · <span class="badge">Karte</span>' : ""}
          · <span class="badge">${a.source === "garmin" ? "Garmin"
            : a.source === "fit" ? "FIT" : "manuell"}</span></div>
      </div>
      <span class="muted">${a.sport === "strength" ? "Auswertung" : "Analyse"} ›</span>
    </div>`).join("") : '<p class="muted">Nichts gefunden.</p>';

  $$("[data-run-id]").forEach((el) => el.addEventListener("click", () =>
    openRunAnalysis(+el.dataset.runId)));
}

$("#logSport").addEventListener("change", loadActivityLog);
$("#logDays").addEventListener("change", loadActivityLog);



/* ------------------------------------------------- Dashboard-Karten */

function relDay(iso) {
  if (!iso) return "";
  const d = new Date(iso.slice(0, 10) + "T12:00:00");
  const diff = Math.round((d - new Date(new Date().toDateString())) / 86400000);
  if (diff === 0) return "heute";
  if (diff === 1) return "morgen";
  if (diff === -1) return "gestern";
  if (diff > 1 && diff < 7) return d.toLocaleDateString("de-DE", { weekday: "long" });
  if (diff < 0 && diff > -7) return `vor ${-diff} Tagen`;
  return fmtDate(iso);
}

function renderRecentActivities(list) {
  const box = $("#recentActivities");
  if (!list || !list.length) {
    box.innerHTML = '<p class="muted">Noch nichts aufgezeichnet.</p>';
    return;
  }
  box.innerHTML = list.slice(0, 6).map((a) => `
    <div class="mini" data-run-id="${a.id}">
      ${kindTag(a.sport)}
      <div class="mt">${esc(a.name || SPORT_LABEL[a.sport] || "Training")}</div>
      <div class="mm">${fmtDur(a.duration_s)}${a.distance_m
        ? " · " + (a.distance_m / 1000).toFixed(1) + " km" : ""}${a.avg_hr
        ? " · Ø " + Math.round(a.avg_hr) + " bpm" : ""}</div>
      <div class="mr">${esc(relDay(a.start_time))}</div>
    </div>`).join("");
  $$("#recentActivities [data-run-id]").forEach((el) =>
    el.addEventListener("click", () => openRunAnalysis(+el.dataset.runId)));
}

/* Eine Kachel: Wert, Einheit, Veränderung gegenüber der Basislinie, Verlauf.
   Für einen einzelnen Wert ist das ehrlicher als ein Diagramm mit einem Balken. */
/* Bei einer Skala von 0 bis 100 sagt die nackte Zahl nichts: 38 ist bei
   Stress gut und bei Bereitschaft schlecht. Deshalb "38 von 100" plus ein
   Balken, der die Lage auf der Skala zeigt. */
function tile(value, unit, label, opts = {}) {
  if (value == null) {
    return `<div class="tile"><div class="tv">–</div><div class="tl">${esc(label)}</div></div>`;
  }
  let meter = "";
  if (opts.max) {
    const pct = Math.max(0, Math.min(100, (Number(value) / opts.max) * 100));
    /* Farbe nach Bedeutung, nicht nach Höhe: viel Stress ist schlecht,
       viel Bereitschaft ist gut. */
    const good = opts.lowerIsBetter ? pct <= 40 : pct >= 65;
    const bad = opts.lowerIsBetter ? pct >= 70 : pct <= 35;
    const color = good ? "var(--good)" : bad ? "var(--warn)" : "var(--accent)";
    meter = `<div class="meter" role="img"
        aria-label="${esc(String(value))} von ${opts.max}">
        <span style="width:${pct.toFixed(0)}%;background:${color}"></span></div>
      <div class="tscale">von ${opts.max}${opts.band ? ` · ${esc(opts.band(value))}` : ""}</div>`;
  }
  let delta = "";
  if (opts.delta != null && Math.abs(opts.delta) >= (opts.threshold || 0.5)) {
    /* Bei Ruhepuls und Stress ist weniger besser — deshalb umkehrbar */
    const better = opts.lowerIsBetter ? opts.delta < 0 : opts.delta > 0;
    delta = `<div class="td ${better ? "good" : "bad"}">${opts.delta > 0 ? "+" : ""}${opts.delta}${opts.deltaUnit || ""} ggü. Schnitt</div>`;
  }
  return `<div class="tile">
    <div class="tv">${esc(String(value))}${unit ? `<span class="u">${unit}</span>` : ""}</div>
    <div class="tl">${esc(label)}</div>
    ${meter}
    ${delta}
    ${opts.series ? `<div class="spark">${sparkline(opts.series, { color: opts.color })}</div>` : ""}
  </div>`;
}

function renderSleepAndHeart(rec) {
  if (!rec) return;
  const series = rec.series || [];
  const l = rec.latest || {};
  const b = rec.baselines || {};
  const col = (key) => series.map((r) => r[key]);

  const hours = l.sleep_seconds ? +(l.sleep_seconds / 3600).toFixed(1) : null;
  $("#sleepTiles").innerHTML =
    tile(hours, " h", "letzte Nacht", {
      series: series.map((r) => r.sleep_seconds ? r.sleep_seconds / 3600 : null),
      color: "var(--teal)",
      delta: b.sleep_seconds?.delta != null
        ? +(b.sleep_seconds.delta / 3600).toFixed(1) : null,
      deltaUnit: " h", threshold: 0.2 }) +
    tile(l.sleep_score != null ? Math.round(l.sleep_score) : null, "", "Schlafscore",
      { series: col("sleep_score"), color: "var(--teal)", max: 100,
        band: (v) => v >= 80 ? "sehr gut" : v >= 60 ? "gut" : v >= 40 ? "mäßig" : "schlecht" });

  /* Schlafphasen als Anteilsbalken — Teil vom Ganzen, keine Torte */
  const stages = [["sleep_deep_s", "Tief", "z4"], ["sleep_rem_s", "REM", "z3"],
                  ["sleep_light_s", "Leicht", "z2"], ["sleep_awake_s", "Wach", "z1"]];
  const total = stages.reduce((sum, [k]) => sum + (l[k] || 0), 0);
  $("#sleepStagesMini").innerHTML = total > 0 ? `
    <div class="zone-bar">${stages.map(([k, , cls]) => {
      const pct = ((l[k] || 0) / total) * 100;
      return pct > 0.5 ? `<span class="${cls}" style="width:${pct}%"></span>` : "";
    }).join("")}</div>
    <div class="zone-legend">${stages.map(([k, label]) => l[k]
      ? `<span>${label} ${Math.round(l[k] / 60)} min</span>` : "").join("")}</div>` : "";

  /* Nur die zwei Werte, die wirklich etwas sagen — ohne Sparkline, weil
     darunter das große Diagramm mit dem Normalband steht. */
  $("#heartTiles").innerHTML =
    tile(l.resting_hr != null ? Math.round(l.resting_hr) : null, " bpm", "Ruhepuls", {
      delta: b.resting_hr?.delta, lowerIsBetter: true, threshold: 1 }) +
    tile(l.hrv_avg != null ? Math.round(l.hrv_avg) : null, " ms", "HRV", {
      delta: b.hrv_avg?.delta, threshold: 1 }) +
    tile(l.body_battery_max != null ? Math.round(l.body_battery_max) : null, "",
      "Body Battery", { series: col("body_battery_max"), color: "var(--good)",
        max: 100, band: (v) => v >= 75 ? "voll" : v >= 50 ? "ordentlich" : v >= 25 ? "wenig" : "leer" }) +
    tile(l.stress_avg != null ? Math.round(l.stress_avg) : null, "", "Stress Ø", {
      lowerIsBetter: true, max: 100,
      band: (v) => v <= 25 ? "ruhig" : v <= 50 ? "normal" : v <= 75 ? "erhöht" : "hoch" });

  /* Verlauf vor dem Normalband: erst dadurch ist zu sehen, ob ein Wert
     auffällig war oder im üblichen Rahmen lag. */
  const dayLabel = (r) => r.day.slice(5);
  baselineChart($("#rhrChart"),
    series.filter((r) => r.resting_hr != null)
      .map((r) => ({ value: r.resting_hr, label: dayLabel(r) })),
    { baseline: b.resting_hr?.baseline, spread: 2, color: "var(--bad)",
      lowerIsBetter: true, label: "Ruhepuls", empty: "Noch zu wenige Ruhepuls-Werte." });
  baselineChart($("#hrvDashChart"),
    series.filter((r) => r.hrv_avg != null)
      .map((r) => ({ value: r.hrv_avg, label: dayLabel(r) })),
    { baseline: b.hrv_avg?.baseline, spread: 5, color: "var(--good)",
      label: "HRV", empty: "Noch zu wenige HRV-Werte." });

  /* Schlafverlauf auf dem Dashboard */
  baselineChart($("#sleepChartDash"),
    series.filter((r) => r.sleep_seconds)
      .map((r) => ({ value: +(r.sleep_seconds / 3600).toFixed(2), label: dayLabel(r) })),
    { baseline: b.sleep_seconds?.baseline ? b.sleep_seconds.baseline / 3600 : null,
      spread: 0.5, color: "var(--teal)", fmt: (v) => v.toFixed(1) + " h",
      label: "Schlafdauer", empty: "Noch zu wenige Nächte aufgezeichnet." });
}

/* Die Verweise am Kartenfuß sollen wirklich zur Ansicht springen */
$$("[data-goto]").forEach((b) => b.addEventListener("click", () => {
  const target = $(`nav.bottom [data-view="${b.dataset.goto}"]`);
  if (target) target.click();
}));



/* ------------------------------------------- Zustand, Schwung, Feedback */

/* Puls, Schlaf, Stress und Bereitschaft in einer Reihe — die vier Werte,
   nach denen sich entscheidet, was heute sinnvoll ist. */
function renderTodayTiles(rec) {
  if (!rec) return;
  const l = rec.latest || {};
  const b = rec.baselines || {};
  const series = rec.series || [];
  const col = (k) => series.map((r) => r[k]);

  $("#todayTiles").innerHTML =
    tile(l.resting_hr != null ? Math.round(l.resting_hr) : null, " bpm", "Ruhepuls",
      { series: col("resting_hr"), color: "var(--bad)",
        delta: b.resting_hr?.delta, lowerIsBetter: true, threshold: 1 }) +
    tile(l.hrv_avg != null ? Math.round(l.hrv_avg) : null, " ms", "HRV",
      { series: col("hrv_avg"), color: "var(--good)",
        delta: b.hrv_avg?.delta, threshold: 1 }) +
    tile(l.sleep_seconds ? +(l.sleep_seconds / 3600).toFixed(1) : null, " h", "Schlaf",
      { series: series.map((r) => r.sleep_seconds ? r.sleep_seconds / 3600 : null),
        color: "var(--teal)" }) +
    tile(l.stress_avg != null ? Math.round(l.stress_avg) : null, "", "Stress Ø",
      { series: col("stress_avg"), color: "var(--warn)", lowerIsBetter: true,
        max: 100, band: (v) => v <= 25 ? "ruhig" : v <= 50 ? "normal" : v <= 75 ? "erhöht" : "hoch" }) +
    tile(l.training_readiness != null ? Math.round(l.training_readiness) : null,
      "", "Bereitschaft", { series: col("training_readiness"),
        color: "var(--accent)", max: 100, band: (v) => v >= 75 ? "sehr gut" : v >= 50 ? "solide" : v >= 25 ? "mäßig" : "niedrig" }) +
    tile(l.body_battery_wake != null ? Math.round(l.body_battery_wake) : null,
      "", "Body Battery früh", { series: col("body_battery_wake"),
        color: "var(--good)", max: 100, band: (v) => v >= 75 ? "voll" : v >= 50 ? "ordentlich" : v >= 25 ? "wenig" : "leer" });
}

async function loadReadout(force = false) {
  const box = $("#readoutText");
  if (!force && sessionStorage.getItem("readout")) {
    box.innerHTML = mdToHtml(sessionStorage.getItem("readout"));
    return;
  }
  box.innerHTML = '<span class="muted"><span class="spin"></span> Der Coach schaut auf die Zahlen …</span>';
  try {
    const r = await api("/coach/readout", { method: "POST" });
    /* Die Einschätzung bis zum Neuladen behalten: auf der CPU dauert sie
       spürbar, und sie ändert sich innerhalb einer Sitzung ohnehin kaum. */
    sessionStorage.setItem("readout", r.message);
    box.innerHTML = mdToHtml(r.message);
  } catch (e) {
    box.innerHTML = `<span class="muted">${esc(e.message)}</span>`;
  }
}

$("#btnReadout").addEventListener("click", (e) =>
  withSpinner(e.currentTarget, () => loadReadout(true)));

const KIND_WORDS = { movement: "Bewegung", nutrition: "Ernährung", routine: "Gewohnheit" };

function renderBoosters(d) {
  const card = $("#boosterCard");
  if (!d || !d.boosters || !d.boosters.length) { card.hidden = true; return; }
  card.hidden = false;
  $("#boosterSituation").textContent = d.situation.reasons.length
    ? "Weil: " + d.situation.reasons.join(", ") : "";

  $("#boosterList").innerHTML = d.boosters.map((b) => `
    <div class="booster">
      <div class="bk">${KIND_WORDS[b.kind] || b.kind}${b.minutes ? ` · ${b.minutes} min` : ""}</div>
      <div class="bn">${esc(b.name)}</div>
      <div class="bt">${esc(b.text)}</div>
      ${b.stats && b.stats.bewertet >= 2
        ? `<div class="bk">bei dir ${b.stats.gut} von ${b.stats.bewertet} Mal hilfreich</div>` : ""}
      <div class="row">
        <button class="btn small ghost" data-rate="${b.id}" data-help="1">Hat geholfen</button>
        <button class="btn small ghost" data-rate="${b.id}" data-help="0">Bringt mir nichts</button>
      </div>
    </div>`).join("");

  $("#boosterOpen").innerHTML = (d.open || []).length ? `
    <div class="works">Von neulich noch offen — hat das etwas gebracht?
      ${d.open.map((o) => `<button class="btn small ghost" data-rate="${o.tip_id}"
        data-help="1">${esc(o.name)}: ja</button>
        <button class="btn small ghost" data-rate="${o.tip_id}"
        data-help="0">nein</button>`).join(" ")}</div>` : "";

  $("#boosterWorks").innerHTML = (d.works || []).length ? `
    <div class="works">Was bei dir bisher am besten wirkt:
      ${d.works.slice(0, 3).map((w) =>
        `<b>${esc(w.name)}</b> (${w.gut}/${w.bewertet})`).join(", ")}.</div>` : "";

  $$("[data-rate]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api(`/boosters/${b.dataset.rate}/rate`, { method: "POST",
        body: JSON.stringify({ helpful: b.dataset.help === "1" }) });
      toast(b.dataset.help === "1" ? "Gemerkt — kommt öfter." : "Gemerkt — kommt seltener.");
      loadDashboard();
    } catch (e) { toast(e.message, true); }
  }));
}

function scaleRow(label, name, id) {
  return `<div class="fb-scale"><span class="lb">${label}</span>
    ${[1, 2, 3, 4, 5].map((n) =>
      `<button class="dot" data-fb="${id}" data-field="${name}" data-value="${n}">${n}</button>`
    ).join("")}</div>`;
}

const fbDraft = {};

function renderFeedback(list) {
  const card = $("#feedbackCard");
  if (!list || !list.length) { card.hidden = true; return; }
  card.hidden = false;
  $("#feedbackBody").innerHTML = list.map((a) => `
    <div class="fb-item">
      <div class="fn">${esc(a.name || SPORT_LABEL[a.sport] || "Training")}</div>
      <div class="fm">${fmtDate(a.start_time)} · ${fmtDur(a.duration_s)}${
        a.distance_m ? " · " + (a.distance_m / 1000).toFixed(1) + " km" : ""}</div>
      ${scaleRow("Wie war es?", "rating", a.id)}
      ${scaleRow("Anstrengung", "effort", a.id)}
      <input class="grow" data-note="${a.id}" placeholder="Notiz (optional)">
      <div class="row" style="margin-top:6px">
        <button class="btn small" data-fbsave="${a.id}">Speichern</button>
      </div>
    </div>`).join("");

  $$("[data-fb]").forEach((b) => b.addEventListener("click", () => {
    const id = b.dataset.fb, field = b.dataset.field;
    fbDraft[id] = fbDraft[id] || {};
    fbDraft[id][field] = +b.dataset.value;
    $$(`[data-fb="${id}"][data-field="${field}"]`).forEach((x) =>
      x.classList.toggle("on", +x.dataset.value === fbDraft[id][field]));
  }));

  $$("[data-fbsave]").forEach((b) => b.addEventListener("click", (e) =>
    withSpinner(e.currentTarget, async () => {
      const id = b.dataset.fbsave;
      const note = $(`[data-note="${id}"]`);
      await api(`/activities/${id}/feedback`, { method: "POST",
        body: JSON.stringify({ ...(fbDraft[id] || {}),
                               note: note ? note.value.trim() || null : null }) });
      toast("Danke — das fließt in die Auswertung ein.");
      delete fbDraft[id];
      loadDashboard();
    })));
}

/* --------------------------------------------- Chat auf der Startseite */

function dashBubble(kind, text, who) {
  const el = document.createElement("div");
  el.className = "bubble " + kind;
  el.innerHTML = (who ? `<div class="k">${esc(who)}</div>` : "") + mdToHtml(text);
  $("#dashChatLog").appendChild(el);
  $("#dashChatLog").scrollTop = $("#dashChatLog").scrollHeight;
  return el;
}

async function dashAsk() {
  const q = $("#dashChatInput").value.trim();
  if (!q) return;
  $("#dashChatInput").value = "";
  dashBubble("user", q);
  const pending = dashBubble("coach", "Denke nach … (lokale KI, kann dauern)", "PULS");
  try {
    const r = await api("/coach/ask", { method: "POST",
      body: JSON.stringify({ question: q }) });
    pending.innerHTML = '<div class="k">PULS</div>' + mdToHtml(r.answer);
    loadMemory();
  } catch (e) {
    pending.innerHTML = '<div class="k">PULS</div>⚠️ ' + esc(e.message);
  }
}

$("#btnDashAsk").addEventListener("click", dashAsk);
$("#dashChatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") dashAsk();
});

async function loadMemory() {
  let list;
  try { list = await api("/memory"); } catch (e) { return; }
  $("#memoryList").innerHTML = list.length ? list.map((m) => `
    <div class="mem-row">
      <span class="mtopic">${esc(m.topic)}</span>
      <span>${esc(m.fact)}</span>
      <span>
        <button class="pin${m.pinned ? " on" : ""}" data-forget="${m.id}"
          title="Vergessen">×</button>
      </span>
    </div>`).join("") : '<p class="muted">Noch nichts gemerkt.</p>';
  $$("[data-forget]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/memory/${b.dataset.forget}`, { method: "DELETE" });
      loadMemory(); }
    catch (e) { toast(e.message, true); }
  }));
}

$("#btnMemAdd").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const topic = $("#memTopic").value.trim(), fact = $("#memFact").value.trim();
  if (!topic || !fact) { toast("Thema und Inhalt bitte ausfüllen.", true); return; }
  await api("/memory", { method: "POST",
    body: JSON.stringify({ topic, fact, pinned: true }) });
  $("#memTopic").value = ""; $("#memFact").value = "";
  toast("Gemerkt"); loadMemory();
}));


/* ------------------------------------------------------- Zusammenhänge */

function renderInsights(d) {
  if (!d) return;
  $("#insightHint").textContent = d.hint || "";
  const foot = [];
  if (d.days_with_mood) foot.push(`${d.days_with_mood} Tage mit Befinden-Einträgen`);
  foot.push("Zusammenhang heißt nicht Ursache — aber es ist der Anfang.");
  $("#insightFoot").textContent = foot.join(" · ");

  if (d.helps?.length) {
    $("#insightHelps").innerHTML = '<h4 class="ins-h">Womit es dir besser geht</h4>' +
      '<div id="helpBars"></div>' +
      d.helps.map((f) => `<div class="ins-t">${esc(f.text)}</div>`).join("");
    splitBars($("#helpBars"), d.helps);
  } else { $("#insightHelps").innerHTML = ""; }

  if (d.hurts?.length) {
    $("#insightHurts").innerHTML = '<h4 class="ins-h">Was mit schlechteren Tagen einhergeht</h4>' +
      '<div id="hurtBars"></div>' +
      d.hurts.map((f) => `<div class="ins-t">${esc(f.text)}</div>`).join("");
    splitBars($("#hurtBars"), d.hurts);
  } else { $("#insightHurts").innerHTML = ""; }
}

/* --------------------------------------------------------- Mahlzeiten */

const SLOT_WORDS = { breakfast: "Frühstück", lunch: "Mittag", dinner: "Abend",
                     snack: "Snack", other: "Sonstiges" };

async function loadMeals() {
  let d;
  try { d = await api("/nutrition/day"); } catch (e) { return; }
  const t = d.targets;

  if (!t.ready) {
    $("#mealTargets").innerHTML = `<p class="muted">${esc(t.hint || "")}</p>`;
  } else {
    /* Erreicht von Ziel — der Balken zeigt, wie weit der Tag ist */
    const row = (key, label, unit, goalKey) => {
      const have = Math.round(d.total[key] || 0);
      const goal = t[goalKey];
      return tile(have, unit, `${label} von ${goal}${unit}`,
        { max: goal, band: () => d.remaining[key] > 0
          ? `noch ${d.remaining[key]}${unit}`
          : `${Math.abs(d.remaining[key])}${unit} drüber` });
    };
    $("#mealTargets").innerHTML =
      row("kcal", "Kalorien", "", "kcal") +
      row("protein_g", "Eiweiß", " g", "protein_g") +
      row("carbs_g", "Kohlenhydrate", " g", "carbs_g") +
      row("fat_g", "Fett", " g", "fat_g");
    $("#targetExplain").textContent = t.explain || "";
  }

  $("#mealList").innerHTML = d.meals.length ? `
    <div class="mini-list">${d.meals.map((m) => `
      <div class="mini" style="cursor:default">
        <span class="kind">${esc((SLOT_WORDS[m.slot] || "").slice(0, 4))}</span>
        <div class="mt">${esc(m.name)}${m.portions !== 1 ? ` ×${m.portions}` : ""}</div>
        <div class="mm">${[m.kcal ? `${Math.round(m.kcal)} kcal` : null,
          m.protein_g ? `${Math.round(m.protein_g)} g Eiweiß` : null]
          .filter(Boolean).join(" · ")}</div>
        <button class="link-del" data-del-meal="${m.id}" title="Löschen">×</button>
      </div>`).join("")}</div>`
    : '<p class="muted">Heute noch nichts eingetragen.</p>';

  $$("[data-del-meal]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/nutrition/meals/${b.dataset.delMeal}`, { method: "DELETE" });
      loadMeals(); loadDashboard(); }
    catch (e) { toast(e.message, true); }
  }));
}

$("#btnAddMeal").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const name = $("#mealName").value.trim();
  if (!name) { toast("Wie heißt die Mahlzeit?", true); return; }
  await api("/nutrition/meals", { method: "POST", body: JSON.stringify({
    name, slot: $("#mealSlot").value,
    kcal: +$("#mealKcal").value || null,
    protein_g: +$("#mealProtein").value || null,
    carbs_g: +$("#mealCarbs").value || null,
    fat_g: +$("#mealFat").value || null }) });
  ["mealName", "mealKcal", "mealProtein", "mealCarbs", "mealFat"]
    .forEach((id) => { $("#" + id).value = ""; });
  toast("Eingetragen"); loadMeals(); loadDashboard();
}));


/* ------------------------------------------------------------ Statistik */

let statsCache = null;
let statsWeakLimit = 12;

async function loadStats() {
  const days = $("#statsDays").value || 365;
  let d;
  try { d = await api(`/stats/matrix?days=${days}`); }
  catch (e) { $("#statsIntro").textContent = e.message; return; }
  statsCache = d;

  $("#statsIntro").innerHTML = d.hint ? esc(d.hint) : `
    ${d.tested} Paare aus ${d.metrics_used} Messgrößen über ${d.rows} Tage geprüft.
    <b>${d.robust.length}</b> davon halten der Korrektur für Mehrfachprüfung stand.
    ${d.metrics_missing.length ? `<br><span class="muted">Noch zu wenig Daten für:
      ${d.metrics_missing.slice(0, 8).map(esc).join(", ")}${
      d.metrics_missing.length > 8 ? " …" : ""}</span>` : ""}`;

  $("#statsRobust").innerHTML = d.robust.length ? d.robust.slice(0, 10).map((p) => `
    <div class="corr-row">
      <div class="ct">${esc(p.a_label)} <span class="muted">und</span> ${esc(p.b_label)}</div>
      <div class="cm">${p.direction} · ${p.strength} · r=${p.r} · ${p.n} Tage
        · p=${p.p < 0.001 ? "&lt;0,001" : p.p.toFixed(3).replace(".", ",")}</div>
    </div>`).join("")
    : '<p class="muted">Noch kein Zusammenhang belastbar. Das ist kein Fehler — es heißt, dass die Datenmenge dafür noch nicht reicht.</p>';
  correlationBars($("#statsRobustBars"), d.robust, { limit: 10 });

  const weak = d.pairs.filter((p) => !p.robust);
  correlationBars($("#statsWeakBars"), weak, { limit: statsWeakLimit });
  $("#btnStatsMore").hidden = weak.length <= statsWeakLimit;

  loadStatsRecommendations(days);
}

async function loadStatsRecommendations(days) {
  let d;
  try { d = await api(`/stats/recommendations?days=${days}`); }
  catch (e) { $("#statsRecs").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }

  if (!d.recommendations.length) {
    $("#statsRecs").innerHTML = `<p class="muted">${esc(d.hint || "Noch nichts abzuleiten.")}</p>`;
    return;
  }
  $("#statsRecs").innerHTML = d.recommendations.map((r) => `
    <div class="rec">
      <div class="rh">${esc(r.lever_label)} ${esc(r.direction)}
        <b>${esc(r.threshold_text)}</b></div>
      <div class="rb">
        <span class="rl">${esc(r.outcome_label)}</span>
        <span class="rv good">${esc(r.good_text)}</span>
        <span class="muted">statt</span>
        <span class="rv bad">${esc(r.bad_text)}</span>
        ${r.gain_pct ? `<span class="rd">+${r.gain_pct} %</span>` : ""}
      </div>
      <div class="rm">${r.days_good} gegen ${r.days_bad} Tage · r=${r.r}
        · korrigiertes p=${String(r.p_adjusted).replace(".", ",")}</div>
    </div>`).join("") + `
    <p class="muted" style="margin-top:10px">Die Richtung bleibt offen: Dass an
      Tagen mit dem einen Wert der andere besser liegt, heißt nicht, dass das
      eine das andere bewirkt. Als Ansatzpunkt taugt es trotzdem — probier eine
      Änderung zwei Wochen aus und sieh hier nach.</p>`;
}

$("#statsDays").addEventListener("change", loadStats);
$("#btnStatsMore").addEventListener("click", () => {
  statsWeakLimit += 20;
  if (statsCache) correlationBars($("#statsWeakBars"),
    statsCache.pairs.filter((p) => !p.robust), { limit: statsWeakLimit });
});
$("#btnStatsExplain").addEventListener("click", (e) =>
  withSpinner(e.currentTarget, async () => {
    const days = $("#statsDays").value || 365;
    const r = await api(`/stats/explain?days=${days}`, { method: "POST" });
    $("#statsAdvice").hidden = false;
    $("#statsAdvice").innerHTML = mdToHtml(r.message);
  }));

async function loadStatsMetrics() {
  let list;
  try { list = await api("/stats/metrics"); } catch (e) { return; }
  const groups = {};
  list.forEach((m) => (groups[m.group] = groups[m.group] || []).push(m));
  $("#statsMetric").innerHTML = '<option value="">Größe wählen …</option>' +
    Object.entries(groups).map(([g, items]) =>
      `<optgroup label="${esc(g)}">${items.map((m) =>
        `<option value="${m.key}">${esc(m.label)}</option>`).join("")}</optgroup>`
    ).join("");
}

$("#statsMetric").addEventListener("change", async () => {
  const key = $("#statsMetric").value;
  if (!key) { $("#statsMetricChart").innerHTML = ""; $("#statsMetricRelated").innerHTML = ""; return; }
  let d;
  try { d = await api(`/stats/metric/${key}?days=${$("#statsDays").value || 365}`); }
  catch (e) { toast(e.message, true); return; }
  lineChart($("#statsMetricChart"), d.series.map((p) => ({
    value: p.value, label: p.day.slice(5), tip: p.day })), { unit: d.unit });
  $("#statsMetricRelated").innerHTML = d.related.length
    ? '<h4 class="ins-h">Hängt zusammen mit</h4>' + d.related.map((p) => `
        <div class="corr-row${p.robust ? "" : " weak"}">
          <div class="ct">${esc(p.other_label)}</div>
          <div class="cm">${p.direction} · r=${p.r} · ${p.n} Tage${
            p.robust ? "" : " · schwach"}</div>
        </div>`).join("")
    : '<p class="muted">Für diese Größe zeigt sich noch kein Zusammenhang.</p>';
});

/* ----------------------------------------------------------- Heute */

function renderToday(d) {
  if (!d) return;
  const pct = d.percent;
  const color = pct >= 100 ? "var(--good)" : pct >= 50 ? "var(--accent)" : "var(--ink-3)";
  const r = 26, c = 2 * Math.PI * r;
  $("#todayRing").innerHTML = `<svg viewBox="0 0 64 64" width="64" height="64">
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="var(--surface-2)" stroke-width="6"></circle>
    <circle cx="32" cy="32" r="${r}" fill="none" stroke="${color}" stroke-width="6"
      stroke-linecap="round" stroke-dasharray="${(c * pct / 100).toFixed(1)} ${c.toFixed(1)}"
      transform="rotate(-90 32 32)"></circle>
    <text x="32" y="37" text-anchor="middle" font-size="16"
      font-family="var(--serif)" fill="var(--ink)">${d.done}</text>
  </svg>`;
  $("#todaySummary").textContent = d.done >= d.total
    ? "Alles erledigt."
    : `${d.done} von ${d.total} — offen: ${d.open.slice(0, 2).join(", ")}`;

  $("#todayList").innerHTML = '<div class="mini-list">' + d.items.map((i) => `
    <div class="mini today-item${i.done ? " done" : ""}" style="cursor:default">
      <span class="tick">${i.done ? "✓" : "○"}</span>
      <div class="mt">${esc(i.label)}</div>
      ${i.progress != null && !i.done
        ? `<div class="mm"><span class="tiny-bar"><span style="width:${i.progress}%"></span></span>
           ${i.detail ? esc(i.detail) : i.progress + " %"}</div>` : '<div class="mm"></div>'}
    </div>`).join("") + "</div>";
}

$("#btnCheckin").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/coach/checkin?kind=midday", { method: "POST" });
  $("#coachMessage").innerHTML = mdToHtml(r.message);
}));

$("#btnSleepAdvice").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/coach/sleep", { method: "POST" });
  $("#sleepAdvice").hidden = false;
  $("#sleepAdvice").innerHTML = mdToHtml(r.message);
}));


/* ------------------------------------------------------------ Autopilot */

const AUTO_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
let autoDays = [];

async function loadAutopilot() {
  // Nicht stillschweigend aussteigen: Ein leeres Autopilot-Feld sieht aus wie
  // eine kaputte Seite, und ohne Meldung sucht man an der falschen Stelle.
  let cfg;
  try { cfg = await api("/autopilot"); }
  catch (e) { toast("Autopilot nicht erreichbar: " + e.message, true); return; }
  autoDays = (cfg.available_days && cfg.available_days.length)
    ? cfg.available_days : AUTO_WEEKDAYS.slice();

  $("#autoFocus").innerHTML = Object.entries(cfg.presets).map(([k, v]) =>
    `<option value="${k}"${k === cfg.focus ? " selected" : ""}>${esc(v.label)}</option>`
  ).join("");
  $("#autoFocusNote").textContent = cfg.presets[cfg.focus]?.note || "";
  $("#autoMinutes").value = cfg.session_minutes;
  $("#autoLongDay").innerHTML = AUTO_WEEKDAYS.map((d) =>
    `<option value="${d}"${d === cfg.long_run_day ? " selected" : ""}>${d}</option>`
  ).join("");
  $("#autoWishes").value = cfg.wishes || "";
  renderAutoDays();

  $("#autoFocus").onchange = () => {
    $("#autoFocusNote").textContent = cfg.presets[$("#autoFocus").value]?.note || "";
  };
}

function renderAutoDays() {
  $("#autoDays").innerHTML = AUTO_WEEKDAYS.map((d) =>
    `<button class="chip${autoDays.includes(d) ? " on" : ""}" data-autoday="${d}">${d}</button>`
  ).join("");
  $$("#autoDays [data-autoday]").forEach((b) => b.addEventListener("click", () => {
    const d = b.dataset.autoday;
    autoDays = autoDays.includes(d) ? autoDays.filter((x) => x !== d) : [...autoDays, d];
    renderAutoDays();
  }));
}

async function saveAutopilot() {
  return api("/autopilot", { method: "POST", body: JSON.stringify({
    focus: $("#autoFocus").value,
    available_days: autoDays,
    session_minutes: +$("#autoMinutes").value || 60,
    long_run_day: $("#autoLongDay").value,
    wishes: $("#autoWishes").value.trim() }) });
}

function renderAutoWeek(w) {
  const cond = w.condition;
  $("#autoPreview").innerHTML = `
    <div class="detail-section">
      <h4>${esc(w.focus)} · ${w.runs} Läufe, ${w.gyms} Gym, je ${w.minutes_per_session} min</h4>
      <p class="muted">Zustand: <b>${esc(cond.state)}</b>${
        cond.reasons.length ? " — " + cond.reasons.map(esc).join(", ") : " — die Werte passen"}.
        ${cond.dose < 1 ? `Dosis auf ${Math.round(cond.dose * 100)} % reduziert.` : ""}</p>
      ${w.adapted.length ? `<p class="muted">Beschwerden berücksichtigt: ${
        w.adapted.map(esc).join("; ")}</p>` : ""}
      ${w.days.map((d) => `
        <div class="auto-day${d.sessions.length ? "" : " rest"}">
          <div class="ad">${esc(d.weekday)}</div>
          <div>
            ${d.sessions.length ? d.sessions.map((se) => `
              <div class="as">${esc(SPORT_LABEL[se.sport] || se.sport)} ·
                ${esc(se.kind)} · ${se.minutes} min</div>
              <div class="aw">${esc(se.why)}</div>`).join("")
              : '<div class="as">frei</div>'}
          </div>
        </div>`).join("")}
    </div>`;
}

$("#btnAutoSave").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await saveAutopilot(); toast("Gespeichert");
}));

$("#btnAutoPreview").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await saveAutopilot();
  renderAutoWeek(await api("/autopilot/preview"));
  const r = await api("/autopilot/explain", { method: "POST" });
  $("#autoAdvice").hidden = false;
  $("#autoAdvice").innerHTML = mdToHtml(r.message);
}));

$("#btnAutoApply").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await saveAutopilot();
  const w = await api("/autopilot/apply", { method: "POST" });
  renderAutoWeek(w);
  toast(`${w.created.length} Einheiten eingeplant`);
  loadDashboard();
}));

/* -------------------------------------------------- Coach-Vorschläge */

function renderSuggestions(list) {
  const card = $("#suggestCard");
  if (!list || !list.length) { card.hidden = true; return; }
  card.hidden = false;
  $("#suggestList").innerHTML = list.map((v) => `
    <div class="suggest" data-sid="${v.id}">
      <div class="st">${esc(v.title)}</div>
      <div class="sd">${esc(v.detail || "")}</div>
      ${v.trigger ? `<div class="sw">Anlass: ${esc(v.trigger)}</div>` : ""}
      <div class="row">
        ${v.payload && v.payload.action !== "advice"
          ? `<button class="btn small" data-apply="${v.id}">Übernehmen</button>` : ""}
        <button class="btn small ghost" data-dismiss="${v.id}">
          ${v.payload && v.payload.action !== "advice" ? "Verwerfen" : "Verstanden"}</button>
      </div>
    </div>`).join("");

  $$("[data-apply]").forEach((b) => b.addEventListener("click", (e) =>
    withSpinner(e.currentTarget, async () => {
      const r = await api(`/suggestions/${b.dataset.apply}/apply`, { method: "POST" });
      toast(r.planned_date
        ? `Eingeplant für ${fmtDate(r.planned_date)}`
        : "Übernommen — die nächste Einheit berücksichtigt es.");
      loadDashboard();
    })));
  $$("[data-dismiss]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/suggestions/${b.dataset.dismiss}/dismiss`, { method: "POST" });
      loadDashboard(); }
    catch (e) { toast(e.message, true); }
  }));
}

/* -------------------------------------------------------------- Score */

function scoreRing(el, value) {
  const size = 108, r = 44, c = 2 * Math.PI * r;
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value)) / 100;
  /* Farbe folgt dem Wert, nicht der Laune: unter 55 warnend, ab 80 gut */
  const color = value == null ? "var(--border)"
    : value >= 80 ? "var(--good)" : value >= 55 ? "var(--accent)" : "var(--warn)";
  el.innerHTML = `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
    <circle cx="54" cy="54" r="${r}" fill="none" stroke="var(--surface-2)" stroke-width="9"></circle>
    <circle cx="54" cy="54" r="${r}" fill="none" stroke="${color}" stroke-width="9"
      stroke-linecap="round" stroke-dasharray="${(c * pct).toFixed(1)} ${c.toFixed(1)}"
      transform="rotate(-90 54 54)"></circle>
    <text x="54" y="58" text-anchor="middle" font-size="26" font-family="var(--serif)"
      fill="var(--ink)">${value == null ? "–" : value}</text>
    <text x="54" y="74" text-anchor="middle" font-size="9" fill="var(--ink-3)">von 100</text>
  </svg>`;
}

function renderScore(d) {
  if (!d) return;
  scoreRing($("#scoreRing"), d.score);
  $("#scoreMood").textContent = `Der Coach ist ${d.mood}`;
  $("#scoreVerdict").textContent = d.verdict;

  $("#scorePillars").innerHTML = d.pillars.map((p) => {
    /* Achtung: 0 ist ein gültiger Wert — nicht mit || abfangen */
    const has = p.value != null;
    const cls = !has ? "none" : p.value >= 80 ? "good" : p.value >= 55 ? "ok" : "low";
    return `<div class="pillar ${cls}">
      <div class="pl">${esc(p.label)}</div>
      <div class="pv">${has ? p.value : "–"}</div>
      <div class="pbar"><span style="width:${has ? p.value : 0}%"></span></div>
      <div class="pw">${esc(p.why || "")}</div>
    </div>`;
  }).join("");

  $("#scorePotential").innerHTML = d.potential.slice(0, 3).map((p) => `
    <div class="finding ${p.missing ? "info" : p.gain > 8 ? "warn" : "info"}">
      <div class="t">${esc(p.title)}${p.gain > 0 ? ` <span class="muted">bis zu +${p.gain} Punkte</span>` : ""}</div>
      <div class="d">${esc(p.text)}</div>
      ${p.why ? `<div class="d muted">Aktuell: ${esc(p.why)}</div>` : ""}
    </div>`).join("");
}

/* ------------------------------------------------------ Garmin-Diagnose */

$("#btnDiagnose").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const d = await api("/garmin/diagnose");
  const mark = (ok) => ok === true ? "✓" : ok === false ? "✗" : "·";
  $("#diagnoseBody").innerHTML = `
    <div class="diag">${d.steps.map((s) => `
      <div class="row ${s.ok === false ? "bad" : s.ok === true ? "good" : ""}">
        <span class="m">${mark(s.ok)}</span>
        <span class="n">${esc(s.name)}</span>
        <span class="v">${esc(s.detail || "")}</span>
      </div>`).join("")}</div>
    <div class="detail-section"><h4>In der Datenbank</h4>
      <div class="diag">${Object.entries(d.counts).map(([k, v]) =>
        `<div class="row"><span class="m"></span><span class="n">${esc(k)}</span>
         <span class="v">${esc(String(v))}</span></div>`).join("")}</div>
      ${d.range && d.range.von ? `<p class="muted">Zeitraum: ${esc(d.range.von)} bis ${esc(d.range.bis)}</p>` : ""}
    </div>
    <div class="detail-section"><h4>Letzte Läufe</h4>
      <div class="diag">${(d.log || []).map((l) =>
        `<div class="row ${l.ok ? "" : "bad"}"><span class="m">${l.ok ? "✓" : "✗"}</span>
         <span class="n">${esc((l.ts || "").slice(5, 16))}</span>
         <span class="v">${esc(l.detail || "")}</span></div>`).join("")
        || '<p class="muted">Noch nichts protokolliert.</p>'}</div></div>`;
}));

$("#btnBackfillReset").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/garmin/backfill/reset", { method: "POST" });
  toast("Zurückgesetzt — der Import lässt sich wieder starten.");
  pollBackfill();
}));

/* ------------------------------------------------------------------- Coach */

function addBubble(kind, text, label) {
  const el = document.createElement("div");
  el.className = "bubble " + kind;
  el.innerHTML = (label ? `<div class="k">${label}</div>` : "") + esc(text);
  $("#chatLog").appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

async function ask(question) {
  addBubble("user", question);
  const pending = addBubble("coach", "Denke nach … (lokale KI, kann dauern)", "PULS");
  try {
    const r = await api("/coach/ask", { method: "POST", body: JSON.stringify({ question }) });
    pending.innerHTML = '<div class="k">PULS</div>' + mdToHtml(r.answer);
  } catch (e) {
    pending.innerHTML = '<div class="k">PULS</div>⚠️ ' + esc(e.message);
  }
}

$("#btnAsk").addEventListener("click", () => {
  const q = $("#chatInput").value.trim();
  if (!q) return;
  $("#chatInput").value = "";
  ask(q);
});
$("#chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#btnAsk").click(); });
$$("[data-quick]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.quick)));

async function loadCoach() {
  const tips = await api("/coach/research-tips?limit=10");
  $("#tipArchive").innerHTML = tips.length ? tips.map((t) =>
    `<div class="list-item"><div class="grow"><div class="title">${esc(t.topic || "Tipp")}</div>
     <div class="tip">${esc(t.content)}</div>
     <div class="meta">${fmtDate(t.created_at)}</div></div></div>`).join("") : "Noch keine Häppchen.";
}

/* ------------------------------------------------------------ Einstellungen */

let selectedGoals = [];

function renderGoalChips() {
  $("#goalChips").innerHTML = GOALS.map(([key, label]) =>
    `<button class="btn small ghost ${selectedGoals.includes(key) ? "on" : ""}" data-goal="${key}">${label}</button>`).join("");
  $$("#goalChips [data-goal]").forEach((b) => b.addEventListener("click", () => {
    const g = b.dataset.goal;
    selectedGoals = selectedGoals.includes(g) ? selectedGoals.filter((x) => x !== g) : [...selectedGoals, g];
    renderGoalChips();
  }));
}


/* ------------------------------------------------- Schriftgröße & Modell */

const FONT_SIZES = [
  { pct: 90, label: "Klein" }, { pct: 100, label: "Normal" },
  { pct: 112, label: "Groß" }, { pct: 125, label: "Größer" },
  { pct: 140, label: "Sehr groß" },
];

function applyFontScale(pct) {
  document.documentElement.style.setProperty("--fs", (16 * pct / 100).toFixed(1) + "px");
}

function renderFontChips(current) {
  $("#fontChips").innerHTML = FONT_SIZES.map((f) =>
    `<button class="btn small ghost ${f.pct === current ? "on" : ""}" data-font="${f.pct}">${f.label}</button>`).join("");
  $$("#fontChips [data-font]").forEach((b) => b.addEventListener("click", async () => {
    const pct = +b.dataset.font;
    applyFontScale(pct);
    renderFontChips(pct);
    try { await api("/settings", { method: "POST", body: JSON.stringify({ font_scale: pct }) }); }
    catch (e) { toast(e.message, true); }
  }));
}

let modelPoller = null;

async function loadModels() {
  let d;
  try { d = await api("/system/models"); }
  catch (e) { $("#modelList").textContent = "Modelle nicht abrufbar."; return; }

  if (!d.ollama_reachable) {
    $("#modelList").innerHTML = '<p class="muted">Ollama ist nicht erreichbar — läuft der Container puls-ollama?</p>';
    return;
  }

  $("#modelList").innerHTML = d.presets.map((m) => `
    <div class="model-item">
      <div class="info">
        <div class="name">${esc(m.label)}${m.active ? '<span class="cur">aktiv</span>' : ""}</div>
        <div class="meta">${m.size_gb} GB · ${esc(m.speed)}${m.installed ? " · geladen" : ""}</div>
        <div class="note">${esc(m.note)}</div>
      </div>
      ${m.active ? "" : `<button class="btn small ghost" data-model="${esc(m.name)}">
        ${m.installed ? "Verwenden" : "Laden"}</button>`}
    </div>`).join("");

  $$("[data-model]").forEach((b) => b.addEventListener("click", (e) =>
    withSpinner(e.currentTarget, async () => {
      const r = await api("/system/model", { method: "POST",
        body: JSON.stringify({ name: b.dataset.model }) });
      toast(r.status === "laedt"
        ? "Modell wird geladen — das dauert ein paar Minuten."
        : "Modell gewechselt.");
      loadModels();
      if (r.status === "laedt") startModelPolling();
    })));

  updatePullBar(d.pull);
}

function updatePullBar(p) {
  const bar = $("#pullBar");
  if (!p || p.status === "idle") { bar.hidden = true; $("#pullStatus").textContent = ""; return; }
  if (p.status === "laden") {
    bar.hidden = false;
    bar.firstElementChild.style.width = (p.percent || 0) + "%";
    $("#pullStatus").textContent =
      `${p.model} wird geladen — ${p.percent || 0} %${p.detail ? " (" + p.detail + ")" : ""}`;
  } else if (p.status === "fertig") {
    bar.hidden = true;
    $("#pullStatus").textContent = `${p.model} ist bereit.`;
  } else if (p.status === "fehler") {
    bar.hidden = true;
    $("#pullStatus").textContent = `Download fehlgeschlagen: ${p.error || ""}`;
  }
}

function startModelPolling() {
  if (modelPoller) clearInterval(modelPoller);
  modelPoller = setInterval(async () => {
    if (!$("#view-settings").classList.contains("active")) {
      clearInterval(modelPoller); modelPoller = null; return;
    }
    try {
      const p = await api("/system/model/progress");
      updatePullBar(p);
      if (p.status === "fertig" || p.status === "fehler") {
        clearInterval(modelPoller); modelPoller = null; loadModels();
      }
    } catch (e) { /* still */ }
  }, 2000);
}

const DAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
let runDays = [], gymDays = [];

function renderDayChips() {
  const build = (selected, attr) => DAYS.map((d) =>
    `<button class="btn small ghost ${selected.includes(d) ? "on" : ""}" data-${attr}="${d}">${d}</button>`).join("");
  $("#runDayChips").innerHTML = build(runDays, "runday");
  $("#gymDayChips").innerHTML = build(gymDays, "gymday");
  $$("#runDayChips [data-runday]").forEach((b) => b.addEventListener("click", () => {
    const d = b.dataset.runday;
    runDays = runDays.includes(d) ? runDays.filter((x) => x !== d) : [...runDays, d];
    runDays.sort((a, z) => DAYS.indexOf(a) - DAYS.indexOf(z));
    renderDayChips();
  }));
  $$("#gymDayChips [data-gymday]").forEach((b) => b.addEventListener("click", () => {
    const d = b.dataset.gymday;
    gymDays = gymDays.includes(d) ? gymDays.filter((x) => x !== d) : [...gymDays, d];
    gymDays.sort((a, z) => DAYS.indexOf(a) - DAYS.indexOf(z));
    renderDayChips();
  }));
}

async function loadSettings() {
  const [s, g, h] = await Promise.all([api("/settings"), api("/garmin/status"), api("/health")]);
  $("#versionInfo").innerHTML = h.version
    ? `Kennung <b>${esc(h.version)}</b> · Stand ${esc(h.built_at || "unbekannt")}`
    : "Diese Version meldet noch keine Kennung — das Update ist nicht angekommen.";
  pollBackfill();
  loadSupplementManager();      // zeigt einen laufenden Verlaufs-Import auch nach Neuladen
  loadAutopilot();
  selectedGoals = s.goals; renderGoalChips();
  runDays = s.run_days || []; gymDays = s.gym_days || []; renderDayChips();
  $("#setWeeklyTarget").value = s.weekly_workout_target;
  $("#setKcal").value = s.kcal_target;
  $("#setProtein").value = s.protein_target;
  $("#setProfile").value = s.profile.text || "";
  $("#setRunMin").value = s.run_minutes;
  $("#setGymMin").value = s.gym_minutes;
  $("#setPullupGoal").value = s.pullup_goal;
  $("#setRunGoalKm").value = s.run_goal_distance_km;
  $("#setRunGoalMin").value = s.run_goal_time_min;
  $("#setEveningMobility").checked = !!s.evening_mobility;
  $("#setPreferMachines").checked = !!s.prefer_machines;
  $("#apiToken").value = s.api_token || "";
  applyFontScale(s.font_scale || 100);
  renderFontChips(s.font_scale || 100);
  loadModels();

  $("#garminStatus").textContent = g.linked
    ? `Verbunden als ${g.email}. ${g.last_sync ? "Letzter Sync: " + new Date(g.last_sync.ts.replace(" ", "T") + "Z").toLocaleString("de-DE") + (g.last_sync.ok ? " – ok" : " – Fehler: " + g.last_sync.detail) : ""}`
    : "Nicht verbunden.";
  $("#garminLoginForm").hidden = g.linked;
  $("#garminLinkedBox").hidden = !g.linked;
  $("#systemStatus").innerHTML =
    `Lokale KI (Ollama): ${h.ollama ? "erreichbar" : "nicht erreichbar"}<br>` +
    `Aktives Modell: ${esc(h.model || "–")}${h.model_present ? " (geladen)" : h.ollama ? " (wird noch geladen)" : ""}<br>` +
    `Garmin: ${h.garmin_linked ? "verknüpft" : "–"}`;

  await loadBody();
  startScalePolling();
}

$("#btnCopyToken").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#apiToken").value); toast("Token kopiert"); }
  catch (e) { $("#apiToken").select(); toast("Bitte manuell kopieren", true); }
});

$("#btnSaveWeek").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/settings", { method: "POST", body: JSON.stringify({
    run_days: runDays, gym_days: gymDays,
    run_minutes: +$("#setRunMin").value || 25,
    gym_minutes: +$("#setGymMin").value || 75,
    pullup_goal: +$("#setPullupGoal").value || 10,
    run_goal_distance_km: +$("#setRunGoalKm").value || 10,
    run_goal_time_min: +$("#setRunGoalMin").value || 60,
    evening_mobility: $("#setEveningMobility").checked,
    prefer_machines: $("#setPreferMachines").checked,
  }) });
  toast("Wochenstruktur gespeichert"); loadDashboard();
}));

$("#btnSaveSettings").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/settings", { method: "POST", body: JSON.stringify({
    goals: selectedGoals,
    weekly_workout_target: +$("#setWeeklyTarget").value || 4,
    kcal_target: $("#setKcal").value, protein_target: $("#setProtein").value,
    profile: { text: $("#setProfile").value } }) });
  toast("Gespeichert"); loadDashboard();
}));

$("#btnGarminLogin").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/garmin/login", { method: "POST", body: JSON.stringify({
    email: $("#garminEmail").value, password: $("#garminPassword").value }) });
  if (r.status === "needs_mfa") { $("#garminMfaForm").hidden = false; toast("MFA-Code nötig — schau in Mails oder App"); }
  else { toast("Garmin verbunden"); $("#garminPassword").value = ""; loadSettings(); }
}));
$("#btnGarminMfa").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  await api("/garmin/mfa", { method: "POST", body: JSON.stringify({ code: $("#garminMfa").value }) });
  $("#garminMfaForm").hidden = true; $("#garminPassword").value = "";
  toast("Garmin verbunden"); loadSettings();
}));
$("#btnSyncNow").addEventListener("click", (e) => withSpinner(e.currentTarget, async () => {
  const r = await api("/garmin/sync", { method: "POST" });
  toast(r.ok ? "Sync fertig: " + r.detail : "Sync-Problem: " + r.detail, !r.ok);
  loadSettings(); loadDashboard();
}));
$("#btnUnlink").addEventListener("click", async () => {
  if (!confirm("Garmin-Verbindung wirklich trennen?")) return;
  await api("/garmin/unlink", { method: "POST" }); loadSettings();
});


/* ------------------------------------------------- Live-Status der Waage */

let scalePoller = null;

const SCALE_STATES = {
  offline:      { dot: "err",  title: "Dienst nicht erreichbar" },
  no_adapter:   { dot: "err",  title: "Kein Bluetooth-Adapter" },
  not_scanning: { dot: "warn", title: "Scan steht" },
  searching:    { dot: "warn pulse", title: "Scan läuft — warte auf die Waage" },
  scale_found:  { dot: "ok pulse", title: "Waage wird empfangen" },
  ok:           { dot: "ok",   title: "Alles verbunden" },
};

async function refreshScale() {
  let d;
  try { d = await api("/scale/status"); }
  catch (e) { return; }
  const meta = SCALE_STATES[d.state] || SCALE_STATES.offline;
  $("#scaleDot").className = "live-dot " + meta.dot;
  $("#scaleTitle").textContent = meta.title;
  $("#scaleHint").textContent = d.hint || "";

  const rep = d.report || {};
  const hasReport = d.age_s !== null && d.age_s < 60;
  $("#scaleMetrics").hidden = !hasReport;
  if (hasReport) {
    $("#scaleAdv").textContent = rep.advertisements ?? 0;
    $("#scaleFrames").textContent = rep.scale_frames ?? 0;
    $("#scaleMeas").textContent = rep.measurements ?? 0;
  }

  const last = d.last_measurement;
  $("#scaleLast").innerHTML = last
    ? `Letzte Messung: <b style="color:var(--ink)">${last.weight_kg} kg</b>` +
      `${last.body_fat_pct ? ` · ${last.body_fat_pct} % Körperfett` : ""}` +
      ` · ${fmtDate(last.day)}`
    : "Noch keine Messung eingegangen.";

  const devs = rep.devices || [];
  $("#scaleDeviceList").innerHTML = devs.length ? devs.map((x) => `
    <div class="dev-row ${x.is_scale ? "is-scale" : ""}">
      <span class="mac">${esc(x.mac)}</span>
      <span>${esc(x.name || "")}</span>
      ${x.is_scale ? '<span class="tag">Waage</span>' : ""}
      ${x.last_weight ? `<span>${x.last_weight} kg</span>` : ""}
      <span class="rssi">${x.rssi ?? "–"} dBm · vor ${x.seconds_ago}s</span>
    </div>`).join("")
    : "Noch keine Geräte empfangen.";

  if (rep.adapter && rep.adapter.address) {
    $("#scaleDeviceList").insertAdjacentHTML("beforebegin", "");
  }
}

function startScalePolling() {
  refreshScale();
  if (scalePoller) clearInterval(scalePoller);
  scalePoller = setInterval(() => {
    if ($("#view-settings").classList.contains("active")) refreshScale();
    else { clearInterval(scalePoller); scalePoller = null; }
  }, 3000);
}

/* -------------------------------------------------------------- Navigation */

const LOADERS = {
  dashboard: loadDashboard, plan: loadPlan, exercises: loadExercises,
  nutrition: loadNutrition, mood: loadMood, stats: loadStatsAll,
  coach: loadCoach,
  settings: loadSettings,
};

function goto(view) {
  $$(".view").forEach((v) => v.classList.remove("active"));
  $("#view-" + view).classList.add("active");
  $$("nav.bottom button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  Promise.resolve((LOADERS[view] || (() => {}))()).catch((e) => toast(e.message, true));
  window.scrollTo({ top: 0 });
}

$$("nav.bottom button").forEach((b) => b.addEventListener("click", () => goto(b.dataset.view)));
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) { e.preventDefault(); goto(g.dataset.goto); }
});

/* -------------------------------------------------------------------- Init */

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
$("#nutDay").value = $("#bodyDay").value = new Date().toISOString().slice(0, 10);
api("/settings").then((s) => applyFontScale(s.font_scale || 100)).catch(() => {});
loadDashboard().catch((e) => toast(e.message, true));

async function loadStatsAll() {
  await loadStatsMetrics();
  await loadStats();
}
