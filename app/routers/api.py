"""Alle API-Endpunkte."""
from __future__ import annotations

import datetime as dt
import io
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..db import get_db, get_setting, rows_to_dicts, set_setting
from ..services import (benchmark, coach_ai, fit_import, garmin_sync, metrics,
                        ollama_client, planner, run_analysis, running)
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
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    muscle_kg: float | None = None
    water_pct: float | None = None


@router.get("/body")
def list_body(days: int = 365) -> list[dict[str, Any]]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute("SELECT * FROM body_metrics WHERE day >= ? "
                          "ORDER BY day DESC", (since,)).fetchall()
    return rows_to_dicts(rows)


@router.post("/body")
def upsert_body(b: BodyIn) -> dict[str, str]:
    day = b.day or dt.date.today().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO body_metrics(day, weight_kg, body_fat_pct, muscle_kg,
                                        water_pct, source)
               VALUES(?,?,?,?,?, 'manual')
               ON CONFLICT(day, source) DO UPDATE SET
                 weight_kg=COALESCE(excluded.weight_kg, body_metrics.weight_kg),
                 body_fat_pct=COALESCE(excluded.body_fat_pct, body_metrics.body_fat_pct),
                 muscle_kg=COALESCE(excluded.muscle_kg, body_metrics.muscle_kg),
                 water_pct=COALESCE(excluded.water_pct, body_metrics.water_pct)""",
            (day, b.weight_kg, b.body_fat_pct, b.muscle_kg, b.water_pct))
    return {"status": "ok"}


class ScaleReadingIn(BaseModel):
    weight_kg: float
    body_fat_pct: float | None = None
    muscle_kg: float | None = None
    water_pct: float | None = None
    bmi: float | None = None
    impedance: int | None = None
    source: str = "miscale"
    day: str | None = None


@router.post("/body/webhook")
def body_webhook(body: ScaleReadingIn,
                 x_puls_token: str = Header(default="")) -> dict[str, Any]:
    """Nimmt Messungen der Waage entgegen (vom BLE-Dienst)."""
    expected = get_setting("api_token", "")
    if not expected or x_puls_token != expected:
        raise HTTPException(401, "Ungültiges Token.")
    day = body.day or dt.date.today().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO body_metrics(day, weight_kg, body_fat_pct, muscle_kg,
                                        water_pct, source)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(day, source) DO UPDATE SET
                 weight_kg=excluded.weight_kg,
                 body_fat_pct=COALESCE(excluded.body_fat_pct, body_metrics.body_fat_pct),
                 muscle_kg=COALESCE(excluded.muscle_kg, body_metrics.muscle_kg),
                 water_pct=COALESCE(excluded.water_pct, body_metrics.water_pct)""",
            (day, body.weight_kg, body.body_fat_pct, body.muscle_kg,
             body.water_pct, body.source))
        db.execute("INSERT INTO sync_log(ok, detail) VALUES(1, ?)",
                   (f"Waage: {body.weight_kg} kg"
                    + (f", {body.body_fat_pct} % Fett" if body.body_fat_pct else ""),))
    log.info("Waagen-Messung übernommen: %s kg", body.weight_kg)
    return {"status": "ok", "day": day}


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
            "ORDER BY day DESC LIMIT 1").fetchone()

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
    muskel/muscle, wasser/water."""
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
    }
    imported = 0
    with get_db() as db:
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
            day = rec["day"][:10].replace(".", "-").replace("/", "-")
            parts = day.split("-")
            if len(parts) == 3 and len(parts[0]) <= 2:  # DD-MM-YYYY -> ISO
                day = f"{parts[2]}-{parts[1]:0>2}-{parts[0]:0>2}"
            def fnum(key: str) -> float | None:
                try:
                    return float(str(rec.get(key, "")).replace(",", "."))
                except ValueError:
                    return None
            w = fnum("weight_kg")
            if not w:
                continue
            db.execute(
                """INSERT INTO body_metrics(day, weight_kg, body_fat_pct,
                                            muscle_kg, water_pct, source)
                   VALUES(?,?,?,?,?, 'import')
                   ON CONFLICT(day, source) DO UPDATE SET
                     weight_kg=excluded.weight_kg,
                     body_fat_pct=excluded.body_fat_pct,
                     muscle_kg=excluded.muscle_kg,
                     water_pct=excluded.water_pct""",
                (day, w, fnum("body_fat_pct"), fnum("muscle_kg"), fnum("water_pct")))
            imported += 1
    return {"imported": imported}


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
    return {"activity": act, "analysis": analysis}


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
