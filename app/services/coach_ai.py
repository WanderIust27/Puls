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
    # Merkposten und was erfahrungsgemaess hilft — beides gehoert in jeden
    # Prompt, sonst faengt der Coach jedes Gespraech wieder bei null an.
    try:
        from . import memory
        facts = memory.as_context()
        if facts:
            ctx["was_ich_ueber_dich_weiss"] = facts
    except Exception as e:
        log.debug("Merkposten nicht im Kontext: %s", e)
    # Entwicklung je Muskelgruppe und beim Laufen: Ohne die antwortet der Coach
    # auf "bin ich auf Kurs" mit allgemeinen Weisheiten statt mit deinen Zahlen.
    try:
        from . import trends as trends_svc
        tr = trends_svc.summary()
        top = [g for g in tr["muscles"]["groups"] if g["need"] >= 20][:3]
        if top:
            ctx["kraft_am_ehesten_dran"] = [
                f"{g['label']}: {'; '.join(g['reasons'][:2])}" for g in top]
        rising = [g["label"] for g in tr["muscles"]["groups"]
                  if g["direction"] == "steigt"]
        if rising:
            ctx["kraft_steigt_bei"] = rising
        run = tr["running"]
        if run.get("runs_recent"):
            ctx["laufen_vier_wochen"] = {
                "kilometer": run["km_recent"],
                "pro_woche": run["km_per_week"],
                "laengster_lauf_km": run["longest_recent"],
                "harte_laeufe": run["hard_runs"],
                "tempo_bei_gleichem_puls": (
                    f"{run['pace_gain_s']:+d} s/km gegenüber den vier Wochen davor"
                    if run.get("pace_gain_s") is not None else None),
            }
        if run.get("needs"):
            ctx["beim_laufen_fehlt"] = run["needs"]
        if tr["goal"].get("recognised"):
            ctx["dein_ziel"] = tr["goal"]["recognised"]
    except Exception as e:
        log.debug("Trends nicht im Kontext: %s", e)
    try:
        from . import boosters
        works = boosters.what_works()
        if works:
            ctx["hat_dir_bisher_geholfen"] = [
                f"{w['name']} ({w['gut']} von {w['bewertet']} Mal hilfreich)"
                for w in works]
    except Exception as e:
        log.debug("Erfahrungen nicht im Kontext: %s", e)
    try:
        from . import feedback
        pat = feedback.patterns()
        if pat.get("findings"):
            ctx["muster_aus_deinen_rueckmeldungen"] = [
                f["text"] for f in pat["findings"]]
    except Exception as e:
        log.debug("Muster nicht im Kontext: %s", e)
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
        "Schreibe eine kurze Tagesnachricht (3–5 Sätze): Nenne einmal den "
        "Zufriedenheitswert aus dem Feld 'score' und in einem Halbsatz, woran "
        "er gerade hängt. Würdige konkret, was "
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
        # Stand in der Frage etwas, das dauerhaft gilt? Dann behalten —
        # sichtbar in der Merkposten-Liste, nicht heimlich.
        try:
            from . import memory
            memory.extract(question, msg)
        except Exception as e:
            log.debug("Nichts gemerkt: %s", e)
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


def daily_readout() -> str:
    """Ein kurzer Kommentar zu Puls, Schlaf, Stress und Bereitschaft.

    Bewusst getrennt von der Tagesnachricht: hier geht es nur um die Werte der
    letzten Tage und was daraus fuer heute folgt — keine Motivation, kein
    Rueckblick auf das Training.
    """
    from . import boosters, metrics
    rec = metrics.recovery_series(10)
    latest, base = rec["latest"], rec["baselines"]
    if not latest:
        return ("Noch keine Erholungsdaten. Nach dem nächsten Garmin-Sync steht "
                "hier, was Puls, Schlaf und Stress über deinen Zustand sagen.")

    facts = {
        "heute": {k: latest.get(k) for k in
                  ("sleep_seconds", "sleep_score", "sleep_deep_s", "hrv_avg",
                   "hrv_status", "resting_hr", "stress_avg", "body_battery_max",
                   "body_battery_wake", "training_readiness", "respiration_avg")},
        "basislinien": base,
        "beobachtungen": [o["text"] for o in rec.get("observations", [])],
        "lage": boosters.situation()["reasons"],
    }
    prompt = (
        f"Erholungswerte des Athleten (JSON):\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
        "Schreibe drei bis vier Sätze dazu, wie sein Zustand heute ist und was "
        "daraus für den Tag folgt. Beziehe dich auf die konkreten Zahlen und "
        "immer auf die Basislinie — ein Ruhepuls von 46 sagt nichts, ohne dass "
        "man weiß, was sein Normalwert ist. Wenn die Werte unauffällig sind, "
        "sag das ruhig kurz. Keine Überschrift, keine Aufzählung, keine "
        "Motivationsfloskeln.")
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("readout", msg)
        return msg
    except OllamaUnavailable:
        parts = []
        if latest.get("sleep_seconds"):
            parts.append(f"{latest['sleep_seconds'] / 3600:.1f} h Schlaf")
        if latest.get("resting_hr"):
            parts.append(f"Ruhepuls {latest['resting_hr']:.0f}")
        if latest.get("hrv_avg"):
            parts.append(f"HRV {latest['hrv_avg']:.0f} ms")
        if latest.get("stress_avg"):
            parts.append(f"Stressmittel {latest['stress_avg']:.0f}")
        return ("Ohne laufendes Modell nur die Zahlen: " + ", ".join(parts)
                + "." if parts else "Noch keine Werte für heute.")


