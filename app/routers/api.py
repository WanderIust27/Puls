"""Alle API-Endpunkte."""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..db import get_db, get_setting, rows_to_dicts, set_setting
from ..version import BUILT_AT, VERSION
from ..services import (benchmark, body, coach_ai, fit_import, garmin_sync,
                        metrics, ollama_client, planner, run_analysis, running)
from ..services import activity_details as activity_details_svc
from ..services import (autopilot, boosters, feedback, gym_analysis,
                        insights, memory, mood, nutrition, recipes, score,
                        stats, suggestions, supplements)
from ..services import exercises as ex_lib
from ..services.garmin_sync import GarminNotLinked
from ..services.ollama_client import (OllamaUnavailable, is_available,
                                      model_present)
from ..services.workout_builder import build_fit_workout, build_garmin_workout

log = logging.getLogger("puls.api")
router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ Dashboard

@router.get("/dashboard")
def dashboard() -> dict[str, Any]:
    with get_db() as db:
        last_msg = db.execute(
            "SELECT * FROM coach_messages WHERE kind IN ('daily','rest') "
            "ORDER BY id DESC LIMIT 1").fetchone()
        last_tip = db.execute(
            "SELECT * FROM research_tips ORDER BY id DESC LIMIT 1").fetchone()
        last_sync = db.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
        upcoming = rows_to_dicts(db.execute(
            "SELECT * FROM planned_workouts WHERE status IN ('planned','pushed') "
            "ORDER BY COALESCE(planned_date,'9999') LIMIT 5").fetchall())
        recent = rows_to_dicts(db.execute(
            "SELECT id, name, sport, start_time, duration_s, distance_m, avg_hr, "
            "training_load, source FROM activities "
            "ORDER BY start_time DESC LIMIT 8").fetchall())
        today_nutrition = db.execute(
            "SELECT * FROM nutrition_log WHERE day = date('now','localtime')").fetchone()
    return {
        "week": metrics.week_summary(),
        "streak_weeks": metrics.streak_weeks(),
        "acwr": metrics.acwr(),
        "load_series": metrics.load_series(42),
        "weight_series": metrics.weight_series(120),
        "body_composition": metrics.body_composition(),
        "latest_daily": metrics.latest_daily(),
        "coach_message": dict(last_msg) if last_msg else None,
        "research_tip": dict(last_tip) if last_tip else None,
        "upcoming_workouts": upcoming,
        "recent_activities": recent,
        "today_nutrition": dict(today_nutrition) if today_nutrition else None,
        "garmin_linked": get_setting("garmin_linked") == "1",
        "last_sync": dict(last_sync) if last_sync else None,
        "goals": json.loads(get_setting("goals", "[]") or "[]"),
        "kcal_target": get_setting("kcal_target", ""),
        "protein_target": get_setting("protein_target", ""),
        "score": score.overall(),
        # Kurze Reihen fuer die Sparklines der Kacheln — der letzte Wert allein
        # sagt nichts darueber, wohin es geht.
        "recovery": metrics.recovery_series(21),
        "suggestions": suggestions.list_open(4),
        "boosters": boosters.suggest(3),
        "insights": insights.analyse(120),
        "pending_feedback": feedback.pending(2),
        "today": score.today(),
        "goal_progress": _goal_progress(),
    }


def _goal_progress() -> dict[str, Any]:
    """Fortschritt auf die beiden erklärten Hauptziele: 10 km und Klimmzüge."""
    out: dict[str, Any] = {}

    # --- Laufziel
    cooper = get_setting("cooper_distance_m", "")
    goal_km = float(get_setting("run_goal_distance_km", "10") or 10)
    goal_min = float(get_setting("run_goal_time_min", "60") or 60)
    run: dict[str, Any] = {"goal_text": f"{goal_km:g} km unter {goal_min:g} min"}
    if cooper:
        vo2max = max(20.0, (float(cooper) - 504.9) / 44.73)
        pred_s = running.predict_race_time(vo2max, goal_km * 1000)
        gap = pred_s - goal_min * 60
        run["predicted_s"] = int(pred_s)
        run["predicted_text"] = running._fmt_time(pred_s)
        run["reached"] = gap <= 0
        # Fortschritt: von "10 min zu langsam" bis Ziel erreicht
        span = 600.0
        run["progress_pct"] = int(max(0, min(100, (1 - gap / span) * 100)))
        if gap <= 0:
            run["verdict"] = f"Zieltempo sitzt — rechnerisch {running._fmt_time(pred_s)}."
        else:
            run["verdict"] = (f"Prognose {running._fmt_time(pred_s)} — noch "
                              f"{gap / 60:.0f} min bis zum Ziel.")
    out["run"] = run

    # --- Klimmzüge
    goal_reps = int(get_setting("pullup_goal", "10") or 10)
    with get_db() as db:
        row = db.execute(
            "SELECT MAX(s.reps) AS best FROM exercise_sets s "
            "JOIN exercises e ON e.id = s.exercise_id WHERE e.name = 'Klimmzüge'"
        ).fetchone()
    best = (row["best"] if row else None) or None
    if not best:
        stored = get_setting("pullup_best", "")
        best = int(stored) if stored.isdigit() else None
    hint = ""
    if best:
        if best >= goal_reps:
            hint = "Ziel erreicht — Zeit für ein höheres Ziel oder Zusatzgewicht."
        else:
            hint = f"Noch {goal_reps - best} bis zum Ziel. Jede Gym-Einheit zahlt darauf ein."
    out["pullup"] = {"best": best, "goal": goal_reps, "hint": hint}
    return out


@router.get("/health")
def health() -> dict[str, Any]:
    ollama_ok = is_available()
    return {
        "version": VERSION,
        "built_at": BUILT_AT,
        "app": "ok",
        "ollama": ollama_ok,
        "model": ollama_client.active_model(),
        "model_present": model_present() if ollama_ok else False,
        "garmin_linked": get_setting("garmin_linked") == "1",
    }


# ------------------------------------------------------------- KI-Modellwahl

class ModelIn(BaseModel):
    name: str


@router.get("/system/models")
def list_models() -> dict[str, Any]:
    installed = {m.get("name", "") for m in ollama_client.installed_models()}
    active = ollama_client.active_model()
    presets = []
    for p in ollama_client.MODEL_PRESETS:
        base = p["name"].split(":")[0]
        presets.append({**p,
                        "installed": p["name"] in installed
                                     or any(n.split(":")[0] == base for n in installed),
                        "active": p["name"] == active})
    return {
        "active": active,
        "presets": presets,
        "installed": sorted(installed),
        "pull": ollama_client.pull_state(),
        "ollama_reachable": is_available(),
    }


@router.post("/system/model")
def set_model(body: ModelIn) -> dict[str, Any]:
    """Modell wählen und bei Bedarf im Hintergrund herunterladen."""
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Kein Modell angegeben.")
    if not is_available():
        raise HTTPException(503, "Ollama ist nicht erreichbar.")
    set_setting("ollama_model", name)
    if not model_present(name):
        threading.Thread(target=ollama_client.pull_model, args=(name,),
                         daemon=True).start()
        return {"status": "laedt", "model": name}
    return {"status": "bereit", "model": name}


