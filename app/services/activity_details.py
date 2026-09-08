"""Detaildaten einer Aktivitaet: GPS-Spur und Messkurven.

Garmin liefert pro Lauf mehrere tausend Messpunkte und eine GPS-Spur in voller
Aufloesung — je nach Dauer ein bis drei Megabyte. In einer Karte auf dem Handy
und in einem Diagramm von 900 Pixel Breite ist davon nichts zu sehen: mehr als
ein paar hundert Punkte kann keine der beiden Darstellungen aufloesen.

Deshalb wird beim Sync ausgeduennt — Kurven durch Mittelung in Zeitfenstern,
die GPS-Spur mit Douglas-Peucker. Uebrig bleiben rund 30-80 kB pro Lauf, die
optisch nicht von den Rohdaten zu unterscheiden sind. So passt jeder Lauf
dauerhaft ins Volume, statt nach ein paar Monaten geloescht werden zu muessen.

Die Funktionen hier rechnen nur — das Holen der Daten steht in garmin_sync.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("puls.details")

TARGET_POINTS = 400          # Messpunkte je Kurve nach dem Ausduennen
TRACK_TOLERANCE_DEG = 1.2e-5  # rund 1,3 m — darunter sieht man nichts mehr
MAX_TRACK_POINTS = 900

# Garmins Bezeichner -> unsere Namen. Was fehlt, wird stillschweigend
# weggelassen: Bodenkontaktzeit und vertikale Bewegung liefert die Fenix nur
# mit Brustgurt oder RD-Pod.
METRIC_KEYS: dict[str, str] = {
    "directTimestamp": "ts",
    "sumElapsedDuration": "t",
    "sumDuration": "t",
    "directHeartRate": "hr",
    "directSpeed": "speed",
    "directElevation": "ele",
    "directDoubleCadence": "cadence",
    "directRunCadence": "cadence",
    "sumDistance": "dist",
    "directPower": "power",
    "directGroundContactTime": "gct",
    "directVerticalOscillation": "vo",
    "directStrideLength": "stride",
    "directVerticalRatio": "vratio",
    "directFractionalCadence": None,
}


def _descriptor_index(details: dict[str, Any]) -> dict[str, int]:
    """Ordnet unsere Namen den Spaltennummern in activityDetailMetrics zu."""
    mapping: dict[str, int] = {}
    for desc in details.get("metricDescriptors") or []:
        key = desc.get("key")
        idx = desc.get("metricsIndex")
        name = METRIC_KEYS.get(key)
        if name and idx is not None and name not in mapping:
            mapping[name] = idx
    return mapping


def _bucket_average(values: list[float | None], buckets: int) -> list[float | None]:
    """Mittelt in gleich grosse Zeitfenster. Luecken bleiben Luecken."""
    if buckets <= 0 or not values:
        return []
    out: list[float | None] = []
    total = len(values)
    for i in range(buckets):
        lo = i * total // buckets
        hi = max(lo + 1, (i + 1) * total // buckets)
        chunk = [v for v in values[lo:hi] if v is not None]
        out.append(round(sum(chunk) / len(chunk), 2) if chunk else None)
    return out


def extract_series(details: dict[str, Any],
                   target: int = TARGET_POINTS) -> dict[str, Any]:
    """Baut aus Garmins Rohmatrix ausgeduennte Kurven."""
    rows = details.get("activityDetailMetrics") or []
    index = _descriptor_index(details)
    if not rows or not index:
        return {}

    columns: dict[str, list[float | None]] = {name: [] for name in index}
    for row in rows:
        metrics = row.get("metrics") or []
        for name, idx in index.items():
            value = metrics[idx] if idx < len(metrics) else None
            columns[name].append(value if isinstance(value, (int, float)) else None)

    buckets = min(target, len(rows))
    series: dict[str, Any] = {"points": buckets}

    # Zeitachse in Sekunden seit dem Start
    if "t" in columns and any(v is not None for v in columns["t"]):
        raw = columns["t"]
    elif "ts" in columns and any(v is not None for v in columns["ts"]):
        stamps = [v for v in columns["ts"] if v is not None]
        base = stamps[0] if stamps else 0
        # Zeitstempel kommen in Millisekunden
        raw = [(v - base) / 1000.0 if v is not None else None for v in columns["ts"]]
    else:
        raw = [float(i) for i in range(len(rows))]
    series["t"] = [int(v) if v is not None else None
                   for v in _bucket_average(raw, buckets)]

    for name in ("hr", "ele", "cadence", "dist", "power", "gct", "vo",
                 "stride", "vratio"):
        if name in columns and any(v is not None for v in columns[name]):
            series[name] = _bucket_average(columns[name], buckets)

    # Tempo ist anschaulicher als Geschwindigkeit: Sekunden je Kilometer.
    # Unter 0,5 m/s (Ampel, Pause) waeren die Werte sinnlos gross.
    if "speed" in columns:
        speeds = _bucket_average(columns["speed"], buckets)
        series["pace"] = [round(1000.0 / v) if v and v > 0.5 else None
                          for v in speeds]
        series["speed"] = speeds
    return series


def _perpendicular_distance(point: tuple[float, float],
                            start: tuple[float, float],
                            end: tuple[float, float]) -> float:
    (x, y), (x1, y1), (x2, y2) = point, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / (dx * dx + dy * dy) ** 0.5


def simplify_track(points: list[dict[str, float]],
                   tolerance: float = TRACK_TOLERANCE_DEG) -> list[dict[str, float]]:
    """Douglas-Peucker: entfernt Punkte, die die Linienform nicht veraendern.

    Auf einer geraden Strasse bleiben Anfang und Ende uebrig, in einer engen
    Kurve jeder Punkt. Genau das, was eine Karte braucht.
    """
    if len(points) < 3:
        return points

    coords = [(p["lat"], p["lon"]) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        worst, worst_i = 0.0, first
        for i in range(first + 1, last):
            d = _perpendicular_distance(coords[i], coords[first], coords[last])
            if d > worst:
                worst, worst_i = d, i
        if worst > tolerance:
            keep[worst_i] = True
            stack.append((first, worst_i))
            stack.append((worst_i, last))
    return [p for p, k in zip(points, keep) if k]


def extract_track(details: dict[str, Any]) -> tuple[list[dict[str, float]],
                                                    dict[str, float] | None]:
    """GPS-Spur samt Eckpunkten fuer den Kartenausschnitt."""
    geo = details.get("geoPolylineDTO") or {}
    raw = geo.get("polyline") or []
    points: list[dict[str, float]] = []
    for p in raw:
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        point = {"lat": round(lat, 6), "lon": round(lon, 6)}
        if p.get("altitude") is not None:
            point["ele"] = round(p["altitude"], 1)
        points.append(point)
    if not points:
        return [], None

    simplified = simplify_track(points)
    if len(simplified) > MAX_TRACK_POINTS:
        step = len(simplified) / MAX_TRACK_POINTS
        simplified = [simplified[int(i * step)] for i in range(MAX_TRACK_POINTS)]

    lats = [p["lat"] for p in simplified]
    lons = [p["lon"] for p in simplified]
    bounds = {
        "min_lat": min(lats), "max_lat": max(lats),
        "min_lon": min(lons), "max_lon": max(lons),
    }
    return simplified, bounds


def condense(details: dict[str, Any]) -> dict[str, Any]:
    """Alles zusammen: was gespeichert wird."""
    series = extract_series(details)
    track, bounds = extract_track(details)
    return {
        "series_json": json.dumps(series, separators=(",", ":")) if series else None,
        "track_json": json.dumps(track, separators=(",", ":")) if track else None,
        "bounds_json": json.dumps(bounds, separators=(",", ":")) if bounds else None,
        "point_count": series.get("points", 0),
    }
