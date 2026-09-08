"""PULS — dein lokaler Trainingscoach."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers.api import router
from .services import scheduler
from .services.ollama_client import is_available, model_present, pull_model

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("puls")

STATIC_DIR = Path(__file__).parent / "static"


def _ensure_model() -> None:
    """Beim Start im Hintergrund prüfen, ob das Modell da ist — sonst ziehen."""
    try:
        if is_available() and not model_present():
            pull_model()
    except Exception as e:
        log.warning("Modell-Download fehlgeschlagen (später erneut möglich): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    threading.Thread(target=_ensure_model, daemon=True).start()
    scheduler.start()
    log.info("PULS läuft.")
    yield
    scheduler.shutdown()


app = FastAPI(title="PULS Trainingscoach", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.json")
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.json")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")
