// Native simulator adapter for firmware/apps/10_sokkon.
//
// The production main.cpp below is compiled unmodified.  This file only plays
// the part the Mac companion plays on a desk: it answers the device's USB
// protocol, injects host state, and reports what the firmware actually drew.

#include "sim_host.hpp"

#if !defined(SIMULATOR_PRODUCTION_MAIN) && defined(SOKKON_PRODUCTION_MAIN)
#define SIMULATOR_PRODUCTION_MAIN SOKKON_PRODUCTION_MAIN
#endif
#ifndef SIMULATOR_PRODUCTION_MAIN
#define SIMULATOR_PRODUCTION_MAIN "../../firmware/apps/10_sokkon/main.cpp"
#endif
#include SIMULATOR_PRODUCTION_MAIN

namespace sokkon_host {

constexpr uint64_t kMaximumAdvanceMs = 7ULL * 24ULL * 60ULL * 60ULL * 1000ULL;

constexpr sim_host::FirmwareIdentity kIdentity = {
    /*id=*/"10_sokkon",
    /*label=*/"SOKKON",
    /*subtitle=*/"DIGITAL TWIN",
    /*shell_subtitle=*/"LOCAL FIRST INTERFACE",
    /*heading=*/"いまを、手で扱う。",
    /*primary_label=*/"MARK",
    /*secondary_label=*/"MODE",
    /*touch_label=*/"FOCUS",
    /*primary_aria=*/"現在をマーク",
    /*secondary_aria=*/"モードを切り替え",
    /*touch_aria=*/"フォーカスタイマーを開始または一時停止",
    /*state_semantics=*/"sokkon",
    /*host_controls=*/true,
};

struct ScheduledLine {
  uint64_t due_us = 0;
  std::string line;
};

class SokkonHost final : public sim_host::Host {
 protected:
  void initialize() override {
    auto& state = sokkon_sim::runtime();
    state.battery_percent = scenario.battery_percent;
    state.charging = scenario.charging;
    sim_host::applyTilt(scenario.tilt_x, scenario.tilt_y);
    setup();
    processDeviceOutput();
    injectHostState();
    advanceRuntimeByMs(101);
    settleAtCurrentTime();
  }

  void beforeCommand() override {
    if (queueHeartbeatIfDue()) runFirmwareLoop();
    settleAtCurrentTime();
  }

  void settle() override { settleAtCurrentTime(); }

  void syncWallClock() override {
    const uint64_t delta_us =
        wall_clock.takeScaledUs(scenario.time_scale, sim_host::remainingVirtualUs());
    if (delta_us == 0) return;
    advanceRuntimeTo(sokkon_sim::runtime().now_us + delta_us);
    settleAtCurrentTime();
  }

  void performAction(const std::string& action) override {
    if (scenario.connected) injectHostState();

    auto& state = sokkon_sim::runtime();
    if (action == "MARK") {
      state.button_a = true;
      runFirmwareLoop();
    } else if (action == "MODE") {
      state.button_b = true;
      runFirmwareLoop();
      scenario.host_mode = kModes[mode_index];
    } else if (action == "FOCUS" || action == "WAKE") {
      // The named action is the centre of the panel; TOUCH reaches anywhere.
      performTouch(M5.Display.width() / 2, M5.Display.height() / 2);
      return;
    } else {
      command_error = "unsupported action";
      return;
    }
    processDeviceOutput();
    settleInput();
  }

  void runOneLoop() override { runFirmwareLoop(); }

  void settleInput() override {
    processDeviceOutput();
    settleAtCurrentTime();
    advanceRuntimeByMs(101);
    settleAtCurrentTime();
  }

  void advance(uint64_t milliseconds) override {
    advanceRuntimeByMs(milliseconds);
    settleAtCurrentTime();
  }

