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
import difflib
import json
import logging
import math
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
          "fitnessstudio", "zuhause", "daheim", "morgens", "abends",
          "mittags", "nachmittags", "einheit", "workout",
          # Einheitenwoerter. Sie stehen hier zusaetzlich zu den Mustern,
          # weil ein Muster nur seine eigene Stelle verbraucht: Aus
          # „3 mal 15 wiederholungen" liest „3 mal 15" die Zahlen, und das
          # Wort „wiederholungen" bliebe sonst als Teil des Namens stehen —
          # und mit ihm steckte „lunge" in „wiederho-lunge-n".
          "wiederholung", "wiederholungen", "wdh", "wh", "reps", "rep",
          "satz", "sätze", "saetze", "sätzen", "saetzen", "serie", "serien",
          "set", "sets", "mal", "kg", "kilo", "kilogramm", "sek", "sekunde",
          "sekunden", "min", "minute", "minuten", "std", "stunde", "stunden"}

# Wenn das dransteht, ist kein Gewicht gemeint, sondern gar keins.
BODYWEIGHT_WORDS = ("eigenkörpergewicht", "eigenkoerpergewicht", "körpergewicht",
                    "koerpergewicht", "eigengewicht", "bodyweight",
                    "ohne gewicht", "ohne zusatzgewicht")


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

    # Was an Zahlen uebrig blieb, ist meistens die Angabe, fuer die kein
    # Wort dastand: „drei Sätze 40 kg 15" nennt zuletzt die Wiederholungen.
    # Sie im Namen stehen zu lassen waere die schlechteste aller Deutungen.
    rest = "".join(mask)
    for leftover in (int(m.group(0)) for m in re.finditer(r"\b\d+\b", rest)):
        if "reps" not in found and "rep_list" not in found and 1 <= leftover <= 50:
            found["reps"] = leftover
            break
    mask = [" " if ch.isdigit() else ch for ch in mask]

    low_segment = segment.lower()
    if any(w in low_segment for w in BODYWEIGHT_WORDS):
        found["bodyweight"] = True
        found.pop("weight", None)
        # Und aus dem Namen raus: „Rückenstrecker mit Eigenkörpergewicht" ist
        # die Uebung Rückenstrecker, nicht eine mit langem Zusatz.
        masked = "".join(mask)
        for word in BODYWEIGHT_WORDS:
            masked = re.sub(re.escape(word), " ", masked, flags=re.IGNORECASE)
        mask = list(masked)

    name = " ".join(_keep_words(re.split(r"\s+", "".join(mask))))
    name = re.sub(r"\s+", " ", name).strip(" .,:;()-–—@/")
    return {"raw": segment.strip(), "name": name, **found}


def _keep_words(words: list[str]) -> list[str]:
    """Fuellwoerter entfernen — ausser sie verbinden zwei Namensteile."""
    cleaned = [(w, w.strip(".,:;()-–—@/")) for w in words]
    cleaned = [(w, bare) for w, bare in cleaned if bare]
    kept: list[str] = []
    for index, (word, bare) in enumerate(cleaned):
        low = bare.lower()
        if low not in FILLER:
            kept.append(bare)
            continue
        later = any(b.lower() not in FILLER for _, b in cleaned[index + 1:])
        if low in CONNECTORS and kept and later:
            kept.append(bare)
    while kept and kept[-1].lower() in FILLER:
        kept.pop()
    return kept


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
#
# Frueher wurde hier mit Teilzeichenketten verglichen. Das ging so lange gut,
# bis "Rückenstrecker 3 mal 15 wiederholungen" als "Ausfallschritte" ankam:
# deren Alias "lunge" steckt in "wiederho-lunge-n". Und "Rudern am Kabelzug"
# landete beim Rudergeraet, weil dessen Alias "rudern" nun einmal in "rudern
# kabelzug" vorkommt. Ein Vergleich, der Woerter in der Mitte anderer Woerter
# findet, ist fuer Freitext unbrauchbar.
#
# Jetzt wird auf Wortebene verglichen, mit drei Zutaten:
#   * Woerter zaehlen unterschiedlich viel. "ruckenstrecker" kommt einmal in
#     der Bibliothek vor und sagt alles; "gerat" kommt oft vor und sagt wenig.
#   * Tippfehler duerfen sein: "klimzug" und "klimmzug" sind dasselbe Wort.
#   * Ein genanntes Geraet, das dem der Uebung widerspricht, schlaegt durch.
#     Wer "am Kabelzug" schreibt, meint nicht die Kurzhantel.

FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s",
                      "é": "e", "è": "e", "á": "a", "í": "i"})

# Endungen, die dasselbe Wort nur anders beugen.
ENDINGS = ("en", "er", "es", "e", "n", "s")


def canon(text: str) -> str:
    """Ein Wort auf seine Vergleichsform bringen.

    Umlaute fallen auf den Grundbuchstaben, und zwar in beiden Schreibweisen:
    "ü" und "ue" werden gleich. Sonst faende "Rückenstrecker" nie den Alias
    "rueckenstrecker", der genau dafuer gedacht war.
    """
    low = str(text or "").lower().translate(FOLD)
    low = re.sub(r"ue|oe|ae", lambda m: m.group(0)[0], low)
    return re.sub(r"[^a-z0-9]+", " ", low).strip()


def _stem(word: str) -> str:
    for ending in ENDINGS:
        if len(word) > 4 + len(ending) and word.endswith(ending):
            return word[: -len(ending)]
    return word


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in canon(text).split() if len(w) >= 3]


def _similar(a: str, b: str) -> float:
    """Wie gleich sind zwei Woerter? 1.0 gleich, 0 verschieden."""
    if a == b:
        return 1.0
    if abs(len(a) - len(b)) > 4:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio if ratio >= 0.84 else 0.0


# Genanntes Geraet gegen das der Uebung. Nur Eindeutiges steht hier drin:
# "Hantel" allein kann beides sein und taucht deshalb nicht auf.
EQUIP_WORDS: dict[str, str] = {
    "langhantel": "barbell", "barbell": "barbell", "stang": "barbell",
    "kurzhantel": "dumbbell", "dumbbell": "dumbbell",
    "kabel": "cable", "kabelzug": "cable", "seilzug": "cable", "cabl": "cable",
    "band": "band", "gummiband": "band", "theraband": "band",
    "maschin": "machine", "gerat": "machine",
    "schlingentrain": "suspension", "trx": "suspension",
    "kettlebell": "kettlebell",
    "korpergewicht": "bodyweight", "eigengewicht": "bodyweight",
    "eigenkorpergewicht": "bodyweight", "bodyweight": "bodyweight",
}


def _equipment_named(toks: list[str]) -> str | None:
    for t in toks:
        if t in EQUIP_WORDS:
            return EQUIP_WORDS[t]
    return None


SURE = 0.72          # darueber gilt die Uebung als erkannt
MAYBE = 0.34         # darunter lohnt nicht einmal eine Nachfrage


def _index() -> list[dict[str, Any]]:
    """Die Bibliothek als Wortlisten, mit Gewicht je Wort.

    Das Gewicht ist Wortlaenge mal Seltenheit: Ein Wort, das in der halben
    Bibliothek vorkommt, unterscheidet nichts.
    """
    library = ex_lib.list_exercises()
    entries = []
    for ex in library:
        variants = [tokens(ex["name"])] + [tokens(a) for a in ex["aliases"]]
        variants = [v for v in variants if v]
        entries.append({"ex": ex, "variants": variants,
                        "equipment": ex["equipment"]})

    document_count = max(1, sum(len(e["variants"]) for e in entries))
    seen: dict[str, int] = {}
    for entry in entries:
        for variant in entry["variants"]:
            for t in set(variant):
                seen[t] = seen.get(t, 0) + 1
    for entry in entries:
        entry["weights"] = [
            {t: len(t) * math.log(document_count / (1 + seen.get(t, 0)) + 1.6)
             for t in variant} for variant in entry["variants"]]
    return entries


def _weight_of(token: str, index: list[dict[str, Any]]) -> float:
    """Gewicht eines Wortes aus der Anfrage — dieselbe Skala wie im Index."""
    for entry in index:
        for weights in entry["weights"]:
            if token in weights:
                return weights[token]
    # Kommt in der Bibliothek nicht vor: ein eigenes, unterscheidendes Wort.
    return len(token) * math.log(20.0)


