import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  BatteryMedium,
  Camera,
  CaretDown,
  CheckCircle,
  CircleNotch,
  Crosshair,
  DeviceMobile,
  DownloadSimple,
  Funnel,
  Gauge,
  GearSix,
  Hammer,
  HandTap,
  Lightning,
  ListBullets,
  MagnifyingGlass,
  Monitor,
  Palette,
  Pause,
  Play,
  Plus,
  Power,
  Pulse,
  Stop,
  TerminalWindow,
  WarningCircle,
} from "@phosphor-icons/react";
import { simulatorClient } from "./simulatorClient.js";
import { createNativeLogWatermark, latestOrderedEvents, nativeLogKeys, nativeLogsAfterWatermark } from "./timeline.js";

const FALLBACK_FIRMWARES = [
  { id: "10_sokkon", label: "SOKKON" },
  { id: "99_stopwatch", label: "STOPWATCH" },
];

const DEMO_SNAPSHOT = {
  revision: 17,
  firmware: {
    id: "99_stopwatch",
    label: "STOPWATCH",
    subtitle: "PRODUCTION C++",
    primary_label: "START / PAUSE",
    secondary_label: "RESET",
    touch_label: "START / PAUSE",
    state_semantics: "stopwatch",
  },
  frame: {
    width: 466,
    height: 466,
    brightness: 96,
    commands: [
      { op: "fillScreen", color: 0 },
      { op: "drawCircle", x: 233, y: 233, r: 230, color: 8484 },
      { op: "drawCircle", x: 233, y: 233, r: 224, color: 6371 },
      { op: "drawArc", x: 233, y: 233, outer_radius: 214, inner_radius: 204, start: 8, end: 344, color: 2047 },
      { op: "drawString", text: "RUNNING", x: 233, y: 74, font: "Font2", font_size: 16, datum: "middle_center", color: 2047 },
      { op: "drawString", text: "00:03:07.84", x: 233, y: 219, font: "FreeSansBold24pt7b", font_size: 48, datum: "middle_center", color: 65535 },
      { op: "drawString", text: "A / TOUCH  start / pause", x: 233, y: 295, font: "Font2", font_size: 16, datum: "middle_center", color: 54938 },
      { op: "drawString", text: "B          reset", x: 233, y: 321, font: "Font2", font_size: 16, datum: "middle_center", color: 54938 },
      { op: "drawString", text: "12:37:30  BAT 84%", x: 233, y: 371, font: "Font2", font_size: 16, datum: "middle_center", color: 2047 },
      { op: "drawString", text: "IMU tilt  X+0.12  Y-0.08", x: 233, y: 401, font: "Font2", font_size: 16, datum: "middle_center", color: 31727 },
      { op: "fillCircle", x: 65, y: 233, r: 9, color: 65504 },
      { op: "fillCircle", x: 401, y: 233, r: 9, color: 31 },
    ],
  },
  screen: {
    status: "NATIVE",
    battery_percent: 84,
    charging: false,
    brightness: 96,
    sleeping: false,
    time: "12:37:30",
    mode: "STOPWATCH",
    focus_running: true,
    elapsed_ms: 187840,
    elapsed_text: "00:03:07.84",
  },
  scenario: { battery_percent: 84, charging: false, time_scale: 1 },
  haptic: { active: false, intensity: 0, pulses: 1, label: "IDLE" },
  log: [
    { time: "12:37:27.102", kind: "BUILD", message: "Build succeeded", detail: "3.182 s" },
    { time: "12:37:27.345", kind: "BOOT", message: "Device boot", detail: "842 ms" },
    { time: "12:37:29.880", kind: "INPUT", message: "Button A pressed", detail: "A" },
    { time: "12:37:29.881", kind: "DRAW", message: "Frame rendered", detail: "468 Hz" },
    { time: "12:37:29.882", kind: "HAPTIC", message: "Short vibration", detail: "20 ms" },
  ],
};

const FILTERS = ["All", "Build", "Boot", "Input", "Draw", "Haptic", "System"];

function clamp(value, minimum, maximum) {
  const numeric = Number(value);
  return Math.min(maximum, Math.max(minimum, Number.isFinite(numeric) ? numeric : minimum));
}

function safeText(value, fallback = "") {
  return value === null || value === undefined ? fallback : String(value);
}

