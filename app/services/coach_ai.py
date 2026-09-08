"""Die Coach-Logik: Prompts für das lokale Modell + Fallbacks ohne KI."""
from __future__ import annotations

import json
import logging
import random
from typing import Any

from ..db import get_db
from . import metrics
from .ollama_client import OllamaUnavailable, generate, generate_json

log = logging.getLogger("puls.coach")

SYSTEM = (
    "Du bist PULS, ein persönlicher Trainingscoach. Du sprichst Deutsch, per Du, "
    "direkt und motivierend, aber ohne Floskeln und ohne Übertreibung. "
    "Deine Empfehlungen stützt du auf etablierte Trainingswissenschaft "
    "(progressive Überlastung, Superkompensation, ausreichend Protein und Schlaf, "
    "sinnvolles Verhältnis von Belastung und Erholung). Wenn du eine Empfehlung "
    "gibst, begründe sie kurz. Du bist kein Arzt und sagst das bei "
    "gesundheitlichen Themen dazu. Halte Antworten kompakt: wenige Absätze, "
    "keine langen Listen.\n\n"
    "Der Athlet trainiert nach einer festen Wochenstruktur: morgens locker laufen, "
    "dreimal pro Woche abends Gym (Kettlebell-Auftakt, dann Maschinen, "
    "Klimmzug-Arbeit, Dehnen zum Abschluss), abends kurzes Yoga. Zwei erklärte "
    "Hauptziele: 10 km unter 60 Minuten und mehr Klimmzüge. Er bevorzugt "
    "Maschinen gegenüber freien Gewichten.\n\n"
    "WICHTIG: Die konkreten Gewichte und Wiederholungen rechnet das System selbst "
    "aus (doppelte Progression). Erfinde keine eigenen Zahlen und widersprich den "
    "Vorgaben aus den Daten nicht — erkläre sie lieber."
)

GOAL_LABELS = {
    "muscle": "Muskelaufbau/Kraft",
    "endurance": "Ausdauer verbessern",
    "general": "allgemeine Fitness und Routine",
    "weight_gain": "Gewichtszunahme (Aufbau)",
    "weight_loss": "Gewichtsabnahme",
}

FALLBACK_MOTIVATION = [
    "Die KI-Einheit ist gerade nicht erreichbar — aber du weißt selbst, was zu tun ist: dranbleiben.",
    "Ollama antwortet gerade nicht. Dein Plan gilt trotzdem: heute zählt jede Einheit.",
    "Kein KI-Tipp verfügbar — Konstanz schlägt Perfektion, mach einfach weiter.",
]


def _context_block() -> str:
    ctx = metrics.coach_context()
    ctx["goals"] = [GOAL_LABELS.get(g, g) for g in ctx.get("goals", [])]
    return json.dumps(ctx, ensure_ascii=False, default=str)


def _store(kind: str, content: str, question: str | None = None) -> None:
    with get_db() as db:
        db.execute(
            "INSERT INTO coach_messages(kind, question, content) VALUES(?,?,?)",
            (kind, question, content),
        )


def daily_message() -> str:
    prompt = (
        "Hier sind die aktuellen Trainingsdaten des Athleten als JSON:\n"
        f"{_context_block()}\n\n"
        "Schreibe eine kurze Tagesnachricht (3–5 Sätze): Würdige konkret, was "
        "zuletzt gut lief (nutze echte Zahlen aus den Daten), sag, was heute "
        "sinnvoll ist (Training oder Erholung — beachte ACWR, Schlaf, HRV und "
        "Training Readiness, falls vorhanden), und schließe motivierend. "
        "Keine Überschrift, keine Aufzählung."
    )
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("daily", msg)
        return msg
    except OllamaUnavailable:
        return random.choice(FALLBACK_MOTIVATION)


