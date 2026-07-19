import { useEffect, useRef } from "react";
import { useStore } from "../state/store";
import { IconRadar, IconPlay, IconPause, IconVisible, IconHidden } from "../ui/icons";
import { radarLayer } from "../map/radarLayer";

const STEP_MS = 400;
const HOLD_LAST_MS = 1100;

function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

const SOURCE_LABEL: Record<string, string> = {
  dpc: "Radar DPC",
  rainviewer: "RainViewer",
};

export function RadarPanel() {
  const radar = useStore((s) => s.radar);
  const index = useStore((s) => s.radarIndex);
  const playing = useStore((s) => s.radarPlaying);
  const opacity = useStore((s) => s.radarOpacity);
  const visible = useStore((s) => s.radarVisible);
  const setRadarIndex = useStore((s) => s.setRadarIndex);
  const setRadarPlaying = useStore((s) => s.setRadarPlaying);
  const setRadarOpacity = useStore((s) => s.setRadarOpacity);
  const setRadarVisible = useStore((s) => s.setRadarVisible);

  const n = radar.frameTimes.length;

  useEffect(() => {
    if (n > 0) radarLayer.showIndex(index);
  }, [index, n]);

  useEffect(() => radarLayer.setOpacity(opacity), [opacity]);
  useEffect(() => radarLayer.setVisible(visible), [visible]);

  const idxRef = useRef(index);
  idxRef.current = index;
  useEffect(() => {
    if (!playing || n <= 1) return;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const cur = idxRef.current;
      const next = (cur + 1) % n;
      setRadarIndex(next);
      const delay = next === n - 1 ? HOLD_LAST_MS : STEP_MS;
      timer = setTimeout(tick, delay);
    };
    timer = setTimeout(tick, STEP_MS);
    return () => clearTimeout(timer);
  }, [playing, n, setRadarIndex]);

  if (radar.source == null || n === 0) {
    return (
      <div className="pointer-events-none">
        <div className="pointer-events-auto flex items-center gap-2 rounded-lg border border-white/10 bg-slate-900/80 px-4 py-2 text-sm text-slate-400 shadow-lg backdrop-blur">
          <IconRadar className="h-4 w-4 shrink-0" strokeWidth={1.75} />
          in attesa del radar…
        </div>
      </div>
    );
  }

  const curTs = radar.frameTimes[Math.min(index, n - 1)];
  const label = SOURCE_LABEL[radar.source] ?? radar.source;
  const isFallback = radar.source === "rainviewer";

  return (
    <div className="pointer-events-none w-full max-w-[540px]">
      <div className="pointer-events-auto rounded-xl border border-white/10 bg-slate-900/85 px-4 py-3 shadow-xl backdrop-blur">
        <div className="mb-2 flex items-center gap-2 text-sm">
          <button
            onClick={() => setRadarPlaying(!playing)}
            className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-700/80 text-slate-100 transition hover:bg-slate-600"
            title={playing ? "Pausa" : "Play"}
          >
            {playing ? (
              <IconPause className="h-3.5 w-3.5" fill="currentColor" strokeWidth={0} />
            ) : (
              <IconPlay className="h-3.5 w-3.5" fill="currentColor" strokeWidth={0} />
            )}
          </button>

          <span className="font-semibold text-slate-100">{label}</span>
          {isFallback && (
            <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-xs text-amber-300">
              fallback
            </span>
          )}

          <span className="ml-auto tabular-nums text-slate-300">
            {curTs != null ? fmtTime(curTs) : "-"}
          </span>
          <span className="text-xs text-slate-500">
            {index + 1}/{n}
          </span>

          <button
            onClick={() => setRadarVisible(!visible)}
            className="ml-1 flex h-7 w-7 items-center justify-center rounded-md bg-slate-700/60 text-slate-200 transition hover:bg-slate-600"
            title={visible ? "Nascondi radar" : "Mostra radar"}
          >
            {visible ? (
              <IconVisible className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <IconHidden className="h-4 w-4" strokeWidth={1.75} />
            )}
          </button>
        </div>

        <input
          type="range"
          min={0}
          max={n - 1}
          value={Math.min(index, n - 1)}
          onChange={(e) => {
            setRadarPlaying(false);
            setRadarIndex(Number(e.target.value));
          }}
          className="w-full accent-sky-400"
          aria-label="Tempo radar"
        />

        <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
          <span>opacità</span>
          <input
            type="range"
            min={0.15}
            max={1}
            step={0.05}
            value={opacity}
            onChange={(e) => setRadarOpacity(Number(e.target.value))}
            className="w-28 accent-sky-400"
            aria-label="Opacità radar"
          />
          <span className="ml-auto truncate text-slate-500" title={radar.attribution}>
            Dati: {radar.attribution}
          </span>
        </div>
      </div>
    </div>
  );
}
