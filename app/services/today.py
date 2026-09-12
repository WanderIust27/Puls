"""Was heute dran ist — eine Empfehlung, keine Liste.

Drei Fragen entscheiden den Tag, und alle drei stehen in eigenen Daten:

* Wie belastbar bist du heute? Erholung von der Uhr, Schlaf, Puls in Ruhe,
  dazu, wie du dich selbst eingetragen hast.
* Was hat gefehlt? Tage seit der letzten Einheit, Muskelgruppen, die
  hinterherhinken, Laufarten, die seit Wochen nicht vorkamen.
* Was willst du erreichen? Der Freitext im Ziel gewichtet die Reihenfolge.

Entschieden wird hier mit Regeln, nicht vom Modell. Jede Regel legt ihren
Grund daneben, damit die Empfehlung nachvollziehbar bleibt und nicht jeden Tag
eine andere Meinung ohne neue Daten hat. Das Modell darf die fertige
Entscheidung in zwei Saetze fassen — mehr nicht.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts
from . import exercises as ex_lib

log = logging.getLogger("puls.today")

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Wie viel jedes Signal zur Belastbarkeit beitraegt. Die Summe der Gewichte
# normiert sich selbst — fehlt ein Signal, zaehlen die uebrigen entsprechend
# mehr. So bleibt die Zahl auch ohne Uhr brauchbar.
WEIGHTS = {"readiness": 3.0, "hrv": 2.0, "sleep": 2.0, "battery": 1.5,
           "resting_hr": 1.5, "mood": 2.0}

REST_BELOW = 35            # darunter ist Training keine gute Idee
EASY_BELOW = 52            # darunter nur locker
HARD_ABOVE = 72            # darüber darf es weh tun
ACWR_CEILING = 1.4         # akute Last gegen den Schnitt — darüber bremsen


# ------------------------------------------------------------------- Signale

def _score(value: float, low: float, high: float) -> float:
    """Einen Messwert auf 0..100 legen, linear zwischen low und high."""
    if high == low:
        return 50.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def _latest_daily(today: dt.date) -> dict[str, Any] | None:
    """Der juengste Tageswert, hoechstens zwei Tage alt."""
    floor = (today - dt.timedelta(days=2)).isoformat()
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM daily_metrics WHERE day >= ? AND day <= ? "
            "ORDER BY day DESC LIMIT 1", (floor, today.isoformat())).fetchone()
    return dict(row) if row else None


def _resting_baseline(today: dt.date) -> float | None:
    floor = (today - dt.timedelta(days=28)).isoformat()
    with get_db() as db:
        rows = [r["resting_hr"] for r in db.execute(
            "SELECT resting_hr FROM daily_metrics WHERE day >= ? "
            "AND resting_hr IS NOT NULL", (floor,)).fetchall()]
    return sum(rows) / len(rows) if len(rows) >= 5 else None


def _mood_today(today: dt.date) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute(
            "SELECT mood, energy, stress, note FROM mood_entries WHERE day=? "
            "ORDER BY recorded_at DESC LIMIT 1", (today.isoformat(),)).fetchone()
    return dict(row) if row else None


def readiness(today: dt.date | None = None) -> dict[str, Any]:
    """Belastbarkeit heute — aus allem, was vorliegt."""
    today = today or dt.date.today()
    daily = _latest_daily(today) or {}
    mood = _mood_today(today)
    parts: list[dict[str, Any]] = []

    def add(key: str, value: float, label: str, detail: str) -> None:
        parts.append({"key": key, "score": round(value), "label": label,
                      "detail": detail, "weight": WEIGHTS[key]})

    if daily.get("training_readiness") is not None:
        v = float(daily["training_readiness"])
        add("readiness", v, "Trainingsbereitschaft",
            f"{v:.0f} von 100 laut Uhr")

    hrv, low, high = (daily.get("hrv_avg"), daily.get("hrv_baseline_low"),
                      daily.get("hrv_baseline_high"))
    if hrv and low and high:
        # In der Basislinie ist alles in Ordnung: die Mitte davon ist 60.
        span = max(1.0, high - low)
        add("hrv", _score(float(hrv), low - span, high + span * 0.5),
            "Herzratenvariabilität",
            f"{hrv:.0f} ms bei einer Basislinie von {low:.0f}–{high:.0f} ms")

    if daily.get("sleep_seconds"):
        hours = float(daily["sleep_seconds"]) / 3600.0
        add("sleep", _score(hours, 4.5, 8.0), "Schlaf",
            f"{int(hours)} h {int((hours % 1) * 60):02d} min")

    if daily.get("body_battery_wake") is not None:
        v = float(daily["body_battery_wake"])
        add("battery", _score(v, 20, 90), "Körperakku beim Aufwachen", f"{v:.0f} %")

    base = _resting_baseline(today)
    if daily.get("resting_hr") and base:
        diff = float(daily["resting_hr"]) - base
        # Ein Ruhepuls fuenf Schlaege ueber dem Schnitt ist ein Warnzeichen.
        add("resting_hr", _score(-diff, -6, 2), "Ruhepuls",
            f"{daily['resting_hr']:.0f} bpm, {diff:+.0f} gegenüber deinem Schnitt")

    if mood and (mood.get("energy") or mood.get("mood")):
        felt = [v for v in (mood.get("energy"), mood.get("mood")) if v]
        stress = mood.get("stress")
        value = sum(felt) / len(felt)
        raw = _score(value, 1, 5)
        if stress:
            raw = raw * 0.75 + _score(6 - stress, 1, 5) * 0.25
        add("mood", raw, "Wie du dich eingetragen hast",
            f"Energie {mood.get('energy') or '–'}/5, Stimmung "
            f"{mood.get('mood') or '–'}/5" +
            (f", Stress {stress}/5" if stress else ""))

    if not parts:
        return {"score": None, "parts": [],
                "hint": "Noch keine Erholungsdaten. Trag dein Gemüt ein oder "
                        "synchronisiere die Uhr — dann wird daraus eine Zahl."}
    total = sum(p["weight"] for p in parts)
    score = sum(p["score"] * p["weight"] for p in parts) / total
    return {"score": round(score), "parts": parts,
            "label": ("erholt" if score >= HARD_ABOVE else
                      "belastbar" if score >= EASY_BELOW else
                      "angeschlagen" if score >= REST_BELOW else "leer"),
            "hint": None}


# -------------------------------------------------------------------- Last

def load(today: dt.date | None = None) -> dict[str, Any]:
    """Was zuletzt war: Tage seit der letzten Einheit, akute gegen chronische Last."""
    today = today or dt.date.today()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT start_time, sport, training_load, duration_s, distance_m "
            "FROM activities WHERE start_time >= ? ORDER BY start_time DESC",
            ((today - dt.timedelta(days=28)).isoformat(),)).fetchall())
        last_strength = db.execute(
            "SELECT MAX(day) AS d FROM exercise_sets").fetchone()["d"]

    def days_since(stamp: str | None) -> int | None:
        if not stamp:
            return None
        try:
            return (today - dt.date.fromisoformat(stamp[:10])).days
        except ValueError:
            return None

    last_run = next((r["start_time"] for r in rows if r["sport"] == "running"), None)
    last_gym_activity = next((r["start_time"] for r in rows
                              if r["sport"] == "strength"), None)
    # Ein Krafttag zaehlt, egal ob die Uhr ihn kennt oder er nachgetragen wurde.
    gym_days = [d for d in (days_since(last_gym_activity), days_since(last_strength))
                if d is not None]

    week = [r for r in rows
            if (r["start_time"] or "")[:10] >= (today - dt.timedelta(days=7)).isoformat()]
    acute = sum(r["training_load"] or 0 for r in week)
    chronic = sum(r["training_load"] or 0 for r in rows) / 4.0
    # Aus einer einzigen Einheit laesst sich kein Verhaeltnis bilden: Die
    # letzte Woche waere dann automatisch das Vierfache des Schnitts.
    with_load = [r for r in rows if r["training_load"]]
    acwr = (round(acute / chronic, 2)
            if chronic > 40 and len(with_load) >= 6 else None)

    return {
        "days_since_run": days_since(last_run),
        "days_since_gym": min(gym_days) if gym_days else None,
        "sessions_7d": len(week),
        "km_7d": round(sum(r["distance_m"] or 0 for r in week) / 1000, 1),
        "acwr": acwr,
        "acwr_note": (None if acwr is None else
                      "deutlich über dem Schnitt der letzten vier Wochen"
                      if acwr > ACWR_CEILING else
                      "unter dem Schnitt — da geht mehr" if acwr < 0.8 else
                      "im gewohnten Rahmen"),
    }


# ---------------------------------------------------------------- Wochenplan

def _day_list(key: str, fallback: list[str]) -> list[str]:
    try:
        value = json.loads(get_setting(key) or "[]")
        return value if isinstance(value, list) and value else fallback
    except ValueError:
        return fallback


def _planned_today(day: str) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute(
            "SELECT id, name, sport, description FROM planned_workouts "
            "WHERE planned_date=? AND status IN ('planned','pushed') "
            "ORDER BY id LIMIT 1", (day,)).fetchone()
    return dict(row) if row else None


# ------------------------------------------------------------- Entscheidung

def decide(today: dt.date | None = None) -> dict[str, Any]:
    """Die Entscheidung fuer heute, mit allen Gruenden, die sie tragen."""
    from . import mood as mood_svc
    from . import trends

    today = today or dt.date.today()
    ready = readiness(today)
    worked = load(today)
    weekday = WEEKDAYS[today.weekday()]
    gym_days = _day_list("gym_days", ["Mo", "Mi", "Fr"])
    run_days = _day_list("run_days", ["Di", "Do", "Sa"])
    planned = _planned_today(today.isoformat())

    trend = trends.summary(today)
    adapt = mood_svc.adaptations(today.isoformat())
    spare = set(adapt.get("spare_groups") or [])
    score = ready["score"]
    reasons: list[dict[str, str]] = []

    # --- Belastbarkeit setzt die Obergrenze -----------------------------
    if score is None:
        intensity, ceiling = "normal", "normal"
        reasons.append({"label": "Keine Erholungsdaten",
                        "detail": "Ohne Zahlen bleibt es bei einer normalen Einheit."})
    elif score < REST_BELOW:
        intensity = ceiling = "ruhe"
        reasons.append({"label": f"Belastbarkeit {score}",
                        "detail": "Zu wenig für eine Einheit, die etwas bringt."})
    elif score < EASY_BELOW:
        intensity = ceiling = "leicht"
        reasons.append({"label": f"Belastbarkeit {score}",
                        "detail": "Reicht für eine Einheit, nicht für eine harte."})
    elif score < HARD_ABOVE:
        intensity = ceiling = "normal"
        reasons.append({"label": f"Belastbarkeit {score}", "detail": "Normal belastbar."})
    else:
        intensity = ceiling = "hart"
        reasons.append({"label": f"Belastbarkeit {score}",
                        "detail": "Erholt — heute darf es wehtun."})

    if worked["acwr"] and worked["acwr"] > ACWR_CEILING and intensity == "hart":
        intensity = "normal"
        reasons.append({"label": f"Belastung {worked['acwr']}×",
                        "detail": f"Die letzte Woche liegt {worked['acwr_note']}. "
                                  "Heute nicht noch einen draufsetzen."})

    # --- Beschwerden koennen alles umwerfen -----------------------------
    severe = [c for c in adapt.get("complaints") or []
              if c.get("kind") in ("pain", "injury") and c.get("severity", 0) >= 3]
    if severe:
        names = ", ".join(c["region_label"] for c in severe)
        if intensity != "ruhe":
            intensity = "leicht"
        reasons.append({"label": f"Beschwerden: {names}",
                        "detail": "Belastung dort aussetzen, den Rest dosieren."})

    # --- Welche Sportart ------------------------------------------------
    kind, focus, note = _choose(weekday, gym_days, run_days, worked, trend,
                               intensity, planned, reasons)

    # Beschwerde-Gruppen aus dem Schwerpunkt nehmen
    if kind == "gym" and spare:
        kept = [g for g in focus if g not in spare]
        if kept != focus:
            dropped = [ex_lib.MUSCLE_LABELS.get(g, g) for g in focus if g in spare]
            reasons.append({"label": f"{', '.join(dropped)} ausgespart",
                            "detail": "Steht wegen deiner Meldung heute nicht an."})
        focus = kept or [g["key"] for g in trend["muscles"]["groups"]
                         if g["key"] not in spare][:2]

    minutes = _minutes(kind, intensity)
    return {"day": today.isoformat(), "weekday": weekday, "kind": kind,
            "intensity": intensity, "ceiling": ceiling, "focus": focus,
            "focus_labels": [ex_lib.MUSCLE_LABELS.get(g, g) for g in focus]
                            if kind in ("gym", "home") else [],
            "minutes": minutes, "note": note, "reasons": reasons,
            "readiness": ready, "load": worked, "trend": trend,
            "planned": planned, "goal": trend["goal"],
            "gym_days": gym_days, "run_days": run_days,
            "complaints": adapt.get("complaints") or []}


def _choose(weekday: str, gym_days: list[str], run_days: list[str],
            worked: dict[str, Any], trend: dict[str, Any], intensity: str,
            planned: dict[str, Any] | None, reasons: list[dict[str, str]]
            ) -> tuple[str, list[str], str]:
    """Kraft, Laufen, zuhause oder Pause — und woran es liegt."""
    muscles = trend["muscles"]
    running = trend["running"]
    focus = muscles.get("focus") or [g["key"] for g in muscles["groups"][:2]]

    if intensity == "ruhe":
        return "rest", [], "Heute erholen. Das ist auch Training."

    is_gym_day = weekday in gym_days
    is_run_day = weekday in run_days
    gym_gap = worked["days_since_gym"]
    run_gap = worked["days_since_run"]

    if planned:
        sport = (planned.get("sport") or "").lower()
        kind = "run" if sport == "running" else "gym"
        reasons.append({"label": "Steht im Plan",
                        "detail": f"„{planned['name']}“ ist für heute eingetragen."})
        return kind, focus, ""

    # Was heute schon stattgefunden hat, steht nicht noch einmal an. Ein
    # Vorschlag, der „Krafttraining war heute schon“ als Begruendung fuer
    # Krafttraining nennt, widerspricht sich selbst.
    done = []
    if gym_gap == 0:
        done.append("Krafttraining")
    if run_gap == 0:
        done.append("ein Lauf")

    # Wie dringend ist was? Tage seit der letzten Einheit, plus ein Bonus,
    # wenn heute ohnehin der Tag dafuer ist.
    open_today: list[tuple[str, int]] = []
    if is_gym_day and gym_gap != 0:
        open_today.append(("gym", (gym_gap if gym_gap is not None else 14) + 3))
    if is_run_day and run_gap != 0:
        open_today.append(("run", (run_gap if run_gap is not None else 14) + 3))

    if open_today:
        kind, _ = max(open_today, key=lambda c: c[1])
        gap = gym_gap if kind == "gym" else run_gap
        what = "Krafttraining" if kind == "gym" else "Laufen"
        if len(open_today) > 1:
            other = "Der Lauf" if kind == "gym" else "Das Gym"
            reasons.append({"label": "Beides steht an",
                            "detail": f"{_gap_text(what, gap)} {other} kann morgen."})
            return kind, focus, ("Wenn du Lust hast, häng 20 Minuten locker an."
                                 if kind == "gym" else "")
        reasons.append({"label": f"{weekday} ist dein "
                                 f"{'Gym' if kind == 'gym' else 'Lauf'}-Tag",
                        "detail": _gap_text(what, gap)})
        return kind, focus, ""

    if done:
        reasons.append({"label": "Heute war schon",
                        "detail": f"{' und '.join(done)} steht bereits in den Daten."})
        return "done", [], "Dehnen am Abend, sonst nichts mehr."

    # Kein geplanter Tag: nur wenn wirklich etwas liegen geblieben ist.
    gym_urge = gym_gap if gym_gap is not None else 14
    run_urge = run_gap if run_gap is not None else 14
    if max(gym_urge, run_urge) >= 4:
        if gym_urge >= run_urge:
            reasons.append({"label": "Eigentlich frei",
                            "detail": _gap_text("Krafttraining", gym_gap)
                                      + " Eine kurze Einheit zuhause reicht."})
            return "home", focus, "Kein Gym-Tag — 30 Minuten auf der Matte genügen."
        reasons.append({"label": "Eigentlich frei",
                        "detail": _gap_text("Laufen", run_gap)
                                  + " Ein lockerer Lauf hält die Grundlage."})
        return "run", focus, ""

    reasons.append({"label": "Kein Trainingstag",
                    "detail": "Die letzten Einheiten liegen dicht genug beieinander."})
    return "mobility", [], "Beweglichkeit und früh ins Bett."




def _gap_text(what: str, gap: int | None) -> str:
    if gap is None:
        return f"{what} ist noch nicht aufgezeichnet."
    if gap == 0:
        return f"{what} war heute schon."
    if gap == 1:
        return f"Das letzte {what} war gestern."
    return f"Das letzte {what} ist {gap} Tage her."


def _minutes(kind: str, intensity: str) -> int:
    def setting(key: str, fallback: int) -> int:
        try:
            return int(float(get_setting(key, str(fallback)) or fallback))
        except (TypeError, ValueError):
            return fallback
    if kind == "gym":
        base = setting("gym_minutes", 75)
    elif kind == "run":
        base = setting("run_minutes", 45)
    elif kind == "home":
        base = 30
    else:
        base = 15
    if intensity == "leicht":
        base = int(base * 0.7)
    return max(10, int(round(base / 5.0) * 5))


# -------------------------------------------------------------- Die Einheit

RUN_KINDS = {
    "easy": "Lockerer Dauerlauf", "tempo": "Tempolauf",
    "long": "Langer Lauf", "interval": "Intervalle",
}


def _run_kind(verdict: dict[str, Any]) -> str:
    """Welche Laufart heute fehlt — aus dem Trend, nicht aus Laune."""
    running = verdict["trend"]["running"]
    goal = verdict["trend"]["goal"]
    if verdict["intensity"] == "leicht":
        return "easy"
    wants = {r for r in (goal.get("runs") or [])}
    if running.get("hard_runs", 0) == 0 and verdict["intensity"] == "hart":
        return "tempo" if "tempo" in wants or not wants else "long"
    if running.get("longest_recent", 0) < 8 and "long" in wants:
        return "long"
    if verdict["intensity"] == "hart" and running.get("runs_recent", 0) >= 3:
        return "tempo"
    return "easy"


def session_for(verdict: dict[str, Any]) -> dict[str, Any] | None:
    """Die konkrete Einheit zur Entscheidung bauen — noch nicht gespeichert."""
    from . import planner, running as run_lib

    kind = verdict["kind"]
    minutes = verdict["minutes"]
    try:
        if kind == "gym":
            return planner.build_gym_session(minutes, emphasis=verdict["focus"][:3])
        if kind == "home":
            return planner.build_home_session(minutes, verdict["focus"][:3],
                                              with_dumbbell=True)
        if kind == "run":
            rk = _run_kind(verdict)
            verdict["run_kind"] = rk
            verdict["run_label"] = RUN_KINDS[rk]
            builder = {"easy": run_lib.build_easy_run, "tempo": run_lib.build_tempo_run,
                       "long": run_lib.build_long_run,
                       "interval": run_lib.build_interval_run}[rk]
            return builder(minutes)
        if kind in ("mobility", "done"):
            return planner.build_evening_yoga(minutes)
    except Exception as e:                                      # noqa: BLE001
        log.warning("Einheit konnte nicht gebaut werden: %s", e)
    return None


# ------------------------------------------------------------ Formulierung

KIND_HEADLINE = {
    "gym": "Krafttraining", "run": "Laufen", "home": "Zuhause trainieren",
    "mobility": "Beweglichkeit", "rest": "Pause", "done": "Erledigt",
}


def _plain_sentence(verdict: dict[str, Any]) -> str:
    """Der Satz, der immer da ist — auch ohne Modell."""
    kind = verdict["kind"]
    minutes = verdict["minutes"]
    if kind == "rest":
        return ("Heute nichts. Deine Werte sagen, dass eine Einheit jetzt mehr "
                "kostet als sie bringt — morgen bist du weiter.")
    if kind == "mobility":
        return (f"Kein Trainingstag. {minutes} Minuten Dehnen am Abend, "
                "sonst nichts.")
    if kind == "done":
        return ("Heute steht schon eine Einheit in den Daten. "
                + verdict["reasons"][-1]["detail"]
                + f" {minutes} Minuten Dehnen am Abend, mehr braucht es nicht.")
    if kind == "run":
        return (f"{verdict.get('run_label', 'Lauf')}, {minutes} Minuten. "
                + verdict["reasons"][-1]["detail"])
    where = "im Studio" if kind == "gym" else "zuhause"
    focus = ", ".join(verdict["focus_labels"][:2]) or "Ganzkörper"
    return (f"{minutes} Minuten {where}, Schwerpunkt {focus}. "
            + verdict["reasons"][-1]["detail"])


def _knowledge(verdict: dict[str, Any]) -> tuple[str, list[str]]:
    """Passende Auszuege zur heutigen Entscheidung — falls die Basis da ist.

    Gefragt wird nicht nach einem Stichwort, sondern nach dem, was heute
    ansteht. Bei einem langen Lauf soll die Regel zur Steigerung danebenstehen,
    bei einer Pause das Kapitel zur Erholung.
    """
    try:
        from ..main import app
        kb = getattr(app.state, "kb", None)
        if kb is None:
            return "", []
        focus = ", ".join(verdict.get("focus_labels") or []) or ""
        query = {
            "gym": f"Krafttraining {focus} Volumen Sätze Intensität",
            "home": f"Training ohne Geräte {focus}",
            "run": f"Laufen {verdict.get('run_label') or 'Dauerlauf'} "
                   "Umfang Intensität steigern",
            "mobility": "Beweglichkeit Dehnen Aufwärmen",
            "rest": "Regeneration Pause Erholung Schlaf",
            "done": "Regeneration nach dem Training",
        }.get(verdict["kind"], "Training")
        return kb.context_with_sources(query, k=3, max_chars=2200)
    except Exception as e:                                      # noqa: BLE001
        log.debug("Tagesempfehlung ohne Wissensbasis: %s", e)
        return "", []


def _phrase(verdict: dict[str, Any]) -> str:
    """Das Modell die fertige Entscheidung in zwei Saetze fassen lassen."""
    reasons = [f"- {r['label']}: {r['detail']}" for r in verdict["reasons"]]
    ready = verdict["readiness"]
    if ready.get("parts"):
        reasons += [f"- {p['label']}: {p['detail']}" for p in ready["parts"]]
    goal = (verdict["goal"].get("text") or "").strip()
    plan = _plain_sentence(verdict)

    context, sources = _knowledge(verdict)
    verdict["sources"] = sources
    try:
        from .ollama_client import generate
        text = generate(
            prompt=(
                "Das ist die Empfehlung für heute, sie steht schon fest:\n"
                f"{plan}\n\nDie Gründe dafür:\n" + "\n".join(reasons)
                + (f"\n\nSein Ziel: {goal}" if goal else "")
                + (f"\n\nGeprüfte Auszüge, falls sie hierher passen:\n{context}"
                   if context else "")
                + "\n\nFasse das in höchstens zwei Sätzen zusammen, direkt "
                  "und motivierend, auf Deutsch, per Du. Ändere die "
                  "Empfehlung nicht und nenne keine Zahlen, die oben nicht "
                  "stehen. Keine Anrede, keine Aufzählung."),
            system="Du bist ein knapper, ehrlicher Trainingscoach.",
            temperature=0.6)
        text = " ".join(text.split())
        if 20 <= len(text) <= 400:
            return text
    except Exception as e:                                      # noqa: BLE001
        log.debug("Tagesempfehlung ohne Modell: %s", e)
    return plan


def recommendation(today: dt.date | None = None, phrase: bool = True
                   ) -> dict[str, Any]:
    """Alles zusammen: Entscheidung, Einheit, Begruendung, ein Satz dazu."""
    verdict = decide(today)
    session = session_for(verdict)
    verdict["session"] = session
    # Die Dauer der gebauten Einheit gilt. Eine Empfehlung, die 75 Minuten
    # sagt und 80 Minuten liefert, ist an genau der Stelle falsch, an der man
    # sie nachrechnet.
    if session and session.get("minutes"):
        verdict["minutes"] = int(session["minutes"])
    verdict["headline"] = KIND_HEADLINE.get(verdict["kind"], "Training")
    if verdict["kind"] == "run" and verdict.get("run_label"):
        verdict["headline"] = verdict["run_label"]
    verdict["plain"] = _plain_sentence(verdict)
    verdict.setdefault("sources", [])
    verdict["text"] = _phrase(verdict) if phrase else verdict["plain"]
    return verdict
