/* Eigenständig: Was die Diagramme brauchen, bringen sie selbst mit.
   Diese drei Helfer standen einmal in app.js — charts.js lief damit nur,
   solange app.js zufaellig vorher geladen war und sie noch enthielt. Eine
   Kopplung, die erst im Browser auffiel, und dort als leeres Diagramm. */

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

let _tipNode = null;

function _tip() {
  if (!_tipNode) {
    _tipNode = document.createElement("div");
    _tipNode.className = "tooltip";
    document.body.append(_tipNode);
  }
  return _tipNode;
}

function showTip(x, y, html) {
  const tip = _tip();
  tip.innerHTML = html;
  tip.style.left = `${Math.min(x, window.innerWidth - 160)}px`;
  tip.style.top = `${Math.max(8, y - 8)}px`;
  tip.classList.add("show");
}

function hideTip() {
  if (_tipNode) _tipNode.classList.remove("show");
}

/* PULS — Diagramme und Karte. Vanilla JS, keine Abhängigkeiten.

   Ergänzt die einfachen Diagramme aus app.js (barChart, lineChart) um das,
   was die Laufansicht braucht: mehrere Kurven mit gemeinsamer Zeitachse und
   Fadenkreuz, eine Karte, Kilometerbalken und Tagesverläufe.

   Zur Karte: eine unbewegliche Karte braucht keine Kartenbibliothek. Es
   genügt, die Kachelnummern für den Ausschnitt auszurechnen und die Bilder
   an die richtige Stelle zu legen — das sind ein paar Zeilen statt 150 kB
   Fremdcode. Die Kacheln lädt der Browser nur, wenn du sie in den
   Einstellungen zuschaltest; ohne sie zeichnet PULS bloß die Spur. */
"use strict";

const SVG_W = 720;

