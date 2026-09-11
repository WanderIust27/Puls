"""Ein Training in Worten — und was daraus folgt.

Du schreibst hin, was du gemacht hast: „Gestern Beinpresse 3x15 mit 60 kg,
dann Latzug 12/10/8 bei 45, neu Wadenheben 3 Sätze à 20 mit 30 kg." PULS liest
daraus die Sätze, legt unbekannte Übungen an und schlägt die neuen Gewichte vor.

Gelesen wird mit Regeln, nicht mit dem Modell. Zahlen sind das Einzige, worauf
es hier ankommt, und ein Sprachmodell, das „60 kg" zu „65 kg" verliest, ist
schlimmer als eines, das gar nichts sagt. Das Modell darf einen Fliesstext in
Zeilen zerlegen, wenn die Regeln daran scheitern — die Zahlen selbst werden
danach gegen den Originaltext geprueft und verworfen, wenn sie dort nicht
vorkommen.

Geschrieben wird erst auf Zuruf: preview() zeigt, was verstanden wurde,
commit() traegt es ein. Ein Missverstaendnis soll auffallen, bevor es in der
Datenbank steht.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from ..db import get_db, rows_to_dicts
from . import exercises as ex_lib

log = logging.getLogger("puls.logbook")

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
            "Samstag", "Sonntag"]
WEEKDAY_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Zahlwoerter, damit „dreimal fuenfzehn mit sechzig Kilo" genauso ankommt wie
# „3x15 60 kg". Bewusst nur bis 100 und ohne Bruchteile: Wer 2,5 kg meint,
# schreibt 2,5.
ONES = {"null": 0, "ein": 1, "eine": 1, "eins": 1, "zwei": 2, "drei": 3,
        "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
        "neun": 9}
TEENS = {"zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12, "dreizehn": 13,
         "vierzehn": 14, "fünfzehn": 15, "fuenfzehn": 15, "sechzehn": 16,
         "siebzehn": 17, "achtzehn": 18, "neunzehn": 19}
TENS = {"zwanzig": 20, "dreißig": 30, "dreissig": 30, "vierzig": 40,
        "fünfzig": 50, "fuenfzig": 50, "sechzig": 60, "siebzig": 70,
        "achtzig": 80, "neunzig": 90, "hundert": 100}


def _decimal_point(text: str) -> str:
    """Aus „5,2 km" ein „5.2 km" machen.

    Das Komma trennt in diesem Text Uebungen voneinander — ausser zwischen
    zwei Ziffern. Wer das nicht vorher aufloest, macht aus 5,2 km zwei Laeufe.
    """
    return re.sub(r"(?<=\d),(?=\d)", ".", text)


def _words_to_digits(text: str) -> str:
    """Zahlwoerter durch Ziffern ersetzen — zusammengesetzte zuerst."""
    out = text
    # „fuenfundzwanzig" vor „fuenf", sonst bliebe „5undzwanzig" stehen.
    for ones, ov in sorted(ONES.items(), key=lambda kv: -len(kv[0])):
        for tens, tv in TENS.items():
            out = re.sub(rf"\b{ones}und{tens}\b", str(ov + tv), out)
    for table in (TEENS, TENS, ONES):
        for word, value in sorted(table.items(), key=lambda kv: -len(kv[0])):
            out = re.sub(rf"\b{word}(?=mal\b)", str(value), out)
            out = re.sub(rf"\b{word}\b", str(value), out)
    return out


# ------------------------------------------------------------------- Datum

def read_day(text: str, today: dt.date | None = None) -> dict[str, Any]:
    """Aus dem Text den Trainingstag lesen. Ohne Angabe: heute."""
    today = today or dt.date.today()
    low = text.lower()

    m = re.search(r"\b(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{2,4}))?", low)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3) or today.year)
        if year < 100:
            year += 2000
        try:
            found = dt.date(year, month, day)
            # Ein Datum ohne Jahr, das in der Zukunft laege, meint das Vorjahr.
            if not m.group(3) and found > today:
                found = dt.date(year - 1, month, day)
            return _day_result(found, today, "Datum im Text")
        except ValueError:
            pass

    if "vorgestern" in low:
        return _day_result(today - dt.timedelta(days=2), today, "vorgestern")
    if "gestern" in low:
        return _day_result(today - dt.timedelta(days=1), today, "gestern")
    if "heute" in low:
        return _day_result(today, today, "heute")

    for index, name in enumerate(WEEKDAYS):
        if name.lower() in low or re.search(rf"\b{WEEKDAY_SHORT[index].lower()}\b", low):
            # Der zuletzt vergangene Wochentag dieses Namens.
            back = (today.weekday() - index) % 7
            return _day_result(today - dt.timedelta(days=back), today,
                               name if back == 0 else f"letzter {name}")
    return _day_result(today, today, "kein Datum genannt — heute")


def _day_result(day: dt.date, today: dt.date, how: str) -> dict[str, Any]:
    delta = (today - day).days
    when = ("heute" if delta == 0 else "gestern" if delta == 1
            else "vorgestern" if delta == 2 else f"vor {delta} Tagen")
    return {"day": day.isoformat(), "how": how,
            "label": f"{when}, {WEEKDAY_SHORT[day.weekday()]} "
                     f"{day.day}.{day.month}."}


# --------------------------------------------------------------- Zerlegung

# Satzpunkt nur, wenn keine Ziffer davorsteht: „5.2 km" und „am 3.9." sind
# keine Satzenden.
SPLIT_RE = re.compile(r"[\n;•·:]+|(?<!\d)\.\s+|\bdann\b|\bdanach\b|\bund\b|"
                      r"\banschließend\b|\banschliessend\b|\bzuerst\b|\bdazu\b",
                      flags=re.IGNORECASE)
FILLER = {"mit", "bei", "je", "à", "a", "und", "auf", "im", "in", "am", "der",
          "die", "das", "den", "dem", "ich", "hab", "habe", "gemacht", "war",
          "danach", "dann", "noch", "an", "für", "fuer", "zu", "von", "aus",
          "heute", "gestern", "vorgestern", "training", "trainiert", "jeweils",
          "insgesamt", "also", "waren", "ca", "etwa", "rund", "gym", "studio",
          "fitnessstudio", "zuhause", "daheim", "heute", "morgens", "abends",
          "mittags", "nachmittags", "einheit", "workout"}


def _segments(text: str) -> list[str]:
    """Den Text in Uebungsstuecke schneiden.

    Erst grosszuegig trennen, dann alles wieder anhaengen, was fuer sich
    genommen keinen Namen hat. So bleibt „Beinpresse 15, 12, 10 mit 60 kg"
    eine Uebung, obwohl das Komma dreimal getrennt hat.
    """
    rough: list[str] = []
    for chunk in SPLIT_RE.split(_decimal_point(text)):
        rough += [p for p in chunk.split(",")]

    out: list[str] = []
    for piece in rough:
        piece = piece.strip(" .:-–—\t")
        if not piece:
            continue
        rest = " ".join(w for w in _strip_units(piece).lower().split()
                        if w.strip(".,:;()-–—@") not in FILLER)
        has_name = bool(re.search(r"[a-zäöüß]{3,}", rest))
        if out and not has_name:
            out[-1] = f"{out[-1]}, {piece}"
        else:
            out.append(piece)
    return out


UNIT_WORDS = (r"kg|kilo|wdh|wiederholung\w*|reps?|sätze?n?|saetze?n?|satz|"
              r"serien?|sets?|sek\w*|min\w*|mal|km|std|stunden?")


def _strip_units(text: str) -> str:
    """Nur die Buchstaben uebrig lassen, die ein Name sein koennten."""
    return re.sub(rf"\d+(?:[.,]\d+)?\s*(?:{UNIT_WORDS})?", " ", text,
                  flags=re.IGNORECASE)


# ------------------------------------------------------------- Satz-Lesung

NUM = r"\d+(?:[.,]\d+)?"

# Reihenfolge ist Bedeutung: Was frueher greift, verbraucht seine Stelle im
# Text. „3 Sätze à 12" darf nicht als „3x12 Sekunden" enden.
PATTERNS: list[tuple[str, str]] = [
    ("sets_reps_weight", rf"(\d+)\s*(?:[x×*]|mal)\s*(\d+)\s*(?:[x×*]|mit|@)\s*({NUM})\s*(?:kg|kilo)?"),
    ("sets_time",        rf"(\d+)\s*(?:[x×*]|mal)\s*({NUM})\s*(?:sek\w*|s)\b"),
    ("sets_weight",      rf"(\d+)\s*(?:[x×*]|mal)\s*({NUM})\s*(?:kg|kilo)\b"),
    ("sets_reps",        r"(\d+)\s*(?:[x×*]|mal)\s*(\d+)\b"),
    ("weight_list",      rf"(?:@|mit|bei)\s*({NUM}(?:\s*/\s*{NUM})+)\s*(?:kg|kilo)?"),
    ("rep_list",         r"(\d+(?:\s*[/,]\s*\d+)+)"),
    ("weight",           rf"(?:@|mit)?\s*({NUM})\s*(?:kg|kilo)\b"),
    ("reps",             r"(\d+)\s*(?:wdh|wiederholung\w*|reps?)\b"),
    ("sets",             r"(\d+)\s*(?:sätze?n?|saetze?n?|satz|serien?|sets?)\b"),
    ("time",             rf"({NUM})\s*(?:sekunden?|sek|s)\b"),
    ("minutes",          rf"({NUM})\s*(?:minuten?|min)\b"),
    ("hours",            rf"({NUM})\s*(?:stunden?|std|h)\b"),
    ("distance",         rf"({NUM})\s*km\b"),
    ("at_weight",        rf"@\s*({NUM})"),
]


def _num(raw: str) -> float:
    return float(str(raw).replace(",", "."))


def read_segment(segment: str) -> dict[str, Any]:
    """Ein Stueck Text zu Name und Saetzen machen."""
    work = _words_to_digits(segment.lower())
    found: dict[str, Any] = {}
    mask = list(work)

    for key, pattern in PATTERNS:
        for m in re.finditer(pattern, "".join(mask), flags=re.IGNORECASE):
            if key == "sets_reps_weight":
                found.setdefault("sets", int(m.group(1)))
                found.setdefault("reps", int(m.group(2)))
                found.setdefault("weight", _num(m.group(3)))
            elif key == "sets_time":
                found.setdefault("sets", int(m.group(1)))
                found.setdefault("seconds", _num(m.group(2)))
            elif key == "sets_weight":
                found.setdefault("sets", int(m.group(1)))
                found.setdefault("weight", _num(m.group(2)))
            elif key == "sets_reps":
                found.setdefault("sets", int(m.group(1)))
                found.setdefault("reps", int(m.group(2)))
            elif key == "weight_list":
                found.setdefault("weight_list",
                                 [_num(v) for v in re.split(r"\s*/\s*", m.group(1))])
            elif key == "rep_list":
                values = [int(v) for v in re.split(r"\s*[/,]\s*", m.group(1))]
                found.setdefault("rep_list", values)
            elif key in ("weight", "at_weight"):
                found.setdefault("weight", _num(m.group(1)))
            elif key == "reps":
                found.setdefault("reps", int(m.group(1)))
            elif key == "sets":
                found.setdefault("sets", int(m.group(1)))
            elif key == "time":
                found.setdefault("seconds", _num(m.group(1)))
            elif key == "minutes":
                found.setdefault("minutes", _num(m.group(1)))
            elif key == "hours":
                found.setdefault("minutes", _num(m.group(1)) * 60)
            elif key == "distance":
                found.setdefault("km", _num(m.group(1)))
            # Die Stelle verbrauchen, damit spaetere Muster sie nicht neu deuten
            for i in range(m.start(), m.end()):
                mask[i] = " "

    name = " ".join(w for w in re.split(r"\s+", "".join(mask))
                    if w.strip(".,:;()-–—@/") and w.strip(".,:;()-–—@/") not in FILLER)
    name = re.sub(r"\s+", " ", name).strip(" .,:;()-–—@/")
    return {"raw": segment.strip(), "name": name, **found}


RUN_WORDS = ("lauf", "gelaufen", "joggen", "gejoggt", "run", "runde gedreht",
             "laufen", "jogging")


def _is_run(item: dict[str, Any]) -> bool:
    low = item["raw"].lower()
    if any(w in low for w in RUN_WORDS):
        return True
    # Kilometer ohne Gewicht und ohne Wiederholungen ist ein Lauf.
    return bool(item.get("km")) and not item.get("weight") and not item.get("reps")


def _sets_of(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Aus dem Gelesenen die einzelnen Saetze machen."""
    weight = item.get("weight")
    if item.get("weight_list"):
        # „15 Wdh @ 25/30/35" heisst: drei Saetze, dreimal dasselbe Ziel,
        # steigendes Gewicht. Der letzte Satz sagt, was wirklich geht.
        reps = item.get("reps")
        rep_list = item.get("rep_list") or []
        return [{"reps": (rep_list[i] if i < len(rep_list) else reps), "weight_kg": w}
                for i, w in enumerate(item["weight_list"])]
    if item.get("rep_list"):
        return [{"reps": r, "weight_kg": weight} for r in item["rep_list"]]
    count = int(item.get("sets") or 1)
    if item.get("seconds"):
        return [{"duration_s": item["seconds"], "weight_kg": weight}
                for _ in range(count)]
    if item.get("reps"):
        return [{"reps": int(item["reps"]), "weight_kg": weight}
                for _ in range(count)]
    if weight:
        return [{"weight_kg": weight} for _ in range(count)]
    return []