  void configure(const std::string& key, const std::string& value) override {
    auto& state = sokkon_sim::runtime();
    if (key == "CONNECTED") {
      if (!sim_host::parseBoolean(value, &scenario.connected)) {
        throw std::invalid_argument("CONNECTED must be boolean");
      }
      if (!scenario.connected) {
        scheduled_lines_.clear();
        state.serial_rx.clear();
      }
    } else if (key == "HOST_MODE") {
      if (!validMode(value)) {
        throw std::invalid_argument("unsupported HOST_MODE");
      }
      scenario.host_mode = value;
    } else if (!sim_host::applyCommonScenarioField(scenario, key, value)) {
      throw std::invalid_argument("unsupported configuration key");
    }

    if (scenario.connected) injectHostState();
    // Power values reach the screen on the firmware's one-second sensor tick.
    advanceRuntimeByMs(key == "BATTERY_PERCENT" || key == "CHARGING" ? 1001 : 101);
    settleAtCurrentTime();
  }

  uint64_t maximumAdvanceMs() const override { return kMaximumAdvanceMs; }

  std::string snapshotJson() override {
    const uint32_t now_ms = millis();
    const uint64_t elapsed_ms = focus_timer.elapsedUs(nowMicros()) / 1000ULL;
    char elapsed_text[24];
    c152::formatElapsed(elapsed_ms * 1000ULL, elapsed_text, sizeof(elapsed_text));
    const bool connected = hostConnected(now_ms);
    const bool toast_visible =
        toast_text[0] != '\0' &&
        static_cast<int32_t>(toast_until_ms - now_ms) > 0;
    const auto& state = sokkon_sim::runtime();

    std::ostringstream output;
    appendCommonPrefix(output, kIdentity);

    output << ",\"screen\":{\"connected\":" << (connected ? "true" : "false")
           << ",\"status\":" << sim_host::jsonEscape(connected ? "USB" : "LOCAL")
           << ",\"battery_percent\":" << battery_percent
           << ",\"charging\":" << (charging ? "true" : "false")
           << ",\"brightness\":" << state.brightness
           << ",\"sleeping\":" << (display_sleeping ? "true" : "false")
           << ",\"time\":"
           << sim_host::jsonEscape(connected ? host_time : rtc_text)
           << ",\"mode\":" << sim_host::jsonEscape(kModes[mode_index])
           << ",\"context\":"
           << sim_host::jsonEscape(connected ? context_text : "MAC NOT CONNECTED")
           << ",\"detail\":"
           << sim_host::jsonEscape(connected ? detail_text : "USB-C TO BEGIN")
           << ",\"focus_running\":"
           << (focus_timer.isRunning() ? "true" : "false")
           << ",\"elapsed_ms\":" << elapsed_ms
           << ",\"elapsed_text\":" << sim_host::jsonEscape(elapsed_text)
           << ",\"marks\":" << mark_count
           << ",\"toast\":" << sim_host::jsonEscape(toast_visible ? toast_text : "")
           << '}';

    output << ",\"pending\":[";
    bool first_pending = true;
    for (const PendingEvent& pending : pending_events) {
      if (!pending.active) continue;
      if (!first_pending) output << ',';
      first_pending = false;
      output << "{\"sequence\":" << pending.sequence << ",\"intent\":"
             << sim_host::jsonEscape(intentName(pending.intent))
             << ",\"accepted\":" << (pending.accepted ? "true" : "false") << '}';
    }
    output << ']';

    appendCommonSuffix(output);
    return output.str();
  }

 private:
  static bool validMode(const std::string& value) {
    for (const char* mode : kModes) {
      if (value == mode) return true;
    }
    return false;
  }

  void queueHostInput(const std::string& line) {
    auto& input = sokkon_sim::runtime().serial_rx;
    for (const char character : line) input.push_back(character);
    input.push_back('\n');
    log.add("RX", line);
  }

  void scheduleHostResponse(const std::string& line, uint64_t delay_ms) {
    scheduled_lines_.push_back({sokkon_sim::micros64() + delay_ms * 1000ULL, line});
    std::stable_sort(scheduled_lines_.begin(), scheduled_lines_.end(),
                     [](const ScheduledLine& left, const ScheduledLine& right) {
                       return left.due_us < right.due_us;
                     });
  }

