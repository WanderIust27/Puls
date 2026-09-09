"""Vorschlaege des Coaches, die ueber die feste Wochenstruktur hinausgehen.

Deine Struktur ist der Rahmen: morgens laufen, Mo/Mi/Fr Gym, abends Yoga. Sie
bleibt. Aber ein Rahmen allein macht noch kein Training — irgendwann fehlt ein
langer Lauf, es ist zu lange nur locker gelaufen worden, oder die Belastung
steigt schneller als die Erholung mitkommt.

Genau dafuer sind diese Vorschlaege da. Jeder entsteht aus einer Regel, die im
Code steht, nennt seinen Anlass und laesst sich mit einem Tipp uebernehmen oder
verwerfen. Nichts geht ungefragt an die Uhr — anders als bei Beschwerden, auf
die sofort und ohne Rueckfrage reagiert wird (siehe mood.adaptations).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.suggestions")

# Ein Vorschlag derselben Art wird nicht staendig wiederholt: einmal verworfen,
# ist fuer diese Zeit Ruhe.
COOLDOWN_DAYS = 10

LONG_RUN_GAP_DAYS = 14      # so lange darf ein langer Lauf ausbleiben
QUALITY_GAP_DAYS = 12       # so lange ohne Tempoeinheit
EASY_SHARE_FLOOR = 68       # Prozent Zone 1-2, darunter wird es zu hart
ACWR_CEILING = 1.45
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _next_weekday(name: str) -> str:
    """Naechstes Vorkommen dieses Wochentags, heute ausgenommen."""
    target = WEEKDAYS.index(name)
    today = dt.date.today()
    delta = (target - today.weekday()) % 7 or 7
    return (today + dt.timedelta(days=delta)).isoformat()


def _recent_open(kind: str) -> bool:
    """Gibt es diesen Vorschlag schon — offen oder kuerzlich verworfen?"""
    since = (dt.date.today() - dt.timedelta(days=COOLDOWN_DAYS)).isoformat()
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM coach_adaptations WHERE kind=? AND "
            "(status='open' OR substr(created_at,1,10) >= ?) LIMIT 1",
            (kind, since)).fetchone()
    return row is not None


def _store(kind: str, title: str, detail: str, trigger: str,
           payload: dict[str, Any] | None) -> int | None:
    if _recent_open(kind):
        return None
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO coach_adaptations(day, kind, trigger, title, detail,
                                             payload_json, status)
               VALUES(?,?,?,?,?,?, 'open')""",
            (dt.date.today().isoformat(), kind, trigger, title, detail,
             json.dumps(payload, ensure_ascii=False) if payload else None))
        return int(cur.lastrowid or 0)


# ------------------------------------------------------------------ Regeln

def _runs(days: int) -> list[dict[str, Any]]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        return rows_to_dicts(db.execute(
            """SELECT id, name, start_time, distance_m, duration_s, avg_hr,
                      hr_zones_json
               FROM activities WHERE sport='running'
                 AND substr(start_time,1,10) >= ? ORDER BY start_time DESC""",
            (since,)).fetchall())


