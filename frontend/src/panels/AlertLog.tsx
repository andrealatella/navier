import { useStore, type AlertMsg } from "../state/store";
import { IconHistory, IconExpand, IconCollapse } from "../ui/icons";

const P_TAG: Record<number, string> = { 1: "bg-rose-600", 2: "bg-amber-600", 3: "bg-slate-600" };

function fmtTime(ms: number): string {
  return new Date(ms).toLocaleTimeString("it-IT", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function AlertLog() {
  const history = useStore((s) => s.alertHistory);
  const open = useStore((s) => s.alertLogOpen);
  const setOpen = useStore((s) => s.setAlertLogOpen);

  if (history.length === 0) return null;

  const rows = [...history].reverse();

  if (!open) {
    return (
      <div className="pointer-events-none w-full select-none">
        <button
          onClick={() => setOpen(true)}
          className="pointer-events-auto flex w-full items-center gap-2 rounded-lg border border-white/10 bg-slate-900/80 px-3 py-1.5 text-sm text-slate-300 shadow-lg backdrop-blur transition hover:bg-slate-800"
        >
          <IconHistory className="h-4 w-4 shrink-0 text-slate-400" strokeWidth={1.75} />
          Registro allerte
          <span className="ml-auto flex items-center gap-1 text-xs text-slate-400">
            {history.length}
            <IconExpand className="h-3.5 w-3.5" strokeWidth={2} />
          </span>
        </button>
      </div>
    );
  }

  return (
    <div className="pointer-events-none w-full select-none">
      <div className="pointer-events-auto rounded-lg border border-white/10 bg-slate-900/85 shadow-lg backdrop-blur">
        <button
          onClick={() => setOpen(false)}
          className="flex w-full items-center gap-2 border-b border-white/10 px-3 py-2 text-sm font-semibold text-slate-100"
        >
          <IconHistory className="h-4 w-4 shrink-0 text-slate-400" strokeWidth={1.75} />
          Registro allerte
          <span className="ml-auto flex items-center gap-1 text-xs font-normal text-slate-400">
            {history.length}
            <IconCollapse className="h-3.5 w-3.5" strokeWidth={2} />
          </span>
        </button>
        <div className="max-h-64 overflow-y-auto">
          {rows.map((a) => (
            <LogRow key={a.id} alert={a} />
          ))}
        </div>
      </div>
    </div>
  );
}

function LogRow({ alert }: { alert: AlertMsg }) {
  return (
    <div className="flex items-start gap-2 border-b border-white/5 px-3 py-1.5 text-xs last:border-0">
      <span className="shrink-0 tabular-nums text-slate-500">{fmtTime(alert.created)}</span>
      <span
        className={`shrink-0 rounded px-1 py-0.5 text-[10px] font-bold text-white ${P_TAG[alert.priority] ?? "bg-slate-600"}`}
      >
        P{alert.priority}
      </span>
      <span className="min-w-0 text-slate-300">
        <span className="font-medium text-slate-200">{alert.title}</span>
      </span>
    </div>
  );
}
