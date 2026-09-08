"""Manueller FIT-Import: Aktivität aus einer FIT-Datei in die Datenbank."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from garmin_fit_sdk import Decoder, Stream

from ..db import get_db

SPORT_MAP = {
    "running": "running",
    "training": "strength",
    "strength_training": "strength",
    "fitness_equipment": "strength",
    "cycling": "cardio",
    "walking": "cardio",
    "hiking": "cardio",
    "yoga": "mobility",
    "cardio": "cardio",
}


def import_fit(content: bytes, filename: str = "upload.fit") -> dict[str, Any]:
    stream = Stream.from_byte_array(bytearray(content))
    decoder = Decoder(stream)
    messages, errors = decoder.read(convert_datetimes_to_dates=True)
    if errors:
        raise ValueError(f"FIT-Datei konnte nicht gelesen werden: {errors[:2]}")

    sessions = messages.get("session_mesgs") or []
    if not sessions:
        raise ValueError("Keine Session in der FIT-Datei gefunden.")
    s = sessions[0]

    sport = str(s.get("sport") or "").lower()
    sub = str(s.get("sub_sport") or "").lower()
    mapped = SPORT_MAP.get(sub) or SPORT_MAP.get(sport) or "other"

    start = s.get("start_time")
    if isinstance(start, dt.datetime):
        start_iso = start.isoformat()
    else:
        start_iso = dt.datetime.now().isoformat(timespec="seconds")

    def num(key: str) -> float | None:
        v = s.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    row = {
        "source": "fit",
        "name": filename.rsplit(".", 1)[0],
        "sport": mapped,
        "start_time": start_iso,
        "duration_s": int(num("total_timer_time") or num("total_elapsed_time") or 0),
        "distance_m": num("total_distance"),
        "calories": num("total_calories"),
        "avg_hr": num("avg_heart_rate"),
        "max_hr": num("max_heart_rate"),
        "training_load": num("training_load_peak"),
    }
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO activities
               (source, name, sport, start_time, duration_s, distance_m, calories,
                avg_hr, max_hr, training_load, raw_json)
               VALUES(:source,:name,:sport,:start_time,:duration_s,:distance_m,
                      :calories,:avg_hr,:max_hr,:training_load,:raw)""",
            {**row, "raw": json.dumps({k: str(v) for k, v in s.items()})},
        )
        row["id"] = cur.lastrowid
    return row