def answer_question(question: str) -> str:
    prompt = (
        f"Trainingsdaten des Athleten (JSON):\n{_context_block()}\n\n"
        f"Frage des Athleten: {question}\n\n"
        "Antworte hilfreich und konkret auf Basis der Daten. Wenn die Daten für "
        "eine fundierte Antwort nicht reichen, sag ehrlich, was fehlt."
    )
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("answer", msg, question)
        return msg
    except OllamaUnavailable as e:
        return f"Die lokale KI ist gerade nicht erreichbar ({e}). Versuch es gleich nochmal."


def rest_recommendation() -> str:
    prompt = (
        f"Trainingsdaten (JSON):\n{_context_block()}\n\n"
        "Beurteile Belastung und Erholung: Ist heute ein Trainingstag, ein "
        "lockerer Tag oder ein Ruhetag angebracht? Nutze ACWR (unter 0.8 = "
        "Luft nach oben, 0.8–1.3 = grüner Bereich, über 1.5 = erhöhtes Risiko), "
        "Schlaf, HRV-Status und Training Readiness, soweit vorhanden. Gib eine "
        "klare Empfehlung mit kurzer Begründung und nenne konkrete Pausenzeiten "
        "zwischen den nächsten harten Einheiten (in Stunden/Tagen)."
    )
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("rest", msg)
        return msg
    except OllamaUnavailable:
        acwr = metrics.acwr()
        if acwr is None:
            return "Noch zu wenig Daten für eine Belastungsanalyse. Faustregel: nach einer harten Einheit 48 h für dieselbe Muskelgruppe."
        if acwr > 1.5:
            return f"Deine akute Last ist deutlich über dem 4-Wochen-Schnitt (ACWR {acwr}). Nimm 1–2 ruhige Tage."
        if acwr < 0.8:
            return f"Du bist unter deinem gewohnten Pensum (ACWR {acwr}) — Luft für eine ordentliche Einheit."
        return f"Belastung im grünen Bereich (ACWR {acwr}). Normal weitertrainieren, harte Einheiten mit ~48 h Abstand."


def nutrition_advice() -> str:
    prompt = (
        f"Trainingsdaten (JSON):\n{_context_block()}\n\n"
        "Gib eine konkrete Ernährungsempfehlung für die nächsten Tage. Ziel des "
        "Athleten beachten (insbesondere Gewichtszunahme/Muskelaufbau: moderater "
        "Kalorienüberschuss von ca. 300–500 kcal, 1.6–2.2 g Protein pro kg "
        "Körpergewicht). Vergleiche mit den letzten getrackten Tagen, falls "
        "Einträge vorhanden sind, und nenne konkrete Zahlen und 2–3 praktische "
        "Lebensmittel-Beispiele."
    )
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("nutrition", msg)
        return msg
    except OllamaUnavailable as e:
        return f"Die lokale KI ist gerade nicht erreichbar ({e})."


WORKOUT_SCHEMA_HINT = """
Antworte NUR mit JSON in exakt diesem Schema:
{
  "name": "kurzer Workout-Name",
  "sport": "running|strength|cardio|mobility|hiit",
  "description": "1-2 Sätze, warum dieses Workout jetzt passt",
  "steps": [
    {"type": "warmup|work|recovery|rest|cooldown", "name": "Übung/Abschnitt",
     "duration_s": 600, "distance_m": null, "reps": null,
     "pace_min_km": ["5:50","5:30"], "hr_zone": null, "weight_kg": null,
     "notes": "optional"},
    {"type": "repeat", "count": 4, "steps": [ ...gleiches Step-Format... ]}
  ]
}
Regeln: Pro Step genau EINE Endbedingung (duration_s ODER distance_m ODER reps),
übrige auf null. pace_min_km nur bei Läufen als ["langsamer","schneller"].
Bei Kraft: pro Übung ein repeat-Block (count = Sätze) mit einem work-Step
(reps, weight_kg wenn sinnvoll) und einem rest-Step (Pause in Sekunden,
kurz begründet in notes). Deutsche Übungsnamen wie "Kniebeuge", "Bankdrücken",
"Kreuzheben", "Klimmzüge" verwenden.
"""


