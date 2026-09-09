"""Fingerabdruck des laufenden Stands.

Damit sich nachsehen laesst, welche Version tatsaechlich laeuft: Nach einem
Update, das nicht anzukommen scheint, ist die erste Frage immer, ob der
Container ueberhaupt neu gebaut wurde. Ohne eine sichtbare Kennung laesst sich
das nur raten.

Berechnet wird der Wert beim Start aus Groesse und Aenderungszeit der eigenen
Dateien. Kein Build-Argument noetig, keine Datei zu pflegen — er aendert sich
genau dann, wenn sich der Code aendert.

Zweiter Zweck: Der Wert haengt an den Adressen von app.js und style.css, damit
der Browser eine neue Fassung laedt statt der gecachten alten.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

APP_DIR = Path(__file__).parent


def _fingerprint() -> str:
    h = hashlib.sha256()
    for path in sorted(APP_DIR.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        h.update(str(path.relative_to(APP_DIR)).encode())
        h.update(str(stat.st_size).encode())
        h.update(str(int(stat.st_mtime)).encode())
    return h.hexdigest()[:10]


def _built_at() -> str:
    """Juengste Aenderungszeit — praktisch der Zeitpunkt des Builds."""
    import datetime as dt
    newest = 0.0
    for path in APP_DIR.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    if not newest:
        return "unbekannt"
    return dt.datetime.fromtimestamp(newest).isoformat(timespec="minutes")


VERSION = _fingerprint()
BUILT_AT = _built_at()