# ------------------------------------------------------- Uebung wiederfinden

def _tokens(name: str) -> set[str]:
    return {t for t in ex_lib.normalize(name).split() if len(t) >= 3}


def find_exercise(name: str) -> dict[str, Any] | None:
    """Die Uebung zum Namen — erst genau, dann ueber Wortueberschneidung."""
    if not name:
        return None
    wanted = ex_lib.normalize(name)
    library = ex_lib.list_exercises()
    for ex in library:
        if ex_lib.normalize(ex["name"]) == wanted:
            return ex
        if any(ex_lib.normalize(a) == wanted for a in ex["aliases"]):
            return ex
    direct = ex_lib.match_exercise(name)
    if direct:
        return direct
    mine = _tokens(name)
    if not mine:
        return None
    best, best_score = None, 0.0
    for ex in library:
        theirs = _tokens(ex["name"]) | {t for a in ex["aliases"] for t in _tokens(a)}
        if not theirs:
            continue
        shared = mine & theirs
        if not shared or max(len(t) for t in shared) < 4:
            continue
        score = len(shared) / min(len(mine), len(theirs))
        if score > best_score:
            best, best_score = ex, score
    return best if best_score >= 0.6 else None


# Was eine unbekannte Uebung wohl ist. Nur Stichworte, keine Kunst: Die
# Zuordnung laesst sich in der Bibliothek mit zwei Tippern korrigieren.
MUSCLE_GUESS: list[tuple[str, str]] = [
    (r"bauch|core|plank|planke|sit.?up|crunch|beinheben|rumpf|käfer|kaefer|"
     r"klappmesser|seitstütz|seitstuetz|unterarmstütz|unterarmstuetz|hollow", "core"),
    (r"bein|squat|kniebeuge|beinpresse|beinbeuger|beinstrecker|wade|calf|"
     r"ausfallschritt|lunge|hip thrust|glute|gesäß|gesaess|hamstring|quad", "legs"),
    (r"brust|bank|bench|butterfly|fly|flye|liegestütz|liegestuetz|push.?up|dip", "chest"),
    (r"rücken|ruecken|lat|rudern|row|klimmzug|pull.?up|kreuzheben|deadlift|"
     r"hyperextension|rückenstrecker|rueckenstrecker|face pull", "back"),
    (r"schulter|shoulder|seitheben|lateral|nacken|shrug|overhead|"
     r"military|pike", "shoulders"),
    (r"bizeps|trizeps|biceps|triceps|curl|unterarm|handgelenk", "arms"),
    (r"lauf|rad|fahrrad|rudergerät|rudergeraet|crosstrainer|ergometer|"
     r"laufband|stepper", "cardio"),
]

