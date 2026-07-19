import { useCallback, useEffect, useState } from "react";
import { useStore } from "../state/store";
import {
  IconReport,
  IconClose,
  IconLightning,
  IconCell,
  IconRoad,
  IconGauge,
  IconSupercell,
} from "../ui/icons";

interface SessionItem {
  name: string;
  size_bytes: number;
  modified_ms: number;
  frames: number;
}

interface AlertRow {
  id: string;
  rule_id: string | null;
  priority: number | null;
  title: string | null;
  message: string | null;
  t_ms: number;
}

interface Report {
  name: string;
  duration_s: number;
  world_frames: number;
  radar_frames: number;
  distance_km: number;
  lightning_total: number;
  nearest_strike_km: number | null;
  cells_seen: number;
  peak_cells: number;
  max_dbz: number | null;
  max_dbz_cell: number | null;
  max_severity: number;
  supercell_cells: number[];
  jump_cells: number[];
  copilot_replies: number;
  alerts: AlertRow[];
  alert_counts: Record<string, number>;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtDuration(s: number): string {
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  if (m > 0) return `${m}m ${Math.round(s % 60)}s`;
  return `${Math.round(s)}s`;
}

function fmtDate(ms: number): string {
  return new Date(ms).toLocaleString("it-IT", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtClock(ms: number): string {
  const s = Math.floor(ms / 1000);
  const mm = String(Math.floor(s / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

const P_TAG: Record<number, string> = { 1: "bg-rose-600", 2: "bg-amber-600", 3: "bg-slate-600" };

export function SessionReport() {
  const open = useStore((s) => s.reportOpen);
  const setOpen = useStore((s) => s.setReportOpen);
  const [sessions, setSessions] = useState<SessionItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);

  const loadReport = useCallback(async (name: string) => {
    setSelected(name);
    setReport(null);
    setLoading(true);
    try {
      const r = await fetch(`/api/sessions/${encodeURIComponent(name)}/report`);
      setReport(r.ok ? await r.json() : null);
    } catch {
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      try {
        const r = await fetch("/api/sessions");
        const j = await r.json();
        const list = (j.sessions as SessionItem[]) ?? [];
        setSessions(list);
        if (list.length > 0) void loadReport(list[0].name);
      } catch {
        setSessions([]);
      }
    })();
  }, [open, loadReport]);

  if (!open) return null;

  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-xl border border-white/10 bg-slate-900/95 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-56 shrink-0 border-r border-white/10 bg-slate-950/40">
          <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2 text-sm font-semibold text-slate-100">
            <IconReport className="h-4 w-4 shrink-0 text-slate-400" strokeWidth={1.75} />
            Sessioni
          </div>
          <div className="max-h-[calc(85vh-42px)] overflow-y-auto">
            {sessions == null ? (
              <p className="px-3 py-3 text-xs text-slate-400">caricamento…</p>
            ) : sessions.length === 0 ? (
              <p className="px-3 py-3 text-xs text-slate-400">
                Nessuna sessione registrata. Premi ⏺ REC durante una caccia per registrarne una.
              </p>
            ) : (
              sessions.map((s) => (
                <button
                  key={s.name}
                  onClick={() => void loadReport(s.name)}
                  className={`block w-full border-b border-white/5 px-3 py-2 text-left text-xs transition ${
                    selected === s.name ? "bg-sky-950/60" : "hover:bg-slate-800/60"
                  }`}
                >
                  <div className="font-medium text-slate-200">{fmtDate(s.modified_ms)}</div>
                  <div className="text-[10px] text-slate-500">
                    {fmtSize(s.size_bytes)} · {s.frames} frame radar
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-white/10 px-4 py-2">
            <span className="text-sm font-semibold text-slate-100">Report sessione</span>
            <button
              onClick={() => setOpen(false)}
              className="ml-auto rounded px-1.5 text-slate-400 hover:text-slate-200"
              aria-label="chiudi"
            >
              <IconClose className="h-4 w-4" strokeWidth={2} />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {loading ? (
              <p className="text-sm text-slate-400">caricamento report…</p>
            ) : !report ? (
              <p className="text-sm text-slate-400">Seleziona una sessione.</p>
            ) : (
              <ReportBody report={report} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ReportBody({ report }: { report: Report }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Stat label="Durata" value={fmtDuration(report.duration_s)} />
        <Stat
          label="Distanza"
          value={`${report.distance_km} km`}
          icon={<IconRoad className="h-3.5 w-3.5" strokeWidth={1.75} />}
        />
        <Stat
          label="Celle viste"
          value={`${report.cells_seen}`}
          hint={`picco ${report.peak_cells} insieme`}
          icon={<IconCell className="h-3.5 w-3.5" strokeWidth={1.75} />}
        />
        <Stat
          label="Eco massima"
          value={report.max_dbz != null ? `${report.max_dbz} dBZ` : "-"}
          hint={report.max_dbz_cell != null ? `cella #${report.max_dbz_cell}` : undefined}
        />
        <Stat
          label="Severità max"
          value={`${report.max_severity}`}
          icon={<IconGauge className="h-3.5 w-3.5" strokeWidth={1.75} />}
        />
        <Stat
          label="Fulmini"
          value={`${report.lightning_total}`}
          hint={
            report.nearest_strike_km != null
              ? `più vicino ${report.nearest_strike_km} km`
              : undefined
          }
          icon={<IconLightning className="h-3.5 w-3.5" strokeWidth={1.75} />}
        />
      </div>

      {report.supercell_cells.length > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-2 text-xs text-fuchsia-200">
          <IconSupercell className="h-4 w-4 shrink-0" strokeWidth={2} />
          Comportamento da possibile supercella su:{" "}
          {report.supercell_cells.map((c) => `#${c}`).join(", ")} (euristica, non una certezza).
        </div>
      )}

      <div>
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
          Allerte ({report.alerts.length})
        </div>
        {report.alerts.length === 0 ? (
          <p className="text-xs text-slate-500">Nessun allarme deterministico durante la sessione.</p>
        ) : (
          <div className="space-y-1">
            {report.alerts.map((a) => (
              <div
                key={a.id}
                className="flex items-start gap-2 rounded border border-white/5 bg-slate-800/40 px-2 py-1.5 text-xs"
              >
                <span className="shrink-0 tabular-nums text-slate-500">{fmtClock(a.t_ms)}</span>
                {a.priority != null && (
                  <span
                    className={`shrink-0 rounded px-1 py-0.5 text-[10px] font-bold text-white ${P_TAG[a.priority] ?? "bg-slate-600"}`}
                  >
                    P{a.priority}
                  </span>
                )}
                <span className="min-w-0">
                  <span className="font-medium text-slate-200">{a.title ?? a.rule_id}</span>
                  {a.message && <span className="text-slate-400"> - {a.message}</span>}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {report.copilot_replies > 0 && (
        <p className="text-[11px] text-slate-500">
          Co-pilota: {report.copilot_replies} messaggi · {report.world_frames} aggiornamenti mondo ·{" "}
          {report.radar_frames} frame radar salvati
        </p>
      )}
      <p className="border-t border-white/10 pt-2 text-[11px] text-slate-500">
        Per rivedere la sessione sulla mappa: imposta <code className="text-slate-400">REPLAY_FILE={report.name}</code> nel{" "}
        <code className="text-slate-400">.env</code> e riavvia il backend.
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-800/40 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums text-slate-100">{value}</div>
      {hint && <div className="text-[10px] text-slate-500">{hint}</div>}
    </div>
  );
}