def mood_advice() -> str:
    """Konkrete Hilfe bei einem Tief — mit dem, was bei dir bisher half."""
    from . import boosters
    picked = boosters.suggest(3)
    ctx = picked["situation"]
    if not picked["boosters"]:
        return ("Deine Werte und Einträge sehen unauffällig aus — es gibt "
                "gerade nichts, wogegen ich etwas vorschlagen müsste.")
    works = boosters.what_works()
    prompt = (
        f"Lage: {', '.join(ctx['reasons']) or 'unauffällig'}\n"
        f"Vorgeschlagene Maßnahmen: "
        + "; ".join(f"{b['name']} — {b['text']}" for b in picked["boosters"])
        + (f"\nWas ihm erfahrungsgemäß hilft: "
           + ", ".join(f"{w['name']}" for w in works) if works else "")
        + "\n\nSchreibe zwei bis drei Sätze, die diese Maßnahmen zu einem "
          "Vorschlag für die nächsten Stunden verbinden. Sprich ihn direkt an, "
          "bleib nüchtern, keine Aufzählung — die Maßnahmen stehen ohnehin "
          "einzeln darunter.")
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("mood_advice", msg)
        return msg
    except OllamaUnavailable:
        return ("Ohne laufendes Modell: " +
                " ".join(b["name"] + "." for b in picked["boosters"]))


# Wie oft der Coach sich ueber den Tag meldet, und womit. Bewusst wenige
# feste Zeiten statt staendiger Meldungen — was jederzeit kommt, wird ignoriert.
CHECKIN_KINDS = {
    "morning": "Was heute ansteht",
    "midday": "Wie es läuft",
    "evening": "Was noch offen ist",
}


def checkin(kind: str = "midday") -> str:
    """Kurze Meldung im Tagesverlauf — mit Blick auf das, was noch offen ist.

    Der Unterschied zur Tagesnachricht: Hier geht es nicht um Einordnung,
    sondern um den Rest des Tages. Deshalb steht die Tagesliste im Mittelpunkt
    und nicht die Wochenbilanz.
    """
    from . import score as _score
    day = _score.today()
    open_items = day["open"]

    if not open_items:
        prompt = (
            f"Der Athlet hat heute alles erledigt: {day['total']} von "
            f"{day['total']} Punkten. Schreibe einen einzigen Satz Anerkennung. "
            "Keine Floskel, keine Aufzählung.")
    else:
        steps = next((i for i in day["items"] if i["key"] == "steps"), None)
        prompt = (
            f"Tageszeit: {CHECKIN_KINDS.get(kind, 'im Tagesverlauf')}.\n"
            f"Erledigt: {day['done']} von {day['total']}.\n"
            f"Noch offen: {', '.join(open_items)}.\n"
            + (f"Schritte: {steps['detail']} ({steps['progress']} % vom Ziel).\n"
               if steps and steps.get("detail") else "")
            + "\nSchreibe zwei Sätze: was jetzt noch machbar ist und warum es "
              "sich lohnt. Nenne höchstens zwei der offenen Punkte, den "
              "wichtigsten zuerst. Direkt ansprechen, nüchtern, keine "
              "Aufzählung, keine Floskeln wie 'du schaffst das'.")
    try:
        msg = generate(prompt, system=SYSTEM)
        _store(f"checkin_{kind}", msg)
        return msg
    except OllamaUnavailable:
        if not open_items:
            return "Heute ist alles erledigt."
        return f"Noch offen: {', '.join(open_items[:3])}."