EQUIPMENT_GUESS: list[tuple[str, str]] = [
    (r"kabel|cable|kabelzug", "cable"),
    (r"band|gummi|theraband", "band"),
    (r"kurzhantel|dumbbell|\bkh\b|hantel", "dumbbell"),
    (r"langhantel|barbell|stange", "barbell"),
    (r"schling|trx|suspension", "suspension"),
    (r"kettlebell", "dumbbell"),
    (r"maschine|gerät|geraet|presse|zug\b", "machine"),
    (r"plank|planke|sit.?up|crunch|liegestütz|liegestuetz|klimmzug|dip|"
     r"beinheben|seitstütz|seitstuetz|käfer|kaefer|hollow|bodyweight|"
     r"eigengewicht", "bodyweight"),
]


def guess_new(name: str, has_weight: bool, has_time: bool) -> dict[str, Any]:
    """Eine unbekannte Uebung so anlegen, dass sie sofort brauchbar ist."""
    low = ex_lib.normalize(name)
    muscle = next((g for pattern, g in MUSCLE_GUESS if re.search(pattern, low)), "core")
    equipment = next((e for pattern, e in EQUIPMENT_GUESS if re.search(pattern, low)),
                     "machine" if has_weight else "bodyweight")
    mode = "time" if has_time and not has_weight else "reps"
    slot = "mat" if equipment == "bodyweight" and muscle == "core" else "main"
    return {"name": name.strip().capitalize() if name.islower() else name.strip(),
            "muscle_group": muscle, "equipment": equipment, "mode": mode,
            "slot": slot}


