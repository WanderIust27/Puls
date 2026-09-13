"""Körperwerte: was sich verändert, wie schnell, und wohin es gehen soll.

Die Waage liefert nach jeder Messung ein halbes Dutzend Zahlen. Einzeln sagt
keine davon etwas: 17,4 % Körperfett ist erst dann eine Information, wenn
danebensteht, was es vorigen Monat war und was es für einen 24-jährigen Mann
bedeutet. Und die wichtigste Frage beim Aufbauen beantwortet keine der Zahlen
für sich — nämlich ob das, was dazugekommen ist, Muskel war oder Fett.

Deshalb rechnet dieses Modul drei Dinge:

* **Die Werte mit Verlauf** — jeder gegen seinen eigenen Stand von vor vier
  und zwölf Wochen, mit einem Bereich, der ihn einordnet.
* **Die Aufteilung der Veränderung** — von den Kilos, die dazugekommen oder
  weggegangen sind: wie viel davon war Fett, wie viel fettfreie Masse. Das ist
  die Zahl, an der sich eine Aufbauphase misst, nicht das Gewicht.
* **Das Zielgewicht** — nicht aus einer Tabelle, sondern aus deiner
  Magermasse: Bei dem, was du an fettfreier Masse hast, und einem Körperfett-
  anteil im Zielbereich kommst du auf dieses Gewicht.

Alles davon sind Schätzungen einer Impedanzwaage. Sie sind im *Verlauf*
brauchbar und im Einzelwert nicht — dasselbe Gerät, dieselbe Uhrzeit, dieselbe
Richtung. Das steht hier nicht als Ausrede, sondern als Gebrauchsanweisung:
Auf die Nachkommastelle eines einzelnen Tages zu schauen ist vergeudete Zeit.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts
from . import body

log = logging.getLogger("puls.body_coach")

WEEKS = 12                # so weit zurueck geht der Verlauf
RECENT_WEEKS = 4          # "zuletzt" heisst: die letzten vier Wochen
MIN_POINTS = 3            # darunter ist eine Rate geraten


def _de(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _signed(value: float, digits: int = 1) -> str:
    return ("+" if value > 0 else "−" if value < 0 else "±") + _de(abs(value), digits)


# ------------------------------------------------------------ Die Kennzahlen

# Referenzbereiche fuer Maenner und Frauen. Koerperfett nach den Bereichen des
# American Council on Exercise; Wasseranteil nach den ueblichen Angaben fuer
# Erwachsene; Viszeralfett ist der dimensionslose Index der Waage, bei dem der
# Hersteller ab 10 warnt. Absichtlich grob: Es geht darum, ob ein Wert im
# Rahmen liegt, nicht um die zweite Nachkommastelle.
RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "body_fat_pct": {"male": (10.0, 18.0), "female": (18.0, 26.0)},
    "water_pct": {"male": (50.0, 65.0), "female": (45.0, 60.0)},
    "visceral_fat": {"male": (1.0, 9.0), "female": (1.0, 9.0)},
}

METRICS: list[dict[str, Any]] = [
    dict(key="body_fat_pct", label="Körperfett", unit="%", digits=1, direction=-1,
         what="Wie viel deines Gewichts Fettgewebe ist.",
         why="Beim Aufbauen die Gegenprobe zum Gewicht: Steigen beide "
             "gleichmäßig, war der Überschuss zu groß. Steigt das Gewicht und "
             "der Anteil bleibt, ist es das, was du wolltest."),
    dict(key="muscle_kg", label="Muskelmasse", unit="kg", digits=1, direction=1,
         what="Die geschätzte Muskelmasse in Kilogramm.",
         why="Die Zahl, die beim Krafttraining steigen soll. Sie bewegt sich "
             "langsam — ein Kilo im Quartal ist für Fortgeschrittene schon "
             "viel, und alles, was in einer Woche passiert, ist Wasser."),
    dict(key="water_pct", label="Wasseranteil", unit="%", digits=1, direction=1,
         what="Anteil Körperwasser am Gewicht.",
         why="Schwankt mit Salz, Kohlenhydraten und Training und erklärt die "
             "meisten Tagessprünge auf der Waage. Als Trend über Wochen "
             "trotzdem ein guter Gegenwert: Er fällt, wenn der Fettanteil "
             "steigt."),
    dict(key="visceral_fat", label="Viszeralfett", unit="", digits=1, direction=-1,
         what="Kennzahl für das Fett um die Organe, nicht unter der Haut.",
         why="Der einzige Fettwert, der gesundheitlich wirklich zählt. Bis 9 "
             "gilt als normal, darüber lohnt sich Gegensteuern — und er "
             "reagiert schneller auf Training als der Gesamtanteil."),
    dict(key="bone_kg", label="Knochenmasse", unit="kg", digits=2, direction=0,
         what="Geschätzte Knochenmasse.",
         why="Ändert sich beim Erwachsenen praktisch nicht. Steht hier als "
             "Kontrollwert: Springt sie, hat die Waage schlecht gemessen — "
             "dann taugen an dem Tag auch die anderen Werte nichts."),
]


def _sex() -> str:
    value = (get_setting("body_sex", "male") or "male").strip().lower()
    return "female" if value.startswith(("f", "w")) else "male"


def _height_m() -> float | None:
    try:
        cm = float(get_setting("body_height_cm", "0") or 0)
    except (TypeError, ValueError):
        return None
    return cm / 100.0 if 120 <= cm <= 230 else None


def _read(today: dt.date) -> list[dict[str, Any]]:
    """Alle Messungen des Zeitraums, in einem Zug."""
    floor = (today - dt.timedelta(weeks=WEEKS)).isoformat()
    with get_db() as db:
        return rows_to_dicts(db.execute(
            """SELECT day, measured_at, weight_kg, weight_adj_kg, in_window,
                      body_fat_pct, muscle_kg, water_pct, bone_kg, lbm_kg,
                      visceral_fat
               FROM body_metrics
               WHERE day >= ? AND day <= ?
               ORDER BY day""", (floor, today.isoformat())).fetchall())


def _weekly(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """Wochenmittel, auf den Montag datiert.

    Einzelmessungen schwanken um mehr, als sich in einer Woche aendern kann —
    eine Linie aus Rohwerten zeigt Rauschen und nennt es Verlauf.
    """
    buckets: dict[str, list[float]] = {}
    for r in rows:
        value = r.get(field)
        if value is None:
            continue
        try:
            d = dt.date.fromisoformat(r["day"])
        except (ValueError, TypeError):
            continue
        monday = (d - dt.timedelta(days=d.weekday())).isoformat()
        buckets.setdefault(monday, []).append(float(value))
    return [{"day": k, "value": round(sum(v) / len(v), 2), "n": len(v)}
            for k, v in sorted(buckets.items())]


def _change(weeks: list[dict[str, Any]], back: int) -> float | None:
    """Veraenderung gegenueber dem Wochenwert vor `back` Wochen."""
    if len(weeks) < 2:
        return None
    target = weeks[-1]
    try:
        end = dt.date.fromisoformat(target["day"])
    except ValueError:
        return None
    floor = (end - dt.timedelta(weeks=back)).isoformat()
    earlier = [w for w in weeks[:-1] if w["day"] <= floor]
    base = earlier[-1] if earlier else weeks[0]
    if base["day"] == target["day"]:
        return None
    return round(target["value"] - base["value"], 2)


def _band(value: float, key: str, sex: str) -> str:
    span = RANGES.get(key, {}).get(sex)
    if not span:
        return "info"
    low, high = span
    if low <= value <= high:
        return "good"
    # Ein Stueck ausserhalb ist noch kein Befund.
    slack = (high - low) * 0.25
    return "ok" if low - slack <= value <= high + slack else "warn"


def composition(today: dt.date | None = None,
                rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Jeder Körperwert mit Verlauf, Einordnung und einem Satz dazu."""
    today = today or dt.date.today()
    rows = _read(today) if rows is None else rows
    sex = _sex()
    goal = _goal_direction()
    out: list[dict[str, Any]] = []
    for spec in METRICS:
        weeks = _weekly(rows, spec["key"])
        if not weeks:
            continue
        now = weeks[-1]["value"]
        band = _band(now, spec["key"], sex)
        span = RANGES.get(spec["key"], {}).get(sex)
        out.append({
            "key": spec["key"], "label": spec["label"], "unit": spec["unit"],
            "value": round(now, spec["digits"]),
            "text": _de(now, spec["digits"]),
            "change_4w": _change(weeks, RECENT_WEEKS),
            "change_12w": _change(weeks, WEEKS),
            "band": band,
            "reference": (f"üblich {_de(span[0], 0)}–{_de(span[1], 0)}"
                          f"{(' ' + spec['unit']) if spec['unit'] else ''}"
                          if span else None),
            "points": weeks,
            "what": spec["what"], "why": spec["why"],
            "sentence": _metric_sentence(spec, now, _change(weeks, RECENT_WEEKS),
                                         goal),
        })
    return out