function colorValue(value, fallback = "#ffffff") {
  if (typeof value === "string") {
    if (/^#[0-9a-f]{3,8}$/i.test(value)) return value;
    const named = {
      TFT_BLACK: "#000000",
      TFT_WHITE: "#ffffff",
      TFT_RED: "#ff453a",
      TFT_GREEN: "#32d74b",
      TFT_BLUE: "#0a84ff",
      TFT_YELLOW: "#ffd60a",
      TFT_CYAN: "#2ee8f2",
      TFT_MAGENTA: "#ff5ce8",
      TFT_ORANGE: "#ff9f0a",
      TFT_DARKGREY: "#636366",
      TFT_LIGHTGREY: "#d1d1d6",
    };
    if (named[value.toUpperCase()]) return named[value.toUpperCase()];
    const numeric = Number(value);
    return Number.isFinite(numeric) ? colorValue(numeric, fallback) : fallback;
  }
  if (!Number.isFinite(Number(value))) return fallback;
  const numeric = Math.max(0, Math.trunc(Number(value)));
  if (numeric <= 0xffff) {
    const red = Math.round(((numeric >> 11) & 0x1f) * 255 / 31);
    const green = Math.round(((numeric >> 5) & 0x3f) * 255 / 63);
    const blue = Math.round((numeric & 0x1f) * 255 / 31);
    return `rgb(${red}, ${green}, ${blue})`;
  }
  return `#${Math.min(numeric, 0xffffff).toString(16).padStart(6, "0")}`;
}

function commandName(command) {
  return safeText(Array.isArray(command) ? command[0] : command?.op ?? command?.type ?? command?.command)
    .replaceAll("_", "")
    .replaceAll("-", "")
    .toLowerCase();
}

function commandField(command, names, index, fallback) {
  if (Array.isArray(command) && command[index + 1] !== undefined) return command[index + 1];
  for (const name of names) if (command?.[name] !== undefined) return command[name];
  if (Array.isArray(command?.args) && command.args[index] !== undefined) return command.args[index];
  return fallback;
}

function applyTextDatum(context, datum) {
  const normalized = safeText(datum, "middle_center").toLowerCase();
  context.textAlign = normalized.includes("left") ? "left" : normalized.includes("right") ? "right" : "center";
  context.textBaseline = normalized.includes("top") ? "top" : normalized.includes("bottom") ? "bottom" : "middle";
}

function roundedRectangle(context, x, y, width, height, radius) {
  context.beginPath();
  if (typeof context.roundRect === "function") {
    context.roundRect(x, y, width, height, radius);
  } else {
    context.rect(x, y, width, height);
  }
}

function FirmwareCanvas({ frame, screen, canvasRef, onPress }) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d", { alpha: false });
    const commands = Array.isArray(frame?.commands) ? frame.commands : [];
    const width = Math.max(1, Number(frame?.width) || 466);
    const height = Math.max(1, Number(frame?.height) || 466);
    const renderState = { color: "#ffffff", background: "#000000", font: "Font2", datum: "middle_center" };

    context.save();
    context.setTransform(466 / width, 0, 0, 466 / height, 0, 0);
    context.fillStyle = "#000000";
    context.fillRect(0, 0, width, height);
    context.lineJoin = "round";

    for (const command of commands) {
      const name = commandName(command);
      if (name === "settextcolor") {
        renderState.color = colorValue(commandField(command, ["color", "foreground", "fg"], 0), renderState.color);
        renderState.background = colorValue(commandField(command, ["background", "bg"], 1), renderState.background);
        continue;
      }
      if (name === "setfont") {
        renderState.font = commandField(command, ["font", "value"], 0, renderState.font);
        continue;
      }
      if (name === "settextdatum") {
        renderState.datum = commandField(command, ["datum", "value"], 0, renderState.datum);
        continue;
      }
      if (name === "fillscreen") {
        context.fillStyle = colorValue(commandField(command, ["color"], 0), "#000000");
        context.fillRect(0, 0, width, height);
        continue;
      }
      if (name === "drawcircle" || name === "fillcircle") {
        const x = Number(commandField(command, ["x", "cx"], 0, 0));
        const y = Number(commandField(command, ["y", "cy"], 1, 0));
        const radius = Math.max(0, Number(commandField(command, ["r", "radius"], 2, 0)));
        const color = colorValue(commandField(command, ["color"], 3), renderState.color);
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        if (name === "fillcircle") {
          context.fillStyle = color;
          context.fill();
        } else {
          context.strokeStyle = color;
          context.lineWidth = Math.max(1, Number(commandField(command, ["line_width"], 4, 1)));
          context.stroke();
        }
        continue;
      }
      if (name === "drawarc") {
        const x = Number(commandField(command, ["x", "cx"], 0, 0));
        const y = Number(commandField(command, ["y", "cy"], 1, 0));
        const outer = Number(commandField(command, ["outer_radius", "outer_r", "r1"], 2, 0));
        const inner = Number(commandField(command, ["inner_radius", "inner_r", "r2"], 3, 0));
        const start = Number(commandField(command, ["start", "start_angle"], 4, 0));
        let end = Number(commandField(command, ["end", "end_angle"], 5, 0));
        if (end < start) end += 360;
        context.beginPath();
        context.arc(x, y, (outer + inner) / 2, (start - 90) * Math.PI / 180, (end - 90) * Math.PI / 180);
        context.strokeStyle = colorValue(commandField(command, ["color"], 6), renderState.color);
        context.lineWidth = Math.max(1, Math.abs(outer - inner) + 1);
        context.stroke();
        continue;
      }
      if (name === "fillroundrect") {
        const x = Number(commandField(command, ["x"], 0, 0));
        const y = Number(commandField(command, ["y"], 1, 0));
        const widthValue = Number(commandField(command, ["width", "w"], 2, 0));
        const heightValue = Number(commandField(command, ["height", "h"], 3, 0));
        roundedRectangle(context, x, y, widthValue, heightValue, Number(commandField(command, ["radius", "r"], 4, 0)));
        context.fillStyle = colorValue(commandField(command, ["color"], 5), renderState.color);
        context.fill();
        continue;
      }
      if (name === "drawstring") {
        const text = safeText(commandField(command, ["text", "value"], 0, ""));
        const x = Number(commandField(command, ["x"], 1, 0));
        const y = Number(commandField(command, ["y"], 2, 0));
        const fontName = safeText(commandField(command, ["font"], -1, renderState.font));
        const fontSize = Math.max(6, Number(commandField(command, ["font_size", "size_px"], -1, /24pt/i.test(fontName) ? 48 : 16)) || 16);
        context.save();
        context.font = `${/bold/i.test(fontName) ? 750 : 600} ${fontSize}px ui-rounded, -apple-system, BlinkMacSystemFont, sans-serif`;
        applyTextDatum(context, commandField(command, ["datum", "text_datum"], -1, renderState.datum));
        context.fillStyle = colorValue(commandField(command, ["color", "foreground"], 3), renderState.color);
        context.fillText(text, x, y);
        context.restore();
      }
    }
    context.restore();
  }, [canvasRef, frame]);

  const brightness = clamp(screen?.brightness ?? frame?.brightness ?? 100, 0, 100) / 100;
  return (
    <button className="screen-button" type="button" onClick={onPress} aria-label="Simulate center touch">
      <canvas
        ref={canvasRef}
        className="firmware-canvas"
        width="466"
        height="466"
        style={{ opacity: screen?.sleeping ? 0 : brightness }}
        aria-hidden="true"
      />
      <span className="sr-only">Live C152 firmware display. Press to simulate touch.</span>
    </button>
  );
}

