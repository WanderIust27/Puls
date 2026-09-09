"""Massnahmen gegen ein Tief — und was davon bei dir tatsaechlich hilft.

Wer schlecht drauf ist, braucht keine Motivationssprueche, sondern etwas
Konkretes fuer die naechste Stunde. Die Liste hier ist kuratiert: jede
Massnahme laesst sich sofort tun, und jede hat einen nachvollziehbaren Grund.

Der zweite Teil ist der wichtigere: PULS merkt sich, was du hinterher als
hilfreich bewertet hast, und zieht das beim naechsten Mal vor. Was zweimal
nichts gebracht hat, kommt seltener. So wird aus einer allgemeinen Liste mit
der Zeit deine Liste.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, rows_to_dicts

log = logging.getLogger("puls.boosters")

# Lagen, auf die eine Massnahme passt
LOW_MOOD, LOW_ENERGY, HIGH_STRESS, POOR_SLEEP, SORENESS = (
    "low_mood", "low_energy", "high_stress", "poor_sleep", "soreness")

BOOSTERS: list[dict[str, Any]] = [
    # --- Bewegung ---------------------------------------------------------
    dict(id="walk_daylight", kind="movement", minutes=15,
         name="15 Minuten raus, ohne Kopfhörer",
         text="Tageslicht am Morgen ist der stärkste Taktgeber für den "
              "Schlaf-Wach-Rhythmus, den du ohne Aufwand bedienen kannst. "
              "Nicht laufen — gehen. Es geht ums Licht, nicht um Belastung.",
         tags=[LOW_MOOD, LOW_ENERGY, POOR_SLEEP]),
    dict(id="easy_shakeout", kind="movement", minutes=20,
         name="20 Minuten ganz locker traben",
         text="Deutlich langsamer als dein lockeres Tempo — so langsam, dass "
              "es sich fast albern anfühlt. Nach einer schlechten Nacht bringt "
              "das mehr als die geplante Einheit, und es kostet nichts.",
         tags=[LOW_ENERGY, LOW_MOOD]),
    dict(id="mobility_break", kind="movement", minutes=8,
         name="Acht Minuten Katze-Kuh, Taube, Brücke",
         text="Gegen das Sitzen. Die Hüftbeuger verkürzen über den Tag, und "
              "das schlägt auf Haltung und Stimmung durch, bevor man es merkt.",
         tags=[LOW_MOOD, HIGH_STRESS, SORENESS]),
    dict(id="breath_478", kind="routine", minutes=5,
         name="Fünf Minuten ruhig atmen, vier ein, sechs aus",
         text="Ein längeres Ausatmen als Einatmen senkt die Herzfrequenz "
              "messbar. Das ist der schnellste Weg, den Stresspegel zu drücken, "
              "und du kannst ihn im Sitzen gehen.",
         tags=[HIGH_STRESS, LOW_MOOD]),
    dict(id="kettlebell_short", kind="movement", minutes=10,
         name="Zehn Minuten Kettlebell Swings",
         text="Kurz, hart, vorbei. Wenn die Lustlosigkeit vom Nichtstun kommt "
              "statt von echter Müdigkeit, bricht das den Zustand am "
              "zuverlässigsten auf — und zehn Minuten schafft man immer.",
         tags=[LOW_MOOD, LOW_ENERGY]),

    # --- Ernährung --------------------------------------------------------
    dict(id="protein_breakfast", kind="nutrition", minutes=5,
         name="Frühstück mit 30 g Eiweiß",
         text="Skyr mit Beeren, Quark, Rührei. Ein Frühstück, das fast nur aus "
              "Kohlenhydraten besteht, sorgt zwei Stunden später für genau das "
              "Loch, das du gerade spürst.",
         tags=[LOW_ENERGY, LOW_MOOD]),
    dict(id="hydrate", kind="nutrition", minutes=1,
         name="Einen halben Liter Wasser, jetzt",
         text="Zwei Prozent Flüssigkeitsdefizit reichen für spürbar schlechtere "
              "Stimmung und Konzentration. Das ist der billigste Test, den es "
              "gibt: trinken und in zwanzig Minuten nachspüren.",
         tags=[LOW_ENERGY, LOW_MOOD, SORENESS]),
    dict(id="carbs_evening", kind="nutrition", minutes=20,
         name="Abends Kohlenhydrate nicht streichen",
         text="Reis, Kartoffeln oder Nudeln zum Abendessen. Sie helfen beim "
              "Einschlafen und füllen die Speicher für den Morgenlauf — bei "
              "deinem Pensum ist Kohlenhydrate-Sparen am Abend die falsche "
              "Baustelle.",
         tags=[POOR_SLEEP, LOW_ENERGY]),
    dict(id="caffeine_cutoff", kind="routine", minutes=1,
         name="Nach 14 Uhr kein Koffein mehr",
         text="Koffein hat eine Halbwertszeit von rund fünf Stunden. Der Kaffee "
              "um 16 Uhr wirkt um Mitternacht noch zur Hälfte — auch wenn du "
              "problemlos einschläfst, wird der Tiefschlaf flacher.",
         tags=[POOR_SLEEP, HIGH_STRESS]),
    dict(id="magnesium_sour_cherry", kind="nutrition", minutes=3,
         name="Sauerkirschsaft oder Magnesium am Abend",
         text="Für beides gibt es Studien mit kleinem, aber echtem Effekt auf "
              "Muskelkater und Schlafqualität. Kein Wundermittel — aber wenn "
              "ohnehin nichts dagegen spricht, ist es billig zu probieren.",
         tags=[SORENESS, POOR_SLEEP]),

    # --- Routine ----------------------------------------------------------
    dict(id="screens_off", kind="routine", minutes=30,
         name="Eine halbe Stunde vor dem Schlafen kein Bildschirm",
         text="Nicht wegen des blauen Lichts — wegen dem, was auf dem Schirm "
              "passiert. Das Wachhalten kommt vom Inhalt, nicht von der "
              "Farbtemperatur.",
         tags=[POOR_SLEEP, HIGH_STRESS]),
    dict(id="one_thing", kind="routine", minutes=2,
         name="Eine Sache aufschreiben, die heute reicht",
         text="An einem schlechten Tag ist die Liste das Problem, nicht die "
              "Energie. Eine einzige Sache, die zählt — der Rest darf warten.",
         tags=[LOW_MOOD, HIGH_STRESS]),
    dict(id="early_night", kind="routine", minutes=1,
         name="Heute eine Stunde früher ins Bett",
         text="Die billigste Leistungssteigerung, die es gibt. Kein Training "
              "gleicht chronisch zu wenig Schlaf aus, und keine Ernährung.",
         tags=[POOR_SLEEP, LOW_ENERGY, LOW_MOOD]),
]

# Ab so vielen Bewertungen wird eine Massnahme nach Erfahrung sortiert statt
# nach der Standardreihenfolge.
MIN_RATINGS = 2

# Wie lange ein Vorschlag stehen bleibt. Ein Tag ist zu lang — abends hilft
# etwas anderes als morgens. Zwei Stunden sind kurz genug, dass es mitgeht,
# und lang genug, dass die Karte nicht bei jedem Blick springt.
SLOT_HOURS = 2


def _by_id(tip_id: str) -> dict[str, Any] | None:
    return next((b for b in BOOSTERS if b["id"] == tip_id), None)


def situation(as_of: str | None = None) -> dict[str, Any]:
    """Woran hakt es gerade? Aus Befinden und Erholungsdaten abgeleitet."""
    tags: list[str] = []
    reasons: list[str] = []

    from . import metrics, mood
    try:
        recent = mood.entries(3)[:3]
    except Exception:
        recent = []
    if recent:
        def avg(key: str) -> float | None:
            values = [r[key] for r in recent if r.get(key) is not None]
            return sum(values) / len(values) if values else None
        m, e, st = avg("mood"), avg("energy"), avg("stress")
        if m is not None and m <= 2.5:
            tags.append(LOW_MOOD)
            reasons.append(f"Stimmung zuletzt {m:.1f} von 5")
        if e is not None and e <= 2.5:
            tags.append(LOW_ENERGY)
            reasons.append(f"Energie zuletzt {e:.1f} von 5")
        if st is not None and st >= 3.5:
            tags.append(HIGH_STRESS)
            reasons.append(f"Stress zuletzt {st:.1f} von 5")

    try:
        rec = metrics.recovery_series(21)
        latest, base = rec["latest"], rec["baselines"]
        sleep = latest.get("sleep_seconds")
        if sleep and sleep < 6.5 * 3600:
            tags.append(POOR_SLEEP)
            reasons.append(f"nur {sleep / 3600:.1f} h Schlaf")
        stress = latest.get("stress_avg")
        if stress is not None and stress >= 40 and HIGH_STRESS not in tags:
            tags.append(HIGH_STRESS)
            reasons.append(f"Stressmittel {stress:.0f}")
        hrv = base.get("hrv_avg") or {}
        if hrv.get("delta") is not None and hrv["delta"] < -3 \
                and LOW_ENERGY not in tags:
            tags.append(LOW_ENERGY)
            reasons.append(f"HRV {hrv['delta']:.0f} ms unter deinem Schnitt")
    except Exception as e:
        log.debug("Erholungsdaten nicht verfuegbar: %s", e)

    try:
        for c in mood.active_complaints(as_of):
            if c["kind"] in ("soreness", "fatigue"):
                tags.append(SORENESS)
                reasons.append(f"{c['region_label']}: {c['kind_label']}")
                break
    except Exception:
        pass

    return {"tags": sorted(set(tags)), "reasons": reasons}


# Tageszeiten, in denen erfahrungsgemaess Verschiedenes hilft. Ein Spaziergang
# um acht Uhr morgens ist etwas anderes als ein Spaziergang um elf Uhr abends.
DAYPARTS = [(5, 10, "morgens"), (10, 14, "mittags"), (14, 18, "nachmittags"),
            (18, 23, "abends")]
MIN_PART_RATINGS = 2      # so viele Bewertungen braucht eine Tageszeit


def daypart(hour: int | None = None) -> str:
    hour = dt.datetime.now().hour if hour is None else hour
    for start, end, name in DAYPARTS:
        if start <= hour < end:
            return name
    return "nachts"


def _slot_hour(slot: str | None) -> int | None:
    """Aus '2026-09-09#10' die Stunde zurueckrechnen."""
    if not slot or "#" not in slot:
        return None
    try:
        return int(slot.rsplit("#", 1)[1]) * SLOT_HOURS
    except ValueError:
        return None


def effectiveness(part: str | None = None) -> dict[str, dict[str, Any]]:
    """Wie oft hat welche Massnahme geholfen?

    Mit part nur die Bewertungen aus dieser Tageszeit. Das ist der Unterschied
    zwischen "hat dir schon geholfen" und "hat dir abends schon geholfen" —
    und abends ist die Frage eine andere als morgens.
    """
    with get_db() as db:
        if part:
            raw = db.execute(
                "SELECT tip_id, slot, helpful FROM tip_log WHERE slot IS NOT NULL"
            ).fetchall()
            counts: dict[str, dict[str, int]] = {}
            for r in raw:
                hour = _slot_hour(r["slot"])
                if hour is None or daypart(hour) != part:
                    continue
                c = counts.setdefault(r["tip_id"], {"gut": 0, "schlecht": 0,
                                                    "bewertet": 0, "gezeigt": 0})
                c["gezeigt"] += 1
                if r["helpful"] == 1:
                    c["gut"] += 1
                    c["bewertet"] += 1
                elif r["helpful"] == -1:
                    c["schlecht"] += 1
                    c["bewertet"] += 1
            return {
                tip: {**c, "score": round(c["gut"] / c["bewertet"], 2)
                      if c["bewertet"] >= MIN_PART_RATINGS else 0.5,
                      "part": part}
                for tip, c in counts.items()}

        rows = db.execute(
            """SELECT tip_id,
                      SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END) AS gut,
                      SUM(CASE WHEN helpful = -1 THEN 1 ELSE 0 END) AS schlecht,
                      COUNT(helpful) AS bewertet, COUNT(*) AS gezeigt
               FROM tip_log GROUP BY tip_id""").fetchall()
    out = {}
    for r in rows:
        rated = r["bewertet"] or 0
        # Ohne Bewertungen bleibt es bei 0.5 — weder bevorzugt noch benachteiligt
        score = 0.5 if rated < MIN_RATINGS else r["gut"] / rated
        out[r["tip_id"]] = {"gut": r["gut"], "schlecht": r["schlecht"],
                            "bewertet": rated, "gezeigt": r["gezeigt"],
                            "score": round(score, 2)}
    return out


def _slot(now: dt.datetime | None = None) -> str:
    """Kennung des aktuellen Zwei-Stunden-Fensters."""
    now = now or dt.datetime.now()
    return f"{now.date().isoformat()}#{now.hour // SLOT_HOURS:02d}"


def suggest(count: int = 3, as_of: str | None = None,
            now: dt.datetime | None = None) -> dict[str, Any]:
    """Passende Massnahmen — bewaehrte zuerst.

    Die Auswahl steht fuer zwei Stunden fest. Kuerzer waere unruhig (die Karte
    spraenge bei jedem Blick), laenger unpassend (abends hilft etwas anderes
    als morgens). Ausserdem wird jede Anzeige protokolliert: Waere die Auswahl
    jedes Mal neu, waeren nach ein paar Aufrufen alle Massnahmen als "gezeigt"
    vermerkt, obwohl nur drei zu sehen waren — das wuerde die Lernstatistik
    verwaessern.
    """
    ctx = situation(as_of)
    stats = effectiveness()
    now = now or dt.datetime.now()
    part = daypart(now.hour)
    part_stats = effectiveness(part)
    day = as_of or now.date().isoformat()
    slot = _slot(now)

    # Steht die Auswahl fuer dieses Fenster schon? Dann genau die zurueckgeben.
    with get_db() as db:
        slot_ids = [r["tip_id"] for r in db.execute(
            "SELECT tip_id FROM tip_log WHERE slot = ? ORDER BY id",
            (slot,)).fetchall()]
        # Was in den letzten Fenstern des Tages schon dran war, nicht erneut
        recent_ids = {r["tip_id"] for r in db.execute(
            "SELECT tip_id FROM tip_log WHERE day = ? AND slot != ?",
            (day, slot)).fetchall()}
    chosen = [b for b in (_by_id(i) for i in slot_ids) if b][:count]

    if len(chosen) < count:
        def score(b: dict[str, Any]) -> float:
            hits = len(set(b["tags"]) & set(ctx["tags"]))
            if not hits:
                return -1.0
            stat = stats.get(b["id"], {})
            value = hits + (stat.get("score", 0.5) - 0.5) * 4
            # Was zu DIESER Tageszeit geholfen hat, wiegt schwerer als der
            # Schnitt über alle Stunden — aber nur, wenn es dafür genug
            # Bewertungen gibt. Sonst entschiede eine einzelne gute Nacht.
            here = part_stats.get(b["id"], {})
            if here.get("bewertet", 0) >= MIN_PART_RATINGS:
                value += (here["score"] - 0.5) * 6
            return value

        taken = {b["id"] for b in chosen}
        pool = [b for b in BOOSTERS if b["id"] not in taken and score(b) > -1]
        # Erst das, was heute noch nicht dran war; reicht das nicht, darf
        # auch Wiederholtes kommen.
        unused = [b for b in pool if b["id"] not in recent_ids]
        ranked = sorted(unused or pool, key=lambda b: -score(b))
        fresh = ranked[:count - len(chosen)]
        if fresh:
            with get_db() as db:
                for b in fresh:
                    db.execute(
                        "INSERT INTO tip_log(tip_id, context, day, slot) "
                        "VALUES(?,?,?,?)",
                        (b["id"], ",".join(ctx["tags"]), day, slot))
        chosen += fresh

    def note(b: dict[str, Any]) -> str | None:
        """Warum steht das hier — in einem Satz, aus den Zahlen."""
        here = part_stats.get(b["id"], {})
        if here.get("bewertet", 0) >= MIN_PART_RATINGS:
            return (f"hat dir {part} {here['gut']} von {here['bewertet']} Mal "
                    f"geholfen")
        overall = stats.get(b["id"], {})
        if overall.get("bewertet", 0) >= MIN_RATINGS:
            return (f"hat dir {overall['gut']} von {overall['bewertet']} Mal "
                    f"geholfen")
        return None

    return {
        "situation": ctx,
        "daypart": part,
        "boosters": [{**b, "stats": stats.get(b["id"]),
                      "part_stats": part_stats.get(b["id"]),
                      "why": note(b)} for b in chosen],
        "learned": sum(1 for v in stats.values() if v["bewertet"] >= MIN_RATINGS),
        "slot": slot,
        "next_change": (now.replace(minute=0, second=0, microsecond=0)
                        + dt.timedelta(hours=SLOT_HOURS - now.hour % SLOT_HOURS)
                        ).strftime("%H:%M"),
    }


def rate(tip_id: str, helpful: bool, day: str | None = None) -> bool:
    """Rueckmeldung zu einer Massnahme — daraus lernt die Auswahl."""
    if not _by_id(tip_id):
        return False
    day = day or dt.date.today().isoformat()
    with get_db() as db:
        row = db.execute(
            "SELECT id FROM tip_log WHERE tip_id=? AND helpful IS NULL "
            "ORDER BY id DESC LIMIT 1", (tip_id,)).fetchone()
        if row:
            db.execute("UPDATE tip_log SET helpful=?, rated_at=datetime('now') "
                       "WHERE id=?", (1 if helpful else -1, row["id"]))
        else:
            db.execute(
                "INSERT INTO tip_log(tip_id, day, helpful, rated_at) "
                "VALUES(?,?,?, datetime('now'))",
                (tip_id, day, 1 if helpful else -1))
    return True


def what_works(limit: int = 5) -> list[dict[str, Any]]:
    """Was bei dir nachweislich hilft — fuer den Coach und die Anzeige."""
    stats = effectiveness()
    out = []
    for tip_id, stat in stats.items():
        if stat["bewertet"] < MIN_RATINGS:
            continue
        booster = _by_id(tip_id)
        if not booster:
            continue
        out.append({"id": tip_id, "name": booster["name"], "kind": booster["kind"],
                    **stat})
    out.sort(key=lambda o: (-o["score"], -o["bewertet"]))
    return out[:limit]


def open_ratings(limit: int = 3) -> list[dict[str, Any]]:
    """Massnahmen von gestern, zu denen noch keine Rueckmeldung vorliegt."""
    since = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT * FROM tip_log WHERE helpful IS NULL AND day >= ? AND day <= ? "
            "ORDER BY id DESC LIMIT ?", (since, yesterday, limit)).fetchall())
    out = []
    for r in rows:
        booster = _by_id(r["tip_id"])
        if booster:
            out.append({**r, "name": booster["name"], "kind": booster["kind"]})
    return out