# Waehrend einer Aufbauphase steigt der Fettanteil fast immer ein wenig mit.
# Das als "falsche Richtung" zu melden, waere Panikmache — die Frage, auf die
# es ankommt, beantwortet ohnehin die Aufteilung weiter unten. Erst ab diesem
# Zuwachs in vier Wochen ist es wirklich zu viel.
FAT_TOLERANCE_GAIN = 0.8


def _metric_sentence(spec: dict[str, Any], now: float, change: float | None,
                     goal: str = "hold") -> str:
    # Bei Prozentwerten sind es Prozentpunkte. "0,2 % mehr Körperfett" hiesse
    # ein Fuenftel Prozent von 16,6 — und das ist etwas anderes.
    unit = "Prozentpunkte" if spec["unit"] == "%" else spec["unit"]
    head = f"{_de(now, spec['digits'])} {spec['unit']}".strip()
    if change is None:
        return f"{head} — noch kein Vergleichswert aus den Wochen davor."
    if abs(change) < 10 ** -spec["digits"]:
        return f"{head}, unverändert gegenüber den Wochen davor."
    way = "mehr" if change > 0 else "weniger"
    good = spec["direction"] and (change > 0) == (spec["direction"] > 0)
    tail = ("" if not spec["direction"] else
            " Das ist die Richtung, die du willst." if good else
            " Das ist die andere Richtung.")
    if (spec["key"] == "body_fat_pct" and goal == "gain" and not good
            and change <= FAT_TOLERANCE_GAIN):
        tail = (" Beim Aufbauen geht ein Teil davon immer mit — in dieser "
                "Größenordnung ist das normal.")
    body_text = (f"{head}, {_de(abs(change), spec['digits'])} {unit} {way} "
                 f"als vor vier Wochen.")
    return " ".join(body_text.split()) + tail


