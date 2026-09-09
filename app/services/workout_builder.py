"""Baut aus unserem einfachen Step-Format Garmin-Connect-Workout-JSON
und alternativ eine FIT-Datei für den manuellen Import.

Eigenes Step-Format (steps_json in planned_workouts):
{
  "steps": [
    {"type": "warmup|work|recovery|rest|cooldown", "name": "...", "notes": "...",
     "duration_s": 600, "distance_m": 1000, "reps": 8,
     "pace_min_km": ["5:50", "5:30"], "hr_zone": 2},
    {"type": "repeat", "count": 4, "steps": [ ... ]}
  ]
}
Pro Step genau EINE Endbedingung: duration_s ODER distance_m ODER reps,
sonst "Runden-Taste drücken".
"""
from __future__ import annotations

from typing import Any

SPORT_TYPES = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running"},
    "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling"},
    "other": {"sportTypeId": 3, "sportTypeKey": "other"},
    "strength": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
    "cardio": {"sportTypeId": 6, "sportTypeKey": "cardio_training"},
    "mobility": {"sportTypeId": 7, "sportTypeKey": "yoga"},
    "yoga": {"sportTypeId": 7, "sportTypeKey": "yoga"},
    "hiit": {"sportTypeId": 9, "sportTypeKey": "hiit"},
}

# Welche Übungskategorien Garmin in welcher Sportart akzeptiert. Passt eine
# Kategorie nicht zum Workout, antwortet die API mit
# "400 - invalid category" und lehnt das GANZE Workout ab — nicht nur den
# einen Schritt. Yoga-Stellungen gehören deshalb nicht in eine Krafteinheit.
# Eine leere Menge heißt: nicht eingeschränkt.
ALLOWED_CATEGORIES: dict[str, set[str]] = {
    "strength": {
        "BENCH_PRESS", "CALF_RAISE", "CARDIO", "CARRY", "CHOP", "CORE",
        "CRUNCH", "CURL", "DEADLIFT", "FLYE", "HIP_RAISE", "HIP_STABILITY",
        "HIP_SWING", "HYPEREXTENSION", "LATERAL_RAISE", "LEG_CURL",
        "LEG_RAISE", "LUNGE", "OLYMPIC_LIFT", "PLANK", "PLYO", "PULL_UP",
        "PUSH_UP", "ROW", "SHOULDER_PRESS", "SHOULDER_STABILITY", "SHRUG",
        "SIT_UP", "SQUAT", "TOTAL_BODY", "TRICEPS_EXTENSION", "WARM_UP",
        "RUN", "UNKNOWN",
    },
    # Bei Yoga sind es die Stellungen, nicht die Kraftkategorien
    "mobility": {"YOGA", "POSE", "UNKNOWN"},
    "yoga": {"YOGA", "POSE", "UNKNOWN"},
}

STEP_TYPES = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup"},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown"},
    "work": {"stepTypeId": 3, "stepTypeKey": "interval"},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery"},
    "rest": {"stepTypeId": 5, "stepTypeKey": "rest"},
    "repeat": {"stepTypeId": 6, "stepTypeKey": "repeat"},
}

END_LAP = {"conditionTypeId": 1, "conditionTypeKey": "lap.button"}
END_TIME = {"conditionTypeId": 2, "conditionTypeKey": "time"}
END_DIST = {"conditionTypeId": 3, "conditionTypeKey": "distance"}
END_ITER = {"conditionTypeId": 7, "conditionTypeKey": "iterations"}
END_REPS = {"conditionTypeId": 10, "conditionTypeKey": "reps"}

NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"}
HR_ZONE_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"}
PACE_TARGET = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"}

# Häufige Übungen -> Garmin-Übungskategorien (Anzeige mit Animation auf der Uhr).
EXERCISES = {
    "kniebeuge": ("SQUAT", "BARBELL_BACK_SQUAT"),
    "squat": ("SQUAT", "BARBELL_BACK_SQUAT"),
    "goblet squat": ("SQUAT", "GOBLET_SQUAT"),
    "bankdrücken": ("BENCH_PRESS", "BARBELL_BENCH_PRESS"),
    "bench press": ("BENCH_PRESS", "BARBELL_BENCH_PRESS"),
    "kurzhantel bankdrücken": ("BENCH_PRESS", "DUMBBELL_BENCH_PRESS"),
    "kreuzheben": ("DEADLIFT", "BARBELL_DEADLIFT"),
    "deadlift": ("DEADLIFT", "BARBELL_DEADLIFT"),
    "rumänisches kreuzheben": ("DEADLIFT", "ROMANIAN_DEADLIFT"),
    "rudern": ("ROW", "BARBELL_ROW"),
    "row": ("ROW", "BARBELL_ROW"),
    "schulterdrücken": ("SHOULDER_PRESS", "OVERHEAD_BARBELL_PRESS"),
    "overhead press": ("SHOULDER_PRESS", "OVERHEAD_BARBELL_PRESS"),
    "klimmzug": ("PULL_UP", "PULL_UP"),
    "klimmzüge": ("PULL_UP", "PULL_UP"),
    "pull up": ("PULL_UP", "PULL_UP"),
    "latzug": ("PULL_UP", "LAT_PULLDOWN"),
    "dips": ("TRICEPS_EXTENSION", "DIP"),
    "ausfallschritt": ("LUNGE", "LUNGE"),
    "lunges": ("LUNGE", "LUNGE"),
    "bizeps curl": ("CURL", "BARBELL_BICEPS_CURL"),
    "curls": ("CURL", "DUMBBELL_BICEPS_CURL"),
    "seitheben": ("LATERAL_RAISE", "LATERAL_RAISE"),
    "plank": ("PLANK", "PLANK"),
    "hip thrust": ("HIP_RAISE", "BARBELL_HIP_THRUST"),
    "liegestütz": ("PUSH_UP", "PUSH_UP"),
    "push up": ("PUSH_UP", "PUSH_UP"),
}


