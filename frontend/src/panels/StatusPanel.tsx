import type { ReactNode } from "react";
import { useStore, type WSStatus, type SourceHealth } from "../state/store";
import { liveSocket } from "../lib/ws";
import {
  Logo,
  IconLightning,
  IconRadar,
  IconPosition,
  IconMeteo,
  IconAllerte,
  IconCopilot,
  IconRec,
  IconReport,
} from "../ui/icons";

const WS_DOT: Record<WSStatus, string> = {
  open: "bg-emerald-400",
  connecting: "bg-amber-400 animate-pulse",
  closed: "bg-rose-500",
};

const WS_LABEL: Record<WSStatus, string> = {
  open: "connesso",
  connecting: "connessione…",
  closed: "disconnesso",
};

const SRC_DOT: Record<SourceHealth["state"], string> = {
  ok: "bg-emerald-400",
  starting: "bg-amber-400 animate-pulse",
  degraded: "bg-rose-500",
  stopped: "bg-slate-500",
  disabled: "bg-slate-600",
};

function fmtAge(age: number | null): string {
  if (age == null) return "-";
  if (age < 60) return `${Math.round(age)}s fa`;
  return `${Math.round(age / 60)}m fa`;
}

function SourceRow({
  dot,
  icon,
  label,
  value,
}: {
  dot: string;
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="mt-1 flex items-center gap-2 text-sm">
      <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
      <span className="flex items-center gap-1.5 text-slate-300">
        <span className="text-slate-400">{icon}</span>
        {label}
      </span>
      <span className="ml-auto shrink-0 tabular-nums text-slate-400">{value}</span>
    </div>
  );
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function RecButton() {
  const rec = useStore((s) => s.recorderStatus);
  if (!rec.available) return null;
  return (
    <button
      onClick={() => liveSocket.send("set_recorder", { on: !rec.recording })}
      title={
        rec.recording
          ? `Registrando in data/sessions/${rec.session} - premi per fermare e salvare`
          : "Registra questa sessione su disco per rivederla in replay"
      }
      className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide transition ${
        rec.recording
          ? "bg-rose-600 text-white hover:bg-rose-500"
          : "bg-slate-700 text-slate-300 hover:bg-slate-600"
      }`}
    >
      <IconRec
        className={`h-2.5 w-2.5 ${rec.recording ? "animate-pulse" : ""}`}
        fill="currentColor"
        strokeWidth={0}
      />
      {rec.recording ? `REC · ${fmtSize(rec.bytes)}` : "REC"}
    </button>
  );
}

function ReportButton() {
  const setReportOpen = useStore((s) => s.setReportOpen);
  return (
    <button
      onClick={() => setReportOpen(true)}
      title="Report delle sessioni registrate"
      className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-slate-300 transition hover:bg-slate-700 hover:text-slate-100"
    >
      <IconReport className="h-3 w-3" strokeWidth={1.75} />
      REPORT
    </button>
  );
}

export function StatusPanel() {
  const wsStatus = useStore((s) => s.wsStatus);
  const serverVersion = useStore((s) => s.serverVersion);
  const replaying = useStore((s) => s.replaying);
  const sources = useStore((s) => s.sources);
  const lightningCount = useStore((s) => s.lightningCount);

  const lightning = sources.find((s) => s.name === "blitzortung" || s.name === "fake_lightning");
  const radarMeta = useStore((s) => s.radar);
  const radarName = radarMeta.source === "rainviewer" ? "rainviewer" : "dpc_radar";
  const radar = sources.find((s) => s.name === radarName);
  const radarFrames = radarMeta.frameTimes.length;
  const user = useStore((s) => s.user);
  const meteo = sources.find((s) => s.name === "openmeteo");
  const allerte = sources.find((s) => s.name === "dpc_allerte");
  const copilot = useStore((s) => s.copilotStatus);

  let llmDot = "bg-slate-600";
  let llmDetail = "off";
  if (copilot.available && copilot.quota_exhausted) {
    llmDot = "bg-rose-500";
    llmDetail = "a riposo";
  } else if (copilot.available && copilot.busy) {
    llmDot = "bg-amber-400 animate-pulse";
    llmDetail = "…";
  } else if (copilot.available) {
    llmDot = "bg-emerald-400";
    llmDetail =
      copilot.calls_today != null && copilot.daily_limit != null
        ? `${copilot.calls_today}/${copilot.daily_limit}`
        : "attivo";
  } else if (copilot.enabled) {
    llmDot = "bg-amber-400";
    llmDetail = "manca chiave";
  }

  return (
    <div className="pointer-events-none w-full select-none">
      <div className="pointer-events-auto rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 shadow-lg backdrop-blur">
        <div className="flex items-center gap-2">
          <Logo />
          <span className="font-semibold tracking-wide">NAVIER</span>
          {serverVersion && <span className="text-xs text-slate-400">v{serverVersion}</span>}
          <div className="ml-auto flex items-center gap-1.5">
            <ReportButton />
            {replaying ? (
              <span className="flex items-center gap-1 rounded bg-fuchsia-600/80 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-white">
                <IconRec className="h-2.5 w-2.5" fill="currentColor" strokeWidth={0} /> REPLAY
              </span>
            ) : (
              <RecButton />
            )}
          </div>
        </div>

        <div className="mt-2 flex items-center gap-2 text-sm">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${WS_DOT[wsStatus]}`} />
          <span className="text-slate-300">live · {WS_LABEL[wsStatus]}</span>
        </div>

        <SourceRow
          dot={lightning ? SRC_DOT[lightning.state] : "bg-slate-600"}
          icon={<IconLightning className="h-3.5 w-3.5" strokeWidth={1.75} />}
          label={`fulmini${lightning?.name === "fake_lightning" ? " (fake)" : ""}`}
          value={`${lightningCount} · ${fmtAge(lightning?.age_s ?? null)}`}
        />
        <SourceRow
          dot={radar ? SRC_DOT[radar.state] : "bg-slate-600"}
          icon={<IconRadar className="h-3.5 w-3.5" strokeWidth={1.75} />}
          label={`radar${radarMeta.source === "rainviewer" ? " (RainViewer)" : ""}`}
          value={`${radarFrames} · ${fmtAge(radar?.age_s ?? null)}`}
        />
        <SourceRow
          dot={user ? "bg-emerald-400" : "bg-slate-600"}
          icon={<IconPosition className="h-3.5 w-3.5" strokeWidth={1.75} />}
          label="GPS"
          value={user ? GPS_SOURCE[user.source] ?? user.source : "assente"}
        />
        <SourceRow
          dot={meteo ? SRC_DOT[meteo.state] : "bg-slate-600"}
          icon={<IconMeteo className="h-3.5 w-3.5" strokeWidth={1.75} />}
          label="meteo"
          value={fmtAge(meteo?.age_s ?? null)}
        />
        <SourceRow
          dot={allerte ? SRC_DOT[allerte.state] : "bg-slate-600"}
          icon={<IconAllerte className="h-3.5 w-3.5" strokeWidth={1.75} />}
          label="allerte"
          value={allerte?.state === "ok" ? "attive" : fmtAge(allerte?.age_s ?? null)}
        />
        <SourceRow
          dot={llmDot}
          icon={<IconCopilot className="h-3.5 w-3.5" strokeWidth={1.75} />}
          label="co-pilota"
          value={llmDetail}
        />
      </div>
    </div>
  );
}

const GPS_SOURCE: Record<string, string> = {
  phone: "telefono",
  gpsd: "gpsd",
  manual: "manuale",
};
