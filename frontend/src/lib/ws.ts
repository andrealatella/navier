import {
  useStore,
  type ServerMessage,
  type SourceHealth,
  type CellRow,
  type AlertMsg,
  type UserPos,
  type CopilotMsg,
  type CopilotStatus,
  type SttStatus,
  type RecorderStatus,
} from "../state/store";
import { lightningLayer, type Strike } from "../map/lightningLayer";
import { radarLayer, type RadarData } from "../map/radarLayer";
import { cellLayer } from "../map/cellLayer";
import { userLayer } from "../map/userLayer";

export class LiveSocket {
  private ws: WebSocket | null = null;
  private backoffMs = 1000;
  private readonly maxBackoffMs = 15000;
  private closedByUser = false;
  private outbox: string[] = [];

  connect(): void {
    this.closedByUser = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/live`;

    useStore.getState().setWsStatus("connecting");
    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      this.backoffMs = 1000;
      useStore.getState().setWsStatus("open");
      for (const msg of this.outbox) ws.send(msg);
      this.outbox = [];
      // eslint-disable-next-line no-console
      console.info("[ws] connected to", url);
    };

    ws.onmessage = (ev) => {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        console.warn("[ws] non-JSON message", ev.data);
        return;
      }
      this.dispatch(msg);
    };

    ws.onclose = () => {
      useStore.getState().setWsStatus("closed");
      if (!this.closedByUser) this.scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private dispatch(msg: ServerMessage): void {
    const store = useStore.getState();
    switch (msg.type) {
      case "hello":
        store.setServerVersion(String(msg.payload.version ?? "?"));
        store.setReplaying(Boolean(msg.payload.replay));
        console.info("[ws] hello from server v" + msg.payload.version);
        break;
      case "lightning_batch":
        lightningLayer.addStrikes((msg.payload.strikes as Strike[]) ?? []);
        break;
      case "radar_frames": {
        const data = msg.payload as unknown as RadarData;
        radarLayer.setData(data);
        store.setRadarMeta({
          source: data.source,
          kind: data.kind,
          attribution: data.attribution ?? "",
          frameTimes: (data.frames ?? []).map((f) => f.ts),
        });
        break;
      }
      case "source_health":
        store.setSourceHealth(
          (msg.payload.sources as SourceHealth[]) ?? [],
          Number(msg.payload.lightning_count ?? 0),
        );
        break;
      case "world_state":
        this.dispatchWorld(msg.payload);
        break;
      case "copilot_msg": {
        const m = msg.payload as unknown as CopilotMsg;
        store.addCopilotMessage(m);
        break;
      }
      case "copilot_status":
        store.setCopilotStatus(msg.payload as unknown as CopilotStatus);
        break;
      case "stt_status":
        store.setSttStatus(msg.payload as unknown as SttStatus);
        break;
      case "recorder_status":
        store.setRecorderStatus(msg.payload as unknown as RecorderStatus);
        break;
      default:
        break;
    }
  }

  private dispatchWorld(payload: Record<string, unknown>): void {
    const store = useStore.getState();
    const cellsFC = (payload.cells as GeoJSON.FeatureCollection) ?? {
      type: "FeatureCollection",
      features: [],
    };
    const conesFC = (payload.cones as GeoJSON.FeatureCollection) ?? {
      type: "FeatureCollection",
      features: [],
    };
    const vectorsFC = (payload.vectors as GeoJSON.FeatureCollection) ?? {
      type: "FeatureCollection",
      features: [],
    };
    cellLayer.setData({ cells: cellsFC, cones: conesFC, vectors: vectorsFC });

    const cells: CellRow[] = (cellsFC.features ?? []).map((f) => {
      const p = f.properties ?? {};
      return {
        id: p.id,
        max_dbz: p.max_dbz,
        severity: p.severity,
        lightning_min: p.lightning_min ?? 0,
        trend: p.trend ?? "steady",
        eta_min: p.eta_min ?? null,
        flags: p.flags ?? [],
        speed_kmh: p.speed_kmh ?? null,
        bearing_deg: p.bearing_deg ?? null,
        deviation_deg: p.deviation_deg ?? null,
        sev_series: p.sev_series ?? [],
        label: p.label ?? `#${p.id}`,
        centroid: p.centroid as [number, number],
      };
    });

    const user = (payload.user as UserPos | null) ?? null;
    userLayer.setUser(user);

    const alerts = (payload.alerts_active as AlertMsg[]) ?? [];
    const ages = (payload.data_age_s as { radar: number | null; lightning: number | null }) ?? {
      radar: null,
      lightning: null,
    };
    store.setWorld({ cells, alerts, dataAges: ages, user });
  }

  private scheduleReconnect(): void {
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs);
    console.info(`[ws] reconnecting in ${delay}ms`);
    setTimeout(() => {
      if (!this.closedByUser) this.connect();
    }, delay);
  }

  send(type: string, payload: Record<string, unknown> = {}): void {
    const data = JSON.stringify({ type, payload });
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    } else {
      this.outbox.push(data);
    }
  }

  close(): void {
    this.closedByUser = true;
    this.ws?.close();
  }
}

export const liveSocket = new LiveSocket();
