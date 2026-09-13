"""Push, Pull, Beine — welcher Aufbau zu wie vielen Trainingstagen passt.

Bis hierher war jede Gym-Einheit eine Ganzkoerpereinheit. Fuer zwei oder drei
Tage die Woche ist das die richtige Antwort, und 02_Training_Gym.md sagt genau
das: Bei drei Tagen trifft Ganzkoerper jede Muskelgruppe dreimal statt einmal,
und ein ausgefallener Tag streicht keine ganze Gruppe. Ab vier Tagen kippt es —
dann wird die einzelne Einheit zu lang, und eine Teilung ist besser.

Das Modul macht daraus eine Entscheidung, die man nachlesen kann:

* **Welcher Split** — aus der Zahl der Gym-Tage nach der Tabelle in
  02_Training_Gym.md, oder ausdruecklich eingestellt. Wer Push/Pull will,
  bekommt Push/Pull, auch bei drei Tagen: Es ist seine Woche.
* **Welcher Tag des Splits heute dran ist** — nicht nach Kalender, sondern
  nach dem, was zuletzt tatsaechlich trainiert wurde. Wer den Push-Tag
  verpasst hat, macht Push nach und nicht Pull, weil Dienstag ist.

Die Unterscheidung Druecken/Ziehen traegt die Tabelle exercises nicht: Bizeps
und Trizeps heissen dort beide "arms". Deshalb steht sie hier, als Wortliste
ueber den Uebungsnamen — grob, aber nachvollziehbar, und an einer Stelle
statt verstreut.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..constants import SPLIT_BY_DAYS
from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.split")


# ---------------------------------------------------- Druecken oder Ziehen

# Nach Muskelgruppe, soweit sie eindeutig ist. "arms" ist es nicht: Der Bizeps
# zieht, der Trizeps drueckt, und die Spalte kennt den Unterschied nicht.
PATTERN_BY_GROUP: dict[str, str | None] = {
    "chest": "push",
    "shoulders": "push",
    "back": "pull",
    "legs": "legs",
    "core": "legs",       # Rumpf laeuft am Beintag mit — so steht es in Template A
    "arms": None,
    "cardio": None,
}

# Der Uebungsname entscheidet, wo die Gruppe es nicht kann — und korrigiert
# sie, wo sie danebenliegt: Aufrechtes Rudern zaehlt zu "shoulders", ist aber
# eine Zugbewegung. Die Liste wird vor der Gruppe gefragt.
PULL_WORDS = ("bizeps", "curl", "rudern", "klimmzug", "klimmzuege", "latzieh",
              "latzug", "reverse fly", "face pull", "kreuzheben", "deadlift",
              "ueberzuege", "überzüge", "pullover", "schwimmer", "nackenzieh",
              "shrug", "zieh")
PUSH_WORDS = ("trizeps", "drueck", "drück", "press", "liegestuetz",
              "liegestütz", "dips", "seitheben", "butterfly", "flys",
              "pike", "handstand", "schulterdr", "bankdr", "stossen", "stoßen")
# Was weder zieht noch drueckt und auch keine Beinarbeit ist: Aufwaermen,
# Dehnen, Rumpf-Halteuebungen. Die laufen in jedem Split mit.
NEUTRAL_SLOTS = {"warmup", "stretch", "cardio"}


def pattern_of(ex: dict[str, Any]) -> str | None:
    """Zieht, drueckt oder traegt die Uebung die Beine? None heisst: egal.

    Die Reihenfolge ist Absicht. Beine und Rumpf entscheidet die Gruppe, bevor
    der Name gefragt wird — sonst landet die Beinpresse wegen "press" am
    Push-Tag und der Hamstring-Curl wegen "curl" am Pull-Tag. Erst danach
    zaehlt der Name, denn nur er weiss, ob "arms" den Bizeps oder den Trizeps
    meint.
    """
    if (ex.get("slot") or "main") in NEUTRAL_SLOTS:
        return None
    group = ex.get("muscle_group") or ""
    if group in ("legs", "core"):
        return "legs"
    name = (ex.get("name") or "").lower()
    for word in PULL_WORDS:
        if word in name:
            return "pull"
    for word in PUSH_WORDS:
        if word in name:
            return "push"
    return PATTERN_BY_GROUP.get(group, None)


# ------------------------------------------------------------- Die Splits

# Jeder Split ist eine Abfolge von Tagen. patterns nennt die Bewegungsarten,
# die an diesem Tag drankommen; None heisst "alles". groups ist die
# Muskelgruppen-Reihenfolge fuer den Hauptteil — sie steuert, was zuerst
# gewaehlt wird, nicht was erlaubt ist.
SPLITS: dict[str, dict[str, Any]] = {
    "fullbody": {
        "label": "Ganzkörper",
        "note": ("Jede Einheit trifft den ganzen Körper. Bei zwei bis drei "
                 "Tagen die Woche ist das die beste Verteilung: jede "
                 "Muskelgruppe zwei- bis dreimal, und ein ausgefallener Tag "
                 "streicht keine ganze Gruppe."),
        "days": [
            {"key": "full", "label": "Ganzkörper", "patterns": None,
             "groups": ["legs", "chest", "back", "shoulders", "arms", "core"]},
        ],
    },
    "upper_lower": {
        "label": "Oberkörper / Unterkörper",
        "note": ("Zwei Einheiten im Wechsel. Ab vier Tagen die Woche die "
                 "sauberste Teilung — jede Muskelgruppe kommt immer noch "
                 "zweimal dran, aber die einzelne Einheit bleibt kurz."),
        "days": [
            {"key": "upper", "label": "Oberkörper", "patterns": ("push", "pull"),
             "groups": ["back", "chest", "shoulders", "arms"]},
            {"key": "lower", "label": "Unterkörper", "patterns": ("legs",),
             "groups": ["legs", "core"]},
        ],
    },
    "ppl": {
        "label": "Push / Pull / Beine",
        "note": ("Drücken, Ziehen, Beine im Wechsel. Die längste Erholung je "
                 "Muskelgruppe, aber auch die niedrigste Frequenz: Bei drei "
                 "Tagen die Woche kommt jede Gruppe nur einmal dran."),
        "days": [
            {"key": "push", "label": "Push", "patterns": ("push",),
             "groups": ["chest", "shoulders", "arms"]},
            {"key": "pull", "label": "Pull", "patterns": ("pull",),
             "groups": ["back", "arms"]},
            {"key": "legs", "label": "Beine", "patterns": ("legs",),
             "groups": ["legs", "core"]},
        ],
    },
}

MODES = ("auto", *SPLITS)


def chosen_split(gym_days: list[str] | None = None) -> dict[str, Any]:
    """Welcher Split gilt — eingestellt oder aus der Zahl der Tage abgeleitet."""
    mode = (get_setting("gym_split", "auto") or "auto").strip().lower()
    if gym_days is None:
        gym_days = json.loads(get_setting("gym_days", "[]") or "[]")
    days = len(gym_days or [])
    key = mode if mode in SPLITS else SPLIT_BY_DAYS.get(days, "fullbody")
    out = dict(SPLITS[key])
    out["key"] = key
    out["mode"] = "auto" if mode not in SPLITS else "manuell"
    out["gym_days"] = days
    out["why"] = (f"{days} Gym-Tage pro Woche — danach richtet sich der Aufbau."
                  if out["mode"] == "auto"
                  else "Von dir so eingestellt.")
    return out


# ------------------------------------------------- Welcher Tag heute dran ist

LOOKBACK_DAYS = 21        # so weit zurueck wird nach der letzten Einheit gesucht
MIN_SETS = 3              # darunter war es keine Einheit, sondern ein Versuch


def _last_sessions(today: dt.date, limit: int) -> list[dict[str, Any]]:
    """Die letzten Krafttage mit ihren Muskelgruppen — je Tag eine Zeile."""
    floor = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT s.day, e.name, e.muscle_group, e.slot, COUNT(*) AS sets
               FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
               WHERE s.day >= ? AND s.day <= ?
               GROUP BY s.day, e.id
               ORDER BY s.day DESC""", (floor, today.isoformat())).fetchall())
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_day.setdefault(row["day"], []).append(row)
    out = []
    for day in sorted(by_day, reverse=True)[:limit]:
        items = by_day[day]
        if sum(i["sets"] for i in items) < MIN_SETS:
            continue
        out.append({"day": day, "items": items})
    return out


