import { create } from "zustand";

export type WSStatus = "connecting" | "open" | "closed";

export interface ServerMessage {
  type: string;
  payload: Record<string, unknown>;
}

export interface SourceHealth {
  name: string;
  state: "starting" | "ok" | "degraded" | "stopped" | "disabled";
  detail: string;
  age_s: number | null;
  events_total: number;
}

export interface RadarUiMeta {
  source: string | null;
  kind: "image" | "tiles" | null;
  attribution: string;
  frameTimes: number[];
}

export interface CellRow {
  id: number;
  max_dbz: number;
  severity: number;
  lightning_min: number;
  trend: string;
  eta_min: number | null;
  flags: string[];
  speed_kmh: number | null;
  bearing_deg: number | null;
  deviation_deg: number | null;
  sev_series: number[];
  label: string;
  centroid: [number, number];
}

export interface AlertMsg {
  id: string;
  rule_id: string;
  priority: 1 | 2 | 3;
  title: string;
  message: string;
  tts_text: string;
  created: number;
}

export interface DataAges {
  radar: number | null;
  lightning: number | null;
}

export interface CopilotMsg {
  id: string;
  role: "user" | "assistant" | "system";
  kind: "chat" | "alert" | "proactive" | "system" | "voice";
  reply: string;
  urgency: "info" | "caution" | "warning";
  speak: boolean;
  tts_text: string;
  ts: number;
}

export interface CopilotStatus {
  enabled: boolean;
  available: boolean;
  reason: string;
  busy: boolean;
  proactive: boolean;
  model: string;
  calls_today?: number;
  daily_limit?: number;
  quota_exhausted?: boolean;
  resumes_in_s?: number | null;
}

export interface SttStatus {
  enabled: boolean;
  available: boolean;
  listening: boolean;
  reason: string;
}

export interface RecorderStatus {
  available: boolean;
  recording: boolean;
  session: string | null;
  events: number;
  bytes: number;
}

export interface PlanningMeta {
  available: boolean;
  reason?: string;
  model: string;
  hour: string | null;
  hours: string[];
  hourIndex: number;
  maxCape: number;
  updatedMs: number | null;
}

export interface UserPos {
  lat: number;
  lon: number;
  speed_kmh: number | null;
  heading_deg: number | null;
  source: string;
}

export type RouteVerdict = "in_tempo" | "limite" | "tardi" | "si_allontana";

export interface RouteFeasibility {
  driveMin: number;
  cellMin: number;
  marginMin: number;
  verdict: RouteVerdict;
  text: string;
}

export type ViewLight = "controluce" | "laterale" | "illuminata" | "crepuscolo" | "notte";
export type ViewQuality = "buona" | "media" | "scarsa";

export interface RouteView {
  rainBlockedKm: number;
  rainMaxMmh: number;
  rainKnown: boolean;
  sunAzimuthDeg: number;
  sunElevationDeg: number;
  light: ViewLight;
  score: number;
  quality: ViewQuality;
  text: string;
}

export interface RouteInfo {
  provider: string;
  distanceKm: number;
  durationMin: number;
  cellId: number | null;
  intercept: boolean;
  note: string | null;
  crosses: number[];
  feasibility: RouteFeasibility | null;
  view: RouteView | null;
  dest: { lat: number; lon: number };
  mapsUrl: string;
}

interface AppState {
  wsStatus: WSStatus;
  serverVersion: string | null;
  replaying: boolean;
  sources: SourceHealth[];
  lightningCount: number;

  radar: RadarUiMeta;
  radarIndex: number;
  radarPlaying: boolean;
  radarOpacity: number;
  radarVisible: boolean;

  cells: CellRow[];
  alerts: AlertMsg[];
  alertHistory: AlertMsg[];
  dataAges: DataAges;
  user: UserPos | null;
  targetCellId: number | null;
  ttsEnabled: boolean;
  placingPosition: boolean;

  route: RouteInfo | null;
  routeError: string | null;
  routeLoading: boolean;
  interceptMode: boolean;
  chaseMode: boolean;

  copilotMessages: CopilotMsg[];
  copilotStatus: CopilotStatus;
  sttStatus: SttStatus;
  recorderStatus: RecorderStatus;

  planningOpen: boolean;
  meteoField: "cape" | "shear";
  planningMeta: PlanningMeta | null;
  allerteOn: boolean;

  reportOpen: boolean;
  alertLogOpen: boolean;

  setWsStatus: (s: WSStatus) => void;
  setServerVersion: (v: string) => void;
  setReplaying: (v: boolean) => void;
  setSourceHealth: (sources: SourceHealth[], lightningCount: number) => void;

  setRadarMeta: (meta: RadarUiMeta) => void;
  setRadarIndex: (i: number) => void;
  setRadarPlaying: (p: boolean) => void;
  setRadarOpacity: (o: number) => void;
  setRadarVisible: (v: boolean) => void;

  setWorld: (world: {
    cells: CellRow[];
    alerts: AlertMsg[];
    dataAges: DataAges;
    user: UserPos | null;
  }) => void;
  setTargetCellId: (id: number | null) => void;
  toggleTts: () => void;
  setPlacingPosition: (v: boolean) => void;

  setRoute: (r: RouteInfo | null) => void;
  setRouteError: (e: string | null) => void;
  setRouteLoading: (v: boolean) => void;
  setInterceptMode: (v: boolean) => void;
  setChaseMode: (v: boolean) => void;