def _check_long_run(out: list[int]) -> None:
    """Wer 10 km unter 60 Minuten will, braucht regelmaessig einen langen Lauf.

    Taegliche 20-30-Minuten-Laeufe bauen die Grundlage nicht weit genug aus —
    die kommt aus der einen langen Einheit pro Woche.
    """
    goal_km = float(get_setting("run_goal_distance_km", "10") or 10)
    runs = _runs(LONG_RUN_GAP_DAYS)
    longest = max((r["duration_s"] or 0 for r in runs), default=0)
    far = max((r["distance_m"] or 0 for r in runs), default=0)
    if longest >= 3000 or far >= goal_km * 800:
        return

    minutes = 45 if not runs else min(60, max(40, int(longest / 60) + 15))
    day = _next_weekday("So")
    sid = _store(
        "long_run",
        f"Langer Lauf am Sonntag, {minutes} Minuten",
        (f"In den letzten {LONG_RUN_GAP_DAYS} Tagen war kein Lauf länger als "
         f"{int(longest / 60)} Minuten. Für {goal_km:.0f} km unter deiner "
         f"Zielzeit ist die lange Einheit der Teil, der die Grundlage breit "
         f"macht — deine täglichen 20 bis 30 Minuten allein schaffen das nicht. "
         f"Ruhig, im Plauderton, es geht nur um die Dauer."),
        f"längster Lauf zuletzt {int(longest / 60)} min",
        {"action": "add_run", "kind": "long", "minutes": minutes,
         "planned_date": day, "name": f"Langer Lauf {minutes} min"})
    if sid:
        out.append(sid)


def _check_quality(out: list[int]) -> None:
    """Nur locker laufen macht nicht schneller — irgendwann fehlt der Reiz."""
    runs = _runs(QUALITY_GAP_DAYS)
    if len(runs) < 4:
        return
    hard = 0
    for r in runs:
        if not r["hr_zones_json"]:
            continue
        try:
            z = {int(k): float(v) for k, v in json.loads(r["hr_zones_json"]).items()}
        except (ValueError, TypeError):
            continue
        if z.get(4, 0) + z.get(5, 0) > 240:      # über vier Minuten hart
            hard += 1
    if hard:
        return

    day = _next_weekday("Di")
    sid = _store(
        "tempo_run",
        "Tempoeinheit am Dienstag, 30 Minuten",
        (f"Deine letzten {len(runs)} Läufe lagen alle im lockeren Bereich. Das "
         f"ist die richtige Grundlage — aber ohne eine harte Einheit pro Woche "
         f"fehlt der Reiz, der das Tempo hebt. 10 Minuten im Schwellentempo "
         f"reichen dafür; den Rest läufst du wie immer."),
        f"{len(runs)} Läufe ohne Tempoanteil",
        {"action": "add_run", "kind": "tempo", "minutes": 30,
         "planned_date": day, "name": "Tempolauf 30 min"})
    if sid:
        out.append(sid)


def _check_intensity(out: list[int]) -> None:
    """Zu viel Intensität ist häufiger als zu wenig."""
    from . import run_analysis
    trend = run_analysis.form_trend(30)
    share = trend.get("easy_share")
    if share is None or share >= EASY_SHARE_FLOOR or trend["runs"] < 6:
        return
    sid = _store(
        "too_hard",
        "Die lockeren Läufe wirklich locker laufen",
        (f"Nur {share} % deiner Laufzeit lagen in Zone 1–2, sinnvoll wären "
         f"75 bis 80. Das ist der häufigste Fehler im Breitensport: Die "
         f"lockeren Läufe werden zu schnell, die harten dadurch zu lasch, und "
         f"am Ende liegt alles in der Mitte, wo am wenigsten passiert. "
         f"Nimm bei den Morgenläufen bewusst Tempo raus."),
        f"nur {share} % in Zone 1–2", None)
    if sid:
        out.append(sid)


def _check_load(out: list[int]) -> None:
    """Steigt die Belastung schneller als die Erholung?"""
    from . import metrics
    acwr = metrics.acwr()
    if acwr is None or acwr <= ACWR_CEILING:
        return
    sid = _store(
        "deload",
        "Ruhigere Woche einlegen",
        (f"Dein Belastungsverhältnis liegt bei {acwr:.2f}. Über 1,5 steigt das "
         f"Verletzungsrisiko messbar — der Körper kommt mit dem Aufbau nicht "
         f"mehr nach. Eine Woche mit rund einem Drittel weniger Umfang kostet "
         f"dich nichts und erspart womöglich eine Pause von Wochen."),
        f"ACWR {acwr:.2f}", {"action": "advice"})
    if sid:
        out.append(sid)


