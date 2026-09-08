"""Gemuetszustand, Beschwerden — und was daraus fuers Training folgt.

Mehrmals am Tag eintragbar: drei Regler, antippbare Beschwerden und ein
Freitextfeld. Aus den Beschwerden leitet PULS konkrete Anpassungen ab —
welche Uebungen heute besser ausfallen, welche Yoga-Stellungen dafuer
dazukommen, und was in der Kueche hilft.

Die Zuordnung steht als Tabelle im Code, nicht im Modell: bei "Rueckenschmerzen"
soll immer dasselbe passieren, nicht mal so und mal so. Das Modell darf nur
eines — im Freitext Beschwerden erkennen, die nicht angetippt wurden. Und
selbst dann werden sie nur vorgeschlagen, nie stillschweigend uebernommen.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, rows_to_dicts

log = logging.getLogger("puls.mood")

REGIONS = {
    "back_low": "Unterer Rücken", "back_up": "Oberer Rücken", "neck": "Nacken",
    "shoulder": "Schulter", "chest": "Brust", "arms": "Arme", "wrist": "Handgelenk",
    "core": "Rumpf", "hip": "Hüfte", "glutes": "Gesäß", "thigh": "Oberschenkel",
    "hamstring": "Beinrückseite", "knee": "Knie", "calf": "Wade",
    "ankle": "Sprunggelenk", "foot": "Fuß", "general": "Allgemein",
}
KINDS = {
    "soreness": "Muskelkater", "pain": "Schmerz", "tension": "Verspannung",
    "stiffness": "Steifheit", "fatigue": "Schwere", "injury": "Verletzung",
}
# Wie lange eine Meldung nachwirkt. Muskelkater klingt ab, Schmerz nicht
# einfach so — deshalb bleibt er laenger im Blick.
DECAY_DAYS = {"soreness": 3, "fatigue": 2, "tension": 4, "stiffness": 4,
              "pain": 7, "injury": 21}

# Muskelgruppen, die bei einer Beschwerde in dieser Region geschont werden.
# Die Namen entsprechen der Spalte muscle_group in der Uebungsbibliothek.
SPARE_GROUPS: dict[str, list[str]] = {
    "back_low": ["back", "legs"], "back_up": ["back", "shoulders"],
    "neck": ["shoulders"], "shoulder": ["shoulders", "chest"],
    "chest": ["chest"], "arms": ["arms"], "wrist": ["arms", "back"],
    "core": ["core"], "hip": ["legs"], "glutes": ["legs"],
    "thigh": ["legs"], "hamstring": ["legs"], "knee": ["legs"],
    "calf": ["legs"], "ankle": ["legs"], "foot": ["legs"], "general": [],
}

# Yoga-Stellungen, die bei einer Beschwerde in dieser Region vorgezogen werden.
# Die Namen muessen zu EVENING_YOGA_POOL in exercises.py passen.
RELIEF_POSES: dict[str, list[str]] = {
    "back_low": ["Kindhaltung", "Katze-Kuh", "Liegende Drehung", "Sphinx"],
    "back_up": ["Nadelöhr", "Katze-Kuh", "Liegende Drehung"],
    "neck": ["Nadelöhr", "Kindhaltung"],
    "shoulder": ["Nadelöhr", "Herabschauender Hund"],
    "chest": ["Brücke", "Sphinx"],
    "hip": ["Taube", "Schmetterling", "Brücke"],
    "glutes": ["Taube", "Nadelöhr"],
    "thigh": ["Taube", "Brücke"],
    "hamstring": ["Sitzende Vorbeuge", "Herabschauender Hund"],
    "knee": ["Beine hoch an der Wand", "Brücke"],
    "calf": ["Herabschauender Hund", "Beine hoch an der Wand"],
    "ankle": ["Beine hoch an der Wand"],
    "foot": ["Beine hoch an der Wand"],
    "core": ["Kindhaltung", "Sphinx"],
    "general": ["Beine hoch an der Wand", "Totenstellung"],
}

# Was in der Kueche hilft. Bewusst knapp und ohne Heilsversprechen.
NUTRITION_HINTS: dict[str, str] = {
    "soreness": ("Eiweiß über den Tag verteilt statt in einer Mahlzeit, und "
                 "genug trinken. Kirschsaft und Ingwer haben in Studien einen "
                 "kleinen Effekt auf Muskelkater — kein Wundermittel, aber "
                 "schaden tut es nicht."),
    "fatigue": ("Kohlenhydrate nicht zu knapp halten. Anhaltende Schwere bei "
                "ausreichendem Schlaf ist oft schlicht ein Energiedefizit."),
    "tension": ("Magnesium und Flüssigkeit prüfen — Verspannungen bei viel "
                "Training hängen häufiger daran, als man denkt."),
    "injury": ("Eiweiß und Gesamtkalorien jetzt nicht kürzen: In der Heilung "
               "braucht der Körper mehr, nicht weniger."),
}

# Schluesselwoerter fuer den Fall, dass kein Modell laeuft. Bewusst sparsam:
# lieber nichts erkennen als das Falsche.
KEYWORDS: list[tuple[tuple[str, ...], str, str]] = [
    (("rücken", "ruecken", "kreuz", "lendenwirbel"), "back_low", "pain"),
    (("nacken", "genick"), "neck", "tension"),
    (("schulter",), "shoulder", "pain"),
    (("knie",), "knee", "pain"),
    (("hüfte", "huefte"), "hip", "tension"),
    (("wade", "waden"), "calf", "soreness"),
    (("oberschenkel", "quadrizeps"), "thigh", "soreness"),
    (("hamstring", "beinrückseite", "beinrueckseite"), "hamstring", "soreness"),
    (("achilles", "sprunggelenk", "knöchel", "knoechel"), "ankle", "pain"),
    (("muskelkater",), "general", "soreness"),
    (("verspannt", "verspannung"), "back_up", "tension"),
]


def _parse_complaints(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        region = c.get("region")
        kind = c.get("kind")
        if region in REGIONS and kind in KINDS:
            out.append({"region": region, "kind": kind,
                        "severity": int(c.get("severity") or 2)})
    return out


def keyword_complaints(text: str | None) -> list[dict[str, Any]]:
    """Beschwerden aus dem Freitext raten — ohne Modell, nur Schluesselwoerter."""
    if not text:
        return []
    low = text.lower()
    found: list[dict[str, Any]] = []
    for words, region, kind in KEYWORDS:
        if any(w in low for w in words):
            if not any(f["region"] == region for f in found):
                found.append({"region": region, "kind": kind, "severity": 2})
    return found


def suggest_from_text(text: str | None) -> list[dict[str, Any]]:
    """Das Modell den Freitext lesen lassen; faellt auf Schluesselwoerter zurueck.

    Erkanntes wird nur vorgeschlagen — uebernommen wird es erst, wenn du im
    Eintrag darauf tippst.
    """
    baseline = keyword_complaints(text)
    if not text or len(text.strip()) < 8:
        return baseline
    try:
        from .ollama_client import generate_json
        data = generate_json(
            prompt=(
                "Aus dem folgenden Tagebucheintrag koerperliche Beschwerden "
                "herauslesen. Nur was wirklich dasteht, nichts hinzudichten. "
                "Antworte als JSON-Objekt mit dem Schluessel \"complaints\": eine "
                "Liste aus Objekten mit \"region\", \"kind\" und \"severity\" (1-3).\n"
                f"Erlaubte region: {', '.join(REGIONS)}\n"
                f"Erlaubte kind: {', '.join(KINDS)}\n\n"
                f"Eintrag: {text.strip()[:600]}"),
            system="Du extrahierst Daten. Du antwortest ausschliesslich mit JSON.")
        found = _parse_complaints((data or {}).get("complaints"))
        if found:
            return found
    except Exception as e:
        log.debug("Freitext-Auswertung ohne Modell: %s", e)
    return baseline


def record(data: dict[str, Any]) -> dict[str, Any]:
    stamp = data.get("recorded_at")
    try:
        when = dt.datetime.fromisoformat(stamp) if stamp else dt.datetime.now()
    except ValueError:
        when = dt.datetime.now()

    def _scale(key: str) -> int | None:
        value = data.get(key)
        if value is None:
            return None
        try:
            return max(1, min(5, int(value)))
        except (TypeError, ValueError):
            return None

    row = {
        "day": when.date().isoformat(),
        "recorded_at": when.isoformat(timespec="seconds"),
        "mood": _scale("mood"), "energy": _scale("energy"), "stress": _scale("stress"),
        "note": (data.get("note") or "").strip() or None,
        "complaints": json.dumps(_parse_complaints(data.get("complaints")),
                                 ensure_ascii=False),
    }
    with get_db() as db:
        cur = db.execute(
            f"INSERT INTO mood_entries({', '.join(row)}) "
            f"VALUES({', '.join(':' + k for k in row)})", row)
        row["id"] = cur.lastrowid
    row["complaints"] = json.loads(row["complaints"])
    return row


def delete(entry_id: int) -> bool:
    with get_db() as db:
        return db.execute("DELETE FROM mood_entries WHERE id=?",
                          (entry_id,)).rowcount > 0


def entries(days: int = 30, limit: int = 200) -> list[dict[str, Any]]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM mood_entries WHERE day >= ? "
            "ORDER BY recorded_at DESC LIMIT ?", (since, limit)).fetchall()
    out = rows_to_dicts(rows)
    for row in out:
        row["complaints"] = _parse_complaints(row.get("complaints"))
        row["complaint_labels"] = [
            f"{REGIONS[c['region']]}: {KINDS[c['kind']]}" for c in row["complaints"]]
    return out


def active_complaints(as_of: str | None = None) -> list[dict[str, Any]]:
    """Beschwerden, die noch nachwirken — je Region die juengste Meldung.

    Ein Muskelkater von vorgestern zaehlt noch, einer von letzter Woche nicht
    mehr. Schmerz wirkt laenger nach als Muskelkater (siehe DECAY_DAYS).
    """
    today = dt.date.fromisoformat(as_of) if as_of else dt.date.today()
    recent = entries(days=max(DECAY_DAYS.values()))
    seen: dict[str, dict[str, Any]] = {}
    for entry in recent:                      # neueste zuerst
        try:
            age = (today - dt.date.fromisoformat(entry["day"])).days
        except ValueError:
            continue
        if age < 0:
            continue
        for c in entry["complaints"]:
            if age > DECAY_DAYS.get(c["kind"], 3):
                continue
            key = c["region"]
            if key in seen:
                continue
            seen[key] = {
                **c, "age_days": age, "day": entry["day"],
                "region_label": REGIONS[c["region"]], "kind_label": KINDS[c["kind"]],
                "note": entry.get("note"),
            }
    return sorted(seen.values(),
                  key=lambda c: (-c["severity"], c["age_days"]))


def adaptations(as_of: str | None = None) -> dict[str, Any]:
    """Was aus den aktuellen Beschwerden fuers Training folgt."""
    active = active_complaints(as_of)
    spare_groups: set[str] = set()
    poses: list[str] = []
    notes: list[str] = []
    easy_run = False

    for c in active:
        for group in SPARE_GROUPS.get(c["region"], []):
            # Muskelkater heisst dosieren, Schmerz heisst aussetzen.
            if c["kind"] in ("pain", "injury") or c["severity"] >= 3:
                spare_groups.add(group)
        for pose in RELIEF_POSES.get(c["region"], []):
            if pose not in poses:
                poses.append(pose)
        hint = NUTRITION_HINTS.get(c["kind"])
        if hint and hint not in notes:
            notes.append(hint)
        if c["region"] in ("knee", "calf", "ankle", "foot", "hamstring") and \
                c["kind"] in ("pain", "injury"):
            easy_run = True

    lines = []
    for c in active:
        what = "aussetzen" if c["kind"] in ("pain", "injury") else "dosieren"
        lines.append(f"{c['region_label']}: {c['kind_label']} "
                     f"(vor {c['age_days']} Tag{'en' if c['age_days'] != 1 else ''}) "
                     f"— betroffene Muskelgruppen {what}")

    return {
        "complaints": active,
        "spare_groups": sorted(spare_groups),
        "relief_poses": poses[:6],
        "nutrition": notes,
        "easy_run": easy_run,
        "summary": lines,
    }


def trend(days: int = 30) -> dict[str, Any]:
    """Stimmung, Energie und Stress als Tagesmittel."""
    rows = entries(days)
    per_day: dict[str, dict[str, list[int]]] = {}
    for r in rows:
        bucket = per_day.setdefault(r["day"], {"mood": [], "energy": [], "stress": []})
        for key in bucket:
            if r.get(key) is not None:
                bucket[key].append(r[key])
    points = []
    for day in sorted(per_day):
        b = per_day[day]
        points.append({
            "day": day,
            **{k: round(sum(v) / len(v), 2) if v else None for k, v in b.items()},
            "count": max(len(v) for v in b.values()) if any(b.values()) else 0,
        })
    return {"points": points, "entries": len(rows)}