def _movement(toks: list[str]) -> list[str]:
    """Nur die Woerter, die die Bewegung benennen.

    Das Geraet steht daneben und wird eigens geprueft. Zaehlte es mit, gewaenne
    „Crunch am Kabelzug" gegen „Rudern am Kabelzug", weil beide dasselbe Geraet
    nennen und „Kabelzug" das seltenere Wort ist. Gemeint ist aber das Rudern.
    """
    movement = [t for t in toks if t not in EQUIP_WORDS]
    return movement or toks


def _pair_score(query: list[str], q_weights: dict[str, float],
                candidate: list[str], c_weights: dict[str, float]) -> float:
    """Wie gut deckt sich die Anfrage mit einer Uebungsschreibweise?

    Gezaehlt wird in beide Richtungen: Was aus der Anfrage fehlt, und was die
    Uebung zusaetzlich mitbringt. Nur so faellt "Rudern" gegen "Rudern am
    Kabelzug" durch — beide enthalten "Rudern", aber eben nicht nur.
    """
    def coverage(left: list[str], left_w: dict[str, float],
                 right: list[str]) -> float:
        total = sum(left_w.get(t, 1.0) for t in left) or 1.0
        hit = sum(left_w.get(t, 1.0) * max((_similar(t, r) for r in right),
                                           default=0.0) for t in left)
        return hit / total

    q_move, c_move = _movement(query), _movement(candidate)
    return 0.6 * coverage(q_move, q_weights, c_move) \
        + 0.4 * coverage(c_move, c_weights, q_move)


def candidates(name: str, limit: int = 5) -> list[dict[str, Any]]:
    """Die plausibelsten Uebungen zu einer Schreibweise, beste zuerst."""
    query = tokens(name)
    if not query:
        return []
    index = _index()
    q_weights = {t: _weight_of(t, index) for t in query}
    wanted_equipment = _equipment_named(query)

    scored: list[dict[str, Any]] = []
    for entry in index:
        best = 0.0
        for variant, weights in zip(entry["variants"], entry["weights"]):
            best = max(best, _pair_score(query, q_weights, variant, weights))
        if wanted_equipment and entry["equipment"] != wanted_equipment:
            # Ein genanntes Geraet, das nicht passt, ist ein Einspruch —
            # kein Grund zum Ausschluss, aber die Uebung gewinnt so nicht.
            best *= 0.45
        if best > 0.12:
            scored.append({"exercise": entry["ex"], "score": round(best, 3)})
    scored.sort(key=lambda c: -c["score"])
    return scored[:limit]


def _exact(name: str) -> dict[str, Any] | None:
    """Eine Uebung, deren Name oder Alias genau so heisst."""
    wanted = canon(name)
    if not wanted:
        return None
    for ex in ex_lib.list_exercises():
        if canon(ex["name"]) == wanted:
            return ex
        if any(canon(a) == wanted for a in ex["aliases"]):
            return ex
    return None


def find_exercise(name: str) -> dict[str, Any] | None:
    """Die eine Uebung zum Namen — oder nichts."""
    found = resolve(name, ask_model=False)
    return found["exercise"]


def resolve(name: str, ask_model: bool = True) -> dict[str, Any]:
    """Eine Schreibweise aufloesen und dazusagen, wie sicher das ist.

    Drei Ausgaenge: sicher erkannt, unsicher (dann steht die Auswahl daneben),
    oder nichts Passendes. Im unsicheren Fall darf das Modell aus genau diesen
    Kandidaten einen auswaehlen — erfinden kann es dabei nichts, es gibt nur
    eine Nummer zurueck, und die wird geprueft.
    """
    empty = {"exercise": None, "score": 0.0, "confidence": "neu",
             "alternatives": [], "asked_model": False}
    if not name:
        return empty

    # Wortgleich ist wortgleich. Ohne diesen Vorrang entschiede bei zwei
    # gleich guten Treffern die Reihenfolge in der Bibliothek — und eine
    # einmal von Hand richtiggestellte Schreibweise bliebe wirkungslos,
    # obwohl sie als Alias danebensteht.
    exact = _exact(name)
    if exact:
        return {"exercise": exact, "score": 1.0, "confidence": "sicher",
                "alternatives": [{"id": c["exercise"]["id"],
                                  "name": c["exercise"]["name"],
                                  "score": c["score"]} for c in candidates(name)],
                "asked_model": False}

    found = candidates(name)
    if not found:
        return empty

    top = found[0]
    runner_up = found[1]["score"] if len(found) > 1 else 0.0
    alternatives = [{"id": c["exercise"]["id"], "name": c["exercise"]["name"],
                     "score": c["score"]} for c in found]

    if top["score"] >= SURE and top["score"] - runner_up >= 0.08:
        return {"exercise": top["exercise"], "score": top["score"],
                "confidence": "sicher", "alternatives": alternatives,
                "asked_model": False}

    if top["score"] < MAYBE:
        return {**empty, "alternatives": alternatives}

    picked = _model_pick(name, found) if ask_model else None
    if picked:
        return {"exercise": found[picked - 1]["exercise"],
                "score": found[picked - 1]["score"], "confidence": "geprüft",
                "alternatives": alternatives, "asked_model": True}
    if picked == 0:
        # Das Modell hat ausdruecklich "keine davon" gesagt. Das ist eine
        # Antwort, keine Ratlosigkeit — also eine neue Uebung.
        return {**empty, "alternatives": alternatives, "asked_model": True}

    # Nicht fragen koennen ist etwas anderes als eine Absage. Ohne Modell
    # bleibt der beste Treffer stehen, nur eben als unsicher gekennzeichnet:
    # Eine zweite Übung „Rückenstrecker" neben „Rückenstrecker (Gerät)"
    # anzulegen waere von allen Ausgaengen der schlechteste.
    return {"exercise": top["exercise"], "score": top["score"],
            "confidence": "unsicher", "alternatives": alternatives,
            "asked_model": False}


