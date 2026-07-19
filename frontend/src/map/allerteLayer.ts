import type { Map as MLMap, GeoJSONSource, ExpressionSpecification } from "maplibre-gl";

const SOURCE = "allerte-zones";
const FILL = "allerte-fill";
const LINE = "allerte-outline";
const BEFORE_ID = "radar-image-layer";
const BEFORE_ID_ALT = "lightning-glow";

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

const LEVEL_COLOR: ExpressionSpecification = [
  "match", ["get", "level"],
  "giallo", "#eab308",
  "arancione", "#f97316",
  "rosso", "#ef4444",
  "#64748b",
];

class AllerteLayer {
  private map: MLMap | null = null;
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
    const vis = this.visible ? "visible" : "none";
    map.addLayer(
      {
        id: FILL,
        type: "fill",
        source: SOURCE,
        layout: { visibility: vis },
        paint: { "fill-color": LEVEL_COLOR, "fill-opacity": 0.3 },
      },
      before,
    );
    map.addLayer(
      {
        id: LINE,
        type: "line",
        source: SOURCE,
        layout: { visibility: vis },
        paint: { "line-color": LEVEL_COLOR, "line-width": 1.2, "line-opacity": 0.8 },
      },
      before,
    );
    if (this.pending) this.setData(this.pending);
  }

  setData(fc: GeoJSON.FeatureCollection): void {
    this.pending = fc;
    (this.map?.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(fc ?? EMPTY);
  }

  setVisible(v: boolean): void {
    this.visible = v;
    const vis = v ? "visible" : "none";
    for (const id of [FILL, LINE]) {
      if (this.map?.getLayer(id)) this.map.setLayoutProperty(id, "visibility", vis);
    }
  }

  detach(): void {
    const map = this.map;
    if (map) {
      for (const id of [FILL, LINE]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    }
    this.map = null;
    this.pending = null;
  }
}

export const allerteLayer = new AllerteLayer();
