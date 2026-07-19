import { useMemo, useState } from "react";
import { useStore, type CellRow } from "../state/store";
import { liveSocket } from "../lib/ws";
import { haversineKm } from "../lib/geo";
import { planRoute, clearRoute } from "../lib/nav";
import {
  IconCell,
  IconLightning,
  IconSpeed,
  IconPosition,
  IconTarget,
  IconSupercell,
  IconTrendUp,
  IconTrendDown,
  IconTrendSteady,
} from "../ui/icons";

type SortKey = "severity" | "distance";

function sevColor(sev: number): string {
  if (sev >= 80) return "text-rose-400";
  if (sev >= 60) return "text-orange-400";
  if (sev >= 40) return "text-amber-300";
  return "text-cyan-300";
}

function TrendIcon({ trend }: { trend: string }) {
  const cls = "h-3.5 w-3.5 shrink-0";
  if (trend === "up") return <IconTrendUp className={`${cls} text-rose-400`} strokeWidth={2} />;
  if (trend === "down") return <IconTrendDown className={`${cls} text-sky-400`} strokeWidth={2} />;
  return <IconTrendSteady className={`${cls} text-slate-500`} strokeWidth={2} />;
}

function Sparkline({ values, colorClass }: { values: number[]; colorClass: string }) {
  if (values.length < 2) return null;
  const W = 46;
  const H = 14;
  const n = values.length;
  const pts = values
    .map((v, i) => {
      const x = (i / (n - 1)) * W;
      const y = H - (Math.max(0, Math.min(100, v)) / 100) * H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      className={`shrink-0 ${colorClass}`}
      preserveAspectRatio="none"
      aria-hidden
    >
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function CellPanel() {
  const cells = useStore((s) => s.cells);
  const user = useStore((s) => s.user);
  const targetId = useStore((s) => s.targetCellId);
  const setTargetCellId = useStore((s) => s.setTargetCellId);
  const [sort, setSort] = useState<SortKey>("severity");

  const rows = useMemo(() => {
    const withDist = cells.map((c) => ({
      cell: c,
      dist: user ? haversineKm([user.lon, user.lat], c.centroid) : null,
    }));
    withDist.sort((a, b) =>
      sort === "distance"
        ? (a.dist ?? Infinity) - (b.dist ?? Infinity)
        : b.cell.severity - a.cell.severity,
    );
    return withDist;
  }, [cells, user, sort]);

  const chase = (id: number) => {
    const next = targetId === id ? null : id;
    setTargetCellId(next);
    liveSocket.send("set_target", { cell_id: next });
    if (next != null) void planRoute();
    else clearRoute();
  };

  if (cells.length === 0) {
    return (
      <div className="pointer-events-none w-[248px] select-none">
        <div className="pointer-events-auto flex items-center gap-2 rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-400 shadow-lg backdrop-blur">
          <IconCell className="h-4 w-4 shrink-0" strokeWidth={1.75} />
          nessuna cella tracciata
        </div>
      </div>
    );
  }

  return (
    <div className="pointer-events-none flex min-h-0 w-[248px] flex-1 flex-col select-none">
      <div className="pointer-events-auto flex max-h-full flex-col rounded-lg border border-white/10 bg-slate-900/85 shadow-lg backdrop-blur">
        <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2 text-sm">
          <span className="flex items-center gap-1.5 font-semibold text-slate-100">
            <IconCell className="h-4 w-4 shrink-0 text-slate-400" strokeWidth={1.75} />
            Celle
          </span>
          <span className="text-xs text-slate-400">{cells.length}</span>
          <div className="ml-auto flex overflow-hidden rounded-md border border-white/10 text-[11px]">
            <SortBtn active={sort === "severity"} onClick={() => setSort("severity")}>
              sev
            </SortBtn>
            <SortBtn active={sort === "distance"} onClick={() => setSort("distance")}>
              dist
            </SortBtn>
          </div>
        </div>
        <div className="overflow-y-auto">
          {rows.map(({ cell, dist }) => (
            <Row
              key={cell.id}
              cell={cell}
              dist={dist}
              target={targetId === cell.id}
              onChase={() => chase(cell.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function SortBtn({
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
      className={`px-2 py-0.5 transition ${active ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"}`}
    >
      {children}
    </button>
  );
}

function SupercellBadge({ cell }: { cell: CellRow }) {
  const dev = cell.deviation_deg;
  const side = dev == null ? null : dev > 0 ? "destra" : "sinistra";
  return (
    <span
      className="flex items-center gap-1 rounded bg-fuchsia-500/20 px-1 font-semibold text-fuchsia-300"
      title={
        "Euristica, non una certezza: cella longeva e intensa il cui moto devia dal " +
        "flusso medio in quota - comportamento tipico delle supercelle. " +
        "NAVIER non ha il radar Doppler: nessuna rotazione è stata osservata."
      }
    >
      <IconSupercell className="h-3 w-3 shrink-0" strokeWidth={2} />
      possibile supercella
      {dev != null && ` · devia ${Math.abs(dev).toFixed(0)}° a ${side}`}
    </span>
  );
}

function Row({
  cell,
  dist,
  target,
  onChase,
}: {
  cell: CellRow;
  dist: number | null;
  target: boolean;
  onChase: () => void;
}) {
  return (
    <div
      className={`border-b border-white/5 px-3 py-2 text-sm ${target ? "bg-sky-950/60" : ""}`}
    >
      <div className="flex items-center gap-2">
        <span className={`font-semibold tabular-nums ${sevColor(cell.severity)}`}>
          {cell.severity}
        </span>
        <Sparkline values={cell.sev_series} colorClass={sevColor(cell.severity)} />
        <span className="font-medium text-slate-200">#{cell.id}</span>
        <span className="flex items-center gap-1 text-xs text-slate-400">
          {cell.max_dbz.toFixed(0)} dBZ
          <TrendIcon trend={cell.trend} />
        </span>
        <button
          onClick={onChase}
          className={`ml-auto flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold transition ${
            target
              ? "bg-sky-500 text-white"
              : "bg-slate-700 text-slate-100 hover:bg-slate-600"
          }`}
        >
          {target ? (
            <>
              <IconTarget className="h-3 w-3" fill="currentColor" strokeWidth={0} />
              target
            </>
          ) : (
            "INSEGUI"
          )}
        </button>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-slate-400">
        {cell.lightning_min > 0 && (
          <span className="flex items-center gap-1">
            <IconLightning className="h-3 w-3 shrink-0" strokeWidth={1.75} />
            {cell.lightning_min.toFixed(0)}/min
          </span>
        )}
        {cell.speed_kmh != null && cell.speed_kmh >= 1 && (
          <span className="flex items-center gap-1">
            <IconSpeed className="h-3 w-3 shrink-0" strokeWidth={1.75} />
            {cell.speed_kmh.toFixed(0)} km/h
          </span>
        )}
        {dist != null && (
          <span className="flex items-center gap-1">
            <IconPosition className="h-3 w-3 shrink-0" strokeWidth={1.75} />
            {dist.toFixed(0)} km
          </span>
        )}
        {cell.eta_min != null && <span className="text-rose-300">ETA {cell.eta_min.toFixed(0)}′</span>}
        {cell.flags.includes("lightning_jump") && (
          <span className="flex items-center gap-1 font-semibold text-amber-300">
            <IconLightning className="h-3 w-3 shrink-0" fill="currentColor" strokeWidth={1.5} />
            jump
          </span>
        )}
        {cell.flags.includes("possible_supercell") && <SupercellBadge cell={cell} />}
      </div>
    </div>
  );
}
