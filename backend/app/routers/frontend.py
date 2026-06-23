from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = BASE_DIR / "frontend"
PATHFINDING_FRONTEND_DIR = FRONTEND_DIR / "Pathfinding-Visualizer-ThreeJS-master"
PATHFINDING_DIST_DIR = PATHFINDING_FRONTEND_DIR / "dist"

router = APIRouter()


def mount_static_files(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    app.mount(
        "/Pathfinding-Visualizer-ThreeJS",
        StaticFiles(directory=PATHFINDING_DIST_DIR, html=True),
        name="pathfinding_frontend",
    )


@router.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse("/pathfinding")


@router.get("/pathfinding")
async def pathfinding_index() -> HTMLResponse:
    html = (PATHFINDING_DIST_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "<head>",
        '<head><script>if ("serviceWorker" in navigator) { navigator.serviceWorker.getRegistrations().then(function(registrations) { registrations.forEach(function(registration) { registration.unregister(); }); }); }</script>',
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/dashboard")
async def dashboard() -> RedirectResponse:
    return RedirectResponse("/pathfinding")