def _pace_to_mps(pace: str) -> float | None:
    """"5:30" (min/km) -> m/s"""
    try:
        parts = str(pace).replace(",", ":").split(":")
        seconds = int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
        return 1000.0 / seconds if seconds > 0 else None
    except (ValueError, IndexError):
        return None


def _find_exercise(name: str | None) -> tuple[str, str] | None:
    """Erst in der Bibliothek nachschlagen (dort steht das gepflegte Mapping),
    dann auf die eingebaute Stichwortliste zurückfallen."""
    if not name:
        return None
    try:
        from . import exercises as ex_lib
        for ex in ex_lib.list_exercises():
            if ex["name"].strip().lower() == name.strip().lower():
                if ex.get("garmin_category") and ex.get("garmin_exercise"):
                    return ex["garmin_category"], ex["garmin_exercise"]
                break
    except Exception:
        pass
    key = name.strip().lower()
    if key in EXERCISES:
        return EXERCISES[key]
    for k, v in EXERCISES.items():
        if k in key:
            return v
    try:
        from . import exercises as ex_lib
        return ex_lib.guess_garmin_mapping(name)
    except Exception:
        return None


def _build_step(step: dict[str, Any], order: list[int], sport: str) -> dict[str, Any]:
    """order ist eine Ein-Element-Liste als mutable Zähler."""
    stype = step.get("type", "work")
    if stype == "repeat":
        my_order = order[0]
        order[0] += 1
        children = [_build_step(s, order, sport) for s in step.get("steps", [])]
        count = int(step.get("count", 2))
        return {
            "type": "RepeatGroupDTO",
            "stepOrder": my_order,
            "stepType": STEP_TYPES["repeat"],
            "numberOfIterations": count,
            "smartRepeat": False,
            "endCondition": END_ITER,
            "endConditionValue": count,
            "workoutSteps": children,
        }

    my_order = order[0]
    order[0] += 1
    dto: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": my_order,
        "stepType": STEP_TYPES.get(stype, STEP_TYPES["work"]),
        "endCondition": END_LAP,
        "endConditionValue": None,
        "targetType": NO_TARGET,
    }

    desc_parts = []
    if step.get("name"):
        desc_parts.append(str(step["name"]))
    if step.get("notes"):
        desc_parts.append(str(step["notes"]))

    if step.get("reps"):
        dto["endCondition"] = END_REPS
        dto["endConditionValue"] = int(step["reps"])
    elif step.get("duration_s"):
        dto["endCondition"] = END_TIME
        dto["endConditionValue"] = int(step["duration_s"])
    elif step.get("distance_m"):
        dto["endCondition"] = END_DIST
        dto["endConditionValue"] = float(step["distance_m"])

    pace = step.get("pace_min_km")
    if isinstance(pace, (list, tuple)) and len(pace) == 2:
        slow, fast = _pace_to_mps(pace[0]), _pace_to_mps(pace[1])
        if slow and fast:
            dto["targetType"] = PACE_TARGET
            dto["targetValueOne"] = min(slow, fast)
            dto["targetValueTwo"] = max(slow, fast)
    elif step.get("hr_zone"):
        dto["targetType"] = HR_ZONE_TARGET
        dto["zoneNumber"] = int(step["hr_zone"])

    if sport in ("strength", "mobility", "yoga", "cardio", "hiit"):
        # Steht die Garmin-Übung am Schritt selbst (z. B. bei Yoga-Stellungen),
        # hat sie Vorrang — dann zeigt die Uhr Name und Abbildung korrekt an,
        # statt nur einen namenlosen Zeitblock.
        if step.get("garmin_category") and step.get("garmin_exercise"):
            category = step["garmin_category"]
            # Garmin prüft die Kategorie gegen die Sportart des Workouts und
            # lehnt das ganze Workout mit "invalid category" ab, wenn sie nicht
            # dazu passt. Eine Yoga-Stellung in einer Krafteinheit ist genau so
            # ein Fall. Lieber ohne Kategorie senden — dann wird es ein
            # benannter Zeitblock statt einer Absage.
            if category in ALLOWED_CATEGORIES.get(sport, set()) \
                    or not ALLOWED_CATEGORIES.get(sport):
                dto["category"] = category
                dto["exerciseName"] = step["garmin_exercise"]
        else:
            ex = _find_exercise(step.get("name"))
            if ex and (ex[0] in ALLOWED_CATEGORIES.get(sport, set())
                       or not ALLOWED_CATEGORIES.get(sport)):
                dto["category"], dto["exerciseName"] = ex
        if step.get("weight_kg"):
            desc_parts.append(f"{step['weight_kg']} kg")
            # Garmin erwartet das Zielgewicht in Gramm
            dto["weightValue"] = float(step["weight_kg"])
            dto["weightUnit"] = {"unitKey": "kilogram"}

    if desc_parts:
        dto["description"] = " — ".join(desc_parts)
    return dto


