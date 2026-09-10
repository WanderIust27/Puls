"""Wochenplaner: baut aus Bibliothek + Progression + Laufzonen die echte Woche.

Thomas' Struktur:
  - jeden Morgen 20–30 min Laufen (überwiegend locker, ein Qualitätsreiz/Woche)
  - 3× pro Woche abends Gym, 60–90 min:
        Kettlebell-Auftakt → Maschinen-Hauptteil → Klimmzug-Arbeit → Dehnen
  - jeden Abend eine kurze Yoga-/Dehneinheit vor dem Schlafen

Die Gewichte und Wiederholungen kommen aus der Progression, nicht vom LLM.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
from typing import Any

from ..db import get_db, get_setting
from . import exercises as ex_lib
from . import mood
from . import running

log = logging.getLogger("puls.planner")

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Ausgangsverteilung der Übungen auf die Blöcke, je nach verfügbarer Zeit.
# Sie ist nur der Startpunkt: Wie lang die Einheit wirklich wird, hängt an
# Sätzen, Wiederholungen und Pausen der konkret gewählten Übungen. Deshalb wird
# hinterher nachgerechnet und angepasst (siehe _fit_to_minutes).
BLOCK_SIZES = {
    45: {"kettlebell": 1, "main": 3, "pullup": 1, "stretch": 2},
    60: {"kettlebell": 2, "main": 4, "pullup": 1, "stretch": 3},
    75: {"kettlebell": 2, "main": 5, "pullup": 2, "stretch": 4},
    90: {"kettlebell": 3, "main": 6, "pullup": 2, "stretch": 5},
    105: {"kettlebell": 3, "main": 7, "pullup": 3, "stretch": 5},
    120: {"kettlebell": 3, "main": 9, "pullup": 3, "stretch": 6},
}

# Wie lange eine Wiederholung dauert. Zwei Sekunden hoch, zwei runter, plus
# Ansetzen — grob, aber deutlich näher an der Wahrheit als sie zu ignorieren.
SECONDS_PER_REP = 3.5
# Umsetzen, Gewicht einstellen, Gerät suchen: zwischen zwei Übungen vergeht
# Zeit, die in keinem Satz steht.
CHANGEOVER_S = 45
TOLERANCE = 0.07          # ±7 % gelten als getroffen


def _weekday_of(date: dt.date) -> str:
    return WEEKDAYS[date.weekday()]


def _block_sizes(minutes: int) -> dict[str, int]:
    key = min(BLOCK_SIZES, key=lambda k: abs(k - minutes))
    return dict(BLOCK_SIZES[key])


def step_seconds(steps: list[dict[str, Any]], depth: int = 0) -> float:
    """Wie lange diese Schritte tatsächlich dauern.

    Wiederholungen zählen mit SECONDS_PER_REP, Pausen und Zeitübungen mit ihrer
    Dauer, dazu je Übung ein Umsetzen. Das ist eine Schätzung — aber eine, die
    nachrechenbar ist, statt einer Zahl im Namen, die niemand geprüft hat.
    """
    total = 0.0
    for step in steps:
        if step.get("type") == "repeat":
            total += int(step.get("count", 1)) * step_seconds(step.get("steps", []),
                                                              depth + 1)
            if depth == 0:
                total += CHANGEOVER_S
            continue
        if step.get("duration_s"):
            total += float(step["duration_s"])
        elif step.get("reps"):
            total += float(step["reps"]) * SECONDS_PER_REP
        if depth == 0 and step.get("type") == "work":
            total += CHANGEOVER_S
    return total


def _fit_to_minutes(build, minutes: int, sizes: dict[str, int]
                    ) -> tuple[list[dict[str, Any]], dict[str, int], float]:
    """Übungen zufügen oder wegnehmen, bis die Einheit die Zeit trifft.

    build(sizes) liefert die Schritte für eine Verteilung. Angepasst wird in
    der Reihenfolge, in der es am wenigsten weh tut: erst der Hauptteil, dann
    Kettlebell und Klimmzüge, das Dehnen zuletzt.
    """
    target = minutes * 60
    order = ["main", "kettlebell", "pullup", "stretch"]
    limits = {"main": (2, 10), "kettlebell": (0, 4), "pullup": (0, 3),
              "stretch": (1, 6)}
    steps = build(sizes)
    best = (abs(step_seconds(steps) - target), dict(sizes), steps)

    for _ in range(12):
        actual = step_seconds(steps)
        if abs(actual - target) <= target * TOLERANCE:
            break
        grow = actual < target
        for key in order:
            low, high = limits[key]
            nxt = sizes[key] + (1 if grow else -1)
            if not low <= nxt <= high:
                continue
            trial = dict(sizes, **{key: nxt})
            trial_steps = build(trial)
            # Nur übernehmen, wenn die Änderung tatsächlich etwas bewirkt hat;
            # sonst dreht man an einem Block, dessen Pool erschöpft ist.
            if step_seconds(trial_steps) == actual:
                continue
            sizes, steps = trial, trial_steps
            break
        else:
            break                      # nichts mehr zu drehen
        gap = abs(step_seconds(steps) - target)
        if gap < best[0]:
            best = (gap, dict(sizes), steps)

    if abs(step_seconds(steps) - target) > best[0]:
        _, sizes, steps = best
    return steps, sizes, step_seconds(steps)


def _rest_days(ex: dict[str, Any]) -> int:
    d = ex_lib.days_since(ex.get("last_performed"))
    return 99 if d is None else d


# ------------------------------------------------------- Kraft-Session bauen

def _exercise_to_steps(ex: dict[str, Any]) -> list[dict[str, Any]]:
    """Eine Übung in unser Step-Format übersetzen — mit aktuellen Zielwerten."""
    note_bits = []
    if ex.get("machine_setting"):
        note_bits.append(ex["machine_setting"])
    if ex.get("notes"):
        note_bits.append(ex["notes"])
    notes = " · ".join(note_bits) or None

    if ex["mode"] == "time":
        work = {"type": "work", "name": ex["name"],
                "duration_s": ex.get("target_duration_s") or 30, "notes": notes}
        if ex.get("weight_kg"):
            work["weight_kg"] = ex["weight_kg"]
    else:
        work = {"type": "work", "name": ex["name"], "reps": ex["target_reps"],
                "notes": notes}
        if ex.get("weight_kg"):
            work["weight_kg"] = ex["weight_kg"]

    sets = max(1, int(ex.get("sets") or 3))
    if sets == 1:
        return [work]
    rest = {"type": "rest", "name": "Pause", "duration_s": int(ex.get("rest_s") or 90)}
    return [{"type": "repeat", "count": sets, "steps": [work, rest]}]


def _pick(pool: list[dict[str, Any]], count: int, seed_key: str) -> list[dict[str, Any]]:
    """Wählt Übungen: Priorität 1 immer, danach die am längsten nicht trainierten."""
    must = [e for e in pool if e.get("priority") == 1]
    rest = [e for e in pool if e.get("priority") != 1]
    rest.sort(key=lambda e: (-_rest_days(e), e.get("priority", 2), e["sort_order"]))
    chosen = must[:count]
    for e in rest:
        if len(chosen) >= count:
            break
        chosen.append(e)
    chosen.sort(key=lambda e: e["sort_order"])
    return chosen


def _balance_main(pool: list[dict[str, Any]], count: int,
                  emphasis: list[str] | None = None,
                  dominate: bool = False) -> list[dict[str, Any]]:
    """Hauptteil so wählen, dass die Muskelgruppen über die Woche abgedeckt sind.

    dominate=True heisst: Der Schwerpunkt ist ausdruecklich gewuenscht (aus
    einem Wunsch wie „Sixpack-Training"), nicht bloss vom Bedarf abgeleitet.
    Dann kommt der Grossteil aus diesen Gruppen, statt reihum durch alle zu
    gehen — wer eine Bauch-Einheit will, will nicht eine Bauchuebung von
    sechsen.
    """
    prefer_machines = get_setting("prefer_machines", "1") == "1"
    order = ["legs", "chest", "back", "shoulders", "arms", "core"]
    # Zuerst, was gerade am ehesten dran ist: der gerechnete Bedarf aus den
    # Trends, danach eine übernommene Empfehlung des Coaches.
    focus = [g for g in (emphasis or []) if g in order]
    try:
        from . import suggestions
        focus += [g for g in suggestions.active_focus()
                  if g in order and g not in focus]
    except Exception:
        pass
    if focus:
        order = focus + [g for g in order if g not in focus]
    by_group: dict[str, list[dict[str, Any]]] = {g: [] for g in order}
    for e in pool:
        by_group.setdefault(e["muscle_group"], []).append(e)
    for g, lst in by_group.items():
        lst.sort(key=lambda e: (
            0 if (prefer_machines and e["equipment"] in ("machine", "cable")) else 1,
            -_rest_days(e), e["sort_order"]))
    chosen: list[dict[str, Any]] = []

    if dominate and focus:
        # Erst die gewuenschten Gruppen ausschoepfen — bis auf einen Rest, der
        # den Koerper nicht einseitig laesst. Zwei Uebungen fuer alles andere
        # sind kein Ganzkoerpertraining, aber sie halten die Woche im Lot.
        keep_free = 1 if count <= 4 else 2
        room = max(1, count - keep_free)
        # Reihum durch die gewuenschten Gruppen, damit bei zwei Gruppen nicht
        # die erste alles bekommt.
        pools = [list(by_group.get(g) or []) for g in focus]
        while len(chosen) < room and any(pools):
            for lst in pools:
                if len(chosen) >= room:
                    break
                if lst:
                    chosen.append(lst.pop(0))

    # Danach (oder ohne Schwerpunkt) reihum: eine Übung pro Gruppe, dann auffüllen
    round_no = 0
    taken = {e["id"] for e in chosen}
    while len(chosen) < count and round_no < 4:
        for g in order:
            if len(chosen) >= count:
                break
            lst = [e for e in (by_group.get(g) or []) if e["id"] not in taken]
            if len(lst) > round_no:
                chosen.append(lst[round_no])
                taken.add(lst[round_no]["id"])
        round_no += 1

    # Matte vor Maschine: Nach dem Aufwärmen liegt man ohnehin schon, und die
    # Geräte sind später frei. Innerhalb dessen die eigene Reihenfolge.
    chosen.sort(key=lambda e: (0 if e.get("equipment") == "bodyweight" else 1,
                               e["sort_order"]))
    return chosen[:count]


def build_gym_session(minutes: int | None = None, name: str | None = None,
                      emphasis: list[str] | None = None,
                      dominate: bool = False) -> dict[str, Any]:
    """Eine komplette Gym-Einheit nach Thomas' Aufbau.

    emphasis nennt die Muskelgruppen, die zuerst drankommen sollen — der
    Autopilot leitet sie aus den Trends ab. Ohne Angabe bleibt es bei der
    ausgewogenen Reihum-Verteilung.

    dominate=True heisst: Der Schwerpunkt kommt aus einem ausdruecklichen
    Wunsch („Sixpack-Training"), nicht aus dem gerechneten Bedarf. Dann traegt
    er den Hauptteil, statt nur vorne zu stehen.
    """
    minutes = minutes or int(get_setting("gym_minutes", "75") or 75)
    sizes = _block_sizes(minutes)
    lib = ex_lib.list_exercises(only_active=True)

    # Bei einem ausdruecklichen Schwerpunkt schrumpfen Auftakt und
    # Klimmzugarbeit zugunsten des Hauptteils: Wer eine Bauch-Einheit will,
    # will kein halbes Ganzkoerpertraining mit angehaengten Sit-ups. Ein
    # Kettlebell-Satz bleibt als Aufwaermen stehen.
    if dominate:
        freed = max(0, sizes["kettlebell"] - 1) + sizes["pullup"]
        sizes["kettlebell"] = min(1, sizes["kettlebell"])
        sizes["pullup"] = 0
        sizes["main"] += freed

    # Gemeldete Beschwerden gehen direkt in den Plan: betroffene Muskelgruppen
    # fallen heraus, statt dass du sie selbst wegklickst. Bleibt danach zu
    # wenig uebrig, wird die Einschraenkung wieder aufgehoben — eine Einheit
    # aus zwei Uebungen hilft niemandem.
    adapt = mood.adaptations()
    spared = set(adapt["spare_groups"])
    skipped: list[str] = []
    if spared:
        keep = [e for e in lib if e.get("muscle_group") not in spared
                or e.get("slot") in ("cardio", "stretch")]
        main_left = [e for e in keep if (e.get("slot") or "main") == "main"]
        if len(main_left) >= max(2, sizes["main"]):
            skipped = sorted({e["muscle_group"] for e in lib
                              if e.get("muscle_group") in spared})
            lib = keep
        else:
            spared = set()

    by_slot: dict[str, list[dict[str, Any]]] = {}
    for e in lib:
        by_slot.setdefault(e.get("slot") or "main", []).append(e)
    # Matten-Übungen gehören auch ins Studio. Sit-ups, Planken und Seitstütz
    # braucht kein Gerät — sie im Studio wegzulassen hiesse, eine Bauch-Einheit
    # aus dem zu bauen, was zufällig an einer Maschine hängt.
    by_slot["main"] = (by_slot.get("main") or []) + (by_slot.get("mat") or [])

    used: list[dict[str, Any]] = []

    def assemble(sz: dict[str, int]) -> list[dict[str, Any]]:
        """Die Einheit für eine bestimmte Verteilung bauen.

        Wird von _fit_to_minutes mehrfach aufgerufen, bis die Dauer passt —
        deshalb steht hier alles, was von der Verteilung abhängt, und nichts,
        was nebenbei etwas verändert.
        """
        used.clear()
        out: list[dict[str, Any]] = []

        # 1. Aufwärmen
        warm = by_slot.get("cardio") or []
        if warm:
            w = warm[0]
            out.append({"type": "warmup", "name": w["name"],
                        "duration_s": min(w.get("target_duration_s") or 480, 480),
                        "notes": "Locker starten, Puls hochfahren"})
        else:
            out.append({"type": "warmup", "name": "Aufwärmen", "duration_s": 480})

        # 2. Kettlebell-Auftakt
        for e in _pick(by_slot.get("kettlebell", []), sz["kettlebell"], "kb"):
            out.extend(_exercise_to_steps(e))
            used.append(e)

        # 3. Klimmzug-Arbeit — früh, solange du frisch bist
        for e in _pick(by_slot.get("pullup", []), sz["pullup"], "pu"):
            out.extend(_exercise_to_steps(e))
            used.append(e)

        # 4. Hauptteil an den Maschinen
        for e in _balance_main(by_slot.get("main", []), sz["main"], emphasis,
                               dominate=dominate):
            out.extend(_exercise_to_steps(e))
            used.append(e)

        # 5. Dehnen zum Abschluss
        for e in _pick(by_slot.get("stretch", []), sz["stretch"], "st"):
            out.append({"type": "cooldown", "name": e["name"],
                        "duration_s": e.get("target_duration_s") or 40,
                        "notes": e.get("notes")})
            used.append(e)
        return out

    # Die Verteilung ist nur der Startwert. Wie lang die Einheit wirklich wird,
    # steht erst fest, wenn die Übungen gewählt sind — also wird nachgerechnet
    # und angepasst, bis die Dauer die Vorgabe trifft.
    steps, sizes, seconds = _fit_to_minutes(assemble, minutes, sizes)
    actual_minutes = round(seconds / 60)

    groups = sorted({ex_lib.MUSCLE_LABELS.get(e["muscle_group"], e["muscle_group"])
                     for e in used if e.get("slot") == "main"})
    emphasis_labels = [ex_lib.MUSCLE_LABELS.get(g, g) for g in (emphasis or [])]

    # Ausgleichende Dehnung fuer die betroffene Stelle ans Ende
    if adapt["relief_poses"]:
        pool = {p["name"]: p for p in ex_lib.EVENING_YOGA_POOL}
        for pose_name in adapt["relief_poses"][:2]:
            pose = pool.get(pose_name)
            if pose:
                # Bewusst OHNE garmin_category: In einer Krafteinheit lehnt
                # Garmin eine Yoga-Kategorie ab und verwirft das ganze
                # Workout. Als benannter Zeitblock kommt die Dehnung an.
                steps.append({"type": "cooldown", "name": pose["name"],
                              "duration_s": pose["duration_s"],
                              "notes": pose.get("cue")})
    actual_minutes = round(step_seconds(steps) / 60)

    adapted = None
    if skipped or adapt["relief_poses"]:
        reason = "; ".join(adapt["summary"][:2])
        parts = []
        if skipped:
            labels = ", ".join(ex_lib.MUSCLE_LABELS.get(g, g) for g in skipped)
            parts.append(f"{labels} ausgelassen")
        if adapt["relief_poses"]:
            parts.append("ausgleichende Dehnung ergänzt")
        adapted = {"reason": reason, "changes": parts,
                   "complaints": adapt["complaints"]}

    # Was sich seit der letzten Einheit an den Vorgaben geaendert hat, gehoert
    # an die Einheit selbst: Wer eine andere Zahl auf dem Zettel findet, ohne
    # zu wissen warum, glaubt eher an einen Fehler als an eine Anpassung.
    changes = ex_lib.recent_changes([e["id"] for e in used], days=10)

    return {
        "adapted": adapted,
        "changes": changes,
        "changes_note": (
            "Seit der letzten Einheit angepasst: "
            + "; ".join(f"{c['name']} {c['change']}" for c in changes[:3])
            + ("." if len(changes) <= 3 else f" und {len(changes) - 3} weitere.")
        ) if changes else None,
        # Im Namen steht die gerechnete Dauer, nicht die gewünschte: Eine
        # Einheit, die "90 min" heißt und nach 80 vorbei ist, ist eine Ansage,
        # auf die man sich nicht verlassen kann.
        "name": name or (f"Gym {'/'.join(emphasis_labels)} {actual_minutes} min"
                         if emphasis_labels else f"Gym Ganzkörper {actual_minutes} min"),
        "sport": "strength",
        "emphasis": emphasis_labels,
        "minutes": actual_minutes,
        "minutes_requested": minutes,
        "description": (f"Kettlebell-Auftakt, Klimmzug-Arbeit, dann Maschinen "
                        f"({', '.join(groups)}) und Dehnen zum Abschluss."
                        + (f" Schwerpunkt: {', '.join(emphasis_labels)}."
                           if emphasis_labels else "")),
        "steps": steps,
        "exercise_ids": [e["id"] for e in used],
    }


# ------------------------------------------------------------ Zuhause-Einheit

def build_home_session(minutes: int = 30, groups: list[str] | None = None,
                       with_dumbbell: bool = True,
                       must: list[str] | None = None) -> dict[str, Any]:
    """Eine Einheit für die Matte — ohne Studio, höchstens mit kleiner Hantel.

    Gebaut wird nach demselben Grundsatz wie die Gym-Einheit: Erst die
    Verteilung schätzen, dann nachrechnen und Übungen zufügen oder wegnehmen,
    bis die Dauer die Vorgabe trifft. Eine Einheit, die "30 min" heißt und
    nach 18 vorbei ist, wäre auch hier eine Ansage, auf die kein Verlass ist.
    """
    wanted = [g for g in (groups or ["core", "back"]) if g in ex_lib.MUSCLE_LABELS]
    if not wanted:
        wanted = ["core", "back"]

    wanted_names = {n.lower() for n in (must or [])}
    everything = ex_lib.list_exercises(only_active=True)

    # Der Block "home" ist die Grundlage. Eine ausdruecklich verlangte Uebung
    # darf aber aus jedem Block kommen: Wer auf den ersten Klimmzug hinarbeitet,
    # braucht negative Klimmzuege — egal, in welcher Schublade sie liegen.
    # "mat" und "home" sind beides Übungen ohne Studio — der Unterschied ist
    # nur, dass Matten-Übungen auch im Gym Sinn ergeben und deshalb dort
    # ebenfalls auftauchen.
    lib = [e for e in everything
           if (e.get("slot") in ("home", "mat") or e["name"].lower() in wanted_names)
           and (with_dumbbell or e.get("equipment") != "dumbbell"
                or e["name"].lower() in wanted_names)]

    # Fertigkeits-Uebungen (Handstand, Kraehe …) tauchen nur auf, wenn ein Ziel
    # sie ausdruecklich verlangt. In einer beliebigen Bauch-Einheit haben sie
    # nichts verloren.
    skills = {"Handstand an der Wand", "Pike-Liegestütz", "Krähe",
              "Handgelenke vorbereiten", "Bär-Kriechen"}
    lib = [e for e in lib
           if e["name"] not in skills or e["name"].lower() in wanted_names]
    # Beschwerden gelten auch zuhause.
    adapt = mood.adaptations()
    spared = set(adapt["spare_groups"])
    focused = [e for e in lib if e["muscle_group"] in wanted
               and e["muscle_group"] not in spared]
    rest = [e for e in lib if e not in focused and e["muscle_group"] not in spared]
    if len(focused) < 3:
        focused = focused + rest              # lieber breiter als zu kurz

    if not focused:
        return {"name": "Zuhause", "sport": "strength", "steps": [],
                "description": "Für eine Einheit ohne Geräte fehlen noch Übungen.",
                "exercise_ids": [], "minutes": 0,
                "hint": "Lege unter Kraft ein paar Übungen mit dem Block „Zuhause“ an."}

    # Reihum durch die gewünschten Gruppen, damit nicht sechsmal Bauch kommt.
    by_group: dict[str, list[dict[str, Any]]] = {}
    for e in focused:
        by_group.setdefault(e["muscle_group"], []).append(e)
    for lst in by_group.values():
        lst.sort(key=lambda e: (-_rest_days(e), e["sort_order"]))

    order = [g for g in wanted if g in by_group] + \
        [g for g in by_group if g not in wanted]
    rotation: list[dict[str, Any]] = []
    round_no = 0
    while any(len(by_group[g]) > round_no for g in order) and round_no < 6:
        for g in order:
            if len(by_group[g]) > round_no:
                rotation.append(by_group[g][round_no])
        round_no += 1

    # Verlangte Uebungen zuerst und in der genannten Reihenfolge: Bei einem
    # Ziel ist die Reihenfolge Teil der Sache — Handgelenke vor Handstand,
    # nicht umgekehrt.
    if wanted_names:
        by_name = {e["name"].lower(): e for e in focused}
        head = [by_name[n] for n in (m.lower() for m in must) if n in by_name]
        rotation = head + [e for e in rotation if e not in head]

    used: list[dict[str, Any]] = []

    def assemble(count: int) -> list[dict[str, Any]]:
        used.clear()
        out: list[dict[str, Any]] = [
            {"type": "warmup", "name": "Aufwärmen auf der Matte", "duration_s": 180,
             "notes": "Katze-Kuh, Schulterkreisen, ein paar Ausfallschritte"}]
        for e in rotation[:count]:
            out.extend(_exercise_to_steps(e))
            used.append(e)
        out.append({"type": "cooldown", "name": "Ausatmen und dehnen",
                    "duration_s": 120,
                    "notes": "Kindhaltung und liegende Drehung, je eine halbe Minute"})
        return out

    # Dauer treffen: Übungen zufügen, bis es passt.
    target = minutes * 60
    best = None
    for count in range(2, min(len(rotation), 12) + 1):
        steps = assemble(count)
        gap = abs(step_seconds(steps) - target)
        if best is None or gap < best[0]:
            best = (gap, count, steps, list(used))
        if step_seconds(steps) > target:
            break
    _gap, count, steps, chosen = best
    used = chosen
    actual = round(step_seconds(steps) / 60)

    labels = sorted({ex_lib.MUSCLE_LABELS.get(e["muscle_group"], e["muscle_group"])
                     for e in used})
    return {
        "name": f"Zuhause {'/'.join(labels)} {actual} min",
        "sport": "strength",
        "minutes": actual,
        "minutes_requested": minutes,
        "groups": labels,
        "description": (f"Auf der Matte, ohne Studio"
                        + (" (kleine Hantel)" if any(
                            e["equipment"] == "dumbbell" for e in used) else "")
                        + f": {', '.join(labels)}."),
        "steps": steps,
        "exercise_ids": [e["id"] for e in used],
        "adapted": ({"reason": "; ".join(adapt["summary"][:2]),
                     "changes": ["betroffene Gruppen ausgelassen"],
                     "complaints": adapt["complaints"]} if spared and adapt["complaints"]
                    else None),
    }


# ------------------------------------------------------------- Abend-Mobility

def _pose_step(pose: dict[str, Any], step_type: str = "work") -> dict[str, Any]:
    """Eine Yoga-Stellung als Schritt — mit Garmin-Stellung, damit die Uhr sie
    beim Namen nennt und die Abbildung zeigt, statt nur die Zeit zu stoppen."""
    return {
        "type": step_type,
        "name": pose["name"],
        "duration_s": pose["duration_s"],
        "notes": pose.get("cue"),
        "garmin_category": "POSE",
        "garmin_exercise": pose["garmin_exercise"],
    }


def build_evening_yoga(minutes: int = 12) -> dict[str, Any]:
    """Kurze Einheit zum Runterkommen — geht als Yoga-Workout auf die Uhr."""
    # Bei gemeldeten Beschwerden kommen die passenden Stellungen zuerst —
    # die Abendeinheit ist die naheliegendste Stelle, etwas dagegen zu tun.
    adapt = mood.adaptations()
    preferred = adapt["relief_poses"]
    pool = [p for p in ex_lib.EVENING_YOGA_POOL if p["name"] != "Totenstellung"]
    # Tagesabhängig rotieren, damit es nicht jeden Abend dasselbe ist
    rnd = random.Random(dt.date.today().toordinal())
    rnd.shuffle(pool)
    # Entlastungsstellungen nach vorn holen — die Reihenfolge entscheidet,
    # was ins Zeitbudget passt.
    if preferred:
        pool.sort(key=lambda p: preferred.index(p["name"])
                  if p["name"] in preferred else len(preferred))
    budget = minutes * 60
    steps: list[dict[str, Any]] = [
        {"type": "warmup", "name": "Ankommen und atmen", "duration_s": 60,
         "notes": "Vier Sekunden ein, sechs Sekunden aus",
         "garmin_category": "POSE", "garmin_exercise": "MOUNTAIN"},
    ]
    chosen: list[dict[str, Any]] = []
    spent = 60
    for pose in pool:
        if spent + pose["duration_s"] > budget - 90:
            break
        steps.append(_pose_step(pose))
        chosen.append(pose)
        spent += pose["duration_s"]

    final = next(p for p in ex_lib.EVENING_YOGA_POOL if p["name"] == "Totenstellung")
    steps.append(_pose_step(final, "cooldown"))
    chosen.append(final)

    adapted = None
    if preferred:
        hit = [p["name"] for p in chosen if p["name"] in preferred]
        if hit:
            adapted = {"reason": "; ".join(adapt["summary"][:2]),
                       "changes": [f"{', '.join(hit)} vorgezogen"],
                       "complaints": adapt["complaints"]}

    return {
        "adapted": adapted,
        "name": f"Abend-Yoga {minutes} min", "sport": "mobility",
        "description": ("Ruhige Einheit vor dem Schlafen. Die Stellungen erscheinen "
                        "namentlich auf der Uhr; die Anleitung dazu steht in PULS "
                        "unter Plan."),
        "steps": steps,
        "poses": [p["name"] for p in chosen],
    }


# ---------------------------------------------------------------- Wochenplan

def _run_for_day(weekday: str, index: int, minutes: int, quality_day: str,
                 long_day: str) -> dict[str, Any]:
    """Ein Qualitätsreiz und ein langer Lauf pro Woche, der Rest locker."""
    if weekday == quality_day:
        return running.build_interval_run(minutes + 10)
    if weekday == long_day:
        return running.build_long_run(max(40, minutes + 20))
    return running.build_easy_run(minutes)


def plan_week(start: dt.date | None = None, include_runs: bool = True,
              include_gym: bool = True, include_mobility: bool = True
              ) -> list[dict[str, Any]]:
    """Baut den kompletten Wochenplan als Liste von Workouts mit Datum."""
    start = start or dt.date.today()
    run_days = json.loads(get_setting("run_days", "[]") or "[]")
    gym_days = json.loads(get_setting("gym_days", "[]") or "[]")
    run_minutes = int(get_setting("run_minutes", "25") or 25)
    gym_minutes = int(get_setting("gym_minutes", "75") or 75)
    mobility_on = get_setting("evening_mobility", "1") == "1"

    # Qualitätslauf an einen Tag ohne Gym legen, langer Lauf aufs Wochenende
    non_gym = [d for d in run_days if d not in gym_days]
    quality_day = non_gym[0] if non_gym else (run_days[0] if run_days else "Di")
    long_day = "Sa" if "Sa" in run_days else (non_gym[-1] if non_gym else "So")
    if long_day == quality_day and len(non_gym) > 1:
        long_day = non_gym[-1]

    out: list[dict[str, Any]] = []
    for offset in range(7):
        date = start + dt.timedelta(days=offset)
        wd = _weekday_of(date)
        iso = date.isoformat()

        if include_runs and wd in run_days:
            run = _run_for_day(wd, offset, run_minutes, quality_day, long_day)
            run["planned_date"] = iso
            run["time_of_day"] = "morgens"
            out.append(run)

        if include_gym and wd in gym_days:
            gym = build_gym_session(gym_minutes)
            gym["planned_date"] = iso
            gym["time_of_day"] = "abends"
            out.append(gym)

        if include_mobility and mobility_on:
            yoga = build_evening_yoga(12)
            yoga["planned_date"] = iso
            yoga["time_of_day"] = "vor dem Schlafen"
            out.append(yoga)

    return out


def week_overview() -> dict[str, Any]:
    """Kompakte Übersicht der eingestellten Wochenstruktur — für Dashboard und KI."""
    run_days = json.loads(get_setting("run_days", "[]") or "[]")
    gym_days = json.loads(get_setting("gym_days", "[]") or "[]")
    paces = running.current_paces()
    with get_db() as db:
        pullup_row = db.execute(
            "SELECT MAX(reps) AS best FROM exercise_sets s "
            "JOIN exercises e ON e.id = s.exercise_id "
            "WHERE e.name = 'Klimmzüge'").fetchone()
    return {
        "run_days": run_days,
        "run_minutes": int(get_setting("run_minutes", "25") or 25),
        "gym_days": gym_days,
        "gym_minutes": int(get_setting("gym_minutes", "75") or 75),
        "evening_mobility": get_setting("evening_mobility", "1") == "1",
        "paces": {k: running.pace_s_to_str(v) for k, v in (paces or {}).items()},
        "goal_pace": running.pace_s_to_str(running.goal_pace_s()),
        "run_goal": (f"{get_setting('run_goal_distance_km', '10')} km unter "
                     f"{get_setting('run_goal_time_min', '60')} min"),
        "pullup_best": (pullup_row["best"] if pullup_row else None)
                       or get_setting("pullup_best", "") or None,
        "pullup_goal": get_setting("pullup_goal", "10"),
        "calibrated": bool(paces),
    }
