import assert from "node:assert/strict";
import test from "node:test";
import { simulatorClient } from "../src/simulatorClient.js";

function jsonResponse(body) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

test("HTTP transport uses the exact firmware and simulator API contracts", async (context) => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const calls = [];
  context.after(() => {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  });

  delete globalThis.window;
  globalThis.fetch = async (path, options = {}) => {
    calls.push({ path, options });
    if (path === "/api/firmwares") {
      return jsonResponse({ active: "10_sokkon", firmwares: [{ id: "10_sokkon", label: "SOKKON" }] });
    }
    return jsonResponse({ revision: calls.length, firmware: { id: "99_stopwatch" }, frame: {} });
  };

  assert.equal(simulatorClient.transport(), "http");
  assert.equal((await simulatorClient.firmwares()).active, "10_sokkon");
  await simulatorClient.selectFirmware("99_stopwatch");
  await simulatorClient.action("focus");
  await simulatorClient.configure({ battery_percent: 72, charging: true });
  await simulatorClient.advance(6001);

  assert.deepEqual(calls.map((call) => call.path), [
    "/api/firmwares",
    "/api/firmware",
    "/api/action",
    "/api/scenario",
    "/api/action",
  ]);
  assert.deepEqual(JSON.parse(calls[1].options.body), { firmware: "99_stopwatch" });
  assert.deepEqual(JSON.parse(calls[2].options.body), { action: "focus" });
  assert.deepEqual(JSON.parse(calls[3].options.body), { battery_percent: 72, charging: true });
  assert.deepEqual(JSON.parse(calls[4].options.body), { action: "advance_6s" });
});

test("native typed bridge takes priority over HTTP without exposing raw commands", async (context) => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const calls = [];
  context.after(() => {
    if (originalWindow === undefined) delete globalThis.window;
    else globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  });

  const snapshot = { revision: 3, firmware: { id: "99_stopwatch" }, frame: {} };
  globalThis.window = {
    m5stackSimulator: {
      available: true,
      capabilities: async () => ({ bridgeVersion: 1, firmware: [{ id: "99_stopwatch", label: "STOPWATCH" }] }),
      snapshot: async () => snapshot,
      selectFirmware: async (id) => (calls.push(["selectFirmware", id]), snapshot),
      action: async (name) => (calls.push(["action", name]), snapshot),
      reset: async () => (calls.push(["reset"]), snapshot),
      advance: async (milliseconds) => (calls.push(["advance", milliseconds]), snapshot),
      configure: async (key, value) => (calls.push(["configure", key, value]), snapshot),
    },
  };
  globalThis.fetch = async () => {
    throw new Error("HTTP must not be used while the native bridge is available");
  };

  assert.equal(simulatorClient.transport(), "native");
  assert.equal((await simulatorClient.firmwares()).active, "99_stopwatch");
  await simulatorClient.selectFirmware("10_sokkon");
  await simulatorClient.action("mark");
  await simulatorClient.reset();
  await simulatorClient.advance(10000);
  await simulatorClient.configure({ battery_percent: 91, charging: false });

  assert.deepEqual(calls, [
    ["selectFirmware", "10_sokkon"],
    ["action", "mark"],
    ["reset"],
    ["advance", 10000],
    ["configure", "battery_percent", 91],
    ["configure", "charging", false],
  ]);
});

test("client rejects values outside the fixed native protocol", async () => {
  await assert.rejects(() => simulatorClient.selectFirmware("../firmware"), /Unsupported firmware/);
  await assert.rejects(() => simulatorClient.action("shell"), /Unsupported action/);
  await assert.rejects(() => simulatorClient.configure({ arbitrary_command: "rm" }), /Unsupported configuration key/);
  await assert.rejects(() => simulatorClient.advance(-1), /positive integer/);
});
