import { useCallback, useEffect, useState } from "react";
import { IconMap, IconAllerte, IconClose, IconExternal } from "../ui/icons";
import { useStore, type PlanningMeta } from "../state/store";
import { meteoLayer, type MeteoField } from "../map/meteoLayer";
import { allerteLayer } from "../map/allerteLayer";

interface OutlookItem {
  source: string;
  title: string;
  page_url: string;
  attribution: string;
  image_url: string | null;
  tendency_url: string | null;
  level: number | null;
  zones: string[] | null;
  summary: string | null;
}

const LEVEL_STYLE: Record<number, { label: string; cls: string }> = {
  0: { label: "Nessun rischio", cls: "bg-slate-600 text-white" },
  1: { label: "Livello 1 · basso", cls: "bg-yellow-500 text-black" },
  2: { label: "Livello 2 · moderato", cls: "bg-orange-500 text-black" },
  3: { label: "Livello 3 · alto", cls: "bg-rose-600 text-white" },
};

export function PlanningPanel() {
  const open = useStore((s) => s.planningOpen);
  const field = useStore((s) => s.meteoField);
  const meta = useStore((s) => s.planningMeta);
  const setOpen = useStore((s) => s.setPlanningOpen);
  const setField = useStore((s) => s.setMeteoField);
  const setMeta = useStore((s) => s.setPlanningMeta);
  const allerteOn = useStore((s) => s.allerteOn);
  const setAllerteOn = useStore((s) => s.setAllerteOn);
  const [allerteInfo, setAllerteInfo] = useState<{ count: number; issued: string | null } | null>(
    null,
  );
  const [outlooks, setOutlooks] = useState<OutlookItem[] | null>(null);

  const load = useCallback(
    async (hour?: number) => {
      try {
        const q = hour == null ? "" : `?hour=${hour}`;
        const r = await fetch(`/api/planning${q}`);
        const j = await r.json();
        if (!j.available) {
          setMeta({
            available: false,
            reason: j.reason ?? "non disponibile",
            model: j.model ?? "",
            hour: null,
            hours: [],
            hourIndex: 0,
            maxCape: 0,
            updatedMs: null,
          });
          meteoLayer.setData({ type: "FeatureCollection", features: [] });
          return;
        }
        const m: PlanningMeta = {
          available: true,
          model: j.model ?? "",
          hour: j.hour ?? null,
          hours: j.hours ?? [],
          hourIndex: j.hour_index ?? 0,
          maxCape: j.max_cape ?? 0,
          updatedMs: j.updated_ms ?? null,
        };
        setMeta(m);
        meteoLayer.setData(j.grid ?? { type: "FeatureCollection", features: [] });
      } catch {
        setMeta({
          available: false,
          reason: "backend irraggiungibile",
          model: "",
          hour: null,
          hours: [],
          hourIndex: 0,
          maxCape: 0,
          updatedMs: null,
        });
      }
    },
    [setMeta],
  );

  useEffect(() => {
    meteoLayer.setVisible(open);
    if (!open) return;
    void load();
    void (async () => {
      try {
        const r = await fetch("/api/outlook");
        const j = await r.json();
        setOutlooks(j.available ? (j.outlooks as OutlookItem[]) : []);
      } catch {
        setOutlooks(null);
      }
    })();
  }, [open, load]);

  useEffect(() => {
    meteoLayer.setField(field);
  }, [field]);

  useEffect(() => {
    allerteLayer.setVisible(allerteOn);
    if (!allerteOn) return;
    void (async () => {
      try {
        const r = await fetch("/api/allerte");
        const j = await r.json();
        const fc = j.zones ?? { type: "FeatureCollection", features: [] };
        allerteLayer.setData(fc);
        setAllerteInfo({ count: fc.features?.length ?? 0, issued: j.issued ?? null });
      } catch {
        setAllerteInfo(null);
      }
    })();
  }, [allerteOn]);

  if (!open) {
    return (
      <div className="pointer-events-none">
        <button
          onClick={() => setOpen(true)}
          className="pointer-events-auto flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/80 px-3 py-1.5 text-sm text-slate-200 shadow-lg backdrop-blur hover:bg-slate-800"
        >
          <IconMap className="h-4 w-4" strokeWidth={1.75} />
          CAPE / shear
        </button>
      </div>
    );
  }

  const hourLabel = meta?.hour ? fmtHour(meta.hour) : "-";

  return (
    <div className="pointer-events-none">
      <div className="pointer-events-auto w-72 rounded-lg border border-white/10 bg-slate-900/85 px-3 py-2 shadow-lg backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-slate-100">
            <IconMap className="h-4 w-4 shrink-0 text-slate-400" strokeWidth={1.75} />
            Pianificazione
          </span>
          <button
            onClick={() => setOpen(false)}
            className="ml-auto rounded px-1.5 text-slate-400 hover:text-slate-200"
            aria-label="chiudi"
          >
            <IconClose className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </div>

        <div className="mt-2 flex overflow-hidden rounded-md border border-white/10 text-sm">
          {(["cape", "shear"] as MeteoField[]).map((f) => (
            <button
              key={f}
              onClick={() => setField(f)}
              className={`flex-1 px-2 py-1 ${
                field === f ? "bg-sky-600 text-white" : "bg-slate-800/60 text-slate-300"
              }`}
            >
              {f === "cape" ? "CAPE" : "Shear 0-6 km"}
            </button>
          ))}
        </div>

        {meta?.available ? (
          <>
            {meta.hours.length > 1 && (
              <div className="mt-2">
                <div className="flex justify-between text-xs text-slate-400">
                  <span>previsione</span>
                  <span className="tabular-nums text-slate-200">{hourLabel}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={meta.hours.length - 1}
                  value={meta.hourIndex}
                  onChange={(e) => void load(Number(e.target.value))}
                  className="w-full accent-sky-500"
                />
              </div>
            )}

            <Legend field={field} />

            <div className="mt-2 flex justify-between text-xs text-slate-400">
              <span>{field === "cape" ? `max ${meta.maxCape} J/kg` : "shear 0-6 km"}</span>
              <span title={meta.model}>ICON-2I · {fmtUpdated(meta.updatedMs)}</span>
            </div>
          </>
        ) : (
          <p className="mt-2 text-xs text-amber-300">{meta?.reason ?? "caricamento…"}</p>
        )}

        <label className="mt-3 flex cursor-pointer items-center gap-2 border-t border-white/10 pt-2 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={allerteOn}
            onChange={(e) => setAllerteOn(e.target.checked)}
            className="accent-amber-500"
          />
          <span className="flex items-center gap-1.5">
            <IconAllerte className="h-3.5 w-3.5 shrink-0 text-slate-400" strokeWidth={1.75} />
            Allerte DPC
          </span>
          {allerteOn && (
            <span className="ml-auto text-xs text-slate-400">
              {allerteInfo
                ? allerteInfo.count > 0
                  ? `${allerteInfo.count} zone`
                  : "nessuna allerta"
                : "…"}
            </span>
          )}
        </label>

        {outlooks && outlooks.length > 0 && (
          <div className="mt-3 border-t border-white/10 pt-2">
            <div className="mb-1 text-xs font-medium text-slate-300">Outlook convettivo</div>
            {outlooks.map((o) => (
              <div key={o.source} className="mb-2 last:mb-0">
                {o.level != null && (
                  <div className="mb-1 flex items-center gap-2">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${
                        LEVEL_STYLE[o.level]?.cls ?? "bg-slate-600 text-white"
                      }`}
                    >
                      {LEVEL_STYLE[o.level]?.label ?? `Livello ${o.level}`}
                    </span>
                    {o.zones && o.zones.length > 0 && (
                      <span className="min-w-0 truncate text-[11px] text-slate-300">
                        {o.zones.join(", ")}
                      </span>
                    )}
                  </div>
                )}
                {o.image_url ? (
                  <a href={o.page_url} target="_blank" rel="noreferrer" title={o.attribution}>
                    <img
                      src={o.image_url}
                      alt={o.title}
                      loading="lazy"
                      className="w-full rounded border border-white/10"
                    />
                  </a>
                ) : (
                  <a
                    href={o.page_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-sm text-sky-400 hover:underline"
                  >
                    {o.source}
                    <IconExternal className="h-3 w-3" strokeWidth={2} />
                  </a>
                )}
                {o.summary && <div className="mt-0.5 text-[11px] text-slate-400">{o.summary}</div>}
                <div className="text-[10px] text-slate-500">{o.attribution}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Legend({ field }: { field: MeteoField }) {
  const stops =
    field === "cape"
      ? ["0", "1500", "3000+ J/kg"]
      : ["0", "15", "30+ m/s"];
  return (
    <div className="mt-2">
      <div
        className="h-2 w-full rounded"
        style={{
          background:
            "linear-gradient(to right, #1e3a8a, #0ea5e9, #22c55e, #eab308, #f97316, #ef4444)",
        }}
      />
      <div className="mt-0.5 flex justify-between text-[10px] text-slate-500">
        {stops.map((s) => (
          <span key={s}>{s}</span>
        ))}
      </div>
    </div>
  );
}

function fmtHour(iso: string): string {
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function fmtUpdated(ms: number | null): string {
  if (ms == null) return "-";
  const age = (Date.now() - ms) / 60000;
  if (age < 1) return "ora";
  return `${Math.round(age)}m fa`;
}
