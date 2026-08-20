// The one interpreter for native firmware draw commands.
//
// The native runner publishes exactly what the production firmware drew.  Both
// simulator front ends — the bundled static UI and the desktop Workbench —
// import this module so a device pixel can never depend on which UI is open.
// Presentation choices a UI may legitimately differ on (font family, weight)
// are options; command semantics are not.

export const DEFAULT_FONT_FAMILY =
  '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';
export const DEVICE_SIZE = 466;

// LovyanGFX colour constants, kept at their real device values.  The firmware
// normally sends numeric RGB565/RGB888, so this map is a fallback for
// hand-written frames and tests.
const NAMED_COLORS = {
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

export function finiteNumber(value, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

export function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, finiteNumber(value, minimum)));
}

export function safeText(value, fallback = "") {
  if (value === null || value === undefined) return fallback;
  return String(value);
}

export function boolValue(value) {
  if (typeof value === "string") {
    return value.toLowerCase() === "true" || value === "1";
  }
  return Boolean(value);
}

export function colorValue(value, fallback = "#ffffff") {
  if (typeof value === "string") {
    const normalized = value.trim();
    if (/^#[0-9a-f]{3,8}$/i.test(normalized) || /^(?:rgb|hsl)a?\(/i.test(normalized)) {
      return normalized;
    }
    const named = NAMED_COLORS[normalized.toUpperCase()];
    if (named) return named;
    const numeric = Number(normalized);
    if (Number.isFinite(numeric)) return colorValue(numeric, fallback);
    return fallback;
  }
  if (!Number.isFinite(Number(value))) return fallback;
  const numeric = Math.max(0, Math.trunc(Number(value)));
  if (numeric <= 0xffff) {
    const red = Math.round((((numeric >> 11) & 0x1f) * 255) / 31);
    const green = Math.round((((numeric >> 5) & 0x3f) * 255) / 63);
    const blue = Math.round(((numeric & 0x1f) * 255) / 31);
    return `rgb(${red}, ${green}, ${blue})`;
  }
  return `#${Math.min(numeric, 0xffffff).toString(16).padStart(6, "0")}`;
}

export function commandName(command) {
  const value = Array.isArray(command)
    ? command[0]
    : command?.op ?? command?.type ?? command?.command ?? command?.name ?? command?.kind;
  return safeText(value).replaceAll("_", "").replaceAll("-", "").toLowerCase();
}

export function commandField(command, names, argumentIndex, fallback = undefined) {
  if (Array.isArray(command) && command[argumentIndex + 1] !== undefined) {
    return command[argumentIndex + 1];
  }
  for (const name of names) {
    if (command && command[name] !== undefined) return command[name];
  }
  if (Array.isArray(command?.args) && command.args[argumentIndex] !== undefined) {
    return command.args[argumentIndex];
  }
  return fallback;
}

export function fontForCommand(command, renderState, typography = {}) {
  const {
    fontFamily = DEFAULT_FONT_FAMILY,
    regularWeight = 600,
    boldWeight = 700,
  } = typography;
  const fontValue = commandField(command, ["font", "font_name"], -1, renderState.font);
  const fontName = typeof fontValue === "object" ? safeText(fontValue.name) : safeText(fontValue);
  let fontSize = finiteNumber(
    commandField(
      command,
      ["font_size", "size_px", "text_size"],
      -1,
      typeof fontValue === "object" ? fontValue.size : 0,
    ),
    0,
  );
  if (!fontSize) {
    if (/24pt|24/i.test(fontName)) fontSize = 48;
    else if (/18pt|18/i.test(fontName)) fontSize = 36;
    else if (/font2/i.test(fontName)) fontSize = 16;
    else fontSize = 16;
  }
  const weight = /bold/i.test(fontName) || command?.bold ? boldWeight : regularWeight;
  return `${weight} ${Math.max(5, fontSize)}px ${fontFamily}`;
}

// Characters the device would actually advance for: it walks bytes and skips
// control codes.
export function printableCharacters(text) {
  return Array.from(safeText(text)).filter((character) => character >= " ");
}

// Device-measured text geometry, when the native runner published it.
export function deviceLayout(command) {
  const placement = command?.layout;
  if (!placement || !Array.isArray(placement.pen) || placement.pen.length === 0) {
    return null;
  }
  const baseline = Number(placement.baseline);
  if (!Number.isFinite(baseline)) return null;
  return {
    pen: placement.pen.map((value) => finiteNumber(value)),
    baseline,
    left: finiteNumber(placement.left),
    top: finiteNumber(placement.top),
    width: finiteNumber(placement.width),
    height: Math.max(1, finiteNumber(placement.height, 16)),
  };
}

// The em size that puts the host face on the device's own font box.
export function fontForLayout(placement, command, typography = {}) {
  const {
    fontFamily = DEFAULT_FONT_FAMILY,
    regularWeight = 600,
    boldWeight = 700,
  } = typography;
  const fontName = safeText(commandField(command, ["font", "font_name"], -1, ""));
  const weight = /bold/i.test(fontName) || command?.bold ? boldWeight : regularWeight;
  return `${weight} ${placement.height}px ${fontFamily}`;
}

// How much room the device gave this glyph before the next pen position.
export function glyphAdvance(placement, index) {
  const next = placement.pen[index + 1];
  if (next !== undefined) return next - placement.pen[index];
  return placement.left + placement.width - placement.pen[index];
}

