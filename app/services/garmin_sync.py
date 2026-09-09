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
from . import activity_details as details
from . import body

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
    """Aktivitaeten der letzten `days` Tage."""
    return sync_activities_range(
        g, (dt.date.today() - dt.timedelta(days=days)).isoformat(),
        dt.date.today().isoformat())


def sync_activities_range(g: Garmin, start: str, end: str) -> int:
    """Aktivitaeten eines Zeitfensters.

    Getrennt von sync_activities, weil der Verlaufs-Import rueckwaerts in
    Scheiben laedt — mit einem "von heute bis X" wuerde jede Scheibe alles
    davor erneut anfordern, und die letzte zoege zehn Jahre auf einmal.
    """
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
            known = db.execute("SELECT 1 FROM activities WHERE garmin_id=?",
                               (gid,)).fetchone()
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
            # lastrowid ist auch nach einem UPDATE gesetzt und taugt hier
            # nicht als Unterscheidung.
            if not known:
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
            # Garmin schreibt -1, wenn die Uhr nichts zaehlen konnte. Als Zahl
            # gelesen waere das "minus eine Wiederholung" — record_set siebt
            # das aus, hier steht es nochmal, damit klar ist warum.
            reps = s.get("repetitionCount")
            weight = s.get("weight")            # Gramm
            weight_kg = round(weight / 1000.0, 2) if (weight or 0) > 0 else None
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
            # Vorschlaege statt stiller Aenderungen: Wer 35 kg statt der
            # geplanten 20 bewegt, hat eine Entscheidung getroffen — die
            # gehoert bestaetigt, nicht nachtraeglich unterstellt.
            results = ex_lib.propose_for_day(day)
            if results:
                log.info("Progression %s: %s", day,
                         ", ".join(f"{r['exercise']}={r['action']}" for r in results))
        except Exception as e:
            log.warning("Progression für %s fehlgeschlagen: %s", day, e)
    return imported


def _downsample(pairs: list[list[Any]], target: int = 96) -> list[list[Any]]:
    """Tagesverlaeufe auf rund 96 Punkte bringen (ein Wert je Viertelstunde)."""
    clean = [[p[0], p[1]] for p in pairs
             if isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] is not None]
    if len(clean) <= target:
        return clean
    step = len(clean) / target
    return [clean[int(i * step)] for i in range(target)]


def _call(g: Garmin, name: str, *args: Any) -> Any:
    """Garmin-Methode aufrufen, falls die installierte Version sie kennt.

    Die inoffizielle Connect-Anbindung aendert sich; fehlt eine Methode oder
    antwortet Garmin nicht, soll das den restlichen Sync nicht aufhalten.
    """
    fn = getattr(g, name, None)
    if fn is None:
        log.debug("garminconnect kennt %s nicht", name)
        return None
    try:
        return fn(*args)
    except Exception as e:
        log.debug("%s: %s", name, e)
        return None


