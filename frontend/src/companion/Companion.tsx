import { useCallback, useEffect, useRef, useState } from "react";
import { Logo, IconPosition, IconWarning, IconRec } from "../ui/icons";
import { setKeepAwake } from "../lib/wakeLock";


type Status = "connecting" | "open" | "retry";

interface Fix {
  lat: number;
  lon: number;
  accuracy: number;
  speedKmh: number | null;
  heading: number | null;
  ts: number;
}

const CONNECT_TIMEOUT_MS = 8000;
const PING_INTERVAL_MS = 20000;
const PONG_TIMEOUT_MS = 10000;
const RETRY_MIN_MS = 1000;
const RETRY_MAX_MS = 10000;
const TROUBLE_AFTER = 3;

export function Companion() {
  const [status, setStatus] = useState<Status>("connecting");
  const [attempts, setAttempts] = useState(0);
  const [active, setActive] = useState(false);
  const [fix, setFix] = useState<Fix | null>(null);
  const [sent, setSent] = useState(0);
  const [lastSentAt, setLastSentAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [geoError, setGeoError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const watchRef = useRef<number | null>(null);
  const activeRef = useRef(false);
  const pendingRef = useRef<Fix | null>(null);
  const reconnectRef = useRef<() => void>(() => {});

  const secure = window.isSecureContext;
  const origin = window.location.origin;
  const host = window.location.host;

  const push = useCallback(() => {
    const ws = wsRef.current;
    const f = pendingRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !f || !activeRef.current) return;
    try {
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
    } catch {
      return;
    }
    pendingRef.current = null;
    setSent((n) => n + 1);
    setLastSentAt(Date.now());
  }, []);

  useEffect(() => {
    let generation = 0;
    let socket: WebSocket | null = null;
    let stopped = false;
    let backoff = RETRY_MIN_MS;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let connectTimer: ReturnType<typeof setTimeout> | undefined;
    let pingTimer: ReturnType<typeof setInterval> | undefined;
    let pongTimer: ReturnType<typeof setTimeout> | undefined;

    const clearLive = () => {
      clearTimeout(connectTimer);
      clearInterval(pingTimer);
      clearTimeout(pongTimer);
    };

    const detach = (sock: WebSocket) => {
      sock.onopen = null;
      sock.onmessage = null;
      sock.onerror = null;
      sock.onclose = null;
      try {
        sock.close();
      } catch {
      }
    };

    const drop = (sock: WebSocket) => {
      generation += 1;
      detach(sock);
      if (socket === sock) socket = null;
      if (wsRef.current === sock) wsRef.current = null;
      clearLive();
    };

    const scheduleRetry = () => {
      if (stopped) return;
      setStatus("retry");
      setAttempts((n) => n + 1);
      const delay = backoff;
      backoff = Math.min(delay * 2, RETRY_MAX_MS);
      retryTimer = setTimeout(dial, delay);
    };

    const dial = () => {
      if (stopped) return;
      clearTimeout(retryTimer);
      clearLive();
      const mine = ++generation;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      let sock: WebSocket;
      try {
        sock = new WebSocket(`${proto}://${host}/ws/live`);
      } catch {
        scheduleRetry();
        return;
      }
      socket = sock;
      setStatus("connecting");

      connectTimer = setTimeout(() => {
        if (mine !== generation) return;
        drop(sock);
        scheduleRetry();
      }, CONNECT_TIMEOUT_MS);

      sock.onopen = () => {
        if (mine !== generation) {
          detach(sock);
          return;
        }
        clearTimeout(connectTimer);
        backoff = RETRY_MIN_MS;
        wsRef.current = sock;
        setAttempts(0);
        setStatus("open");
        push();
        pingTimer = setInterval(() => {
          if (mine !== generation || sock.readyState !== WebSocket.OPEN) return;
          try {
            sock.send(JSON.stringify({ type: "ping" }));
          } catch {
            return;
          }
          clearTimeout(pongTimer);
          pongTimer = setTimeout(() => {
            if (mine !== generation) return;
            drop(sock);
            scheduleRetry();
          }, PONG_TIMEOUT_MS);
        }, PING_INTERVAL_MS);
      };

      sock.onmessage = (ev) => {
        if (mine !== generation) return;
        clearTimeout(pongTimer);
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

      sock.onerror = () => {
        if (mine !== generation) return;
        drop(sock);
        scheduleRetry();
      };

      sock.onclose = () => {
        if (mine !== generation) return;
        drop(sock);
        scheduleRetry();
      };
    };

    const revive = (force: boolean) => {
      if (stopped) return;
      if (!force && document.visibilityState === "hidden") return;
      if (!force && socket && socket.readyState === WebSocket.OPEN) return;
      clearTimeout(retryTimer);
      if (socket) drop(socket);
      backoff = RETRY_MIN_MS;
      setAttempts(0);
      dial();
    };

    const onWake = () => revive(false);
    reconnectRef.current = () => revive(true);

    dial();
    document.addEventListener("visibilitychange", onWake);
    window.addEventListener("online", onWake);
    window.addEventListener("focus", onWake);
    window.addEventListener("pageshow", onWake);

    return () => {
      stopped = true;
      generation += 1;
      document.removeEventListener("visibilitychange", onWake);
      window.removeEventListener("online", onWake);
      window.removeEventListener("focus", onWake);
      window.removeEventListener("pageshow", onWake);
      clearTimeout(retryTimer);
      clearLive();
      if (socket) detach(socket);
      socket = null;
      wsRef.current = null;
    };
  }, [host, push]);

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);

  const start = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setGeoError("Questo browser non espone la geolocalizzazione.");
      return;
    }
    setGeoError(null);
    setActive(true);
    activeRef.current = true;
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
        setGeoError(null);
        setFix(f);
        pendingRef.current = f;
        push();
      },
      (err) => setGeoError(geoMessage(err)),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 12000 },
    );
  }, [push]);

  const stop = useCallback(() => {
    setActive(false);
    activeRef.current = false;
    setKeepAwake(false);
    pendingRef.current = null;
    if (watchRef.current != null) {
      navigator.geolocation.clearWatch(watchRef.current);
      watchRef.current = null;
    }
  }, []);

  useEffect(() => () => stop(), [stop]);

  const down = status !== "open";

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
        <span className={`h-3 w-3 shrink-0 rounded-full ${STATUS_DOT[status]}`} />
        <span className="text-sm text-slate-300">link · {STATUS_LABEL[status]}</span>
        {down ? (
          <button
            onClick={() => reconnectRef.current()}
            className="ml-auto rounded-md border border-white/20 px-2.5 py-1 text-xs text-slate-200 transition hover:bg-white/10"
          >
            riconnetti
          </button>
        ) : (
          active && <span className="ml-auto text-sm text-emerald-300">{sent} invii</span>
        )}
      </div>

      {down && attempts >= TROUBLE_AFTER && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-950/40 p-3 text-sm leading-relaxed text-amber-100">
          <IconWarning className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
          <span>
            Nessuna risposta da <span className="break-all font-mono">{host}</span>. Verifica che
            NAVIER sia avviato sul laptop e che il telefono sia sulla stessa rete Wi-Fi.
          </span>
        </div>
      )}

      {!secure && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-950/40 p-4 text-sm leading-relaxed text-amber-100">
          <p className="font-semibold">Il browser blocca il GPS su questo indirizzo.</p>
          <p className="mt-1">
            La geolocalizzazione è esposta solo in contesto sicuro. Su Chrome per Android
            si autorizza una volta sola: apri{" "}
            <code className="rounded bg-black/30 px-1 break-all">
              chrome://flags/#unsafely-treat-insecure-origin-as-secure
            </code>
            , incolla qui sotto l'indirizzo nella casella, scegli <em>Enabled</em> e
            riavvia Chrome.
          </p>
          <p className="mt-2 select-all break-all rounded bg-black/30 px-2 py-1 font-mono text-amber-50">
            {origin}
          </p>
          <p className="mt-2 text-amber-200/80">
            In alternativa si serve la pagina in HTTPS con un certificato mkcert, vedi il
            README.
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
            {active && (
              <>
                <span className="text-slate-400">ultimo invio</span>
                <span className={`text-right ${down ? "text-rose-300" : ""}`}>
                  {lastSentAt != null ? `${elapsed(now, lastSentAt)} fa` : "-"}
                </span>
              </>
            )}
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
  connecting: "bg-amber-400 animate-pulse",
  open: "bg-emerald-400",
  retry: "bg-rose-500",
};
const STATUS_LABEL: Record<Status, string> = {
  connecting: "connessione…",
  open: "connesso",
  retry: "riconnetto…",
};

function elapsed(now: number, then: number): string {
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return `${m} min`;
}

function geoMessage(err: GeolocationPositionError): string {
  if (err.code === err.PERMISSION_DENIED)
    return "Permesso negato. Consenti la posizione per questo sito nelle impostazioni del browser.";
  if (err.code === err.POSITION_UNAVAILABLE) return "Posizione non disponibile (nessun fix GPS).";
  if (err.code === err.TIMEOUT) return "Timeout nel fix GPS, riprovo…";
  return err.message || "Errore di geolocalizzazione.";
}
