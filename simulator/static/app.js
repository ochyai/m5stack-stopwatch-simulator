"use strict";

(() => {
  const POLL_INTERVAL_MS = 100;
  const MODE_COLORS = {
    NOW: "#33d6e8",
    BUILD: "#ff9f2d",
    READ: "#68dc81",
    MEET: "#337cff",
    PRESENT: "#eb63dd",
    REST: "#8b9493",
  };
  const COLOR_PATTERN = /^#[0-9a-f]{6}$/i;

  const elements = {
    brand: document.getElementById("simulator-brand"),
    brandWord: document.getElementById("brand-word"),
    brandSubtitle: document.getElementById("brand-subtitle"),
    deviceHeading: document.getElementById("device-heading"),
    primaryActionLabel: document.getElementById("primary-action-label"),
    secondaryActionLabel: document.getElementById("secondary-action-label"),
    touchActionLabel: document.getElementById("touch-action-label"),
    shellLabel: document.getElementById("shell-label"),
    shellSubtitle: document.getElementById("shell-subtitle"),
    keyboardPrimary: document.getElementById("keyboard-primary"),
    keyboardSecondary: document.getElementById("keyboard-secondary"),
    keyboardTouch: document.getElementById("keyboard-touch"),
    accessibilitySummary: document.getElementById("device-accessibility-summary"),
    scenarioKicker: document.getElementById("scenario-kicker"),
    scenarioHeading: document.getElementById("scenario-heading"),
    firmwareControlNote: document.getElementById("firmware-control-note"),
    timeControlsLabel: document.getElementById("time-controls-label"),
    hostControls: document.querySelectorAll("[data-host-control]"),
    advanceLabels: document.querySelectorAll("[data-advance] span"),
    apiState: document.querySelector(".api-state"),
    apiStatusText: document.getElementById("api-status-text"),
    revision: document.getElementById("revision-label"),
    pollDiagnostic: document.getElementById("poll-diagnostic"),
    deviceSlot: document.getElementById("device-slot"),
    deviceScaler: document.getElementById("device-scaler"),
    face: document.getElementById("amoled-face"),
    canvas: document.getElementById("device-canvas"),
    screenContent: document.getElementById("screen-content"),
    screenConnection: document.getElementById("screen-connection"),
    screenBattery: document.getElementById("screen-battery"),
    batteryFill: document.getElementById("battery-fill"),
    chargingMark: document.getElementById("charging-mark"),
    screenTime: document.getElementById("screen-time"),
    screenMode: document.getElementById("screen-mode"),
    screenContext: document.getElementById("screen-context"),
    screenDetail: document.getElementById("screen-detail"),
    focusStateText: document.getElementById("focus-state-text"),
    elapsedTime: document.getElementById("elapsed-time"),
    markCount: document.getElementById("mark-count"),
    pending: document.getElementById("pending-indicator"),
    pendingLabel: document.getElementById("pending-label"),
    toast: document.getElementById("screen-toast"),
    sleepOverlay: document.getElementById("sleep-overlay"),
    markButton: document.getElementById("mark-button"),
    modeButton: document.getElementById("mode-button"),
    focusButton: document.getElementById("focus-button"),
    wakeButton: document.getElementById("wake-button"),
    resetButton: document.getElementById("reset-button"),
    connectedInput: document.getElementById("connected-input"),
    latencyInput: document.getElementById("latency-input"),
    latencyOutput: document.getElementById("latency-output"),
    contextInput: document.getElementById("context-input"),
    detailInput: document.getElementById("detail-input"),
    modeInput: document.getElementById("mode-input"),
    batteryInput: document.getElementById("battery-input"),
    chargingInput: document.getElementById("charging-input"),
    hapticReadout: document.getElementById("haptic-readout"),
    hapticLabel: document.getElementById("haptic-label"),
    log: document.getElementById("protocol-log"),
  };

  const state = {
    polling: false,
    scenarioUpdating: false,
    scenarioTimer: null,
    lastRevision: null,
    lastLogSignature: "",
    lastHapticSignature: "",
    controlsHydrated: false,
    online: false,
    requestStartedAt: 0,
    sleeping: false,
    firmwareLabel: "SOKKON",
    stateSemantics: "sokkon",
    hostControls: true,
  };

  const canvasContext = elements.canvas.getContext("2d", { alpha: false });
  canvasContext.imageSmoothingEnabled = true;

  function finiteNumber(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, finiteNumber(value, minimum)));
  }

  function safeText(value, fallback = "") {
    if (value === null || value === undefined) return fallback;
    return String(value);
  }

  function boolValue(value) {
    if (typeof value === "string") {
      return value.toLowerCase() === "true" || value === "1";
    }
    return Boolean(value);
  }

  function accentFor(screen) {
    const supplied = safeText(screen.accent).trim();
    if (COLOR_PATTERN.test(supplied)) return supplied;
    return MODE_COLORS[safeText(screen.mode, "NOW").toUpperCase()] || MODE_COLORS.NOW;
  }

  function hexToRgb(hex) {
    const normalized = hex.slice(1);
    return [0, 2, 4].map((offset) => Number.parseInt(normalized.slice(offset, offset + 2), 16)).join(", ");
  }

  function colorValue(value, fallback = "#ffffff") {
    if (typeof value === "string") {
      const normalized = value.trim();
      if (/^#[0-9a-f]{3,8}$/i.test(normalized) || /^(?:rgb|hsl)a?\(/i.test(normalized)) return normalized;
      const named = {
        TFT_BLACK: "#000000",
        TFT_WHITE: "#ffffff",
        TFT_RED: "#ff0000",
        TFT_GREEN: "#00ff00",
        TFT_BLUE: "#0000ff",
        TFT_YELLOW: "#ffff00",
        TFT_CYAN: "#00ffff",
        TFT_MAGENTA: "#ff00ff",
        TFT_ORANGE: "#ff9f00",
        TFT_DARKGREY: "#7b7d7b",
        TFT_LIGHTGREY: "#d6d3d6",
      };
      if (named[normalized.toUpperCase()]) return named[normalized.toUpperCase()];
      const numeric = Number(normalized);
      if (Number.isFinite(numeric)) return colorValue(numeric, fallback);
      return fallback;
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
    const value = Array.isArray(command) ? command[0] : command?.op ?? command?.type ?? command?.command ?? command?.name ?? command?.kind;
    return safeText(value)
      .replaceAll("_", "")
      .replaceAll("-", "")
      .toLowerCase();
  }

  function commandField(command, names, argumentIndex, fallback = undefined) {
    if (Array.isArray(command) && command[argumentIndex + 1] !== undefined) return command[argumentIndex + 1];
    for (const name of names) {
      if (command && command[name] !== undefined) return command[name];
    }
    if (Array.isArray(command?.args) && command.args[argumentIndex] !== undefined) return command.args[argumentIndex];
    return fallback;
  }

  function fontForCommand(command, renderState) {
    const fontValue = commandField(command, ["font", "font_name"], -1, renderState.font);
    const fontName = typeof fontValue === "object" ? safeText(fontValue.name) : safeText(fontValue);
    let fontSize = finiteNumber(
      commandField(command, ["font_size", "size_px", "text_size"], -1, typeof fontValue === "object" ? fontValue.size : 0),
      0,
    );
    if (!fontSize) {
      if (/24pt|24/i.test(fontName)) fontSize = 48;
      else if (/18pt|18/i.test(fontName)) fontSize = 36;
      else if (/font2/i.test(fontName)) fontSize = 16;
      else fontSize = 16;
    }
    const weight = /bold/i.test(fontName) || command.bold ? 700 : 600;
    return `${weight} ${Math.max(5, fontSize)}px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif`;
  }

  function applyTextDatum(context, datum) {
    const normalized = safeText(datum, "middle_center").toLowerCase();
    context.textAlign = normalized.includes("left") ? "left" : normalized.includes("right") ? "right" : "center";
    context.textBaseline = normalized.includes("top") ? "top" : normalized.includes("bottom") ? "bottom" : "middle";
  }

  function roundedRectanglePath(context, x, y, width, height, radius) {
    const safeRadius = Math.max(0, Math.min(radius, Math.abs(width) / 2, Math.abs(height) / 2));
    context.beginPath();
    if (typeof context.roundRect === "function") {
      context.roundRect(x, y, width, height, safeRadius);
      return;
    }
    context.moveTo(x + safeRadius, y);
    context.arcTo(x + width, y, x + width, y + height, safeRadius);
    context.arcTo(x + width, y + height, x, y + height, safeRadius);
    context.arcTo(x, y + height, x, y, safeRadius);
    context.arcTo(x, y, x + width, y, safeRadius);
    context.closePath();
  }

  function renderFrame(frame, screen = {}) {
    const context = canvasContext;
    const commands = Array.isArray(frame?.commands) ? frame.commands : [];
    const frameWidth = Math.max(1, finiteNumber(frame?.width, 466));
    const frameHeight = Math.max(1, finiteNumber(frame?.height, 466));
    const scaleX = 466 / frameWidth;
    const scaleY = 466 / frameHeight;
    const renderState = {
      color: "#ffffff",
      background: "#000000",
      font: "Font2",
      datum: "middle_center",
    };

    context.save();
    context.setTransform(scaleX, 0, 0, scaleY, 0, 0);
    context.fillStyle = "#000000";
    context.fillRect(0, 0, frameWidth, frameHeight);
    context.lineCap = "butt";
    context.lineJoin = "round";

    for (const command of commands) {
      const name = commandName(command);
      if (!name) continue;

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
        context.fillRect(0, 0, frameWidth, frameHeight);
        continue;
      }

      if (name === "drawcircle" || name === "fillcircle") {
        const x = finiteNumber(commandField(command, ["x", "cx", "center_x"], 0));
        const y = finiteNumber(commandField(command, ["y", "cy", "center_y"], 1));
        const radius = Math.max(0, finiteNumber(commandField(command, ["r", "radius"], 2)));
        const color = colorValue(commandField(command, ["color"], 3), renderState.color);
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        if (name === "fillcircle") {
          context.fillStyle = color;
          context.fill();
        } else {
          context.strokeStyle = color;
          context.lineWidth = Math.max(1, finiteNumber(commandField(command, ["line_width", "stroke_width"], 4), 1));
          context.stroke();
        }
        continue;
      }

      if (name === "drawarc") {
        const x = finiteNumber(commandField(command, ["x", "cx", "center_x"], 0));
        const y = finiteNumber(commandField(command, ["y", "cy", "center_y"], 1));
        const outer = Math.max(0, finiteNumber(commandField(command, ["outer_radius", "outer_r", "outer", "r_outer", "r1"], 2)));
        const inner = Math.max(0, finiteNumber(commandField(command, ["inner_radius", "inner_r", "inner", "r_inner", "r2"], 3)));
        const start = finiteNumber(commandField(command, ["start", "start_angle", "angle_start"], 4));
        let end = finiteNumber(commandField(command, ["end", "end_angle", "angle_end"], 5));
        const color = colorValue(commandField(command, ["color"], 6), renderState.color);
        if (end < start) end += 360;
        context.beginPath();
        context.arc(x, y, (outer + inner) / 2, (start - 90) * Math.PI / 180, (end - 90) * Math.PI / 180, false);
        context.strokeStyle = color;
        context.lineWidth = Math.max(1, Math.abs(outer - inner) + 1);
        context.lineCap = "butt";
        context.stroke();
        continue;
      }

      if (name === "fillroundrect") {
        const x = finiteNumber(commandField(command, ["x"], 0));
        const y = finiteNumber(commandField(command, ["y"], 1));
        const width = finiteNumber(commandField(command, ["width", "w"], 2));
        const height = finiteNumber(commandField(command, ["height", "h"], 3));
        const radius = finiteNumber(commandField(command, ["radius", "r"], 4));
        const color = colorValue(commandField(command, ["color"], 5), renderState.color);
        roundedRectanglePath(context, x, y, width, height, radius);
        context.fillStyle = color;
        context.fill();
        continue;
      }

      if (name === "drawstring") {
        const text = safeText(commandField(command, ["text", "value"], 0));
        const x = finiteNumber(commandField(command, ["x"], 1));
        const y = finiteNumber(commandField(command, ["y"], 2));
        const color = colorValue(commandField(command, ["color", "foreground", "fg"], 3), renderState.color);
        const datum = commandField(command, ["datum", "text_datum"], -1, renderState.datum);
        context.save();
        context.font = fontForCommand(command, renderState);
        applyTextDatum(context, datum);
        context.fillStyle = color;
        context.fillText(text, x, y);
        context.restore();
      }
    }
    context.restore();

    const brightness = clamp(screen.brightness ?? 100, 0, 100);
    elements.canvas.style.opacity = boolValue(screen.sleeping) ? "0" : `${brightness / 100}`;
    elements.canvas.dataset.commandCount = String(commands.length);
  }

  function renderFirmware(firmware = {}) {
    const label = safeText(firmware.label, "SOKKON").trim() || "SOKKON";
    const subtitle = safeText(firmware.subtitle, "DIGITAL TWIN").trim() || "DIGITAL TWIN";
    const shellSubtitle = safeText(firmware.shell_subtitle, "LOCAL FIRST INTERFACE").trim() || "LOCAL FIRST INTERFACE";
    const heading = safeText(firmware.heading, "いまを、手で扱う。");
    const primary = safeText(firmware.primary_label, "MARK").trim() || "MARK";
    const secondary = safeText(firmware.secondary_label, "MODE").trim() || "MODE";
    const touch = safeText(firmware.touch_label, "FOCUS").trim() || "FOCUS";
    const primaryAria = safeText(firmware.primary_aria, primary).trim() || primary;
    const secondaryAria = safeText(firmware.secondary_aria, secondary).trim() || secondary;
    const touchAria = safeText(firmware.touch_aria, touch).trim() || touch;
    const hostControls = firmware.host_controls !== false;

    state.firmwareLabel = label;
    state.stateSemantics = safeText(firmware.state_semantics, "sokkon");
    state.hostControls = hostControls;

    elements.brandWord.textContent = label;
    elements.brandSubtitle.textContent = subtitle;
    elements.deviceHeading.textContent = heading;
    elements.primaryActionLabel.textContent = primary;
    elements.secondaryActionLabel.textContent = secondary;
    elements.touchActionLabel.textContent = touch;
    elements.shellLabel.textContent = label;
    elements.shellSubtitle.textContent = shellSubtitle;
    elements.keyboardPrimary.textContent = primary;
    elements.keyboardSecondary.textContent = secondary;
    elements.keyboardTouch.textContent = touch;
    elements.brand.setAttribute("aria-label", `${label} simulator`);
    elements.face.setAttribute("aria-label", `${label} device screen`);
    elements.markButton.setAttribute("aria-label", `黄色 A ボタン: ${primaryAria}`);
    elements.modeButton.setAttribute("aria-label", `青 B ボタン: ${secondaryAria}`);
    elements.focusButton.setAttribute("aria-label", `中央タッチ: ${touchAria}`);
    elements.scenarioKicker.textContent = hostControls ? "HOST CONDITIONS" : "DEVICE CONDITIONS";
    elements.scenarioHeading.textContent = hostControls ? "Scenario" : "Stopwatch simulation";
    elements.firmwareControlNote.hidden = hostControls;
    elements.firmwareControlNote.textContent = hostControls
      ? ""
      : "Mac連携専用の設定は無効です。仮想時間、電池、充電状態は操作できます。";
    elements.hostControls.forEach((container) => {
      container.classList.toggle("is-firmware-disabled", !hostControls);
      container.setAttribute("aria-disabled", hostControls ? "false" : "true");
      container.querySelectorAll("input, select, textarea, button").forEach((control) => {
        control.disabled = !hostControls;
      });
    });
    elements.timeControlsLabel.textContent = hostControls
      ? "Virtual time · production constants"
      : "Virtual time · production stopwatch";
    elements.advanceLabels.forEach((labelElement) => {
      if (!labelElement.dataset.sokkonLabel) labelElement.dataset.sokkonLabel = labelElement.textContent;
      labelElement.textContent = hostControls ? labelElement.dataset.sokkonLabel : "ADVANCE";
    });
    document.title = `${label} Simulator`;
  }

  async function apiRequest(path, options = {}) {
    const response = await fetch(path, {
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!response.ok) {
      const message = await response.text().catch(() => "");
      throw new Error(`${response.status} ${message || response.statusText}`.trim());
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function setApiState(kind, detail = "") {
    elements.apiState.classList.toggle("is-online", kind === "online");
    elements.apiState.classList.toggle("is-error", kind === "error");
    elements.apiStatusText.textContent = kind === "online" ? "SIMULATOR ONLINE" : kind === "error" ? "API OFFLINE" : "CONNECTING";
    if (detail) elements.pollDiagnostic.textContent = detail;
  }

  function renderScreen(screen = {}) {
    const connected = boolValue(screen.connected);
    const focusRunning = boolValue(screen.focus_running);
    const sleeping = boolValue(screen.sleeping);
    const battery = clamp(screen.battery_percent ?? screen.battery, 0, 100);
    const charging = boolValue(screen.charging);
    const mode = safeText(screen.mode, "NOW").toUpperCase();
    const accent = accentFor(screen);

    document.documentElement.style.setProperty("--accent", accent);
    document.documentElement.style.setProperty("--accent-rgb", hexToRgb(accent));
    elements.face.style.setProperty("--screen-accent", accent);
    elements.face.classList.toggle("is-connected", connected);
    elements.face.classList.toggle("is-focus-running", focusRunning);
    elements.face.classList.toggle("is-sleeping", sleeping);
    state.sleeping = sleeping;

    elements.screenConnection.textContent = connected ? safeText(screen.status, "USB") : safeText(screen.status, "LOCAL");
    elements.screenBattery.textContent = `${Math.round(battery)}%`;
    elements.batteryFill.style.width = `${battery}%`;
    elements.chargingMark.hidden = !charging;
    elements.screenTime.textContent = safeText(screen.time, "--:--");
    elements.screenMode.textContent = mode;
    elements.screenContext.textContent = safeText(screen.context, connected ? "MAC" : "MAC NOT CONNECTED");
    elements.screenDetail.textContent = safeText(screen.detail, connected ? "AUTO MODE" : "USB-C TO BEGIN");
    elements.focusStateText.textContent = focusRunning ? "FOCUS / RUNNING" : "FOCUS / PAUSED";
    elements.elapsedTime.textContent = safeText(screen.elapsed_text, formatElapsed(screen.elapsed_ms));
    elements.markCount.textContent = `MARKS ${Math.max(0, Math.trunc(finiteNumber(screen.marks, 0)))}`;

    elements.sleepOverlay.hidden = !sleeping;
    const accessibilitySummary = state.stateSemantics === "stopwatch"
      ? `${state.firmwareLabel}、${focusRunning ? "計測中" : "一時停止"}、経過時間 ${elements.elapsedTime.textContent}、${elements.screenTime.textContent}、バッテリー ${Math.round(battery)}%${charging ? "、充電中" : ""}`
      : `${state.firmwareLabel}、接続 ${elements.screenConnection.textContent}、バッテリー ${Math.round(battery)}%${charging ? "、充電中" : ""}、${mode}、${elements.screenTime.textContent}、${elements.screenContext.textContent}、${elements.screenDetail.textContent}、${focusRunning ? "フォーカス計測中" : "フォーカス一時停止"}、${elements.elapsedTime.textContent}、${elements.markCount.textContent}`;
    if (elements.accessibilitySummary.textContent !== accessibilitySummary) {
      elements.accessibilitySummary.textContent = accessibilitySummary;
    }

    const toast = safeText(screen.toast).trim();
    elements.toast.textContent = toast;
    elements.toast.hidden = toast.length === 0 || sleeping;

    const minute = Math.floor(Date.now() / 60000) % 4;
    const shifts = [[0, 0], [0, 1], [0, 0], [0, -1]];
    elements.screenContent.style.setProperty("--pixel-shift-x", `${shifts[minute][0]}px`);
    elements.screenContent.style.setProperty("--pixel-shift-y", `${shifts[minute][1]}px`);
  }

  function formatElapsed(value) {
    const totalSeconds = Math.max(0, Math.floor(finiteNumber(value) / 1000));
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds].map((unit) => String(unit).padStart(2, "0")).join(":");
  }

  function pendingCount(pending) {
    if (Array.isArray(pending)) return pending.length;
    if (!pending) return 0;
    if (typeof pending === "number") return Math.max(0, Math.trunc(pending));
    if (typeof pending === "object") {
      if (Number.isFinite(Number(pending.count))) return Math.max(0, Math.trunc(Number(pending.count)));
      if (pending.active === false) return 0;
      return Object.keys(pending).length ? 1 : 0;
    }
    return boolValue(pending) ? 1 : 0;
  }

  function renderPending(pending) {
    const count = pendingCount(pending);
    elements.pending.hidden = count === 0;
    if (count === 0) return;
    const first = Array.isArray(pending) ? pending[0] : pending;
    const intent = first && typeof first === "object" ? safeText(first.intent || first.action).replaceAll("_", " ") : "MAC";
    elements.pendingLabel.textContent = count > 1 ? `${count} EVENTS PENDING` : `${intent || "MAC"} PENDING`;
  }

  function hapticSignature(haptic) {
    try {
      return JSON.stringify(haptic ?? null);
    } catch (_error) {
      return safeText(haptic);
    }
  }

  function renderHaptic(haptic) {
    const active = Boolean(haptic && (typeof haptic !== "object" || haptic.active !== false));
    let label = "IDLE";
    if (active) {
      if (typeof haptic === "string") label = haptic;
      else if (typeof haptic === "number") label = `${haptic} PULSE${haptic === 1 ? "" : "S"}`;
      else if (Array.isArray(haptic)) label = `${haptic.length} PULSE${haptic.length === 1 ? "" : "S"}`;
      else {
        const pulses = finiteNumber(haptic.pulses ?? haptic.pulse_count ?? haptic.count, 0);
        const intensity = finiteNumber(haptic.intensity, 0);
        label = safeText(haptic.label || haptic.pattern, pulses ? `${pulses}× / ${intensity}` : "ACTIVE").toUpperCase();
      }
    }

    const signature = hapticSignature(haptic);
    if (signature !== state.lastHapticSignature) {
      elements.hapticReadout.classList.remove("is-active");
      void elements.hapticReadout.offsetWidth;
      elements.hapticReadout.classList.toggle("is-active", active);
      state.lastHapticSignature = signature;
    } else if (!active) {
      elements.hapticReadout.classList.remove("is-active");
    }
    elements.hapticLabel.textContent = label;
  }

  function normalizeLogEntry(entry, index) {
    if (typeof entry === "string") {
      const parts = entry.match(/^\[?([^\]]+)\]?\s+(TX|RX|EVENT|RESULT|HAPTIC|ERROR)?\s*(.*)$/i);
      return {
        time: parts ? parts[1] : "—",
        kind: parts?.[2] || "EVENT",
        message: parts ? parts[3] : entry,
        key: `${index}:${entry}`,
      };
    }
    if (!entry || typeof entry !== "object") {
      return { time: "—", kind: "EVENT", message: safeText(entry), key: `${index}` };
    }
    const timeValue = entry.time ?? entry.timestamp ?? entry.at ?? entry.created_at;
    return {
      time: formatLogTime(timeValue),
      kind: safeText(entry.kind ?? entry.direction ?? entry.level ?? entry.type, "EVENT").toUpperCase(),
      message: safeText(entry.message ?? entry.line ?? entry.data ?? entry.text ?? entry.event, stringifyCompact(entry)),
      key: safeText(entry.id, `${index}:${timeValue}:${entry.message ?? entry.line ?? ""}`),
    };
  }

  function stringifyCompact(value) {
    try {
      return JSON.stringify(value);
    } catch (_error) {
      return safeText(value);
    }
  }

  function formatLogTime(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number") {
      // Native protocol entries use virtual elapsed milliseconds.  Keeping
      // that clock relative makes accelerated scenario steps legible instead
      // of accidentally treating 1,000 ms as 1,000 Unix seconds.
      if (value < 1e12) {
        const totalSeconds = Math.max(0, Math.floor(value / 1000));
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        return hours
          ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
          : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
      }
      const date = new Date(value);
      if (!Number.isNaN(date.getTime())) return date.toLocaleTimeString([], { hour12: false, minute: "2-digit", second: "2-digit" });
    }
    return safeText(value).replace(/^.*T/, "").replace(/Z$/, "").slice(0, 12);
  }

  function renderLog(log) {
    const entries = Array.isArray(log) ? log.slice(-120) : log ? [log] : [];
    const signature = hapticSignature(entries);
    if (signature === state.lastLogSignature) return;

    const wasNearBottom = elements.log.scrollHeight - elements.log.scrollTop - elements.log.clientHeight < 36;
    elements.log.replaceChildren();
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.className = "log-empty";
      const glyph = document.createElement("span");
      glyph.setAttribute("aria-hidden", "true");
      glyph.textContent = "⌁";
      const message = document.createElement("p");
      message.textContent = "イベントを待っています";
      const hint = document.createElement("small");
      hint.textContent = "A / B / SPACE で操作";
      empty.append(glyph, message, hint);
      elements.log.append(empty);
    } else {
      const fragment = document.createDocumentFragment();
      entries.forEach((entry, index) => {
        const item = normalizeLogEntry(entry, index);
        const row = document.createElement("div");
        row.className = "log-row";
        if (/ERROR|TIMEOUT|FAIL/.test(`${item.kind} ${item.message}`)) row.classList.add("is-error");
        if (/HAPTIC|PULSE|VIBR/.test(`${item.kind} ${item.message}`)) row.classList.add("is-haptic");
        row.dataset.logKey = item.key;

        const time = document.createElement("span");
        time.className = "log-time";
        time.textContent = item.time;
        const kind = document.createElement("span");
        kind.className = "log-kind";
        kind.textContent = item.kind;
        kind.title = item.kind;
        const message = document.createElement("span");
        message.className = "log-message";
        message.textContent = item.message;
        row.append(time, kind, message);
        fragment.append(row);
      });
      elements.log.append(fragment);
    }
    if (wasNearBottom || !state.lastLogSignature) elements.log.scrollTop = elements.log.scrollHeight;
    state.lastLogSignature = signature;
  }

  function hydrateScenario(scenario = {}) {
    if (state.scenarioUpdating || document.activeElement?.matches("[data-scenario]")) return;
    const connected = scenario.connected;
    if (connected !== undefined) elements.connectedInput.checked = boolValue(connected);
    const outcome = safeText(scenario.outcome).toUpperCase();
    const outcomeInput = document.querySelector(`input[name="outcome"][value="${CSS.escape(outcome)}"]`);
    if (outcomeInput) outcomeInput.checked = true;
    setInputValue(elements.latencyInput, scenario.latency_ms);
    setInputValue(elements.contextInput, scenario.context);
    setInputValue(elements.detailInput, scenario.detail);
    setInputValue(elements.modeInput, scenario.host_mode);
    setInputValue(elements.batteryInput, scenario.battery_percent);
    if (scenario.charging !== undefined) elements.chargingInput.checked = boolValue(scenario.charging);
    updateRangeDisplay(elements.latencyInput, elements.latencyOutput);
    state.controlsHydrated = true;
  }

  function setInputValue(input, value) {
    if (value !== undefined && value !== null) input.value = safeText(value);
  }

  function renderSnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== "object") throw new Error("Invalid state payload");
    const screen = { ...(snapshot.scenario || {}), ...(snapshot.screen || {}) };
    renderFirmware(snapshot.firmware || {});
    renderFrame(snapshot.frame || {}, screen);
    renderScreen(screen);
    renderPending(snapshot.pending);
    renderHaptic(snapshot.haptic);
    renderLog(snapshot.log);
    hydrateScenario(snapshot.scenario || {});
    state.lastRevision = snapshot.revision ?? state.lastRevision;
    elements.revision.textContent = `R${safeText(state.lastRevision, "—")}`;
  }

  async function poll() {
    if (state.polling || document.hidden) return;
    state.polling = true;
    state.requestStartedAt = performance.now();
    try {
      const snapshot = await apiRequest("/api/state");
      renderSnapshot(snapshot);
      const duration = Math.max(0, performance.now() - state.requestStartedAt);
      setApiState("online", `GET /api/state · ${duration.toFixed(0)} MS`);
      state.online = true;
    } catch (error) {
      setApiState("error", `API ERROR · ${safeText(error.message, "UNKNOWN")}`);
      state.online = false;
    } finally {
      state.polling = false;
    }
  }

  async function sendAction(action, sourceButton) {
    if (sourceButton) animatePress(sourceButton);
    try {
      const snapshot = await apiRequest("/api/action", {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      if (snapshot && snapshot.screen) renderSnapshot(snapshot);
      await poll();
    } catch (error) {
      setApiState("error", `POST ${action.toUpperCase()} · ${safeText(error.message)}`);
    }
  }

  function animatePress(button) {
    button.classList.remove("is-pressed");
    void button.offsetWidth;
    button.classList.add("is-pressed");
    window.setTimeout(() => button.classList.remove("is-pressed"), 130);
  }

  function scenarioPayload() {
    const devicePayload = {
      battery_percent: Math.round(clamp(elements.batteryInput.value, 0, 100)),
      charging: elements.chargingInput.checked,
    };
    if (!state.hostControls) return devicePayload;
    const outcome = document.querySelector('input[name="outcome"]:checked');
    return {
      ...devicePayload,
      connected: elements.connectedInput.checked,
      outcome: outcome ? outcome.value : "OK",
      latency_ms: Math.max(0, Math.trunc(finiteNumber(elements.latencyInput.value, 0))),
      context: elements.contextInput.value,
      detail: elements.detailInput.value,
      host_mode: elements.modeInput.value,
    };
  }

  async function updateScenario() {
    window.clearTimeout(state.scenarioTimer);
    state.scenarioUpdating = true;
    try {
      const snapshot = await apiRequest("/api/scenario", {
        method: "POST",
        body: JSON.stringify(scenarioPayload()),
      });
      if (snapshot && snapshot.screen) renderSnapshot(snapshot);
      await poll();
    } catch (error) {
      setApiState("error", `SCENARIO ERROR · ${safeText(error.message)}`);
    } finally {
      state.scenarioUpdating = false;
    }
  }

  function scheduleScenarioUpdate() {
    window.clearTimeout(state.scenarioTimer);
    state.scenarioTimer = window.setTimeout(updateScenario, 120);
  }

  function updateRangeDisplay(input, output) {
    const minimum = finiteNumber(input.min, 0);
    const maximum = finiteNumber(input.max, 100);
    const value = clamp(input.value, minimum, maximum);
    const fill = maximum === minimum ? 0 : ((value - minimum) / (maximum - minimum)) * 100;
    input.style.setProperty("--range-fill", `${fill}%`);
    output.textContent = `${Math.round(value)} ms`;
  }

  function resizeDevice() {
    const naturalWidth = 570;
    const naturalHeight = 610;
    const available = Math.max(280, elements.deviceSlot.clientWidth);
    const scale = Math.min(1, available / naturalWidth);
    document.documentElement.style.setProperty("--device-scale", String(scale));
    elements.deviceSlot.style.minHeight = `${Math.ceil(naturalHeight * scale)}px`;
  }

  function isTypingTarget(target) {
    return target instanceof HTMLElement && (target.matches("input, select, textarea") || target.isContentEditable);
  }

  elements.markButton.addEventListener("click", () => sendAction("mark", elements.markButton));
  elements.modeButton.addEventListener("click", () => sendAction("mode", elements.modeButton));
  elements.focusButton.addEventListener("click", () => sendAction(state.sleeping ? "wake" : "focus", elements.focusButton));
  elements.wakeButton.addEventListener("click", () => sendAction("wake", elements.wakeButton));
  elements.resetButton.addEventListener("click", () => sendAction("reset", elements.resetButton));

  document.addEventListener("keydown", (event) => {
    if (event.repeat || event.metaKey || event.ctrlKey || event.altKey || isTypingTarget(event.target)) return;
    const key = event.key.toLowerCase();
    if (key === "a") {
      event.preventDefault();
      sendAction("mark", elements.markButton);
    } else if (key === "b") {
      event.preventDefault();
      sendAction("mode", elements.modeButton);
    } else if (event.code === "Space" && !(event.target instanceof HTMLButtonElement)) {
      event.preventDefault();
      sendAction("focus", elements.focusButton);
    }
  });

  document.querySelectorAll("[data-scenario]").forEach((input) => {
    const eventName = input.matches('input[type="text"], input[type="number"], input[type="range"]') ? "input" : "change";
    input.addEventListener(eventName, () => {
      if (input === elements.latencyInput) updateRangeDisplay(elements.latencyInput, elements.latencyOutput);
      scheduleScenarioUpdate();
    });
  });

  document.querySelectorAll("[data-advance]").forEach((button) => {
    button.addEventListener("click", () => sendAction(button.dataset.advance, button));
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) poll();
  });

  if ("ResizeObserver" in window) {
    new ResizeObserver(resizeDevice).observe(elements.deviceSlot);
  } else {
    window.addEventListener("resize", resizeDevice);
  }

  updateRangeDisplay(elements.latencyInput, elements.latencyOutput);
  resizeDevice();
  poll();
  window.setInterval(poll, POLL_INTERVAL_MS);
})();
