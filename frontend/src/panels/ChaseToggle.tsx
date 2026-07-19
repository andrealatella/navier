import { useEffect } from "react";
import { useStore } from "../state/store";
import { setKeepAwake } from "../lib/wakeLock";
import { IconChase, IconClose } from "../ui/icons";

export function ChaseToggle() {
  const chase = useStore((s) => s.chaseMode);
  const setChase = useStore((s) => s.setChaseMode);

  useEffect(() => {
    setKeepAwake(chase);
    return () => setKeepAwake(false);
  }, [chase]);

  if (chase) {
    return (
      <div className="pointer-events-none absolute left-3 top-3 z-30">
        <button
          onClick={() => setChase(false)}
          className="pointer-events-auto flex items-center gap-2 rounded-xl border border-white/20 bg-slate-900/90 px-4 py-3 text-lg font-bold text-amber-300 shadow-xl backdrop-blur transition hover:bg-slate-800"
        >
          <IconClose className="h-5 w-5" strokeWidth={2.5} />
          ESCI CACCIA
        </button>
      </div>
    );
  }

  return (
    <div className="pointer-events-none">
      <button
        onClick={() => setChase(true)}
        className="pointer-events-auto flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/80 px-4 py-1.5 text-sm font-semibold text-slate-200 shadow-lg backdrop-blur transition hover:bg-slate-800"
        title="Modalità caccia: UI essenziale, schermo sempre acceso, mappa che segue il GPS"
      >
        <IconChase className="h-4 w-4" strokeWidth={1.75} />
        modalità caccia
      </button>
    </div>
  );
}