def _check_recovery(out: list[int]) -> None:
    """HRV unter der Basislinie bei gleichzeitig erhöhtem Ruhepuls."""
    from . import metrics
    rec = metrics.recovery_series(21)
    hrv = rec["baselines"].get("hrv_avg") or {}
    rhr = rec["baselines"].get("resting_hr") or {}
    if hrv.get("delta") is None or rhr.get("delta") is None:
        return
    if not (hrv["delta"] < -3 and rhr["delta"] > 2):
        return
    sid = _store(
        "recovery_day",
        "Heute besser nur Yoga",
        (f"Deine HRV liegt {abs(hrv['delta']):.0f} ms unter deinem Schnitt und "
         f"der Ruhepuls {rhr['delta']:.0f} Schläge darüber. Beides zusammen ist "
         f"das deutlichste Zeichen, das dein Körper senden kann. Das Training "
         f"von heute ist morgen nicht verloren — eine durchgezogene Einheit im "
         f"falschen Moment dagegen schon."),
        f"HRV {hrv['delta']:.0f}, Ruhepuls +{rhr['delta']:.0f}",
        {"action": "advice"})
    if sid:
        out.append(sid)


def _check_neglected_muscle(out: list[int]) -> None:
    """Eine Muskelgruppe, die im Gym seit Wochen nicht drankam."""
    since = (dt.date.today() - dt.timedelta(days=21)).isoformat()
    with get_db() as db:
        rows = db.execute(
            """SELECT e.muscle_group AS grp, MAX(s.day) AS zuletzt
               FROM exercises e LEFT JOIN exercise_sets s ON s.exercise_id = e.id
               WHERE e.active=1 AND e.slot='main'
               GROUP BY e.muscle_group""").fetchall()
    stale = [r["grp"] for r in rows
             if not r["zuletzt"] or r["zuletzt"] < since]
    if not stale or len(stale) > 2:      # mehr als zwei heißt: nichts trainiert
        return
    from . import exercises as ex_lib
    labels = ", ".join(ex_lib.MUSCLE_LABELS.get(g, g) for g in stale)
    sid = _store(
        "neglected",
        f"{labels} kam lange nicht dran",
        (f"Seit über drei Wochen ohne Satz für {labels}. Bei einer "
         f"Ganzkörper-Aufteilung fällt so etwas leicht durch, weil die "
         f"Rotation immer dieselben Geräte zieht. Die nächste Einheit kann das "
         f"gezielt nachholen."),
        f"{labels} seit über 21 Tagen ohne Satz",
        {"action": "gym_focus", "groups": stale})
    if sid:
        out.append(sid)


def _check_pullups(out: list[int]) -> None:
    """Klimmzug-Ziel: bewegt sich etwas?"""
    best = get_setting("pullup_best", "")
    goal = get_setting("pullup_goal", "10")
    if not best:
        return
    try:
        best_n, goal_n = int(float(best)), int(float(goal))
    except (TypeError, ValueError):
        return
    if best_n >= goal_n:
        return
    since = (dt.date.today() - dt.timedelta(days=21)).isoformat()
    with get_db() as db:
        n = db.execute(
            """SELECT COUNT(*) AS n FROM exercise_sets s
               JOIN exercises e ON e.id = s.exercise_id
               WHERE e.slot='pullup' AND s.day >= ?""", (since,)).fetchone()["n"]
    if n >= 6:
        return
    sid = _store(
        "pullup_focus",
        "Klimmzüge häufiger einbauen",
        (f"Dein Ziel sind {goal_n} Klimmzüge, dein Bestwert liegt bei {best_n} "
         f"— aber in den letzten drei Wochen kamen nur {n} Sätze zusammen. "
         f"Klimmzüge werden über Häufigkeit besser, nicht über Umfang in einer "
         f"Einheit. Lieber an jedem Gym-Tag ein paar Sätze früh, solange du "
         f"frisch bist."),
        f"{n} Klimmzug-Sätze in 21 Tagen",
        {"action": "gym_focus", "groups": ["back"]})
    if sid:
        out.append(sid)


