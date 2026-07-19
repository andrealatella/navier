import { useStore, type AlertMsg } from "../state/store";
import { IconSound, IconMuted } from "../ui/icons";
import { liveSocket } from "../lib/ws";

const P_STYLE: Record<number, string> = {
  1: "border-rose-500/70 bg-rose-950/85 text-rose-50",
  2: "border-amber-500/60 bg-amber-950/80 text-amber-50",
  3: "border-slate-500/50 bg-slate-900/85 text-slate-100",
};
const P_TAG: Record<number, string> = { 1: "bg-rose-600", 2: "bg-amber-600", 3: "bg-slate-600" };
const P_LABEL: Record<number, string> = { 1: "P1", 2: "P2", 3: "P3" };

export function AlertBanner() {
  const alerts = useStore((s) => s.alerts);
  const ttsEnabled = useStore((s) => s.ttsEnabled);
  const toggleTts = useStore((s) => s.toggleTts);

  const sorted = [...alerts].sort((a, b) => a.priority - b.priority);

  return (
    <div className="pointer-events-none flex w-full max-w-[440px] flex-col gap-2">
      {sorted.length > 0 && (
        <div className="flex justify-end">
          <button
            onClick={() => {
              const next = !ttsEnabled;
              toggleTts();
              liveSocket.send("set_tts", { enabled: next });
            }}
            className="pointer-events-auto flex items-center gap-1.5 rounded-md border border-white/10 bg-slate-900/80 px-2 py-1 text-xs text-slate-200 shadow backdrop-blur transition hover:bg-slate-800"
            title={ttsEnabled ? "Disattiva voce" : "Attiva voce"}
          >
            {ttsEnabled ? (
              <IconSound className="h-3.5 w-3.5" strokeWidth={1.75} />
            ) : (
              <IconMuted className="h-3.5 w-3.5" strokeWidth={1.75} />
            )}
            {ttsEnabled ? "voce attiva" : "voce muta"}
          </button>
        </div>
      )}
      {sorted.map((a) => (
        <AlertCard key={a.id} alert={a} />
      ))}
    </div>
  );
}

function AlertCard({ alert }: { alert: AlertMsg }) {
  const pulse = alert.priority === 1 ? "animate-pulse" : "";
  return (
    <div
      className={`pointer-events-auto rounded-lg border px-3 py-2 shadow-xl backdrop-blur ${P_STYLE[alert.priority]} ${pulse}`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`rounded px-1.5 py-0.5 text-[11px] font-bold text-white ${P_TAG[alert.priority]}`}
        >
          {P_LABEL[alert.priority]}
        </span>
        <span className="text-sm font-semibold">{alert.title}</span>
      </div>
      <p className="mt-1 text-xs leading-snug opacity-90">{alert.message}</p>
    </div>
  );
}