def _classify(items: list[dict[str, Any]], split: dict[str, Any]) -> str | None:
    """Welcher Tag des Splits war das? Nach Saetzen gewichtet, nicht nach Namen.

    Ganzkoerper hat nur einen Tag — da gibt es nichts zu erkennen. Bei zwei
    oder drei Moeglichkeiten gewinnt die, auf die die meisten Saetze entfallen,
    und nur wenn sie deutlich vorn liegt: Eine Einheit, die halb Push und halb
    Pull war, sagt ueber die Rotation nichts.
    """
    days = split["days"]
    if len(days) < 2:
        return days[0]["key"]
    score: dict[str, float] = {d["key"]: 0.0 for d in days}
    total = 0.0
    for item in items:
        pattern = pattern_of(item)
        if not pattern:
            continue
        total += item["sets"]
        for d in days:
            if pattern in (d["patterns"] or ()):
                score[d["key"]] += item["sets"]
    if not total:
        return None
    best = max(score, key=lambda k: score[k])
    if score[best] < total * 0.5:
        return None
    return best


def next_day(today: dt.date | None = None,
             gym_days: list[str] | None = None) -> dict[str, Any]:
    """Der Tag des Splits, der als Naechstes dran ist — samt Begruendung.

    Die Rotation haengt an dem, was tatsaechlich trainiert wurde, nicht am
    Wochentag. Wer den Push-Tag hat ausfallen lassen, macht Push nach. Ein
    Kalender, der stur weiterzaehlt, wuerde ihn ueberspringen — und dann fehlt
    die Brust eine Woche lang, ohne dass es jemandem auffaellt.
    """
    today = today or dt.date.today()
    split = chosen_split(gym_days)
    days = split["days"]
    if len(days) < 2:
        return {**split, "day": days[0], "because": split["note"],
                "last": None}

    history = _last_sessions(today, limit=len(days) + 2)
    last_key = last_day = None
    for entry in history:
        key = _classify(entry["items"], split)
        if key:
            last_key, last_day = key, entry["day"]
            break

    keys = [d["key"] for d in days]
    if last_key in keys:
        # Schon heute trainiert? Dann ist die Einheit von heute die letzte,
        # und der naechste Tag ist der danach — nicht derselbe noch einmal.
        index = (keys.index(last_key) + 1) % len(keys)
        gap = (today - dt.date.fromisoformat(last_day)).days
        because = (f"Zuletzt {days[keys.index(last_key)]['label']}"
                   + (" heute" if gap == 0 else " gestern" if gap == 1
                      else f" vor {gap} Tagen")
                   + f" — als Nächstes ist {days[index]['label']} dran.")
    else:
        index = 0
        because = (f"Keine Einheit der letzten {LOOKBACK_DAYS} Tage ließ sich "
                   f"eindeutig zuordnen — es geht bei "
                   f"{days[0]['label']} los.")
    return {**split, "day": days[index], "because": because,
            "last": {"key": last_key, "day": last_day} if last_key else None}


def upcoming(count: int, today: dt.date | None = None,
             gym_days: list[str] | None = None) -> list[dict[str, Any]]:
    """Die naechsten count Tage des Splits der Reihe nach — fuer den Wochenplan."""
    start = next_day(today, gym_days)
    days = start["days"]
    first = [d["key"] for d in days].index(start["day"]["key"])
    return [days[(first + i) % len(days)] for i in range(count)]


def overview(today: dt.date | None = None) -> dict[str, Any]:
    """Was im Reiter und im Prompt ueber den Aufbau steht."""
    nxt = next_day(today)
    return {
        "key": nxt["key"], "label": nxt["label"], "note": nxt["note"],
        "mode": nxt["mode"], "why": nxt["why"], "gym_days": nxt["gym_days"],
        "next": {"key": nxt["day"]["key"], "label": nxt["day"]["label"]},
        "because": nxt["because"],
        "rotation": [{"key": d["key"], "label": d["label"]} for d in nxt["days"]],
    }
