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
  private shownTs: number | null = null;
  private shownUrl: string | null = null;
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
    const prevTs = this.shownTs;
    const wasAtLast = this.frames.length > 0 && this.shownIndex === this.frames.length - 1;
    this.frames = data.frames;
    const target = this.pickIndex(prevTs, wasAtLast);

    if (data.kind === "image") this.syncImage(target);
    else if (data.kind === "tiles") this.syncTiles();

    if (data.kind === "image") {
      for (const f of data.frames) {
        if (f.url) {
          const img = new Image();
          img.src = f.url;
        }
      }
    }

    if (target >= 0) this.showIndex(target);
  }

  private pickIndex(prevTs: number | null, wasAtLast: boolean): number {
    if (!this.frames.length) return -1;
    if (!wasAtLast && prevTs != null) {
      const found = this.frames.findIndex((f) => f.ts === prevTs);
      if (found >= 0) return found;
    }
    return this.frames.length - 1;
  }

  private syncImage(index: number): void {
    const map = this.map;
    if (!map || index < 0) return;
    const frame = this.frames[index];
    if (!frame.url || !frame.bounds) return;
    if (!map.getSource(IMG_SOURCE)) {
      map.addSource(IMG_SOURCE, {
        type: "image",
        url: frame.url,
        coordinates: this.corners(frame.bounds),
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
      this.shownIndex = index;
      this.shownTs = frame.ts;
      this.shownUrl = frame.url;
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

    const f = this.frames[i];
    if (this.kind === "image") {
      const src = map.getSource(IMG_SOURCE) as ImageSource | undefined;
      if (src && f.url && f.bounds && f.url !== this.shownUrl) {
        src.updateImage({ url: f.url, coordinates: this.corners(f.bounds) });
        this.shownUrl = f.url;
      }
    } else if (this.kind === "tiles") {
      const activeId = TILE_PREFIX + f.ts;
      const prevId = this.shownTs != null ? TILE_PREFIX + this.shownTs : null;
      if (prevId && prevId !== activeId && map.getLayer(prevId)) {
        map.setPaintProperty(prevId, "raster-opacity", 0);
      }
      if (map.getLayer(activeId)) {
        map.setPaintProperty(activeId, "raster-opacity", this.visible ? this.opacity : 0);
      }
    }
    this.shownIndex = i;
    this.shownTs = f.ts;
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
    } else if (this.kind === "tiles" && this.shownTs != null) {
      const id = TILE_PREFIX + this.shownTs;
      if (map.getLayer(id)) map.setPaintProperty(id, "raster-opacity", op);
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
    this.shownTs = null;
    this.shownUrl = null;
  }

  detach(): void {
    this.clear();
    this.map = null;
    this.frames = [];
    this.kind = null;
  }
}

export const radarLayer = new RadarLayer();
