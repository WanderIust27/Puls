"""Zentrale Konfiguration — alles über Umgebungsvariablen steuerbar."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("PULS_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "puls.db"
GARMIN_TOKEN_DIR = DATA_DIR / "garmin_tokens"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))  # CPU-Inferenz darf dauern

SYNC_INTERVAL_HOURS = float(os.environ.get("SYNC_INTERVAL_HOURS", "3"))
SYNC_LOOKBACK_DAYS = int(os.environ.get("SYNC_LOOKBACK_DAYS", "14"))

TZ = os.environ.get("TZ", "Europe/Berlin")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
