import type { Map as MLMap, GeoJSONSource } from "maplibre-gl";

export interface Strike {
  t: number;
  lat: number;
  lon: number;
}

const SOURCE_ID = "lightning";
const LAYER_GLOW = "lightning-glow";
const LAYER_CORE = "lightning-core";
const WINDOW_MS = 15 * 60 * 1000;
const MAX_STRIKES = 8000;
const TICK_MS = 500;

class LightningLayer {
  private map: MLMap | null = null;
  private strikes: Strike[] = [];
  private timer: ReturnType<typeof setInterval> | null = null;

  attach(map: MLMap): void {
    this.map = map;

    map.addSource(SOURCE_ID, {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });

    map.addLayer({
      id: LAYER_GLOW,
      type: "circle",
      source: SOURCE_ID,
      paint: {
        "circle-blur": 1,
        "circle-radius": ["interpolate", ["linear"], ["get", "a"], 0, 11, 3, 7, 15, 4],
        "circle-color": "#8ab4ff",
        "circle-opacity": ["interpolate", ["linear"], ["get", "a"], 0, 0.55, 5, 0.15, 15, 0],
      },
    });

    map.addLayer({
      id: LAYER_CORE,
      type: "circle",
      source: SOURCE_ID,
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["get", "a"], 0, 4.5, 3, 3, 15, 2],
        "circle-color": [
          "interpolate",
          ["linear"],
          ["get", "a"],
          0, "#ffffff",
          0.4, "#d6f0ff",
          2, "#ffd24d",
          5, "#ff7a1a",
          10, "#c026ff",
          15, "#5b1290",
        ],
        "circle-opacity": ["interpolate", ["linear"], ["get", "a"], 0, 1, 12, 0.6, 15, 0],
      },
    });

    this.timer = setInterval(() => this.tick(), TICK_MS);
    this.tick();
  }

  addStrikes(list: Strike[]): void {
    if (!list?.length) return;
    this.strikes.push(...list);
    if (this.strikes.length > MAX_STRIKES) {
      this.strikes = this.strikes.slice(-MAX_STRIKES);
    }
  }

  count(): number {
    return this.strikes.length;
  }

  private tick(): void {
    if (!this.map) return;
    const now = Date.now();
    const cutoff = now - WINDOW_MS;

    const kept: Strike[] = [];
    const features: GeoJSON.Feature[] = [];
    for (const s of this.strikes) {
      if (s.t < cutoff) continue;
      kept.push(s);
      features.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [s.lon, s.lat] },
        properties: { a: (now - s.t) / 60000 },
      });
    }
    this.strikes = kept;

    const src = this.map.getSource(SOURCE_ID) as GeoJSONSource | undefined;
    src?.setData({ type: "FeatureCollection", features });
  }

  detach(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.map = null;
    this.strikes = [];
  }
}

export const lightningLayer = new LightningLayer();
