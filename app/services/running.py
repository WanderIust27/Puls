"""Laufmodul: Benchmark-Kalibrierung, Trainingstempi, Laufeinheiten.

Kalibriert wird über den Cooper-Test (12 Minuten maximale Distanz) — einfach auf
der Uhr umzusetzen und robust:

    VO2max ≈ (Distanz_m − 504.9) / 44.73                       (Cooper 1968)

Tempi und Renn-Prognose laufen danach über das Modell von Jack Daniels, weil
eine reine Hochrechnung (Riegel) von 12 Minuten auf 10 km viel zu optimistisch
ausfällt — das ist mehr als das Vierfache der Testdauer.

    Sauerstoffbedarf:  VO2(v) = −4.60 + 0.182258·v + 0.000104·v²   (v in m/min)
    Haltbarer Anteil:  %VO2max(t) = 0.8 + 0.1894393·e^(−0.012778·t)
                                        + 0.2989558·e^(−0.1932605·t)

Die Rennzeit ergibt sich, wenn Angebot und Nachfrage zusammenpassen: Man sucht
die Geschwindigkeit, bei der der Sauerstoffbedarf genau dem entspricht, was über
die Renndauer haltbar ist. Das löst die Funktion iterativ.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, set_setting

log = logging.getLogger("puls.running")

# Anteil der VO2max je Trainingsart (nach Daniels' Trainingszonen)
INTENSITY = {
    "easy": 0.68,       # lockere Dauerläufe — der Großteil der Wochenkilometer
    "long": 0.66,       # noch etwas ruhiger, dafür länger
    "tempo": 0.88,      # Schwellentempo, "angenehm hart"
    "interval": 0.98,   # 3–5-Minuten-Intervalle
}


def vo2_at_speed(v_m_per_min: float) -> float:
    """Sauerstoffbedarf bei einer Laufgeschwindigkeit (Daniels)."""
    return -4.60 + 0.182258 * v_m_per_min + 0.000104 * v_m_per_min ** 2


def speed_at_vo2(vo2: float) -> float:
    """Umkehrung: Geschwindigkeit (m/min) für einen Sauerstoffbedarf."""
    a, b, c = 0.000104, 0.182258, -(vo2 + 4.60)
    disc = b * b - 4 * a * c
    if disc <= 0:
        return 0.0
    return (-b + disc ** 0.5) / (2 * a)


def sustainable_fraction(minutes: float) -> float:
    """Welcher Anteil der VO2max lässt sich über diese Dauer halten? (Daniels)"""
    import math
    return (0.8 + 0.1894393 * math.exp(-0.012778 * minutes)
            + 0.2989558 * math.exp(-0.1932605 * minutes))


def predict_race_time(vo2max: float, distance_m: float) -> float:
    """Rennzeit in Sekunden — iterativ, bis Bedarf und Haltbarkeit passen."""
    minutes = distance_m / 200.0        # grober Startwert (~5:00/km)
    for _ in range(50):
        usable = vo2max * sustainable_fraction(minutes)
        v = speed_at_vo2(usable)
        if v <= 0:
            return 0.0
        new_minutes = distance_m / v
        if abs(new_minutes - minutes) < 0.01:
            minutes = new_minutes
            break
        minutes = (minutes + new_minutes) / 2   # gedämpft, damit es sicher konvergiert
    return minutes * 60.0


def _fmt_time(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d} min"


def mps_to_pace_s(mps: float) -> int:
    """m/s -> Sekunden pro Kilometer."""
    return int(round(1000.0 / mps)) if mps > 0 else 0


def pace_s_to_str(sec_per_km: float | int | None) -> str:
    if not sec_per_km:
        return "–"
    s = int(round(sec_per_km))
    return f"{s // 60}:{s % 60:02d}"


def pace_str_to_s(text: str) -> int | None:
    try:
        parts = str(text).replace(",", ":").split(":")
        return int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return None


def riegel_predict(known_distance_m: float, known_time_s: float,
                   target_distance_m: float) -> float:
    """Rennzeit-Prognose auf eine andere Distanz (Riegel-Exponent 1.06)."""
    return known_time_s * (target_distance_m / known_distance_m) ** 1.06


def calibrate_from_cooper(distance_m: float) -> dict[str, Any]:
    """Cooper-Distanz auswerten: Tempi berechnen, speichern, Prognose stellen."""
    vo2max = max(20.0, (distance_m - 504.9) / 44.73)

    # Trainingstempi: Geschwindigkeit beim jeweiligen Anteil der VO2max
    paces = {k: mps_to_pace_s(speed_at_vo2(vo2max * f) / 60.0)
             for k, f in INTENSITY.items()}

    pred_10k_s = predict_race_time(vo2max, 10000.0)

    set_setting("cooper_distance_m", str(int(distance_m)))
    set_setting("easy_pace_s_per_km", str(paces["easy"]))
    set_setting("tempo_pace_s_per_km", str(paces["tempo"]))
    set_setting("interval_pace_s_per_km", str(paces["interval"]))
    set_setting("last_run_benchmark", dt.date.today().isoformat())

    goal_km = float(get_setting("run_goal_distance_km", "10") or 10)
    goal_min = float(get_setting("run_goal_time_min", "60") or 60)
    goal_pace = int(goal_min * 60 / goal_km) if goal_km else 360
    pred_goal_s = predict_race_time(vo2max, goal_km * 1000)
    gap_s = pred_goal_s - goal_min * 60

    if gap_s <= 0:
        verdict = (f"Rechnerisch schaffst du die {goal_km:g} km schon unter "
                   f"{goal_min:g} Minuten — jetzt geht es ums Umsetzen im Rennen.")
    elif gap_s <= 180:
        verdict = (f"Du bist rund {gap_s / 60:.0f} Minuten weg — das ist mit ein paar "
                   "Wochen konsequentem Training gut zu holen.")
    elif gap_s <= 600:
        verdict = (f"Noch etwa {gap_s / 60:.0f} Minuten Rückstand. Realistisch in "
                   "zwei bis drei Monaten, wenn die lockeren Läufe wirklich locker "
                   "bleiben und ein Temporeiz pro Woche dazukommt.")
    else:
        verdict = (f"Aktuell noch rund {gap_s / 60:.0f} Minuten entfernt. Das wird ein "
                   "Projekt über mehrere Monate — Grundlage aufbauen kommt zuerst.")

    return {
        "distance_m": int(distance_m),
        "vo2max": round(vo2max, 1),
        "paces": {k: {"s_per_km": v, "text": pace_s_to_str(v)} for k, v in paces.items()},
        "predicted_10k_s": int(pred_10k_s),
        "predicted_10k_text": _fmt_time(pred_10k_s),
        "goal": {
            "distance_km": goal_km,
            "time_min": goal_min,
            "required_pace": pace_s_to_str(goal_pace),
            "predicted_now_s": int(pred_goal_s),
            "predicted_now_text": _fmt_time(pred_goal_s),
            "gap_s": int(gap_s),
            "reached": gap_s <= 0,
            "verdict": verdict,
        },
    }


def current_paces() -> dict[str, int] | None:
    """Gespeicherte Trainingstempi (Sekunden/km) oder None ohne Kalibrierung."""
    easy = get_setting("easy_pace_s_per_km", "")
    if not easy:
        return None
    return {
        "easy": int(easy),
        "long": int(float(easy) * 1.02),
        "tempo": int(get_setting("tempo_pace_s_per_km", easy) or easy),
        "interval": int(get_setting("interval_pace_s_per_km", easy) or easy),
    }


def goal_pace_s() -> int:
    goal_km = float(get_setting("run_goal_distance_km", "10") or 10)
    goal_min = float(get_setting("run_goal_time_min", "60") or 60)
    return int(goal_min * 60 / goal_km) if goal_km else 360


def _pace_window(sec_per_km: int, tolerance: int = 12) -> list[str]:
    """Garmin will eine Tempo-Spanne — langsamere Grenze zuerst."""
    return [pace_s_to_str(sec_per_km + tolerance), pace_s_to_str(sec_per_km - tolerance)]


# ------------------------------------------------------------ Laufeinheiten

def build_easy_run(minutes: int = 25, kind: str = "easy") -> dict[str, Any]:
    """Lockerer Dauerlauf — das tägliche Brot-und-Butter-Training."""
    paces = current_paces()
    steps: list[dict[str, Any]] = [
        {"type": "warmup", "name": "Locker einlaufen", "duration_s": 300,
         "notes": "Ruhig starten, Atmung soll leicht bleiben"},
    ]
    main: dict[str, Any] = {
        "type": "work", "name": "Lockerer Dauerlauf",
        "duration_s": max(300, (minutes - 8) * 60),
        "notes": "Unterhaltungstempo — du solltest sprechen können",
    }
    if paces:
        main["pace_min_km"] = _pace_window(paces[kind], 15)
    else:
        main["hr_zone"] = 2
    steps.append(main)
    steps.append({"type": "cooldown", "name": "Austraben", "duration_s": 180})
    return {
        "name": f"Lockerer Lauf {minutes} min", "sport": "running",
        "description": ("Ruhige Grundlage. Der Großteil deiner Laufkilometer soll sich "
                        "leicht anfühlen — genau das baut die Ausdauer für die 10 km."),
        "steps": steps,
    }


def build_tempo_run(minutes: int = 30) -> dict[str, Any]:
    """Schwellenlauf: der Reiz, der das Renntempo schneller macht."""
    paces = current_paces()
    block_s = max(480, min(1200, (minutes - 15) * 60))
    work: dict[str, Any] = {"type": "work", "name": "Tempoblock", "duration_s": block_s,
                            "notes": "Angenehm hart — reden ginge nur in kurzen Sätzen"}
    if paces:
        work["pace_min_km"] = _pace_window(paces["tempo"], 8)
    else:
        work["hr_zone"] = 4
    return {
        "name": f"Tempolauf {minutes} min", "sport": "running",
        "description": "Ein Schwellenblock pro Woche hebt dein Renntempo spürbar an.",
        "steps": [
            {"type": "warmup", "name": "Einlaufen", "duration_s": 600},
            work,
            {"type": "cooldown", "name": "Auslaufen", "duration_s": 300},
        ],
    }


def build_interval_run(minutes: int = 35) -> dict[str, Any]:
    """Intervalle: kurzer, harter Reiz für die Sauerstoffaufnahme."""
    paces = current_paces()
    reps = 5 if minutes >= 35 else 4
    work: dict[str, Any] = {"type": "work", "name": "Intervall", "distance_m": 800,
                            "notes": "Zügig, aber kontrolliert bis zum Schluss"}
    if paces:
        work["pace_min_km"] = _pace_window(paces["interval"], 10)
    else:
        work["hr_zone"] = 5
    return {
        "name": f"Intervalle {reps}×800 m", "sport": "running",
        "description": ("Kurze harte Abschnitte mit vollen Trabpausen — der stärkste "
                        "Reiz für deine Ausdauer, aber höchstens einmal pro Woche."),
        "steps": [
            {"type": "warmup", "name": "Einlaufen", "duration_s": 600},
            {"type": "repeat", "count": reps, "steps": [
                work,
                {"type": "recovery", "name": "Trabpause", "duration_s": 180,
                 "notes": "Locker traben oder gehen"},
            ]},
            {"type": "cooldown", "name": "Auslaufen", "duration_s": 300},
        ],
    }


def build_long_run(minutes: int = 50) -> dict[str, Any]:
    paces = current_paces()
    main: dict[str, Any] = {"type": "work", "name": "Langer Lauf",
                            "duration_s": max(1200, (minutes - 8) * 60),
                            "notes": "Gleichmäßig und ruhig — Zeit auf den Beinen zählt"}
    if paces:
        main["pace_min_km"] = _pace_window(paces["long"], 20)
    else:
        main["hr_zone"] = 2
    return {
        "name": f"Langer Lauf {minutes} min", "sport": "running",
        "description": "Die längste Einheit der Woche — Grundlage für die 10 km.",
        "steps": [
            {"type": "warmup", "name": "Einlaufen", "duration_s": 300},
            main,
            {"type": "cooldown", "name": "Austraben", "duration_s": 180},
        ],
    }


def build_goal_pace_run(minutes: int = 35) -> dict[str, Any]:
    """Zieltempo üben: das Gefühl für 6:00/km bekommen."""
    gp = goal_pace_s()
    return {
        "name": "Zieltempo-Lauf", "sport": "running",
        "description": (f"Blöcke im Zieltempo ({pace_s_to_str(gp)}/km). So lernst du, "
                        "wie sich dein 10-km-Tempo anfühlt."),
        "steps": [
            {"type": "warmup", "name": "Einlaufen", "duration_s": 600},
            {"type": "repeat", "count": 3, "steps": [
                {"type": "work", "name": "Im Zieltempo", "duration_s": 360,
                 "pace_min_km": _pace_window(gp, 8)},
                {"type": "recovery", "name": "Trabpause", "duration_s": 120},
            ]},
            {"type": "cooldown", "name": "Auslaufen", "duration_s": 300},
        ],
    }


def build_cooper_test() -> dict[str, Any]:
    """Benchmark-Lauf: 12 Minuten so weit wie möglich."""
    return {
        "name": "Benchmark: Cooper-Test", "sport": "running",
        "description": ("12 Minuten so weit wie möglich laufen. Gleichmäßig einteilen, "
                        "nicht zu schnell starten — die letzten 3 Minuten dürfen "
                        "brennen. Aus der Distanz berechnet PULS deine Trainingstempi."),
        "steps": [
            {"type": "warmup", "name": "Locker einlaufen", "duration_s": 600,
             "notes": "Gut warm werden, sonst verfälscht der Test"},
            {"type": "work", "name": "12 Minuten alles geben", "duration_s": 720,
             "notes": "Gleichmäßiges Tempo, das du 12 min halten kannst"},
            {"type": "cooldown", "name": "Auslaufen", "duration_s": 600},
        ],
    }


def find_cooper_lap(activity_id: int) -> dict[str, Any] | None:
    """Sucht in einer Garmin-Aktivität die Runde, die dem 12-Minuten-Block entspricht.

    Das Benchmark-Workout hat drei Schritte, also legt die Uhr drei Runden an.
    Wir nehmen die Runde, deren Dauer am nächsten an 720 s liegt (Toleranz 90 s).
    """
    from . import garmin_sync
    with get_db() as db:
        row = db.execute("SELECT garmin_id FROM activities WHERE id=?",
                         (activity_id,)).fetchone()
    if not row or not row["garmin_id"]:
        return None
    try:
        g = garmin_sync.get_client()
        data = g.get_activity_splits(row["garmin_id"]) or {}
    except Exception as e:
        log.debug("Runden für %s nicht abrufbar: %s", activity_id, e)
        return None
    laps = data.get("lapDTOs") or data.get("splits") or []
    best, best_delta = None, 1e9
    for lap in laps:
        dur = lap.get("duration") or lap.get("elapsedDuration")
        dist = lap.get("distance")
        if not dur or not dist:
            continue
        delta = abs(float(dur) - 720.0)
        if delta < best_delta:
            best, best_delta = {"duration_s": float(dur), "distance_m": float(dist)}, delta
    if best and best_delta <= 90:
        # auf exakt 12 Minuten hochrechnen, falls die Runde leicht abweicht
        best["distance_m"] = best["distance_m"] * 720.0 / best["duration_s"]
        return best
    return None


def evaluate_cooper_from_activity(activity_id: int) -> dict[str, Any] | None:
    """Benchmark-Lauf auswerten: bevorzugt über die 12-Minuten-Runde der Uhr."""
    lap = find_cooper_lap(activity_id)
    if lap:
        return calibrate_from_cooper(lap["distance_m"])
    return None