# ------------------------------------------------------------------ Vorschau

def preview(text: str, today: dt.date | None = None) -> dict[str, Any]:
    """Lesen, was dasteht — ohne etwas zu speichern."""
    text = (text or "").strip()
    if not text:
        return {"day": (today or dt.date.today()).isoformat(), "items": [],
                "runs": [], "unread": [], "hint": "Schreib hin, was du gemacht hast."}

    text = _decimal_point(text)
    when = read_day(text, today)
    items, runs, unread = _read_all(text)

    if not items and not runs:
        assisted = _model_lines(text)
        if assisted:
            items, runs, extra = _read_all("\n".join(assisted), verify_against=text)
            unread += extra

    return {"day": when["day"], "day_label": when["label"], "day_how": when["how"],
            "items": items, "runs": runs, "unread": unread,
            "hint": None if (items or runs) else
                    "Daraus konnte ich keine Sätze lesen. Ein Beispiel, das "
                    "immer klappt: „Beinpresse 3x15 mit 60 kg“."}


def _read_all(text: str, verify_against: str | None = None
              ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    unread: list[str] = []

    for segment in _segments(text):
        # Ein Stueck ohne jede Ziffer ist Beiwerk („Gestern im Gym“), kein
        # missverstandener Satz. Es als „nicht verstanden“ zu melden waere
        # ein Fehler, der keiner ist.
        if not re.search(r"\d", _words_to_digits(segment.lower())):
            continue
        parsed = read_segment(segment)
        if verify_against is not None and not _numbers_occur(parsed, verify_against):
            unread.append(segment.strip())
            continue
        if _is_run(parsed):
            minutes = parsed.get("minutes") or (
                parsed["seconds"] / 60 if parsed.get("seconds") else None)
            if parsed.get("km") or minutes:
                label = " ".join(w for w in parsed["name"].split()
                                 if not any(r in w for r in RUN_WORDS))
                runs.append({"raw": parsed["raw"], "km": parsed.get("km"),
                             "minutes": round(minutes, 1) if minutes else None,
                             "name": label.strip().capitalize() or "Lauf"})
            else:
                unread.append(segment.strip())
            continue

        sets = _sets_of(parsed)
        if not parsed["name"] or not sets:
            unread.append(segment.strip())
            continue

        known = find_exercise(parsed["name"])
        has_weight = any(s.get("weight_kg") for s in sets)
        has_time = any(s.get("duration_s") for s in sets)
        item = {
            "raw": parsed["raw"], "read_name": parsed["name"], "sets": sets,
            "known": bool(known),
            "exercise_id": known["id"] if known else None,
            "name": known["name"] if known else
                    guess_new(parsed["name"], has_weight, has_time)["name"],
            "summary": _summarise(sets),
        }
        if known:
            item["muscle_group"] = known["muscle_group"]
            item["muscle_label"] = ex_lib.MUSCLE_LABELS.get(known["muscle_group"], "")
            item["current"] = _current_of(known)
        else:
            guess = guess_new(parsed["name"], has_weight, has_time)
            item.update({"muscle_group": guess["muscle_group"],
                         "muscle_label": ex_lib.MUSCLE_LABELS.get(
                             guess["muscle_group"], ""),
                         "equipment": guess["equipment"], "mode": guess["mode"],
                         "slot": guess["slot"]})
        items.append(item)
    return items, runs, unread


def _numbers_occur(parsed: dict[str, Any], source: str) -> bool:
    """Kommt jede Zahl, die das Modell gelesen hat, im Originaltext vor?

    Das Modell darf zerlegen, nicht rechnen. Eine Zahl, die es dazuerfindet,
    stuende sonst am Ende als gestemmtes Gewicht in der Datenbank.
    """
    digits = set(re.findall(r"\d+", _words_to_digits(source.lower())))
    wanted: list[float] = []
    for key in ("sets", "reps", "weight", "seconds", "minutes", "km"):
        if parsed.get(key) is not None:
            wanted.append(float(parsed[key]))
    wanted += [float(r) for r in parsed.get("rep_list") or []]
    wanted += [float(w) for w in parsed.get("weight_list") or []]
    for value in wanted:
        text = f"{value:g}"
        if text not in digits and text.replace(".", ",") not in source.lower():
            return False
    return True


def _summarise(sets: list[dict[str, Any]]) -> str:
    parts = []
    for s in sets:
        if s.get("duration_s"):
            core = f"{s['duration_s']:g} s"
        elif s.get("reps"):
            core = f"{s['reps']}×"
        else:
            core = "1 Satz"
        if s.get("weight_kg"):
            core += f" {s['weight_kg']:g} kg"
        parts.append(core)
    return " · ".join(parts)


def _current_of(ex: dict[str, Any]) -> str:
    if ex["mode"] == "time":
        return f"bisher {ex.get('target_duration_s') or 30:g} s"
    weight = ex.get("weight_kg")
    return (f"bisher {weight:g} kg × {ex['target_reps']}" if weight
            else f"bisher {ex['target_reps']} Wiederholungen")


def _model_lines(text: str) -> list[str]:
    """Fliesstext vom Modell in Zeilen schneiden lassen — nur zerlegen."""
    if len(text.strip()) < 12:
        return []
    try:
        from .ollama_client import generate_json
        data = generate_json(
            prompt=(
                "Zerlege die folgende Trainingsbeschreibung in einzelne Zeilen, "
                "eine je Übung. Schreibe jede Zeile im Format "
                "\"Übungsname Sätze x Wiederholungen Gewichtkg\". Übernimm alle "
                "Zahlen unverändert aus dem Text und erfinde keine. Wenn eine "
                "Angabe fehlt, lass sie weg. Antworte als JSON-Objekt mit dem "
                "Schlüssel \"zeilen\" (Liste von Zeichenketten).\n\n"
                f"Text: {text.strip()[:800]}"),
            system="Du zerlegst Text. Du antwortest ausschliesslich mit JSON.")
        lines = data.get("zeilen") if isinstance(data, dict) else None
        return [str(line) for line in lines][:20] if isinstance(lines, list) else []
    except Exception as e:                                      # noqa: BLE001
        log.debug("Beschreibung ohne Modell gelesen: %s", e)
        return []


# ----------------------------------------------------------------- Eintragen

def commit(day: str, items: list[dict[str, Any]],
           runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Die bestaetigte Vorschau eintragen und die Gewichte fortschreiben."""
    day = day or dt.date.today().isoformat()
    created: list[str] = []
    written = 0

    for item in items or []:
        if item.get("skip"):
            continue
        ex_id = item.get("exercise_id")
        if not ex_id:
            guess = guess_new(item.get("name") or item.get("read_name") or "",
                              any(s.get("weight_kg") for s in item.get("sets") or []),
                              any(s.get("duration_s") for s in item.get("sets") or []))
            guess["name"] = (item.get("name") or guess["name"]).strip()
            guess["muscle_group"] = item.get("muscle_group") or guess["muscle_group"]
            guess["equipment"] = item.get("equipment") or guess["equipment"]
            heaviest = max((s.get("weight_kg") or 0) for s in item["sets"]) or None
            reps = next((s.get("reps") for s in item["sets"] if s.get("reps")), 12)
            guess.update({"weight_kg": heaviest, "target_reps": reps,
                          "rep_min": min(10, reps), "rep_max": max(15, reps),
                          "sets": len(item["sets"]),
                          "aliases": [item.get("read_name") or ""]})
            existing = find_exercise(guess["name"])
            if existing:
                ex_id = existing["id"]
            else:
                ex_id = ex_lib.upsert_exercise(guess)
                created.append(guess["name"])

        # Eine erneut geschickte Beschreibung soll denselben Tag ersetzen,
        # nicht verdoppeln. Saetze von der Uhr bleiben unangetastet.
        with get_db() as db:
            db.execute("DELETE FROM exercise_sets WHERE exercise_id=? AND day=? "
                       "AND source='text'", (ex_id, day))
        for index, s in enumerate(item.get("sets") or [], start=1):
            ex_lib.record_set(ex_id, reps=s.get("reps"), weight_kg=s.get("weight_kg"),
                              duration_s=s.get("duration_s"), day=day,
                              set_index=index, source="text")
            written += 1

    logged_runs = 0
    for run in runs or []:
        if run.get("skip"):
            continue
        if _record_run(day, run):
            logged_runs += 1

    proposals = ex_lib.propose_for_day(day) if written else []
    return {"day": day, "sets": written, "created": created,
            "runs": logged_runs, "proposals": proposals}


def _record_run(day: str, run: dict[str, Any]) -> bool:
    km = run.get("km")
    minutes = run.get("minutes")
    if not km and not minutes:
        return False
    start = f"{day}T12:00:00"
    with get_db() as db:
        exists = db.execute(
            "SELECT id FROM activities WHERE sport='running' AND start_time=? "
            "AND source='text'", (start,)).fetchone()
        if exists:
            return False
        db.execute(
            """INSERT INTO activities(source, name, sport, start_time, duration_s,
                                      distance_m, notes)
               VALUES('text', ?, 'running', ?, ?, ?, ?)""",
            (run.get("name") or "Lauf", start,
             int(minutes * 60) if minutes else None,
             km * 1000 if km else None, run.get("raw")))
    return True


# ------------------------------------------------------------ Letzte Einheiten

def recent_sessions(limit: int = 8) -> list[dict[str, Any]]:
    """Die letzten Krafttage mit ihren Uebungen — kurz gefasst."""
    with get_db() as db:
        days = [r["day"] for r in db.execute(
            "SELECT DISTINCT day FROM exercise_sets ORDER BY day DESC LIMIT ?",
            (limit,)).fetchall()]
        if not days:
            return []
        marks = ",".join("?" for _ in days)
        rows = rows_to_dicts(db.execute(
            f"""SELECT s.day, s.reps, s.weight_kg, s.duration_s, s.source,
                       e.name, e.muscle_group
                FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
                WHERE s.day IN ({marks})
                ORDER BY s.day DESC, e.name, s.set_index""", days).fetchall())

    sessions: dict[str, dict[str, Any]] = {}
    for r in rows:
        day = sessions.setdefault(r["day"], {"day": r["day"], "exercises": {},
                                             "sets": 0, "volume": 0.0,
                                             "sources": set()})
        day["sets"] += 1
        day["volume"] += (r["reps"] or 0) * (r["weight_kg"] or 0)
        day["sources"].add(r["source"])
        ex = day["exercises"].setdefault(r["name"], {"name": r["name"],
                                                     "group": r["muscle_group"],
                                                     "sets": []})
        ex["sets"].append({"reps": r["reps"], "weight_kg": r["weight_kg"],
                           "duration_s": r["duration_s"]})

    out = []
    for day in sessions.values():
        exercises = list(day["exercises"].values())
        for ex in exercises:
            ex["summary"] = _summarise(ex["sets"])
        out.append({"day": day["day"], "sets": day["sets"],
                    "volume": round(day["volume"]),
                    "sources": sorted(day["sources"]),
                    "exercises": exercises})
    out.sort(key=lambda d: d["day"], reverse=True)
    return out
