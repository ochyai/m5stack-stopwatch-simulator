// Native simulator adapter for firmware/apps/99_stopwatch.
//
// This firmware has no host protocol: it is a self-contained stopwatch.  The
// adapter therefore only supplies inputs, drives the production loop, and
// reports what that loop drew.

#include "sim_host.hpp"

#ifndef SIMULATOR_PRODUCTION_MAIN
#define SIMULATOR_PRODUCTION_MAIN "../../firmware/apps/99_stopwatch/main.cpp"
#endif
#include SIMULATOR_PRODUCTION_MAIN

namespace stopwatch_host {

constexpr uint64_t kMaximumAdvanceMs = 600001;

constexpr sim_host::FirmwareIdentity kIdentity = {
    /*id=*/"99_stopwatch",
    /*label=*/"STOPWATCH",
    /*subtitle=*/"PRODUCTION C++",
    /*shell_subtitle=*/"NATIVE FIRMWARE",
    /*heading=*/"時間を、そのまま測る。",
    /*primary_label=*/"START / PAUSE",
    /*secondary_label=*/"RESET",
    /*touch_label=*/"START / PAUSE",
    /*primary_aria=*/"ストップウォッチを開始または一時停止",
    /*secondary_aria=*/"ストップウォッチをリセット",
    /*touch_aria=*/"ストップウォッチを開始または一時停止",
    /*state_semantics=*/"stopwatch",
    /*host_controls=*/false,
};

class StopwatchHost final : public sim_host::Host {
 public:
  StopwatchHost() {
    // This firmware is never host-driven; the scenario panel describes a
    // standalone device.
    scenario.connected = false;
    scenario.context = "STOPWATCH";
    scenario.detail = "PRODUCTION C++";
  }

 protected:
  void initialize() override {
    auto& state = sokkon_sim::runtime();
    state.battery_percent = scenario.battery_percent;
    state.charging = scenario.charging;
    setup();
    processDeviceOutput();
    advanceRuntimeByMs(40);
  }

  void syncWallClock() override {
    fastForwardIdleRuntimeByUs(
        wall_clock.takeScaledUs(scenario.time_scale, sim_host::remainingVirtualUs()));
  }

  void performAction(const std::string& action) override {
    auto& state = sokkon_sim::runtime();
    if (action == "MARK") {
      state.button_a = true;
      runFirmwareLoop();
      log.add("INPUT", "A / START-PAUSE");
    } else if (action == "MODE") {
      state.button_b = true;
      runFirmwareLoop();
      log.add("INPUT", "B / RESET");
    } else if (action == "FOCUS") {
      state.touch_x = M5.Display.width() / 2;
      state.touch_y = M5.Display.height() / 2;
      state.touch_pressed = true;
      runFirmwareLoop();
      state.touch_pressed = false;
      runFirmwareLoop();
      log.add("INPUT", "TOUCH / START-PAUSE");
    } else if (action == "WAKE") {
      // This firmware has no sleep state. A wake request must not masquerade as
      // a touch and unexpectedly toggle a running stopwatch.
      log.add("INPUT", "WAKE / NO-OP");
      return;
    } else {
      command_error = "unsupported action";
      return;
    }
    // The production app redraws at 30 fps. Run its actual loop across one
    // frame boundary instead of manufacturing a browser-side state update.
    advanceRuntimeByMs(40);
  }

  void advance(uint64_t milliseconds) override { advanceRuntimeByMs(milliseconds); }

  void configure(const std::string& key, const std::string& value) override {
    if (key == "CONNECTED") {
      bool requested_connection = false;
      if (!sim_host::parseBoolean(value, &requested_connection)) {
        throw std::invalid_argument("CONNECTED must be boolean");
      }
      // A standalone firmware cannot be connected to a host, whatever the UI
      // requests. Report the truth rather than a scenario the device ignores.
      scenario.connected = false;
    } else if (key == "HOST_MODE") {
      scenario.host_mode = value;
    } else if (!sim_host::applyCommonScenarioField(scenario, key, value)) {
      throw std::invalid_argument("unsupported configuration key");
    }

    if (key == "BATTERY_PERCENT" || key == "CHARGING") {
      // Configuration is an observation change, not virtual elapsed time.
      // Refresh the production canvas with the HAL values at the current clock.
      battery_percent = scenario.battery_percent;
      charging = scenario.charging;
      drawUi(stopwatch.elapsedUs(nowMicros()));
    }
  }