function niceTime(sec) {
  if (sec == null) return "–";
  const m = Math.floor(sec / 60), s = Math.round(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function paceText(secPerKm) {
  return secPerKm == null ? "–" : `${niceTime(secPerKm)} /km`;
}

/* Rundet eine Achsenbeschriftung auf einen lesbaren Wert. */
function niceStep(span, count) {
  const raw = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  return [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => s >= raw) || mag * 10;
}

/* ------------------------------------------------------------- Laufprofil */

/* Mehrere Kurven untereinander, eine gemeinsame Zeitachse, ein Fadenkreuz,
   das über alle Bahnen gleichzeitig läuft. */
function runProfile(container, series, opts = {}) {
  const tracks = (opts.tracks || []).filter(
    (t) => Array.isArray(series[t.key]) && series[t.key].some((v) => v != null));
  if (!tracks.length || !series.t) {
    container.innerHTML = '<p class="muted">Für diese Einheit hat die Uhr keine Verlaufsdaten aufgezeichnet.</p>';
    return;
  }

  const t = series.t;
  const n = t.length;
  const padL = 46, padR = 12, padT = 12, gap = 14;
  const trackH = opts.height || 96;
  const H = tracks.length * (trackH + gap) + 22;
  const X = (i) => padL + (i * (SVG_W - padL - padR)) / Math.max(1, n - 1);

  let body = "";
  const layout = [];

  tracks.forEach((track, ti) => {
    const values = series[track.key];
    const known = values.filter((v) => v != null);
    let min = Math.min(...known), max = Math.max(...known);
    if (track.zeroBased) min = Math.min(0, min);
    if (max - min < 1e-6) { max = min + 1; }
    const pad = (max - min) * 0.12;
    min -= pad; max += pad;
    const top = padT + ti * (trackH + gap);
    const Y = (v) => top + trackH - ((v - min) * trackH) / (max - min);
    layout.push({ track, values, Y, top, min, max });

    /* Lücken (Tunnel, Signalverlust) trennen die Linie, statt sie zu erfinden */
    let d = "", open = false;
    values.forEach((v, i) => {
      if (v == null) { open = false; return; }
      d += `${open ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)} `;
      open = true;
    });

    const first = values.findIndex((v) => v != null);
    const last = values.length - 1 - [...values].reverse().findIndex((v) => v != null);
    const areaId = `grad-${track.key}`;
    let area = "";
    if (track.fill && first >= 0) {
      area = `<path d="${d} L${X(last).toFixed(1)},${top + trackH} L${X(first).toFixed(1)},${top + trackH} Z"
        fill="url(#${areaId})" stroke="none"></path>`;
    }

    const labels = [min + pad, (min + max) / 2, max - pad].map((v) =>
      `<text x="${padL - 6}" y="${(Y(v) + 3).toFixed(1)}" font-size="10"
        fill="var(--ink-3)" text-anchor="end">${track.fmtAxis ? track.fmtAxis(v) : Math.round(v)}</text>
       <line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${SVG_W - padR}" y2="${Y(v).toFixed(1)}"
        stroke="var(--border-soft)"></line>`).join("");

    body += `<defs><linearGradient id="${areaId}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="${track.color}" stop-opacity="0.28"></stop>
        <stop offset="100%" stop-color="${track.color}" stop-opacity="0"></stop>
      </linearGradient></defs>
      ${labels}${area}
      <path d="${d}" fill="none" stroke="${track.color}" stroke-width="1.8"
        stroke-linejoin="round" stroke-linecap="round"></path>
      <text x="${padL}" y="${(top - 2).toFixed(1)}" font-size="10.5"
        fill="var(--ink-2)" letter-spacing="0.04em">${track.label}</text>`;
  });

  /* Zeitachse */
  const totalSec = t[n - 1] || 0;
  const step = niceStep(totalSec, 5);
  let axis = "";
  for (let s = 0; s <= totalSec; s += step) {
    const i = t.findIndex((v) => v >= s);
    if (i < 0) break;
    axis += `<text x="${X(i).toFixed(1)}" y="${H - 4}" font-size="10"
      fill="var(--ink-3)" text-anchor="middle">${niceTime(s)}</text>`;
  }

  container.innerHTML = `<svg viewBox="0 0 ${SVG_W} ${H}" class="profile" role="img"
      aria-label="Verlauf der Einheit">
      ${body}${axis}
      <line id="cross" x1="0" y1="${padT}" x2="0" y2="${H - 20}"
        stroke="var(--ink-3)" stroke-width="1" style="display:none"></line>
      <rect id="grab" x="${padL}" y="0" width="${SVG_W - padL - padR}" height="${H - 18}"
        fill="transparent"></rect>
    </svg>`;

  const svg = container.querySelector("svg");
  const cross = svg.querySelector("#cross");
  const grab = svg.querySelector("#grab");

  function at(ev) {
    const box = svg.getBoundingClientRect();
    const rel = ((ev.clientX - box.left) / box.width) * SVG_W;
    const i = Math.round(((rel - padL) / (SVG_W - padL - padR)) * (n - 1));
    return Math.max(0, Math.min(n - 1, i));
  }

  grab.addEventListener("pointermove", (ev) => {
    const i = at(ev);
    cross.setAttribute("x1", X(i).toFixed(1));
    cross.setAttribute("x2", X(i).toFixed(1));
    cross.style.display = "";
    const rows = layout.map(({ track, values }) => {
      const v = values[i];
      return v == null ? "" :
        `<span class="t-label">${track.label}</span> <b>${track.fmt ? track.fmt(v) : Math.round(v)}</b>`;
    }).filter(Boolean).join("<br>");
    showTip(ev.clientX, ev.clientY - 12,
      `<span class="t-label">bei ${niceTime(t[i])}</span><br>${rows}`);
    if (opts.onHover) opts.onHover(i);
  });
  grab.addEventListener("pointerleave", () => {
    cross.style.display = "none";
    hideTip();
    if (opts.onHover) opts.onHover(null);
  });
}

/* ------------------------------------------------------------------ Karte */

const TILE = 256;

function lonToX(lon, z) { return ((lon + 180) / 360) * Math.pow(2, z); }
function latToY(lat, z) {
  const r = (lat * Math.PI) / 180;
  return ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * Math.pow(2, z);
}

/* Größter Zoom, bei dem der Ausschnitt noch in die Fläche passt. */
function fitZoom(bounds, w, h) {
  for (let z = 17; z >= 2; z--) {
    const dx = (lonToX(bounds.max_lon, z) - lonToX(bounds.min_lon, z)) * TILE;
    const dy = (latToY(bounds.min_lat, z) - latToY(bounds.max_lat, z)) * TILE;
    if (dx <= w && dy <= h) return z;
  }
  return 2;
}

/* Zeichnet die Strecke. Mit values wird sie nach Wert eingefärbt (Puls,
   Tempo), mit tiles=true liegt eine echte Karte darunter. */
function routeMap(container, track, bounds, opts = {}) {
  if (!track || track.length < 2 || !bounds) {
    container.innerHTML = '<p class="muted">Für diese Einheit gibt es keine GPS-Spur.</p>';
    return;
  }
  const W = 720, H = opts.height || 420, pad = 16;
  const z = fitZoom(bounds, W - pad * 2, H - pad * 2);
  const scale = Math.pow(2, z) * TILE;

  const px = (p) => lonToX(p.lon, z) * TILE;
  const py = (p) => latToY(p.lat, z) * TILE;
  const xs = track.map(px), ys = track.map(py);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  /* Ausschnitt mittig legen */
  const offX = (W - (maxX - minX)) / 2 - minX;
  const offY = (H - (maxY - minY)) / 2 - minY;
  const X = (i) => xs[i] + offX;
  const Y = (i) => ys[i] + offY;

  let tiles = "";
  if (opts.tiles) {
    const x0 = Math.floor((-offX) / TILE), x1 = Math.floor((W - offX) / TILE);
    const y0 = Math.floor((-offY) / TILE), y1 = Math.floor((H - offY) / TILE);
    const span = Math.pow(2, z);
    for (let tx = x0; tx <= x1; tx++) {
      for (let ty = y0; ty <= y1; ty++) {
        if (ty < 0 || ty >= span) continue;
        const wrapped = ((tx % span) + span) % span;
        tiles += `<image href="https://tile.openstreetmap.org/${z}/${wrapped}/${ty}.png"
          x="${(tx * TILE + offX).toFixed(1)}" y="${(ty * TILE + offY).toFixed(1)}"
          width="${TILE}" height="${TILE}" opacity="0.75"></image>`;
      }
    }
  }

  /* Einfärbung nach Wert: die Spur wird in Abschnitte zerlegt. Ohne Werte
     bleibt sie einfarbig — das ist der ruhigere Normalfall. */
  let line = "";
  const values = opts.values;
  if (values && values.length) {
    const known = values.filter((v) => v != null);
    const lo = Math.min(...known), hi = Math.max(...known);
    const stops = opts.palette || ["#3d8b82", "#5a9e73", "#c9973f", "#c8763c", "#c85f52"];
    for (let i = 1; i < track.length; i++) {
      const v = values[Math.floor((i / track.length) * values.length)];
      const f = v == null || hi === lo ? 0.5 : (v - lo) / (hi - lo);
      const color = stops[Math.min(stops.length - 1, Math.floor(f * stops.length))];
      line += `<line x1="${X(i - 1).toFixed(1)}" y1="${Y(i - 1).toFixed(1)}"
        x2="${X(i).toFixed(1)}" y2="${Y(i).toFixed(1)}" stroke="${color}"
        stroke-width="3.2" stroke-linecap="round"></line>`;
    }
  } else {
    const d = track.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(i).toFixed(1)}`).join(" ");
    line = `<path d="${d}" fill="none" stroke="var(--accent)" stroke-width="3"
      stroke-linejoin="round" stroke-linecap="round"></path>`;
  }

  const marker = (i, fill, label) =>
    `<circle cx="${X(i).toFixed(1)}" cy="${Y(i).toFixed(1)}" r="5" fill="${fill}"
      stroke="var(--bg)" stroke-width="2"><title>${label}</title></circle>`;

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="routemap" role="img"
      aria-label="Streckenverlauf">
      <rect width="${W}" height="${H}" fill="var(--surface-2)"></rect>
      ${tiles}${line}
      ${marker(0, "var(--good)", "Start")}
      ${marker(track.length - 1, "var(--bad)", "Ziel")}
      <circle id="here" r="6" fill="var(--ink)" stroke="var(--bg)" stroke-width="2"
        style="display:none"></circle>
    </svg>
    ${opts.tiles ? '<p class="map-credit">Karte © OpenStreetMap-Mitwirkende</p>' : ""}`;

  /* Erlaubt der Laufkurve, den Punkt auf der Karte mitzuführen */
  const here = container.querySelector("#here");
  return function highlight(fraction) {
    if (fraction == null) { here.style.display = "none"; return; }
    const i = Math.max(0, Math.min(track.length - 1, Math.round(fraction * (track.length - 1))));
    here.setAttribute("cx", X(i).toFixed(1));
    here.setAttribute("cy", Y(i).toFixed(1));
    here.style.display = "";
  };
}

/* --------------------------------------------------------- Kilometerzeiten */

function splitChart(container, splits, opts = {}) {
  const rows = (splits || []).filter((s) => s.seconds);
  if (rows.length < 2) { container.innerHTML = ""; return; }
  const W = 720, H = 150, padL = 44, padB = 20, padT = 10;
  const times = rows.map((s) => s.seconds);
  const slowest = Math.max(...times), fastest = Math.min(...times);
  const span = Math.max(1, slowest - fastest);
  const iw = (W - padL - 8) / rows.length;
  const bw = Math.max(6, Math.min(46, iw - 6));

  let bars = "";
  rows.forEach((s, i) => {
    /* Höhe relativ zum langsamsten Kilometer — schnellere Kilometer stehen
       höher, das ist die Leserichtung, die man erwartet. */
    const f = 0.25 + 0.75 * ((slowest - s.seconds) / span);
    const h = Math.round((H - padB - padT) * f);
    const x = padL + i * iw + (iw - bw) / 2;
    const y = H - padB - h;
    const fill = s.seconds === fastest ? "var(--accent)" : "var(--teal)";
    bars += `<rect data-i="${i}" x="${x.toFixed(1)}" y="${y}" width="${bw.toFixed(1)}"
        height="${h}" rx="2" fill="${fill}" opacity="0.9"></rect>
      <text x="${(x + bw / 2).toFixed(1)}" y="${y - 4}" font-size="10"
        fill="var(--ink-2)" text-anchor="middle">${niceTime(s.seconds)}</text>
      <text x="${(x + bw / 2).toFixed(1)}" y="${H - 5}" font-size="10"
        fill="var(--ink-3)" text-anchor="middle">${s.label}</text>`;
  });

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
    aria-label="Kilometerzeiten">${bars}</svg>`;
  container.querySelectorAll("rect").forEach((r) => {
    r.addEventListener("pointerenter", (ev) => {
      const s = rows[+r.dataset.i];
      const box = r.getBoundingClientRect();
      showTip(box.left + box.width / 2, box.top,
        `<span class="t-label">${esc(s.label)}</span><br><b>${paceText(s.seconds)}</b>` +
        (s.hr ? `<br>${Math.round(s.hr)} bpm` : ""));
    });
    r.addEventListener("pointerleave", hideTip);
  });
}

/* ------------------------------------------------------------ Tagesverlauf */

/* Für Stress und Body Battery: ein Tag von 0 bis 24 Uhr. */
function dayCurve(container, pairs, opts = {}) {
  const points = (pairs || []).filter((p) => Array.isArray(p) && p[1] != null);
  if (points.length < 3) {
    container.innerHTML = `<p class="muted">${opts.empty || "Noch keine Daten für diesen Tag."}</p>`;
    return;
  }
  const W = 720, H = opts.height || 130, padL = 32, padB = 18, padT = 8;
  const first = points[0][0], last = points[points.length - 1][0];
  const span = Math.max(1, last - first);
  const max = opts.max || Math.max(...points.map((p) => p[1]));
  const X = (ts) => padL + ((ts - first) / span) * (W - padL - 10);
  const Y = (v) => H - padB - (v / max) * (H - padB - padT);

  const d = points.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ");
  const area = `${d} L${X(last).toFixed(1)},${H - padB} L${X(first).toFixed(1)},${H - padB} Z`;
  const color = opts.color || "var(--teal)";

  /* Stundenraster, damit man sieht, wann etwas passiert ist */
  let ticks = "";
  for (let h = 0; h < 24; h += 6) {
    const ts = first + (h / 24) * span;
    ticks += `<text x="${X(ts).toFixed(1)}" y="${H - 4}" font-size="10"
      fill="var(--ink-3)" text-anchor="middle">${String(h).padStart(2, "0")}:00</text>`;
  }
  const bands = (opts.bands || []).map((b) =>
    `<rect x="${padL}" y="${Y(b.to).toFixed(1)}" width="${W - padL - 10}"
      height="${(Y(b.from) - Y(b.to)).toFixed(1)}" fill="${b.color}" opacity="0.10"></rect>`).join("");

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(opts.label || "Tagesverlauf")}">
      <defs><linearGradient id="dc" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.3"></stop>
        <stop offset="100%" stop-color="${color}" stop-opacity="0"></stop>
      </linearGradient></defs>
      ${bands}
      <path d="${area}" fill="url(#dc)"></path>
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.8"
        stroke-linejoin="round"></path>
      ${ticks}
    </svg>`;
}


/* --------------------------------------------------------- Sparkline */

/* Der knappe Verlauf neben einer Kachel: keine Achsen, keine Beschriftung,
   nur die Richtung. Wer den genauen Wert braucht, öffnet das große Diagramm. */
function sparkline(values, opts = {}) {
  const points = (values || []).filter((v) => v != null);
  if (points.length < 2) return "";
  const W = 120, H = 26, pad = 2;
  let min = Math.min(...points), max = Math.max(...points);
  if (max - min < 1e-9) { min -= 1; max += 1; }
  const X = (i) => (i * W) / (points.length - 1);
  const Y = (v) => H - pad - ((v - min) / (max - min)) * (H - pad * 2);
  const d = points.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const color = opts.color || "var(--ink-3)";
  const last = points[points.length - 1];
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.4"
      stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"></path>
    <circle cx="${X(points.length - 1).toFixed(1)}" cy="${Y(last).toFixed(1)}" r="2"
      fill="${color}"></circle>
  </svg>`;
}


/* ----------------------------------------------------- Vergleichsbalken */

/* Zwei Werte nebeneinander: "an Tagen mit viel X" gegen "an Tagen mit wenig X".
   Ehrlicher als eine Korrelationszahl, die niemand einordnen kann — man sieht
   sofort, ob der Unterschied gross oder klein ist. */
function splitBars(container, findings, opts = {}) {
  if (!findings || !findings.length) { container.innerHTML = ""; return; }
  const rows = findings.slice(0, opts.limit || 4);
  const W = 720, rowH = 54, padL = 4, labelW = 0;
  const H = rows.length * rowH + 8;

  let body = "";
  rows.forEach((f, i) => {
    const top = i * rowH + 4;
    const max = Math.max(f.low, f.high) * 1.15 || 1;
    const barW = (v) => Math.max(2, (v / max) * (W - 210));
    const helps = f.direction === "helps";
    const hi = helps ? "var(--good)" : "var(--warn)";
    const lo = "var(--ink-3)";

    body += `
      <text x="${padL}" y="${top + 11}" font-size="11" fill="var(--ink-2)">
        ${esc(f.driver_label)} → ${esc(f.target_label)}</text>

      <rect x="${padL}" y="${top + 18}" width="${barW(f.high).toFixed(1)}" height="9"
        rx="2" fill="${hi}" opacity="0.9"></rect>
      <text x="${(padL + barW(f.high) + 7).toFixed(1)}" y="${top + 26}" font-size="10.5"
        fill="var(--ink-2)">${f.high}${esc(f.target_unit)} · viel ${esc(f.driver_label)}</text>

      <rect x="${padL}" y="${top + 31}" width="${barW(f.low).toFixed(1)}" height="9"
        rx="2" fill="${lo}" opacity="0.55"></rect>
      <text x="${(padL + barW(f.low) + 7).toFixed(1)}" y="${top + 39}" font-size="10.5"
        fill="var(--ink-3)">${f.low}${esc(f.target_unit)} · wenig</text>`;
  });

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="splitbars" role="img"
    aria-label="Vergleich nach Einflussgröße">${body}</svg>`;
}


/* ------------------------------------------------- Verlauf mit Basislinie */

/* Eine Linie vor einem Band. Das Band ist dein Normalbereich — damit ist auf
   einen Blick zu sehen, wann ein Wert darueber oder darunter lag. Vier kleine
   Kurven nebeneinander sagen das nicht; sie zeigen Zacken ohne Massstab. */
function baselineChart(container, points, opts = {}) {
  const data = (points || []).filter((p) => p.value != null);
  if (data.length < 3) {
    container.innerHTML = `<p class="muted">${opts.empty || "Noch zu wenige Werte."}</p>`;
    return;
  }
  const W = 720, H = opts.height || 150, padL = 40, padR = 12, padT = 12, padB = 22;
  const values = data.map((p) => p.value);
  const base = opts.baseline;
  const spread = opts.spread || (Math.max(...values) - Math.min(...values)) * 0.25 || 1;

  let min = Math.min(...values, base != null ? base - spread : Infinity);
  let max = Math.max(...values, base != null ? base + spread : -Infinity);
  const pad = (max - min) * 0.12 || 1;
  min -= pad; max += pad;

  const X = (i) => padL + (i * (W - padL - padR)) / Math.max(1, data.length - 1);
  const Y = (v) => H - padB - ((v - min) / (max - min)) * (H - padB - padT);

  /* Das Normalband: Basislinie plus/minus die uebliche Schwankung */
  let band = "";
  if (base != null) {
    const top = Y(base + spread), bottom = Y(base - spread);
    band = `<rect x="${padL}" y="${top.toFixed(1)}" width="${W - padL - padR}"
        height="${Math.max(1, bottom - top).toFixed(1)}"
        fill="var(--ink-3)" opacity="0.10"></rect>
      <line x1="${padL}" y1="${Y(base).toFixed(1)}" x2="${W - padR}"
        y2="${Y(base).toFixed(1)}" stroke="var(--ink-3)" stroke-width="1"
        stroke-dasharray="none" opacity="0.5"></line>
      <text x="${W - padR}" y="${(Y(base) - 4).toFixed(1)}" font-size="10"
        fill="var(--ink-3)" text-anchor="end">dein Schnitt ${
          opts.fmt ? opts.fmt(base) : Math.round(base)}</text>`;
  }

  const d = data.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`).join(" ");
  const color = opts.color || "var(--accent)";

  /* Punkte nur dort, wo der Wert das Band verlaesst — das sind die Tage,
     auf die es ankommt. */
  let marks = "";
  if (base != null) {
    data.forEach((p, i) => {
      const off = p.value > base + spread ? 1 : p.value < base - spread ? -1 : 0;
      if (!off) return;
      const good = opts.lowerIsBetter ? off < 0 : off > 0;
      marks += `<circle cx="${X(i).toFixed(1)}" cy="${Y(p.value).toFixed(1)}" r="3"
        fill="${good ? "var(--good)" : "var(--warn)"}"></circle>`;
    });
  }

  const step = Math.max(1, Math.floor(data.length / 5));
  let axis = "";
  for (let i = 0; i < data.length; i += step) {
    axis += `<text x="${X(i).toFixed(1)}" y="${H - 6}" font-size="10"
      fill="var(--ink-3)" text-anchor="middle">${esc(data[i].label || "")}</text>`;
  }
  const labels = [min + pad, max - pad].map((v) =>
    `<text x="${padL - 6}" y="${(Y(v) + 3).toFixed(1)}" font-size="10"
      fill="var(--ink-3)" text-anchor="end">${opts.fmt ? opts.fmt(v) : Math.round(v)}</text>`
  ).join("");

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(opts.label || "Verlauf")}">
      ${band}${labels}
      <path d="${d}" fill="none" stroke="${color}" stroke-width="1.8"
        stroke-linejoin="round" stroke-linecap="round"></path>
      ${marks}${axis}
    </svg>`;
}


/* ------------------------------------------------------- Zusammenhangsbalken */

/* Ein Balken je Wertepaar, von der Mitte aus: nach rechts gleichläufig, nach
   links gegenläufig, die Länge ist die Stärke. So ist die Rangfolge auf einen
   Blick zu sehen, ohne dass man Korrelationskoeffizienten lesen muss. */
function correlationBars(container, pairs, opts = {}) {
  const rows = (pairs || []).slice(0, opts.limit || 20);
  if (!rows.length) { container.innerHTML = ""; return; }
  const W = 720, rowH = 26, mid = 330, maxBar = 150;
  const H = rows.length * rowH + 20;

  let body = `<line x1="${mid}" y1="14" x2="${mid}" y2="${H - 8}"
      stroke="var(--border)" stroke-width="1"></line>
    <text x="${mid - maxBar}" y="10" font-size="9.5" fill="var(--ink-3)">gegenläufig</text>
    <text x="${mid + maxBar}" y="10" font-size="9.5" fill="var(--ink-3)"
      text-anchor="end">gleichläufig</text>`;

  rows.forEach((p, i) => {
    const y = 20 + i * rowH;
    const len = Math.abs(p.r) * maxBar;
    const x = p.r > 0 ? mid : mid - len;
    const robust = p.robust;
    const color = robust ? (p.r > 0 ? "var(--teal)" : "var(--accent)") : "var(--ink-3)";
    body += `
      <text x="${mid - maxBar - 10}" y="${y + 11}" font-size="11"
        fill="${robust ? "var(--ink-2)" : "var(--ink-3)"}" text-anchor="end">
        ${esc(p.a_label)} ↔ ${esc(p.b_label)}</text>
      <rect x="${x.toFixed(1)}" y="${y + 3}" width="${len.toFixed(1)}" height="14"
        rx="2" fill="${color}" opacity="${robust ? 0.85 : 0.4}"></rect>
      <text x="${mid + maxBar + 10}" y="${y + 14}" font-size="10.5"
        fill="var(--ink-3)">r=${p.r} · n=${p.n}${robust ? "" : " · schwach"}</text>`;
  });

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="corrbars" role="img"
    aria-label="Zusammenhänge zwischen Messwerten">${body}</svg>`;
}


/* ------------------------------------------------- Zeitachse mit Bereichen */

/* Diagramme über einer echten Zeitachse: Ein Punkt liegt dort, wo er zeitlich
   hingehört, nicht auf einem gleichmäßigen Raster. Für den Gemütsverlauf ist
   das der ganze Unterschied — drei Einträge um 7, 13 und 22 Uhr sind kein
   Drittel-Drittel-Drittel, und zwei Tage ohne Eintrag sind eine Lücke, kein
   nahtloser Strich.

   Die Beschriftung richtet sich nach der Spanne: Stunden bei einem Tag,
   Wochentage bei einer Woche, Datum bei einem Monat oder mehr. */

const RANGE_MS = {
  day: 24 * 3600e3,
  week: 7 * 24 * 3600e3,
  month: 30 * 24 * 3600e3,
  quarter: 91 * 24 * 3600e3,
  year: 365 * 24 * 3600e3,
};

const RANGE_LABEL = { day: "Tag", week: "Woche", month: "Monat",
                      quarter: "3 Monate", year: "Jahr" };

const WEEKDAY_SHORT = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

/* Wie die Achse bei dieser Spanne beschriftet wird — und wie ein einzelner
   Punkt im Tooltip heißt. */
function timeAxis(spanMs) {
  const hours = spanMs / 3600e3;
  if (hours <= 36) {
    return {
      stepMs: hours <= 8 ? 3600e3 : hours <= 14 ? 2 * 3600e3 : 4 * 3600e3,
      tick: (d) => `${String(d.getHours()).padStart(2, "0")}:00`,
      point: (d) => `${WEEKDAY_SHORT[d.getDay()]} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
      unitName: "Stunden",
    };
  }
  if (hours <= 24 * 10) {
    return {
      stepMs: 24 * 3600e3,
      tick: (d) => `${WEEKDAY_SHORT[d.getDay()]} ${d.getDate()}.`,
      point: (d) => `${WEEKDAY_SHORT[d.getDay()]}, ${d.getDate()}.${d.getMonth() + 1}. ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
      unitName: "Tage",
    };
  }
  if (hours <= 24 * 75) {
    return {
      stepMs: 7 * 24 * 3600e3,
      tick: (d) => `${d.getDate()}.${d.getMonth() + 1}.`,
      point: (d) => `${WEEKDAY_SHORT[d.getDay()]}, ${d.getDate()}.${d.getMonth() + 1}.`,
      unitName: "Wochen",
    };
  }
  const MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                  "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
  return {
    stepMs: 30 * 24 * 3600e3,
    tick: (d) => MONTHS[d.getMonth()],
    point: (d) => `${d.getDate()}. ${MONTHS[d.getMonth()]} ${d.getFullYear()}`,
    unitName: "Monate",
  };
}

/* Rasterlinien auf runde Zeitpunkte legen: volle Stunden bzw. Mitternacht.
   Sonst stünde "13:47" an der Achse, und niemand liest daran etwas ab. */
function timeTicks(from, to, axis) {
  const out = [];
  const start = new Date(from);
  if (axis.stepMs >= 24 * 3600e3) start.setHours(0, 0, 0, 0);
  else start.setMinutes(0, 0, 0);
  for (let t = start.getTime(); t <= to; t += axis.stepMs) {
    if (t >= from) out.push(t);
    if (out.length > 14) break;
  }
  return out;
}

/* points: [{ t: Millisekunden, value, label?, tip? }]
   series: mehrere Linien als [{ key, label, color, points }] */
function timeChart(container, series, opts = {}) {
  const lines = (series || []).filter((s) => s.points && s.points.length);
  if (!lines.length) {
    container.innerHTML = `<p class="muted">${esc(opts.empty || "Für diesen Zeitraum liegt nichts vor.")}</p>`;
    return;
  }
  const W = 720, H = opts.height || 190;
  const padL = 40, padR = 12, padT = 12, padB = opts.legend === false ? 22 : 34;

  const all = lines.flatMap((s) => s.points);
  const from = opts.from ?? Math.min(...all.map((p) => p.t));
  const to = opts.to ?? Math.max(...all.map((p) => p.t));
  const span = Math.max(60e3, to - from);

  let min = opts.min ?? Math.min(...all.map((p) => p.value));
  let max = opts.max ?? Math.max(...all.map((p) => p.value));
  if (max - min < 1e-9) { min -= 1; max += 1; }
  const pad = (max - min) * 0.12;
  min -= pad; max += pad;

  const X = (t) => padL + ((t - from) / span) * (W - padL - padR);
  const Y = (v) => H - padB - ((v - min) * (H - padB - padT)) / (max - min);

  const axis = timeAxis(span);
  const ticks = timeTicks(from, to, axis).map((t) =>
    `<line x1="${X(t).toFixed(1)}" y1="${padT}" x2="${X(t).toFixed(1)}"
       y2="${H - padB}" stroke="var(--border)" stroke-dasharray="2 4"></line>
     <text x="${X(t).toFixed(1)}" y="${H - padB + 13}" font-size="10"
       fill="var(--ink-3)" text-anchor="middle">${esc(axis.tick(new Date(t)))}</text>`
  ).join("");

  const gridY = [min + (max - min) * 0.5, max - (max - min) * 0.12].map((v) =>
    `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${W - padR}" y2="${Y(v).toFixed(1)}"
       stroke="var(--border)"></line>
     <text x="2" y="${(Y(v) + 3).toFixed(1)}" font-size="10"
       fill="var(--ink-3)">${v.toFixed(Math.abs(max - min) < 5 ? 1 : 0)}</text>`).join("");

  const body = lines.map((s, si) => {
    const color = s.color || `var(--chart-${(si % 4) + 1}, var(--teal))`;
    const pts = [...s.points].sort((a, b) => a.t - b.t);
    // Eine Lücke bleibt eine Lücke: Zwischen zwei Punkten, die weiter
    // auseinanderliegen als der übliche Abstand, wird nicht durchgezogen.
    const gapMs = opts.maxGapMs || span / 4;
    let d = "", open = false;
    pts.forEach((p, i) => {
      const jump = i && p.t - pts[i - 1].t > gapMs;
      d += `${!open || jump ? "M" : "L"}${X(p.t).toFixed(1)},${Y(p.value).toFixed(1)} `;
      open = true;
    });
    const dots = pts.length <= 60
      ? pts.map((p) => `<circle cx="${X(p.t).toFixed(1)}" cy="${Y(p.value).toFixed(1)}"
          r="2.6" fill="${color}"></circle>`).join("")
      : "";
    return `<path d="${d.trim()}" fill="none" stroke="${color}" stroke-width="1.7"
      stroke-linejoin="round" stroke-linecap="round"></path>${dots}`;
  }).join("");

  const legend = opts.legend === false ? "" : lines.map((s, si) => {
    const color = s.color || `var(--chart-${(si % 4) + 1}, var(--teal))`;
    const x = padL + si * 108;
    return `<circle cx="${x}" cy="${H - 5}" r="3.5" fill="${color}"></circle>
      <text x="${x + 8}" y="${H - 2}" font-size="10" fill="var(--ink-3)"
        >${esc(s.label || s.key || "")}</text>`;
  }).join("");

  container.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(opts.label || "Verlauf")}">
    ${gridY}${ticks}${body}${legend}
    <rect class="tc-hit" x="${padL}" y="${padT}" width="${W - padL - padR}"
      height="${H - padB - padT}" fill="transparent"></rect>
  </svg>`;

  const svg = container.querySelector("svg");
  const hit = svg.querySelector(".tc-hit");
  const unit = opts.unit || "";
  hit.addEventListener("pointermove", (ev) => {
    const box = svg.getBoundingClientRect();
    const t = from + (((ev.clientX - box.left) / box.width * W) - padL)
      / (W - padL - padR) * span;
    let best = null;
    lines.forEach((s, si) => {
      s.points.forEach((p) => {
        const dist = Math.abs(p.t - t);
        if (!best || dist < best.dist) best = { dist, p, s, si };
      });
    });
    if (!best || best.dist > span / 20) { hideTip(); return; }
    const when = axis.point(new Date(best.p.t));
    showTip(ev.clientX, box.top + (Y(best.p.value) / H) * box.height,
      `<span class="t-label">${esc(best.p.tip || when)}</span><br>` +
      `${lines.length > 1 ? esc(best.s.label) + ": " : ""}<b>${best.p.value}${unit}</b>`);
  });
  hit.addEventListener("pointerleave", hideTip);
}