def _collect_day(g: Garmin, day: str) -> dict[str, Any]:
    """Alle Erholungswerte eines Tages einsammeln."""
    entry: dict[str, Any] = {"day": day}

    sleep = _call(g, "get_sleep_data", day) or {}
    daily = sleep.get("dailySleepDTO") or {}
    if daily:
        entry["sleep_seconds"] = daily.get("sleepTimeSeconds")
        entry["sleep_score"] = ((daily.get("sleepScores") or {})
                                .get("overall") or {}).get("value")
        entry["sleep_deep_s"] = daily.get("deepSleepSeconds")
        entry["sleep_light_s"] = daily.get("lightSleepSeconds")
        entry["sleep_rem_s"] = daily.get("remSleepSeconds")
        entry["sleep_awake_s"] = daily.get("awakeSleepSeconds")
        entry["sleep_start"] = daily.get("sleepStartTimestampLocal")
        entry["sleep_end"] = daily.get("sleepEndTimestampLocal")
    for key, field in (("avgOvernightHrv", "hrv_avg"),
                       ("restingHeartRate", "resting_hr"),
                       ("averageRespirationValue", "respiration_avg"),
                       ("averageSpO2", "spo2_avg")):
        if sleep.get(key) is not None:
            entry.setdefault(field, sleep[key])

    hrv = _call(g, "get_hrv_data", day) or {}
    summary = hrv.get("hrvSummary") or {}
    if summary:
        entry["hrv_avg"] = summary.get("lastNightAvg") or entry.get("hrv_avg")
        entry["hrv_status"] = summary.get("status")
        entry["hrv_weekly_avg"] = summary.get("weeklyAvg")
        baseline = summary.get("baseline") or {}
        entry["hrv_baseline_low"] = baseline.get("lowUpper")
        entry["hrv_baseline_high"] = baseline.get("balancedUpper")

    # Stress und Body Battery kommen aus derselben Abfrage
    stress = _call(g, "get_all_day_stress", day) or _call(g, "get_stress_data", day) or {}
    if stress:
        entry["stress_avg"] = stress.get("avgStressLevel")
        entry["stress_max"] = stress.get("maxStressLevel")
        entry["stress_rest_min"] = stress.get("restStressDuration")
        entry["stress_low_min"] = stress.get("lowStressDuration")
        entry["stress_medium_min"] = stress.get("mediumStressDuration")
        entry["stress_high_min"] = stress.get("highStressDuration")
        # Garmin liefert Sekunden; Minuten sind hier die lesbarere Einheit
        for field in ("stress_rest_min", "stress_low_min", "stress_medium_min",
                      "stress_high_min"):
            if entry.get(field) is not None:
                entry[field] = int(entry[field] // 60)
        values = stress.get("stressValuesArray") or stress.get("stressValueDescriptorsDTOList")
        if isinstance(values, list) and values:
            series = _downsample([v for v in values if isinstance(v, (list, tuple))])
            if series:
                entry["stress_series_json"] = json.dumps(series, separators=(",", ":"))

        bb = stress.get("bodyBatteryValuesArray")
        if isinstance(bb, list) and bb:
            # Format je nach Version: [ts, status, level, version] oder [ts, level]
            levels = []
            for row in bb:
                if not isinstance(row, (list, tuple)) or len(row) < 2:
                    continue
                value = row[2] if len(row) > 2 and isinstance(row[2], (int, float)) \
                    else row[1]
                if isinstance(value, (int, float)):
                    levels.append([row[0], value])
            if levels:
                entry["body_battery_series_json"] = json.dumps(
                    _downsample(levels), separators=(",", ":"))
                only = [v for _, v in levels]
                entry["body_battery_min"] = min(only)
                entry["body_battery_max"] = max(only)
                entry["body_battery_wake"] = only[0]

    for source, field in (("bodyBatteryChargedValue", "body_battery_charged"),
                          ("bodyBatteryDrainedValue", "body_battery_drained")):
        if stress.get(source) is not None:
            entry[field] = stress[source]

    hr = _call(g, "get_heart_rates", day) or {}
    if hr:
        entry["hr_min"] = hr.get("minHeartRate")
        entry["hr_max"] = hr.get("maxHeartRate")
        entry.setdefault("resting_hr", hr.get("restingHeartRate"))
    if entry.get("resting_hr") is None:
        rhr = _call(g, "get_rhr_day", day) or {}
        stats = ((rhr.get("allMetrics") or {}).get("metricsMap") or {})
        values = stats.get("WELLNESS_RESTING_HEART_RATE") or []
        if values and isinstance(values[0], dict):
            entry["resting_hr"] = values[0].get("value")

    if entry.get("respiration_avg") is None:
        resp = _call(g, "get_respiration_data", day) or {}
        entry["respiration_avg"] = resp.get("avgSleepRespirationValue") or \
            resp.get("avgWakingRespirationValue")

    tr = _call(g, "get_training_readiness", day)
    if isinstance(tr, list) and tr:
        tr = tr[0]
    if isinstance(tr, dict):
        entry["training_readiness"] = tr.get("score")

    steps = _call(g, "get_daily_steps", day, day)
    if isinstance(steps, list) and steps:
        entry["steps"] = steps[0].get("totalSteps")

    _collect_step_hours(g, day)

    return {k: v for k, v in entry.items() if v is not None}


def _collect_step_hours(g: Garmin, day: str) -> None:
    """Den Tagesverlauf der Schritte stundenweise ablegen.

    Garmin liefert Viertelstunden-Abschnitte mit Zeitstempel. Aufgehoben wird
    nur die Stundensumme: Feiner braucht es niemand, und eine Zeile je
    Viertelstunde waere das Vierfache an Daten fuer dieselbe Aussage.
    """
    raw = _call(g, "get_steps_data", day)
    if not isinstance(raw, list) or not raw:
        return
    per_hour: dict[int, int] = {}
    for chunk in raw:
        if not isinstance(chunk, dict):
            continue
        stamp = (chunk.get("startGMT") or chunk.get("startTimeLocal")
                 or chunk.get("startTimeGMT"))
        count = chunk.get("steps")
        if not stamp or not count:
            continue
        try:
            when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        per_hour[when.hour] = per_hour.get(when.hour, 0) + int(count)
    if per_hour:
        from . import steps as steps_svc
        steps_svc.record_day(day, per_hour)


DAILY_FIELDS = (
    "sleep_seconds", "sleep_score", "sleep_deep_s", "sleep_light_s",
    "sleep_rem_s", "sleep_awake_s", "sleep_start", "sleep_end",
    "respiration_avg", "spo2_avg", "hrv_avg", "hrv_status", "hrv_weekly_avg",
    "hrv_baseline_low", "hrv_baseline_high", "stress_avg", "stress_max",
    "stress_rest_min", "stress_low_min", "stress_medium_min", "stress_high_min",
    "stress_series_json", "body_battery_min", "body_battery_max",
    "body_battery_wake", "body_battery_charged", "body_battery_drained",
    "body_battery_series_json", "hr_min", "hr_max", "hr_avg", "resting_hr",
    "training_readiness", "steps",
)


def sync_daily_metrics(g: Garmin, days: int, offset: int = 0) -> int:
    """Schlaf, HRV, Stress, Body Battery und Puls je Tag."""
    count = 0
    for i in range(offset, offset + days):
        day = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        entry = _collect_day(g, day)
        if len(entry) <= 1:
            continue
        row = {"day": day, **{f: entry.get(f) for f in DAILY_FIELDS}}
        columns = ", ".join(row)
        placeholders = ", ".join(f":{k}" for k in row)
        # COALESCE: ein spaeterer Lauf darf vorhandene Werte nicht mit NULL
        # ueberschreiben, nur ergaenzen.
        updates = ", ".join(
            f"{k}=COALESCE(excluded.{k}, daily_metrics.{k})" for k in row if k != "day")
        with get_db() as db:
            db.execute(f"INSERT INTO daily_metrics({columns}) VALUES({placeholders}) "
                       f"ON CONFLICT(day) DO UPDATE SET {updates}", row)
        count += 1
    return count


def sync_body_composition(g: Garmin, days: int) -> int:
    """Koerperwerte aus Garmin (z. B. von einer Index-Waage oder App-Eintraegen)."""
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    end = dt.date.today().isoformat()
    data = _call(g, "get_body_composition", start, end) or {}
    count = 0
    for entry in data.get("dateWeightList") or []:
        day = entry.get("calendarDate")
        weight = entry.get("weight")
        if not day or not weight:
            continue
        stamp = None
        raw_ts = entry.get("date") or entry.get("timestampGMT")
        if isinstance(raw_ts, (int, float)):
            try:
                stamp = dt.datetime.fromtimestamp(raw_ts / 1000).isoformat(
                    timespec="seconds")
            except (OverflowError, OSError, ValueError):
                stamp = None
        grams = lambda v: round(v / 1000.0, 2) if isinstance(v, (int, float)) else None  # noqa: E731
        body.record({
            "measured_at": stamp,
            "day": day,
            "weight_kg": grams(weight),
            "body_fat_pct": entry.get("bodyFat"),
            "muscle_kg": grams(entry.get("muscleMass")),
            "bone_kg": grams(entry.get("boneMass")),
            "water_pct": entry.get("bodyWater"),
            "visceral_fat": entry.get("visceralFat"),
            "bmi": entry.get("bmi"),
        }, source="garmin")
        count += 1
    return count


def sync_activity_details(g: Garmin, limit: int = 20, force: bool = False,
                          progress: Any = None) -> int:
    """Karten- und Kurvendaten fuer Aktivitaeten holen, die noch keine haben.

    Wird ausgeduennt gespeichert (siehe services/activity_details.py) — rund
    30-80 kB je Lauf statt ein bis drei Megabyte.
    """
    where = "" if force else \
        " AND a.id NOT IN (SELECT activity_id FROM activity_details)"
    with get_db() as db:
        rows = db.execute(
            f"""SELECT a.id, a.garmin_id FROM activities a
                WHERE a.garmin_id IS NOT NULL{where}
                ORDER BY a.start_time DESC LIMIT ?""", (limit,)).fetchall()
    pending = [(r["id"], r["garmin_id"]) for r in rows]

    count = 0
    for activity_id, garmin_id in pending:
        raw = _call(g, "get_activity_details", garmin_id, 2000, 4000)
        if not raw:
            continue
        try:
            packed = details.condense(raw)
        except Exception as e:
            log.warning("Detaildaten von %s nicht verwertbar: %s", garmin_id, e)
            continue
        if not packed["series_json"] and not packed["track_json"]:
            continue
        splits = _call(g, "get_activity_splits", garmin_id)
        with get_db() as db:
            db.execute(
                """INSERT INTO activity_details(activity_id, series_json, track_json,
                                                bounds_json, splits_json, point_count)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(activity_id) DO UPDATE SET
                     fetched_at=datetime('now'),
                     series_json=excluded.series_json,
                     track_json=excluded.track_json,
                     bounds_json=excluded.bounds_json,
                     splits_json=excluded.splits_json,
                     point_count=excluded.point_count""",
                (activity_id, packed["series_json"], packed["track_json"],
                 packed["bounds_json"],
                 json.dumps(splits, separators=(",", ":")) if splits else None,
                 packed["point_count"]))
        count += 1
        if progress and progress(count, f"{count} von {len(pending)}") is False:
            break
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
        n_det = sync_activity_details(g, limit=15)
        detail = (f"{n_act} Aktivitäten, {n_sets} Sätze, {n_runs} Läufe bewertet, "
                  f"{n_days} Tagesmetriken, {n_body} Körperwerte, "
                  f"{n_det} Detailverläufe")
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


# ------------------------------------------------------- Verlaufs-Import

# Zustand des laufenden Imports. Bewusst nur im Speicher: bricht er ab, wird
# er einfach neu gestartet — die bereits geholten Tage bleiben in der Datenbank.
_backfill: dict[str, Any] = {
    "running": False, "cancel": False,
    "phase": "", "phase_no": 0, "phase_count": 4,
    "done": 0, "total": 0, "detail": "",
    "counts": {}, "error": None, "started_at": None, "finished_at": None,
    "beat": None, "summary": "",
}
_backfill_lock = threading.Lock()

# Tagesmetriken kosten je Tag rund sieben Anfragen an Garmin. Ueber zehn Jahre
# waeren das zehntausende — das laeuft stundenlang und wird gedrosselt.
# Aktivitaeten dagegen kommen in Jahresscheiben und sind billig.
MAX_DAILY_BACKFILL_DAYS = 900
ACTIVITY_SLICE_DAYS = 180


# Meldet der Import fuenf Minuten lang keinen Fortschritt, gilt er als tot.
# Ohne das bliebe nach einem gestorbenen Thread "laeuft bereits" fuer immer
# stehen — der Knopf taete dann nichts mehr, ohne zu sagen warum.
STALE_AFTER_S = 300


def _note(text: str, ok: bool = True) -> None:
    """Schritt festhalten — in der Datenbank, damit er einen Neustart ueberlebt."""
    try:
        with get_db() as db:
            db.execute("INSERT INTO sync_log(ok, detail) VALUES(?,?)",
                       (1 if ok else 0, f"Verlauf: {text}"))
    except Exception as e:
        log.debug("Protokolleintrag fehlgeschlagen: %s", e)
    log.info("Verlaufs-Import: %s", text)


def _is_stale() -> bool:
    last = _backfill.get("beat")
    if not last:
        return False
    try:
        age = (dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds()
    except ValueError:
        return False
    return age > STALE_AFTER_S


def backfill_state() -> dict[str, Any]:
    st = dict(_backfill)
    st["percent"] = round(st["done"] / st["total"] * 100) if st["total"] else 0
    st["stale"] = st["running"] and _is_stale()
    if st["stale"]:
        st["error"] = (st.get("error") or
                       "Seit über fünf Minuten kein Fortschritt — der Import "
                       "scheint zu hängen. Mit „Zurücksetzen“ neu startbar.")
    return st


def reset_backfill() -> dict[str, Any]:
    """Festgefahrenen Import freigeben, damit er neu gestartet werden kann."""
    _backfill.update(running=False, cancel=False, phase="Zurückgesetzt")
    _note("zurückgesetzt", ok=False)
    return backfill_state()


def cancel_backfill() -> dict[str, Any]:
    """Laufenden Import abbrechen. Das Geholte bleibt erhalten."""
    if _backfill["running"]:
        _backfill["cancel"] = True
    return backfill_state()


def _phase(no: int, name: str, total: int) -> None:
    _backfill.update(phase_no=no, phase=name, total=max(1, total), done=0,
                     detail="", beat=dt.datetime.now().isoformat(timespec="seconds"))
    _note(f"Schritt {no}/4 — {name} ({total})")


def _tick(done: int, detail: str = "") -> bool:
    """Fortschritt melden. Gibt False zurueck, wenn abgebrochen werden soll."""
    _backfill["done"] = done
    _backfill["beat"] = dt.datetime.now().isoformat(timespec="seconds")
    if detail:
        _backfill["detail"] = detail
    return not _backfill["cancel"]


def _oldest_activity_day() -> str | None:
    with get_db() as db:
        row = db.execute("SELECT MIN(substr(start_time,1,10)) AS d "
                         "FROM activities WHERE start_time IS NOT NULL").fetchone()
    return row["d"] if row and row["d"] else None


def run_backfill(days: int = 3650) -> None:
    """Holt die Historie nach — in vier Phasen, jede mit eigenem Fortschritt.

    Ohne Vergangenheit kann der Coach keine Tendenzen erklaeren. Vorhandene
    Tage werden nur ergaenzt, nie geleert.
    """
    with _backfill_lock:
        if _backfill["running"] and not _is_stale():
            log.info("Verlaufs-Import laeuft bereits.")
            return
        if _backfill["running"]:
            _note("vorheriger Lauf hing fest und wird überschrieben", ok=False)
        _backfill.update(running=True, cancel=False, error=None, summary="",
                         counts={}, finished_at=None,
                         started_at=dt.datetime.now().isoformat(timespec="seconds"))

    counts = {"Aktivitäten": 0, "Tage": 0, "Körperwerte": 0, "Detailverläufe": 0}
    today = dt.date.today()
    try:
        _phase(1, "Verbinde mit Garmin", 1)
        g = get_client()

        # --- 1. Aktivitaeten, rueckwaerts in Scheiben --------------------
        slices = max(1, days // ACTIVITY_SLICE_DAYS)
        _phase(1, "Aktivitäten", slices)
        empty = 0
        for i in range(slices):
            end = today - dt.timedelta(days=i * ACTIVITY_SLICE_DAYS)
            begin = end - dt.timedelta(days=ACTIVITY_SLICE_DAYS)
            got = sync_activities_range(g, begin.isoformat(), end.isoformat())
            counts["Aktivitäten"] += got
            _backfill["counts"] = dict(counts)
            if not _tick(i + 1, f"bis {begin.isoformat()} — {counts['Aktivitäten']} gefunden"):
                raise _Cancelled()
            # Zwei leere Halbjahre hintereinander: davor gibt es nichts mehr.
            empty = empty + 1 if got == 0 else 0
            if empty >= 2 and i >= 2:
                break

        # --- 2. Tagesmetriken bis zur aeltesten Aktivitaet ---------------
        oldest = _oldest_activity_day()
        span = days
        if oldest:
            try:
                span = (today - dt.date.fromisoformat(oldest)).days + 7
            except ValueError:
                pass
        span = max(30, min(span, days, MAX_DAILY_BACKFILL_DAYS))
        _phase(2, "Schlaf, HRV, Stress, Body Battery", span)
        blank = 0
        for offset in range(span):
            got = sync_daily_metrics(g, 1, offset=offset)
            counts["Tage"] += got
            _backfill["counts"] = dict(counts)
            day = (today - dt.timedelta(days=offset)).isoformat()
            if not _tick(offset + 1, f"{day} — {counts['Tage']} Tage geladen"):
                raise _Cancelled()
            # 30 Tage am Stueck ohne jeden Wert: davor hat die Uhr nichts erfasst.
            blank = blank + 1 if got == 0 else 0
            if blank >= 30:
                break

        # --- 3. Koerperwerte ---------------------------------------------
        _phase(3, "Körperwerte", 1)
        counts["Körperwerte"] = sync_body_composition(g, days)
        _backfill["counts"] = dict(counts)
        if not _tick(1):
            raise _Cancelled()

        # --- 4. Karten und Kurven ----------------------------------------
        with get_db() as db:
            pending = db.execute(
                "SELECT COUNT(*) AS n FROM activities a WHERE a.garmin_id IS NOT NULL "
                "AND a.id NOT IN (SELECT activity_id FROM activity_details)"
            ).fetchone()["n"]
        _phase(4, "Karten und Kurven", max(1, pending))
        counts["Detailverläufe"] = sync_activity_details(
            g, limit=pending or 1,
            progress=lambda n, name: (_backfill["counts"].update(
                {"Detailverläufe": n}) or _tick(n, name)))
        _backfill["counts"] = dict(counts)

        summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        _backfill.update(phase="Fertig", summary=summary or "nichts Neues gefunden")
        with get_db() as db:
            db.execute("INSERT INTO sync_log(ok, detail) VALUES(1, ?)",
                       (f"Verlaufs-Import: {summary}",))


        _note(f"fertig — {summary or 'nichts Neues'}")
    except _Cancelled:
        summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        _backfill.update(phase="Abgebrochen",
                         summary=f"Abgebrochen — geladen: {summary or 'nichts'}")
        _note("vom Nutzer abgebrochen", ok=False)
    except Exception as e:
        _backfill.update(phase="Abgebrochen", error=f"{type(e).__name__}: {e}")
        _note(f"abgebrochen mit Fehler — {type(e).__name__}: {e}", ok=False)
        log.warning("Verlaufs-Import fehlgeschlagen: %s", e, exc_info=True)
    finally:
        _backfill.update(running=False, cancel=False,
                         finished_at=dt.datetime.now().isoformat(timespec="seconds"))


class _Cancelled(Exception):
    """Der Nutzer hat den Import abgebrochen."""


def start_backfill(days: int = 3650) -> dict[str, Any]:
    """Import im Hintergrund anstossen, damit die Anfrage nicht wartet."""
    if _backfill["running"] and not _is_stale():
        return {"status": "läuft bereits", **backfill_state()}
    threading.Thread(target=run_backfill, args=(days,), daemon=True).start()
    return {"status": "gestartet", "days": days}


def diagnose() -> dict[str, Any]:
    """Sagt, woran es liegt, wenn keine Daten ankommen.

    Prueft der Reihe nach: Verbindung, ob Garmin ueberhaupt antwortet, was
    davon in der Datenbank gelandet ist, und was die letzten Laeufe gemeldet
    haben. Damit laesst sich in einem Blick unterscheiden, ob die Verbindung,
    die Abfrage oder das Speichern klemmt.
    """
    out: dict[str, Any] = {"steps": [], "counts": {}, "log": []}

    def step(name: str, ok: bool | None, detail: str = "") -> None:
        out["steps"].append({"name": name, "ok": ok, "detail": detail})

    # 1. Verknuepfung
    linked = get_setting("garmin_linked", "0") == "1"
    step("Garmin verknüpft", linked,
         get_setting("garmin_email", "") if linked
         else "Unter Mehr → Garmin Connect verbinden.")

    # 2. Antwortet Garmin?
    client = None
    if linked:
        try:
            client = get_client()
            step("Verbindung steht", True)
        except Exception as e:
            step("Verbindung steht", False, f"{type(e).__name__}: {e}")

    # 3. Liefert Garmin Aktivitaeten?
    if client:
        try:
            end = dt.date.today()
            begin = end - dt.timedelta(days=30)
            acts = client.get_activities_by_date(begin.isoformat(), end.isoformat()) or []
            step("Aktivitäten der letzten 30 Tage", len(acts) > 0,
                 f"{len(acts)} von Garmin geliefert")
            if acts:
                first = acts[0]
                out["sample"] = {
                    "name": first.get("activityName"),
                    "typ": (first.get("activityType") or {}).get("typeKey"),
                    "start": first.get("startTimeLocal"),
                }
        except Exception as e:
            step("Aktivitäten der letzten 30 Tage", False, f"{type(e).__name__}: {e}")

        # 4. Liefert Garmin Tagesdaten?
        try:
            day = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            entry = _collect_day(client, day)
            got = sorted(k for k in entry if k != "day")
            step("Erholungsdaten von gestern", len(got) > 0,
                 ", ".join(got[:8]) if got else "Garmin liefert für gestern nichts")
        except Exception as e:
            step("Erholungsdaten von gestern", False, f"{type(e).__name__}: {e}")

    # 5. Was liegt in der Datenbank?
    with get_db() as db:
        for label, sql in (
            ("Aktivitäten", "SELECT COUNT(*) AS n FROM activities"),
            ("davon mit Karte/Kurven", "SELECT COUNT(*) AS n FROM activity_details"),
            ("Kraftsätze", "SELECT COUNT(*) AS n FROM exercise_sets"),
            ("Tage mit Erholungsdaten", "SELECT COUNT(*) AS n FROM daily_metrics"),
            ("Tage mit Stresswerten",
             "SELECT COUNT(*) AS n FROM daily_metrics WHERE stress_avg IS NOT NULL"),
            ("Tage mit Body Battery",
             "SELECT COUNT(*) AS n FROM daily_metrics WHERE body_battery_max IS NOT NULL"),
            ("Körpermessungen", "SELECT COUNT(*) AS n FROM body_metrics"),
        ):
            try:
                out["counts"][label] = db.execute(sql).fetchone()["n"]
            except Exception as e:
                out["counts"][label] = f"Fehler: {e}"
        span = db.execute(
            "SELECT MIN(substr(start_time,1,10)) AS von, "
            "MAX(substr(start_time,1,10)) AS bis FROM activities").fetchone()
        out["range"] = {"von": span["von"], "bis": span["bis"]} if span else {}
        out["log"] = rows_to_dicts(db.execute(
            "SELECT ts, ok, detail FROM sync_log ORDER BY id DESC LIMIT 20").fetchall())

    step("Daten in der Datenbank", out["counts"].get("Aktivitäten", 0) > 0,
         f"{out['counts'].get('Aktivitäten', 0)} Aktivitäten"
         + (f", {out['range'].get('von')} bis {out['range'].get('bis')}"
            if out["range"].get("von") else ""))

    out["backfill"] = backfill_state()
    return out
