import { useEffect, useRef, useState } from "react";
import { IconWarning } from "../ui/icons";
import maplibregl from "maplibre-gl";
import { ITALY_VIEW } from "./style";
import { buildBasemapStyle } from "./basemap";
import { lightningLayer } from "./lightningLayer";
import { radarLayer } from "./radarLayer";
import { cellLayer } from "./cellLayer";
import { routeLayer } from "./routeLayer";
import { userLayer } from "./userLayer";
import { meteoLayer } from "./meteoLayer";
import { allerteLayer } from "./allerteLayer";
import { useStore } from "../state/store";
import { liveSocket } from "../lib/ws";

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return !!(
      canvas.getContext("webgl2") ||
      canvas.getContext("webgl") ||
      canvas.getContext("experimental-webgl")
    );
  } catch {
    return false;
  }
}

export function MapView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    if (!hasWebGL()) {
      setError("no-webgl");
      return;
    }

    let cancelled = false;
    void (async () => {
      const style = await buildBasemapStyle();
      const container = containerRef.current;
      if (cancelled || !container || mapRef.current) return;

      let map: maplibregl.Map;
      try {
        map = new maplibregl.Map({
          container,
          style,
          center: ITALY_VIEW.center,
          zoom: ITALY_VIEW.zoom,
          maxBounds: ITALY_VIEW.maxBounds,
          attributionControl: false,
        });
      } catch (e) {
        console.error("[map] init failed", e);
        setError("init-failed");
        return;
      }
      mapRef.current = map;

      map.on("error", (e) => console.warn("[map] error", e?.error ?? e));

      map.on("load", () => {
        radarLayer.attach(map);
        allerteLayer.attach(map);
        meteoLayer.attach(map);
        lightningLayer.attach(map);
        cellLayer.attach(map);
        routeLayer.attach(map);
        userLayer.attach(map);
      });

      map.on("click", (e) => {
        if (!useStore.getState().placingPosition) return;
        liveSocket.send("position_update", {
          lat: e.lngLat.lat,
          lon: e.lngLat.lng,
          source: "manual",
        });
        useStore.getState().setPlacingPosition(false);
      });

      map.addControl(
        new maplibregl.AttributionControl({
          compact: true,
          customAttribution:
            "Dati radar: Radar-DPC, Dipartimento della Protezione Civile · Fulmini: Blitzortung.org",
        }),
        "bottom-left",
      );
      map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "top-right");
    })();

    return () => {
      cancelled = true;
      const map = mapRef.current;
      if (!map) return;
      lightningLayer.detach();
      radarLayer.detach();
      meteoLayer.detach();
      allerteLayer.detach();
      cellLayer.detach();
      routeLayer.detach();
      userLayer.detach();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  const targetCellId = useStore((s) => s.targetCellId);
  const placing = useStore((s) => s.placingPosition);
  useEffect(() => cellLayer.setTarget(targetCellId), [targetCellId]);
  useEffect(() => {
    const map = mapRef.current;
    if (map) map.getCanvas().style.cursor = placing ? "crosshair" : "";
  }, [placing]);

  const user = useStore((s) => s.user);
  const chase = useStore((s) => s.chaseMode);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !chase || !user) return;
    map.easeTo({
      center: [user.lon, user.lat],
      zoom: Math.max(map.getZoom(), 10),
      duration: 700,
    });
  }, [user, chase]);

  if (error) {
    return (
      <div className="absolute inset-0 flex items-center justify-center p-8 text-center">
        <div className="max-w-md rounded-xl border border-amber-500/30 bg-slate-900/90 p-6 shadow-xl">
          <IconWarning className="mx-auto mb-2 h-9 w-9 text-amber-400" strokeWidth={1.5} />
          <h2 className="mb-2 text-lg font-semibold text-amber-300">
            Mappa non disponibile: WebGL assente
          </h2>
          <p className="text-sm leading-relaxed text-slate-300">
            MapLibre ha bisogno di WebGL, che questo browser non espone (tipico
            della <em>Simple Browser</em> integrata in VS Code).
          </p>
          <p className="mt-3 text-sm leading-relaxed text-slate-300">
            Apri <code className="rounded bg-slate-800 px-1.5 py-0.5 text-sky-300">http://localhost:5700/</code>{" "}
            in un browser vero - <strong>Chrome, Edge o Firefox</strong> - e la
            mappa comparirà. Il resto dell'app (backend, WebSocket) sta già
            funzionando.
          </p>
        </div>
      </div>
    );
  }

  return <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />;
}
