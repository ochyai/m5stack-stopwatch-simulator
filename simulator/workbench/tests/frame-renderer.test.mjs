// Behavioural contract for the one draw-command interpreter shared by the
// bundled static UI and this Workbench.  These checks run without a browser by
// recording every 2D context call the renderer makes.

import assert from "node:assert/strict";
import test from "node:test";

import {
  DEVICE_SIZE,
  colorValue,
  commandName,
  renderFrame,
  screenOpacity,
} from "../../static/frame-renderer.js";

function recordingContext() {
  const calls = [];
  const state = {};
  const record = (name) => (...args) => calls.push([name, ...args]);
  const context = {
    calls,
    state,
    save: record("save"),
    restore: record("restore"),
    setTransform: record("setTransform"),
    fillRect: record("fillRect"),
    beginPath: record("beginPath"),
    moveTo: record("moveTo"),
    arc: record("arc"),
    arcTo: record("arcTo"),
    closePath: record("closePath"),
    fill: record("fill"),
    stroke: record("stroke"),
    fillText: record("fillText"),
    translate: record("translate"),
    scale: record("scale"),
    // A host face is wider than the device's advance grid; make that concrete.
    measureText: (character) => ({ width: character.length * 12 }),
  };
  for (const property of [
    "fillStyle",
    "strokeStyle",
    "lineWidth",
    "lineCap",
    "lineJoin",
    "font",
    "textAlign",
    "textBaseline",
  ]) {
    Object.defineProperty(context, property, {
      get: () => state[property],
      set: (value) => {
        state[property] = value;
        calls.push([`set:${property}`, value]);
      },
    });
  }
  return context;
}

function callsNamed(context, name) {
  return context.calls.filter((call) => call[0] === name);
}

test("frames scale to the device canvas and start from a cleared panel", () => {
  const context = recordingContext();
  const result = renderFrame(context, { width: 233, height: 233, commands: [] });

  assert.deepEqual(result, { width: 233, height: 233, commandCount: 0 });
  assert.deepEqual(context.calls[1], ["setTransform", 2, 0, 0, 2, 0, 0]);
  assert.deepEqual(callsNamed(context, "fillRect")[0], ["fillRect", 0, 0, 233, 233]);
  assert.equal(DEVICE_SIZE, 466);
});

test("a missing frame still clears the panel at device resolution", () => {
  const context = recordingContext();
  const result = renderFrame(context, undefined);

  assert.equal(result.commandCount, 0);
  assert.deepEqual(context.calls[1], ["setTransform", 1, 0, 0, 1, 0, 0]);
});

test("native RGB565 integers become the device's colour", () => {
  // 0xF800 is pure red in RGB565, exactly what the firmware sends.
  assert.equal(colorValue(0xf800), "rgb(255, 0, 0)");
  assert.equal(colorValue(0x07e0), "rgb(0, 255, 0)");
  assert.equal(colorValue(0x10000), "#010000");
  assert.equal(colorValue("TFT_RED"), "#ff0000");
  assert.equal(colorValue("nonsense", "#123456"), "#123456");
});

test("command names are matched regardless of casing or separators", () => {
  assert.equal(commandName({ op: "fillRoundRect" }), "fillroundrect");
  assert.equal(commandName({ type: "fill_round_rect" }), "fillroundrect");
  assert.equal(commandName(["draw-string", "hi"]), "drawstring");
  assert.equal(commandName({}), "");
});

test("drawArc strokes the band midline with the band's own width", () => {
  const context = recordingContext();
  renderFrame(context, {
    width: DEVICE_SIZE,
    height: DEVICE_SIZE,
    commands: [
      {
        op: "drawArc",
        x: 233,
        y: 233,
        outer_radius: 220,
        inner_radius: 200,
        start: 0,
        end: 90,
        color: 0xffff,
      },
    ],
  });

  const [, x, y, radius, start, end] = callsNamed(context, "arc")[0];
  assert.equal(x, 233);
  assert.equal(y, 233);
  assert.equal(radius, 210);
  assert.equal(start, (-90 * Math.PI) / 180);
  assert.equal(end, 0);
  assert.equal(context.state.lineWidth, 21);
  assert.equal(context.state.lineCap, "butt");
  assert.equal(callsNamed(context, "stroke").length, 1);
});

test("drawArc wrapping past zero degrees sweeps forward, never backwards", () => {
  const context = recordingContext();
  renderFrame(context, {
    commands: [{ op: "drawArc", x: 0, y: 0, r1: 10, r2: 8, start: 300, end: 60 }],
  });

  const [, , , , start, end] = callsNamed(context, "arc")[0];
  assert.ok(end > start);
  assert.equal(Math.round(((end - start) * 180) / Math.PI), 120);
});