# ----------------------------------------- Was war Muskel, was war Fett?

# Unter dieser Veraenderung lohnt die Aufteilung nicht: Bei 300 g Unterschied
# steckt mehr Messfehler drin als Aussage.
MIN_SPLIT_KG = 0.6


def partition(today: dt.date | None = None,
              rows: list[dict[str, Any]] | None = None,
              weeks: int = WEEKS) -> dict[str, Any] | None:
    """Von der Gewichtsveraenderung: wie viel war Fett, wie viel fettfreie Masse?

    Das ist die eigentliche Frage einer Aufbauphase. Zwei Kilo mehr auf der
    Waage sind ein Erfolg oder ein Versehen, je nachdem, was davon Muskel war
    — und das Gewicht allein sagt es nicht.

    Gerechnet wird ueber die Fettmasse, nicht ueber die Muskelmasse der Waage:
    Fettmasse ist Gewicht mal Fettanteil, also ein Produkt aus zwei Werten,
    die beide direkt gemessen beziehungsweise geschaetzt werden. Die
    fettfreie Masse ist der Rest — sie enthaelt dann auch Wasser, und genau
    deshalb steht der Hinweis dabei.
    """
    today = today or dt.date.today()
    rows = _read(today) if rows is None else rows
    usable = [r for r in rows
              if r.get("weight_kg") and r.get("body_fat_pct") is not None]
    if len(usable) < MIN_POINTS:
        return None
    for r in usable:
        r["fat_kg"] = r["weight_kg"] * r["body_fat_pct"] / 100.0
        r["lean_kg"] = r["weight_kg"] - r["fat_kg"]

    w_weight = _weekly(usable, "weight_kg")
    w_fat = _weekly(usable, "fat_kg")
    w_lean = _weekly(usable, "lean_kg")
    if len(w_weight) < 2:
        return None

    d_weight = round(w_weight[-1]["value"] - w_weight[0]["value"], 2)
    d_fat = round(w_fat[-1]["value"] - w_fat[0]["value"], 2)
    d_lean = round(w_lean[-1]["value"] - w_lean[0]["value"], 2)
    span_weeks = len(w_weight)

    return {
        "weeks": span_weeks,
        "from_day": w_weight[0]["day"], "to_day": w_weight[-1]["day"],
        "weight_kg": d_weight, "fat_kg": d_fat, "lean_kg": d_lean,
        "lean_share": (round(d_lean / d_weight * 100)
                       if abs(d_weight) >= MIN_SPLIT_KG else None),
        "per_week_lean": round(d_lean / span_weeks, 2) if span_weeks else None,
        "per_week_fat": round(d_fat / span_weeks, 2) if span_weeks else None,
        "points": [{"day": w["day"], "fat": w_fat[i]["value"],
                    "lean": w_lean[i]["value"]}
                   for i, w in enumerate(w_weight) if i < len(w_fat)],
        "sentence": _partition_sentence(d_weight, d_fat, d_lean, span_weeks),
        "note": ("Fettmasse ist Gewicht mal Fettanteil; die fettfreie Masse ist "
                 "der Rest — Muskel, Wasser, Knochen. Ein Teil der Bewegung "
                 "darin ist deshalb Wasser und kein Muskel. Über zwölf Wochen "
                 "mittelt sich das weitgehend heraus."),
    }


