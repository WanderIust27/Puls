"""Koerperdaten: Referenzfenster, Tagesgang-Korrektur, Verlauf.

Gewicht ist eine unruhige Groesse. Zwischen der Messung um 6:40 nuechtern und
der um 21 Uhr nach dem Abendessen liegen leicht anderthalb Kilo — ohne dass
sich am Koerper irgendetwas geaendert haette. Wer Messungen zu verschiedenen
Uhrzeiten in dieselbe Kurve wirft, sieht vor allem seinen Tagesablauf.

Deshalb arbeitet PULS mit einem Referenzfenster (Standard 6-9 Uhr). Messungen
darin bilden die Trendlinie. Messungen ausserhalb gehen nicht verloren: sie
werden markiert und ueber ein Tagesgang-Modell auf das Fenster umgerechnet.

Das Modell startet mit Erfahrungswerten und lernt aus den eigenen Daten dazu,
sobald genug Tage mit zwei Messungen vorliegen — siehe personal_factor().
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.body")

# Tagesgang des Koerpergewichts als Abweichung in Prozent des Koerpergewichts,
# bezogen auf den nuechternen Morgenwert. Stuetzstellen (Stunde, Prozent) —
# dazwischen wird linear interpoliert, ueber Mitternacht hinweg zyklisch.
# Groessenordnung: rund 1,5 % ueber den Tag, das sind bei 80 kg gut 1,2 kg.
_DIURNAL: list[tuple[float, float]] = [
    (0.0, 1.30), (3.0, 0.75), (6.0, 0.00), (7.5, 0.05), (9.0, 0.25),
    (12.0, 0.90), (15.0, 1.20), (18.0, 1.50), (21.0, 1.70), (23.0, 1.60),
]

MIN_PAIRS_FOR_CALIBRATION = 5


def _hours(ts: dt.datetime) -> float:
    return ts.hour + ts.minute / 60.0


def _parse(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def _time_setting(key: str, fallback: str) -> float:
    raw = (get_setting(key, fallback) or fallback).strip()
    try:
        h, m = raw.split(":")[:2]
        return int(h) + int(m) / 60.0
    except (ValueError, IndexError):
        log.warning("Ungueltige Uhrzeit in %s: %r — nutze %s", key, raw, fallback)
        h, m = fallback.split(":")
        return int(h) + int(m) / 60.0


def window() -> tuple[float, float]:
    """Referenzfenster als Stunden-Paar, z. B. (6.0, 9.0)."""
    return _time_setting("weigh_window_start", "06:00"), \
        _time_setting("weigh_window_end", "09:00")


def window_label() -> str:
    start, end = window()
    fmt = lambda h: f"{int(h):02d}:{int(round((h % 1) * 60)):02d}"  # noqa: E731
    return f"{fmt(start)}–{fmt(end)}"


def _within(stamp: dt.datetime, bounds: tuple[float, float]) -> bool:
    """Reine Rechnung ohne Datenbankzugriff — auch innerhalb get_db() nutzbar."""
    start, end = bounds
    h = _hours(stamp)
    return start <= h <= end if start <= end else (h >= start or h <= end)


def in_window(ts: dt.datetime | str | None, time_known: bool = True) -> bool:
    """Faellt der Messzeitpunkt ins Referenzfenster?

    Messungen ohne bekannte Uhrzeit zaehlen nie dazu — eine Uhrzeit zu raten
    waere schlimmer als die Luecke.
    """
    if not time_known:
        return False
    stamp = _parse(ts) if isinstance(ts, str) else ts
    if stamp is None:
        return False
    return _within(stamp, window())


def _diurnal_pct(hour: float) -> float:
    """Erwartete Abweichung vom Morgenwert in Prozent, interpoliert."""
    hour %= 24.0
    points = _DIURNAL + [(_DIURNAL[0][0] + 24.0, _DIURNAL[0][1])]
    for (h1, p1), (h2, p2) in zip(points, points[1:]):
        if h1 <= hour <= h2:
            span = h2 - h1
            if span <= 0:
                return p1
            return p1 + (p2 - p1) * (hour - h1) / span
    return points[-1][1]


def personal_factor() -> float:
    """Wie stark schwankt *dieser* Koerper im Vergleich zum Standardmodell?

    Ausgewertet werden Tage mit mindestens einer Messung im Fenster und einer
    ausserhalb: das Modell sagt eine Differenz voraus, die Waage zeigt die
    tatsaechliche. Der Median der Verhaeltnisse ist der Korrekturfaktor.
    Unter MIN_PAIRS_FOR_CALIBRATION Paaren bleibt es beim Standardmodell.
    """
    start, end = window()
    mid = (start + end) / 2 if start <= end else start
    with get_db() as db:
        rows = db.execute(
            "SELECT day, measured_at, weight_kg, time_known FROM body_metrics "
            "WHERE weight_kg IS NOT NULL AND time_known=1 "
            "ORDER BY measured_at DESC LIMIT 400").fetchall()

    by_day: dict[str, list[tuple[dt.datetime, float]]] = {}
    for r in rows:
        stamp = _parse(r["measured_at"])
        if stamp:
            by_day.setdefault(r["day"], []).append((stamp, r["weight_kg"]))

    ratios: list[float] = []
    for entries in by_day.values():
        refs = [(t, w) for t, w in entries if in_window(t)]
        others = [(t, w) for t, w in entries if not in_window(t)]
        if not refs or not others:
            continue
        ref_w = sum(w for _, w in refs) / len(refs)
        for t, w in others:
            predicted = (_diurnal_pct(_hours(t)) - _diurnal_pct(mid)) / 100 * ref_w
            if abs(predicted) < 0.15:      # zu klein, um daraus etwas zu lernen
                continue
            ratios.append((w - ref_w) / predicted)

    if len(ratios) < MIN_PAIRS_FOR_CALIBRATION:
        return 1.0
    ratios.sort()
    median = ratios[len(ratios) // 2]
    return max(0.3, min(2.5, median))


def adjust(weight_kg: float | None, ts: dt.datetime | str | None,
           time_known: bool = True, factor: float | None = None,
           bounds: tuple[float, float] | None = None) -> float | None:
    """Rechnet eine Messung auf das Referenzfenster um.

    Ohne bekannte Uhrzeit wird nicht korrigiert — der Wert bleibt, wie er ist.

    factor und bounds lassen sich uebergeben, damit Schleifen sie einmal
    bestimmen koennen statt bei jedem Wert erneut die Datenbank zu befragen
    (siehe Warnung bei get_db(): verschachtelte Zugriffe blockieren).
    """
    if weight_kg is None:
        return None
    if not time_known:
        return weight_kg
    stamp = _parse(ts) if isinstance(ts, str) else ts
    if stamp is None:
        return weight_kg
    start, end = bounds if bounds is not None else window()
    mid = (start + end) / 2 if start <= end else start
    if factor is None:
        factor = personal_factor()
    delta_pct = (_diurnal_pct(_hours(stamp)) - _diurnal_pct(mid)) * factor
    return round(weight_kg - delta_pct / 100 * weight_kg, 2)


# --------------------------------------------------------------- Schreiben

_FIELDS = ("weight_kg", "body_fat_pct", "muscle_kg", "water_pct", "bone_kg",
           "lbm_kg", "bmi", "visceral_fat", "impedance", "note")


def record(data: dict[str, Any], source: str = "manual") -> dict[str, Any]:
    """Eine Messung speichern. Mehrere pro Tag sind ausdruecklich erlaubt."""
    raw_stamp = data.get("measured_at")
    stamp = _parse(raw_stamp) if raw_stamp else None
    time_known = stamp is not None
    if stamp is None:
        day = data.get("day") or dt.date.today().isoformat()
        # Ohne Uhrzeit auf die Tagesmitte datieren, damit die Sortierung stimmt.
        # time_known=0 haelt fest, dass die Uhrzeit nicht echt ist.
        stamp = dt.datetime.fromisoformat(f"{day}T12:00:00")

    values = {f: data.get(f) for f in _FIELDS}
    if values["bmi"] is None and values["weight_kg"]:
        try:
            height_m = float(get_setting("body_height_cm", "0") or 0) / 100
            if height_m > 0:
                values["bmi"] = round(values["weight_kg"] / height_m ** 2, 1)
        except (TypeError, ValueError):
            pass

    row = {
        **values,
        "day": stamp.date().isoformat(),
        "measured_at": stamp.isoformat(timespec="seconds"),
        "time_known": 1 if time_known else 0,
        "in_window": 1 if in_window(stamp, time_known) else 0,
        "weight_adj_kg": adjust(values["weight_kg"], stamp, time_known),
        "source": source,
    }
    columns = ", ".join(row)
    placeholders = ", ".join(f":{k}" for k in row)
    updates = ", ".join(f"{k}=excluded.{k}" for k in row
                        if k not in ("source", "measured_at"))
    with get_db() as db:
        db.execute(f"INSERT INTO body_metrics({columns}) VALUES({placeholders}) "
                   f"ON CONFLICT(source, measured_at) DO UPDATE SET {updates}", row)
    return row


def delete(measurement_id: int) -> bool:
    with get_db() as db:
        cur = db.execute("DELETE FROM body_metrics WHERE id=?", (measurement_id,))
        return cur.rowcount > 0


def recompute() -> int:
    """Fenster-Zugehoerigkeit und Korrektur neu berechnen.

    Noetig, wenn sich das Referenzfenster aendert oder genug neue Messpaare
    fuer eine bessere Kalibrierung zusammengekommen sind.
    """
    # Fenster und Faktor VOR dem Oeffnen der Verbindung bestimmen: get_db()
    # sperrt nicht-reentrant, ein get_setting() mittendrin blockiert fuer immer.
    factor = personal_factor()
    bounds = window()
    with get_db() as db:
        rows = db.execute("SELECT id, measured_at, weight_kg, time_known "
                          "FROM body_metrics").fetchall()
        updates = []
        for r in rows:
            known = bool(r["time_known"])
            stamp = _parse(r["measured_at"])
            inside = known and stamp is not None and _within(stamp, bounds)
            updates.append((1 if inside else 0,
                            adjust(r["weight_kg"], r["measured_at"], known,
                                   factor, bounds),
                            r["id"]))
        db.executemany(
            "UPDATE body_metrics SET in_window=?, weight_adj_kg=? WHERE id=?", updates)
    return len(rows)


# ----------------------------------------------------------------- Lesen

def measurements(days: int = 180, limit: int = 500) -> list[dict[str, Any]]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM body_metrics WHERE day >= ? "
            "ORDER BY measured_at DESC LIMIT ?", (since, limit)).fetchall()
    return rows_to_dicts(rows)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def trend(days: int = 180) -> list[dict[str, Any]]:
    """Ein Punkt je Tag: der Referenzwert, plus geglaettete Linie."""
    rows = measurements(days)
    per_day: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("weight_adj_kg") is not None:
            per_day.setdefault(r["day"], []).append(r)

    points: list[dict[str, Any]] = []
    for day in sorted(per_day):
        entries = per_day[day]
        refs = [e["weight_kg"] for e in entries if e["in_window"] and e["weight_kg"]]
        value = _median(refs) if refs else _median(
            [e["weight_adj_kg"] for e in entries if e["weight_adj_kg"]])
        points.append({
            "day": day,
            "weight_kg": round(value, 2) if value is not None else None,
            "measured": bool(refs),          # echt im Fenster gemessen
            "count": len(entries),
        })

    # 7-Tage-Median als ruhige Linie ueber den Tageswerten
    values = [p["weight_kg"] for p in points]
    for i, p in enumerate(points):
        chunk = [v for v in values[max(0, i - 6):i + 1] if v is not None]
        p["smooth_kg"] = round(_median(chunk), 2) if chunk else None
    return points


def discipline(days: int = 30) -> dict[str, Any]:
    """Wie konsequent wird zur gleichen Zeit gemessen?"""
    rows = [r for r in measurements(days) if r["time_known"] and r["weight_kg"]]
    if not rows:
        return {"total": 0, "in_window": 0, "share": None, "hint": None,
                "window": window_label()}
    inside = sum(1 for r in rows if r["in_window"])
    share = inside / len(rows)
    hours = [_hours(_parse(r["measured_at"])) for r in rows
             if _parse(r["measured_at"])]
    typical = _median(hours)
    hint = None
    if share < 0.5:
        hint = (f"Nur {inside} von {len(rows)} Messungen lagen im Fenster "
                f"{window_label()}. Der Trend beruht dann grosstenteils auf "
                f"umgerechneten Werten — miss moeglichst direkt nach dem Aufstehen.")
    elif share < 0.8:
        hint = (f"{inside} von {len(rows)} Messungen im Fenster. Solide, "
                f"aber ein paar Ausreisser verwaessern den Trend.")
    return {
        "total": len(rows), "in_window": inside, "share": round(share, 2),
        "typical_hour": round(typical, 1) if typical is not None else None,
        "window": window_label(), "hint": hint,
        "factor": round(personal_factor(), 2),
    }


def latest(fields: tuple[str, ...] = _FIELDS) -> dict[str, Any] | None:
    """Juengste Messung, in der die einzelnen Werte tatsaechlich stehen.

    Koerperwerte kommen nur bei barfuessigem Kontakt — die letzte Messung hat
    oft nur das Gewicht. Deshalb wird jeder Wert einzeln gesucht.
    """
    rows = measurements(90)
    if not rows:
        return None
    out: dict[str, Any] = {"measured_at": rows[0]["measured_at"],
                           "day": rows[0]["day"]}
    for field in fields:
        for r in rows:
            if r.get(field) is not None:
                out[field] = r[field]
                out.setdefault(f"{field}_at", r["measured_at"])
                break
    return out


def summary(days: int = 180) -> dict[str, Any]:
    """Alles, was Dashboard und Coach ueber den Koerper wissen muessen."""
    points = trend(days)
    smooth = [p for p in points if p["smooth_kg"] is not None]
    current = smooth[-1]["smooth_kg"] if smooth else None

    def _delta(back_days: int) -> float | None:
        if not smooth or current is None:
            return None
        target = (dt.date.today() - dt.timedelta(days=back_days)).isoformat()
        earlier = [p for p in smooth if p["day"] <= target]
        return round(current - earlier[-1]["smooth_kg"], 2) if earlier else None

    return {
        "current_kg": current,
        "delta_7d": _delta(7),
        "delta_30d": _delta(30),
        "delta_90d": _delta(90),
        "points": points,
        "latest": latest(),
        "discipline": discipline(),
        "estimated_fields": ["body_fat_pct", "muscle_kg", "water_pct",
                             "bone_kg", "lbm_kg", "visceral_fat"],
    }