def generate_workout(wish: str | None = None) -> dict[str, Any]:
    prompt = (
        f"Trainingsdaten (JSON):\n{_context_block()}\n\n"
        + (f"Wunsch des Athleten: {wish}\n\n" if wish else "")
        + "Erstelle das nächste sinnvolle Workout unter Berücksichtigung von "
          "Zielen, letzter Belastung und Erholung.\n" + WORKOUT_SCHEMA_HINT
    )
    data = generate_json(prompt, system=SYSTEM)
    if "steps" not in data or "name" not in data:
        raise OllamaUnavailable(f"Unerwartetes Workout-Format: {json.dumps(data)[:200]}")
    data.setdefault("sport", "strength")
    return data


def generate_week_plan(wish: str | None = None) -> list[dict[str, Any]]:
    prompt = (
        f"Trainingsdaten (JSON):\n{_context_block()}\n\n"
        + (f"Wunsch des Athleten: {wish}\n\n" if wish else "")
        + "Erstelle einen Wochenplan mit 3-5 Workouts, passend zu den Zielen "
          "(Mischung aus Kraft, Laufen und Mobilität) und zur bisherigen "
          "Belastung. Verteile die Einheiten sinnvoll über die Woche "
          "(harte Einheiten nicht an aufeinanderfolgenden Tagen).\n"
          "Antworte NUR mit JSON: {\"workouts\": [{\"weekday\": \"Mo|Di|Mi|Do|Fr|Sa|So\", "
          "...restliches Workout-Schema wie unten...}]}\n" + WORKOUT_SCHEMA_HINT
    )
    data = generate_json(prompt, system=SYSTEM, temperature=0.5)
    workouts = data.get("workouts")
    if not isinstance(workouts, list) or not workouts:
        raise OllamaUnavailable(f"Unerwartetes Plan-Format: {json.dumps(data)[:200]}")
    return workouts


RESEARCH_TOPICS = [
    "optimale Satzpausen im Hypertrophietraining",
    "Protein-Timing und Gesamtproteinzufuhr",
    "Zone-2-Training und aerobe Basis",
    "Schlaf und Muskelaufbau",
    "Progressive Überlastung richtig steuern",
    "Kreatin: Wirkung und Einnahme",
    "Krafttraining für Läufer",
    "HRV als Erholungsmarker",
    "Trainingsvolumen vs. Intensität beim Muskelaufbau",
    "Deload-Wochen: wann und wie",
    "Kalorienüberschuss beim Lean Bulk",
    "Mobilität und Verletzungsprophylaxe",
    "Nüchterntraining: Mythos und Fakten",
    "Muskelkater: was er bedeutet und was nicht",
    "Intervalltraining: VO2max effektiv steigern",
]


def research_tip(topic: str | None = None) -> str:
    topic = topic or random.choice(RESEARCH_TOPICS)
    prompt = (
        f"Schreibe ein kurzes Wissens-Häppchen (4–6 Sätze) zum Thema "
        f"\"{topic}\" für einen ambitionierten Freizeitsportler. Gib den "
        "aktuellen Stand der Sportwissenschaft nüchtern und korrekt wieder, "
        "nenne konkrete Zahlen/Spannen, wo etabliert, und schließe mit einem "
        "umsetzbaren Praxistipp. Keine Quellenangaben erfinden."
    )
    try:
        tip = generate(prompt, system=SYSTEM, temperature=0.6)
        with get_db() as db:
            db.execute("INSERT INTO research_tips(topic, content) VALUES(?,?)",
                       (topic, tip))
        return tip
    except OllamaUnavailable as e:
        return f"Die lokale KI ist gerade nicht erreichbar ({e})."