def _model_pick(name: str, found: list[dict[str, Any]]) -> int | None:
    """Das Modell aus einer geschlossenen Liste waehlen lassen.

    Es bekommt nur Nummern zur Auswahl und die Moeglichkeit, keine zu nehmen.
    Antwortet es etwas anderes, gilt das als "keine". So kann aus einer
    Nachfrage keine erfundene Uebung werden.

    Rueckgabe: die Nummer (ab 1), 0 fuer "keine davon", None wenn gar nicht
    gefragt werden konnte. Die beiden letzten Faelle auseinanderzuhalten ist
    wichtig — ein nicht erreichbares Modell ist keine Absage.
    """
    try:
        from .ollama_client import generate_json
        liste = "\n".join(f"{i + 1}. {c['exercise']['name']}"
                          for i, c in enumerate(found))
        data = generate_json(
            prompt=(
                f"Jemand hat in sein Trainingstagebuch „{name.strip()[:80]}“ "
                "geschrieben. Welche Übung aus dieser Liste ist gemeint?\n\n"
                f"{liste}\n\nAntworte als JSON-Objekt mit dem Schlüssel "
                "\"nummer\": die Nummer der gemeinten Übung, oder 0, wenn "
                "keine davon passt. Nur eine Zahl, keine Erklärung. Im "
                "Zweifel 0."),
            system="Du ordnest zu. Du antwortest ausschliesslich mit JSON.",
            temperature=0.1)
        number = int(data.get("nummer", 0)) if isinstance(data, dict) else 0
    except Exception as e:                                      # noqa: BLE001
        log.debug("Zuordnung ohne Modell: %s", e)
        return None
    return number if 1 <= number <= len(found) else 0


# Was eine unbekannte Uebung wohl ist. Nur Stichworte, keine Kunst: Die
# Zuordnung laesst sich in der Vorschau mit einem Tipp korrigieren.
MUSCLE_GUESS: list[tuple[str, str]] = [
    (r"klim+ ?zug|klim+zug|pull ?up|klimmzug", "back"),
    (r"bauch|core|plank|plank|sit ?up|situp|crunch|beinheb|rumpf|kafer|"
     r"klappmess|seitstutz|unterarmstutz|hollow|hohlkorp|russisch", "core"),
    (r"bein|squat|kniebeug|beinpress|wade|calf|ausfallschritt|lunge|"
     r"hip ?thrust|glut|gesass|hamstring|quad|beinbeug|beinstreck", "legs"),
    (r"brust|bank|bench|butterfly|fly|liegestutz|push ?up|dip|chest", "chest"),
    (r"ruck|lat|rudern|row|kreuzheb|deadlift|hyperextension|face ?pull|"
     r"uberzug|pullover|shrug|nackenzieh", "back"),
    (r"schult|shoulder|seitheb|lateral|nacken|overhead|military|pike|"
     r"handstand|halo", "shoulders"),
    (r"bizeps|trizeps|bicep|tricep|curl|unterarm|handgelenk|arm", "arms"),
    (r"lauf|rad|fahrrad|rudergerat|crosstrain|ergomet|laufband|stepp", "cardio"),
]

