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
  const W = 720, H = opts.height || 300, pad = 16;
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
