"""Die API von PULS — vier Ansichten, ein Vorschlag für heute.

Bewusst knapp gehalten: Jeder Reiter holt sich seine Daten mit einem Aufruf,
und was kein Reiter zeigt, gibt es hier auch nicht.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..db import get_db, get_setting, rows_to_dicts, set_setting
from ..version import BUILT_AT, VERSION
from ..services import (body, facts, fit_import, garmin_sync, gym_analysis,
                        logbook, mood, ollama_client, planner, run_analysis,
                        running, session_request, today as today_svc, trends)
from ..services import activity_details as activity_details_svc
from ..services import exercises as ex_lib
from ..services.garmin_sync import GarminNotLinked
from ..services.ollama_client import (OllamaUnavailable, is_available,
                                      model_present)
from ..services.workout_builder import build_fit_workout, build_garmin_workout
from ..puls_knowledge import PROMPT_TEMPLATE

log = logging.getLogger("puls.api")
router = APIRouter(prefix="/api")

WEEKDAYS = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}


# ------------------------------------------------------------------- System

@router.get("/health")
def health() -> dict[str, Any]:
    ollama_ok = is_available()
    return {"version": VERSION, "built_at": BUILT_AT, "app": "ok",
            "ollama": ollama_ok, "model": ollama_client.active_model(),
            "model_present": model_present() if ollama_ok else False,
            "garmin_linked": get_setting("garmin_linked") == "1"}


class ModelIn(BaseModel):
    name: str


@router.get("/system/models")
def list_models() -> dict[str, Any]:
    installed = {m.get("name", "") for m in ollama_client.installed_models()}
    active = ollama_client.active_model()
    presets = []
    for p in ollama_client.MODEL_PRESETS:
        base = p["name"].split(":")[0]
        presets.append({**p, "active": p["name"] == active,
                        "installed": p["name"] in installed
                                     or any(n.split(":")[0] == base for n in installed)})
    return {"active": active, "presets": presets, "installed": sorted(installed),
            "pull": ollama_client.pull_state(), "ollama_reachable": is_available()}


@router.post("/system/model")
def set_model(payload: ModelIn) -> dict[str, Any]:
    name = payload.name.strip()
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


# --------------------------------------------------------------- Coach-Frage

class AskIn(BaseModel):
    frage: str


@router.get("/coach/status")
def coach_status(request: Request) -> dict[str, Any]:
    """Steht die Wissensdatenbank bereit — und wenn nicht, warum nicht?"""
    kb = getattr(request.app.state, "kb", None)
    return {
        "bereit": kb is not None,
        "abschnitte": kb.size() if kb else 0,
        "modell": kb.embedder.profile.model if kb else None,
        "fehler": getattr(request.app.state, "kb_error", None),
    }


@router.post("/coach/ask")
def coach_ask(payload: AskIn, request: Request) -> dict[str, Any]:
    """Eine Frage an den Coach — mit geprüftem Wissen statt aus dem Gedächtnis.

    Die Quellenliste kommt aus dem Abruf, nicht aus der Antwort. Was das
    Modell selbst an Dateinamen nennt, ist nicht überprüfbar; was hier steht,
    lag ihm tatsächlich vor. Genau das ist bei einer merkwürdigen Antwort die
    erste Frage: Lag es am Abruf oder am Modell?
    """
    question = (payload.frage or "").strip()
    if len(question) < 4:
        raise HTTPException(400, "Stell eine Frage.")

    kb = getattr(request.app.state, "kb", None)
    playbook = getattr(request.app.state, "playbook", "") or ""
    computed = facts.computed_block()

    if kb is None:
        context, sources = "", []
    else:
        context, sources = kb.context_with_sources(question)

    prompt = PROMPT_TEMPLATE.format(
        playbook=playbook.strip(),
        kontext=context or "(Keine passenden Auszüge gefunden.)",
        berechnet=computed or "—",
        frage=question,
    )
    try:
        answer = ollama_client.generate(prompt, temperature=0.3)
    except OllamaUnavailable as e:
        raise HTTPException(503, f"Das Modell antwortet nicht: {e}")

    return {"antwort": answer, "quellen": sources, "berechnet": computed,
            "wissensbasis": kb is not None,
            "hinweis": None if kb is not None else
                       "Ohne Wissensdatenbank — die Antwort stammt allein aus "
                       "dem Modell und ist nicht belegt."}


# -------------------------------------------------------------------- Heute

@router.get("/today")
def today_view(phrase: bool = True) -> dict[str, Any]:
    """Die Gesamtempfehlung für heute."""
    return today_svc.recommendation(phrase=phrase)


@router.post("/today/plan")
def today_to_plan() -> dict[str, Any]:
    """Die empfohlene Einheit als geplante Einheit übernehmen."""
    rec = today_svc.recommendation(phrase=False)
    session = rec.get("session")
    if not session:
        raise HTTPException(400, "Für heute gibt es keine Einheit zum Planen.")
    session["planned_date"] = rec["day"]
    wid = _insert_workout(session, "coach")
    return {"id": wid, "name": session.get("name"), "planned_date": rec["day"]}


# --------------------------------------------------------------------- Plan

def _insert_workout(w: dict[str, Any], created_by: str) -> int:
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO planned_workouts
               (name, sport, planned_date, description, steps_json, created_by)
               VALUES(?,?,?,?,?,?)""",
            (w.get("name", "Einheit"), w.get("sport", "strength"),
             w.get("planned_date"), w.get("description"),
             json.dumps({"steps": w.get("steps", [])}, ensure_ascii=False),
             created_by))
        return int(cur.lastrowid or 0)


