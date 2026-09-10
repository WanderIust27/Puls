"""Eine Einheit aus einem Satz: „60 Minuten zuhause für den Handstand".

Die Arbeitsteilung ist dieselbe wie überall hier. Das Modell liest aus dem Satz
Dauer, Ort, Muskelgruppen und ein etwaiges Ziel heraus — mehr nicht. Welche
Übungen daraus werden, entscheidet der Code aus der Bibliothek. Ein Modell,
das sich Übungen ausdenkt, erfindet auch Gewichte, und die stehen dann in
deinem Plan.

Ohne laufendes Modell wird der Satz selbst zerlegt. Das ist gröber, aber die
Fälle, die man wirklich tippt („90 min Ganzkörper", „30 Minuten Bauch zuhause"),
kommen auch so an.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import exercises as ex_lib

log = logging.getLogger("puls.request")

# Muskelgruppen und wie man sie auf Deutsch nennt.
GROUP_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("bauch", "rumpf", "core", "sixpack", "bauchmuskel"), "core"),
    (("rücken", "ruecken", "latissimus", "lat", "rückenmuskulatur"), "back"),
    (("brust", "chest", "pecs"), "chest"),
    (("schulter", "deltoid", "delta"), "shoulders"),
    (("arme", "arm", "bizeps", "trizeps", "unterarm"), "arms"),
    (("bein", "beine", "quadrizeps", "waden", "gesäß", "gesaess", "po"), "legs"),
]

# Ziele, die auf eine Fertigkeit hinarbeiten. Sie legen Gruppen UND bestimmte
# Uebungen fest — ein Handstandprogramm ohne Handstand waere keines.
SKILL_GOALS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (("handstand", "hand stand", "handstuetz"),
     {"label": "Handstand",
      "groups": ["shoulders", "core", "arms"],
      "must": ["Handgelenke vorbereiten", "Handstand an der Wand",
               "Pike-Liegestütz", "Hohlkörper halten", "Krähe"],
      "note": "Schultern über Kopf, ein Rumpf, der die Linie hält, und "
              "Handgelenke, die das aushalten. Genau in dieser Reihenfolge."}),
    (("klimmzug", "klimmzüge", "pull up", "pull-up", "pullup"),
     {"label": "Klimmzüge",
      "groups": ["back", "arms", "core"],
      "must": ["Negative Klimmzüge", "Kurzhantel-Rudern einarmig",
               "Hohlkörper halten"],
      "note": "Der Weg zum ersten Klimmzug führt über das langsame Ablassen "
              "und über Rudern — nicht über mehr Versuche."}),
    (("liegestütz", "liegestuetz", "push up", "push-up"),
     {"label": "Liegestütze",
      "groups": ["chest", "shoulders", "arms", "core"],
      "must": ["Liegestütz", "Pike-Liegestütz", "Unterarmstütz"],
      "note": "Drückkraft und ein fester Rumpf — ohne den zweiten sackt der "
              "erste in der Mitte durch."}),
    (("planke", "plank", "rumpfstabilität", "stabilität", "stabilitaet"),
     {"label": "Rumpfstabilität",
      "groups": ["core", "back"],
      "must": ["Unterarmstütz", "Seitstütz", "Hohlkörper halten",
               "Vierfüßlerstand diagonal"],
      "note": "Halten statt bewegen. Der Rumpf lernt hier, Kraft zu übertragen "
              "statt sie zu schlucken."}),
]

SPLIT_WORDS: list[tuple[tuple[str, ...], list[str]]] = [
    (("push", "drücken", "druecken"), ["chest", "shoulders", "arms"]),
    (("pull", "ziehen"), ["back", "arms"]),
    (("oberkörper", "oberkoerper", "upper"), ["chest", "back", "shoulders", "arms"]),
    (("unterkörper", "unterkoerper", "lower"), ["legs", "core"]),
    (("ganzkörper", "ganzkoerper", "full body", "fullbody"),
     ["legs", "chest", "back", "shoulders", "arms", "core"]),
]

HOME_WORDS = ("zuhause", "zu hause", "daheim", "wohnzimmer", "matte", "ohne geräte",
              "ohne geraete", "home")
GYM_WORDS = ("gym", "studio", "fitnessstudio", "maschinen", "geräte", "geraete")


def _norm(text: str) -> str:
    return (text or "").lower().replace("ß", "ss")


def parse(text: str) -> dict[str, Any]:
    """Aus einem Satz Dauer, Ort, Gruppen und Ziel lesen."""
    guess = _plain_parse(text)
    model = _model_parse(text)
    if model:
        # Das Modell ergaenzt, es ueberschreibt nicht: Was im Satz eindeutig
        # dasteht (eine Zahl mit "min"), ist verlaesslicher als eine Schaetzung.
        for key in ("minutes", "place"):
            if guess.get(key) is None and model.get(key) is not None:
                guess[key] = model[key]
        extra = [g for g in (model.get("groups") or [])
                 if g in ex_lib.MUSCLE_LABELS and g not in guess["groups"]]
        guess["groups"] += extra
        if not guess["goal"] and model.get("goal"):
            guess["goal"] = _match_goal(str(model["goal"]))
    guess["minutes"] = guess["minutes"] or 45
    guess["place"] = guess["place"] or "gym"
    if guess["goal"]:
        for g in guess["goal"]["groups"]:
            if g not in guess["groups"]:
                guess["groups"].append(g)
    if not guess["groups"]:
        guess["groups"] = (["core", "back"] if guess["place"] == "home"
                           else list(ex_lib.MUSCLE_LABELS)[:6])
    guess["groups"] = [g for g in guess["groups"] if g in ex_lib.MUSCLE_LABELS]
    return guess


def _match_goal(text: str) -> dict[str, Any] | None:
    low = _norm(text)
    for words, goal in SKILL_GOALS:
        if any(w in low for w in words):
            return goal
    return None


def _plain_parse(text: str) -> dict[str, Any]:
    low = _norm(text)

    minutes = None
    m = re.search(r"(\d{2,3})\s*(?:min|minuten|minütig|minuetig)?", low)
    if m and 10 <= int(m.group(1)) <= 180:
        minutes = int(m.group(1))
    stunde = re.search(r"(?:eine|1)\s*stunde", low)
    if stunde and minutes is None:
        minutes = 60

    place = None
    if any(w in low for w in HOME_WORDS):
        place = "home"
    elif any(w in low for w in GYM_WORDS):
        place = "gym"

    groups: list[str] = []
    for words, split_groups in SPLIT_WORDS:
        if any(w in low for w in words):
            groups += [g for g in split_groups if g not in groups]
    for words, key in GROUP_WORDS:
        if any(w in low for w in words) and key not in groups:
            groups.append(key)

    return {"text": text.strip(), "minutes": minutes, "place": place,
            "groups": groups, "goal": _match_goal(low)}


def _model_parse(text: str) -> dict[str, Any] | None:
    """Das Modell den Satz lesen lassen — Parameter ja, Übungen nein."""
    if not text or len(text.strip()) < 6:
        return None
    try:
        from .ollama_client import generate_json
        data = generate_json(
            prompt=(
                "Lies aus dem folgenden Trainingswunsch die Eckdaten heraus. "
                "Antworte als JSON-Objekt mit den Schlüsseln \"minutes\" (Zahl, "
                "Dauer in Minuten), \"place\" (\"home\" oder \"gym\"), "
                "\"groups\" (Liste aus: legs, chest, back, shoulders, arms, "
                "core) und \"goal\" (eine Fertigkeit wie \"Handstand\" oder "
                "\"Klimmzug\", sonst null). Nenne KEINE Übungen — die werden "
                "woanders ausgewählt. Erfinde nichts, was nicht dasteht.\n\n"
                f"Wunsch: {text.strip()[:400]}"),
            system="Du extrahierst Daten. Du antwortest ausschliesslich mit JSON.")
        return data if isinstance(data, dict) else None
    except Exception as e:                                      # noqa: BLE001
        log.debug("Wunsch ohne Modell gelesen: %s", e)
        return None


def build(text: str) -> dict[str, Any]:
    """Den Wunsch lesen und die passende Einheit bauen."""
    from . import planner

    want = parse(text)
    goal = want["goal"]

    if want["place"] == "home":
        workout = planner.build_home_session(want["minutes"], want["groups"],
                                             with_dumbbell=True,
                                             must=(goal or {}).get("must"))
    else:
        workout = planner.build_gym_session(want["minutes"],
                                            emphasis=want["groups"][:3])

    labels = [ex_lib.MUSCLE_LABELS.get(g, g) for g in want["groups"]]
    workout["request"] = {
        "text": want["text"], "minutes": want["minutes"], "place": want["place"],
        "groups": want["groups"], "group_labels": labels,
        "goal": (goal or {}).get("label"),
    }
    workout["read_as"] = (
        f"{want['minutes']} Minuten "
        + ("zuhause" if want["place"] == "home" else "im Studio")
        + (f", auf {goal['label']} hin" if goal else "")
        + f" — {', '.join(labels)}.")
    if goal:
        workout["goal_note"] = goal["note"]
        workout["name"] = f"{goal['label']} {workout.get('minutes', want['minutes'])} min"
    return workout
