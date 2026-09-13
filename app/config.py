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
_BUNDLED_KB = Path(__file__).parent.parent / "knowledge"


def _knowledge_dir() -> Path:
    """Wo die Markdown-Dateien liegen — mit Rueckfallebene.

    Ein Bind-Mount auf einen leeren Ordner schiebt sich ueber die Dateien im
    Image. Dann steht /knowledge zwar da, ist aber leer, und die
    Wissensdatenbank bliebe still ohne Inhalt. Liegt dort nichts, wird deshalb
    die mitgelieferte Kopie genommen.
    """
    named = os.environ.get("PULS_KB")
    if named:
        chosen = Path(named)
        if any(chosen.glob("*.md")):
            return chosen
        if any(_BUNDLED_KB.glob("*.md")):
            import logging
            logging.getLogger("puls.config").warning(
                "%s enthält keine .md-Dateien — nehme die Kopie aus dem Image "
                "(%s).", chosen, _BUNDLED_KB)
            return _BUNDLED_KB
        return chosen
    return _BUNDLED_KB


KNOWLEDGE_DIR = _knowledge_dir()
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
