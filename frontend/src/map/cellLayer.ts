import type { Map as MLMap, GeoJSONSource, ExpressionSpecification } from "maplibre-gl";

export interface CellData {
  cells: GeoJSON.FeatureCollection;
  cones: GeoJSON.FeatureCollection;
  vectors: GeoJSON.FeatureCollection;
}

const S = {
  cells: "cells",
  cones: "cones",
  vectors: "cell-vectors",
  points: "cell-points",
};
const L = {
  coneLine: "cone-line",
  fill: "cell-fill",
  outline: "cell-outline",
  target: "cell-target",
  vector: "cell-vector-line",
  arrow: "cell-arrow",
  label: "cell-label",
};

const SEV_COLOR: ExpressionSpecification = [
  "interpolate",
  ["linear"],
  ["get", "severity"],
  0, "#22d3ee",
  40, "#eab308",
  60, "#f97316",
  80, "#ef4444",
  100, "#b91c1c",
];

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

class CellLayer {
  private map: MLMap | null = null;
  private pending: CellData | null = null;
  private targetId: number | null = null;

  attach(map: MLMap): void {
    this.map = map;
    for (const id of [S.cells, S.cones, S.vectors, S.points]) {
      if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: EMPTY });
    }

    map.addLayer({
      id: L.coneLine,
      type: "line",
      source: S.cones,
      paint: {
        "line-color": SEV_COLOR,
        "line-width": 1.2,
        "line-opacity": ["match", ["get", "horizon"], 30, 0.5, 60, 0.28, 0.35],
        "line-dasharray": [2, 2],
      },
    });

    map.addLayer({
      id: L.fill,
      type: "fill",
      source: S.cells,
      paint: { "fill-color": SEV_COLOR, "fill-opacity": 0.22 },
    });

    map.addLayer({
      id: L.target,
      type: "line",
      source: S.cells,
      filter: ["==", ["get", "id"], -1],
      paint: { "line-color": "#ffffff", "line-width": 3.5, "line-opacity": 0.9 },
    });

    map.addLayer({
      id: L.outline,
      type: "line",
      source: S.cells,
      paint: {
        "line-color": SEV_COLOR,
        "line-width": ["interpolate", ["linear"], ["get", "severity"], 0, 1.2, 100, 2.6],
        "line-opacity": 0.95,
      },
    });

    map.addLayer({
      id: L.vector,
      type: "line",
      source: S.vectors,
      paint: { "line-color": "#e2e8f0", "line-width": 1.6, "line-opacity": 0.85 },
    });

    map.addLayer({
      id: L.arrow,
      type: "symbol",
      source: S.points,
      filter: ["get", "hasMotion"],
      layout: {
        "text-field": "▲",
        "text-size": 15,
        "text-rotate": ["get", "bearing"],
        "text-rotation-alignment": "map",
        "text-allow-overlap": true,
        "text-offset": [0, 0],
      },
      paint: { "text-color": "#f1f5f9", "text-halo-color": "#0b0f17", "text-halo-width": 1.2 },
    });

    map.addLayer({
      id: L.label,
      type: "symbol",
      source: S.points,
      layout: {
        "text-field": ["get", "label"],
        "text-size": 11,
        "text-offset": [0, -1.6],
        "text-anchor": "bottom",
        "text-allow-overlap": false,
        "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
      },
      paint: { "text-color": "#f8fafc", "text-halo-color": "#0b0f17", "text-halo-width": 1.6 },
    });

    if (this.pending) this.render(this.pending);
    this.applyTarget();
  }

  setData(data: CellData): void {
    this.pending = data;
    if (this.map) this.render(data);
  }

  setTarget(id: number | null): void {
    this.targetId = id;
    this.applyTarget();
  }

  private render(data: CellData): void {
    const map = this.map;
    if (!map) return;
    (map.getSource(S.cells) as GeoJSONSource | undefined)?.setData(data.cells ?? EMPTY);
    (map.getSource(S.cones) as GeoJSONSource | undefined)?.setData(data.cones ?? EMPTY);
    (map.getSource(S.vectors) as GeoJSONSource | undefined)?.setData(data.vectors ?? EMPTY);
    (map.getSource(S.points) as GeoJSONSource | undefined)?.setData(this.points(data.cells));
  }

  private points(cells: GeoJSON.FeatureCollection | undefined): GeoJSON.FeatureCollection {
    const features: GeoJSON.Feature[] = [];
    for (const f of cells?.features ?? []) {
      const p = f.properties ?? {};
      const centroid = p.centroid as [number, number] | undefined;
      if (!centroid) continue;
      const speed = p.speed_kmh as number | null;
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: centroid },
        properties: {
          label: p.label ?? `#${p.id}`,
          bearing: (p.bearing_deg as number) ?? 0,
          hasMotion: speed != null && speed >= 1,
          severity: p.severity ?? 0,
        },
      });
    }
    return { type: "FeatureCollection", features };
  }

  private applyTarget(): void {
    const map = this.map;
    if (!map || !map.getLayer(L.target)) return;
    map.setFilter(L.target, ["==", ["get", "id"], this.targetId ?? -1]);
  }

  detach(): void {
    this.map = null;
    this.pending = null;
  }
}

export const cellLayer = new CellLayer();