@router.get("/system/model/progress")
def model_progress() -> dict[str, Any]:
    return ollama_client.pull_state()


# -------------------------------------------------------------------- Garmin

class GarminLogin(BaseModel):
    email: str
    password: str


class MfaCode(BaseModel):
    code: str


@router.post("/garmin/login")
def garmin_login(body: GarminLogin) -> dict[str, Any]:
    try:
        return garmin_sync.start_login(body.email, body.password)
    except Exception as e:
        raise HTTPException(400, f"Garmin-Login fehlgeschlagen: {e}")


@router.post("/garmin/mfa")
def garmin_mfa(body: MfaCode) -> dict[str, Any]:
    try:
        return garmin_sync.finish_login_mfa(body.code)
    except Exception as e:
        raise HTTPException(400, f"MFA fehlgeschlagen: {e}")


@router.post("/garmin/sync")
def garmin_do_sync() -> dict[str, Any]:
    res = garmin_sync.full_sync()
    if not res.get("ok") and res.get("not_linked"):
        raise HTTPException(400, res["detail"])
    return res


@router.post("/garmin/unlink")
def garmin_unlink() -> dict[str, str]:
    garmin_sync.unlink()
    return {"status": "ok"}


@router.get("/garmin/status")
def garmin_status() -> dict[str, Any]:
    with get_db() as db:
        last = db.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "linked": get_setting("garmin_linked") == "1",
        "email": get_setting("garmin_email", ""),
        "last_sync": dict(last) if last else None,
    }


# --------------------------------------------------------------- Aktivitäten

class ActivityIn(BaseModel):
    name: str | None = None
    sport: str = "strength"
    start_time: str | None = None
    duration_min: float | None = None
    distance_km: float | None = None
    calories: float | None = None
    avg_hr: float | None = None
    notes: str | None = None


@router.get("/activities")
def list_activities(limit: int = 50) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, garmin_id, source, name, sport, start_time, duration_s, "
            "distance_m, calories, avg_hr, max_hr, training_load, notes "
            "FROM activities ORDER BY start_time DESC LIMIT ?", (limit,)).fetchall()
    return rows_to_dicts(rows)


@router.post("/activities")
def add_activity(a: ActivityIn) -> dict[str, Any]:
    start = a.start_time or dt.datetime.now().isoformat(timespec="minutes")
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO activities(source, name, sport, start_time, duration_s,
               distance_m, calories, avg_hr, notes)
               VALUES('manual',?,?,?,?,?,?,?,?)""",
            (a.name, a.sport, start,
             int(a.duration_min * 60) if a.duration_min else None,
             a.distance_km * 1000 if a.distance_km else None,
             a.calories, a.avg_hr, a.notes))
        return {"id": cur.lastrowid}


@router.post("/activities/fit")
async def upload_fit(file: UploadFile) -> dict[str, Any]:
    content = await file.read()
    try:
        return fit_import.import_fit(content, file.filename or "upload.fit")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int) -> dict[str, str]:
    with get_db() as db:
        db.execute("DELETE FROM activities WHERE id=?", (activity_id,))
    return {"status": "ok"}


# ------------------------------------------------------------------ Workouts

class WorkoutIn(BaseModel):
    name: str
    sport: str = "strength"
    planned_date: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]]


class GenerateIn(BaseModel):
    wish: str | None = None


class PushIn(BaseModel):
    planned_date: str | None = None


class WorkoutPatch(BaseModel):
    status: str | None = None
    planned_date: str | None = None
    name: str | None = None


WEEKDAYS = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}


def _next_date_for(weekday: str | None) -> str | None:
    if not weekday or weekday not in WEEKDAYS:
        return None
    today = dt.date.today()
    delta = (WEEKDAYS[weekday] - today.weekday()) % 7
    return (today + dt.timedelta(days=delta)).isoformat()


def _insert_workout(w: dict[str, Any], created_by: str) -> int:
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO planned_workouts
               (name, sport, planned_date, description, steps_json, created_by)
               VALUES(?,?,?,?,?,?)""",
            (w.get("name", "Workout"), w.get("sport", "strength"),
             w.get("planned_date"), w.get("description"),
             json.dumps({"steps": w.get("steps", [])}, ensure_ascii=False),
             created_by))
        return int(cur.lastrowid or 0)


@router.get("/workouts")
def list_workouts(limit: int = 50) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT * FROM planned_workouts ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall())
    for r in rows:
        r["steps"] = json.loads(r.pop("steps_json") or "{}").get("steps", [])
    return rows


@router.post("/workouts")
def create_workout(w: WorkoutIn) -> dict[str, Any]:
    wid = _insert_workout(w.model_dump(), "user")
    return {"id": wid}


@router.post("/workouts/generate")
def generate_workout(body: GenerateIn) -> dict[str, Any]:
    try:
        w = coach_ai.generate_workout(body.wish)
    except OllamaUnavailable as e:
        raise HTTPException(503, str(e))
    wid = _insert_workout(w, "coach")
    w["id"] = wid
    return w


@router.post("/workouts/plan-week")
def plan_week(body: GenerateIn) -> dict[str, Any]:
    try:
        workouts = coach_ai.generate_week_plan(body.wish)
    except OllamaUnavailable as e:
        raise HTTPException(503, str(e))
    created = []
    for w in workouts:
        w["planned_date"] = w.get("planned_date") or _next_date_for(w.get("weekday"))
        wid = _insert_workout(w, "coach")
        created.append({"id": wid, "name": w.get("name"),
                        "planned_date": w.get("planned_date")})
    return {"created": created}


