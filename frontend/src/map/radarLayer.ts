import type { Map as MLMap, ImageSource } from "maplibre-gl";

export interface RadarFrame {
  ts: number;
  url?: string;
  bounds?: [number, number, number, number];
  tile_url?: string;
  max_dbz?: number;
}

export interface RadarData {
  source: string | null;
  kind: "image" | "tiles" | null;
  attribution: string;
  frames: RadarFrame[];
}

const IMG_SOURCE = "radar-image";
const IMG_LAYER = "radar-image-layer";
const TILE_PREFIX = "radar-tiles-";
const BEFORE_ID = "lightning-glow";

class RadarLayer {
  private map: MLMap | null = null;
  private kind: "image" | "tiles" | null = null;
  private frames: RadarFrame[] = [];
  private tileLayerIds: string[] = [];
  private opacity = 0.8;
  private visible = true;
  private shownIndex = -1;
  private pending: RadarData | null = null;

  attach(map: MLMap): void {
    this.map = map;
    if (this.pending) this.render(this.pending);
  }

  setData(data: RadarData): void {
    this.pending = data;
    if (this.map) this.render(data);
  }

  private render(data: RadarData): void {
    if (!this.map) return;
    if (data.kind !== this.kind || data.source == null) {
      this.clear();
      this.kind = data.kind;
    }
    this.frames = data.frames;

    if (data.kind === "image") this.syncImage();
    else if (data.kind === "tiles") this.syncTiles();

    if (data.kind === "image") {
      for (const f of data.frames) {
        if (f.url) {
          const img = new Image();
          img.src = f.url;
        }
      }
    }
  }

  private syncImage(): void {
    const map = this.map;
    if (!map || !this.frames.length) return;
    const last = this.frames[this.frames.length - 1];
    if (!last.url || !last.bounds) return;
    if (!map.getSource(IMG_SOURCE)) {
      map.addSource(IMG_SOURCE, {
        type: "image",
        url: last.url,
        coordinates: this.corners(last.bounds),
      });
      map.addLayer(
        {
          id: IMG_LAYER,
          type: "raster",
          source: IMG_SOURCE,
          paint: {
            "raster-opacity": this.visible ? this.opacity : 0,
            "raster-fade-duration": 0,
            "raster-resampling": "linear",
          },
        },
        map.getLayer(BEFORE_ID) ? BEFORE_ID : undefined,
      );
      this.shownIndex = this.frames.length - 1;
    }
  }

  private syncTiles(): void {
    const map = this.map;
    if (!map) return;
    const wanted = new Set(this.frames.map((f) => TILE_PREFIX + f.ts));
    for (const id of this.tileLayerIds) {
      if (!wanted.has(id)) this.removeTileLayer(id);
    }
    this.tileLayerIds = this.tileLayerIds.filter((id) => wanted.has(id));
    for (const f of this.frames) {
      const id = TILE_PREFIX + f.ts;
      if (!f.tile_url || map.getSource(id)) continue;
      map.addSource(id, { type: "raster", tiles: [f.tile_url], tileSize: 256 });
      map.addLayer(
        {
          id,
          type: "raster",
          source: id,
          paint: { "raster-opacity": 0, "raster-fade-duration": 0 },
        },
        map.getLayer(BEFORE_ID) ? BEFORE_ID : undefined,
      );
      this.tileLayerIds.push(id);
    }
  }

  showIndex(i: number): void {
    const map = this.map;
    if (!map || i < 0 || i >= this.frames.length) return;

    if (this.kind === "image") {
      const f = this.frames[i];
      const src = map.getSource(IMG_SOURCE) as ImageSource | undefined;
      if (src && f.url && f.bounds) {
        src.updateImage({ url: f.url, coordinates: this.corners(f.bounds) });
      }
    } else if (this.kind === "tiles") {
      const prev = this.frames[this.shownIndex];
      if (prev && map.getLayer(TILE_PREFIX + prev.ts)) {
        map.setPaintProperty(TILE_PREFIX + prev.ts, "raster-opacity", 0);
      }
      const f = this.frames[i];
      if (map.getLayer(TILE_PREFIX + f.ts)) {
        map.setPaintProperty(
          TILE_PREFIX + f.ts,
          "raster-opacity",
          this.visible ? this.opacity : 0,
        );
      }
    }
    this.shownIndex = i;
  }

  setOpacity(o: number): void {
    this.opacity = o;
    this.applyVisibility();
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.applyVisibility();
  }

  private applyVisibility(): void {
    const map = this.map;
    if (!map) return;
    const op = this.visible ? this.opacity : 0;
    if (this.kind === "image" && map.getLayer(IMG_LAYER)) {
      map.setPaintProperty(IMG_LAYER, "raster-opacity", op);
    } else if (this.kind === "tiles") {
      const cur = this.frames[this.shownIndex];
      if (cur && map.getLayer(TILE_PREFIX + cur.ts)) {
        map.setPaintProperty(TILE_PREFIX + cur.ts, "raster-opacity", op);
      }
    }
  }

  private corners(
    b: [number, number, number, number],
  ): [[number, number], [number, number], [number, number], [number, number]] {
    const [w, s, e, n] = b;
    return [
      [w, n],
      [e, n],
      [e, s],
      [w, s],
    ];
  }

  private removeTileLayer(id: string): void {
    const map = this.map;
    if (!map) return;
    if (map.getLayer(id)) map.removeLayer(id);
    if (map.getSource(id)) map.removeSource(id);
  }

  private clear(): void {
    const map = this.map;
    if (!map) return;
    if (map.getLayer(IMG_LAYER)) map.removeLayer(IMG_LAYER);
    if (map.getSource(IMG_SOURCE)) map.removeSource(IMG_SOURCE);
    for (const id of this.tileLayerIds) this.removeTileLayer(id);
    this.tileLayerIds = [];
    this.shownIndex = -1;
  }

  detach(): void {
    this.clear();
    this.map = null;
    this.frames = [];
    this.kind = null;
  }
}

export const radarLayer = new RadarLayer();