// The host face is not the panel's face, so a glyph can be wider than the
// advance the device reserved for it. Condense it into that advance instead of
// letting neighbours collide: the reader then sees the device's real density.
export function drawGlyph(context, character, penX, baseline, advance) {
  const measured =
    typeof context.measureText === "function" ? Number(context.measureText(character)?.width) : 0;
  if (Number.isFinite(measured) && measured > 0 && advance > 0 && measured > advance) {
    context.save();
    context.translate(penX, baseline);
    context.scale(advance / measured, 1);
    context.fillText(character, 0, 0);
    context.restore();
    return;
  }
  context.fillText(character, penX, baseline);
}

export function applyTextDatum(context, datum) {
  const normalized = safeText(datum, "middle_center").toLowerCase();
  context.textAlign = normalized.includes("left")
    ? "left"
    : normalized.includes("right")
      ? "right"
      : "center";
  context.textBaseline = normalized.includes("top")
    ? "top"
    : normalized.includes("bottom")
      ? "bottom"
      : "middle";
}

export function roundedRectanglePath(context, x, y, width, height, radius) {
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

// Opacity the device glass should have for a snapshot: a sleeping panel is
// dark, otherwise the firmware's own brightness drives it.
export function screenOpacity(screen = {}, frame = {}) {
  if (boolValue(screen?.sleeping)) return 0;
  return clamp(screen?.brightness ?? frame?.brightness ?? 100, 0, 100) / 100;
}

/**
 * Replay one published frame onto a 2D canvas context.
 *
 * @param {CanvasRenderingContext2D} context destination, sized DEVICE_SIZE².
 * @param {object} frame native ``frame`` snapshot block.
 * @param {object} [typography] optional font family/weight overrides.
 * @returns {{width: number, height: number, commandCount: number}}
 */
export function renderFrame(context, frame, typography = {}) {
  const commands = Array.isArray(frame?.commands) ? frame.commands : [];
  const frameWidth = Math.max(1, finiteNumber(frame?.width, DEVICE_SIZE));
  const frameHeight = Math.max(1, finiteNumber(frame?.height, DEVICE_SIZE));
  const renderState = {
    color: "#ffffff",
    background: "#000000",
    font: "Font2",
    datum: "middle_center",
  };

  context.save();
  context.setTransform(DEVICE_SIZE / frameWidth, 0, 0, DEVICE_SIZE / frameHeight, 0, 0);
  context.fillStyle = "#000000";
  context.fillRect(0, 0, frameWidth, frameHeight);
  context.lineCap = "butt";
  context.lineJoin = "round";

  for (const command of commands) {
    const name = commandName(command);
    if (!name) continue;

    if (name === "settextcolor") {
      renderState.color = colorValue(
        commandField(command, ["color", "foreground", "fg"], 0),
        renderState.color,
      );
      renderState.background = colorValue(
        commandField(command, ["background", "bg"], 1),
        renderState.background,
      );
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
        context.lineWidth = Math.max(
          1,
          finiteNumber(commandField(command, ["line_width", "stroke_width"], 4), 1),
        );
        context.stroke();
      }
      continue;
    }

    if (name === "drawarc") {
      const x = finiteNumber(commandField(command, ["x", "cx", "center_x"], 0));
      const y = finiteNumber(commandField(command, ["y", "cy", "center_y"], 1));
      const outer = Math.max(
        0,
        finiteNumber(
          commandField(command, ["outer_radius", "outer_r", "outer", "r_outer", "r1"], 2),
        ),
      );
      const inner = Math.max(
        0,
        finiteNumber(
          commandField(command, ["inner_radius", "inner_r", "inner", "r_inner", "r2"], 3),
        ),
      );
      const start = finiteNumber(commandField(command, ["start", "start_angle", "angle_start"], 4));
      let end = finiteNumber(commandField(command, ["end", "end_angle", "angle_end"], 5));
      const color = colorValue(commandField(command, ["color"], 6), renderState.color);
      if (end < start) end += 360;
      context.beginPath();
      context.arc(
        x,
        y,
        (outer + inner) / 2,
        ((start - 90) * Math.PI) / 180,
        ((end - 90) * Math.PI) / 180,
        false,
      );
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
      const color = colorValue(
        commandField(command, ["color", "foreground", "fg"], 3),
        renderState.color,
      );
      const datum = commandField(command, ["datum", "text_datum"], -1, renderState.datum);
      context.save();
      context.fillStyle = color;
      const placement = deviceLayout(command);
      if (placement) {
        // The device measured this string with its own font. Put every glyph on
        // that pen grid so the panel and the viewer wrap, clip, and overflow at
        // the same pixel — the browser only supplies letterforms.
        context.font = fontForLayout(placement, command, typography);
        context.textAlign = "left";
        context.textBaseline = "alphabetic";
        const glyphs = printableCharacters(text);
        for (let index = 0; index < glyphs.length; index += 1) {
          const penX = placement.pen[index];
          if (penX === undefined) break;
          drawGlyph(context, glyphs[index], penX, placement.baseline, glyphAdvance(placement, index));
        }
      } else {
        context.font = fontForCommand(command, renderState, typography);
        applyTextDatum(context, datum);
        context.fillText(text, x, y);
      }
      context.restore();
    }
  }
  context.restore();

  return { width: frameWidth, height: frameHeight, commandCount: commands.length };
}
