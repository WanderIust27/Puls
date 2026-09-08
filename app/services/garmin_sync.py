"""Garmin-Connect-Anbindung: Login (inkl. MFA), Sync, Workout-Push.

Nutzt die inoffizielle Connect-API über die garminconnect-Bibliothek.
Nach dem ersten Login werden nur OAuth-Tokens gespeichert — nie das Passwort.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from typing import Any

from garminconnect import Garmin

from ..config import GARMIN_TOKEN_DIR, SYNC_LOOKBACK_DAYS
from ..db import get_db, get_setting, rows_to_dicts, set_setting

log = logging.getLogger("puls.garmin")

_client: Garmin | None = None
_client_lock = threading.Lock()
_mfa_state: dict[str, Any] | None = None  # Zwischenspeicher für laufenden MFA-Login

SPORT_MAP = {
    "running": "running",
    "trail_running": "running",
    "treadmill_running": "running",
    "track_running": "running",
    "strength_training": "strength",
    "indoor_cardio": "cardio",
    "cardio": "cardio",
    "hiit": "cardio",
    "cycling": "cardio",
    "indoor_cycling": "cardio",
    "walking": "cardio",
    "hiking": "cardio",
    "yoga": "mobility",
    "pilates": "mobility",
    "stretching": "mobility",
    "breathwork": "mobility",
}


class GarminNotLinked(Exception):
    pass


def _tokenstore() -> str:
    return str(GARMIN_TOKEN_DIR)


def get_client() -> Garmin:
    """Client aus gespeicherten Tokens; wirft GarminNotLinked ohne Verknüpfung."""
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        if get_setting("garmin_linked") != "1":
            raise GarminNotLinked("Garmin ist nicht verknüpft.")
        g = Garmin()
        try:
            g.login(_tokenstore())
        except Exception as e:
            raise GarminNotLinked(f"Garmin-Tokens ungültig, bitte neu anmelden: {e}") from e
        _client = g
        return g


def start_login(email: str, password: str) -> dict[str, Any]:
    """Login starten. Ergebnis: {status: 'ok'|'needs_mfa'}"""
    global _client, _mfa_state
    with _client_lock:
        g = Garmin(email=email, password=password, return_on_mfa=True)
        result1, result2 = g.login()
        if result1 == "needs_mfa":
            _mfa_state = {"garmin": g, "client_state": result2, "email": email}
            return {"status": "needs_mfa"}
        g.client.dump(_tokenstore())
        set_setting("garmin_linked", "1")
        set_setting("garmin_email", email)
        _client = g
        return {"status": "ok"}


def finish_login_mfa(code: str) -> dict[str, Any]:
    global _client, _mfa_state
    with _client_lock:
        if not _mfa_state:
            raise ValueError("Kein MFA-Login in Arbeit — bitte Login neu starten.")
        g: Garmin = _mfa_state["garmin"]
        g.resume_login(_mfa_state["client_state"], code)
        g.client.dump(_tokenstore())
        set_setting("garmin_linked", "1")
        set_setting("garmin_email", _mfa_state["email"])
        _client = g
        _mfa_state = None
        return {"status": "ok"}


def unlink() -> None:
    global _client
    with _client_lock:
        _client = None
    set_setting("garmin_linked", "0")
    set_setting("garmin_email", "")
    for f in GARMIN_TOKEN_DIR.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass


def _map_sport(type_key: str | None) -> str:
    if not type_key:
        return "other"
    return SPORT_MAP.get(type_key, "other")


def _num(d: dict, *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def sync_activities(g: Garmin, days: int) -> int:
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    end = dt.date.today().isoformat()
    acts = g.get_activities_by_date(start, end) or []
    new = 0
    with get_db() as db:
        for a in acts:
            gid = str(a.get("activityId"))
            type_key = (a.get("activityType") or {}).get("typeKey")
            row = (
                gid,
                "garmin",
                a.get("activityName"),
                _map_sport(type_key),
                (a.get("startTimeLocal") or a.get("startTimeGMT") or "").replace(" ", "T"),
                int(a.get("duration") or 0),
                _num(a, "distance"),
                _num(a, "calories"),
                _num(a, "averageHR", "avgHr"),
                _num(a, "maxHR", "maxHr"),
                _num(a, "activityTrainingLoad", "trainingLoad"),
                json.dumps(a),
            )
            cur = db.execute(
                """INSERT INTO activities
                   (garmin_id, source, name, sport, start_time, duration_s, distance_m,
                    calories, avg_hr, max_hr, training_load, raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(garmin_id) DO UPDATE SET
                     name=excluded.name, duration_s=excluded.duration_s,
                     distance_m=excluded.distance_m, calories=excluded.calories,
                     avg_hr=excluded.avg_hr, max_hr=excluded.max_hr,
                     training_load=excluded.training_load, raw_json=excluded.raw_json""",
                row,
            )
            if cur.lastrowid:
                new += 1
    return new


def _first_num(d: dict, *keys: str) -> float | None:
    """Garmin benennt Felder je nach Endpunkt unterschiedlich — erste Treffer gewinnt."""
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def sync_running_metrics(g: Garmin, days: int) -> int:
    """Holt Laufkennzahlen: Puls-Zonen, Schrittfrequenz, Laufeffizienz, Trainingseffekt.

    Die Fenix 7 zeichnet Schrittfrequenz und Schrittlänge am Handgelenk auf;
    Bodenkontaktzeit und vertikale Bewegung nur mit Brustgurt (HRM-Pro) oder
    RD-Pod. Fehlende Werte bleiben leer — die Bewertung kommt damit klar.
    """
    from . import run_analysis

    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        acts = rows_to_dicts(db.execute(
            "SELECT id, garmin_id, raw_json, analysis_json FROM activities "
            "WHERE sport IN ('running','cardio') AND garmin_id IS NOT NULL "
            "AND date(start_time) >= ? ORDER BY start_time DESC LIMIT 25",
            (since,)).fetchall())

    updated = 0
    for act in acts:
        # Schon vollständig ausgewertet? Dann nicht erneut abfragen.
        if act.get("analysis_json"):
            continue
        raw = json.loads(act["raw_json"] or "{}")

        # 1. Kennzahlen aus der Zusammenfassung. Fehlt etwas, die Detailansicht holen.
        summary = raw
        if not any(k in raw for k in ("averageRunningCadenceInStepsPerMinute",
                                      "avgGroundContactTime", "aerobicTrainingEffect")):
            try:
                detail = g.get_activity(act["garmin_id"]) or {}
                summary = {**raw, **(detail.get("summaryDTO") or {}), **detail}
            except Exception as e:
                log.debug("Details für %s nicht abrufbar: %s", act["garmin_id"], e)

        vals = {
            "avg_cadence": _first_num(summary, "averageRunningCadenceInStepsPerMinute",
                                      "averageRunCadence", "avgRunCadence"),
            "max_cadence": _first_num(summary, "maxRunningCadenceInStepsPerMinute",
                                      "maxRunCadence"),
            "avg_stride_m": None,
            "ground_contact_ms": _first_num(summary, "avgGroundContactTime",
                                            "averageGroundContactTime"),
            "vertical_osc_cm": _first_num(summary, "avgVerticalOscillation",
                                          "averageVerticalOscillation"),
            "vertical_ratio": _first_num(summary, "avgVerticalRatio",
                                         "averageVerticalRatio"),
            "avg_power": _first_num(summary, "avgPower", "averagePower"),
            "elevation_gain": _first_num(summary, "elevationGain", "totalElevationGain"),
            "aerobic_te": _first_num(summary, "aerobicTrainingEffect"),
            "anaerobic_te": _first_num(summary, "anaerobicTrainingEffect"),
            "vo2max": _first_num(summary, "vO2MaxValue", "vo2MaxValue"),
        }
        stride = _first_num(summary, "avgStrideLength", "averageStrideLength")
        if stride:
            # Garmin liefert die Schrittlänge in Zentimetern
            vals["avg_stride_m"] = round(stride / 100.0, 2) if stride > 5 else stride

        # 2. Zeit in den Herzfrequenzzonen
        zones = None
        try:
            zone_data = g.get_activity_hr_in_timezones(act["garmin_id"]) or []
            if isinstance(zone_data, list) and zone_data:
                zones = {
                    str(z.get("zoneNumber")): round(float(z.get("secsInZone") or 0))
                    for z in zone_data if z.get("zoneNumber") is not None
                }
        except Exception as e:
            log.debug("HF-Zonen für %s nicht abrufbar: %s", act["garmin_id"], e)

        with get_db() as db:
            db.execute(
                """UPDATE activities SET
                     avg_cadence=COALESCE(?, avg_cadence),
                     max_cadence=COALESCE(?, max_cadence),
                     avg_stride_m=COALESCE(?, avg_stride_m),
                     ground_contact_ms=COALESCE(?, ground_contact_ms),
                     vertical_osc_cm=COALESCE(?, vertical_osc_cm),
                     vertical_ratio=COALESCE(?, vertical_ratio),
                     avg_power=COALESCE(?, avg_power),
                     elevation_gain=COALESCE(?, elevation_gain),
                     aerobic_te=COALESCE(?, aerobic_te),
                     anaerobic_te=COALESCE(?, anaerobic_te),
                     vo2max=COALESCE(?, vo2max),
                     hr_zones_json=COALESCE(?, hr_zones_json)
                   WHERE id=?""",
                (vals["avg_cadence"], vals["max_cadence"], vals["avg_stride_m"],
                 vals["ground_contact_ms"], vals["vertical_osc_cm"],
                 vals["vertical_ratio"], vals["avg_power"], vals["elevation_gain"],
                 vals["aerobic_te"], vals["anaerobic_te"], vals["vo2max"],
                 json.dumps(zones) if zones else None, act["id"]))

        # 3. Runden holen, damit die Bewertung die Ermüdung im Verlauf sehen kann
        laps = None
        try:
            split_data = g.get_activity_splits(act["garmin_id"]) or {}
            laps = split_data.get("lapDTOs") or split_data.get("splits")
        except Exception as e:
            log.debug("Runden für %s nicht abrufbar: %s", act["garmin_id"], e)

        # 4. Bewerten und Ergebnis ablegen
        try:
            run_analysis.analyse_and_store(act["id"], laps)
        except Exception as e:
            log.warning("Laufbewertung für %s fehlgeschlagen: %s", act["id"], e)
        updated += 1

    return updated


def sync_exercise_sets(g: Garmin, days: int) -> int:
    """Holt die auf der Uhr aufgezeichneten Kraftsätze zurück in die Bibliothek.

    Die Fenix protokolliert bei Kraft-Workouts Übung, Wiederholungen und Gewicht.
    Genau daraus lebt die Progression — deshalb wird sie danach fortgeschrieben.
    """
    from . import exercises as ex_lib

    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        acts = rows_to_dicts(db.execute(
            "SELECT id, garmin_id, start_time FROM activities "
            "WHERE sport='strength' AND garmin_id IS NOT NULL AND date(start_time) >= ? "
            "ORDER BY start_time DESC LIMIT 20", (since,)).fetchall())

    imported = 0
    touched_days: set[str] = set()
    for act in acts:
        try:
            data = g.get_activity_exercise_sets(act["garmin_id"]) or {}
        except Exception as e:
            log.debug("Sätze für %s nicht abrufbar: %s", act["garmin_id"], e)
            continue
        sets = data.get("exerciseSets") or []
        day = (act["start_time"] or "")[:10]
        index_per_ex: dict[int, int] = {}
        for i, s in enumerate(sets):
            if str(s.get("setType") or "").upper() not in ("ACTIVE", ""):
                continue  # Pausen überspringen
            infos = s.get("exercises") or []
            gname = gcat = None
            if infos:
                gname = infos[0].get("name")
                gcat = infos[0].get("category")
            ex = ex_lib.match_exercise(gname, gcat)
            if not ex:
                log.debug("Übung ohne Zuordnung: %s / %s", gcat, gname)
                continue
            reps = s.get("repetitionCount")
            weight = s.get("weight")            # Gramm
            weight_kg = round(weight / 1000.0, 2) if weight else None
            duration = s.get("duration")
            idx = index_per_ex.get(ex["id"], 0) + 1
            index_per_ex[ex["id"]] = idx
            key = f"{act['garmin_id']}:{i}"
            new_id = ex_lib.record_set(
                ex["id"], reps=reps, weight_kg=weight_kg, duration_s=duration,
                day=day, set_index=idx, source="garmin",
                activity_id=act["id"], garmin_set_key=key)
            if new_id:
                imported += 1
                touched_days.add(day)

    # Progression nur für Tage fortschreiben, an denen wirklich Neues ankam
    for day in sorted(touched_days):
        try:
            results = ex_lib.apply_progression_for_day(day)
            if results:
                log.info("Progression %s: %s", day,
                         ", ".join(f"{r['exercise']}={r['action']}" for r in results))
        except Exception as e:
            log.warning("Progression für %s fehlgeschlagen: %s", day, e)
    return imported


def sync_daily_metrics(g: Garmin, days: int) -> int:
    count = 0
    for i in range(days):
        day = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        entry: dict[str, Any] = {"day": day}
        try:
            sleep = g.get_sleep_data(day) or {}
            daily = sleep.get("dailySleepDTO") or {}
            entry["sleep_seconds"] = daily.get("sleepTimeSeconds")
            scores = daily.get("sleepScores") or {}
            entry["sleep_score"] = (scores.get("overall") or {}).get("value")
        except Exception as e:
            log.debug("sleep %s: %s", day, e)
        try:
            hrv = g.get_hrv_data(day) or {}
            summary = hrv.get("hrvSummary") or {}
            entry["hrv_avg"] = summary.get("lastNightAvg") or summary.get("weeklyAvg")
            entry["hrv_status"] = summary.get("status")
        except Exception as e:
            log.debug("hrv %s: %s", day, e)
        try:
            tr = g.get_training_readiness(day)
            if isinstance(tr, list) and tr:
                tr = tr[0]
            if isinstance(tr, dict):
                entry["training_readiness"] = tr.get("score")
        except Exception as e:
            log.debug("readiness %s: %s", day, e)
        try:
            steps = g.get_daily_steps(day, day)
            if isinstance(steps, list) and steps:
                entry["steps"] = steps[0].get("totalSteps")
        except Exception as e:
            log.debug("steps %s: %s", day, e)
        if len(entry) == 1:
            continue
        with get_db() as db:
            db.execute(
                """INSERT INTO daily_metrics
                   (day, sleep_seconds, sleep_score, hrv_avg, hrv_status,
                    training_readiness, steps)
                   VALUES(:day,:sleep_seconds,:sleep_score,:hrv_avg,:hrv_status,
                          :training_readiness,:steps)
                   ON CONFLICT(day) DO UPDATE SET
                     sleep_seconds=COALESCE(excluded.sleep_seconds, daily_metrics.sleep_seconds),
                     sleep_score=COALESCE(excluded.sleep_score, daily_metrics.sleep_score),
                     hrv_avg=COALESCE(excluded.hrv_avg, daily_metrics.hrv_avg),
                     hrv_status=COALESCE(excluded.hrv_status, daily_metrics.hrv_status),
                     training_readiness=COALESCE(excluded.training_readiness, daily_metrics.training_readiness),
                     steps=COALESCE(excluded.steps, daily_metrics.steps)""",
                {k: entry.get(k) for k in
                 ("day", "sleep_seconds", "sleep_score", "hrv_avg", "hrv_status",
                  "training_readiness", "steps")},
            )
        count += 1
    return count


def sync_body_composition(g: Garmin, days: int) -> int:
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    end = dt.date.today().isoformat()
    count = 0
    try:
        data = g.get_body_composition(start, end) or {}
    except Exception as e:
        log.debug("body composition: %s", e)
        return 0
    for entry in data.get("dateWeightList") or []:
        day = entry.get("calendarDate")
        weight = entry.get("weight")
        if not day or not weight:
            continue
        with get_db() as db:
            db.execute(
                """INSERT INTO body_metrics(day, weight_kg, body_fat_pct, muscle_kg, source)
                   VALUES(?,?,?,?, 'garmin')
                   ON CONFLICT(day, source) DO UPDATE SET
                     weight_kg=excluded.weight_kg,
                     body_fat_pct=COALESCE(excluded.body_fat_pct, body_metrics.body_fat_pct),
                     muscle_kg=COALESCE(excluded.muscle_kg, body_metrics.muscle_kg)""",
                (day, round(weight / 1000.0, 2), entry.get("bodyFat"),
                 (entry.get("muscleMass") or 0) / 1000.0 or None),
            )
        count += 1
    return count


def full_sync() -> dict[str, Any]:
    """Kompletter Sync-Lauf; Ergebnis wird in sync_log festgehalten."""
    try:
        g = get_client()
        n_act = sync_activities(g, SYNC_LOOKBACK_DAYS)
        n_sets = sync_exercise_sets(g, SYNC_LOOKBACK_DAYS)
        n_runs = sync_running_metrics(g, SYNC_LOOKBACK_DAYS)
        n_days = sync_daily_metrics(g, min(SYNC_LOOKBACK_DAYS, 7))
        n_body = sync_body_composition(g, 90)
        detail = (f"{n_act} Aktivitäten, {n_sets} Sätze, {n_runs} Läufe bewertet, "
                  f"{n_days} Tagesmetriken, {n_body} Körperwerte")
        with get_db() as db:
            db.execute("INSERT INTO sync_log(ok, detail) VALUES(1, ?)", (detail,))
        log.info("Sync ok: %s", detail)
        return {"ok": True, "detail": detail}
    except GarminNotLinked as e:
        return {"ok": False, "detail": str(e), "not_linked": True}
    except Exception as e:
        with get_db() as db:
            db.execute("INSERT INTO sync_log(ok, detail) VALUES(0, ?)", (str(e),))
        log.warning("Sync fehlgeschlagen: %s", e)
        return {"ok": False, "detail": str(e)}


def push_workout(workout_json: dict[str, Any], planned_date: str | None) -> str:
    """Workout nach Garmin Connect hochladen und optional auf ein Datum planen.

    Gibt die Garmin-Workout-ID zurück.
    """
    g = get_client()
    res = g.upload_workout(workout_json)
    workout_id = str(res.get("workoutId") or res.get("id") or "")
    if not workout_id:
        raise RuntimeError(f"Unerwartete Antwort von Garmin: {res}")
    if planned_date:
        try:
            g.schedule_workout(workout_id, planned_date)
        except Exception as e:
            log.warning("Workout %s hochgeladen, aber Planung auf %s fehlgeschlagen: %s",
                        workout_id, planned_date, e)
    return workout_id


def upload_fit_activity(path: str) -> Any:
    g = get_client()
    return g.upload_activity(path)