function ToolbarButton({ icon: Icon, label, disabled = false, active = false, onClick }) {
  return (
    <button className={`toolbar-button${active ? " is-active" : ""}`} type="button" disabled={disabled} onClick={onClick} title={label}>
      <Icon size={23} weight={active ? "fill" : "regular"} aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}

function formatFirmwareLabel(firmware) {
  if (firmware.id === "10_sokkon") return "10_sokkon";
  if (firmware.id === "99_stopwatch") return "99_stopwatch";
  return firmware.id;
}

function formatVirtualTime(value) {
  if (typeof value === "string") return value;
  const milliseconds = Math.max(0, Number(value) || 0);
  const totalSeconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const fraction = String(Math.floor(milliseconds % 1000)).padStart(3, "0");
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${fraction}`;
}

function eventCategory(kind, message) {
  const value = `${kind} ${message}`.toUpperCase();
  if (value.includes("BUILD")) return "Build";
  if (value.includes("BOOT") || value.includes("SERIAL")) return "Boot";
  if (value.includes("INPUT") || value.includes("BUTTON") || value.includes("TOUCH")) return "Input";
  if (value.includes("DRAW") || value.includes("FRAME")) return "Draw";
  if (value.includes("HAPTIC") || value.includes("VIBR")) return "Haptic";
  return "System";
}

function eventIcon(category) {
  if (category === "Build") return CheckCircle;
  if (category === "Boot") return Power;
  if (category === "Input") return HandTap;
  if (category === "Draw") return Palette;
  if (category === "Haptic") return Pulse;
  return TerminalWindow;
}

function eventTime(value) {
  if (typeof value === "string") return value;
  if (Number(value) < 1e12) return formatVirtualTime(value).slice(3);
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "--:--:--" : date.toLocaleTimeString([], { hour12: false });
}

function Switch({ checked, onChange, label }) {
  return (
    <button className={`switch${checked ? " is-on" : ""}`} role="switch" aria-checked={checked} aria-label={label} type="button" onClick={() => onChange(!checked)}>
      <span />
    </button>
  );
}

function SectionHeading({ children }) {
  return (
    <div className="inspector-section-heading">
      <span>{children}</span>
      <i />
    </div>
  );
}

export function App() {
  const nativeTransport = simulatorClient.transport() === "native";
  const canvasRef = useRef(null);
  const inspectorSectionRefs = useRef({});
  const snapshotRef = useRef(DEMO_SNAPSHOT);
  const hasLiveSnapshot = useRef(false);
  const pollInFlight = useRef(false);
  const timelineOrderRef = useRef(0);
  const nativeEventOrdersRef = useRef(new Map());
  const [snapshot, setSnapshot] = useState(DEMO_SNAPSHOT);
  const [connection, setConnection] = useState("connecting");
  const [firmwares, setFirmwares] = useState(FALLBACK_FIRMWARES);
  const [activeFirmware, setActiveFirmware] = useState("99_stopwatch");
  const [selectedFirmware, setSelectedFirmware] = useState("99_stopwatch");
  const [firmwareQuery, setFirmwareQuery] = useState("");
  const [activeFirmwareOnly, setActiveFirmwareOnly] = useState(false);
  const [rightTab, setRightTab] = useState("Inspector");
  const [inspectorSection, setInspectorSection] = useState("Inputs");
  const [timelineFilter, setTimelineFilter] = useState("All");
  const [nativeLogCutoff, setNativeLogCutoff] = useState(null);
  const [clearEpoch, setClearEpoch] = useState(0);
  const [localEvents, setLocalEvents] = useState([]);
  const [build, setBuild] = useState(() => nativeTransport
    ? { phase: "succeeded", seconds: 0, message: "Bundled Firmware Ready" }
    : { phase: "succeeded", seconds: 3.182, message: "Build Succeeded" });
  const [pendingControl, setPendingControl] = useState("");
  const [batteryDraft, setBatteryDraft] = useState(84);
  const [timeScaleDraft, setTimeScaleDraft] = useState(1);

  const observeNativeLog = useCallback((next) => {
    const firmwareID = safeText(next?.firmware?.id);
    const keys = nativeLogKeys(next?.log).map((key) => `${firmwareID}\u0000${key}`);
    for (const key of keys) {
      if (!nativeEventOrdersRef.current.has(key)) {
        timelineOrderRef.current += 1;
        nativeEventOrdersRef.current.set(key, timelineOrderRef.current);
      }
    }
    return keys;
  }, []);

  const beginNativeGeneration = useCallback(() => {
    nativeEventOrdersRef.current.clear();
    setNativeLogCutoff(null);
  }, []);

  const applySnapshot = useCallback((next) => {
    if (!next || typeof next !== "object" || !next.firmware || !next.frame) return;
    const previous = snapshotRef.current;
    if (previous?.firmware?.id !== next.firmware.id
      || Number(next.revision) < Number(previous?.revision)) {
      beginNativeGeneration();
    }
    observeNativeLog(next);
    snapshotRef.current = next;
    hasLiveSnapshot.current = true;
    setSnapshot(next);
    setActiveFirmware(next.firmware.id);
    setConnection("live");
  }, [beginNativeGeneration, observeNativeLog]);

  const pushLocalEvent = useCallback((kind, message, detail = "") => {
    timelineOrderRef.current += 1;
    const order = timelineOrderRef.current;
    setLocalEvents((events) => [...events.slice(-30), { time: Date.now(), kind, message, detail, order }]);
  }, []);

  const refreshFirmwares = useCallback(async () => {
    try {
      const response = await simulatorClient.firmwares();
      if (!Array.isArray(response?.firmwares) || !response.firmwares.length) throw new Error("Empty firmware registry");
      setFirmwares(response.firmwares);
      if (response.active) {
        setActiveFirmware(response.active);
        setSelectedFirmware(response.active);
      }
    } catch {
      setFirmwares(FALLBACK_FIRMWARES);
    }
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer = 0;

    async function poll() {
      if (stopped || pollInFlight.current || document.hidden) {
        timer = window.setTimeout(poll, 300);
        return;
      }
      pollInFlight.current = true;
      try {
        const next = await simulatorClient.snapshot();
        if (!stopped) applySnapshot(next);
      } catch {
        if (!stopped && !hasLiveSnapshot.current) {
          snapshotRef.current = DEMO_SNAPSHOT;
          setSnapshot(DEMO_SNAPSHOT);
          setConnection("demo");
        } else if (!stopped) {
          setConnection("error");
        }
      } finally {
        pollInFlight.current = false;
        if (!stopped) timer = window.setTimeout(poll, hasLiveSnapshot.current ? 120 : 1600);
      }
    }

    refreshFirmwares();
    poll();
    const unsubscribe = simulatorClient.subscribe(applySnapshot, () => {
      refreshFirmwares();
      poll();
    });
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      unsubscribe();
    };
  }, [applySnapshot, refreshFirmwares]);

  useEffect(() => {
    if (document.activeElement?.id !== "battery-range") {
      setBatteryDraft(clamp(snapshot.scenario?.battery_percent ?? snapshot.screen?.battery_percent ?? 84, 0, 100));
    }
    if (document.activeElement?.id !== "time-scale-range") {
      setTimeScaleDraft(clamp(snapshot.scenario?.time_scale ?? 1, 0.01, 1000));
    }
  }, [snapshot]);

  const sendAction = useCallback(async (action, label) => {
    if (pendingControl) return;
    setPendingControl(action);
    try {
      const next = action === "reset" ? await simulatorClient.reset() : await simulatorClient.action(action);
      if (action === "reset") beginNativeGeneration();
      applySnapshot(next);
      pushLocalEvent("INPUT", label, action.toUpperCase());
    } catch (error) {
      setConnection(hasLiveSnapshot.current ? "error" : "demo");
      pushLocalEvent("SYSTEM", `${label} failed`, safeText(error.message, "Backend unavailable"));
    } finally {
      setPendingControl("");
    }
  }, [applySnapshot, beginNativeGeneration, pendingControl, pushLocalEvent]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.repeat || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.target instanceof HTMLElement && event.target.matches("input, textarea, select, button")) return;
      if (event.key.toLowerCase() === "a") {
        event.preventDefault();
        sendAction("mark", "Button A pressed");
      } else if (event.key.toLowerCase() === "b") {
        event.preventDefault();
        sendAction("mode", "Button B pressed");
      } else if (event.code === "Space") {
        event.preventDefault();
        sendAction("focus", "Screen touched");
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [sendAction]);

  const switchFirmware = useCallback(async () => {
    if (build.phase === "building") return;
    const restartBundledFirmware = simulatorClient.transport() === "native";
    const started = performance.now();
    setBuild({
      phase: "building",
      seconds: 0,
      message: restartBundledFirmware ? "Restarting Bundled Firmware" : "Building Native Firmware",
    });
    pushLocalEvent(
      restartBundledFirmware ? "BOOT" : "BUILD",
      restartBundledFirmware ? `Restarting ${selectedFirmware}` : `Building ${selectedFirmware}`,
      restartBundledFirmware ? "Bundled runner" : "C++",
    );
    try {
      const next = await simulatorClient.selectFirmware(selectedFirmware);
      const seconds = (performance.now() - started) / 1000;
      beginNativeGeneration();
      applySnapshot(next);
      setActiveFirmware(selectedFirmware);
      setBuild({
        phase: "succeeded",
        seconds,
        message: restartBundledFirmware ? "Firmware Restarted" : "Build Succeeded",
      });
      pushLocalEvent(
        restartBundledFirmware ? "BOOT" : "BUILD",
        restartBundledFirmware ? "Bundled firmware restarted" : "Build succeeded",
        `${seconds.toFixed(3)} s`,
      );
      await refreshFirmwares();
    } catch (error) {
      setBuild({
        phase: "failed",
        seconds: (performance.now() - started) / 1000,
        message: restartBundledFirmware ? "Firmware Restart Failed" : "Build Failed",
      });
      pushLocalEvent("SYSTEM", restartBundledFirmware ? "Firmware restart failed" : "Build failed", safeText(error.message));
    }
  }, [applySnapshot, beginNativeGeneration, build.phase, pushLocalEvent, refreshFirmwares, selectedFirmware]);

  const configure = useCallback(async (configuration, label) => {
    setPendingControl(`configure:${label}`);
    try {
      const next = await simulatorClient.configure(configuration);
      applySnapshot(next);
      pushLocalEvent("SYSTEM", label, "Scenario updated");
    } catch (error) {
      pushLocalEvent("SYSTEM", `${label} failed`, safeText(error.message));
    } finally {
      setPendingControl("");
    }
  }, [applySnapshot, pushLocalEvent]);

  const advanceTime = useCallback(async (milliseconds, label) => {
    setPendingControl(`advance:${milliseconds}`);
    try {
      const next = await simulatorClient.advance(milliseconds);
      applySnapshot(next);
      pushLocalEvent("SYSTEM", `Time advanced ${label}`, `${milliseconds} ms`);
    } catch (error) {
      pushLocalEvent("SYSTEM", "Virtual time failed", safeText(error.message));
    } finally {
      setPendingControl("");
    }
  }, [applySnapshot, pushLocalEvent]);

  const downloadScreenshot = useCallback(async () => {
    const screenCanvas = canvasRef.current;
    if (!screenCanvas) return;
    const output = document.createElement("canvas");
    output.width = 1000;
    output.height = 1000;
    const context = output.getContext("2d");
    context.fillStyle = "#070a0c";
    context.fillRect(0, 0, 1000, 1000);
    const shell = new Image();
    shell.src = "/device-shell.png";
    await shell.decode();
    context.drawImage(shell, -165, -165, 1330, 1330);
    context.save();
    context.beginPath();
    context.arc(500, 500, 409, 0, Math.PI * 2);
    context.clip();
    context.drawImage(screenCanvas, 91, 91, 818, 818);
    context.restore();
    const link = document.createElement("a");
    link.download = `${snapshot.firmware.id}-simulator.png`;
    link.href = output.toDataURL("image/png");
    link.click();
    pushLocalEvent("SYSTEM", "Screenshot saved", link.download);
  }, [pushLocalEvent, snapshot.firmware.id]);

  const visibleFirmwares = useMemo(() => {
    const query = firmwareQuery.trim().toLowerCase();
    return firmwares.filter((item) => {
      const matchesQuery = !query || `${item.id} ${item.label}`.toLowerCase().includes(query);
      return matchesQuery && (!activeFirmwareOnly || item.id === activeFirmware);
    });
  }, [activeFirmware, activeFirmwareOnly, firmwareQuery, firmwares]);

  const screen = snapshot.screen ?? {};
  const scenario = snapshot.scenario ?? {};
  const firmware = snapshot.firmware ?? DEMO_SNAPSHOT.firmware;
  const isRunning = Boolean(screen.focus_running);
  const isNative = nativeTransport;
  const registryFirmware = firmwares.find((item) => item.id === selectedFirmware) ?? firmwares[0];
  const statusLabel = connection === "live" ? "LIVE" : connection === "connecting" ? "CONNECTING" : connection === "demo" ? "DEMO DATA" : "RECONNECTING";
  const battery = clamp(batteryDraft, 0, 100);
  const charging = Boolean(scenario.charging ?? screen.charging);
  const virtualTimeEnabled = timeScaleDraft > 0.01;
  const imuText = snapshot.frame?.commands?.find((command) => commandName(command) === "drawstring" && safeText(command.text).startsWith("IMU tilt"))?.text ?? "IMU tilt  X+0.12  Y-0.08";
  const imuMatch = imuText.match(/X([+-]?\d+(?:\.\d+)?)\s+Y([+-]?\d+(?:\.\d+)?)/i);
  const imu = { x: imuMatch?.[1] ?? "+0.12", y: imuMatch?.[2] ?? "-0.08", z: "+0.98" };

  const nativeEvents = useMemo(() => {
    const fullLog = Array.isArray(snapshot.log) ? snapshot.log : [];
    const visibleLog = nativeLogsAfterWatermark(snapshot, nativeLogCutoff);
    const allKeys = observeNativeLog(snapshot);
    const visibleKeys = allKeys.slice(Math.max(0, fullLog.length - visibleLog.length));
    return visibleLog.map((entry, index) => ({
      time: entry.time ?? entry.timestamp ?? index,
      kind: safeText(entry.kind ?? entry.type, "SYSTEM"),
      message: safeText(entry.message ?? entry.line ?? entry.event, "Event"),
      detail: safeText(entry.detail, ""),
      order: nativeEventOrdersRef.current.get(visibleKeys[index]) ?? 0,
    }));
  }, [nativeLogCutoff, observeNativeLog, snapshot]);

  const timelineEvents = useMemo(() => {
    const categorized = [...nativeEvents, ...localEvents.filter((event) => event.time > clearEpoch)]
      .map((event) => ({ ...event, category: eventCategory(event.kind, event.message) }))
      .filter((event) => timelineFilter === "All" || event.category === timelineFilter);
    return latestOrderedEvents(categorized, 7);
  }, [clearEpoch, localEvents, nativeEvents, timelineFilter]);

  const clearTimeline = () => {
    setNativeLogCutoff(createNativeLogWatermark(snapshot));
    setClearEpoch(Date.now());
  };

  const selectInspectorSection = (section) => {
    setInspectorSection(section);
    inspectorSectionRefs.current[section]?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  return (
    <div className={`app-window${isNative ? " is-native-shell" : ""}`} data-transport={isNative ? "native" : "http"}>
      <header className="app-toolbar">
        <div className="titlebar-safe" aria-hidden="true" />
        <h1>M5Stack Simulator</h1>
        <nav className="toolbar-actions" aria-label="Simulator controls">
          <ToolbarButton icon={Hammer} label={isNative ? "Restart FW" : "Build"} onClick={switchFirmware} disabled={build.phase === "building"} />
          <ToolbarButton icon={isRunning ? Pause : Play} label="Run / Pause" active={isRunning} onClick={() => sendAction("focus", "Run / Pause")} />
          <ToolbarButton icon={Stop} label="Stop" disabled={!isRunning} onClick={() => sendAction("focus", "Device stopped")} />
          <ToolbarButton icon={ArrowClockwise} label="Restart" onClick={() => sendAction("reset", "Device restarted")} />
          <span className="toolbar-divider" />
          <ToolbarButton icon={DownloadSimple} label="Install to Device" disabled />
          <ToolbarButton icon={Camera} label="Screenshot" onClick={downloadScreenshot} />
        </nav>
        <div className="toolbar-device">
          <button type="button" className="device-picker" title="C152 is the only allowlisted simulator target" disabled>
            <span className={`status-dot ${connection}`} />
            C152
            <CaretDown size={14} aria-hidden="true" />
          </button>
          <button type="button" className="icon-button" title="Open system inspector" aria-label="Simulator settings" onClick={() => { setRightTab("Inspector"); selectInspectorSection("System"); }}>
            <GearSix size={24} aria-hidden="true" />
          </button>
        </div>
      </header>

      <div className="workspace">
        <aside className="firmware-rail" aria-label="Firmware library">
          <section className="firmware-library">
            <h2>Firmware</h2>
            <div className="firmware-search-row">
              <label className="search-field">
                <MagnifyingGlass size={17} aria-hidden="true" />
                <span className="sr-only">Search firmware</span>
                <input value={firmwareQuery} onChange={(event) => setFirmwareQuery(event.target.value)} placeholder="Search firmware" />
              </label>
              <button className={`square-button${activeFirmwareOnly ? " is-active" : ""}`} type="button" title="Show only the running firmware" aria-label="Filter firmware" aria-pressed={activeFirmwareOnly} onClick={() => setActiveFirmwareOnly((value) => !value)}>
                <Funnel size={18} aria-hidden="true" />
              </button>
            </div>

            <div className="firmware-list">
              {visibleFirmwares.map((item) => {
                const selected = item.id === selectedFirmware;
                const active = item.id === activeFirmware;
                return (
                  <button
                    className={`firmware-item${selected ? " is-selected" : ""}`}
                    type="button"
                    key={item.id}
                    onClick={() => setSelectedFirmware(item.id)}
                    aria-pressed={selected}
                  >
                    <span className="firmware-item-copy">
                      <strong>{formatFirmwareLabel(item)}</strong>
                      <small>C++ <b>·</b> {active ? "Running now" : item.id === "10_sokkon" ? "2 days ago" : "Just now"}</small>
                    </span>
                    <span className={`firmware-indicator${active ? " is-active" : ""}`} title={active ? "Active firmware" : "Ready"} />
                  </button>
                );
              })}
            </div>

            <button className="add-firmware" type="button" disabled title="Add firmware from the repository">
              <Plus size={17} aria-hidden="true" />
              Add Firmware
            </button>
          </section>

          <section className="build-panel">
            <h2>{isNative ? "Bundled Firmware" : "Build & Run"}</h2>
            <div className="build-primary-row">
              <button className="build-primary" type="button" onClick={switchFirmware} disabled={build.phase === "building"}>
                {build.phase === "building" ? <CircleNotch className="spin" size={20} aria-hidden="true" /> : <Play size={20} weight="fill" aria-hidden="true" />}
                <span>{build.phase === "building" ? (isNative ? "Restarting…" : "Building…") : (isNative ? "Restart Firmware" : "Build & Run")}</span>
              </button>
              <button className="build-menu" type="button" title="Build options are fixed for the allowlisted native target" aria-label="Build options" disabled>
                <CaretDown size={17} aria-hidden="true" />
              </button>
            </div>

            <article className={`build-card is-${build.phase}`}>
              <div className="build-card-title">
                {build.phase === "building" ? <CircleNotch className="spin" size={20} /> : build.phase === "failed" ? <WarningCircle size={20} /> : <CheckCircle size={20} weight="fill" />}
                <strong>{build.message}</strong>
                <time>{build.phase === "building" ? "Now" : "Just now"}</time>
              </div>
              <dl>
                <div><dt>Target</dt><dd>C152 (ESP32-S3)</dd></div>
                <div><dt>Firmware</dt><dd>{registryFirmware?.id ?? selectedFirmware}</dd></div>
                <div><dt>Runtime</dt><dd>{isNative ? "Bundled native runner" : "Apple Clang / native HAL"}</dd></div>
                <div><dt>{isNative ? "Restart Time" : "Build Time"}</dt><dd>{build.seconds ? `${build.seconds.toFixed(3)} s` : "—"}</dd></div>
              </dl>
              <button type="button" onClick={() => setRightTab("Logs")}>View Output</button>
            </article>
          </section>
        </aside>

        <main className="device-stage">
          <div className="stage-meta">
            <div><span className="status-dot live" /> Device <strong>C152</strong> <CaretDown size={13} aria-hidden="true" /></div>
            <div><span className={`status-dot ${connection}`} /> {statusLabel} <strong>{connection === "live" ? "120 ms" : "—"}</strong></div>
          </div>

          <div className="device-visual" data-testid="device-visual">
            <img src="/device-shell.png" className="device-shell-raster" alt="" draggable="false" />
            <div className="device-screen">
              <FirmwareCanvas frame={snapshot.frame} screen={screen} canvasRef={canvasRef} onPress={() => sendAction("focus", "Screen touched")} />
            </div>
            <button className="hardware-hit hardware-a" type="button" onClick={() => sendAction("mark", "Button A pressed")} aria-label={`Button A: ${firmware.primary_label ?? "Primary action"}`} />
            <button className="hardware-hit hardware-b" type="button" onClick={() => sendAction("mode", "Button B pressed")} aria-label={`Button B: ${firmware.secondary_label ?? "Secondary action"}`} />
          </div>

          <div className="stage-caption" aria-live="polite">
            <span>{firmware.id}</span>
            <b>{safeText(screen.elapsed_text, "00:00:00.00")}</b>
            <small>{connection === "demo" ? "Static preview · connect the simulator backend to interact" : "Compiled production C++ · live native state"}</small>
          </div>
        </main>

        <aside className="inspector-panel" aria-label="Simulator inspector">
          <div className="right-tabs" role="tablist" aria-label="Inspector views">
            {["Inspector", "Device", "Logs"].map((tab) => (
              <button key={tab} type="button" role="tab" aria-selected={rightTab === tab} className={rightTab === tab ? "is-active" : ""} onClick={() => setRightTab(tab)}>{tab}</button>
            ))}
          </div>

          {rightTab === "Inspector" && (
            <div className="inspector-layout">
              <nav className="inspector-nav" aria-label="Inspector sections">
                {[
                  ["Inputs", HandTap],
                  ["Display", Monitor],
                  ["System", GearSix],
                ].map(([label, Icon]) => (
                  <button key={label} type="button" className={inspectorSection === label ? "is-active" : ""} onClick={() => selectInspectorSection(label)}>
                    <Icon size={19} aria-hidden="true" />
                    {label}
                  </button>
                ))}
              </nav>

              <div className="inspector-scroll">
                <section ref={(node) => { inspectorSectionRefs.current.Inputs = node; }}>
                  <SectionHeading>Inputs</SectionHeading>
                  <div className="control-block">
                    <label className="control-label"><i className="input-color yellow" /> Button A (Yellow)</label>
                    <button className="press-button" type="button" onClick={() => sendAction("mark", "Button A pressed")}>Press</button>
                  </div>
                  <div className="control-block">
                    <label className="control-label"><i className="input-color blue" /> Button B (Blue)</label>
                    <button className="press-button" type="button" onClick={() => sendAction("mode", "Button B pressed")}>Press</button>
                  </div>
                  <div className="control-block touch-control">
                    <label className="control-label"><HandTap size={15} aria-hidden="true" /> Touch / Screen</label>
                    <button className="press-button" type="button" onClick={() => sendAction("focus", "Screen touched")}>Simulate Touch</button>
                  </div>
                </section>

                <section ref={(node) => { inspectorSectionRefs.current.Display = node; }}>
                  <SectionHeading>Status</SectionHeading>
                  <div className="inline-control battery-control">
                    <label htmlFor="battery-range"><BatteryMedium size={18} aria-hidden="true" /> Battery</label>
                    <input
                      id="battery-range"
                      type="range"
                      min="0"
                      max="100"
                      value={batteryDraft}
                      onChange={(event) => setBatteryDraft(Number(event.target.value))}
                      onPointerUp={(event) => configure({ battery_percent: Math.round(Number(event.currentTarget.value)) }, "Battery changed")}
                      onKeyUp={(event) => event.key.startsWith("Arrow") && configure({ battery_percent: Math.round(Number(event.currentTarget.value)) }, "Battery changed")}
                    />
                    <output>{Math.round(battery)}%</output>
                  </div>
                  <div className="inline-control">
                    <label><Lightning size={18} aria-hidden="true" /> Charging</label>
                    <Switch checked={charging} onChange={(value) => configure({ charging: value }, "Charging changed")} label="Charging" />
                  </div>
                </section>

                <section ref={(node) => { inspectorSectionRefs.current.System = node; }}>
                  <SectionHeading>Sensors</SectionHeading>
                  <div className="sensor-row">
                    <label><Crosshair size={18} aria-hidden="true" /> IMU Tilt</label>
                    <div className="axis-readout"><span>X <b>{imu.x}</b></span><span>Y <b>{imu.y}</b></span><span>Z <b>{imu.z}</b></span></div>
                  </div>
                  <div className="inline-control sensor-noise">
                    <label><Gauge size={18} aria-hidden="true" /> IMU Noise</label>
                    <input type="range" min="0" max="1" step="0.01" value="0.02" disabled readOnly />
                    <output>0.02</output>
                  </div>
                </section>

                <section>
                  <SectionHeading>Virtual Time</SectionHeading>
                  <div className="inline-control">
                    <label>Virtual Time</label>
                    <Switch checked={virtualTimeEnabled} onChange={(value) => configure({ time_scale: value ? 1 : 0.01 }, "Virtual time changed")} label="Virtual time" />
                  </div>
                  <div className="time-offset">
                    <label>Time Offset</label>
                    <div>
                      {[
                        [6001, "+6s"],
                        [30001, "+30s"],
                        [120001, "+2m"],
                        [600001, "+10m"],
                      ].map(([milliseconds, label]) => (
                        <button type="button" key={milliseconds} onClick={() => advanceTime(milliseconds, label)}>{label}</button>
                      ))}
                    </div>
                  </div>
                  <div className="inline-control time-scale">
                    <label htmlFor="time-scale-range">Time Scale</label>
                    <input
                      id="time-scale-range"
                      type="range"
                      min="0.25"
                      max="4"
                      step="0.25"
                      value={clamp(timeScaleDraft, 0.25, 4)}
                      onChange={(event) => setTimeScaleDraft(Number(event.target.value))}
                      onPointerUp={(event) => configure({ time_scale: Number(event.currentTarget.value) }, "Time scale changed")}
                      onKeyUp={(event) => event.key.startsWith("Arrow") && configure({ time_scale: Number(event.currentTarget.value) }, "Time scale changed")}
                    />
                    <output>{Number(timeScaleDraft).toFixed(2)}×</output>
                  </div>
                </section>
              </div>
            </div>
          )}

          {rightTab === "Device" && (
            <div className="details-view">
              <div className="details-hero"><DeviceMobile size={30} /><div><small>SIMULATED TARGET</small><strong>M5Stack C152</strong></div><span className="online-pill"><i /> Online</span></div>
              <SectionHeading>Firmware</SectionHeading>
              <dl className="detail-list">
                <div><dt>Identifier</dt><dd>{firmware.id}</dd></div>
                <div><dt>Label</dt><dd>{firmware.label}</dd></div>
                <div><dt>Revision</dt><dd>{snapshot.revision}</dd></div>
                <div><dt>Transport</dt><dd>{isNative ? "WKWebView Bridge" : "HTTP API"}</dd></div>
              </dl>
              <SectionHeading>Display</SectionHeading>
              <dl className="detail-list">
                <div><dt>Panel</dt><dd>466 × 466 AMOLED</dd></div>
                <div><dt>Brightness</dt><dd>{screen.brightness ?? snapshot.frame?.brightness ?? 100}%</dd></div>
                <div><dt>Draw commands</dt><dd>{snapshot.frame?.commands?.length ?? 0}</dd></div>
              </dl>
              <SectionHeading>Runtime</SectionHeading>
              <dl className="detail-list">
                <div><dt>Status</dt><dd>{statusLabel}</dd></div>
                <div><dt>Mode</dt><dd>{screen.mode ?? "—"}</dd></div>
                <div><dt>Haptic</dt><dd>{snapshot.haptic?.label ?? "IDLE"}</dd></div>
              </dl>
            </div>
          )}

          {rightTab === "Logs" && (
            <div className="logs-view">
              <div className="logs-toolbar"><TerminalWindow size={18} /><span>Native output</span><b>{snapshot.log?.length ?? 0} events</b></div>
              {(snapshot.log ?? []).map((entry, index) => (
                <div className="console-line" key={`${entry.time}-${index}`}><time>{eventTime(entry.time)}</time><strong>{safeText(entry.kind, "EVENT")}</strong><span>{safeText(entry.message)}</span></div>
              ))}
              {!snapshot.log?.length && <div className="empty-state"><ListBullets size={28} /><p>No native events yet.</p></div>}
            </div>
          )}
        </aside>

        <section className="event-timeline" aria-label="Event timeline">
          <header>
            <h2>Event Timeline</h2>
            <div className="timeline-filters" role="group" aria-label="Event filters">
              {FILTERS.map((filter) => <button type="button" key={filter} className={timelineFilter === filter ? "is-active" : ""} onClick={() => setTimelineFilter(filter)}>{filter}</button>)}
            </div>
            <button type="button" className="clear-button" onClick={clearTimeline}>Clear</button>
          </header>
          <div className="event-table">
            {timelineEvents.map((event, index) => {
              const Icon = eventIcon(event.category);
              return (
                <div className={`event-row category-${event.category.toLowerCase()}`} key={`${event.time}-${event.kind}-${index}`}>
                  <time>{eventTime(event.time)}</time>
                  <span className="event-kind"><Icon size={17} aria-hidden="true" /> {event.category}</span>
                  <span className="event-message">{event.message}</span>
                  <span className="event-detail">{event.detail}</span>
                </div>
              );
            })}
            {!timelineEvents.length && <div className="timeline-empty"><ListBullets size={20} /> Timeline cleared — interact with the device to capture new events.</div>}
          </div>
        </section>
      </div>
    </div>
  );
}
