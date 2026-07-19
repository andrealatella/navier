
interface WakeLockSentinelLike {
  released: boolean;
  release(): Promise<void>;
  addEventListener(type: "release", cb: () => void): void;
}
interface WakeLockNav {
  wakeLock?: { request(type: "screen"): Promise<WakeLockSentinelLike> };
}

let sentinel: WakeLockSentinelLike | null = null;
let wanted = false;

async function acquire(): Promise<void> {
  const wl = (navigator as unknown as WakeLockNav).wakeLock;
  if (!wanted || !wl || sentinel) return;
  try {
    sentinel = await wl.request("screen");
    sentinel.addEventListener("release", () => {
      sentinel = null;
    });
  } catch {
  }
}

function onVisibility(): void {
  if (document.visibilityState === "visible") void acquire();
}

export function setKeepAwake(on: boolean): void {
  if (on === wanted) return;
  wanted = on;
  if (on) {
    document.addEventListener("visibilitychange", onVisibility);
    void acquire();
  } else {
    document.removeEventListener("visibilitychange", onVisibility);
    void sentinel?.release().catch(() => {});
    sentinel = null;
  }
}