def sleep_advice() -> str:
    """Was konkret den Schlaf verbessern wuerde — aus den eigenen Zahlen.

    Schlaf ist die Groesse mit dem groessten Hebel und der laengsten Leitung:
    Was heute Abend anders laeuft, sieht man morgen frueh. Deshalb bekommt er
    eine eigene Einschaetzung statt einer Zeile im Tagesbericht.
    """
    from . import metrics, stats
    rec = metrics.recovery_series(30)
    latest, base = rec["latest"], rec["baselines"]
    if not latest.get("sleep_seconds"):
        return ("Noch keine Schlafdaten. Sobald die Uhr eine Nacht aufgezeichnet "
                "hat, steht hier, woran es hakt.")

    # Was haengt bei DIR mit dem Schlaf zusammen? Das ist der Unterschied zu
    # allgemeinen Schlafregeln.
    related = []
    try:
        for key in ("sleep_hours", "sleep_score", "sleep_deep_hours"):
            found = stats.for_metric(key, days=180, limit=4)
            related += [f"{p['a_label']} ↔ {p['b_label']} (r={p['r']}, n={p['n']})"
                        for p in found["related"] if p.get("robust")]
    except Exception as e:
        log.debug("Zusammenhänge nicht verfuegbar: %s", e)

    facts = {
        "letzte_nacht": {
            "dauer_h": round(latest["sleep_seconds"] / 3600, 1),
            "score": latest.get("sleep_score"),
            "tief_min": round((latest.get("sleep_deep_s") or 0) / 60),
            "rem_min": round((latest.get("sleep_rem_s") or 0) / 60),
            "wach_min": round((latest.get("sleep_awake_s") or 0) / 60),
            "start": latest.get("sleep_start"), "ende": latest.get("sleep_end"),
            "atmung": latest.get("respiration_avg"),
        },
        "dein_schnitt": base.get("sleep_seconds"),
        "belegte_zusammenhaenge": related[:5],
    }
    prompt = (
        f"Schlafdaten (JSON):\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\n"
        "Schreibe drei bis vier Sätze: Was war an der letzten Nacht auffällig, "
        "und welche ZWEI konkreten Dinge würden bei ihm den größten Unterschied "
        "machen? Nutze die belegten Zusammenhänge, wenn welche dabei sind — die "
        "gelten für ihn, nicht allgemein. Tiefschlaf unter 60 Minuten oder "
        "Wachzeit über 40 Minuten sind erwähnenswert. Keine Aufzählung, keine "
        "allgemeinen Schlafhygiene-Listen.")
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("sleep", msg)
        return msg
    except OllamaUnavailable:
        n = facts["letzte_nacht"]
        return (f"{n['dauer_h']} h Schlaf, davon {n['tief_min']} min tief und "
                f"{n['rem_min']} min REM, {n['wach_min']} min wach.")


def stats_readout(days: int = 365, limit: int = 6) -> str:
    """Einschaetzung zu den staerksten Zusammenhaengen in deinen Daten."""
    from . import stats
    data = stats.matrix(days)
    robust = data["robust"][:limit]
    if not robust:
        return (f"Von {data['tested']} geprüften Paaren hält keines der "
                f"Mehrfachprüfung stand. Das heißt nicht, dass nichts "
                f"zusammenhängt — es heißt, dass die Datenmenge für eine "
                f"belastbare Aussage noch nicht reicht. "
                + (data["hint"] or ""))
    listing = "\n".join(
        f"- {p['a_label']} und {p['b_label']}: r={p['r']}, {p['direction']}, "
        f"{p['n']} gemeinsame Tage" for p in robust)

    # Die abgeleiteten Schwellen sind im Code gerechnet. Sie gehoeren in den
    # Prompt, damit das Modell konkret werden kann, ohne Zahlen zu erfinden.
    try:
        advice = stats.recommendations(days, limit=5)["recommendations"]
    except Exception as e:                                  # noqa: BLE001
        log.debug("Empfehlungen nicht verfuegbar: %s", e)
        advice = []
    derived = "\n".join(f"- {r['text']}" for r in advice)

    prompt = (
        f"Aus den Daten eines Sportlers wurden {data['tested']} Paare von "
        f"Messwerten geprüft. Diese halten der Korrektur für Mehrfachprüfung "
        f"stand:\n{listing}\n\n"
        + (f"Daraus wurden bereits konkrete Schwellen gerechnet — der "
           f"Vergleich seiner besten mit seinen schlechtesten Tagen:\n"
           f"{derived}\n\n" if derived else "")
        + "Schreibe vier bis sechs Sätze: Was sagen diese Zusammenhänge, und was "
        "folgt praktisch daraus? Nenne dabei die Schwellen und Zahlen aus der "
        "Liste wörtlich — rechne nichts nach und erfinde keine. Weise "
        "ausdrücklich darauf hin, wo die Richtung unklar ist — ob also A auf B "
        "wirkt oder umgekehrt. Keine Aufzählung.")
    try:
        msg = generate(prompt, system=SYSTEM)
        _store("stats", msg)
        return msg
    except OllamaUnavailable:
        return ("Ohne laufendes Modell nur das Gerechnete:\n"
                + (derived or listing))

