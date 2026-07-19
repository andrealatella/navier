import { useEffect, useRef, useState } from "react";
import { IconCopilot, IconMic, IconMicOff, IconExpand, IconCollapse, IconWarning } from "../ui/icons";
import { useStore, type CopilotMsg, type CopilotStatus, type SttStatus } from "../state/store";
import { liveSocket } from "../lib/ws";

export function CopilotPanel() {
  const messages = useStore((s) => s.copilotMessages);
  const status = useStore((s) => s.copilotStatus);
  const stt = useStore((s) => s.sttStatus);
  const chase = useStore((s) => s.chaseMode);
  const addCopilotMessage = useStore((s) => s.addCopilotMessage);
  const [text, setText] = useState("");
  const [open, setOpen] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, open]);

  if (chase) return null;

  const disabled = !status.available;

  const send = () => {
    const q = text.trim();
    if (!q || disabled) return;
    addCopilotMessage({
      id: `u${Date.now()}`,
      role: "user",
      kind: "chat",
      reply: q,
      urgency: "info",
      speak: false,
      tts_text: "",
      ts: Date.now(),
    });
    liveSocket.send("ask_copilot", { question: q });
    setText("");
  };

  return (
    <div className="pointer-events-none w-full">
      <div className="pointer-events-auto flex flex-col overflow-hidden rounded-xl border border-white/10 bg-slate-900/90 shadow-xl backdrop-blur">
        <Header
          status={status}
          stt={stt}
          open={open}
          onToggle={() => setOpen((v) => !v)}
        />

        {open && (
          <>
            <div
              ref={scrollRef}
              className="flex max-h-[38vh] min-h-[96px] flex-col gap-2 overflow-y-auto px-3 py-2"
            >
              {messages.length === 0 && (
                <div className="py-4 text-center text-xs text-slate-500">
                  {disabled
                    ? "Co-pilota non attivo."
                    : "Chiedi al co-pilota “quale cella conviene?”, “che rischi ha la 3?”"}
                </div>
              )}
              {messages.map((m) => (
                <Bubble key={m.id} m={m} />
              ))}
            </div>

            <div className="flex items-center gap-2 border-t border-white/10 px-2 py-2">
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") send();
                }}
                disabled={disabled}
                placeholder={disabled ? "Co-pilota non disponibile" : "scrivi al co-pilota…"}
                className="min-w-0 flex-1 rounded-md border border-white/10 bg-slate-800 px-2 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus:border-sky-500 focus:outline-none disabled:opacity-50"
              />
              <button
                onClick={send}
                disabled={disabled || !text.trim()}
                className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:opacity-40"
              >
                invia
              </button>
            </div>

            <StatusFooter status={status} />
          </>
        )}
      </div>
    </div>
  );
}

