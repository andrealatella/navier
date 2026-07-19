import type { Map as MLMap, GeoJSONSource } from "maplibre-gl";
import type { UserPos } from "../state/store";

const SRC = "user";
const SRC_RING = "user-ring";
const L_RING = "user-ring-fill";
const L_RING_LINE = "user-ring-line";
const L_DOT = "user-dot";
const L_HEADING = "user-heading";

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
const NEAR_KM = 5;

class UserLayer {
  private map: MLMap | null = null;
  private user: UserPos | null = null;

  attach(map: MLMap): void {
    this.map = map;
    if (!map.getSource(SRC_RING)) map.addSource(SRC_RING, { type: "geojson", data: EMPTY });
    if (!map.getSource(SRC)) map.addSource(SRC, { type: "geojson", data: EMPTY });

    map.addLayer({
      id: L_RING,
      type: "fill",
      source: SRC_RING,
      paint: { "fill-color": "#38bdf8", "fill-opacity": 0.06 },
    });
    map.addLayer({
      id: L_RING_LINE,
      type: "line",
      source: SRC_RING,
      paint: { "line-color": "#38bdf8", "line-width": 1, "line-opacity": 0.5, "line-dasharray": [3, 3] },
    });
    map.addLayer({
      id: L_HEADING,
      type: "symbol",
      source: SRC,
      filter: ["get", "hasHeading"],
      layout: {
        "text-field": "▲",
        "text-size": 16,
        "text-rotate": ["get", "heading"],
        "text-rotation-alignment": "map",
        "text-allow-overlap": true,
      },
      paint: { "text-color": "#38bdf8", "text-halo-color": "#0b0f17", "text-halo-width": 1.5 },
    });
    map.addLayer({
      id: L_DOT,
      type: "circle",
      source: SRC,
      paint: {
        "circle-radius": 6,
        "circle-color": "#0ea5e9",
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });

    if (this.user) this.render();
  }

  setUser(user: UserPos | null): void {
    this.user = user;
    this.render();
  }

  private render(): void {
    const map = this.map;
    if (!map) return;
    const u = this.user;
    const dot = map.getSource(SRC) as GeoJSONSource | undefined;
    const ring = map.getSource(SRC_RING) as GeoJSONSource | undefined;
    if (!u) {
      dot?.setData(EMPTY);
      ring?.setData(EMPTY);
      return;
    }
    dot?.setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [u.lon, u.lat] },
          properties: { hasHeading: u.heading_deg != null, heading: u.heading_deg ?? 0 },
        },
      ],
    });
    ring?.setData(this.circle(u.lon, u.lat, NEAR_KM));
  }

  private circle(lon: number, lat: number, km: number): GeoJSON.FeatureCollection {
    const pts: [number, number][] = [];
    const dLat = km / 110.574;
    const dLon = km / (111.32 * Math.cos((lat * Math.PI) / 180));
    for (let i = 0; i <= 48; i++) {
      const a = (i / 48) * 2 * Math.PI;
      pts.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
    }
    return {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: { type: "Polygon", coordinates: [pts] }, properties: {} }],
    };
  }

  detach(): void {
    this.map = null;
    this.user = null;
  }
}

export const userLayer = new UserLayer();