  uint64_t maximumAdvanceMs() const override { return kMaximumAdvanceMs; }

  std::string snapshotJson() override {
    const auto& state = sokkon_sim::runtime();
    const uint64_t elapsed_us = stopwatch.elapsedUs(nowMicros());
    char elapsed_text[24];
    c152::formatElapsed(elapsed_us, elapsed_text, sizeof(elapsed_text));

    std::ostringstream output;
    appendCommonPrefix(output, kIdentity);

    output << ",\"screen\":{\"connected\":false,\"status\":\"NATIVE\""
           << ",\"battery_percent\":" << battery_percent
           << ",\"charging\":" << (charging ? "true" : "false")
           << ",\"brightness\":" << state.brightness
           << ",\"sleeping\":false,\"time\":" << sim_host::jsonEscape(rtc_text)
           << ",\"mode\":\"STOPWATCH\""
           << ",\"context\":\"99 / STOPWATCH\""
           << ",\"detail\":\"COMPILED PRODUCTION C++\""
           << ",\"focus_running\":" << (stopwatch.isRunning() ? "true" : "false")
           << ",\"elapsed_ms\":" << elapsed_us / 1000ULL
           << ",\"elapsed_text\":" << sim_host::jsonEscape(elapsed_text)
           << ",\"marks\":0,\"toast\":\"\"}";

    output << ",\"pending\":[]";

    appendCommonSuffix(output);
    return output.str();
  }

 private:
  void processDeviceOutput() {
    auto& lines = sokkon_sim::runtime().device_lines;
    while (processed_device_lines_ < lines.size()) {
      log.add("SERIAL", lines[processed_device_lines_++]);
    }
  }

  void runFirmwareLoop() {
    const uint64_t before = sokkon_sim::micros64();
    loop();
    if (sokkon_sim::micros64() == before) {
      // A cooperative Arduino loop should yield with delay(), but force one
      // virtual millisecond so an accidental busy loop cannot hang the host.
      sokkon_sim::advanceMs(1);
    }
    processDeviceOutput();
  }

  void advanceRuntimeTo(uint64_t target_us) {
    auto& state = sokkon_sim::runtime();
    const uint64_t previous_limit = state.advance_limit_us;
    state.advance_limit_us = target_us;
    while (state.now_us < target_us) runFirmwareLoop();
    state.advance_limit_us = previous_limit;
  }

  void advanceRuntimeByMs(uint64_t milliseconds) {
    const uint64_t delta_us = sim_host::millisecondsToUs(milliseconds);
    advanceRuntimeTo(sokkon_sim::runtime().now_us +
                     std::min(delta_us, sim_host::remainingVirtualUs()));
  }

  void fastForwardIdleRuntimeByUs(uint64_t delta_us) {
    auto& state = sokkon_sim::runtime();
    if (delta_us == 0) return;

    // There are no queued asynchronous events in this firmware. During an
    // input-free wall-clock interval, the stopwatch is a function of now_us and
    // the other time-driven branches only refresh sensors, drawing, and haptic
    // expiry. Jump to the interval boundary and run the real production loop
    // once there. This is equivalent at the observable boundary and avoids
    // millions of 2 ms loop iterations at high time scales.
    const uint64_t target_us = state.now_us + delta_us;
    const uint64_t previous_limit = state.advance_limit_us;
    state.advance_limit_us = target_us;
    state.now_us = target_us;
    runFirmwareLoop();
    state.advance_limit_us = previous_limit;
  }

  size_t processed_device_lines_ = 0;
};

}  // namespace stopwatch_host

int main() {
  stopwatch_host::StopwatchHost host;
  return host.run();
}