test("fillRoundRect keeps its corner radius when roundRect is unavailable", () => {
  const context = recordingContext();
  renderFrame(context, {
    commands: [{ op: "fillRoundRect", x: 10, y: 20, w: 100, h: 40, r: 12, color: 0xffff }],
  });

  const arcs = callsNamed(context, "arcTo");
  assert.equal(arcs.length, 4);
  assert.deepEqual(callsNamed(context, "moveTo")[0], ["moveTo", 22, 20]);
  // A radius wider than half the box would invert the path.
  assert.equal(arcs[0].at(-1), 12);
  assert.equal(callsNamed(context, "fill").length, 1);
});

test("an oversized corner radius is clamped instead of inverting the path", () => {
  const context = recordingContext();
  renderFrame(context, {
    commands: [{ op: "fillRoundRect", x: 0, y: 0, w: 20, h: 10, r: 999 }],
  });

  assert.equal(callsNamed(context, "arcTo")[0].at(-1), 5);
});

test("drawString honours font size, datum, and the caller's typography", () => {
  const context = recordingContext();
  renderFrame(
    context,
    {
      commands: [
        { op: "setTextColor", color: 0xffff, background: 0 },
        { op: "setTextDatum", datum: "top_left" },
        { op: "drawString", text: "12:34", x: 40, y: 50, font_size: 48, font: "Font7" },
      ],
    },
    { fontFamily: "ui-rounded", regularWeight: 620, boldWeight: 750 },
  );

  assert.deepEqual(callsNamed(context, "fillText")[0], ["fillText", "12:34", 40, 50]);
  assert.equal(context.state.font, "620 48px ui-rounded");
  assert.equal(context.state.textAlign, "left");
  assert.equal(context.state.textBaseline, "top");
});

test("drawString falls back to the inherited font when no size is published", () => {
  const context = recordingContext();
  renderFrame(context, {
    commands: [
      { op: "setFont", font: "FreeSansBold24pt7b" },
      { op: "drawString", text: "SOKKON", x: 0, y: 0 },
    ],
  });

  assert.equal(context.state.font.startsWith("700 48px"), true);
});

test("unknown commands are skipped without disturbing the frame", () => {
  const context = recordingContext();
  const result = renderFrame(context, {
    commands: [{ op: "drawBitmap" }, {}, { op: "fillCircle", x: 1, y: 2, r: 3, color: 0xffff }],
  });

  assert.equal(result.commandCount, 3);
  assert.equal(callsNamed(context, "arc").length, 1);
  assert.equal(callsNamed(context, "fill").length, 1);
});

test("published device geometry places every glyph on the panel's pen grid", () => {
  const context = recordingContext();
  renderFrame(context, {
    commands: [
      {
        op: "drawString",
        text: "MARK",
        x: 89,
        y: 350,
        font: "Font2",
        datum: "middle_center",
        color: 0xffff,
        layout: { left: 72, top: 342, baseline: 355, width: 34, height: 16, pen: [72, 81, 89, 98] },
      },
    ],
  });

  // Every glyph lands on its own device pen position, on the device baseline.
  const xs = callsNamed(context, "translate").map((call) => call[1]);
  assert.deepEqual(xs, [72, 81, 89, 98]);
  for (const call of callsNamed(context, "translate")) {
    assert.equal(call[2], 355);
  }
  assert.equal(context.state.textAlign, "left");
  assert.equal(context.state.textBaseline, "alphabetic");
  // The font box, not a guessed point size, sets the em.
  assert.ok(context.state.font.includes("16px"));
});

test("a glyph wider than its advance is condensed, never overlapped", () => {
  const context = recordingContext();
  renderFrame(context, {
    commands: [
      {
        op: "drawString",
        text: "AB",
        x: 0,
        y: 0,
        layout: { left: 0, top: 0, baseline: 20, width: 16, height: 20, pen: [0, 8] },
      },
    ],
  });

  // measureText reports 12px for one character while the device reserved 8.
  const scales = callsNamed(context, "scale");
  assert.equal(scales.length, 2);
  for (const call of scales) {
    assert.equal(call[1], 8 / 12);
    assert.equal(call[2], 1);
  }
});

test("a frame without device geometry still draws through the datum path", () => {
  const context = recordingContext();
  renderFrame(context, {
    commands: [
      { op: "setTextDatum", datum: "top_left" },
      { op: "drawString", text: "HI", x: 10, y: 20, font_size: 16 },
    ],
  });

  assert.equal(callsNamed(context, "translate").length, 0);
  assert.deepEqual(callsNamed(context, "fillText")[0], ["fillText", "HI", 10, 20]);
  assert.equal(context.state.textAlign, "left");
});

test("screen opacity reports the panel the firmware actually lit", () => {
  assert.equal(screenOpacity({ sleeping: true, brightness: 100 }), 0);
  assert.equal(screenOpacity({ sleeping: "true" }), 0);
  assert.equal(screenOpacity({ brightness: 40 }), 0.4);
  assert.equal(screenOpacity({}, { brightness: 25 }), 0.25);
  assert.equal(screenOpacity({}, {}), 1);
  assert.equal(screenOpacity({ brightness: 400 }), 1);
});
