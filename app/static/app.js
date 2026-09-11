/* PULS — vier Reiter, eine Empfehlung.
   Kein Framework, keine Abhängigkeiten. Jeder Reiter holt seine Daten mit
   einem Aufruf und zeichnet sich daraus neu. */

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const state = { settings: null, strength: null, preview: null, mood: {} };

/* ------------------------------------------------------------- Werkzeug */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function rowOf(...nodes) {
  const box = el("div", "row");
  nodes.filter(Boolean).forEach((n) => box.append(n));
  return box;
}

function toast(message, kind = "") {
  const box = $("#toast");
  box.textContent = message;
  box.className = `show ${kind}`;
  clearTimeout(box._timer);
  box._timer = setTimeout(() => { box.className = ""; }, 4200);
}

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" }, ...options,
  });
  if (!res.ok) {
    let detail = `Fehler ${res.status}`;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* egal */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

const post = (path, body) =>
  api(path, { method: "POST", body: JSON.stringify(body ?? {}) });
const patch = (path, body) =>
  api(path, { method: "PATCH", body: JSON.stringify(body ?? {}) });
const del = (path) => api(path, { method: "DELETE" });

function fmtDate(iso) {
  if (!iso) return "ohne Datum";
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`);
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const days = Math.round((d - today) / 86400000);
  if (days === 0) return "heute";
  if (days === 1) return "morgen";
  if (days === -1) return "gestern";
  return `${WEEKDAYS[(d.getDay() + 6) % 7]} ${d.getDate()}.${d.getMonth() + 1}.`;
}

function fmtDuration(seconds) {
  if (!seconds) return "–";
  const m = Math.round(seconds / 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")} h` : `${m} min`;
}

function fmtPace(secPerKm) {
  if (!secPerKm) return "–";
  return `${Math.floor(secPerKm / 60)}:${String(Math.round(secPerKm % 60)).padStart(2, "0")}/km`;
}

/* --------------------------------------------------------------- Reiter */

const LOADERS = {
  plan: loadPlan, strength: loadStrength, running: loadRunning, mood: loadMood,
};

function show(view) {
  $$("nav.tabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$("main > section").forEach((s) => { s.hidden = s.id !== `view-${view}`; });
  localStorage.setItem("puls.view", view);
  LOADERS[view]?.().catch((e) => toast(e.message, "bad"));
}

/* =========================================================== PLAN / HEUTE */

async function loadPlan() {
  await Promise.all([loadToday(), loadPlanned(), loadKbState()]);
}

async function loadKbState() {
  const box = $("#kbState");
  try {
    const st = await api("/coach/status");
    if (st.bereit) {
      box.textContent = `${st.abschnitte} Abschnitte`;
      box.className = "kb-state ok";
    } else {
      box.textContent = "ohne Wissensbasis";
      box.className = "kb-state warn";
      box.title = st.fehler || "";
    }
  } catch (e) {
    box.textContent = "";
  }
}

async function ask() {
  const frage = $("#askText").value.trim();
  if (frage.length < 4) { toast("Stell eine Frage.", "bad"); return; }
  const box = $("#askAnswer");
  box.replaceChildren(el("p", "hint", "denkt nach …"));
  $("#btnAsk").disabled = true;
  try {
    const res = await post("/coach/ask", { frage });
    box.replaceChildren();
    if (res.hinweis) box.append(el("p", "note warn", res.hinweis));
    box.append(el("p", "answer", res.antwort));

    // Woher die Antwort kommt — aus dem Abruf, nicht aus dem, was das Modell
    // selbst an Quellen nennt. Bei einer merkwürdigen Antwort ist das die
    // erste Frage: lag es am Abruf oder am Modell?
    if (res.quellen?.length) {
      const src = el("div", "sources");
      src.append(el("span", "src-label", "Gelesen:"));
      res.quellen.forEach((q) => src.append(el("span", "src", q)));
      box.append(src);
    } else if (res.wissensbasis) {
      box.append(el("div", "sources",
        "Kein passender Auszug gefunden — die Antwort ist nicht belegt."));
    }
    if (res.berechnet) {
      const det = el("details", "computed");
      det.append(el("summary", null, "Werte, die dem Coach vorlagen"));
      res.berechnet.split("\n").forEach((line) => {
        if (line.trim()) det.append(el("div", "item-sub", line.replace(/^-\s*/, "")));
      });
      box.append(det);
    }
  } catch (e) {
    box.replaceChildren(el("p", "note bad", e.message));
  } finally {
    $("#btnAsk").disabled = false;
  }
}

async function loadToday(phrase = true) {
  const t = await api(`/today?phrase=${phrase ? "true" : "false"}`);
  $("#todayHeadline").textContent = t.headline;
  $("#todayText").textContent = t.text || t.plain;

  const ready = t.readiness || {};
  $("#readyBox").hidden = ready.score === null || ready.score === undefined;
  if (ready.score !== null && ready.score !== undefined) {
    $("#readyNum").textContent = ready.score;
    $("#readyNum").className = `ready-num ${ready.score >= 72 ? "good"
      : ready.score >= 52 ? "" : ready.score >= 35 ? "warn" : "bad"}`;
    $("#readyLabel").textContent = ready.label || "";
  }

  const reasons = $("#todayReasons");
  reasons.replaceChildren();
  (t.reasons || []).forEach((r) => {
    const li = el("li");
    li.append(el("b", null, r.label), document.createTextNode(` ${r.detail}`));
    reasons.append(li);
  });

  const parts = $("#readyParts");
  parts.replaceChildren();
  (ready.parts || []).forEach((p) => {
    const li = el("li");
    li.append(el("span", "pk", p.label), el("span", "pv", p.detail),
              el("span", "ps", p.score));
    parts.append(li);
  });
  $("#readyDetails").hidden = !(ready.parts || []).length;

  const session = t.session;
  $("#todayDetails").hidden = !session;
  if (session) {
    $("#todaySessionName").textContent =
      `${session.name || "Die Einheit"} · ${t.minutes} min`;
    const list = $("#todaySteps");
    list.replaceChildren();
    (session.steps || []).forEach((s) => list.append(stepLine(s)));
  }
  state.today = t;
}

function stepLine(step, depth = 0) {
  const li = el("li", depth ? "sub" : "");
  if (step.type === "repeat" && step.steps) {
    li.append(el("b", null, `${step.repeat || 1}× `));
    li.append(document.createTextNode(step.name || "Runde"));
    const inner = el("ol", "steps");
    step.steps.forEach((s) => inner.append(stepLine(s, depth + 1)));
    li.append(inner);
    return li;
  }
  li.append(el("span", "sn", step.name || step.type || "Schritt"));
  const bits = [];
  if (step.reps) bits.push(`${step.reps} Wdh`);
  if (step.weight_kg) bits.push(`${step.weight_kg} kg`);
  if (step.duration_s) bits.push(`${Math.round(step.duration_s)} s`);
  if (step.distance_m) bits.push(`${(step.distance_m / 1000).toFixed(1)} km`);
  if (step.target) bits.push(step.target);
  if (bits.length) li.append(el("span", "sv", bits.join(" · ")));
  if (step.note) li.append(el("span", "note", step.note));
  return li;
}

async function loadPlanned() {
  const data = await api("/plan");
  const list = $("#plannedList");
  list.replaceChildren();
  if (!data.workouts.length) {
    list.append(el("p", "hint", "Nichts geplant. „Woche planen“ legt sie an."));
  }
  data.workouts.forEach((w) => {
    const row = el("div", "item");
    const main = el("div", "item-main");
    main.append(el("div", "item-title", w.name));
    main.append(el("div", "item-sub",
      [fmtDate(w.planned_date), w.minutes ? `${w.minutes} min` : null,
       `${w.step_count} Schritte`, w.status === "pushed" ? "auf der Uhr" : null]
        .filter(Boolean).join(" · ")));
    row.append(main);
    const push = el("button", "ghost small", w.status === "pushed" ? "erneut" : "an die Uhr");
    push.onclick = () => post(`/plan/workouts/${w.id}/push`, {})
      .then(() => { toast("Auf der Uhr."); loadPlanned(); })
      .catch((e) => toast(e.message, "bad"));
    const drop = el("button", "ghost small danger", "×");
    drop.onclick = () => del(`/plan/workouts/${w.id}`).then(loadPlanned);
    row.append(push, drop);
    list.append(row);
  });

  const s = data.structure;
  renderDays("#gymDays", s.gym_days);
  renderDays("#runDays", s.run_days);
  $("#gymMinutes").value = s.gym_minutes;
  $("#runMinutes").value = s.run_minutes;
}

function renderDays(sel, active) {
  const box = $(sel);
  box.replaceChildren();
  WEEKDAYS.forEach((d) => {
    const b = el("button", `day${active.includes(d) ? " on" : ""}`, d);
    b.onclick = () => { b.classList.toggle("on"); saveStructure(); };
    box.append(b);
  });
}

function pickedDays(sel) {
  return $$(`${sel} .day.on`).map((b) => b.textContent);
}

async function saveStructure() {
  await post("/settings", {
    gym_days: pickedDays("#gymDays"), run_days: pickedDays("#runDays"),
    gym_minutes: Number($("#gymMinutes").value) || 75,
    run_minutes: Number($("#runMinutes").value) || 45,
  });
  toast("Wochenstruktur gespeichert.");
}

function renderWish(w) {
  const box = $("#wishResult");
  box.replaceChildren();
  if (w.read_as) box.append(el("p", "lead", w.read_as));
  if (w.goal_note) box.append(el("p", "hint", w.goal_note));
  const list = el("ol", "steps");
  (w.steps || []).forEach((s) => list.append(stepLine(s)));
  box.append(list);
  const save = el("button", null, "In den Plan legen");
  save.onclick = async () => {
    await post("/plan/workouts", {
      name: w.name, sport: w.sport || "strength", steps: w.steps,
      planned_date: new Date().toISOString().slice(0, 10),
      description: w.read_as,
    });
    toast("Eingetragen.");
    box.replaceChildren();
    loadPlanned();
  };
  box.append(rowOf(save));
}

/* ================================================================ KRAFT */

async function loadStrength() {
  const data = await api("/strength");
  state.strength = data;
  renderProposals(data.proposals);
  renderMuscles(data.muscles);
  renderSessions(data.sessions);
  renderExercises(data.exercises);
}

function renderProposals(props) {
  $("#propCard").hidden = !props.length;
  $("#propCount").textContent = props.length ? `${props.length}` : "";
  const list = $("#propList");
  list.replaceChildren();
  props.forEach((p) => {
    const row = el("div", "item prop");
    const main = el("div", "item-main");
    main.append(el("div", "item-title", p.name));
    const change = el("div", "change");
    change.append(el("span", "from", `${p.from_weight ?? "–"} kg × ${p.from_reps}`),
                  el("span", "arrow", "→"),
                  el("span", "to", `${p.to_weight} kg × ${p.to_reps}`));
    main.append(change);
    main.append(el("div", "item-sub", p.reason));
    row.append(main);
    const yes = el("button", "small", "Übernehmen");
    yes.onclick = () => post(`/strength/proposals/${p.id}`, { accept: true })
      .then(() => { toast(`${p.name}: ${p.to_weight} kg × ${p.to_reps}.`); loadStrength(); });
    const no = el("button", "ghost small", "Nein");
    no.onclick = () => post(`/strength/proposals/${p.id}`, { accept: false })
      .then(loadStrength);
    row.append(yes, no);
    list.append(row);
  });
}

function renderMuscles(m) {
  const box = $("#muscleList");
  box.replaceChildren();
  if (m.hint) { box.append(el("p", "hint", m.hint)); return; }
  m.groups.forEach((g) => {
    const row = el("div", "bar-row");
    row.append(el("div", "bar-label", g.label));
    const track = el("div", "bar");
    const fill = el("div", `fill ${g.need >= 60 ? "hot" : g.need >= 30 ? "warm" : ""}`);
    fill.style.width = `${Math.max(3, g.need)}%`;
    track.append(fill);
    row.append(track);
    row.append(el("div", "bar-val", g.need));
    const why = el("div", "bar-why",
      g.reasons.length ? g.reasons[0] : `${g.sets_recent} Sätze in vier Wochen`);
    const wrap = el("div", "bar-wrap");
    wrap.append(row, why);
    box.append(wrap);
  });
}

function renderSessions(sessions) {
  const list = $("#sessionList");
  list.replaceChildren();
  if (!sessions.length) {
    list.append(el("p", "hint", "Noch keine Sätze. Trag oben ein Training nach."));
  }
  sessions.forEach((s) => {
    const wrap = el("details", "session");
    const sum = el("summary");
    sum.append(el("b", null, fmtDate(s.day)),
               el("span", "item-sub",
                  ` ${s.exercises.length} Übungen · ${s.sets} Sätze`
                  + (s.volume ? ` · ${s.volume.toLocaleString("de-DE")} kg` : "")));
    wrap.append(sum);
    s.exercises.forEach((e) => {
      const line = el("div", "ex-line");
      line.append(el("span", "sn", e.name), el("span", "sv", e.summary));
      wrap.append(line);
    });
    list.append(wrap);
  });
}

let exFilter = "";

function renderExercises(items) {
  const filters = $("#exFilters");
  if (!filters.childElementCount) {
    const labels = state.strength.muscle_labels;
    [["", "alle"], ...Object.entries(labels)].forEach(([key, label]) => {
      const b = el("button", `chip${key === exFilter ? " on" : ""}`, label);
      b.onclick = () => {
        exFilter = key;
        $$("#exFilters .chip").forEach((c) => c.classList.remove("on"));
        b.classList.add("on");
        renderExercises(state.strength.exercises);
      };
      filters.append(b);
    });
  }
  const list = $("#exerciseList");
  list.replaceChildren();
  items.filter((e) => !exFilter || e.muscle_group === exFilter).forEach((e) => {
    const row = el("div", "item ex");
    const main = el("div", "item-main");
    main.append(el("div", "item-title", e.name));
    const target = e.mode === "time"
      ? `${e.target_duration_s || 30} s`
      : `${e.weight_kg ? `${e.weight_kg} kg × ` : ""}${e.target_reps}`;
    main.append(el("div", "item-sub",
      [target, `${e.sets} Sätze`,
       e.days_since === null ? "noch nie" : e.days_since === 0 ? "heute"
         : `vor ${e.days_since} Tagen`].join(" · ")));
    row.append(main);
    row.onclick = () => openExercise(e);
    list.append(row);
  });
}

/* ---------------------------------------------- Training in Worten lesen */

async function readTraining() {
  const text = $("#logText").value.trim();
  if (!text) { toast("Schreib hin, was du gemacht hast.", "bad"); return; }
  $("#btnRead").disabled = true;
  $("#btnRead").textContent = "liest …";
  try {
    const pv = await post("/strength/describe", { text });
    state.preview = pv;
    renderPreview(pv);
  } catch (e) {
    toast(e.message, "bad");
  } finally {
    $("#btnRead").disabled = false;
    $("#btnRead").textContent = "Lesen";
  }
}

function renderPreview(pv) {
  const box = $("#logPreview");
  box.replaceChildren();
  const ready = Boolean(pv.items.length || pv.runs.length);
  $("#btnCommit").hidden = !ready;
  // Sobald es etwas zu bestätigen gibt, ist „Eintragen“ die Handlung —
  // zwei gleich betonte Knöpfe nebeneinander sagen nicht, welcher gemeint ist.
  $("#btnRead").classList.toggle("ghost", ready);

  if (pv.hint) box.append(el("p", "hint", pv.hint));
  if (!ready) return;

  // „gestern (gestern)“ wäre doppelt gemoppelt — die Herkunft steht nur
  // dann daneben, wenn sie etwas hinzufügt.
  const how = pv.day_how && !pv.day_label.startsWith(pv.day_how)
    ? ` — ${pv.day_how}` : "";
  box.append(el("div", "preview-day", `Trainingstag: ${pv.day_label}${how}`));

  pv.items.forEach((item, index) => box.append(previewItem(pv, item, index)));
  pv.runs.forEach((run, index) => {
    const row = el("div", "item preview-item");
    row.append(tickFor(run, row));
    const main = el("div", "item-main");
    main.append(el("div", "item-title", `${run.name} (Lauf)`));
    main.append(el("div", "item-sub",
      [run.km ? `${run.km} km` : null, run.minutes ? `${run.minutes} min` : null]
        .filter(Boolean).join(" · ")));
    row.append(main);
    box.append(row);
  });

  if (pv.unread.length) {
    const un = el("details", "unread");
    un.append(el("summary", null, `${pv.unread.length} Stelle(n) nicht verstanden`));
    pv.unread.forEach((u) => un.append(el("div", "item-sub", `„${u}“`)));
    box.append(un);
  }
}

function tickFor(entry, row) {
  const tick = el("input");
  tick.type = "checkbox";
  tick.checked = !entry.skip;
  tick.onchange = () => {
    entry.skip = !tick.checked;
    row.classList.toggle("off", !tick.checked);
  };
  return tick;
}

const CONFIDENCE = {
  unsicher: ["unsicher", "warn"],
  geprüft: ["KI geprüft", ""],
  neu: ["neu", "new"],
};

function previewItem(pv, item, index) {
  const row = el("div", "item preview-item");
  row.append(tickFor(item, row));
  const main = el("div", "item-main");

  const title = el("div", "item-title");
  title.append(document.createTextNode(item.name));
  const mark = CONFIDENCE[item.confidence];
  if (mark) title.append(el("span", `tag ${mark[1]}`, mark[0]));
  main.append(title);

  main.append(setsEditor(pv, item, index));

  // Welche Übung gemeint ist, entscheidest du. Die Auswahl steht immer da,
  // auch wenn die Zuordnung sicher aussah — eine falsche Zuordnung, die man
  // nur abwählen statt richtigstellen kann, kostet mehr als sie spart.
  const picker = el("select", "picker");
  const seen = new Set();
  const add = (value, label, parent) => {
    const opt = el("option", null, label);
    opt.value = value;
    (parent || picker).append(opt);
    return opt;
  };
  (item.alternatives || []).forEach((a) => {
    seen.add(a.id);
    add(String(a.id), a.name);
  });
  const fresh = add("new", `neu anlegen: ${item.read_name}`);
  const rest = document.createElement("optgroup");
  rest.label = "alle Übungen";
  (state.strength?.exercises || []).forEach((e) => {
    if (!seen.has(e.id)) add(String(e.id), e.name, rest);
  });
  if (rest.childElementCount) picker.append(rest);
  picker.value = item.exercise_id && !item.force_new ? String(item.exercise_id) : "new";
  if (picker.value === "new") fresh.selected = true;

  picker.onchange = () => {
    if (picker.value === "new") {
      item.force_new = true;
      item.exercise_id = null;
    } else {
      item.force_new = false;
      item.exercise_id = Number(picker.value);
    }
    const chosen = (state.strength?.exercises || [])
      .find((e) => e.id === item.exercise_id);
    item.name = chosen ? chosen.name : item.read_name;
    item.confidence = picker.value === "new" ? "neu" : "sicher";
    renderPreview(pv);
  };
  main.append(picker);

  main.append(el("div", "item-sub faint", item.exercise_id && !item.force_new
    ? `${item.muscle_label}${item.current ? ` · ${item.current}` : ""}`
      + ` · gelesen als „${item.read_name}“`
    : `wird angelegt als ${item.muscle_label} · gelesen als „${item.read_name}“`));

  row.append(main);
  return row;
}

function setsEditor(pv, item, index) {
  const box = el("div", "sets-edit");
  const sets = item.sets || [];
  const same = sets.every((s) => s.reps === sets[0].reps
    && s.weight_kg === sets[0].weight_kg && s.duration_s === sets[0].duration_s);
  if (!same || !sets.length) {
    box.append(el("span", "item-sub", item.summary));
    return box;
  }

  // Alle Sätze gleich: Dann lassen sie sich in drei Zahlen fassen — und
  // nachbessern, wenn im Text keine Satzzahl stand.
  const field = (label, value, unit, apply) => {
    const wrap = el("label", "num");
    const input = el("input");
    input.type = "number";
    input.step = unit === "kg" ? "0.5" : "1";
    input.min = "0";
    input.value = value ?? "";
    input.onchange = () => {
      apply(input.value === "" ? null : Number(input.value));
      item.summary = summarise(item.sets);
      renderPreview(pv);
    };
    wrap.append(input, el("span", "unit", label));
    return wrap;
  };

  box.append(field("Sätze", sets.length, "", (n) => {
    const count = Math.max(1, Math.min(20, n || 1));
    const template = { ...sets[0] };
    item.sets = Array.from({ length: count }, () => ({ ...template }));
  }));
  if (sets[0].duration_s) {
    box.append(field("s", sets[0].duration_s, "",
      (n) => item.sets.forEach((s) => { s.duration_s = n; })));
  } else {
    box.append(field("Wdh", sets[0].reps, "",
      (n) => item.sets.forEach((s) => { s.reps = n; })));
  }
  box.append(field("kg", sets[0].weight_kg, "kg",
    (n) => item.sets.forEach((s) => { s.weight_kg = n; })));
  return box;
}

function summarise(sets) {
  return sets.map((s) => {
    let core = s.duration_s ? `${s.duration_s} s` : s.reps ? `${s.reps}×` : "1 Satz";
    if (s.weight_kg) core += ` ${s.weight_kg} kg`;
    return core;
  }).join(" · ");
}

async function commitTraining() {
  const pv = state.preview;
  if (!pv) return;
  $("#btnCommit").disabled = true;
  try {
    const res = await post("/strength/commit", {
      day: pv.day, items: pv.items, runs: pv.runs,
    });
    const bits = [`${res.sets} Sätze eingetragen`];
    if (res.created.length) bits.push(`${res.created.length} neue Übung(en): ${res.created.join(", ")}`);
    if (res.learned?.length) bits.push(`gemerkt: ${res.learned.join(", ")}`);
    if (res.runs) bits.push(`${res.runs} Lauf`);
    toast(`${bits.join(" · ")}.`, "good");
    $("#logText").value = "";
    $("#logPreview").replaceChildren();
    $("#btnCommit").hidden = true;
    $("#btnRead").classList.remove("ghost");
    state.preview = null;
    await loadStrength();
    if (res.proposals.length) {
      $("#propCard").scrollIntoView({ behavior: "smooth", block: "center" });
    }
  } catch (e) {
    toast(e.message, "bad");
  } finally {
    $("#btnCommit").disabled = false;
  }
}

/* ------------------------------------------------------- Übungs-Dialog */

let editing = null;

function openExercise(ex) {
  editing = ex || null;
  const labels = state.strength;
  $("#exTitle").textContent = ex ? ex.name : "Neue Übung";
  $("#exName").value = ex?.name || "";
  fillSelect("#exGroup", labels.muscle_labels, ex?.muscle_group);
  fillSelect("#exEquip", labels.equipment_labels, ex?.equipment);
  $("#exWeight").value = ex?.weight_kg ?? "";
  $("#exStep").value = ex?.weight_increment ?? 2.5;
  $("#exReps").value = ex?.target_reps ?? 12;
  $("#exSets").value = ex?.sets ?? 3;
  $("#exSetting").value = ex?.machine_setting || "";
  $("#exAssisted").checked = Boolean(ex?.assisted);
  $("#btnExDelete").hidden = !ex;
  $("#exHistory").replaceChildren();
  $("#dlgExercise").showModal();
  if (ex) {
    api(`/exercises/${ex.id}/history`).then((h) => {
      const box = $("#exHistory");
      box.replaceChildren();
      if (!h.sets.length) return;
      box.append(el("h4", null, "Zuletzt"));
      const byDay = {};
      h.sets.forEach((s) => { (byDay[s.day] ||= []).push(s); });
      Object.entries(byDay).slice(0, 6).forEach(([day, sets]) => {
        const line = el("div", "ex-line");
        line.append(el("span", "sn", fmtDate(day)),
                    el("span", "sv", sets.map((s) =>
                      s.duration_s ? `${Math.round(s.duration_s)} s`
                        : `${s.reps ?? "–"}×${s.weight_kg ? ` ${s.weight_kg} kg` : ""}`
                    ).join(" · ")));
        box.append(line);
      });
    });
  }
}

function fillSelect(sel, labels, active) {
  const node = $(sel);
  node.replaceChildren();
  Object.entries(labels).forEach(([key, label]) => {
    const opt = el("option", null, label);
    opt.value = key;
    if (key === active) opt.selected = true;
    node.append(opt);
  });
}

async function saveExercise() {
  const data = {
    name: $("#exName").value.trim(),
    muscle_group: $("#exGroup").value,
    equipment: $("#exEquip").value,
    weight_kg: Number($("#exWeight").value) || null,
    weight_increment: Number($("#exStep").value) || 2.5,
    target_reps: Number($("#exReps").value) || 12,
    sets: Number($("#exSets").value) || 3,
    machine_setting: $("#exSetting").value.trim() || null,
    assisted: $("#exAssisted").checked ? 1 : 0,
  };
  if (!data.name) { toast("Name fehlt.", "bad"); return; }
  if (editing) await patch(`/exercises/${editing.id}`, data);
  else await post("/exercises", data);
  $("#dlgExercise").close();
  toast("Gespeichert.");
  loadStrength();
}

/* =============================================================== LAUFEN */

async function loadRunning() {
  const data = await api("/running");
  const form = $("#runForm");
  form.replaceChildren();
  const paces = data.paces || {};
  const bests = (data.form?.bests || []);
  const kpis = [
    ["Läufe (4 Wochen)", data.trend.runs_recent],
    ["Kilometer/Woche", data.trend.km_per_week],
    ["Tempo bei Puls 120–155", fmtPace(data.trend.pace_recent)],
    ["Längster Lauf", data.trend.longest_recent ? `${data.trend.longest_recent} km` : "–"],
  ];
  kpis.forEach(([label, value]) => {
    const box = el("div", "kpi");
    box.append(el("div", "kpi-val", value ?? "–"), el("div", "kpi-lab", label));
    form.append(box);
  });

  const goal = $("#runGoal");
  goal.replaceChildren();
  goal.append(el("div", "hint",
    `Ziel: ${data.goal.distance_km} km unter ${data.goal.time_min} Minuten.`));
  if (paces.easy) {
    goal.append(el("div", "hint",
      `Deine Tempi — locker ${fmtPace(paces.easy)}, Tempo ${fmtPace(paces.tempo)}, `
      + `Intervall ${fmtPace(paces.interval)}.`));
  }
  bests.forEach((b) => {
    goal.append(el("div", "hint",
      `Bestes ${b.label}: ${fmtPace(b.pace_s)} am ${fmtDate(b.day)}.`));
  });

  const trend = $("#runTrend");
  trend.replaceChildren();
  if (data.trend.hint) trend.append(el("p", "hint", data.trend.hint));
  if (data.trend.pace_gain_s) {
    trend.append(el("p", "lead",
      data.trend.pace_gain_s > 0
        ? `${data.trend.pace_gain_s} s/km schneller bei gleichem Puls als im Monat davor.`
        : `${Math.abs(data.trend.pace_gain_s)} s/km langsamer bei gleichem Puls als im Monat davor.`));
  }
  (data.trend.needs || []).forEach((n) => trend.append(el("li", "need", n)));
  (data.form?.hints || []).forEach((h) =>
    trend.append(el("p", `note ${h.level}`, h.text)));

  const list = $("#runList");
  list.replaceChildren();
  if (!data.runs.length) list.append(el("p", "hint", "Noch keine Läufe."));
  data.runs.forEach((r) => {
    const row = el("div", "item");
    const main = el("div", "item-main");
    main.append(el("div", "item-title", r.name || "Lauf"));
    const km = r.distance_m ? (r.distance_m / 1000).toFixed(2) : null;
    const pace = (r.distance_m && r.duration_s)
      ? fmtPace(r.duration_s / (r.distance_m / 1000)) : null;
    main.append(el("div", "item-sub",
      [fmtDate(r.start_time), km ? `${km} km` : null, fmtDuration(r.duration_s),
       pace, r.avg_hr ? `${Math.round(r.avg_hr)} bpm` : null]
        .filter(Boolean).join(" · ")));
    row.append(main);
    row.onclick = () => openRun(r);
    list.append(row);
  });
}

async function openRun(run) {
  $("#runTitle").textContent = run.name || "Lauf";
  const box = $("#runDetail");
  box.replaceChildren(el("p", "hint", "lädt …"));
  $("#dlgRun").showModal();
  try {
    const [analysis, details] = await Promise.all([
      api(`/activities/${run.id}/analysis`),
      api(`/activities/${run.id}/details`),
    ]);
    box.replaceChildren();
    (analysis.analysis?.findings || []).forEach((f) => {
      box.append(el("p", `note ${f.level}`, `${f.title}: ${f.detail}`));
    });
    if (details.track && details.bounds && window.routeMap) {
      const map = el("div");
      box.append(map);
      routeMap(map, details.track, details.bounds, {});
    }
    if (details.series && window.runProfile) {
      const prof = el("div");
      box.append(prof);
      runProfile(prof, details.series, {});
    }
    if (details.splits?.length && window.splitChart) {
      const sp = el("div");
      box.append(sp);
      splitChart(sp, details.splits, {});
    }
    if (!box.childElementCount) box.append(el("p", "hint", details.hint || "Keine Details."));
    const drop = el("button", "ghost small danger", "Diese Einheit löschen");
    drop.onclick = async () => {
      await del(`/activities/${run.id}`);
      $("#dlgRun").close();
      loadRunning();
    };
    box.append(drop);
  } catch (e) {
    box.replaceChildren(el("p", "hint", e.message));
  }
}

/* ================================================================ GEMÜT */

async function loadMood() {
  const data = await api("/mood");
  state.moodMeta = data;
  renderScales();

  const chart = $("#moodChart");
  chart.replaceChildren();
  const points = data.trend.points || [];
  if (points.length && window.timeChart) {
    timeChart(chart, [
      { key: "mood", label: "Stimmung", points: points.filter((p) => p.mood != null)
          .map((p) => ({ t: new Date(`${p.day}T12:00:00`).getTime(), value: p.mood })) },
      { key: "energy", label: "Energie", points: points.filter((p) => p.energy != null)
          .map((p) => ({ t: new Date(`${p.day}T12:00:00`).getTime(), value: p.energy })) },
      { key: "stress", label: "Stress", points: points.filter((p) => p.stress != null)
          .map((p) => ({ t: new Date(`${p.day}T12:00:00`).getTime(), value: p.stress })) },
    ], { min: 1, max: 5 });
  } else {
    chart.append(el("p", "hint", "Noch keine Einträge."));
  }

  const adapt = $("#moodAdapt");
  adapt.replaceChildren();
  const a = data.adaptations;
  if (!a.summary?.length) adapt.append(el("p", "hint", "Keine Beschwerden gemeldet — gut."));
  (a.summary || []).forEach((line) => adapt.append(el("li", "need", line)));
  (a.relief_poses || []).forEach((p) => adapt.append(el("p", "hint", `Hilft: ${p}`)));

  const list = $("#moodList");
  list.replaceChildren();
  data.entries.slice(0, 20).forEach((e) => {
    const row = el("div", "item");
    const main = el("div", "item-main");
    main.append(el("div", "item-title",
      `${fmtDate(e.day)} · ${(e.recorded_at || "").slice(11, 16)}`));
    main.append(el("div", "item-sub",
      [e.mood ? `Stimmung ${e.mood}` : null, e.energy ? `Energie ${e.energy}` : null,
       e.stress ? `Stress ${e.stress}` : null, e.note].filter(Boolean).join(" · ")));
    row.append(main);
    const drop = el("button", "ghost small danger", "×");
    drop.onclick = () => del(`/mood/${e.id}`).then(loadMood);
    row.append(drop);
    list.append(row);
  });
}

function renderScales() {
  $$(".scale").forEach((scale) => {
    const key = scale.dataset.key;
    const dots = $(".dots", scale);
    if (dots.childElementCount) return;
    for (let i = 1; i <= 5; i += 1) {
      const b = el("button", "dot", i);
      b.onclick = () => {
        state.mood[key] = i;
        $$(".dot", dots).forEach((d, index) => d.classList.toggle("on", index < i));
      };
      dots.append(b);
    }
  });
}

async function saveMood() {
  const note = $("#moodNote").value.trim();
  const payload = { ...state.mood };
  if (note) payload.note = note;
  if (!Object.keys(payload).length) { toast("Nichts ausgewählt.", "bad"); return; }
  if (note) {
    try {
      const s = await post("/mood/suggest", { text: note });
      if (s.complaints?.length) payload.complaints = s.complaints;
    } catch (e) { /* ohne Modell eben ohne Beschwerden */ }
  }
  await post("/mood", payload);
  state.mood = {};
  $("#moodNote").value = "";
  $$(".dot").forEach((d) => d.classList.remove("on"));
  toast("Eingetragen.", "good");
  loadMood();
}

/* ======================================================== EINSTELLUNGEN */

async function openSettings() {
  const s = await api("/settings");
  state.settings = s;
  $("#setGoal").value = s.goal_text;
  $("#setGoalKm").value = s.run_goal_distance_km;
  $("#setGoalMin").value = s.run_goal_time_min;
  $("#setPullup").value = s.pullup_goal;
  $("#setRepMin").value = s.progression.rep_min;
  $("#setRepMax").value = s.progression.rep_max;
  $("#setFont").value = s.font_scale;
  updateProgPreview();
  $("#versionLine").textContent = `Kennung ${s.version} · Stand ${s.built_at}`;
  await Promise.all([renderGarmin(), renderModels()]);
  $("#dlgSettings").showModal();
}

function updateProgPreview() {
  $("#pvMin").textContent = $("#setRepMin").value;
  $("#pvMin2").textContent = $("#setRepMin").value;
  $("#pvMax").textContent = $("#setRepMax").value;
}

async function saveSettings() {
  await post("/settings", {
    goal_text: $("#setGoal").value,
    run_goal_distance_km: Number($("#setGoalKm").value) || 10,
    run_goal_time_min: Number($("#setGoalMin").value) || 60,
    pullup_goal: Number($("#setPullup").value) || 10,
    prog_rep_min: Number($("#setRepMin").value),
    prog_rep_max: Number($("#setRepMax").value),
    font_scale: Number($("#setFont").value),
  });
  document.documentElement.style.setProperty("--fs", `${$("#setFont").value / 100 * 16}px`);
  toast("Gespeichert.", "good");
  $("#dlgSettings").close();
}

async function renderGarmin() {
  const box = $("#garminBox");
  box.replaceChildren();
  const st = await api("/garmin/status");
  if (st.linked) {
    box.append(el("p", "hint", `Verbunden als ${st.email}.`));
    if (st.last_sync) {
      box.append(el("p", "hint",
        `Zuletzt ${st.last_sync.ts}: ${st.last_sync.detail || ""}`));
    }
    const unlink = el("button", "ghost small", "Trennen");
    unlink.onclick = () => post("/garmin/unlink").then(renderGarmin);
    const backfill = el("button", "ghost small", "Verlauf nachladen");
    backfill.onclick = () => post("/garmin/backfill")
      .then(() => toast("Läuft im Hintergrund."));
    box.append(rowOf(unlink, backfill));
    return;
  }
  const mail = el("input"); mail.placeholder = "Garmin-E-Mail"; mail.type = "email";
  const pass = el("input"); pass.placeholder = "Passwort"; pass.type = "password";
  const go = el("button", "small", "Verbinden");
  go.onclick = async () => {
    try {
      const res = await post("/garmin/login", { email: mail.value, password: pass.value });
      if (res.mfa_required) {
        const code = prompt("Code aus der Garmin-App:");
        if (code) await post("/garmin/mfa", { code });
      }
      toast("Verbunden.", "good");
      renderGarmin();
    } catch (e) { toast(e.message, "bad"); }
  };
  box.append(mail, pass, rowOf(go));
}

async function renderModels() {
  const box = $("#modelBox");
  box.replaceChildren();
  try {
    const m = await api("/system/models");
    if (!m.ollama_reachable) {
      box.append(el("p", "hint", "Ollama ist nicht erreichbar — PULS rechnet "
        + "trotzdem, formuliert nur nüchterner."));
      return;
    }
    const sel = el("select");
    m.presets.forEach((p) => {
      const opt = el("option", null,
        `${p.label || p.name}${p.installed ? "" : " (lädt beim Wählen)"}`);
      opt.value = p.name;
      if (p.active) opt.selected = true;
      sel.append(opt);
    });
    sel.onchange = () => post("/system/model", { name: sel.value })
      .then((r) => toast(`Modell ${r.model}: ${r.status}.`));
    box.append(sel);
  } catch (e) {
    box.append(el("p", "hint", "Modellstatus nicht abrufbar."));
  }
}

async function refreshBadge() {
  try {
    const h = await api("/health");
    $("#syncBadge").textContent = h.garmin_linked ? "Garmin ✓" : "Garmin –";
    $("#syncBadge").className = h.garmin_linked ? "ok" : "";
  } catch (e) {
    $("#syncBadge").textContent = "offline";
  }
}

/* ================================================================= Start */

function bind() {
  $$("nav.tabs button").forEach((b) => { b.onclick = () => show(b.dataset.view); });
  $("#btnSettings").onclick = () => openSettings().catch((e) => toast(e.message, "bad"));
  $("#btnSaveSettings").onclick = () => saveSettings().catch((e) => toast(e.message, "bad"));
  $("#btnSync").onclick = () => {
    toast("Synchronisiere …");
    post("/garmin/sync").then((r) =>
      toast(r.ok ? "Daten sind da." : (r.detail || "Sync fehlgeschlagen."),
            r.ok ? "good" : "bad")).catch((e) => toast(e.message, "bad"));
  };
  ["#setRepMin", "#setRepMax"].forEach((sel) => {
    $(sel).oninput = updateProgPreview;
  });

  $("#btnTodayRefresh").onclick = () => loadToday(true).catch((e) => toast(e.message, "bad"));
  $("#btnTodayPlan").onclick = () => post("/today/plan")
    .then((r) => { toast(`„${r.name}“ eingetragen.`, "good"); loadPlanned(); })
    .catch((e) => toast(e.message, "bad"));
  $("#btnPlanWeek").onclick = () => {
    toast("Plane die Woche …");
    post("/plan/week", { include_runs: true })
      .then((r) => { toast(`${r.created.length} Einheiten gelegt.`, "good"); loadPlanned(); })
      .catch((e) => toast(e.message, "bad"));
  };
  $("#btnPushAll").onclick = () => post("/plan/push-all")
    .then((r) => toast(`${r.pushed.length} auf der Uhr`
      + (r.failed.length ? `, ${r.failed.length} nicht` : "."), r.failed.length ? "bad" : "good"))
    .catch((e) => toast(e.message, "bad"));
  $("#btnAsk").onclick = () => ask();
  $("#askText").onkeydown = (e) => {
    // Strg+Enter schickt ab — eine Frage ist meist einzeilig, aber nicht immer.
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) ask();
  };
  $("#btnWish").onclick = () => {
    const text = $("#wishText").value.trim();
    if (!text) { toast("Schreib deinen Wunsch hin.", "bad"); return; }
    toast("Baue die Einheit …");
    post("/plan/wish", { text }).then(renderWish).catch((e) => toast(e.message, "bad"));
  };
  $("#gymMinutes").onchange = saveStructure;
  $("#runMinutes").onchange = saveStructure;

  $("#btnRead").onclick = readTraining;
  $("#btnCommit").onclick = commitTraining;
  $("#btnPropAll").onclick = () => post("/strength/proposals/all", { accept: true })
    .then((r) => { toast(`${r.count} Gewichte übernommen.`, "good"); loadStrength(); });
  $("#btnPropRecalc").onclick = () => post("/strength/proposals/recalculate")
    .then((r) => { toast(`${r.days} Trainingstage geprüft.`); loadStrength(); });
  $("#btnNewExercise").onclick = (e) => { e.stopPropagation(); openExercise(null); };
  $("#btnExSave").onclick = () => saveExercise().catch((err) => toast(err.message, "bad"));
  $("#btnExDelete").onclick = async () => {
    if (!editing) return;
    await del(`/exercises/${editing.id}`);
    $("#dlgExercise").close();
    loadStrength();
  };

  $("#btnMoodSave").onclick = () => saveMood().catch((e) => toast(e.message, "bad"));
}

async function boot() {
  bind();
  refreshBadge();
  try {
    const s = await api("/settings");
    document.documentElement.style.setProperty("--fs", `${s.font_scale / 100 * 16}px`);
  } catch (e) { /* Vorgabe bleibt */ }
  show(localStorage.getItem("puls.view") || "plan");
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
}

boot();