function Header({
  status,
  stt,
  open,
  onToggle,
}: {
  status: CopilotStatus;
  stt: SttStatus;
  open: boolean;
  onToggle: () => void;
}) {
  const dot = status.busy
    ? "bg-amber-400 animate-pulse"
    : status.available
      ? "bg-emerald-400"
      : "bg-slate-500";
  return (
    <div className="flex items-center gap-2 border-b border-white/10 px-3 py-2">
      <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
      <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
        <IconCopilot className="h-4 w-4 shrink-0 text-slate-400" strokeWidth={1.75} />
        Co-pilota
      </span>
      {status.busy && <span className="text-xs text-amber-300">sta scrivendo…</span>}
      <div className="ml-auto flex items-center gap-1">
        {stt.enabled && <MicButton stt={stt} />}
        {status.available && (
          <button
            onClick={() => liveSocket.send("set_copilot_proactive", { on: !status.proactive })}
            className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
              status.proactive
                ? "bg-cyan-600/80 text-white"
                : "bg-slate-700 text-slate-300 hover:bg-slate-600"
            }`}
            title="Commento proattivo periodico (~90s): utile ma consuma quota"
          >
            proattivo {status.proactive ? "ON" : "OFF"}
          </button>
        )}
        <button
          onClick={onToggle}
          className="rounded px-2 py-0.5 text-xs text-slate-400 hover:bg-slate-700 hover:text-slate-100"
          title={open ? "riduci" : "espandi"}
        >
          {open ? (
            <IconCollapse className="h-4 w-4" strokeWidth={2} />
          ) : (
            <IconExpand className="h-4 w-4" strokeWidth={2} />
          )}
        </button>
      </div>
    </div>
  );
}

function MicButton({ stt }: { stt: SttStatus }) {
  const disabled = !stt.available || stt.listening;
  const cls = stt.listening
    ? "bg-fuchsia-600/90 text-white"
    : disabled
      ? "bg-slate-800 text-slate-500"
      : "bg-slate-700 text-slate-300 hover:bg-slate-600";
  const title = stt.available
    ? "Voce: premi Spazio (o questo tasto) per parlare al co-pilota"
    : `Voce non disponibile: ${stt.reason}`;
  return (
    <button
      onClick={() => liveSocket.send("push_to_talk", {})}
      disabled={disabled}
      className={`flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold transition ${cls}`}
      title={title}
    >
      {stt.listening ? (
        <IconMic className="h-3 w-3" strokeWidth={2} />
      ) : (
        <IconMicOff className="h-3 w-3" strokeWidth={2} />
      )}
      {stt.listening ? "ascolto…" : "voce"}
    </button>
  );
}

const KIND_BADGE: Record<string, { label: string; cls: string }> = {
  proactive: { label: "proattivo", cls: "text-cyan-300" },
  alert: { label: "alert", cls: "text-amber-300" },
};

const URGENCY_BORDER: Record<string, string> = {
  warning: "border-rose-500/40",
  caution: "border-amber-500/40",
  info: "border-white/10",
};

function Bubble({ m }: { m: CopilotMsg }) {
  if (m.role === "system") {
    return (
      <div className="mx-auto max-w-[92%] rounded-md bg-slate-800/60 px-2 py-1 text-center text-[11px] text-slate-400">
        {m.reply}
      </div>
    );
  }
  if (m.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] rounded-lg rounded-br-sm bg-sky-600/90 px-2.5 py-1.5 text-sm text-white">
        {m.kind === "voice" && (
          <IconMic className="mr-1 inline h-3 w-3 opacity-80" strokeWidth={2} />
        )}
        {m.reply}
      </div>
    );
  }
  const badge = KIND_BADGE[m.kind];
  return (
    <div
      className={`mr-auto max-w-[90%] rounded-lg rounded-bl-sm border bg-slate-800/80 px-2.5 py-1.5 text-sm text-slate-100 ${
        URGENCY_BORDER[m.urgency] ?? "border-white/10"
      }`}
    >
      {badge && (
        <span className={`mb-0.5 block text-[10px] font-semibold uppercase tracking-wide ${badge.cls}`}>
          {badge.label}
        </span>
      )}
      {m.reply}
    </div>
  );
}

function StatusFooter({ status }: { status: CopilotStatus }) {
  let text: string;
  let cls = "text-slate-500";
  let warn = false;
  if (!status.available) {
    text = status.reason || "non disponibile";
    cls = "text-amber-300";
    warn = true;
  } else if (status.quota_exhausted) {
    text = "a riposo · quota esaurita";
    cls = "text-amber-300";
  } else {
    const calls =
      status.calls_today != null && status.daily_limit != null
        ? ` · ${status.calls_today}/${status.daily_limit}`
        : "";
    text = `${status.model}${calls}`;
  }
  return (
    <div className={`flex items-center gap-1.5 border-t border-white/10 px-3 py-1 text-[11px] ${cls}`}>
      {warn && <IconWarning className="h-3 w-3 shrink-0" strokeWidth={2} />}
      {text}
    </div>
  );
}
