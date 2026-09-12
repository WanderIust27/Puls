"""Dünner Client für die lokale Ollama-Instanz (CPU-Inferenz, darf dauern)."""
from __future__ import annotations

import json
import os
import logging
from typing import Any

import httpx

from ..config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL
from ..db import get_setting

log = logging.getLogger("puls.ollama")

# Auswahl für die Oberfläche. Größen sind Richtwerte für die Q4-Quantisierung;
# die Geschwindigkeit gilt für reine CPU-Rechnung auf einem Heimserver.
MODEL_PRESETS = [
    {"name": "qwen3:8b", "label": "Qwen 3 · 8B",
     "size_gb": 4.7, "speed": "gemütlich",
     "note": "Empfohlen. Beste Antwortqualität in dieser Größe, gutes Deutsch. "
             "Braucht etwa so viel Arbeitsspeicher wie das alte 7B-Modell."},
    {"name": "qwen3:4b", "label": "Qwen 3 · 4B",
     "size_gb": 2.8, "speed": "flott",
     "note": "Rund doppelt so schnell, immer noch klar besser als die "
             "Vorgängergeneration. Gute Wahl, wenn dir Warten lästig ist."},
    {"name": "gemma3:4b", "label": "Gemma 3 · 4B",
     "size_gb": 2.6, "speed": "flott",
     "note": "Sehr sprachstark für seine Größe, formuliert oft natürlicher."},
    {"name": "llama3.2:3b", "label": "Llama 3.2 · 3B",
     "size_gb": 2.0, "speed": "schnell",
     "note": "Der Sparsame. Für kurze Rückmeldungen genug, bei längeren "
             "Begründungen merkt man die Größe."},
    {"name": "qwen2.5:7b-instruct-q4_K_M", "label": "Qwen 2.5 · 7B (alt)",
     "size_gb": 4.7, "speed": "gemütlich",
     "note": "Das bisherige Modell. Nur behalten, falls du damit zufrieden bist."},
]


class OllamaUnavailable(Exception):
    pass


def active_model() -> str:
    """In der Oberfläche gewähltes Modell, sonst der Wert aus der Umgebung."""
    return get_setting("ollama_model", "") or OLLAMA_MODEL


def is_available() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def installed_models() -> list[dict[str, Any]]:
    """Was auf dem Server tatsächlich heruntergeladen ist."""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        return r.json().get("models", []) or []
    except httpx.HTTPError:
        return []


def model_present(name: str | None = None) -> bool:
    name = name or active_model()
    names = [m.get("name", "") for m in installed_models()]
    if name in names:
        return True
    # "qwen3:8b" und "qwen3:8b-instruct-q4_K_M" gelten als dasselbe Modell
    base = name.split(":")[0]
    return any(n.split(":")[0] == base for n in names)


# Fortschritt eines laufenden Downloads — für die Anzeige in der Oberfläche
_pull_state: dict[str, Any] = {"model": None, "status": "idle", "percent": 0,
                               "error": None}


def pull_state() -> dict[str, Any]:
    return dict(_pull_state)


def pull_model(name: str | None = None) -> None:
    """Modell herunterladen. Blockiert — gehört in einen Hintergrund-Thread."""
    name = name or active_model()
    _pull_state.update({"model": name, "status": "laden", "percent": 0, "error": None})
    log.info("Lade Modell %s — das kann eine Weile dauern.", name)
    try:
        with httpx.stream("POST", f"{OLLAMA_URL}/api/pull",
                          json={"name": name}, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("error"):
                    _pull_state.update({"status": "fehler", "error": msg["error"]})
                    log.error("Download von %s fehlgeschlagen: %s", name, msg["error"])
                    return
                total, done = msg.get("total"), msg.get("completed")
                if total and done:
                    _pull_state["percent"] = round(done / total * 100)
                status = msg.get("status", "")
                _pull_state["detail"] = status
                if "success" in status:
                    _pull_state.update({"status": "fertig", "percent": 100})
                    log.info("Modell %s bereit.", name)
                    return
        _pull_state["status"] = "fertig"
    except httpx.HTTPError as e:
        _pull_state.update({"status": "fehler", "error": str(e)})
        log.error("Download von %s fehlgeschlagen: %s", name, e)


# Ollamas Vorgabe ist ein Kontextfenster von 4096 Token. Ist der Prompt
# laenger, schneidet Ollama ihn stillschweigend VON VORNE ab — und vorne steht
# bei uns das Playbook, also genau die Verhaltenssteuerung. Von aussen sieht
# man davon nichts: Es kommt eine fluessige, hoeflich formulierte Antwort, der
# nur die Haelfte ihrer Grundlage fehlt.
#
# Deshalb wird die Fenstergroesse hier aus der Prompt-Laenge bestimmt und nicht
# an den Aufrufstellen gesetzt. Eine Zahl, die man an sechs Stellen richtig
# setzen muss, wird irgendwann an einer vergessen.
CTX_STEPS = (4096, 8192, 16384)
CHARS_PER_TOKEN = 3.2          # Deutsch, grosszuegig geschaetzt
CTX_HEADROOM = 1.35            # Platz fuer die Antwort und den System-Prompt


def context_window(*parts: str | None) -> int:
    """Das kleinste Fenster, in das Prompt und Antwort sicher passen."""
    chars = sum(len(p or "") for p in parts)
    needed = int(chars / CHARS_PER_TOKEN * CTX_HEADROOM)
    cap = CTX_STEPS[-1]
    try:
        cap = int(os.environ.get("OLLAMA_NUM_CTX_MAX") or cap)
    except ValueError:
        pass
    for step in CTX_STEPS:
        if needed <= step:
            return min(step, cap)
    return cap


def generate(prompt: str, system: str | None = None,
             json_mode: bool = False, temperature: float = 0.7) -> str:
    """Eine Antwort vom lokalen Modell holen. Wirft OllamaUnavailable bei Problemen."""
    num_ctx = context_window(prompt, system)
    payload: dict[str, Any] = {
        "model": active_model(),
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    try:
        log.debug("Ollama: %d Zeichen Prompt, num_ctx=%d", len(prompt), num_ctx)
        r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload,
                       timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        return (r.json().get("response") or "").strip()
    except httpx.HTTPError as e:
        raise OllamaUnavailable(f"Ollama nicht erreichbar oder Fehler: {e}") from e


def generate_json(prompt: str, system: str | None = None,
                  temperature: float = 0.4) -> dict[str, Any]:
    """JSON-Antwort erzwingen und robust parsen."""
    text = generate(prompt, system=system, json_mode=True, temperature=temperature)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Notnagel: erstes {...} aus dem Text fischen
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise OllamaUnavailable(f"Modell lieferte kein gültiges JSON: {text[:200]}")