def _partition_sentence(d_weight: float, d_fat: float, d_lean: float,
                        weeks: int) -> str:
    if abs(d_weight) < MIN_SPLIT_KG:
        return (f"Das Gewicht steht seit {weeks} Wochen praktisch still "
                f"({_signed(d_weight, 2)} kg). Innen hat sich trotzdem etwas "
                f"bewegt: {_signed(d_lean, 2)} kg fettfreie Masse bei "
                f"{_signed(d_fat, 2)} kg Fett.")
    direction = "dazugekommen" if d_weight > 0 else "weggegangen"
    head = (f"{_de(abs(d_weight), 2)} kg in {weeks} Wochen {direction} — "
            f"davon {_signed(d_lean, 2)} kg fettfreie Masse und "
            f"{_signed(d_fat, 2)} kg Fett.")
    if d_weight > 0:
        if d_lean >= abs(d_fat) * 1.5:
            return head + " So soll ein Aufbau aussehen."
        if d_lean <= 0:
            return (head + " Das ist reiner Fettaufbau. Der Überschuss ist zu "
                    "groß oder der Trainingsreiz zu klein.")
        return (head + " Mehr als die Hälfte davon war Fett — etwas weniger "
                "Überschuss würde das Verhältnis verbessern.")
    if d_lean >= -0.3:
        return head + " Fett runter, Muskel gehalten. Genau so."
    return (head + " Da ging auch fettfreie Masse mit. Mehr Protein und ein "
            "gehaltener Trainingsreiz bremsen das.")


# ------------------------------------------------------------- Zielgewicht

# Gesunder BMI-Korridor. Bei jemandem mit viel Muskelmasse ist der obere Rand
# zu streng — deshalb steht daneben immer der FFMI, der die Magermasse auf die
# Koerpergroesse bezieht und Muskeln nicht als Uebergewicht liest.
HEALTHY_BMI = (20.0, 25.0)

