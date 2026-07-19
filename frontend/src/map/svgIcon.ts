import type { Map as MLMap } from "maplibre-gl";

export function addSvgImage(map: MLMap, id: string, svg: string, size = 20): void {
  if (map.hasImage(id)) return;
  const img = new Image(size * 2, size * 2);
  img.onload = () => {
    if (!map.hasImage(id)) map.addImage(id, img, { pixelRatio: 2 });
  };
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export const CROSSHAIR_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="#0b0f17" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="8"/><line x1="22" y1="12" x2="18" y2="12"/>
  <line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/>
  <line x1="12" y1="22" x2="12" y2="18"/>
  <g stroke="#ffffff" stroke-width="2">
    <circle cx="12" cy="12" r="8"/><line x1="22" y1="12" x2="18" y2="12"/>
    <line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/>
    <line x1="12" y1="22" x2="12" y2="18"/>
  </g>
</svg>`;
