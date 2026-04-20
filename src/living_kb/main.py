from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from living_kb.api.routes import router
from living_kb.config import get_settings
from living_kb.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.is_sqlite:
        init_db()
    yield


app = FastAPI(
    title="Living KB",
    version="0.1.0",
    description="Agentic knowledge base MVP",
    lifespan=lifespan,
)
app.include_router(router)

WEB_ROOT = Path(__file__).resolve().parent / "web"
STATIC_ROOT = WEB_ROOT / "static"
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "Living KB",
        "status": "ok",
        "docs": "/docs",
        "app": "/app",
    }


@app.get("/app")
def admin_app() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")
