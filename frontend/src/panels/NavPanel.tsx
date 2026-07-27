import {
  useStore,
  type RouteFeasibility,
  type RouteVerdict,
  type RouteView,
  type ViewQuality,
} from "../state/store";
import { liveSocket } from "../lib/ws";
import { planRoute, clearRoute, openInMaps } from "../lib/nav";
import {
  IconRoute,
  IconCell,
  IconDirect,
  IconMap,
  IconClose,
  IconWarning,
  IconTimer,
  IconOk,
  IconVisible,
} from "../ui/icons";

const VERDICT_STYLE: Record<RouteVerdict, string> = {
  in_tempo: "border-emerald-500/40 bg-emerald-950/50 text-emerald-200",
  limite: "border-amber-500/40 bg-amber-950/50 text-amber-200",
  tardi: "border-rose-500/40 bg-rose-950/50 text-rose-200",
  si_allontana: "border-rose-500/40 bg-rose-950/50 text-rose-200",
};

const VIEW_TEXT: Record<ViewQuality, string> = {
  buona: "text-emerald-300",
  media: "text-amber-300",
  scarsa: "text-rose-300",
};

export function NavPanel() {
  const route = useStore((s) => s.route);
  const loading = useStore((s) => s.routeLoading);
  const error = useStore((s) => s.routeError);
  const targetId = useStore((s) => s.targetCellId);
  const intercept = useStore((s) => s.interceptMode);
  const setIntercept = useStore((s) => s.setInterceptMode);
  const setTargetCellId = useStore((s) => s.setTargetCellId);
  const chase = useStore((s) => s.chaseMode);

  const active = targetId != null || route != null || error != null || loading;
  if (!active) return null;

  const setMode = (v: boolean) => {
    if (v === intercept) return;
    setIntercept(v);
    if (targetId != null) void planRoute();
  };

  const close = () => {
    setTargetCellId(null);
    liveSocket.send("set_target", { cell_id: null });
    clearRoute();
  };

  const onMaps = () => {
    if (route) openInMaps(route.dest.lat, route.dest.lon, `cella ${route.cellId ?? ""}`.trim());
  };

  const wrap = chase
    ? "pointer-events-none absolute bottom-6 left-1/2 z-20 w-[min(94vw,560px)] -translate-x-1/2"
    : "pointer-events-none w-full";

  return (
    <div className={wrap}>
      <div
        className={`pointer-events-auto rounded-xl border border-white/10 bg-slate-900/90 shadow-xl backdrop-blur ${
          chase ? "p-4 text-lg" : "px-3 py-2 text-sm"
        }`}
      >
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 font-semibold text-slate-100">
            <IconRoute className="h-4 w-4 shrink-0 text-slate-400" strokeWidth={1.75} />
            Rotta
          </span>
          {targetId != null && <span className="text-xs text-slate-400">cella #{targetId}</span>}
          <button
            onClick={close}
            className="ml-auto rounded px-2 py-0.5 text-xs text-slate-400 hover:bg-slate-700 hover:text-slate-100"
            title="Annulla inseguimento"
          >
            <IconClose className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </div>

        {targetId != null && (
          <div className="mt-2 flex overflow-hidden rounded-md border border-white/10 text-xs">
            <ModeBtn active={intercept} onClick={() => setMode(true)}>
              <IconCell className="h-3.5 w-3.5" strokeWidth={1.75} />
              intercetta
            </ModeBtn>
            <ModeBtn active={!intercept} onClick={() => setMode(false)}>
              <IconDirect className="h-3.5 w-3.5" strokeWidth={1.75} />
              diretto
            </ModeBtn>
          </div>
        )}

        {loading && <div className="mt-2 text-slate-400">calcolo rotta…</div>}

        {error && !loading && (
          <div className="mt-2 flex items-center gap-1.5 rounded-md border border-rose-500/30 bg-rose-950/40 px-2 py-1 text-rose-200">
            <IconWarning className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
            {error}
            {targetId != null && (
              <button
                onClick={() => void planRoute()}
                className="ml-2 rounded bg-rose-800/60 px-2 py-0.5 text-xs hover:bg-rose-700"
              >
                riprova
              </button>
            )}
          </div>
        )}

        {route && !loading && (
          <>
            <div className="mt-2 flex items-baseline gap-3">
              <span className="font-semibold tabular-nums text-cyan-300">
                {route.durationMin.toFixed(0)}′
              </span>
              <span className="tabular-nums text-slate-300">{route.distanceKm.toFixed(1)} km</span>
              <span className="ml-auto text-[11px] uppercase text-slate-500">{route.provider}</span>
            </div>

            {route.feasibility && <Feasibility data={route.feasibility} chase={chase} />}

            {route.view && <ViewBox data={route.view} chase={chase} />}

            {route.intercept && route.note && (
              <div className="mt-1 text-xs text-slate-400">{route.note}</div>
            )}

            {route.crosses.length > 0 && (
              <div className="mt-2 flex items-start gap-1.5 rounded-md border border-rose-500/40 bg-rose-950/50 px-2 py-1 text-xs text-rose-200">
                <IconWarning className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                <span>
                  la rotta attraversa il cono della cella #{route.crosses.join(", #")}: valuta un
                  avvicinamento laterale.
                </span>
              </div>
            )}

            <button
              onClick={onMaps}
              className={`mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-sky-600 font-semibold text-white shadow transition hover:bg-sky-500 ${
                chase ? "py-3 text-lg" : "py-2 text-sm"
              }`}
            >
              <IconMap className={chase ? "h-5 w-5" : "h-4 w-4"} strokeWidth={1.75} />
              Apri in Google Maps
            </button>
            <div className="mt-1 text-center text-[11px] text-slate-500">
              in companion mode si apre anche sul telefono
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Feasibility({ data, chase }: { data: RouteFeasibility; chase: boolean }) {
  const Icon =
    data.verdict === "in_tempo" ? IconOk : data.verdict === "limite" ? IconTimer : IconWarning;
  return (
    <div
      className={`mt-2 rounded-md border px-2 py-1.5 ${VERDICT_STYLE[data.verdict]} ${
        chase ? "text-base" : "text-xs"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <Icon className={chase ? "h-4 w-4 shrink-0" : "h-3.5 w-3.5 shrink-0"} strokeWidth={2} />
        <span className="font-semibold">{data.text}</span>
      </div>
      <div className="mt-0.5 pl-5 text-[11px] tabular-nums opacity-70">
        guida {data.driveMin.toFixed(0)}′ · cella {data.cellMin.toFixed(0)}′
      </div>
    </div>
  );
}

function ViewBox({ data, chase }: { data: RouteView; chase: boolean }) {
  return (
    <div
      className={`mt-2 rounded-md border border-white/10 bg-slate-800/50 px-2 py-1.5 ${
        chase ? "text-sm" : "text-xs"
      }`}
    >
      <div className="flex items-center gap-1.5">
        <IconVisible
          className={`shrink-0 ${chase ? "h-4 w-4" : "h-3.5 w-3.5"} ${VIEW_TEXT[data.quality]}`}
          strokeWidth={1.75}
        />
        <span className={`font-medium ${VIEW_TEXT[data.quality]}`}>{data.text}</span>
      </div>
      <div className="mt-0.5 pl-5 text-[11px] tabular-nums text-slate-500">
        vista {data.score}/100 · sole {data.sunAzimuthDeg.toFixed(0)}° a{" "}
        {data.sunElevationDeg.toFixed(0)}° sull'orizzonte
        {!data.rainKnown && " · pioggia non nota"}
      </div>
    </div>
  );
}

function ModeBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-1 items-center justify-center gap-1.5 px-2 py-1 transition ${
        active ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"
      }`}
    >
      {children}
    </button>
  );
}
