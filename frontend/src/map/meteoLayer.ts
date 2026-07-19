import type { Map as MLMap, GeoJSONSource, ExpressionSpecification } from "maplibre-gl";

export type MeteoField = "cape" | "shear";

const SOURCE = "meteo-grid";
const LAYER = "meteo-heatmap";
const BEFORE_ID = "radar-image-layer";
const BEFORE_ID_ALT = "lightning-glow";

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

const WEIGHT: Record<MeteoField, ExpressionSpecification> = {
  cape: [
    "interpolate", ["linear"], ["get", "cape"],
    0, 0, 500, 0.15, 1500, 0.5, 2500, 0.8, 3500, 1,
  ],
  shear: [
    "interpolate", ["linear"], ["get", "shear"],
    0, 0, 10, 0.3, 20, 0.65, 30, 1,
  ],
};

const COLOR: ExpressionSpecification = [
  "interpolate", ["linear"], ["heatmap-density"],
  0, "rgba(0,0,0,0)",
  0.1, "#1e3a8a",
  0.3, "#0ea5e9",
  0.5, "#22c55e",
  0.7, "#eab308",
  0.85, "#f97316",
  1, "#ef4444",
];

const RADIUS: ExpressionSpecification = [
  "interpolate", ["linear"], ["zoom"], 4, 34, 6, 60, 8, 95,
];

class MeteoLayer {
  private map: MLMap | null = null;
  private field: MeteoField = "cape";
  private visible = false;
  private pending: GeoJSON.FeatureCollection | null = null;

  attach(map: MLMap): void {
    this.map = map;
    if (!map.getSource(SOURCE)) map.addSource(SOURCE, { type: "geojson", data: EMPTY });
    const before = map.getLayer(BEFORE_ID)
      ? BEFORE_ID
      : map.getLayer(BEFORE_ID_ALT)
        ? BEFORE_ID_ALT
        : undefined;
    map.addLayer(
      {
        id: LAYER,
        type: "heatmap",
        source: SOURCE,
        layout: { visibility: this.visible ? "visible" : "none" },
        paint: {
          "heatmap-weight": WEIGHT[this.field],
          "heatmap-intensity": 1,
          "heatmap-radius": RADIUS,
          "heatmap-color": COLOR,
          "heatmap-opacity": 0.55,
        },
      },
      before,
    );
    if (this.pending) this.setData(this.pending);
  }

  setData(fc: GeoJSON.FeatureCollection): void {
    this.pending = fc;
    (this.map?.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(fc ?? EMPTY);
  }

  setField(field: MeteoField): void {
    this.field = field;
    if (this.map?.getLayer(LAYER)) {
      this.map.setPaintProperty(LAYER, "heatmap-weight", WEIGHT[field]);
    }
  }

  setVisible(v: boolean): void {
    this.visible = v;
    if (this.map?.getLayer(LAYER)) {
      this.map.setLayoutProperty(LAYER, "visibility", v ? "visible" : "none");
    }
  }

  detach(): void {
    const map = this.map;
    if (map) {
      if (map.getLayer(LAYER)) map.removeLayer(LAYER);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    }
    this.map = null;
    this.pending = null;
  }
}

export const meteoLayer = new MeteoLayer();
