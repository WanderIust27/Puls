"""Zentrale Konfiguration — alles über Umgebungsvariablen steuerbar."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("PULS_DATA_DIR", "/data"))
# PULS_DB kann die Datei einzeln setzen — die Wissensdatenbank und der
# Eval-Harness lesen dieselbe Variable.
DB_PATH = Path(os.environ["PULS_DB"]) if os.environ.get("PULS_DB") \
    else DATA_DIR / "puls.db"
GARMIN_TOKEN_DIR = DATA_DIR / "garmin_tokens"

# Die geprueften Markdown-Quellen. Im Container ein Bind-Mount, lokal der
# Ordner im Repo.
KNOWLEDGE_DIR = Path(os.environ.get("PULS_KB")
                     or Path(__file__).parent.parent / "knowledge")
# Das Playbook steuert das Verhalten und gehoert in den System-Prompt, nicht
# in den Abrufindex.
PLAYBOOK_FILE = KNOWLEDGE_DIR / "11_Coach_Playbook.md"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))  # CPU-Inferenz darf dauern

SYNC_INTERVAL_HOURS = float(os.environ.get("SYNC_INTERVAL_HOURS", "3"))
SYNC_LOOKBACK_DAYS = int(os.environ.get("SYNC_LOOKBACK_DAYS", "14"))

TZ = os.environ.get("TZ", "Europe/Berlin")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