  // Answer the device exactly like the Mac companion: acknowledge the event,
  // then deliver the configured outcome after the configured latency.
  void processDeviceOutput() {
    auto& lines = sokkon_sim::runtime().device_lines;
    while (processed_device_lines_ < lines.size()) {
      const std::string line = lines[processed_device_lines_++];
      log.add("TX", line);
      const std::vector<std::string> fields = sim_host::splitPipe(line);
      if (fields.size() < 4 || fields[0] != "EVENT") continue;

      const std::string& session = fields[2];
      const std::string& sequence = fields[3];
      scheduleHostResponse("ACK|" + session + "|" + sequence + "|ACCEPTED",
                           scenario.latency_ms);
      if (scenario.outcome == "OK") {
        scheduleHostResponse("RESULT|" + session + "|" + sequence + "|OK",
                             scenario.latency_ms);
      } else if (scenario.outcome == "ERROR") {
        scheduleHostResponse(
            "RESULT|" + session + "|" + sequence + "|ERROR|SIMULATED",
            scenario.latency_ms);
      }
    }
  }

  void runFirmwareLoop() {
    loop();
    processDeviceOutput();
  }

  void consumeHostInput() {
    if (sokkon_sim::runtime().serial_rx.empty()) return;
    runFirmwareLoop();
    processDeviceOutput();
  }

  bool deliverScheduledLines() {
    if (!scenario.connected) {
      scheduled_lines_.clear();
      return false;
    }
    bool delivered = false;
    const uint64_t now_us = sokkon_sim::micros64();
    while (!scheduled_lines_.empty() &&
           scheduled_lines_.front().due_us <= now_us) {
      queueHostInput(scheduled_lines_.front().line);
      scheduled_lines_.erase(scheduled_lines_.begin());
      delivered = true;
    }
    return delivered;
  }

  std::string hostStateLine() const {
    return "STATE|12:34|" + scenario.host_mode + "|" +
           sim_host::protocolSafe(scenario.context) + "|" +
           sim_host::protocolSafe(scenario.detail);
  }

  void injectHostState() {
    if (!scenario.connected) return;
    queueHostInput("PING");
    queueHostInput(hostStateLine());
    consumeHostInput();
  }

  bool queueHeartbeatIfDue() {
    if (!scenario.connected) return false;
    const uint32_t now_ms = millis();
    if (host_seen && now_ms - last_host_ms < 1000U) return false;
    queueHostInput("PING");
    queueHostInput(hostStateLine());
    return true;
  }

  void advanceRuntimeTo(uint64_t target_us) {
    auto& state = sokkon_sim::runtime();
    while (state.now_us < target_us) {
      deliverScheduledLines();
      queueHeartbeatIfDue();
      runFirmwareLoop();
    }

    // A response can become due on the final 2 ms production-loop tick.  Give
    // that serial input one loop before exposing the snapshot.
    const bool delivered = deliverScheduledLines();
    const bool heartbeat = queueHeartbeatIfDue();
    if (delivered || heartbeat || !state.serial_rx.empty()) {
      runFirmwareLoop();
    }
  }

  void advanceRuntimeByMs(uint64_t milliseconds) {
    const uint64_t delta_us = sim_host::millisecondsToUs(milliseconds);
    advanceRuntimeTo(sokkon_sim::runtime().now_us +
                     std::min(delta_us, sim_host::remainingVirtualUs()));
  }

  void settleAtCurrentTime() {
    for (int iteration = 0; iteration < 4; ++iteration) {
      const bool delivered = deliverScheduledLines();
      if (delivered || !sokkon_sim::runtime().serial_rx.empty()) {
        consumeHostInput();
        continue;
      }
      break;
    }
  }

  std::vector<ScheduledLine> scheduled_lines_;
  size_t processed_device_lines_ = 0;
};

}  // namespace sokkon_host

int main() {
  sokkon_host::SokkonHost host;
  return host.run();
}