# Zielkorridor fuer den Koerperfettanteil. Unterer Rand: sichtbar definiert,
# noch ohne Verzicht. Oberer Rand: der Punkt, ab dem ein Aufbau kippt.
TARGET_FAT = {"male": (12.0, 17.0), "female": (20.0, 25.0)}

# Was an fettfreier Masse pro Woche realistisch dazukommt. Mehr ist beim
# Erwachsenen ohne Trainingsrueckstand Wasser oder Wunschdenken.
LEAN_GAIN_KG_WEEK = (0.1, 0.25)


def target(today: dt.date | None = None,
           rows: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Zielgewicht aus der eigenen Magermasse, nicht aus einer Tabelle.

    Der uebliche Weg — "BMI 22 mal Groesse im Quadrat" — beantwortet die Frage
    fuer einen Durchschnittskoerper und nicht fuer diesen. Wer schon 68 kg
    fettfreie Masse mit sich traegt, landet bei 12 % Koerperfett zwangslaeufig
    bei 77 kg, ganz gleich was eine Tabelle sagt.

    Deshalb: Magermasse nehmen, den gewuenschten Fettanteil daraufrechnen,
    und den BMI-Korridor nur als Gegenprobe danebenlegen.
    """
    today = today or dt.date.today()
    rows = _read(today) if rows is None else rows
    height = _height_m()
    sex = _sex()
    usable = [r for r in rows
              if r.get("weight_kg") and r.get("body_fat_pct") is not None]
    if not usable:
        return None

    recent = usable[-6:]
    weight = sum(r["weight_kg"] for r in recent) / len(recent)
    fat_pct = sum(r["body_fat_pct"] for r in recent) / len(recent)
    lean = weight * (1 - fat_pct / 100.0)

    low_fat, high_fat = TARGET_FAT[sex]
    # Bei gleichbleibender Magermasse: das Gewicht, das sich aus dem
    # Zielfettanteil ergibt.
    at_low = lean / (1 - low_fat / 100.0)
    at_high = lean / (1 - high_fat / 100.0)

    out: dict[str, Any] = {
        "weight_kg": round(weight, 1),
        "fat_pct": round(fat_pct, 1),
        "lean_kg": round(lean, 1),
        "fat_target": [low_fat, high_fat],
        "range_kg": [round(min(at_low, at_high), 1), round(max(at_low, at_high), 1)],
        "note": ("Gerechnet aus deiner fettfreien Masse und einem Fettanteil "
                 f"von {_de(low_fat, 0)}–{_de(high_fat, 0)} %. Die Zahl "
                 "verschiebt sich mit jedem Kilo Muskel nach oben — sie ist "
                 "kein fester Punkt, sondern der Stand von heute."),
    }

    if height:
        bmi = weight / (height ** 2)
        ffmi = lean / (height ** 2)
        # Auf 1,80 m normiert, wie in der Literatur ueblich — sonst sind die
        # Grenzen fuer grosse und kleine Menschen nicht vergleichbar.
        ffmi_adj = ffmi + 6.1 * (1.8 - height)
        out["bmi"] = round(bmi, 1)
        out["ffmi"] = round(ffmi_adj, 1)
        out["bmi_range_kg"] = [round(HEALTHY_BMI[0] * height ** 2, 1),
                               round(HEALTHY_BMI[1] * height ** 2, 1)]
        out["ffmi_note"] = _ffmi_note(ffmi_adj, sex)

    goal = _goal_direction()
    out["goal"] = goal
    out["sentence"] = _target_sentence(out, goal)
    if goal == "gain":
        mid = sum(out["range_kg"]) / 2
        gap = mid - weight
        if gap > 0.5:
            weeks_low = gap / LEAN_GAIN_KG_WEEK[1]
            weeks_high = gap / LEAN_GAIN_KG_WEEK[0]
            out["eta"] = {
                "gap_kg": round(gap, 1),
                "weeks": [int(round(weeks_low)), int(round(weeks_high))],
                "text": (f"{_de(gap, 1)} kg bis zur Mitte des Korridors. Bei "
                         f"{_de(LEAN_GAIN_KG_WEEK[0], 2)}–"
                         f"{_de(LEAN_GAIN_KG_WEEK[1], 2)} kg fettfreier Masse "
                         f"pro Woche sind das {int(round(weeks_low))} bis "
                         f"{int(round(weeks_high))} Wochen."),
            }
    return out


FFMI_BANDS = (
    (18.0, "unter dem Durchschnitt"),
    (20.0, "durchschnittlich"),
    (22.0, "gut trainiert"),
    (24.0, "sehr gut trainiert"),
    (26.0, "am oberen Rand dessen, was ohne Mittel erreichbar ist"),
)


def _ffmi_note(ffmi: float, sex: str) -> str:
    shift = 0.0 if sex == "male" else -3.0
    for limit, label in FFMI_BANDS:
        if ffmi < limit + shift:
            return (f"FFMI {_de(ffmi)} — {label}. Der FFMI setzt die fettfreie "
                    "Masse ins Verhältnis zur Größe und liest Muskeln nicht "
                    "als Übergewicht, anders als der BMI.")
    return (f"FFMI {_de(ffmi)} — über dem, was üblicherweise als natürliche "
            "Grenze gilt. Meist heißt das, dass die Waage den Fettanteil zu "
            "niedrig schätzt.")


GOAL_WORDS = [
    (("abnehmen", "definieren", "diät", "diaet", "fett verlieren", "sixpack",
      "gewicht verlieren", "schlanker"), "lose"),
    (("zunehmen", "aufbauen", "masse", "muskelaufbau", "muskeln aufbauen",
      "kräftiger", "kraeftiger", "schwerer"), "gain"),
]


def _goal_direction() -> str:
    """Aufbauen, abnehmen oder halten — aus dem Zieltext.

    Dieselbe Lesart wie in vital.weight_goal(): Es gibt genau eine Stelle, an
    der das Ziel steht, und das ist der Freitext.
    """
    text = (get_setting("goal_text", "") or "").lower()
    for words, direction in GOAL_WORDS:
        if any(w in text for w in words):
            return direction
    return "hold"


def _target_sentence(data: dict[str, Any], goal: str) -> str:
    low, high = data["range_kg"]
    now = data["weight_kg"]
    corridor = f"{_de(low)}–{_de(high)} kg"
    if low <= now <= high:
        return (f"Mit {_de(now)} kg liegst du im Korridor {corridor}, der sich "
                f"aus deiner fettfreien Masse ergibt. Von hier aus geht es "
                "nur noch über mehr Muskel, nicht über mehr Gewicht.")
    if now < low:
        gap = low - now
        if goal == "gain":
            return (f"Zielkorridor {corridor} — {_de(gap)} kg über deinem "
                    f"jetzigen Gewicht. Genau die Richtung, die du dir "
                    "vorgenommen hast.")
        return (f"Zielkorridor {corridor}. Du liegst {_de(gap)} kg darunter: "
                "Zum Abnehmen ist das wenig Reserve.")
    gap = now - high
    return (f"Zielkorridor {corridor} — {_de(gap)} kg unter deinem jetzigen "
            f"Gewicht. Das ginge über den Fettanteil, nicht über die Muskeln.")


# ------------------------------------------------------------------ Gesamt

def overview(today: dt.date | None = None) -> dict[str, Any]:
    """Alles, was im Körper-Block des Vitalreiters steht."""
    today = today or dt.date.today()
    rows = _read(today)
    if not rows:
        return {"measurements": 0,
                "hint": ("Noch keine Messungen. Sobald die Waage Daten "
                         "schickt, steht hier die Entwicklung.")}
    return {
        "measurements": len(rows),
        "composition": composition(today, rows),
        "partition": partition(today, rows),
        "target": target(today, rows),
        "discipline": body.discipline(),
    }