def build_garmin_workout(name: str, sport: str, steps: list[dict[str, Any]],
                         description: str | None = None) -> dict[str, Any]:
    sport_type = SPORT_TYPES.get(sport, SPORT_TYPES["other"])
    order = [1]
    workout_steps = [_build_step(s, order, sport) for s in steps]
    return {
        "workoutName": name[:80],
        "description": (description or "")[:1024] or None,
        "sportType": sport_type,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": sport_type,
                "workoutSteps": workout_steps,
            }
        ],
    }


# ---------------------------------------------------------------- FIT-Export

def build_fit_workout(name: str, sport: str, steps: list[dict[str, Any]]) -> bytes:
    """FIT-Workout-Datei als Fallback für den manuellen Import in Garmin Connect."""
    from fit_tool.fit_file_builder import FitFileBuilder
    from fit_tool.profile.messages.file_id_message import FileIdMessage
    from fit_tool.profile.messages.workout_message import WorkoutMessage
    from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
    from fit_tool.profile.profile_type import (
        FileType, Intensity, Manufacturer, Sport, WorkoutStepDuration,
        WorkoutStepTarget,
    )

    sport_map = {
        "running": Sport.RUNNING,
        "cycling": Sport.CYCLING,
        "strength": Sport.TRAINING,
        "cardio": Sport.TRAINING,
        "mobility": Sport.TRAINING,
        "hiit": Sport.TRAINING,
    }
    intensity_map = {
        "warmup": Intensity.WARMUP,
        "cooldown": Intensity.COOLDOWN,
        "work": Intensity.ACTIVE,
        "recovery": Intensity.RECOVERY,
        "rest": Intensity.REST,
    }

    builder = FitFileBuilder(auto_define=True)
    file_id = FileIdMessage()
    file_id.type = FileType.WORKOUT
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.product = 0
    file_id.serial_number = 0x12345678
    builder.add(file_id)

    step_messages: list[WorkoutStepMessage] = []

    def add_step(step: dict[str, Any]) -> None:
        if step.get("type") == "repeat":
            start_index = len(step_messages)
            for child in step.get("steps", []):
                add_step(child)
            msg = WorkoutStepMessage()
            msg.message_index = len(step_messages)
            msg.duration_type = WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT
            msg.duration_value = start_index
            msg.target_value = int(step.get("count", 2))
            step_messages.append(msg)
            return
        msg = WorkoutStepMessage()
        msg.message_index = len(step_messages)
        name_txt = str(step.get("name") or step.get("type") or "Step")[:15]
        msg.workout_step_name = name_txt
        msg.intensity = intensity_map.get(step.get("type", "work"), Intensity.ACTIVE)
        if step.get("duration_s"):
            msg.duration_type = WorkoutStepDuration.TIME
            msg.duration_time = float(step["duration_s"])
        elif step.get("distance_m"):
            msg.duration_type = WorkoutStepDuration.DISTANCE
            msg.duration_distance = float(step["distance_m"])
        elif step.get("reps"):
            msg.duration_type = WorkoutStepDuration.REPS
            msg.duration_value = int(step["reps"])
        else:
            msg.duration_type = WorkoutStepDuration.OPEN
        msg.target_type = WorkoutStepTarget.OPEN
        step_messages.append(msg)

    for s in steps:
        add_step(s)

    workout = WorkoutMessage()
    workout.workout_name = name[:30]
    workout.sport = sport_map.get(sport, Sport.TRAINING)
    workout.num_valid_steps = len(step_messages)
    builder.add(workout)
    builder.add_all(step_messages)

    return builder.build().to_bytes()