@router.post("/workouts/{workout_id}/push")
def push_workout(workout_id: int, body: PushIn) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM planned_workouts WHERE id=?",
                         (workout_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Workout nicht gefunden.")
    steps = json.loads(row["steps_json"] or "{}").get("steps", [])
    planned_date = body.planned_date or row["planned_date"]
    wj = build_garmin_workout(row["name"], row["sport"], steps, row["description"])
    try:
        gid = garmin_sync.push_workout(wj, planned_date)
    except GarminNotLinked as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Push zu Garmin fehlgeschlagen: {e}")
    with get_db() as db:
        db.execute("UPDATE planned_workouts SET status='pushed', "
                   "garmin_workout_id=?, planned_date=? WHERE id=?",
                   (gid, planned_date, workout_id))
    return {"status": "pushed", "garmin_workout_id": gid,
            "planned_date": planned_date}


@router.get("/workouts/{workout_id}/fit")
def workout_fit(workout_id: int) -> Response:
    with get_db() as db:
        row = db.execute("SELECT * FROM planned_workouts WHERE id=?",
                         (workout_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Workout nicht gefunden.")
    steps = json.loads(row["steps_json"] or "{}").get("steps", [])
    try:
        data = build_fit_workout(row["name"], row["sport"], steps)
    except Exception as e:
        raise HTTPException(500, f"FIT-Export fehlgeschlagen: {e}")
    fname = "".join(c if c.isalnum() else "_" for c in row["name"])[:40] or "workout"
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition":
                             f'attachment; filename="{fname}.fit"'})


@router.patch("/workouts/{workout_id}")
def patch_workout(workout_id: int, body: WorkoutPatch) -> dict[str, str]:
    sets, vals = [], []
    for field in ("status", "planned_date", "name"):
        v = getattr(body, field)
        if v is not None:
            sets.append(f"{field}=?")
            vals.append(v)
    if not sets:
        return {"status": "ok"}
    vals.append(workout_id)
    with get_db() as db:
        db.execute(f"UPDATE planned_workouts SET {', '.join(sets)} WHERE id=?", vals)
    return {"status": "ok"}


@router.delete("/workouts/{workout_id}")
def delete_workout(workout_id: int) -> dict[str, str]:
    with get_db() as db:
        db.execute("DELETE FROM planned_workouts WHERE id=?", (workout_id,))
    return {"status": "ok"}


# ----------------------------------------------------------------- Ernährung

class NutritionIn(BaseModel):
    day: str | None = None
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    notes: str | None = None


@router.get("/nutrition")
def list_nutrition(days: int = 30) -> list[dict[str, Any]]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute("SELECT * FROM nutrition_log WHERE day >= ? "
                          "ORDER BY day DESC", (since,)).fetchall()
    return rows_to_dicts(rows)


@router.post("/nutrition")
def upsert_nutrition(n: NutritionIn) -> dict[str, str]:
    day = n.day or dt.date.today().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO nutrition_log(day, kcal, protein_g, carbs_g, fat_g, notes)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(day) DO UPDATE SET
                 kcal=COALESCE(excluded.kcal, nutrition_log.kcal),
                 protein_g=COALESCE(excluded.protein_g, nutrition_log.protein_g),
                 carbs_g=COALESCE(excluded.carbs_g, nutrition_log.carbs_g),
                 fat_g=COALESCE(excluded.fat_g, nutrition_log.fat_g),
                 notes=COALESCE(excluded.notes, nutrition_log.notes)""",
            (day, n.kcal, n.protein_g, n.carbs_g, n.fat_g, n.notes))
    return {"status": "ok"}


# ---------------------------------------------------------------- Körperdaten

class BodyIn(BaseModel):
    day: str | None = None
    measured_at: str | None = None      # ISO-Zeitstempel; fehlt er, gilt die
    weight_kg: float | None = None      # Uhrzeit als unbekannt
    body_fat_pct: float | None = None
    muscle_kg: float | None = None
    water_pct: float | None = None
    bone_kg: float | None = None
    visceral_fat: float | None = None
    bmi: float | None = None
    note: str | None = None


@router.get("/body")
def list_body(days: int = 365) -> list[dict[str, Any]]:
    """Einzelne Messungen, neueste zuerst — mehrere pro Tag sind moeglich."""
    return body.measurements(days)


@router.get("/body/summary")
def body_summary(days: int = 180) -> dict[str, Any]:
    """Trend, letzte Werte und wie diszipliniert zur gleichen Zeit gemessen wird."""
    return body.summary(days)


@router.post("/body")
def upsert_body(b: BodyIn) -> dict[str, Any]:
    return body.record(b.model_dump(exclude_none=True), source="manual")


@router.delete("/body/{measurement_id}")
def delete_body(measurement_id: int) -> dict[str, str]:
    if not body.delete(measurement_id):
        raise HTTPException(404, "Diese Messung gibt es nicht (mehr).")
    return {"status": "ok"}


class WeighWindowIn(BaseModel):
    start: str
    end: str


@router.post("/body/window")
def set_weigh_window(w: WeighWindowIn) -> dict[str, Any]:
    """Referenzfenster aendern und alle Messungen neu einordnen."""
    for value in (w.start, w.end):
        parts = value.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts) \
                or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
            raise HTTPException(400, f"Ungültige Uhrzeit: {value!r} (erwartet HH:MM)")
    set_setting("weigh_window_start", w.start)
    set_setting("weigh_window_end", w.end)
    updated = body.recompute()
    return {"status": "ok", "window": body.window_label(), "recomputed": updated}


class ScaleReadingIn(BaseModel):
    weight_kg: float
    body_fat_pct: float | None = None
    muscle_kg: float | None = None
    water_pct: float | None = None
    bone_kg: float | None = None
    lbm_kg: float | None = None
    visceral_fat: float | None = None
    bmi: float | None = None
    impedance: int | None = None
    source: str = "miscale"
    day: str | None = None
    measured_at: str | None = None


@router.post("/body/webhook")
def body_webhook(reading: ScaleReadingIn,
                 x_puls_token: str = Header(default="")) -> dict[str, Any]:
    """Nimmt Messungen der Waage entgegen (vom BLE-Dienst)."""
    expected = get_setting("api_token", "")
    if not expected or x_puls_token != expected:
        raise HTTPException(401, "Ungültiges Token.")
    row = body.record(reading.model_dump(exclude_none=True), source=reading.source)
    with get_db() as db:
        db.execute("INSERT INTO sync_log(ok, detail) VALUES(1, ?)",
                   (f"Waage: {reading.weight_kg} kg"
                    + (f", {reading.body_fat_pct} % Fett" if reading.body_fat_pct else ""),))
    log.info("Waagen-Messung übernommen: %s kg um %s",
             reading.weight_kg, row["measured_at"])
    return {"status": "ok", "day": row["day"], "in_window": row["in_window"]}


# Letzter Zustand des Waagen-Dienstes — bewusst nur im Speicher, nicht in der DB:
# das ist Live-Zustand, der nach einem Neustart ohnehin neu gemeldet wird.
_scale_state: dict[str, Any] = {"received_at": None, "data": None}


@router.post("/scale/report")
def scale_report(payload: dict[str, Any],
                 x_puls_token: str = Header(default="")) -> dict[str, str]:
    """Statusmeldung des Waagen-Dienstes (alle 10 s)."""
    expected = get_setting("api_token", "")
    if not expected or x_puls_token != expected:
        raise HTTPException(401, "Ungültiges Token.")
    _scale_state["data"] = payload
    _scale_state["received_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return {"status": "ok"}


@router.get("/scale/status")
def scale_status() -> dict[str, Any]:
    """Live-Zustand für die Einrichtungsansicht."""
    data = _scale_state["data"]
    received = _scale_state["received_at"]
    age = None
    if received:
        age = int((dt.datetime.now() - dt.datetime.fromisoformat(received)).total_seconds())

    if not data or age is None or age > 60:
        state = "offline"
        hint = ("Der Waagen-Dienst meldet sich nicht. Läuft der Container "
                "puls-miscale, und stimmt das Token darin?")
    elif not (data.get("adapter") or {}).get("present"):
        state = "no_adapter"
        hint = ("Der Dienst läuft, sieht aber keinen Bluetooth-Adapter. Steckt der "
                "Dongle, und ist der Container mit network_mode host und privileged "
                "gestartet?")
    elif not data.get("scanning"):
        state = "not_scanning"
        hint = data.get("last_error") or "Der Scan läuft gerade nicht."
    elif data.get("measurements"):
        state = "ok"
        hint = "Alles läuft — Messungen kommen an."
    elif data.get("scale_frames"):
        state = "scale_found"
        hint = ("Die Waage funkt und wird empfangen. Stell dich drauf und warte, "
                "bis der Wert stabil steht.")
    else:
        state = "searching"
        hint = ("Scan läuft, aber noch kein Waagen-Signal. Die Waage funkt nur, "
                "wenn jemand draufsteht — kurz drauftreten zum Aufwecken.")

    with get_db() as db:
        last = db.execute(
            "SELECT * FROM body_metrics WHERE source='miscale' "
            "ORDER BY measured_at DESC LIMIT 1").fetchone()

    return {
        "state": state,
        "hint": hint,
        "age_s": age,
        "report": data or {},
        "last_measurement": dict(last) if last else None,
    }


@router.post("/body/import")
async def import_body_csv(file: UploadFile) -> dict[str, Any]:
    """CSV-Import, z. B. Export aus Zepp/Mi Fit oder openScale.

    Erwartete Spalten (flexibel): datum/date, gewicht/weight, fett/fat,
    muskel/muscle, wasser/water, knochen/bone. Steht in der Datumsspalte auch
    eine Uhrzeit, wird sie uebernommen — sonst gilt die Messung als
    "Uhrzeit unbekannt" und bleibt aus dem Referenzfenster heraus.
    """
    import csv
    text = (await file.read()).decode("utf-8", errors="replace")
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    aliases = {
        "day": ("date", "datum", "day", "time", "zeit", "timestamp"),
        "weight_kg": ("weight", "gewicht", "weight_kg", "weight(kg)"),
        "body_fat_pct": ("fat", "fett", "bodyfat", "body_fat", "fat(%)"),
        "muscle_kg": ("muscle", "muskel", "muscle_mass", "muskelmasse"),
        "water_pct": ("water", "wasser", "water(%)"),
        "bone_kg": ("bone", "knochen", "bone_mass", "knochenmasse"),
        "visceral_fat": ("visceral", "viszeral", "visceral_fat"),
    }
    imported = 0
    for raw in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        rec: dict[str, Any] = {}
        for target, keys in aliases.items():
            for k in keys:
                if k in row and row[k]:
                    rec[target] = row[k]
                    break
        if "day" not in rec or "weight_kg" not in rec:
            continue

        stamp = rec["day"].strip().replace("/", "-").replace(".", "-")
        date_part, _, time_part = stamp.replace("T", " ").partition(" ")
        parts = date_part.split("-")
        if len(parts) == 3 and len(parts[0]) <= 2:      # DD-MM-YYYY -> ISO
            date_part = f"{parts[2]}-{parts[1]:0>2}-{parts[0]:0>2}"

        def fnum(key: str) -> float | None:
            try:
                return float(str(rec.get(key, "")).replace(",", "."))
            except ValueError:
                return None

        weight = fnum("weight_kg")
        if not weight:
            continue
        entry: dict[str, Any] = {
            "day": date_part, "weight_kg": weight,
            "body_fat_pct": fnum("body_fat_pct"), "muscle_kg": fnum("muscle_kg"),
            "water_pct": fnum("water_pct"), "bone_kg": fnum("bone_kg"),
            "visceral_fat": fnum("visceral_fat"),
        }
        time_part = time_part.strip()
        if len(time_part) >= 5 and time_part[:2].isdigit():
            entry["measured_at"] = f"{date_part}T{time_part[:8]:0<8}"
        try:
            body.record(entry, source="import")
        except (ValueError, sqlite3.Error) as e:
            log.debug("CSV-Zeile übersprungen (%s): %s", e, rec)
            continue
        imported += 1
    return {"imported": imported, "window": body.window_label()}


# ------------------------------------------------------- Erholung & Details

@router.get("/recovery")
def recovery(days: int = 30) -> dict[str, Any]:
    """Schlaf, HRV, Stress, Body Battery und Ruhepuls im Zusammenhang."""
    return metrics.recovery_series(days)


@router.get("/activities/{activity_id}/details")
def activity_details(activity_id: int) -> dict[str, Any]:
    """Karte und Kurven zu einer Aktivitaet."""
    with get_db() as db:
        act = db.execute("SELECT * FROM activities WHERE id=?",
                         (activity_id,)).fetchone()
        row = db.execute("SELECT * FROM activity_details WHERE activity_id=?",
                         (activity_id,)).fetchone()
    if not act:
        raise HTTPException(404, "Diese Aktivität gibt es nicht.")

    out: dict[str, Any] = {"activity": dict(act), "has_details": bool(row)}
    if not row:
        out["hint"] = ("Für diese Einheit wurden noch keine Detaildaten geholt. "
                       "Sie kommen beim nächsten Sync — oder sofort über "
                       "Mehr → Garmin → Verlauf nachladen.")
        return out
    for field in ("series", "track", "bounds"):
        raw = row[f"{field}_json"]
        out[field] = json.loads(raw) if raw else None
    out["splits"] = activity_details_svc.normalize_splits(
        json.loads(row["splits_json"]) if row["splits_json"] else None)
    out["fetched_at"] = row["fetched_at"]
    out["point_count"] = row["point_count"]
    return out


@router.post("/garmin/backfill")
def garmin_backfill(days: int = 3650) -> dict[str, Any]:
    """Gesamten Verlauf nachladen — laeuft im Hintergrund."""
    return garmin_sync.start_backfill(days)


@router.get("/garmin/backfill/status")
def garmin_backfill_status() -> dict[str, Any]:
    return garmin_sync.backfill_state()


@router.get("/garmin/diagnose")
def garmin_diagnose() -> dict[str, Any]:
    """Prueft der Reihe nach, woran es liegt, wenn keine Daten ankommen."""
    return garmin_sync.diagnose()


@router.post("/garmin/backfill/reset")
def garmin_backfill_reset() -> dict[str, Any]:
    """Festgefahrenen Import freigeben."""
    return garmin_sync.reset_backfill()


@router.post("/garmin/backfill/cancel")
def garmin_backfill_cancel() -> dict[str, Any]:
    """Laufenden Import abbrechen — das bereits Geholte bleibt."""
    return garmin_sync.cancel_backfill()


# ---------------------------------------------- Schwung, Gedächtnis, Feedback

@router.get("/boosters")
def boosters_suggest(count: int = 3) -> dict[str, Any]:
    """Konkrete Massnahmen zur aktuellen Lage — Bewaehrtes zuerst."""
    return {**boosters.suggest(count), "works": boosters.what_works(),
            "open": boosters.open_ratings()}


class BoosterRating(BaseModel):
    helpful: bool


@router.post("/boosters/{tip_id}/rate")
def booster_rate(tip_id: str, r: BoosterRating) -> dict[str, Any]:
    if not boosters.rate(tip_id, r.helpful):
        raise HTTPException(404, "Diese Maßnahme gibt es nicht.")
    return {"status": "ok", "works": boosters.what_works()}


class MemoryIn(BaseModel):
    topic: str
    fact: str
    pinned: bool = False


@router.get("/memory")
def memory_list() -> list[dict[str, Any]]:
    return memory.all_facts()


@router.post("/memory")
def memory_add(m: MemoryIn) -> dict[str, Any]:
    try:
        return {"id": memory.remember(m.topic, m.fact, "user", m.pinned)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/memory/{memory_id}")
def memory_delete(memory_id: int) -> dict[str, str]:
    if not memory.forget(memory_id):
        raise HTTPException(404, "Diesen Merkposten gibt es nicht.")
    return {"status": "ok"}


class FeedbackIn(BaseModel):
    rating: int | None = None
    effort: int | None = None
    note: str | None = None


@router.get("/feedback/pending")
def feedback_pending() -> dict[str, Any]:
    """Einheiten, zu denen noch keine Rueckmeldung vorliegt."""
    return {"activities": feedback.pending(), "patterns": feedback.patterns()}


@router.post("/activities/{activity_id}/feedback")
def feedback_save(activity_id: int, f: FeedbackIn) -> dict[str, Any]:
    try:
        return feedback.save(activity_id, f.rating, f.effort, f.note)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ------------------------------------------------------- Coach-Vorschläge

@router.get("/suggestions")
def suggestions_open() -> dict[str, Any]:
    """Offene Vorschlaege — und was zuletzt daraus wurde."""
    return {"open": suggestions.list_open(), "history": suggestions.history(10),
            "focus": suggestions.active_focus()}


@router.post("/suggestions/refresh")
def suggestions_refresh() -> dict[str, Any]:
    """Regeln jetzt pruefen (sonst passiert das beim Sync)."""
    created = suggestions.generate()
    return {"created": len(created), "open": suggestions.list_open()}


@router.post("/suggestions/{sid}/apply")
def suggestion_apply(sid: int) -> dict[str, Any]:
    try:
        return suggestions.apply(sid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/suggestions/{sid}/dismiss")
def suggestion_dismiss(sid: int) -> dict[str, str]:
    if not suggestions.dismiss(sid):
        raise HTTPException(404, "Diesen offenen Vorschlag gibt es nicht.")
    return {"status": "ok"}


# ------------------------------------------------------------- Statistik

@router.get("/stats/matrix")
def stats_matrix(days: int = 365, min_r: float = 0.0) -> dict[str, Any]:
    """Jede Groesse gegen jede — belastbare Funde zuerst."""
    return stats.matrix(days, min_r)


@router.get("/stats/metrics")
def stats_metrics() -> list[dict[str, Any]]:
    """Welche Groessen es gibt, nach Gruppen."""
    return [{"key": k, "label": label, "group": group, "unit": unit,
             "higher_is_better": better}
            for k, label, group, unit, better in stats.METRICS]


@router.get("/stats/metric/{key}")
def stats_metric(key: str, days: int = 365) -> dict[str, Any]:
    try:
        data = stats.for_metric(key, days)
    except ValueError as e:
        raise HTTPException(404, str(e))
    data["series"] = stats.series(key, min(days, 180))
    return data


@router.get("/stats/recommendations")
def stats_recommendations(days: int = 365) -> dict[str, Any]:
    """Was aus den belastbaren Funden konkret folgt."""
    return stats.recommendations(days)


@router.post("/stats/explain")
def stats_explain(days: int = 365, limit: int = 6) -> dict[str, str]:
    """Einschaetzung des Coaches zu den staerksten Zusammenhaengen."""
    return {"message": coach_ai.stats_readout(days, limit)}


# ------------------------------------------------------------- Autopilot

@router.get("/autopilot")
def autopilot_get() -> dict[str, Any]:
    return autopilot.settings()


class AutopilotIn(BaseModel):
    enabled: bool | None = None
    focus: str | None = None
    available_days: list[str] | None = None
    session_minutes: int | None = None
    long_run_day: str | None = None
    wishes: str | None = None


@router.post("/autopilot")
def autopilot_save(a: AutopilotIn) -> dict[str, Any]:
    return autopilot.save_settings(a.model_dump(exclude_none=True))


@router.get("/autopilot/preview")
def autopilot_preview() -> dict[str, Any]:
    """Vorschau der kommenden Woche, ohne etwas anzulegen."""
    return autopilot.plan()


@router.post("/autopilot/apply")
def autopilot_apply() -> dict[str, Any]:
    """Die Woche tatsaechlich anlegen."""
    return autopilot.plan(apply_it=True)


@router.post("/autopilot/explain")
def autopilot_explain() -> dict[str, str]:
    return {"message": autopilot.explain(autopilot.plan())}


# ---------------------------------------------------------- Tag & Schlaf

@router.get("/today")
def today_checklist() -> dict[str, Any]:
    """Was heute noch zu einem vollstaendigen Tag fehlt."""
    return score.today()


@router.post("/coach/checkin")
def coach_checkin(kind: str = "midday") -> dict[str, str]:
    return {"message": coach_ai.checkin(kind)}


@router.post("/coach/sleep")
def coach_sleep() -> dict[str, str]:
    """Was konkret den Schlaf verbessern wuerde."""
    return {"message": coach_ai.sleep_advice()}


# ---------------------------------------------------- Zusammenhänge & Essen

@router.get("/insights")
def insights_all(days: int = 120) -> dict[str, Any]:
    """Was mit deinem Befinden einhergeht — und was dagegen."""
    return insights.analyse(days)


@router.get("/nutrition/targets")
def nutrition_targets() -> dict[str, Any]:
    """Zielwerte aus Alter, Größe, Gewicht und Trainingsbelastung."""
    return nutrition.targets()


@router.get("/nutrition/day")
def nutrition_day(day: str | None = None) -> dict[str, Any]:
    return nutrition.day(day)


class MealIn(BaseModel):
    name: str
    slot: str = "other"
    kcal: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    portions: float = 1
    eaten_at: str | None = None


@router.post("/nutrition/meals")
def meal_add(m: MealIn) -> dict[str, Any]:
    return nutrition.add_meal(m.model_dump())


class RecipeMealIn(BaseModel):
    recipe_id: str
    portions: float = 1
    slot: str = "other"
    eaten_at: str | None = None


@router.post("/nutrition/meals/from-recipe")
def meal_from_recipe(m: RecipeMealIn) -> dict[str, Any]:
    try:
        return nutrition.add_recipe(m.recipe_id, m.portions, m.slot, m.eaten_at)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/nutrition/meals/{meal_id}")
def meal_delete(meal_id: int) -> dict[str, str]:
    if not nutrition.delete_meal(meal_id):
        raise HTTPException(404, "Diese Mahlzeit gibt es nicht.")
    return {"status": "ok"}


# ------------------------------------------------------------------ Score

@router.get("/score")
def coach_score() -> dict[str, Any]:
    """Wie zufrieden der Coach gerade ist — und wo das meiste Potenzial liegt."""
    return score.overall()


# ---------------------------------------------------------------- Rezepte

@router.get("/recipes/suggest")
def recipes_suggest(day: str | None = None, meal: str | None = None,
                    count: int = 3) -> dict[str, Any]:
    """Rezepte passend zur heutigen Trainingslage."""
    return recipes.suggest(day, meal, count)


@router.post("/recipes/explain")
def recipes_explain(day: str | None = None, meal: str | None = None
                    ) -> dict[str, str]:
    """Begruendung vom Modell — die Zahlen kommen aus der Auswahl."""
    return {"text": recipes.explain(recipes.suggest(day, meal))}


@router.get("/recipes")
def recipes_all(meal: str | None = None) -> list[dict[str, Any]]:
    return recipes.all_recipes(meal)


@router.get("/recipes/{recipe_id}")
def recipe_one(recipe_id: str) -> dict[str, Any]:
    r = recipes.get(recipe_id)
    if not r:
        raise HTTPException(404, "Dieses Rezept gibt es nicht.")
    return r


@router.get("/activities/log")
def activity_log(days: int = 365, sport: str | None = None,
                 limit: int = 300) -> dict[str, Any]:
    """Vollstaendiges Trainingsprotokoll, filterbar nach Sportart."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    clause = " AND a.sport = ?" if sport else ""
    params: list[Any] = [since] + ([sport] if sport else []) + [limit]
    with get_db() as db:
        rows = db.execute(
            f"""SELECT a.id, a.name, a.sport, a.start_time, a.duration_s,
                       a.distance_m, a.avg_hr, a.max_hr, a.calories, a.source,
                       a.elevation_gain, a.aerobic_te, a.training_load,
                       (a.analysis_json IS NOT NULL) AS has_analysis,
                       (d.activity_id IS NOT NULL) AS has_details
                FROM activities a
                LEFT JOIN activity_details d ON d.activity_id = a.id
                WHERE substr(a.start_time,1,10) >= ?{clause}
                ORDER BY a.start_time DESC LIMIT ?""", params).fetchall()
        totals = db.execute(
            f"""SELECT a.sport, COUNT(*) AS n, SUM(a.duration_s) AS seconds,
                       SUM(a.distance_m) AS meters
                FROM activities a
                WHERE substr(a.start_time,1,10) >= ?{clause}
                GROUP BY a.sport""", params[:-1]).fetchall()
    return {
        "activities": rows_to_dicts(rows),
        "totals": rows_to_dicts(totals),
        "days": days,
    }


# ------------------------------------------------------------ Supplements

class SupplementIn(BaseModel):
    name: str
    dose: str | None = None
    trigger_kind: str = "time"        # time | after_gym | after_run
    at_time: str | None = None
    weekdays: list[str] | None = None
    note: str | None = None
    active: bool = True
    sort_order: int = 100


@router.get("/supplements")
def supplements_today(day: str | None = None) -> dict[str, Any]:
    """Was heute ansteht — mit Faelligkeit und Stand."""
    return supplements.today(day)


@router.get("/supplements/all")
def supplements_all() -> list[dict[str, Any]]:
    return supplements.list_all()


@router.post("/supplements")
def supplement_create(s: SupplementIn) -> dict[str, Any]:
    try:
        return {"id": supplements.upsert(s.model_dump())}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/supplements/{supp_id}")
def supplement_update(supp_id: int, s: SupplementIn) -> dict[str, Any]:
    try:
        return {"id": supplements.upsert(s.model_dump(), supp_id)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/supplements/{supp_id}")
def supplement_delete(supp_id: int) -> dict[str, str]:
    if not supplements.delete(supp_id):
        raise HTTPException(404, "Dieses Supplement gibt es nicht.")
    return {"status": "ok"}


@router.post("/supplements/{supp_id}/taken")
def supplement_taken(supp_id: int, day: str | None = None,
                     taken: bool = True) -> dict[str, Any]:
    supplements.mark(supp_id, day, taken)
    return supplements.today(day)


@router.get("/supplements/streak")
def supplement_streak(days: int = 30) -> dict[str, Any]:
    return supplements.streak(days)


# ------------------------------------------------------- Gemuetszustand

class MoodIn(BaseModel):
    recorded_at: str | None = None
    mood: int | None = None
    energy: int | None = None
    stress: int | None = None
    note: str | None = None
    complaints: list[dict[str, Any]] | None = None


class MoodTextIn(BaseModel):
    note: str


@router.get("/mood")
def mood_list(days: int = 30) -> dict[str, Any]:
    """Eintraege, Verlauf und was daraus fuers Training folgt."""
    return {
        "entries": mood.entries(days),
        "trend": mood.trend(days),
        "adaptations": mood.adaptations(),
        "regions": mood.REGIONS,
        "kinds": mood.KINDS,
    }


@router.post("/mood")
def mood_create(m: MoodIn) -> dict[str, Any]:
    return mood.record(m.model_dump(exclude_none=True))


@router.delete("/mood/{entry_id}")
def mood_delete(entry_id: int) -> dict[str, str]:
    if not mood.delete(entry_id):
        raise HTTPException(404, "Diesen Eintrag gibt es nicht.")
    return {"status": "ok"}


@router.post("/mood/suggest")
def mood_suggest(m: MoodTextIn) -> dict[str, Any]:
    """Freitext auf Beschwerden lesen — als Vorschlag, nicht als Tatsache."""
    found = mood.suggest_from_text(m.note)
    return {"complaints": [
        {**c, "region_label": mood.REGIONS[c["region"]],
         "kind_label": mood.KINDS[c["kind"]]} for c in found]}


@router.get("/mood/adaptations")
def mood_adaptations() -> dict[str, Any]:
    return mood.adaptations()


# --------------------------------------------------------------------- Coach

class AskIn(BaseModel):
    question: str


class TopicIn(BaseModel):
    topic: str | None = None


@router.post("/coach/ask")
def coach_ask(body: AskIn) -> dict[str, str]:
    return {"answer": coach_ai.answer_question(body.question)}


@router.post("/coach/daily")
def coach_daily() -> dict[str, str]:
    return {"message": coach_ai.daily_message()}


@router.post("/coach/rest")
def coach_rest() -> dict[str, str]:
    return {"message": coach_ai.rest_recommendation()}


@router.post("/coach/nutrition")
def coach_nutrition() -> dict[str, str]:
    return {"message": coach_ai.nutrition_advice()}


@router.post("/coach/research")
def coach_research(body: TopicIn) -> dict[str, str]:
    return {"tip": coach_ai.research_tip(body.topic)}


@router.post("/coach/readout")
def coach_readout() -> dict[str, str]:
    """Kommentar zu Puls, Schlaf, Stress und Bereitschaft."""
    return {"message": coach_ai.daily_readout()}


@router.post("/coach/mood-advice")
def coach_mood_advice() -> dict[str, str]:
    """Konkreter Vorschlag bei einem Tief."""
    return {"message": coach_ai.mood_advice()}


@router.get("/coach/messages")
def coach_messages(limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM coach_messages ORDER BY id DESC LIMIT ?",
                          (limit,)).fetchall()
    return rows_to_dicts(rows)


@router.get("/coach/research-tips")
def research_tips(limit: int = 10) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = db.execute("SELECT * FROM research_tips ORDER BY id DESC LIMIT ?",
                          (limit,)).fetchall()
    return rows_to_dicts(rows)


# ----------------------------------------------------------------- Settings

class SettingsIn(BaseModel):
    goals: list[str] | None = None
    weekly_workout_target: int | None = None
    kcal_target: str | None = None
    protein_target: str | None = None
    profile: dict[str, Any] | None = None
    run_days: list[str] | None = None
    run_minutes: int | None = None
    gym_days: list[str] | None = None
    gym_minutes: int | None = None
    evening_mobility: bool | None = None
    prefer_machines: bool | None = None
    run_goal_distance_km: float | None = None
    run_goal_time_min: float | None = None
    pullup_goal: int | None = None
    font_scale: int | None = None


# ------------------------------------------------------------ Übungsbibliothek

class ExerciseIn(BaseModel):
    name: str | None = None
    muscle_group: str | None = None
    equipment: str | None = None
    mode: str | None = None
    slot: str | None = None
    priority: int | None = None
    weight_kg: float | None = None
    weight_increment: float | None = None
    target_reps: int | None = None
    rep_min: int | None = None
    rep_max: int | None = None
    target_duration_s: int | None = None
    sets: int | None = None
    rest_s: int | None = None
    machine_setting: str | None = None
    garmin_category: str | None = None
    garmin_exercise: str | None = None
    active: int | None = None
    sort_order: int | None = None
    notes: str | None = None
    aliases: list[str] | None = None


@router.get("/exercises")
def get_exercises(only_active: bool = False) -> dict[str, Any]:
    items = ex_lib.list_exercises(only_active=only_active)
    for it in items:
        it["days_since"] = ex_lib.days_since(it.get("last_performed"))
    return {
        "exercises": items,
        "muscle_labels": ex_lib.MUSCLE_LABELS,
        "equipment_labels": ex_lib.EQUIPMENT_LABELS,
        "slot_labels": ex_lib.SLOT_LABELS,
    }


@router.post("/exercises")
def create_exercise(body: ExerciseIn) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data.get("name"):
        raise HTTPException(400, "Name fehlt.")
    data.setdefault("muscle_group", "main")
    data.setdefault("equipment", "machine")
    return {"id": ex_lib.upsert_exercise(data)}


@router.patch("/exercises/{ex_id}")
def patch_exercise(ex_id: int, body: ExerciseIn) -> dict[str, Any]:
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    ex_lib.upsert_exercise(data, ex_id)
    return {"status": "ok"}


@router.delete("/exercises/{ex_id}")
def remove_exercise(ex_id: int) -> dict[str, str]:
    ex_lib.delete_exercise(ex_id)
    return {"status": "ok"}


@router.get("/exercises/{ex_id}/history")
def exercise_history(ex_id: int) -> dict[str, Any]:
    with get_db() as db:
        sets = rows_to_dicts(db.execute(
            "SELECT * FROM exercise_sets WHERE exercise_id=? "
            "ORDER BY day DESC, set_index LIMIT 60", (ex_id,)).fetchall())
    return {"sets": sets, "progression": ex_lib.progression_history(ex_id)}


class SetIn(BaseModel):
    exercise_id: int
    reps: int | None = None
    weight_kg: float | None = None
    duration_s: float | None = None
    day: str | None = None
    set_index: int = 1
    feeling: str | None = None


@router.post("/sets")
def add_set(body: SetIn) -> dict[str, Any]:
    new_id = ex_lib.record_set(
        body.exercise_id, reps=body.reps, weight_kg=body.weight_kg,
        duration_s=body.duration_s, day=body.day, set_index=body.set_index,
        feeling=body.feeling, source="manual")
    return {"id": new_id}


class ProgressIn(BaseModel):
    day: str | None = None


@router.post("/sets/apply-progression")
def run_progression(body: ProgressIn) -> dict[str, Any]:
    day = body.day or dt.date.today().isoformat()
    return {"results": ex_lib.apply_progression_for_day(day)}


# ----------------------------------------------------------------- Benchmark

class CalibrateIn(BaseModel):
    exercise_id: int
    reps: int
    weight_kg: float | None = None


class CooperIn(BaseModel):
    distance_m: float | None = None
    activity_id: int | None = None


class PullupIn(BaseModel):
    reps: int


@router.get("/benchmark/status")
def benchmark_status() -> dict[str, Any]:
    return benchmark.status()


@router.post("/benchmark/strength/create")
def create_strength_benchmark() -> dict[str, Any]:
    w = benchmark.build_strength_benchmark()
    wid = _insert_workout(w, "coach")
    return {"id": wid, "name": w["name"], "steps": w["steps"]}


@router.post("/benchmark/run/create")
def create_run_benchmark() -> dict[str, Any]:
    w = running.build_cooper_test()
    wid = _insert_workout(w, "coach")
    return {"id": wid, "name": w["name"], "steps": w["steps"]}


@router.post("/benchmark/calibrate-exercise")
def calibrate_one(body: CalibrateIn) -> dict[str, Any]:
    res = benchmark.calibrate_exercise(body.exercise_id, body.reps, body.weight_kg)
    if not res:
        raise HTTPException(404, "Übung nicht gefunden.")
    return res


@router.post("/benchmark/calibrate-from-sets")
def calibrate_from_sets(body: ProgressIn) -> dict[str, Any]:
    return {"results": benchmark.calibrate_from_sets(body.day)}


@router.post("/benchmark/cooper")
def cooper(body: CooperIn) -> dict[str, Any]:
    if body.distance_m:
        return running.calibrate_from_cooper(body.distance_m)
    if body.activity_id:
        res = running.evaluate_cooper_from_activity(body.activity_id)
        if not res:
            raise HTTPException(
                400, "Aus dieser Aktivität ließ sich der 12-Minuten-Block nicht "
                     "herauslesen. Trag die Distanz bitte von Hand ein.")
        return res
    raise HTTPException(400, "Distanz oder Aktivität angeben.")


@router.post("/benchmark/pullup")
def pullup_max(body: PullupIn) -> dict[str, Any]:
    return benchmark.record_pullup_max(body.reps)


# ------------------------------------------------------------- Wochenplanung

class WeekPlanIn(BaseModel):
    start: str | None = None
    include_runs: bool = True
    include_gym: bool = True
    include_mobility: bool = True
    replace: bool = True


@router.get("/plan/overview")
def plan_overview() -> dict[str, Any]:
    return planner.week_overview()


@router.post("/plan/week")
def create_week_plan(body: WeekPlanIn) -> dict[str, Any]:
    start = dt.date.fromisoformat(body.start) if body.start else dt.date.today()
    end = start + dt.timedelta(days=6)
    if body.replace:
        with get_db() as db:
            db.execute("DELETE FROM planned_workouts WHERE status='planned' "
                       "AND created_by='coach' AND planned_date BETWEEN ? AND ?",
                       (start.isoformat(), end.isoformat()))
    workouts = planner.plan_week(start, body.include_runs, body.include_gym,
                                 body.include_mobility)
    created = []
    for w in workouts:
        wid = _insert_workout(w, "coach")
        created.append({"id": wid, "name": w["name"],
                        "planned_date": w.get("planned_date"),
                        "sport": w["sport"], "time_of_day": w.get("time_of_day")})
    return {"created": created, "count": len(created)}


@router.post("/plan/gym-session")
def create_gym_session() -> dict[str, Any]:
    w = planner.build_gym_session()
    wid = _insert_workout(w, "coach")
    return {"id": wid, **w}


@router.get("/yoga/poses")
def yoga_poses() -> dict[str, Any]:
    """Alle Yoga-Stellungen samt Anleitung — für die Vorlage in der App."""
    return {"poses": ex_lib.EVENING_YOGA_POOL}


@router.post("/plan/evening-yoga")
def create_evening_yoga() -> dict[str, Any]:
    w = planner.build_evening_yoga()
    w["planned_date"] = dt.date.today().isoformat()
    wid = _insert_workout(w, "coach")
    return {"id": wid, **w}


class RunIn(BaseModel):
    kind: str = "easy"
    minutes: int = 25


@router.post("/plan/run")
def create_run(body: RunIn) -> dict[str, Any]:
    builders = {
        "easy": running.build_easy_run, "tempo": running.build_tempo_run,
        "interval": running.build_interval_run, "long": running.build_long_run,
        "goal": running.build_goal_pace_run,
    }
    fn = builders.get(body.kind)
    if not fn:
        raise HTTPException(400, f"Unbekannte Laufart: {body.kind}")
    w = fn(body.minutes)
    w["planned_date"] = dt.date.today().isoformat()
    wid = _insert_workout(w, "coach")
    return {"id": wid, **w}


@router.get("/activities/{activity_id}/analysis")
def activity_analysis(activity_id: int) -> dict[str, Any]:
    """Bewertung einer Laufeinheit — wird bei Bedarf neu berechnet."""
    with get_db() as db:
        row = db.execute("SELECT * FROM activities WHERE id=?",
                         (activity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Aktivität nicht gefunden.")
    act = dict(row)
    analysis = None
    gym = None
    if act.get("sport") == "strength":
        gym = gym_analysis.analyse(activity_id, (act.get("start_time") or "")[:10])
    else:
        analysis = run_analysis.get_analysis(activity_id)
        if not analysis:
            analysis = run_analysis.analyse_and_store(activity_id)
    act.pop("raw_json", None)
    act.pop("analysis_json", None)
    if act.get("hr_zones_json"):
        try:
            act["hr_zones"] = json.loads(act.pop("hr_zones_json"))
        except (ValueError, TypeError):
            act.pop("hr_zones_json", None)
    return {"activity": act, "analysis": analysis, "gym": gym,
            "feedback": feedback.get(activity_id)}


@router.get("/running/trend")
def running_trend(days: int = 365) -> dict[str, Any]:
    """Entwicklung ueber alle Laeufe: Effizienz, Umfang, Intensitaet, Bestwerte."""
    return run_analysis.form_trend(days)


@router.get("/running/summary")
def running_summary(limit: int = 8) -> dict[str, Any]:
    return run_analysis.recent_summary(limit)


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return {
        "goals": json.loads(get_setting("goals", "[]") or "[]"),
        "weekly_workout_target": int(get_setting("weekly_workout_target", "4") or 4),
        "kcal_target": get_setting("kcal_target", ""),
        "protein_target": get_setting("protein_target", ""),
        "profile": json.loads(get_setting("profile", "{}") or "{}"),
        "run_days": json.loads(get_setting("run_days", "[]") or "[]"),
        "run_minutes": int(get_setting("run_minutes", "25") or 25),
        "gym_days": json.loads(get_setting("gym_days", "[]") or "[]"),
        "gym_minutes": int(get_setting("gym_minutes", "75") or 75),
        "evening_mobility": get_setting("evening_mobility", "1") == "1",
        "prefer_machines": get_setting("prefer_machines", "1") == "1",
        "run_goal_distance_km": float(get_setting("run_goal_distance_km", "10") or 10),
        "run_goal_time_min": float(get_setting("run_goal_time_min", "60") or 60),
        "pullup_goal": int(get_setting("pullup_goal", "10") or 10),
        "font_scale": int(get_setting("font_scale", "100") or 100),
        "api_token": get_setting("api_token", ""),
    }


@router.post("/settings")
def post_settings(s: SettingsIn) -> dict[str, str]:
    if s.goals is not None:
        set_setting("goals", json.dumps(s.goals))
    if s.weekly_workout_target is not None:
        set_setting("weekly_workout_target", str(s.weekly_workout_target))
    if s.kcal_target is not None:
        set_setting("kcal_target", s.kcal_target)
    if s.protein_target is not None:
        set_setting("protein_target", s.protein_target)
    if s.profile is not None:
        set_setting("profile", json.dumps(s.profile, ensure_ascii=False))
    if s.run_days is not None:
        set_setting("run_days", json.dumps(s.run_days))
    if s.run_minutes is not None:
        set_setting("run_minutes", str(s.run_minutes))
    if s.gym_days is not None:
        set_setting("gym_days", json.dumps(s.gym_days))
    if s.gym_minutes is not None:
        set_setting("gym_minutes", str(s.gym_minutes))
    if s.evening_mobility is not None:
        set_setting("evening_mobility", "1" if s.evening_mobility else "0")
    if s.prefer_machines is not None:
        set_setting("prefer_machines", "1" if s.prefer_machines else "0")
    if s.run_goal_distance_km is not None:
        set_setting("run_goal_distance_km", str(s.run_goal_distance_km))
    if s.run_goal_time_min is not None:
        set_setting("run_goal_time_min", str(s.run_goal_time_min))
    if s.pullup_goal is not None:
        set_setting("pullup_goal", str(s.pullup_goal))
    if s.font_scale is not None:
        set_setting("font_scale", str(max(85, min(150, s.font_scale))))
    return {"status": "ok"}
