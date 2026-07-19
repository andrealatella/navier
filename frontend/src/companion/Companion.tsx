import { useCallback, useEffect, useRef, useState } from "react";
import { Logo, IconPosition, IconWarning, IconRec } from "../ui/icons";
import { setKeepAwake } from "../lib/wakeLock";


type Status = "idle" | "connecting" | "open" | "closed";

interface Fix {
  lat: number;
  lon: number;
  accuracy: number;
  speedKmh: number | null;
  heading: number | null;
  ts: number;
}

export function Companion() {
  const [status, setStatus] = useState<Status>("idle");
  const [active, setActive] = useState(false);
  const [fix, setFix] = useState<Fix | null>(null);
  const [sent, setSent] = useState(0);
  const [geoError, setGeoError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const watchRef = useRef<number | null>(null);
  const backoffRef = useRef(1000);
  const closedRef = useRef(false);

  const secure = window.isSecureContext;

  const connect = useCallback(() => {
    closedRef.current = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => {
      backoffRef.current = 1000;
      setStatus("open");
    };
    ws.onmessage = (ev) => {
      let msg: { type?: string; payload?: Record<string, unknown> };
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === "open_maps" && msg.payload) {
        const url = msg.payload.url;
        if (typeof url === "string") window.location.href = url;
      }
    };
    ws.onclose = () => {
      setStatus("closed");
      if (!closedRef.current) {
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, 15000);
        setTimeout(() => {
          if (!closedRef.current) connect();
        }, delay);
      }
    };
    ws.onerror = () => ws.close();
  }, []);

  useEffect(() => {
    connect();
    return () => {
      closedRef.current = true;
      wsRef.current?.close();
    };
  }, [connect]);

  const start = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setGeoError("Questo browser non espone la geolocalizzazione.");
      return;
    }
    setGeoError(null);
    setActive(true);
    setKeepAwake(true);
    watchRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        const c = pos.coords;
        const f: Fix = {
          lat: c.latitude,
          lon: c.longitude,
          accuracy: c.accuracy,
          speedKmh: c.speed != null ? Math.round(c.speed * 3.6 * 10) / 10 : null,
          heading: c.heading != null && !Number.isNaN(c.heading) ? Math.round(c.heading) : null,
          ts: pos.timestamp,
        };
        setFix(f);
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: "position_update",
              payload: {
                lat: f.lat,
                lon: f.lon,
                speed_kmh: f.speedKmh,
                heading_deg: f.heading,
                source: "phone",
              },
            }),
          );
          setSent((n) => n + 1);
        }
      },
      (err) => setGeoError(geoMessage(err)),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 12000 },
    );
  }, []);

  const stop = useCallback(() => {
    setActive(false);
    setKeepAwake(false);
    if (watchRef.current != null) {
      navigator.geolocation.clearWatch(watchRef.current);
      watchRef.current = null;
    }
  }, []);

  useEffect(() => () => stop(), [stop]);

  return (
    <div className="mx-auto flex min-h-full max-w-md flex-col gap-5 p-6">
      <header className="flex items-center gap-3">
        <Logo className="h-9 w-9" />
        <div>
          <h1 className="text-xl font-bold tracking-wide">NAVIER companion</h1>
          <p className="text-sm text-slate-400">GPS del telefono → mappa del laptop</p>
        </div>
      </header>

      <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-slate-900/70 px-4 py-3">
        <span className={`h-3 w-3 rounded-full ${STATUS_DOT[status]}`} />
        <span className="text-sm text-slate-300">link · {STATUS_LABEL[status]}</span>
        {active && <span className="ml-auto text-sm text-emerald-300">{sent} invii</span>}
      </div>

      {!secure && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-950/40 p-4 text-sm leading-relaxed text-amber-100">
          <p className="font-semibold">Serve una connessione sicura (HTTPS).</p>
          <p className="mt-1">
            Il browser attiva il GPS solo in contesto sicuro. Apri questa pagina come{" "}
            <code className="rounded bg-black/30 px-1">https://&lt;ip-laptop&gt;:5173/companion</code>{" "}
            con il certificato mkcert (vedi il README).
          </p>
        </div>
      )}

      {!active ? (
        <button
          onClick={start}
          disabled={!secure}
          className="flex items-center justify-center gap-2 rounded-2xl bg-sky-600 py-5 text-xl font-bold text-white shadow-lg transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <IconPosition className="h-6 w-6" strokeWidth={2} />
          Attiva GPS
        </button>
      ) : (
        <button
          onClick={stop}
          className="flex items-center justify-center gap-2 rounded-2xl border border-white/20 bg-slate-800 py-5 text-xl font-bold text-slate-100 shadow-lg transition hover:bg-slate-700"
        >
          <IconRec className="h-5 w-5" fill="currentColor" strokeWidth={0} />
          Ferma invio
        </button>
      )}

      {geoError && (
        <div className="flex items-start gap-2 rounded-lg border border-rose-500/40 bg-rose-950/50 p-3 text-sm text-rose-100">
          <IconWarning className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
          <span>{geoError}</span>
        </div>
      )}

      {fix && (
        <div className="rounded-lg border border-white/10 bg-slate-900/70 p-4 text-sm">
          <div className="grid grid-cols-2 gap-y-1 tabular-nums">
            <span className="text-slate-400">lat</span>
            <span className="text-right">{fix.lat.toFixed(5)}</span>
            <span className="text-slate-400">lon</span>
            <span className="text-right">{fix.lon.toFixed(5)}</span>
            <span className="text-slate-400">precisione</span>
            <span className="text-right">± {fix.accuracy.toFixed(0)} m</span>
            <span className="text-slate-400">velocità</span>
            <span className="text-right">{fix.speedKmh != null ? `${fix.speedKmh} km/h` : "-"}</span>
            <span className="text-slate-400">direzione</span>
            <span className="text-right">{fix.heading != null ? `${fix.heading}°` : "-"}</span>
          </div>
        </div>
      )}

      <p className="mt-auto text-center text-xs leading-relaxed text-slate-500">
        Tieni questa scheda aperta durante la caccia. Chi guida non tocca il telefono:
        lo gestisce l'operatore. Fulmini: Blitzortung.org · Radar: Radar-DPC.
      </p>
    </div>
  );
}

const STATUS_DOT: Record<Status, string> = {
  idle: "bg-slate-500",
  connecting: "bg-amber-400 animate-pulse",
  open: "bg-emerald-400",
  closed: "bg-rose-500",
};
const STATUS_LABEL: Record<Status, string> = {
  idle: "in attesa",
  connecting: "connessione…",
  open: "connesso",
  closed: "disconnesso",
};

function geoMessage(err: GeolocationPositionError): string {
  if (err.code === err.PERMISSION_DENIED)
    return "Permesso negato. Consenti la posizione per questo sito nelle impostazioni del browser.";
  if (err.code === err.POSITION_UNAVAILABLE) return "Posizione non disponibile (nessun fix GPS).";
  if (err.code === err.TIMEOUT) return "Timeout nel fix GPS, riprovo…";
  return err.message || "Errore di geolocalizzazione.";
}