EQUIPMENT_GUESS: list[tuple[str, str]] = [
    (r"kabel|cable|seilzug", "cable"),
    (r"band|gummi|theraband", "band"),
    (r"langhantel|barbell|stange|sz ?stange", "barbell"),
    (r"kurzhantel|dumbbell|\bkh\b", "dumbbell"),
    (r"schling|trx|suspension", "suspension"),
    (r"kettlebell", "kettlebell"),
    (r"maschin|gerat|presse|zug\b", "machine"),
    (r"plank|sit ?up|situp|crunch|liegestutz|klim+ ?zug|dip|beinheb|"
     r"seitstutz|kafer|hollow|bodyweight|eigengewicht|korpergewicht|"
     r"handstand|kriech", "bodyweight"),
    (r"hantel", "dumbbell"),
]


def _clean_name(raw: str) -> str:
    """Aus dem gelesenen Wortsalat einen Uebungsnamen machen.

    Gross geschrieben werden das erste Wort und alles, was auf ein
    Verbindungswort folgt: „Rudern am Kabelzug", „Kreuzheben mit Langhantel".
    Der Rest bleibt, wie er dasteht — sonst entstuende „Wadenheben Stehend",
    und Adjektive schreibt das Deutsche nun einmal klein.
    """
    words = [w for w in re.split(r"\s+", (raw or "").strip()) if w]
    out: list[str] = []
    for index, word in enumerate(words):
        after_connector = index and words[index - 1].lower() in CONNECTORS
        if (index == 0 or after_connector) and not word[:1].isupper():
            word = word[:1].upper() + word[1:]
        out.append(word)
    return " ".join(out)


# Kleine Woerter, die zwischen zwei Namensteilen stehen bleiben duerfen:
# „Rudern am Kabelzug" liest sich besser als „Rudern Kabelzug".
CONNECTORS = ("am", "an", "mit", "auf", "im", "vor", "hinter")


def guess_new(name: str, has_weight: bool, has_time: bool,
              bodyweight: bool = False) -> dict[str, Any]:
    """Eine unbekannte Uebung so anlegen, dass sie sofort brauchbar ist."""
    low = canon(name)
    muscle = next((g for pattern, g in MUSCLE_GUESS if re.search(pattern, low)), None)
    equipment = next((e for pattern, e in EQUIPMENT_GUESS if re.search(pattern, low)),
                     None)
    if bodyweight:
        equipment = "bodyweight"
    guessed_by_model = False
    if muscle is None or equipment is None:
        asked = _model_guess(name)
        if asked:
            muscle = muscle or asked.get("muscle_group")
            equipment = equipment or asked.get("equipment")
            guessed_by_model = True
    if equipment is None:
        equipment = "machine" if has_weight else "bodyweight"
    if muscle is None:
        muscle = "core"
    mode = "time" if has_time and not has_weight else "reps"
    slot = "mat" if equipment == "bodyweight" and muscle == "core" else "main"
    return {"name": _clean_name(name), "muscle_group": muscle,
            "equipment": equipment, "mode": mode, "slot": slot,
            "guessed_by_model": guessed_by_model}


