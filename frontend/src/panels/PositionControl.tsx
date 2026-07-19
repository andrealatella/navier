import { useStore } from "../state/store";
import { IconPosition } from "../ui/icons";

export function PositionControl() {
  const placing = useStore((s) => s.placingPosition);
  const user = useStore((s) => s.user);
  const setPlacing = useStore((s) => s.setPlacingPosition);

  return (
    <div className="pointer-events-none select-none">
      <button
        onClick={() => setPlacing(!placing)}
        className={`pointer-events-auto flex items-center gap-2 rounded-lg border px-3 py-2 text-sm shadow-lg backdrop-blur transition ${
          placing
            ? "border-sky-400/60 bg-sky-950/90 text-sky-100"
            : "border-white/10 bg-slate-900/80 text-slate-200 hover:bg-slate-800"
        }`}
        title="Imposta la tua posizione con un clic sulla mappa"
      >
        <IconPosition className="h-4 w-4 shrink-0" strokeWidth={1.75} />
        {placing ? "clicca sulla mappa…" : user ? "sposta posizione" : "imposta posizione"}
      </button>
    </div>
  );
}
