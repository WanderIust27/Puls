"""SQLite-Zugriff — bewusst schlank, ohne ORM."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .config import DB_PATH, ensure_dirs

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    garmin_id TEXT UNIQUE,
    source TEXT NOT NULL DEFAULT 'manual',        -- garmin | fit | manual
    name TEXT,
    sport TEXT NOT NULL,                          -- running | strength | cardio | mobility | other
    start_time TEXT NOT NULL,                     -- ISO
    duration_s INTEGER,
    distance_m REAL,
    calories REAL,
    avg_hr REAL,
    max_hr REAL,
    training_load REAL,
    notes TEXT,
    raw_json TEXT,
    -- Laufspezifische Kennzahlen (Fenix 7)
    avg_cadence REAL,              -- Schritte pro Minute
    max_cadence REAL,
    avg_stride_m REAL,             -- Schrittlänge in Metern
    ground_contact_ms REAL,        -- Bodenkontaktzeit
    vertical_osc_cm REAL,          -- vertikale Bewegung
    vertical_ratio REAL,           -- vertikales Verhältnis in %
    avg_power REAL,                -- Laufleistung in Watt
    elevation_gain REAL,
    aerobic_te REAL,               -- aerober Trainingseffekt 0..5
    anaerobic_te REAL,
    vo2max REAL,
    hr_zones_json TEXT,            -- Sekunden je Herzfrequenzzone
    analysis_json TEXT             -- Ergebnis der Laufbewertung
);
CREATE TABLE IF NOT EXISTS activity_details (
    activity_id INTEGER PRIMARY KEY REFERENCES activities(id) ON DELETE CASCADE,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    -- Ausgeduennt gespeichert: rund 300-500 Messpunkte statt sekundengenauer Rohdaten.
    -- In Karte und Diagrammen nicht von der vollen Aufloesung zu unterscheiden,
    -- kostet aber Kilobyte statt Megabyte.
    series_json TEXT,                             -- Puls, Tempo, Hoehe, Kadenz ueber die Zeit
    track_json TEXT,                              -- vereinfachte GPS-Spur
    splits_json TEXT,                             -- Runden/Kilometer
    bounds_json TEXT,                             -- Eckpunkte der Spur fuer den Kartenausschnitt
    point_count INTEGER
);
CREATE TABLE IF NOT EXISTS supplements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dose TEXT,                                    -- "5 g", "1 Tablette"
    -- Wann faellig: feste Uhrzeit oder an eine Einheit gekoppelt.
    trigger_kind TEXT NOT NULL DEFAULT 'time',    -- time | after_gym | after_run
    at_time TEXT,                                 -- HH:MM bei trigger_kind='time'
    weekdays TEXT NOT NULL DEFAULT '["Mo","Di","Mi","Do","Fr","Sa","So"]',
    note TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS supplement_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplement_id INTEGER NOT NULL REFERENCES supplements(id) ON DELETE CASCADE,
    day TEXT NOT NULL,
    taken_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(supplement_id, day)
);
CREATE TABLE IF NOT EXISTS mood_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    recorded_at TEXT NOT NULL,                    -- ISO; mehrmals taeglich moeglich
    mood INTEGER,                                 -- 1..5
    energy INTEGER,                               -- 1..5
    stress INTEGER,                               -- 1..5
    note TEXT,
    complaints TEXT NOT NULL DEFAULT '[]',        -- JSON: [{region, kind, severity}]
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mood_day ON mood_entries(day);
CREATE TABLE IF NOT EXISTS coach_adaptations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    day TEXT,
    kind TEXT NOT NULL,                           -- complaint | structure | recovery
    trigger TEXT,                                 -- was den Vorschlag ausgeloest hat
    title TEXT NOT NULL,
    detail TEXT,
    payload_json TEXT,                            -- was uebernommen wuerde
    status TEXT NOT NULL DEFAULT 'open',          -- open | applied | dismissed | auto
    applied_at TEXT
);
CREATE TABLE IF NOT EXISTS planned_workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sport TEXT NOT NULL,
    planned_date TEXT,
    description TEXT,
    steps_json TEXT NOT NULL,                     -- unser eigenes Step-Format
    status TEXT NOT NULL DEFAULT 'planned',       -- planned | pushed | done | skipped
    garmin_workout_id TEXT,
    created_by TEXT NOT NULL DEFAULT 'coach',     -- coach | user
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS nutrition_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,                            -- YYYY-MM-DD
    kcal REAL,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    notes TEXT,
    UNIQUE(day)
);
CREATE TABLE IF NOT EXISTS body_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,                            -- YYYY-MM-DD, aus measured_at abgeleitet
    measured_at TEXT NOT NULL,                    -- ISO-Zeitstempel der Messung (lokale Zeit)
    time_known INTEGER NOT NULL DEFAULT 1,        -- 0 = Uhrzeit unbekannt (Altbestand, CSV)
    in_window INTEGER,                            -- 1 = im Referenzfenster gemessen
    weight_kg REAL,
    weight_adj_kg REAL,                           -- auf das Referenzfenster umgerechnet
    body_fat_pct REAL,
    muscle_kg REAL,
    water_pct REAL,
    bone_kg REAL,                                 -- Schaetzung aus der Impedanz
    lbm_kg REAL,                                  -- Magermasse (Zwischengroesse der Schaetzung)
    bmi REAL,
    visceral_fat REAL,                            -- Schaetzung, dimensionslose Kennzahl
    impedance INTEGER,                            -- Rohwert der Waage, fuer Nachrechnen
    note TEXT,
    source TEXT NOT NULL DEFAULT 'manual',        -- manual | miscale | garmin | import
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, measured_at)
);
CREATE INDEX IF NOT EXISTS idx_body_day ON body_metrics(day);
CREATE TABLE IF NOT EXISTS daily_metrics (
    day TEXT PRIMARY KEY,
    sleep_seconds INTEGER,
    sleep_score REAL,
    hrv_avg REAL,
    hrv_status TEXT,
    resting_hr REAL,
    body_battery_max REAL,
    training_readiness REAL,
    steps INTEGER,
    raw_json TEXT,
    -- Schlafphasen (Sekunden) und Zeitpunkte
    sleep_deep_s INTEGER,
    sleep_light_s INTEGER,
    sleep_rem_s INTEGER,
    sleep_awake_s INTEGER,
    sleep_start TEXT,
    sleep_end TEXT,
    respiration_avg REAL,                         -- Atemzuege pro Minute
    spo2_avg REAL,
    -- HRV im Verhaeltnis zur persoenlichen Basislinie
    hrv_weekly_avg REAL,
    hrv_baseline_low REAL,
    hrv_baseline_high REAL,
    -- Stress: Tagesmittel und Minuten je Stufe
    stress_avg REAL,
    stress_max REAL,
    stress_rest_min INTEGER,
    stress_low_min INTEGER,
    stress_medium_min INTEGER,
    stress_high_min INTEGER,
    stress_series_json TEXT,                      -- ausgeduennter Tagesverlauf
    -- Body Battery
    body_battery_min REAL,
    body_battery_wake REAL,                       -- Stand beim Aufwachen
    body_battery_charged REAL,
    body_battery_drained REAL,
    body_battery_series_json TEXT,
    -- Puls ueber den Tag
    hr_min REAL,
    hr_max REAL,
    hr_avg REAL
);
CREATE TABLE IF NOT EXISTS coach_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL,                           -- daily | answer | plan | nutrition | rest
    question TEXT,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_tips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    topic TEXT,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    ok INTEGER NOT NULL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,                    -- Anzeigename, deutsch
    aliases TEXT NOT NULL DEFAULT '[]',           -- JSON-Liste für Garmin-Matching
    muscle_group TEXT NOT NULL,                   -- legs|chest|back|shoulders|arms|core|cardio
    equipment TEXT NOT NULL,                      -- machine|cable|band|dumbbell|barbell|bodyweight|suspension|cardio_machine
    mode TEXT NOT NULL DEFAULT 'reps',            -- reps | time
    weight_kg REAL,                               -- aktuelles Arbeitsgewicht (NULL = Körpergewicht)
    weight_increment REAL NOT NULL DEFAULT 2.5,   -- kleinste sinnvolle Steigerung
    target_reps INTEGER NOT NULL DEFAULT 12,      -- aktuelles Ziel innerhalb der Spanne
    rep_min INTEGER NOT NULL DEFAULT 12,
    rep_max INTEGER NOT NULL DEFAULT 15,
    target_duration_s INTEGER,                    -- bei mode='time'
    sets INTEGER NOT NULL DEFAULT 3,
    rest_s INTEGER NOT NULL DEFAULT 90,
    machine_setting TEXT,                         -- z. B. "Stufe 7 bei Füße"
    slot TEXT NOT NULL DEFAULT 'main',            -- kettlebell|main|pullup|stretch|cardio
    priority INTEGER NOT NULL DEFAULT 2,          -- 1=immer dabei, 2=normal, 3=Rotation
    garmin_category TEXT,
    garmin_exercise TEXT,
    est_1rm REAL,
    last_performed TEXT,
    fail_streak INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS exercise_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
    garmin_set_key TEXT UNIQUE,                   -- Dedupe für Garmin-Sätze
    day TEXT NOT NULL,
    set_index INTEGER NOT NULL DEFAULT 1,
    reps INTEGER,
    weight_kg REAL,
    duration_s REAL,
    feeling TEXT,                                 -- easy | ok | hard
    source TEXT NOT NULL DEFAULT 'manual',        -- garmin | manual | benchmark
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sets_exercise_day ON exercise_sets(exercise_id, day);
CREATE TABLE IF NOT EXISTS progression_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id INTEGER NOT NULL REFERENCES exercises(id) ON DELETE CASCADE,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL,                         -- weight_up | reps_up | hold | deload | calibrate
    from_weight REAL, to_weight REAL,
    from_reps INTEGER, to_reps INTEGER,
    reason TEXT
);
"""

