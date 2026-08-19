const FIRMWARE_IDS = new Set(["10_sokkon", "99_stopwatch"]);
const ACTIONS = new Set(["mark", "mode", "focus", "wake"]);
const CONFIGURATION_KEYS = new Set([
  "connected",
  "outcome",
  "latency_ms",
  "context",
  "detail",
  "host_mode",
  "battery_percent",
  "charging",
  "time_scale",
]);

const HTTP_ADVANCE_ACTIONS = new Map([
  [6001, "advance_6s"],
  [30001, "advance_30s"],
  [120001, "advance_2m"],
  [600001, "advance_10m"],
]);

function nativeBridge() {
  if (typeof window === "undefined") return null;
  const bridge = window.m5stackSimulator;
  return bridge?.available === true ? bridge : null;
}

async function readError(response) {
  try {
    const body = await response.json();
    return body?.error?.message || body?.error?.code || response.statusText;
  } catch {
    return response.statusText;
  }
}

async function request(path, { timeout = 5000, ...options } = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    signal: AbortSignal.timeout(timeout),
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${await readError(response)}`.trim());
  }
  return response.status === 204 ? null : response.json();
}

function assertFirmware(firmware) {
  if (!FIRMWARE_IDS.has(firmware)) throw new Error(`Unsupported firmware: ${firmware}`);
}

function assertAction(action) {
  if (!ACTIONS.has(action)) throw new Error(`Unsupported action: ${action}`);
}

function assertConfiguration(configuration) {
  if (!configuration || typeof configuration !== "object" || Array.isArray(configuration)) {
    throw new Error("Configuration must be an object");
  }
  for (const key of Object.keys(configuration)) {
    if (!CONFIGURATION_KEYS.has(key)) throw new Error(`Unsupported configuration key: ${key}`);
  }
}

export const simulatorClient = {
  transport() {
    return nativeBridge() ? "native" : "http";
  },

  async firmwares() {
    const bridge = nativeBridge();
    if (!bridge) return request("/api/firmwares");
    const [capabilities, snapshot] = await Promise.all([
      bridge.capabilities(),
      bridge.snapshot(),
    ]);
    return {
      active: snapshot?.firmware?.id,
      firmwares: capabilities?.firmware ?? [],
    };
  },

  async snapshot() {
    const bridge = nativeBridge();
    return bridge ? bridge.snapshot() : request("/api/state", { timeout: 3000 });
  },

  async selectFirmware(firmware) {
    assertFirmware(firmware);
    const bridge = nativeBridge();
    return bridge
      ? bridge.selectFirmware(firmware)
      : request("/api/firmware", {
          method: "POST",
          body: JSON.stringify({ firmware }),
          timeout: 120000,
        });
  },

  async action(action) {
    assertAction(action);
    const bridge = nativeBridge();
    return bridge
      ? bridge.action(action)
      : request("/api/action", {
          method: "POST",
          body: JSON.stringify({ action }),
        });
  },

  async reset() {
    const bridge = nativeBridge();
    return bridge
      ? bridge.reset()
      : request("/api/action", {
          method: "POST",
          body: JSON.stringify({ action: "reset" }),
        });
  },

  async advance(milliseconds) {
    const numeric = Number(milliseconds);
    if (!Number.isInteger(numeric) || numeric <= 0) throw new Error("Advance must be a positive integer");
    const bridge = nativeBridge();
    if (bridge) return bridge.advance(numeric);
    const action = HTTP_ADVANCE_ACTIONS.get(numeric);
    if (!action) throw new Error(`Unsupported HTTP advance: ${numeric} ms`);
    return request("/api/action", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
  },

  async configure(configuration) {
    assertConfiguration(configuration);
    const bridge = nativeBridge();
    if (!bridge) {
      return request("/api/scenario", {
        method: "POST",
        body: JSON.stringify(configuration),
      });
    }

    let snapshot = null;
    for (const [key, value] of Object.entries(configuration)) {
      snapshot = await bridge.configure(key, value);
    }
    return snapshot ?? bridge.snapshot();
  },

  subscribe(onSnapshot, onReady) {
    if (typeof window === "undefined") return () => {};
    const handleSnapshot = (event) => onSnapshot?.(event.detail);
    const handleReady = () => onReady?.();
    window.addEventListener("m5stack-simulator-snapshot", handleSnapshot);
    window.addEventListener("m5stack-simulator-ready", handleReady);
    return () => {
      window.removeEventListener("m5stack-simulator-snapshot", handleSnapshot);
      window.removeEventListener("m5stack-simulator-ready", handleReady);
    };
  },
};
