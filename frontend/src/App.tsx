import { useEffect } from "react";
import { MapView } from "./map/MapView";
import { StatusPanel } from "./panels/StatusPanel";
import { RadarPanel } from "./panels/RadarPanel";
import { AlertBanner } from "./panels/AlertBanner";
import { CellPanel } from "./panels/CellPanel";
import { PositionControl } from "./panels/PositionControl";
import { NavPanel } from "./panels/NavPanel";
import { ChaseToggle } from "./panels/ChaseToggle";
import { CopilotPanel } from "./panels/CopilotPanel";
import { PlanningPanel } from "./panels/PlanningPanel";
import { AlertLog } from "./panels/AlertLog";
import { SessionReport } from "./panels/SessionReport";
import { liveSocket } from "./lib/ws";
import { useStore } from "./state/store";

function PanelRails() {
  return (
    <div className="pointer-events-none absolute inset-0 z-10 flex gap-3 p-3">
      <div className="flex w-[248px] shrink-0 flex-col gap-2">
        <StatusPanel />
        <NavPanel />
        <PositionControl />
        <AlertLog />
      </div>

      <div className="flex min-w-0 flex-1 flex-col items-center gap-2 pb-7">
        <AlertBanner />
        <PlanningPanel />
        <div className="mt-auto flex w-full justify-center">
          <RadarPanel />
        </div>
      </div>

      <div className="flex w-[340px] shrink-0 flex-col items-end gap-2 pt-24">
        <CellPanel />
        <div className="mt-auto flex w-full flex-col items-end gap-2">
          <CopilotPanel />
          <ChaseToggle />
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const chase = useStore((s) => s.chaseMode);

  useEffect(() => {
    liveSocket.connect();
    liveSocket.send("ping");
    return () => liveSocket.close();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat) return;
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || el?.isContentEditable) return;
      const stt = useStore.getState().sttStatus;
      if (!stt.available || stt.listening) return;
      e.preventDefault();
      liveSocket.send("push_to_talk", {});
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="relative h-full w-full overflow-hidden">
      <MapView />
      <SessionReport />
      {chase ? (
        <>
          <div className="pointer-events-none absolute left-1/2 top-3 z-20 flex w-[min(92vw,440px)] -translate-x-1/2">
            <AlertBanner />
          </div>
          <NavPanel />
          <ChaseToggle />
        </>
      ) : (
        <PanelRails />
      )}
    </div>
  );
}
