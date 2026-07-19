import type { StyleSpecification } from "maplibre-gl";

export const darkStyle: StyleSpecification = {
  version: 8,
  sources: {
    "carto-dark": {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
      ],
      tileSize: 256,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · © <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0b0f17" } },
    { id: "carto-dark", type: "raster", source: "carto-dark" },
  ],
};

export const ITALY_VIEW = {
  center: [12.5, 42.5] as [number, number],
  zoom: 5.2,
  maxBounds: [
    [3.0, 33.0],
    [23.0, 50.0],
  ] as [[number, number], [number, number]],
};