def _planned(limit: int = 30) -> list[dict[str, Any]]:
    """Geplante Einheiten, das naechste Datum zuerst."""
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT id, name, sport, planned_date, description, status,
                      garmin_workout_id, created_by, steps_json
               FROM planned_workouts WHERE status IN ('planned','pushed')
               ORDER BY planned_date IS NULL, planned_date, id LIMIT ?""",
            (limit,)).fetchall())
    for r in rows:
        try:
            r["steps"] = json.loads(r.pop("steps_json") or "{}").get("steps", [])
        except ValueError:
            r["steps"] = []
        r["step_count"] = len(r["steps"])
        r["minutes"] = round(planner.step_seconds(r["steps"]) / 60) or None
    return rows


@router.get("/plan")
def plan_view() -> dict[str, Any]:
    return {
        "workouts": _planned(),
        "week": planner.week_overview(),
        "structure": {
            "gym_days": json.loads(get_setting("gym_days", "[]") or "[]"),
            "run_days": json.loads(get_setting("run_days", "[]") or "[]"),
            "gym_minutes": int(get_setting("gym_minutes", "75") or 75),
            "run_minutes": int(get_setting("run_minutes", "45") or 45),
            "evening_mobility": get_setting("evening_mobility", "1") == "1",
        },
        "goal": trends.goal_focus(),
    }


class WeekIn(BaseModel):
    include_runs: bool = True


@router.post("/plan/week")
def plan_week(payload: WeekIn) -> dict[str, Any]:
    """Die kommende Woche neu legen — die alte weicht dafür."""
    today = dt.date.today().isoformat()
    with get_db() as db:
        # Was der Coach gelegt hat, wird ersetzt. Selbst eingetragene Einheiten
        # bleiben, und Vergangenes wird aufgeraeumt statt mitgeschleppt.
        db.execute("DELETE FROM planned_workouts WHERE created_by='coach' "
                   "AND status='planned' AND (planned_date IS NULL OR planned_date >= ?)",
                   (today,))
        db.execute("UPDATE planned_workouts SET status='skipped' "
                   "WHERE status='planned' AND planned_date < ?", (today,))
    created = []
    for w in planner.plan_week(include_runs=payload.include_runs):
        created.append({"id": _insert_workout(w, "coach"), "name": w.get("name"),
                        "planned_date": w.get("planned_date")})
    return {"created": created}


class WishIn(BaseModel):
    text: str


@router.post("/plan/wish")
def plan_wish(payload: WishIn) -> dict[str, Any]:
    """Eine Einheit auf Zuruf: „90 Minuten Ganzkörper", „30 Minuten zuhause Bauch"."""
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(400, "Schreib hin, was du trainieren willst.")
    return session_request.build(text)


class WorkoutIn(BaseModel):
    name: str
    sport: str = "strength"
    planned_date: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]] = []


@router.post("/plan/workouts")
def add_workout(payload: WorkoutIn) -> dict[str, Any]:
    return {"id": _insert_workout(payload.model_dump(), "user")}


class WorkoutPatch(BaseModel):
    status: str | None = None
    planned_date: str | None = None
    name: str | None = None


@router.patch("/plan/workouts/{workout_id}")
def patch_workout(workout_id: int, payload: WorkoutPatch) -> dict[str, str]:
    fields, values = [], []
    for field in ("status", "planned_date", "name"):
        value = getattr(payload, field)
        if value is not None:
            fields.append(f"{field}=?")
            values.append(value)
    if fields:
        values.append(workout_id)
        with get_db() as db:
            db.execute(f"UPDATE planned_workouts SET {', '.join(fields)} WHERE id=?",
                       values)
    return {"status": "ok"}


@router.delete("/plan/workouts/{workout_id}")
def delete_workout(workout_id: int) -> dict[str, str]:
    with get_db() as db:
        db.execute("DELETE FROM planned_workouts WHERE id=?", (workout_id,))
    return {"status": "ok"}


class PushIn(BaseModel):
    planned_date: str | None = None


def _workout_row(workout_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM planned_workouts WHERE id=?",
                         (workout_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Diese Einheit gibt es nicht.")
    return dict(row)


@router.post("/plan/workouts/{workout_id}/push")
def push_workout(workout_id: int, payload: PushIn) -> dict[str, Any]:
    row = _workout_row(workout_id)
    steps = json.loads(row["steps_json"] or "{}").get("steps", [])
    planned_date = payload.planned_date or row["planned_date"]
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
    return {"status": "pushed", "garmin_workout_id": gid, "planned_date": planned_date}


@router.post("/plan/push-all")
def push_all() -> dict[str, Any]:
    """Alle offenen Einheiten auf die Uhr schieben."""
    pushed, failed = [], []
    for w in _planned():
        if w["status"] == "pushed":
            continue
        try:
            push_workout(w["id"], PushIn(planned_date=w["planned_date"]))
            pushed.append(w["name"])
        except HTTPException as e:
            failed.append({"name": w["name"], "detail": e.detail})
    return {"pushed": pushed, "failed": failed}


@router.get("/plan/workouts/{workout_id}/fit")
def workout_fit(workout_id: int) -> Response:
    row = _workout_row(workout_id)
    steps = json.loads(row["steps_json"] or "{}").get("steps", [])
    try:
        data = build_fit_workout(row["name"], row["sport"], steps)
    except Exception as e:
        raise HTTPException(500, f"FIT-Export fehlgeschlagen: {e}")
    name = "".join(c if c.isalnum() else "_" for c in row["name"])[:40] or "einheit"
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}.fit"'})


# ---------------------------------------------------------------- Kraft

@router.get("/strength")
def strength_view() -> dict[str, Any]:
    items = ex_lib.list_exercises()
    for it in items:
        it["days_since"] = ex_lib.days_since(it.get("last_performed"))
    return {
        "exercises": items,
        "sessions": logbook.recent_sessions(8),
        "proposals": ex_lib.open_proposals(30),
        "muscles": trends.muscles(),
        "changes": ex_lib.recent_changes(days=21),
        "muscle_labels": ex_lib.MUSCLE_LABELS,
        "equipment_labels": ex_lib.EQUIPMENT_LABELS,
        "slot_labels": ex_lib.SLOT_LABELS,
    }


class DescribeIn(BaseModel):
    text: str
    day: str | None = None


@router.post("/strength/describe")
def describe_training(payload: DescribeIn) -> dict[str, Any]:
    """Ein Training in Worten lesen — noch ohne zu speichern."""
    return logbook.preview(payload.text or "")


class CommitIn(BaseModel):
    day: str
    items: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []


@router.post("/strength/commit")
def commit_training(payload: CommitIn) -> dict[str, Any]:
    """Die bestätigte Vorschau eintragen."""
    if not payload.items and not payload.runs:
        raise HTTPException(400, "Da ist nichts zum Eintragen.")
    return logbook.commit(payload.day, payload.items, payload.runs)


@router.post("/strength/proposals/recalculate")
def recalculate_proposals(days: int = 21) -> dict[str, Any]:
    """Die Vorgaben an die letzten Trainings anpassen.

    Nuetzlich nach einem Nachtrag oder wenn ein Sync Saetze gebracht hat, die
    beim ersten Durchlauf noch fehlten.
    """
    since = (dt.date.today() - dt.timedelta(days=max(1, min(365, days)))).isoformat()
    with get_db() as db:
        training_days = [r["day"] for r in db.execute(
            "SELECT DISTINCT day FROM exercise_sets WHERE day >= ? ORDER BY day",
            (since,)).fetchall()]
    made: list[dict[str, Any]] = []
    for day in training_days:
        made += ex_lib.propose_for_day(day)
    return {"days": len(training_days), "proposals": ex_lib.open_proposals(30),
            "made": len(made)}


class DecideIn(BaseModel):
    accept: bool = True


@router.post("/strength/proposals/all")
def decide_all_proposals(payload: DecideIn) -> dict[str, Any]:
    return {"count": ex_lib.decide_all(payload.accept)}


@router.post("/strength/proposals/{proposal_id}")
def decide_proposal(proposal_id: int, payload: DecideIn) -> dict[str, Any]:
    result = ex_lib.decide_proposal(proposal_id, payload.accept)
    if not result:
        raise HTTPException(404, "Dieser Vorschlag ist schon entschieden.")
    return result


class ExerciseIn(BaseModel):
    name: str | None = None
    muscle_group: str | None = None
    equipment: str | None = None
    mode: str | None = None
    weight_kg: float | None = None
    weight_increment: float | None = None
    target_reps: int | None = None
    rep_min: int | None = None
    rep_max: int | None = None
    target_duration_s: int | None = None
    sets: int | None = None
    rest_s: int | None = None
    machine_setting: str | None = None
    slot: str | None = None
    priority: int | None = None
    assisted: int | None = None
    active: int | None = None
    notes: str | None = None


@router.post("/exercises")
def create_exercise(payload: ExerciseIn) -> dict[str, Any]:
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not data.get("name"):
        raise HTTPException(400, "Name fehlt.")
    data.setdefault("muscle_group", "core")
    data.setdefault("equipment", "machine")
    return {"id": ex_lib.upsert_exercise(data)}


@router.patch("/exercises/{ex_id}")
def patch_exercise(ex_id: int, payload: ExerciseIn) -> dict[str, str]:
    ex_lib.upsert_exercise({k: v for k, v in payload.model_dump().items()
                            if v is not None}, ex_id)
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


@router.post("/sets")
def add_set(payload: SetIn) -> dict[str, Any]:
    return {"id": ex_lib.record_set(
        payload.exercise_id, reps=payload.reps, weight_kg=payload.weight_kg,
        duration_s=payload.duration_s, day=payload.day,
        set_index=payload.set_index, source="manual")}


# --------------------------------------------------------------------- Laufen

@router.get("/running")
def running_view(limit: int = 20) -> dict[str, Any]:
    since = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    with get_db() as db:
        runs = rows_to_dicts(db.execute(
            """SELECT a.id, a.name, a.source, a.start_time, a.duration_s,
                      a.distance_m, a.avg_hr, a.max_hr, a.calories, a.vo2max,
                      a.avg_cadence, a.elevation_gain, a.training_load,
                      (a.analysis_json IS NOT NULL) AS has_analysis,
                      (d.activity_id IS NOT NULL) AS has_details
               FROM activities a LEFT JOIN activity_details d ON d.activity_id = a.id
               WHERE a.sport='running' AND substr(a.start_time,1,10) >= ?
               ORDER BY a.start_time DESC LIMIT ?""", (since, limit)).fetchall())
    return {"runs": runs, "trend": trends.running_trend(),
            "form": run_analysis.form_trend(365),
            "paces": running.current_paces(),
            "goal": {"distance_km": float(get_setting("run_goal_distance_km", "10") or 10),
                     "time_min": float(get_setting("run_goal_time_min", "60") or 60)}}


@router.get("/activities/{activity_id}/analysis")
def activity_analysis(activity_id: int) -> dict[str, Any]:
    with get_db() as db:
        row = db.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Diese Einheit gibt es nicht.")
    act = dict(row)
    analysis = gym = None
    if act.get("sport") == "strength":
        gym = gym_analysis.analyse(activity_id, (act.get("start_time") or "")[:10])
    else:
        analysis = (run_analysis.get_analysis(activity_id)
                    or run_analysis.analyse_and_store(activity_id))
    act.pop("raw_json", None)
    act.pop("analysis_json", None)
    if act.get("hr_zones_json"):
        try:
            act["hr_zones"] = json.loads(act.pop("hr_zones_json"))
        except (ValueError, TypeError):
            act.pop("hr_zones_json", None)
    return {"activity": act, "analysis": analysis, "gym": gym}


@router.get("/activities/{activity_id}/details")
def activity_details(activity_id: int) -> dict[str, Any]:
    with get_db() as db:
        act = db.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
        row = db.execute("SELECT * FROM activity_details WHERE activity_id=?",
                         (activity_id,)).fetchone()
    if not act:
        raise HTTPException(404, "Diese Einheit gibt es nicht.")
    out: dict[str, Any] = {"activity": dict(act), "has_details": bool(row)}
    if not row:
        out["hint"] = ("Für diese Einheit liegen keine Detaildaten vor. Sie "
                       "kommen beim nächsten Sync.")
        return out
    for field in ("series", "track", "bounds"):
        raw = row[f"{field}_json"]
        out[field] = json.loads(raw) if raw else None
    out["splits"] = activity_details_svc.normalize_splits(
        json.loads(row["splits_json"]) if row["splits_json"] else None)
    out["fetched_at"] = row["fetched_at"]
    out["point_count"] = row["point_count"]
    return out


@router.delete("/activities/{activity_id}")
def delete_activity(activity_id: int) -> dict[str, str]:
    with get_db() as db:
        db.execute("DELETE FROM activities WHERE id=?", (activity_id,))
    return {"status": "ok"}


@router.post("/activities/fit")
async def upload_fit(file: UploadFile) -> dict[str, Any]:
    content = await file.read()
    try:
        return fit_import.import_fit(content, file.filename or "upload.fit")
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------- Gemüt

class MoodIn(BaseModel):
    mood: int | None = None
    energy: int | None = None
    stress: int | None = None
    note: str | None = None
    complaints: list[dict[str, Any]] | None = None
    day: str | None = None
    recorded_at: str | None = None


@router.get("/mood")
def mood_view(days: int = 30) -> dict[str, Any]:
    return {"entries": mood.entries(days), "trend": mood.trend(days),
            "adaptations": mood.adaptations(),
            "regions": mood.REGIONS, "kinds": mood.KINDS}


@router.post("/mood")
def add_mood(payload: MoodIn) -> dict[str, Any]:
    return mood.record(payload.model_dump(exclude_none=True))


@router.delete("/mood/{entry_id}")
def delete_mood(entry_id: int) -> dict[str, str]:
    if not mood.delete(entry_id):
        raise HTTPException(404, "Dieser Eintrag existiert nicht.")
    return {"status": "ok"}


class TextIn(BaseModel):
    text: str


@router.post("/mood/suggest")
def suggest_complaints(payload: TextIn) -> dict[str, Any]:
    return {"complaints": mood.suggest_from_text(payload.text)}


# -------------------------------------------------------------------- Garmin

class GarminLogin(BaseModel):
    email: str
    password: str


class MfaCode(BaseModel):
    code: str


@router.post("/garmin/login")
def garmin_login(payload: GarminLogin) -> dict[str, Any]:
    try:
        return garmin_sync.start_login(payload.email, payload.password)
    except Exception as e:
        raise HTTPException(400, f"Garmin-Login fehlgeschlagen: {e}")


@router.post("/garmin/mfa")
def garmin_mfa(payload: MfaCode) -> dict[str, Any]:
    try:
        return garmin_sync.finish_login_mfa(payload.code)
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
    return {"linked": get_setting("garmin_linked") == "1",
            "email": get_setting("garmin_email", ""),
            "last_sync": dict(last) if last else None}


@router.post("/garmin/backfill")
def garmin_backfill(days: int = 3650) -> dict[str, Any]:
    return garmin_sync.start_backfill(days)


@router.get("/garmin/backfill/status")
def garmin_backfill_status() -> dict[str, Any]:
    return garmin_sync.backfill_state()


@router.post("/garmin/backfill/cancel")
def garmin_backfill_cancel() -> dict[str, Any]:
    return garmin_sync.cancel_backfill()


@router.get("/garmin/diagnose")
def garmin_diagnose() -> dict[str, Any]:
    return garmin_sync.diagnose()


# --------------------------------------------------------------------- Waage

class ScaleReadingIn(BaseModel):
    weight_kg: float
    body_fat_pct: float | None = None
    muscle_kg: float | None = None
    water_pct: float | None = None
    bone_kg: float | None = None
    lbm_kg: float | None = None
    bmi: float | None = None
    visceral_fat: float | None = None
    impedance: int | None = None
    measured_at: str | None = None
    note: str | None = None
    source: str = "miscale"


_scale_state: dict[str, Any] = {"received_at": None, "data": None}


def _check_token(token: str) -> None:
    expected = get_setting("api_token", "")
    if not expected or token != expected:
        raise HTTPException(401, "Ungültiges Token.")


@router.post("/body/webhook")
def body_webhook(reading: ScaleReadingIn,
                 x_puls_token: str = Header(default="")) -> dict[str, Any]:
    """Messungen der Waage entgegennehmen — vom BLE-Dienst im Nachbarcontainer."""
    _check_token(x_puls_token)
    row = body.record(reading.model_dump(exclude_none=True), source=reading.source)
    with get_db() as db:
        db.execute("INSERT INTO sync_log(ok, detail) VALUES(1, ?)",
                   (f"Waage: {reading.weight_kg} kg",))
    return {"status": "ok", "day": row["day"]}


@router.post("/scale/report")
def scale_report(payload: dict[str, Any],
                 x_puls_token: str = Header(default="")) -> dict[str, str]:
    _check_token(x_puls_token)
    _scale_state["data"] = payload
    _scale_state["received_at"] = dt.datetime.now().isoformat(timespec="seconds")
    return {"status": "ok"}


@router.get("/scale/status")
def scale_status() -> dict[str, Any]:
    data, received = _scale_state["data"], _scale_state["received_at"]
    age = (int((dt.datetime.now() - dt.datetime.fromisoformat(received)).total_seconds())
           if received else None)
    if not data or age is None or age > 60:
        state, hint = "offline", ("Der Waagen-Dienst meldet sich nicht. Läuft der "
                                  "Container puls-miscale, und stimmt das Token?")
    elif not (data.get("adapter") or {}).get("present"):
        state, hint = "no_adapter", ("Der Dienst läuft, sieht aber keinen "
                                     "Bluetooth-Adapter.")
    elif not data.get("scanning"):
        state, hint = "not_scanning", (data.get("last_error")
                                       or "Der Scan läuft gerade nicht.")
    elif data.get("measurements"):
        state, hint = "ok", "Alles läuft — Messungen kommen an."
    elif data.get("scale_frames"):
        state, hint = "scale_found", ("Die Waage funkt. Stell dich drauf und warte, "
                                      "bis der Wert steht.")
    else:
        state, hint = "searching", ("Scan läuft, noch kein Waagen-Signal. Kurz "
                                    "drauftreten weckt die Waage.")
    with get_db() as db:
        last = db.execute("SELECT * FROM body_metrics WHERE source='miscale' "
                          "ORDER BY measured_at DESC LIMIT 1").fetchone()
    return {"state": state, "hint": hint, "age_s": age, "report": data or {},
            "last_measurement": dict(last) if last else None}


# --------------------------------------------------------------- Einstellungen

class SettingsIn(BaseModel):
    goal_text: str | None = None
    gym_days: list[str] | None = None
    run_days: list[str] | None = None
    gym_minutes: int | None = None
    run_minutes: int | None = None
    evening_mobility: bool | None = None
    prefer_machines: bool | None = None
    run_goal_distance_km: float | None = None
    run_goal_time_min: float | None = None
    pullup_goal: int | None = None
    font_scale: int | None = None
    prog_rep_min: int | None = None
    prog_rep_max: int | None = None


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return {
        "goal_text": get_setting("goal_text", "") or "",
        "gym_days": json.loads(get_setting("gym_days", "[]") or "[]"),
        "run_days": json.loads(get_setting("run_days", "[]") or "[]"),
        "gym_minutes": int(get_setting("gym_minutes", "75") or 75),
        "run_minutes": int(get_setting("run_minutes", "45") or 45),
        "evening_mobility": get_setting("evening_mobility", "1") == "1",
        "prefer_machines": get_setting("prefer_machines", "1") == "1",
        "run_goal_distance_km": float(get_setting("run_goal_distance_km", "10") or 10),
        "run_goal_time_min": float(get_setting("run_goal_time_min", "60") or 60),
        "pullup_goal": int(get_setting("pullup_goal", "10") or 10),
        "font_scale": int(get_setting("font_scale", "100") or 100),
        "progression": ex_lib._scheme(),
        "api_token": get_setting("api_token", ""),
        "version": VERSION, "built_at": BUILT_AT,
    }


@router.post("/settings")
def post_settings(s: SettingsIn) -> dict[str, str]:
    if s.goal_text is not None:
        set_setting("goal_text", s.goal_text.strip()[:500])
    for key in ("gym_days", "run_days"):
        value = getattr(s, key)
        if value is not None:
            set_setting(key, json.dumps([d for d in value if d in WEEKDAYS]))
    for key, low, high in (("gym_minutes", 20, 150), ("run_minutes", 10, 180),
                           ("pullup_goal", 1, 50), ("font_scale", 85, 150)):
        value = getattr(s, key)
        if value is not None:
            set_setting(key, str(int(max(low, min(high, value)))))
    for key in ("evening_mobility", "prefer_machines"):
        value = getattr(s, key)
        if value is not None:
            set_setting(key, "1" if value else "0")
    for key in ("run_goal_distance_km", "run_goal_time_min"):
        value = getattr(s, key)
        if value is not None:
            set_setting(key, str(float(value)))
    # Die Spanne wird gemeinsam geprueft: Ein Minimum oberhalb des Maximums
    # waere eine Regel, die nie zutrifft.
    if s.prog_rep_min is not None or s.prog_rep_max is not None:
        current = ex_lib._scheme()
        low = int(s.prog_rep_min if s.prog_rep_min is not None else current["rep_min"])
        high = int(s.prog_rep_max if s.prog_rep_max is not None else current["rep_max"])
        low = max(1, min(50, low))
        high = max(low + 1, min(60, high))
        set_setting("prog_rep_min", str(low))
        set_setting("prog_rep_max", str(high))
    return {"status": "ok"}
