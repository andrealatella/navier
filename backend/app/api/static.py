"""Serve the built frontend from the backend."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..config import settings

logger = logging.getLogger("navier.static")

_DEV_HINT = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><title>NAVIER</title>
<style>body{background:#0b0f17;color:#cbd5e1;font-family:system-ui;padding:3rem;line-height:1.6}
code{background:#1e293b;padding:.15rem .4rem;border-radius:4px;color:#38bdf8}</style></head>
<body>
<h1>⛈️ NAVIER - backend attivo</h1>
<p>Il frontend buildato non è ancora presente in <code>backend/app/static_dist/</code>.</p>
<p>In sviluppo apri il dev server Vite: <code>cd frontend &amp;&amp; npm run dev</code> → <code>http://localhost:5173</code></p>
<p>Per servire tutto da qui: <code>npm run build</code> nel frontend, poi ricarica.</p>
<p>API attive: <code>GET /api/health</code> · WebSocket: <code>/ws/live</code></p>
</body></html>"""


def mount_static(app: FastAPI) -> None:
    """Mount the built SPA at `/` if present, else serve a dev hint page."""
    static_dir = settings.static_dir
    index = static_dir / "index.html"
    if static_dir.is_dir() and index.exists():
        @app.get("/companion", response_class=FileResponse, include_in_schema=False)
        async def _companion() -> FileResponse:
            return FileResponse(index)

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
        logger.info("serving built frontend from %s", static_dir)
    else:
        logger.info("no built frontend at %s - serving dev hint at /", static_dir)

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def _dev_root() -> str:
            return _DEV_HINT