DEFAULT_SETTINGS = {
    "goals": json.dumps(["muscle", "endurance", "general", "weight_gain"]),
    "weekly_workout_target": "4",
    "kcal_target": "",
    "protein_target": "",
    "profile": json.dumps({}),
    "garmin_linked": "0",
    "garmin_email": "",
    "last_benchmark": "",
    "last_run_benchmark": "",
    "benchmark_interval_weeks": "10",
    "exercises_seeded": "0",
    "font_scale": "100",
    "ollama_model": "",
    # Wochenstruktur (vom Nutzer einstellbar)
    "run_days": json.dumps(["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]),
    "run_minutes": "25",
    "gym_days": json.dumps(["Mo", "Mi", "Fr"]),
    "gym_minutes": "75",
    "evening_mobility": "1",
    "prefer_machines": "1",
    # Laufziel: 10 km unter 60 min
    "run_goal_distance_km": "10",
    "run_goal_time_min": "60",
    "pullup_goal": "10",
    "pullup_best": "",
    # Laufleistung aus dem Benchmark (m in 12 min, Cooper)
    "supplements_seeded": "0",
    # Vom Coach vorgeschlagener Schwerpunkt im Gym (auf Zeit)
    "gym_focus_groups": "[]",
    "gym_focus_until": "",
    # Ernaehrung: Schwerpunkte fuer die Rezeptauswahl
    "diet_style": json.dumps(["vegetarian_lean", "quick", "mealprep"]),
    "diet_exclude": "",
    # Waage: Referenzfenster fuer vergleichbare Messungen
    "weigh_window_start": "06:00",
    "weigh_window_end": "09:00",
    "weigh_adjust_offwindow": "1",   # Messungen ausserhalb rechnerisch angleichen
    "body_height_cm": "184",
    "body_age": "24",
    "body_sex": "male",
    # Karte in der Laufansicht: 0 = nur GPS-Spur, 1 = OpenStreetMap-Hintergrund
    "map_tiles": "0",
    "cooper_distance_m": "",
    "easy_pace_s_per_km": "",
    "tempo_pace_s_per_km": "",
    "interval_pace_s_per_km": "",
}


# Spalten, die zu einer bereits bestehenden Datenbank hinzukommen können.
# CREATE TABLE IF NOT EXISTS ergänzt keine Spalten — das muss ALTER TABLE tun.
# Die Liste darf wachsen; jeder Eintrag wird nur angelegt, wenn er noch fehlt.
COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    ("activities", "avg_cadence", "REAL"),
    ("activities", "max_cadence", "REAL"),
    ("activities", "avg_stride_m", "REAL"),
    ("activities", "ground_contact_ms", "REAL"),
    ("activities", "vertical_osc_cm", "REAL"),
    ("activities", "vertical_ratio", "REAL"),
    ("activities", "avg_power", "REAL"),
    ("activities", "elevation_gain", "REAL"),
    ("activities", "aerobic_te", "REAL"),
    ("activities", "anaerobic_te", "REAL"),
    ("activities", "vo2max", "REAL"),
    ("activities", "hr_zones_json", "TEXT"),
    ("activities", "analysis_json", "TEXT"),
    ("exercises", "slot", "TEXT NOT NULL DEFAULT 'main'"),
    ("exercises", "priority", "INTEGER NOT NULL DEFAULT 2"),
    ("exercises", "est_1rm", "REAL"),
    ("exercises", "fail_streak", "INTEGER NOT NULL DEFAULT 0"),
    ("body_metrics", "water_pct", "REAL"),
    ("body_metrics", "bone_kg", "REAL"),
    ("body_metrics", "lbm_kg", "REAL"),
    ("body_metrics", "bmi", "REAL"),
    ("body_metrics", "visceral_fat", "REAL"),
    ("body_metrics", "impedance", "INTEGER"),
    ("body_metrics", "note", "TEXT"),
    ("body_metrics", "in_window", "INTEGER"),
    ("body_metrics", "weight_adj_kg", "REAL"),
    ("daily_metrics", "sleep_deep_s", "INTEGER"),
    ("daily_metrics", "sleep_light_s", "INTEGER"),
    ("daily_metrics", "sleep_rem_s", "INTEGER"),
    ("daily_metrics", "sleep_awake_s", "INTEGER"),
    ("daily_metrics", "sleep_start", "TEXT"),
    ("daily_metrics", "sleep_end", "TEXT"),
    ("daily_metrics", "respiration_avg", "REAL"),
    ("daily_metrics", "spo2_avg", "REAL"),
    ("daily_metrics", "hrv_weekly_avg", "REAL"),
    ("daily_metrics", "hrv_baseline_low", "REAL"),
    ("daily_metrics", "hrv_baseline_high", "REAL"),
    ("daily_metrics", "stress_avg", "REAL"),
    ("daily_metrics", "stress_max", "REAL"),
    ("daily_metrics", "stress_rest_min", "INTEGER"),
    ("daily_metrics", "stress_low_min", "INTEGER"),
    ("daily_metrics", "stress_medium_min", "INTEGER"),
    ("daily_metrics", "stress_high_min", "INTEGER"),
    ("daily_metrics", "stress_series_json", "TEXT"),
    ("daily_metrics", "body_battery_min", "REAL"),
    ("daily_metrics", "body_battery_wake", "REAL"),
    ("daily_metrics", "body_battery_charged", "REAL"),
    ("daily_metrics", "body_battery_drained", "REAL"),
    ("daily_metrics", "body_battery_series_json", "TEXT"),
    ("daily_metrics", "hr_min", "REAL"),
    ("daily_metrics", "hr_max", "REAL"),
    ("daily_metrics", "hr_avg", "REAL"),
]


def _rebuild_body_metrics(db: sqlite3.Connection) -> None:
    """Aeltere Datenbanken erlauben nur eine Messung pro Tag und Quelle.

    Der Constraint UNIQUE(day, source) laesst sich in SQLite nicht per
    ALTER TABLE entfernen — die Tabelle muss neu aufgebaut werden. Erkannt wird
    der Altbestand daran, dass die Spalte measured_at fehlt.

    Bestandsmessungen bekommen keine erfundene Uhrzeit: sie werden mit
    time_known=0 gefuehrt, auf 12:00 datiert (Tagesmitte, damit die Sortierung
    stimmt) und spaeter weder korrigiert noch dem Referenzfenster zugerechnet.
    """
    cols = {r["name"] for r in db.execute("PRAGMA table_info(body_metrics)").fetchall()}
    if not cols or "measured_at" in cols:
        return

    import logging
    log = logging.getLogger("puls.db")
    keep = [c for c in ("day", "weight_kg", "body_fat_pct", "muscle_kg",
                        "water_pct", "source") if c in cols]

    db.execute("ALTER TABLE body_metrics RENAME TO body_metrics_old")
    db.executescript(SCHEMA)          # legt body_metrics in neuer Form an
    fields = ", ".join(keep)
    db.execute(
        f"""INSERT INTO body_metrics(measured_at, time_known, {fields})
            SELECT day || 'T12:00:00', 0, {fields} FROM body_metrics_old""")
    moved = db.execute("SELECT COUNT(*) AS n FROM body_metrics").fetchone()["n"]
    db.execute("DROP TABLE body_metrics_old")
    log.info("body_metrics umgebaut: %d Messung(en) uebernommen, "
             "Uhrzeit als unbekannt markiert.", moved)


def _migrate(db: sqlite3.Connection) -> None:
    """Fehlende Spalten nachrüsten, ohne bestehende Daten anzufassen."""
    existing_tables = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    added = 0
    for table, column, coltype in COLUMN_MIGRATIONS:
        if table not in existing_tables:
            continue
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column in cols:
            continue
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        added += 1
    if added:
        import logging
        logging.getLogger("puls.db").info("%d fehlende Spalte(n) ergänzt.", added)


def init_db() -> None:
    ensure_dirs()
    with get_db() as db:
        _rebuild_body_metrics(db)
        db.executescript(SCHEMA)
        _migrate(db)
        for k, v in DEFAULT_SETTINGS.items():
            db.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v))
        # Token für den Waagen-Webhook einmalig erzeugen
        row = db.execute("SELECT value FROM settings WHERE key='api_token'").fetchone()
        if not row or not row["value"]:
            import secrets
            db.execute("INSERT INTO settings(key, value) VALUES('api_token', ?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (secrets.token_urlsafe(24),))
    from .services.exercises import seed_default_exercises
    seed_default_exercises()
    from .services.supplements import seed_defaults
    seed_defaults()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Datenbankverbindung mit Sperre.

    Achtung: Die Sperre ist nicht reentrant. Innerhalb eines offenen get_db()
    darf nichts aufgerufen werden, das seinerseits die Datenbank oeffnet —
    auch nicht get_setting(). Das blockiert dauerhaft, ohne Fehlermeldung.
    Werte, die in einer Schleife gebraucht werden, vorher bestimmen.
    """
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_db() as db:
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
