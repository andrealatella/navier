"""REST endpoints: health, radar frames, planning, allerte, outlook, routing and"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from .. import __version__, runtime
from ..config import settings
from ..models import RouteRequest
from ..routing.intercept import intercept_point, maps_deeplink, route_crosses_cones
from ..routing.service import build_provider
from ..store.allerte import allerte_store
from ..store.hub import hub
from ..store.memory import lightning_store
from ..store.meteo import meteo_store
from ..store.outlook import outlook_store
from ..store.radar import radar_store

router = APIRouter(prefix="/api", tags=["rest"])


@router.get("/health")
async def health() -> dict:
    """Liveness + a snapshot of which sources are enabled (feature flags)."""
    return {
        "status": "ok",
        "version": __version__,
        "time": datetime.now(UTC).isoformat(),
        "ws_clients": hub.client_count,
        "sources_enabled": {
            "blitzortung": settings.enable_blitzortung,
            "dpc_radar": settings.enable_dpc_radar,
            "openmeteo": settings.enable_openmeteo,
            "rainviewer": settings.enable_rainviewer,
            "pretemp": settings.enable_pretemp,
            "dpc_allerte": settings.enable_dpc_allerte,
            "gpsd": settings.enable_gpsd,
            "fake_lightning": settings.enable_fake_lightning,
        },
        "replay": bool(settings.replay_file),
        "lightning_count": lightning_store.count(),
        "sources_health": runtime.source_health_payload()["sources"],
    }


@router.get("/radar/frames")
async def radar_frames() -> dict:
    """The active radar source (DPC or RainViewer) and its ordered frame list."""
    return radar_store.active_payload()


@router.get("/copilot/status")
async def copilot_status() -> dict:
    """Co-pilot availability + budget. Shows why it's dormant when it is."""
    return runtime.copilot_status_payload()


@router.get("/planning")
async def planning(hour: int | None = None) -> dict:
    """Planning data: the CAPE/shear heatmap grid for one forecast hour."""
    if not meteo_store.available:
        enabled = settings.enable_openmeteo
        reason = "in caricamento…" if enabled else "Open-Meteo disattivato (ENABLE_OPENMETEO=0)"
        return {"available": False, "reason": reason, "model": settings.openmeteo_model}
    hm = meteo_store.heatmap(hour)
    hm["available"] = True
    hm["model"] = settings.openmeteo_model
    return hm


@router.get("/allerte")
async def allerte() -> dict:
    """Official DPC criticality bulletin: alert zones as a choropleth FeatureCollection."""
    return allerte_store.wire()


@router.get("/outlook")
async def outlook() -> dict:
    """Convective outlooks for planning: PRETEMP map + ESTOFEX link."""
    return outlook_store.wire()


@router.post("/route")
async def route(req: RouteRequest) -> dict:
    """Plan a driving route to a cell (intercept point) or a raw point."""
    proc = runtime.processor()

    if req.start_lat is not None and req.start_lon is not None:
        start = (req.start_lon, req.start_lat)
    else:
        user = proc.current_user() if proc is not None else None
        if user is None:
            raise HTTPException(status_code=409, detail="posizione utente sconosciuta")
        start = (user.lon, user.lat)

    intercept = False
    note: str | None = None
    cell_id: int | None = None
    if req.cell_id is not None:
        cell = proc.find_cell(req.cell_id) if proc is not None else None
        if cell is None:
            raise HTTPException(status_code=404, detail=f"cella {req.cell_id} non tracciata")
        cell_id = cell.id
        if req.mode == "intercept":
            dest, intercept, note = intercept_point(
                cell,
                start,
                settings.intercept_horizon_min,
                settings.intercept_offset_km,
            )
        else:
            dest = (cell.centroid[0], cell.centroid[1])
    elif req.dest_lat is not None and req.dest_lon is not None:
        dest = (req.dest_lon, req.dest_lat)
    else:
        raise HTTPException(status_code=400, detail="serve cell_id oppure dest_lat/dest_lon")

    provider = build_provider(settings)
    r = await provider.route(start, dest)
    if r is None:
        raise HTTPException(status_code=502, detail=f"routing non disponibile ({provider.name})")

    cells = proc.current_cells() if proc is not None else []
    crossed = route_crosses_cones(r.coordinates, cells)

    return {
        "provider": r.provider,
        "distance_km": r.distance_km,
        "duration_min": r.duration_min,
        "geometry": r.geometry(),
        "start": {"lat": round(start[1], 5), "lon": round(start[0], 5)},
        "dest": {"lat": round(dest[1], 5), "lon": round(dest[0], 5)},
        "cell_id": cell_id,
        "intercept": intercept,
        "note": note,
        "crosses_cone_cell_ids": crossed,
        "maps_url": maps_deeplink(dest[1], dest[0]),
    }


@router.get("/sessions")
async def sessions() -> dict:
    """Recorded sessions for replay: list + whether we're recording/replaying."""
    return runtime.list_recorded_sessions()


@router.get("/sessions/{name}/report")
async def session_report(name: str) -> dict:
    """Post-chase summary of one recorded session: stats + alert timeline."""
    from ..store.report import build_report

    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="nome sessione non valido")
    session_dir = settings.sessions_path / name
    report = build_report(session_dir)
    if report is None:
        raise HTTPException(status_code=404, detail=f"sessione {name} non trovata")
    return report


@router.get("/basemap")
async def basemap() -> dict:
    """Whether an offline PMTiles basemap is available."""
    p = settings.basemap_pmtiles_path
    if p.is_file():
        return {"available": True, "url": "/api/basemap.pmtiles", "size_bytes": p.stat().st_size}
    return {"available": False, "url": None}


@router.get("/basemap.pmtiles")
async def basemap_file() -> Response:
    """Serve the offline PMTiles archive with HTTP range support (the JS lib needs it)."""
    p = settings.basemap_pmtiles_path
    if not p.is_file():
        raise HTTPException(status_code=404, detail="nessun basemap offline")
    return FileResponse(
        p,
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/radar/frame/{ts_ms}.png")
async def radar_frame_png(ts_ms: int) -> Response:
    """Serve one radar frame PNG by its epoch-ms timestamp (live store, or replay session)."""
    png = radar_store.get_png(ts_ms) or runtime.replay_frame_png(ts_ms)
    if png is None:
        return Response(status_code=404)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
