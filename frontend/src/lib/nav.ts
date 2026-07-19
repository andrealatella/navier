import { useStore, type RouteInfo } from "../state/store";
import { routeLayer } from "../map/routeLayer";
import { liveSocket } from "./ws";

interface RouteResponse {
  provider: string;
  distance_km: number;
  duration_min: number;
  geometry: GeoJSON.LineString;
  start: { lat: number; lon: number };
  dest: { lat: number; lon: number };
  cell_id: number | null;
  intercept: boolean;
  note: string | null;
  crosses_cone_cell_ids: number[];
  maps_url: string;
}

const HTTP_MSG: Record<number, string> = {
  409: "posizione sconosciuta: imposta prima la tua posizione",
  404: "la cella non è più tracciata",
  400: "destinazione mancante",
  502: "servizio di routing non raggiungibile",
};

export function mapsDeeplink(lat: number, lon: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat.toFixed(6)},${lon.toFixed(6)}&travelmode=driving`;
}

export async function planRoute(opts?: { dest?: { lat: number; lon: number } }): Promise<void> {
  const s = useStore.getState();
  const cellId = s.targetCellId;
  const body =
    opts?.dest != null
      ? { dest_lat: opts.dest.lat, dest_lon: opts.dest.lon }
      : cellId != null
        ? { cell_id: cellId, mode: s.interceptMode ? "intercept" : "direct" }
        : null;
  if (body == null) return;

  s.setRouteLoading(true);
  try {
    const resp = await fetch("/api/route", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      let detail = HTTP_MSG[resp.status] ?? `errore ${resp.status}`;
      try {
        const j = await resp.json();
        if (typeof j.detail === "string") detail = j.detail;
      } catch {
      }
      s.setRouteError(detail);
      routeLayer.clear();
      return;
    }
    const data: RouteResponse = await resp.json();
    const info: RouteInfo = {
      provider: data.provider,
      distanceKm: data.distance_km,
      durationMin: data.duration_min,
      cellId: data.cell_id,
      intercept: data.intercept,
      note: data.note,
      crosses: data.crosses_cone_cell_ids ?? [],
      dest: data.dest,
      mapsUrl: data.maps_url,
    };
    s.setRoute(info);
    routeLayer.setRoute({
      geometry: data.geometry,
      dest: data.dest,
      crosses: info.crosses.length > 0,
    });
  } catch {
    s.setRouteError("errore di rete nel calcolo rotta");
    routeLayer.clear();
  }
}

export function clearRoute(): void {
  useStore.getState().setRoute(null);
  routeLayer.clear();
}

export function openInMaps(lat: number, lon: number, label?: string): void {
  liveSocket.send("open_maps", { lat, lon, label });
  window.open(mapsDeeplink(lat, lon), "_blank", "noopener");
}