RULES = (_check_long_run, _check_quality, _check_intensity, _check_load,
         _check_recovery, _check_neglected_muscle, _check_pullups)


def generate() -> list[int]:
    """Alle Regeln pruefen. Jede einzeln abgesichert — eine fehlende
    Datenquelle darf nicht die uebrigen Vorschlaege kosten."""
    created: list[int] = []
    for rule in RULES:
        try:
            rule(created)
        except Exception as e:
            log.debug("Regel %s uebersprungen: %s", rule.__name__, e)
    if created:
        log.info("%d neue Coach-Vorschläge.", len(created))
    return created


# --------------------------------------------------------------- Verwalten

def list_open(limit: int = 10) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT * FROM coach_adaptations WHERE status='open' "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall())
    for r in rows:
        r["payload"] = json.loads(r.pop("payload_json") or "null")
    return rows


def history(limit: int = 30) -> list[dict[str, Any]]:
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT * FROM coach_adaptations WHERE status != 'open' "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall())
    for r in rows:
        r.pop("payload_json", None)
    return rows


def dismiss(sid: int) -> bool:
    with get_db() as db:
        return db.execute(
            "UPDATE coach_adaptations SET status='dismissed', "
            "applied_at=datetime('now') WHERE id=? AND status='open'",
            (sid,)).rowcount > 0


def apply(sid: int) -> dict[str, Any]:
    """Vorschlag umsetzen — je nach Art ein Workout anlegen oder vormerken."""
    with get_db() as db:
        row = db.execute("SELECT * FROM coach_adaptations WHERE id=?",
                         (sid,)).fetchone()
    if not row:
        raise ValueError("Diesen Vorschlag gibt es nicht.")
    if row["status"] != "open":
        raise ValueError("Dieser Vorschlag wurde schon bearbeitet.")

    payload = json.loads(row["payload_json"] or "null") or {}
    action = payload.get("action", "advice")
    result: dict[str, Any] = {"action": action}

    if action == "add_run":
        from . import running
        workout = running.build_easy_run(
            minutes=int(payload.get("minutes", 45)),
            kind=payload.get("kind", "long"))
        workout["name"] = payload.get("name", workout.get("name"))
        with get_db() as db:
            cur = db.execute(
                """INSERT INTO planned_workouts
                   (name, sport, planned_date, description, steps_json, created_by)
                   VALUES(?,?,?,?,?, 'coach')""",
                (workout["name"], "running", payload.get("planned_date"),
                 row["detail"],
                 json.dumps({"steps": workout.get("steps", [])},
                            ensure_ascii=False)))
            result["workout_id"] = int(cur.lastrowid or 0)
        result["planned_date"] = payload.get("planned_date")

    elif action == "gym_focus":
        # Als Wunsch hinterlegen; die naechste gebaute Einheit zieht ihn heran.
        groups = payload.get("groups") or []
        from ..db import set_setting
        set_setting("gym_focus_groups", json.dumps(groups))
        set_setting("gym_focus_until",
                    (dt.date.today() + dt.timedelta(days=14)).isoformat())
        result["groups"] = groups

    with get_db() as db:
        db.execute("UPDATE coach_adaptations SET status='applied', "
                   "applied_at=datetime('now') WHERE id=?", (sid,))
    return result


def active_focus() -> list[str]:
    """Muskelgruppen, die der Planer gerade bevorzugen soll."""
    until = get_setting("gym_focus_until", "")
    if not until or until < dt.date.today().isoformat():
        return []
    try:
        groups = json.loads(get_setting("gym_focus_groups", "[]") or "[]")
        return groups if isinstance(groups, list) else []
    except ValueError:
        return []