  addCopilotMessage: (m: CopilotMsg) => void;
  setCopilotStatus: (s: CopilotStatus) => void;
  setSttStatus: (s: SttStatus) => void;
  setRecorderStatus: (s: RecorderStatus) => void;

  setPlanningOpen: (v: boolean) => void;
  setMeteoField: (f: "cape" | "shear") => void;
  setPlanningMeta: (m: PlanningMeta | null) => void;
  setAllerteOn: (v: boolean) => void;

  setReportOpen: (v: boolean) => void;
  setAlertLogOpen: (v: boolean) => void;
}

const ALERT_HISTORY_MAX = 200;

const COPILOT_STATUS_INIT: CopilotStatus = {
  enabled: false,
  available: false,
  reason: "in avvio",
  busy: false,
  proactive: false,
  model: "",
};

const STT_STATUS_INIT: SttStatus = {
  enabled: false,
  available: false,
  listening: false,
  reason: "in avvio",
};

const RECORDER_STATUS_INIT: RecorderStatus = {
  available: false,
  recording: false,
  session: null,
  events: 0,
  bytes: 0,
};

const COPILOT_MAX_MESSAGES = 60;

export const useStore = create<AppState>((set) => ({
  wsStatus: "connecting",
  serverVersion: null,
  replaying: false,
  sources: [],
  lightningCount: 0,

  radar: { source: null, kind: null, attribution: "", frameTimes: [] },
  radarIndex: 0,
  radarPlaying: true,
  radarOpacity: 0.8,
  radarVisible: true,

  cells: [],
  alerts: [],
  alertHistory: [],
  dataAges: { radar: null, lightning: null },
  user: null,
  targetCellId: null,
  ttsEnabled: true,
  placingPosition: false,

  route: null,
  routeError: null,
  routeLoading: false,
  interceptMode: true,
  chaseMode: false,

  copilotMessages: [],
  copilotStatus: COPILOT_STATUS_INIT,
  sttStatus: STT_STATUS_INIT,
  recorderStatus: RECORDER_STATUS_INIT,

  planningOpen: false,
  meteoField: "cape",
  planningMeta: null,
  allerteOn: false,

  reportOpen: false,
  alertLogOpen: false,

  setWsStatus: (s) => set({ wsStatus: s }),
  setServerVersion: (v) => set({ serverVersion: v }),
  setReplaying: (v) => set({ replaying: v }),
  setSourceHealth: (sources, lightningCount) => set({ sources, lightningCount }),

  setRadarMeta: (meta) =>
    set((state) => {
      const times = meta.frameTimes;
      if (!times.length) return { radar: meta, radarIndex: 0 };
      const prevTs = state.radar.frameTimes[state.radarIndex];
      const wasLiveEdge =
        state.radarIndex >= state.radar.frameTimes.length - 1 || state.radar.frameTimes.length === 0;
      let index = times.length - 1;
      if (!state.radarPlaying && !wasLiveEdge && prevTs != null) {
        const found = times.indexOf(prevTs);
        if (found >= 0) index = found;
      }
      return { radar: meta, radarIndex: index };
    }),
  setRadarIndex: (i) => set({ radarIndex: i }),
  setRadarPlaying: (p) => set({ radarPlaying: p }),
  setRadarOpacity: (o) => set({ radarOpacity: o }),
  setRadarVisible: (v) => set({ radarVisible: v }),

  setWorld: (world) =>
    set((s) => {
      const known = new Set(s.alertHistory.map((a) => a.id));
      const fresh = world.alerts.filter((a) => !known.has(a.id));
      const alertHistory = fresh.length
        ? [...s.alertHistory, ...fresh].slice(-ALERT_HISTORY_MAX)
        : s.alertHistory;
      return {
        cells: world.cells,
        alerts: world.alerts,
        alertHistory,
        dataAges: world.dataAges,
        user: world.user,
      };
    }),
  setTargetCellId: (id) => set({ targetCellId: id }),
  toggleTts: () => set((s) => ({ ttsEnabled: !s.ttsEnabled })),
  setPlacingPosition: (v) => set({ placingPosition: v }),

  setRoute: (r) => set({ route: r, routeError: null, routeLoading: false }),
  setRouteError: (e) => set({ routeError: e, routeLoading: false }),
  setRouteLoading: (v) => set({ routeLoading: v }),
  setInterceptMode: (v) => set({ interceptMode: v }),
  setChaseMode: (v) => set({ chaseMode: v }),

  addCopilotMessage: (m) =>
    set((s) => {
      if (s.copilotMessages.some((x) => x.id === m.id)) return s;
      const next = [...s.copilotMessages, m];
      return { copilotMessages: next.slice(-COPILOT_MAX_MESSAGES) };
    }),
  setCopilotStatus: (status) => set({ copilotStatus: status }),
  setSttStatus: (status) => set({ sttStatus: status }),
  setRecorderStatus: (status) => set({ recorderStatus: status }),

  setPlanningOpen: (v) => set({ planningOpen: v }),
  setMeteoField: (f) => set({ meteoField: f }),
  setPlanningMeta: (m) => set({ planningMeta: m }),
  setAllerteOn: (v) => set({ allerteOn: v }),

  setReportOpen: (v) => set({ reportOpen: v }),
  setAlertLogOpen: (v) => set({ alertLogOpen: v }),
}));
