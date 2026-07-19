import maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import { Protocol, PMTiles } from "pmtiles";
import { darkStyle, ITALY_VIEW } from "./style";

const protocol = new Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

export async function buildBasemapStyle(): Promise<StyleSpecification> {
  try {
    const r = await fetch("/api/basemap");
    const j = await r.json();
    if (!j.available || !j.url) return darkStyle;
    const url = new URL(j.url as string, location.origin).toString();
    const archive = new PMTiles(url);
    protocol.add(archive);
    const header = await archive.getHeader();
    return header.tileType === 1 ? vectorDarkStyle(url) : rasterStyle(url);
  } catch {
    return darkStyle;
  }
}

const OSM_ATTRIB =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · basemap offline PMTiles';

function rasterStyle(url: string): StyleSpecification {
  return {
    version: 8,
    sources: {
      basemap: { type: "raster", url: `pmtiles://${url}`, tileSize: 256, attribution: OSM_ATTRIB },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0b0f17" } },
      { id: "basemap", type: "raster", source: "basemap" },
    ],
  };
}

function vectorDarkStyle(url: string): StyleSpecification {
  return {
    version: 8,
    sources: {
      pm: { type: "vector", url: `pmtiles://${url}`, attribution: OSM_ATTRIB },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#0b0f17" } },
      {
        id: "earth",
        type: "fill",
        source: "pm",
        "source-layer": "earth",
        paint: { "fill-color": "#12161f" },
      },
      {
        id: "landuse",
        type: "fill",
        source: "pm",
        "source-layer": "landuse",
        paint: { "fill-color": "#151a24", "fill-opacity": 0.6 },
      },
      {
        id: "water",
        type: "fill",
        source: "pm",
        "source-layer": "water",
        paint: { "fill-color": "#0c1830" },
      },
      {
        id: "buildings",
        type: "fill",
        source: "pm",
        "source-layer": "buildings",
        minzoom: 13,
        paint: { "fill-color": "#1a1f2a" },
      },
      {
        id: "roads",
        type: "line",
        source: "pm",
        "source-layer": "roads",
        paint: {
          "line-color": "#2b313d",
          "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.3, 10, 1.0, 14, 2.5],
        },
      },
      {
        id: "boundaries",
        type: "line",
        source: "pm",
        "source-layer": "boundaries",
        paint: { "line-color": "#3a3242", "line-width": 0.7, "line-dasharray": [3, 2] },
      },
    ],
  };
}

export { ITALY_VIEW };
