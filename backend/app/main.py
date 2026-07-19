"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__, runtime
from .api import rest, ws
from .api.static import mount_static
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("navier")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start and stop the background tasks."""
    logger.info("NAVIER backend v%s starting up", __version__)
    logger.info("replay mode: %s", settings.replay_file or "off")
    await runtime.start()
    yield
    logger.info("NAVIER backend shutting down")
    await runtime.stop()


app = FastAPI(
    title="NAVIER",
    version=__version__,
    summary="Nowcasting, tracking e co-pilota AI per lo storm chasing in Italia",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest.router)
app.include_router(ws.router)

mount_static(app)


def main() -> None:
    """Run the server on the configured host/port (default :5700)."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.uvicorn_reload,
    )


if __name__ == "__main__":
    main()
