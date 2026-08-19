import assert from "node:assert/strict";
import test from "node:test";
import { createNativeLogWatermark, latestOrderedEvents, nativeLogsAfterWatermark } from "../src/timeline.js";

function snapshot(revision, log, firmware = "99_stopwatch") {
  return { revision, firmware: { id: firmware }, log };
}

function entry(index) {
  return { time: index, kind: "INPUT", message: `event-${index}` };
}

test("timeline clear hides the current log and reveals appended entries", () => {
  const before = snapshot(8, [entry(1), entry(2)]);
  const watermark = createNativeLogWatermark(before);

  assert.deepEqual(nativeLogsAfterWatermark(before, watermark), []);
  assert.deepEqual(
    nativeLogsAfterWatermark(snapshot(9, [entry(1), entry(2), entry(3)]), watermark),
    [entry(3)],
  );
});

test("timeline clear follows a capped rolling 120-entry native log", () => {
  const original = Array.from({ length: 120 }, (_, index) => entry(index));
  const watermark = createNativeLogWatermark(snapshot(120, original));

  const rolledOnce = [...original.slice(1), entry(120)];
  assert.deepEqual(
    nativeLogsAfterWatermark(snapshot(121, rolledOnce), watermark),
    [entry(120)],
  );

  const entirelyNewWindow = Array.from({ length: 120 }, (_, index) => entry(index + 120));
  assert.deepEqual(
    nativeLogsAfterWatermark(snapshot(240, entirelyNewWindow), watermark),
    entirelyNewWindow,
  );
});

test("new firmware generation is not hidden by the previous watermark", () => {
  const watermark = createNativeLogWatermark(snapshot(42, [entry(1), entry(2)]));
  const rebooted = snapshot(1, [entry(1)], "99_stopwatch");
  const switched = snapshot(43, [entry(1)], "10_sokkon");

  assert.deepEqual(nativeLogsAfterWatermark(rebooted, watermark), [entry(1)]);
  assert.deepEqual(nativeLogsAfterWatermark(switched, watermark), [entry(1)]);
});

test("a newly observed native event remains visible after seven local events", () => {
  const localEvents = Array.from({ length: 7 }, (_, index) => ({
    source: "local",
    order: index + 1,
  }));
  const newNativeEvent = { source: "native", order: 8 };

  const visible = latestOrderedEvents([newNativeEvent, ...localEvents], 7);
  assert.equal(visible.at(-1), newNativeEvent);
  assert.equal(visible.some((event) => event.source === "native"), true);
});