def _model_guess(name: str) -> dict[str, str] | None:
    """Muskelgruppe und Geraet vom Modell schaetzen lassen — aus fester Auswahl.

    Geprueft wird beides gegen die erlaubten Werte. Etwas anderes als die
    vorgegebenen Woerter kommt nicht durch.
    """
    try:
        from .ollama_client import generate_json
        data = generate_json(
            prompt=(
                f"Die Kraftübung heißt „{name.strip()[:80]}“. Ordne sie zu.\n"
                "Antworte als JSON-Objekt mit zwei Schlüsseln:\n"
                "\"muskelgruppe\": eines von legs, chest, back, shoulders, "
                "arms, core, cardio\n"
                "\"geraet\": eines von machine, cable, band, dumbbell, "
                "barbell, bodyweight, kettlebell, suspension\n"
                "Nur diese Wörter, nichts anderes."),
            system="Du ordnest zu. Du antwortest ausschliesslich mit JSON.",
            temperature=0.1)
    except Exception as e:                                      # noqa: BLE001
        log.debug("Zuordnung der neuen Übung ohne Modell: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    muscle = str(data.get("muskelgruppe", "")).strip().lower()
    equipment = str(data.get("geraet", "")).strip().lower()
    return {
        "muscle_group": muscle if muscle in ex_lib.MUSCLE_LABELS else "",
        "equipment": equipment if equipment in ex_lib.EQUIPMENT_LABELS else "",
    }

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

        found = resolve(parsed["name"])
        known = found["exercise"]
        has_weight = any(s.get("weight_kg") for s in sets)
        has_time = any(s.get("duration_s") for s in sets)
        item = {
            "raw": parsed["raw"], "read_name": parsed["name"], "sets": sets,
            "known": bool(known),
            "exercise_id": known["id"] if known else None,
            "confidence": found["confidence"],
            "score": found["score"],
            # Die naechstbesten Treffer stehen immer daneben — auch wenn die
            # Zuordnung sicher aussieht. Eine falsche Zuordnung, die man nur
            # abwaehlen statt richtigstellen kann, kostet mehr als sie spart.
            "alternatives": found["alternatives"],
            "summary": _summarise(sets),
        }
        if known:
            item.update({
                "name": known["name"],
                "muscle_group": known["muscle_group"],
                "muscle_label": ex_lib.MUSCLE_LABELS.get(known["muscle_group"], ""),
                "equipment": known["equipment"],
                "current": _current_of(known),
            })
        else:
            guess = guess_new(parsed["name"], has_weight, has_time,
                              bodyweight=bool(parsed.get("bodyweight")))
            item.update({"name": guess["name"],
                         "muscle_group": guess["muscle_group"],
                         "muscle_label": ex_lib.MUSCLE_LABELS.get(
                             guess["muscle_group"], ""),
                         "equipment": guess["equipment"], "mode": guess["mode"],
                         "slot": guess["slot"],
                         "guessed_by_model": guess["guessed_by_model"]})
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
    learned: list[str] = []
    written = 0

    for item in items or []:
        if item.get("skip"):
            continue
        ex_id = None if item.get("force_new") else item.get("exercise_id")
        if ex_id:
            learned += _learn_alias(int(ex_id), item.get("read_name") or "")
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
            existing = None if item.get("force_new") else find_exercise(guess["name"])
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
            "learned": learned, "runs": logged_runs, "proposals": proposals}


def _learn_alias(exercise_id: int, written_as: str) -> list[str]:
    """Wie du es geschrieben hast, als Alias merken.

    Wer eine falsche Zuordnung einmal richtigstellt, soll sie nicht jedes Mal
    wieder richtigstellen muessen. Die eigene Schreibweise wird zum Alias, und
    beim naechsten Mal sitzt sie auf Anhieb.
    """
    written_as = " ".join((written_as or "").split())
    if len(written_as) < 3:
        return []
    ex = ex_lib.get_exercise(exercise_id)
    if not ex:
        return []
    known = {canon(ex["name"]), *(canon(a) for a in ex["aliases"])}
    if canon(written_as) in known:
        return []
    # Wenn dieselbe Schreibweise bisher einer anderen Uebung gehoerte, gehoert
    # sie ihr ab jetzt nicht mehr. Zwei Uebungen, die beide „Rückenstrecker"
    # heissen wollen, machen die Korrektur wirkungslos — es entschiede weiter
    # die Reihenfolge in der Bibliothek.
    wanted = canon(written_as)
    freed = []
    for other in ex_lib.list_exercises():
        if other["id"] == exercise_id:
            continue
        keep = [a for a in other["aliases"] if canon(a) != wanted]
        if len(keep) != len(other["aliases"]):
            with get_db() as db:
                db.execute("UPDATE exercises SET aliases=? WHERE id=?",
                           (json.dumps(keep, ensure_ascii=False), other["id"]))
            freed.append(other["name"])

    aliases = [*ex["aliases"], written_as.lower()]
    with get_db() as db:
        db.execute("UPDATE exercises SET aliases=? WHERE id=?",
                   (json.dumps(aliases, ensure_ascii=False), exercise_id))
    log.info("Schreibweise gemerkt: „%s“ heisst %s%s.", written_as, ex["name"],
             f" (vorher {', '.join(freed)})" if freed else "")
    return [f"„{written_as}“ → {ex['name']}"]


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
