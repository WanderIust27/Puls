"""PULS — dein lokaler Trainingscoach."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .version import BUILT_AT, VERSION
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
    log.info("PULS läuft. Version %s (Stand %s)", VERSION, BUILT_AT)
    yield
    scheduler.shutdown()


app = FastAPI(title="PULS Trainingscoach", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> HTMLResponse:
    """Die Oberflaeche, mit Versionsstempel an den statischen Dateien.

    Ohne den laedt der Browser nach einem Update die alte app.js aus seinem
    Cache weiter — die Datei heisst ja gleich. Der Stempel aendert sich mit
    jedem Build, also laedt er genau dann neu, wenn es noetig ist.
    """
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{V}}", VERSION))


@app.get("/manifest.json")
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.json")


@app.get("/sw.js")
def service_worker() -> Response:
    """Der Service Worker traegt die Version in seinen Cache-Namen.

    Nur so raeumt er beim Aktivieren den alten Bestand ab — sonst haelt er
    nach einem Update weiter die alten Dateien vor.
    """
    js = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    return Response(js.replace("{{V}}", VERSION),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})
