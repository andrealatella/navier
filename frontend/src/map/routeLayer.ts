import type { Map as MLMap, GeoJSONSource } from "maplibre-gl";
import { addSvgImage, CROSSHAIR_SVG } from "./svgIcon";

const SRC = "route";
const SRC_DEST = "route-dest";
const L_CASING = "route-casing";
const L_LINE = "route-line";
const L_DEST = "route-dest-dot";
const L_DEST_LABEL = "route-dest-label";
const IMG_DEST = "route-dest-crosshair";

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export interface RouteGeom {
  geometry: GeoJSON.LineString;
  dest: { lat: number; lon: number };
  crosses: boolean;
}

class RouteLayer {
  private map: MLMap | null = null;
  private data: RouteGeom | null = null;

  attach(map: MLMap): void {
    this.map = map;
    if (!map.getSource(SRC)) map.addSource(SRC, { type: "geojson", data: EMPTY });
    if (!map.getSource(SRC_DEST)) map.addSource(SRC_DEST, { type: "geojson", data: EMPTY });

    map.addLayer({
      id: L_CASING,
      type: "line",
      source: SRC,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#0b0f17", "line-width": 8, "line-opacity": 0.6 },
    });
    map.addLayer({
      id: L_LINE,
      type: "line",
      source: SRC,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": ["case", ["get", "crosses"], "#f43f5e", "#22d3ee"],
        "line-width": 4,
        "line-opacity": 0.95,
      },
    });
    map.addLayer({
      id: L_DEST,
      type: "circle",
      source: SRC_DEST,
      paint: {
        "circle-radius": 7,
        "circle-color": ["case", ["get", "crosses"], "#f43f5e", "#22d3ee"],
        "circle-stroke-color": "#0b0f17",
        "circle-stroke-width": 2,
      },
    });
    addSvgImage(map, IMG_DEST, CROSSHAIR_SVG);
    map.addLayer({
      id: L_DEST_LABEL,
      type: "symbol",
      source: SRC_DEST,
      layout: {
        "icon-image": IMG_DEST,
        "icon-size": 1,
        "icon-offset": [0, -14],
        "icon-allow-overlap": true,
      },
    });

    if (this.data) this.render();
  }

  setRoute(data: RouteGeom | null): void {
    this.data = data;
    this.render();
  }

  clear(): void {
    this.setRoute(null);
  }

  private render(): void {
    const map = this.map;
    if (!map) return;
    const line = map.getSource(SRC) as GeoJSONSource | undefined;
    const dest = map.getSource(SRC_DEST) as GeoJSONSource | undefined;
    if (!line || !dest) return;
    const d = this.data;
    if (!d) {
      line.setData(EMPTY);
      dest.setData(EMPTY);
      return;
    }
    line.setData({
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: d.geometry, properties: { crosses: d.crosses } }],
    });
    dest.setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "Point", coordinates: [d.dest.lon, d.dest.lat] },
          properties: { crosses: d.crosses },
        },
      ],
    });
  }

  detach(): void {
    this.map = null;
  }
}

export const routeLayer = new RouteLayer();
