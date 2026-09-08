"""Supplements: was heute faellig ist, und was davon schon erledigt.

Zwei Arten von Faelligkeit. Die meisten Mittel haengen an einer Uhrzeit
(Kreatin morgens, Zink abends). Eiweiss dagegen haengt am Training — an einem
Gym-Tag ist es nach der Einheit faellig, an einem freien Tag gar nicht. Beides
wird hier gleich behandelt, nur die Faelligkeitsfrage wird anders beantwortet.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts, set_setting

log = logging.getLogger("puls.supplements")

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Der uebliche Anfang. Aendern laesst sich alles in der App; angelegt wird das
# hier nur einmal, damit man nicht vor einer leeren Liste steht.
DEFAULTS: list[dict[str, Any]] = [
    {"name": "Kreatin", "dose": "5 g", "trigger_kind": "time", "at_time": "08:00",
     "sort_order": 10,
     "note": "Wirkt über die Sättigung des Speichers, nicht über den Zeitpunkt — "
             "entscheidend ist, dass es täglich passiert, auch an Ruhetagen."},
    {"name": "Zink", "dose": "1 Tablette", "trigger_kind": "time", "at_time": "21:00",
     "sort_order": 20,
     "note": "Mit Abstand zu Milchprodukten und Kaffee; beides bremst die Aufnahme."},
    {"name": "Eiweiß-Shake", "dose": "30 g", "trigger_kind": "after_gym",
     "sort_order": 30,
     "note": "An Gym-Tagen nach der Einheit. Die Tagesmenge zählt mehr als das "
             "Zeitfenster, aber nach dem Training trinkt es sich am leichtesten."},
]


def seed_defaults() -> None:
    if get_setting("supplements_seeded", "0") == "1":
        return
    with get_db() as db:
        existing = db.execute("SELECT COUNT(*) AS n FROM supplements").fetchone()["n"]
        if not existing:
            for entry in DEFAULTS:
                db.execute(
                    """INSERT INTO supplements(name, dose, trigger_kind, at_time,
                                               note, sort_order)
                       VALUES(:name,:dose,:trigger_kind,:at_time,:note,:sort_order)""",
                    {"at_time": None, **entry})
    set_setting("supplements_seeded", "1")
    log.info("Supplements mit %d Vorschlägen angelegt.", len(DEFAULTS))


def _weekdays(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else list(WEEKDAYS)
    except ValueError:
        return list(WEEKDAYS)


def list_all(only_active: bool = False) -> list[dict[str, Any]]:
    where = " WHERE active=1" if only_active else ""
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM supplements{where} ORDER BY sort_order, id").fetchall()
    out = rows_to_dicts(rows)
    for row in out:
        row["weekdays"] = _weekdays(row.get("weekdays"))
    return out


def upsert(data: dict[str, Any], supp_id: int | None = None) -> int:
    fields = {
        "name": (data.get("name") or "").strip(),
        "dose": data.get("dose"),
        "trigger_kind": data.get("trigger_kind") or "time",
        "at_time": data.get("at_time"),
        "weekdays": json.dumps(data.get("weekdays") or WEEKDAYS),
        "note": data.get("note"),
        "active": 1 if data.get("active", True) else 0,
        "sort_order": data.get("sort_order", 100),
    }
    if not fields["name"]:
        raise ValueError("Ein Supplement braucht einen Namen.")
    if fields["trigger_kind"] == "time" and not fields["at_time"]:
        fields["at_time"] = "08:00"
    with get_db() as db:
        if supp_id:
            sets = ", ".join(f"{k}=:{k}" for k in fields)
            db.execute(f"UPDATE supplements SET {sets} WHERE id=:id",
                       {**fields, "id": supp_id})
            return supp_id
        cur = db.execute(
            f"INSERT INTO supplements({', '.join(fields)}) "
            f"VALUES({', '.join(':' + k for k in fields)})", fields)
        return cur.lastrowid


def delete(supp_id: int) -> bool:
    with get_db() as db:
        return db.execute("DELETE FROM supplements WHERE id=?",
                          (supp_id,)).rowcount > 0


def mark(supp_id: int, day: str | None = None, taken: bool = True) -> bool:
    day = day or dt.date.today().isoformat()
    with get_db() as db:
        if taken:
            db.execute("INSERT OR IGNORE INTO supplement_log(supplement_id, day) "
                       "VALUES(?,?)", (supp_id, day))
        else:
            db.execute("DELETE FROM supplement_log WHERE supplement_id=? AND day=?",
                       (supp_id, day))
    return taken


def _trained(day: str, sport: str) -> str | None:
    """Endzeit der Einheit an diesem Tag, falls es eine gab."""
    with get_db() as db:
        row = db.execute(
            "SELECT start_time, duration_s FROM activities "
            "WHERE sport=? AND substr(start_time,1,10)=? "
            "ORDER BY start_time DESC LIMIT 1", (sport, day)).fetchone()
    if not row:
        return None
    try:
        start = dt.datetime.fromisoformat(row["start_time"])
    except (TypeError, ValueError):
        return None
    return (start + dt.timedelta(seconds=row["duration_s"] or 0)).isoformat(
        timespec="seconds")


def today(day: str | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Was heute ansteht, was erledigt ist, was überfällig."""
    day = day or dt.date.today().isoformat()
    now = now or dt.datetime.now()
    weekday = WEEKDAYS[dt.date.fromisoformat(day).weekday()]

    with get_db() as db:
        done = {r["supplement_id"] for r in db.execute(
            "SELECT supplement_id FROM supplement_log WHERE day=?", (day,)).fetchall()}

    gym_end = _trained(day, "strength")
    run_end = _trained(day, "running")

    items: list[dict[str, Any]] = []
    for supp in list_all(only_active=True):
        if weekday not in supp["weekdays"]:
            continue
        due_at, waiting = None, None
        if supp["trigger_kind"] == "after_gym":
            if not gym_end:
                waiting = "nach der Gym-Einheit"
            due_at = gym_end
        elif supp["trigger_kind"] == "after_run":
            if not run_end:
                waiting = "nach dem Lauf"
            due_at = run_end
        else:
            due_at = f"{day}T{supp['at_time'] or '08:00'}:00"

        taken = supp["id"] in done
        overdue = False
        if not taken and due_at:
            try:
                overdue = dt.datetime.fromisoformat(due_at) < now
            except ValueError:
                overdue = False

        items.append({
            **supp, "taken": taken, "due_at": due_at,
            "waiting_for": waiting,
            # Noch nicht faellig ist etwas anderes als vergessen — nur das
            # Zweite wird hervorgehoben.
            "overdue": overdue and not waiting,
            "due_label": (waiting or (due_at[11:16] if due_at else "")),
        })

    items.sort(key=lambda i: (i["taken"], i["due_at"] or "z"))
    open_items = [i for i in items if not i["taken"] and not i["waiting_for"]]
    return {
        "day": day,
        "items": items,
        "open": len(open_items),
        "overdue": [i["name"] for i in items if i["overdue"]],
        "done": len([i for i in items if i["taken"]]),
        "total": len(items),
    }


def streak(days: int = 30) -> dict[str, Any]:
    """Wie zuverlaessig wird genommen — je Supplement die Quote."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute(
            """SELECT s.id, s.name, COUNT(l.id) AS taken
               FROM supplements s
               LEFT JOIN supplement_log l ON l.supplement_id = s.id AND l.day >= ?
               WHERE s.active = 1 GROUP BY s.id ORDER BY s.sort_order""",
            (since,)).fetchall()
    out = []
    for row in rows:
        out.append({"id": row["id"], "name": row["name"], "taken": row["taken"],
                    "days": days, "share": round(row["taken"] / days, 2)})
    return {"days": days, "items": out}


def context_line(day: str | None = None) -> str | None:
    """Eine Zeile für die Tagesnachricht des Coaches — oder nichts."""
    state = today(day)
    if not state["total"]:
        return None
    if state["overdue"]:
        names = ", ".join(state["overdue"])
        return f"Noch offen: {names}."
    if state["open"]:
        pending = [i["name"] for i in state["items"]
                   if not i["taken"] and not i["waiting_for"]]
        return f"Heute noch dran: {', '.join(pending)}."
    if state["done"] == state["total"]:
        return "Supplements sind heute vollständig."
    return None
