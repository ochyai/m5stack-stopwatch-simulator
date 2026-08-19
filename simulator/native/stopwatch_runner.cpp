#include "sim_runtime.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace sokkon_sim {

Runtime& runtime() {
  static Runtime state;
  return state;
}

void serialWrite(const char* data, size_t size) {
  if (data == nullptr || size == 0) return;
  auto& state = runtime();
  for (size_t index = 0; index < size; ++index) {
    const char value = data[index];
    if (value == '\r') continue;
    if (value == '\n') {
      if (!state.serial_partial.empty()) {
        state.device_lines.push_back(state.serial_partial);
        state.serial_partial.clear();
      }
    } else {
      state.serial_partial.push_back(value);
    }
  }
}

}  // namespace sokkon_sim

#ifndef SIMULATOR_PRODUCTION_MAIN
#define SIMULATOR_PRODUCTION_MAIN "../../firmware/apps/99_stopwatch/main.cpp"
#endif
#include SIMULATOR_PRODUCTION_MAIN

namespace stopwatch_host {

using Clock = std::chrono::steady_clock;

struct Scenario {
  bool connected = false;
  std::string outcome = "OK";
  uint64_t latency_ms = 400;
  std::string context = "STOPWATCH";
  std::string detail = "PRODUCTION C++";
  std::string host_mode = "NOW";
  int battery_percent = 84;
  bool charging = false;
  double time_scale = 1.0;
};

struct LogEntry {
  uint64_t at_ms = 0;
  std::string kind;
  std::string message;
};

Scenario scenario;
std::vector<LogEntry> event_log;
size_t processed_device_lines = 0;
uint64_t revision = 0;
std::string command_error;
Clock::time_point last_wall = Clock::now();
long double wall_fraction_us = 0.0L;
constexpr uint64_t kMaximumAdvanceMs = 600001;

std::string jsonEscape(std::string_view value) {
  std::ostringstream output;
  output << '"';
  for (const unsigned char character : value) {
    switch (character) {
      case '"':
        output << "\\\"";
        break;
      case '\\':
        output << "\\\\";
        break;
      case '\b':
        output << "\\b";
        break;
      case '\f':
        output << "\\f";
        break;
      case '\n':
        output << "\\n";
        break;
      case '\r':
        output << "\\r";
        break;
      case '\t':
        output << "\\t";
        break;
      default:
        if (character < 0x20) {
          output << "\\u" << std::hex << std::setw(4) << std::setfill('0')
                 << static_cast<int>(character) << std::dec;
        } else {
          output << static_cast<char>(character);
        }
    }
  }
  output << '"';
  return output.str();
}

void addLog(std::string kind, std::string message) {
  event_log.push_back(
      {static_cast<uint64_t>(millis()), std::move(kind), std::move(message)});
  if (event_log.size() > 120) {
    event_log.erase(
        event_log.begin(),
        event_log.begin() +
            static_cast<std::ptrdiff_t>(event_log.size() - 120));
  }
}

void processDeviceOutput() {
  auto& lines = sokkon_sim::runtime().device_lines;
  while (processed_device_lines < lines.size()) {
    addLog("SERIAL", lines[processed_device_lines++]);
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
  auto& state = sokkon_sim::runtime();
  const uint64_t delta_us =
      milliseconds > std::numeric_limits<uint64_t>::max() / 1000ULL
          ? std::numeric_limits<uint64_t>::max()
          : milliseconds * 1000ULL;
  const uint64_t maximum_delta =
      std::numeric_limits<uint64_t>::max() - state.now_us;
  advanceRuntimeTo(state.now_us + std::min(delta_us, maximum_delta));
}

void fastForwardIdleRuntimeByUs(uint64_t delta_us) {
  auto& state = sokkon_sim::runtime();
  const uint64_t maximum_delta =
      std::numeric_limits<uint64_t>::max() - state.now_us;
  const uint64_t bounded_delta = std::min(delta_us, maximum_delta);
  if (bounded_delta == 0) return;

  // There are no queued asynchronous events in this firmware. During an
  // input-free wall-clock interval, the stopwatch is a function of now_us and
  // the other time-driven branches only refresh sensors, drawing, and haptic
  // expiry. Jump to the interval boundary and run the real production loop
  // once there. This is equivalent at the observable boundary and avoids
  // millions of 2 ms loop iterations at high time scales.
  const uint64_t target_us = state.now_us + bounded_delta;
  const uint64_t previous_limit = state.advance_limit_us;
  state.advance_limit_us = target_us;
  state.now_us = target_us;
  runFirmwareLoop();
  state.advance_limit_us = previous_limit;
}

void syncWallClock() {
  const Clock::time_point now = Clock::now();
  const auto elapsed =
      std::chrono::duration_cast<std::chrono::microseconds>(now - last_wall)
          .count();
  last_wall = now;
  if (elapsed <= 0 || scenario.time_scale <= 0.0) return;
  const long double scaled =
      static_cast<long double>(elapsed) *
          static_cast<long double>(scenario.time_scale) +
      wall_fraction_us;
  const uint64_t maximum = std::numeric_limits<uint64_t>::max() -
                           sokkon_sim::runtime().now_us;
  const uint64_t delta_us =
      scaled >= static_cast<long double>(maximum)
          ? maximum
          : static_cast<uint64_t>(scaled);
  wall_fraction_us = delta_us == maximum
                         ? 0.0L
                         : scaled - static_cast<long double>(delta_us);
  fastForwardIdleRuntimeByUs(delta_us);
}

void performAction(const std::string& action) {
  auto& state = sokkon_sim::runtime();
  if (action == "MARK") {
    state.button_a = true;
    runFirmwareLoop();
    addLog("INPUT", "A / START-PAUSE");
  } else if (action == "MODE") {
    state.button_b = true;
    runFirmwareLoop();
    addLog("INPUT", "B / RESET");
  } else if (action == "FOCUS") {
    state.touch_x = M5.Display.width() / 2;
    state.touch_y = M5.Display.height() / 2;
    state.touch_pressed = true;
    runFirmwareLoop();
    state.touch_pressed = false;
    runFirmwareLoop();
    addLog("INPUT", "TOUCH / START-PAUSE");
  } else if (action == "WAKE") {
    // This firmware has no sleep state. A wake request must not masquerade as
    // a touch and unexpectedly toggle a running stopwatch.
    addLog("INPUT", "WAKE / NO-OP");
    return;
  } else {
    command_error = "unsupported action";
    return;
  }
  // The production app redraws at 30 fps. Run its actual loop across one
  // frame boundary instead of manufacturing a browser-side state update.
  advanceRuntimeByMs(40);
}

bool parseBoolean(const std::string& value, bool* output) {
  if (value == "1" || value == "true" || value == "TRUE") {
    *output = true;
    return true;
  }
  if (value == "0" || value == "false" || value == "FALSE") {
    *output = false;
    return true;
  }
  return false;
}

uint64_t parseUnsigned(const std::string& value, uint64_t maximum) {
  if (value.empty()) throw std::invalid_argument("empty integer");
  size_t consumed = 0;
  const unsigned long long parsed = std::stoull(value, &consumed, 10);
  if (consumed != value.size() || parsed > maximum) {
    throw std::out_of_range("integer outside range");
  }
  return static_cast<uint64_t>(parsed);
}

void configure(const std::string& key, const std::string& value) {
  auto& state = sokkon_sim::runtime();
  try {
    if (key == "CONNECTED") {
      bool requested_connection = false;
      if (!parseBoolean(value, &requested_connection)) {
        throw std::invalid_argument("CONNECTED must be boolean");
      }
      scenario.connected = false;
    } else if (key == "OUTCOME") {
      if (value != "OK" && value != "ERROR" && value != "TIMEOUT") {
        throw std::invalid_argument("unsupported OUTCOME");
      }
      scenario.outcome = value;
    } else if (key == "LATENCY_MS") {
      scenario.latency_ms = parseUnsigned(value, 60000);
    } else if (key == "CONTEXT") {
      scenario.context = value;
    } else if (key == "DETAIL") {
      scenario.detail = value;
    } else if (key == "HOST_MODE") {
      scenario.host_mode = value;
    } else if (key == "BATTERY_PERCENT") {
      scenario.battery_percent =
          static_cast<int>(parseUnsigned(value, 100));
      state.battery_percent = scenario.battery_percent;
    } else if (key == "CHARGING") {
      if (!parseBoolean(value, &scenario.charging)) {
        throw std::invalid_argument("CHARGING must be boolean");
      }
      state.charging = scenario.charging;
    } else if (key == "TIME_SCALE") {
      size_t consumed = 0;
      const double parsed = std::stod(value, &consumed);
      if (consumed != value.size() || !std::isfinite(parsed) || parsed < 0.01 ||
          parsed > 1000.0) {
        throw std::invalid_argument("TIME_SCALE outside range");
      }
      scenario.time_scale = parsed;
    } else {
      throw std::invalid_argument("unsupported configuration key");
    }
  } catch (const std::exception& error) {
    command_error = error.what();
    return;
  }

  if (key == "BATTERY_PERCENT" || key == "CHARGING") {
    // Configuration is an observation change, not virtual elapsed time.
    // Refresh the production canvas with the HAL values at the current clock.
    battery_percent = scenario.battery_percent;
    charging = scenario.charging;
    drawUi(stopwatch.elapsedUs(nowMicros()));
  }
}

void appendDrawCommand(std::ostringstream& output,
                       const sokkon_sim::DrawCommand& command) {
  output << "{\"op\":" << jsonEscape(command.op);
  if (command.op == "fillScreen") {
    output << ",\"color\":" << command.color;
  } else if (command.op == "drawCircle" || command.op == "fillCircle") {
    output << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"r\":" << command.r << ",\"color\":" << command.color;
  } else if (command.op == "drawArc") {
    output << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"outer_radius\":" << command.outer_radius
           << ",\"inner_radius\":" << command.inner_radius
           << ",\"start\":" << command.start << ",\"end\":" << command.end
           << ",\"color\":" << command.color;
  } else if (command.op == "fillRoundRect") {
    output << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"w\":" << command.w << ",\"h\":" << command.h
           << ",\"r\":" << command.r << ",\"color\":" << command.color;
  } else if (command.op == "drawString") {
    output << ",\"text\":" << jsonEscape(command.text)
           << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"font\":" << jsonEscape(command.font)
           << ",\"font_size\":" << command.font_size
           << ",\"text_size\":" << command.text_size
           << ",\"datum\":" << jsonEscape(command.datum)
           << ",\"color\":" << command.color
           << ",\"background\":" << command.background;
  }
  output << '}';
}

std::string snapshotJson() {
  const auto& runtime = sokkon_sim::runtime();
  const uint64_t elapsed_us = stopwatch.elapsedUs(nowMicros());
  char elapsed_text[24];
  c152::formatElapsed(elapsed_us, elapsed_text, sizeof(elapsed_text));

  std::ostringstream output;
  output << "{\"revision\":" << revision;
  if (!command_error.empty()) {
    output << ",\"command_error\":" << jsonEscape(command_error);
  }
  output << ",\"firmware\":{\"id\":\"99_stopwatch\""
         << ",\"label\":\"STOPWATCH\""
         << ",\"subtitle\":\"PRODUCTION C++\""
         << ",\"shell_subtitle\":\"NATIVE FIRMWARE\""
         << ",\"heading\":\"時間を、そのまま測る。\""
         << ",\"primary_label\":\"START / PAUSE\""
         << ",\"secondary_label\":\"RESET\""
         << ",\"touch_label\":\"START / PAUSE\""
         << ",\"primary_aria\":\"ストップウォッチを開始または一時停止\""
         << ",\"secondary_aria\":\"ストップウォッチをリセット\""
         << ",\"touch_aria\":\"ストップウォッチを開始または一時停止\""
         << ",\"state_semantics\":\"stopwatch\""
         << ",\"host_controls\":false}";

  output << ",\"frame\":{\"width\":466,\"height\":466,\"brightness\":"
         << runtime.brightness << ",\"commands\":[";
  for (size_t index = 0; index < runtime.published_commands.size(); ++index) {
    if (index != 0) output << ',';
    appendDrawCommand(output, runtime.published_commands[index]);
  }
  output << "]}";

  output << ",\"screen\":{\"connected\":false,\"status\":\"NATIVE\""
         << ",\"battery_percent\":" << battery_percent
         << ",\"charging\":" << (charging ? "true" : "false")
         << ",\"brightness\":" << runtime.brightness
         << ",\"sleeping\":false,\"time\":" << jsonEscape(rtc_text)
         << ",\"mode\":\"STOPWATCH\""
         << ",\"context\":\"99 / STOPWATCH\""
         << ",\"detail\":\"COMPILED PRODUCTION C++\""
         << ",\"focus_running\":"
         << (stopwatch.isRunning() ? "true" : "false")
         << ",\"elapsed_ms\":" << elapsed_us / 1000ULL
         << ",\"elapsed_text\":" << jsonEscape(elapsed_text)
         << ",\"marks\":0,\"toast\":\"\"}";

  output << ",\"scenario\":{\"connected\":"
         << (scenario.connected ? "true" : "false")
         << ",\"outcome\":" << jsonEscape(scenario.outcome)
         << ",\"latency_ms\":" << scenario.latency_ms
         << ",\"context\":" << jsonEscape(scenario.context)
         << ",\"detail\":" << jsonEscape(scenario.detail)
         << ",\"host_mode\":" << jsonEscape(scenario.host_mode)
         << ",\"battery_percent\":" << scenario.battery_percent
         << ",\"charging\":" << (scenario.charging ? "true" : "false")
         << ",\"time_scale\":" << scenario.time_scale << '}';

  output << ",\"pending\":[]";
  output << ",\"haptic\":{\"active\":"
         << (runtime.vibration != 0 ? "true" : "false")
         << ",\"intensity\":" << static_cast<int>(runtime.last_vibration)
         << ",\"pulses\":" << runtime.haptic_pulses
         << ",\"label\":"
         << jsonEscape(runtime.vibration == 0 ? "IDLE" : "VIBRATION")
         << '}';

  output << ",\"log\":[";
  for (size_t index = 0; index < event_log.size(); ++index) {
    if (index != 0) output << ',';
    const LogEntry& entry = event_log[index];
    output << "{\"time\":" << entry.at_ms << ",\"kind\":"
           << jsonEscape(entry.kind) << ",\"message\":"
           << jsonEscape(entry.message) << '}';
  }
  output << "]}";
  return output.str();
}

void initialize() {
  auto& state = sokkon_sim::runtime();
  state.battery_percent = scenario.battery_percent;
  state.charging = scenario.charging;
  setup();
  processDeviceOutput();
  advanceRuntimeByMs(40);
  last_wall = Clock::now();
}

void handleCommand(const std::string& line) {
  command_error.clear();
  syncWallClock();
  if (line == "SNAPSHOT") {
    // Wall-clock synchronization already ran the production loop.
  } else if (line.rfind("ACTION\t", 0) == 0) {
    performAction(line.substr(7));
  } else if (line.rfind("ADVANCE\t", 0) == 0) {
    try {
      advanceRuntimeByMs(parseUnsigned(line.substr(8), kMaximumAdvanceMs));
    } catch (const std::exception& error) {
      command_error = error.what();
    }
  } else if (line.rfind("CONFIGURE\t", 0) == 0) {
    const size_t separator = line.find('\t', 10);
    if (separator == std::string::npos) {
      command_error = "CONFIGURE requires key and value";
    } else {
      configure(line.substr(10, separator - 10), line.substr(separator + 1));
    }
  } else {
    command_error = "unsupported command";
  }
  ++revision;
  std::cout << snapshotJson() << '\n' << std::flush;
  last_wall = Clock::now();
}

}  // namespace stopwatch_host

int main() {
  std::ios::sync_with_stdio(false);
  stopwatch_host::initialize();
  std::string line;
  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    stopwatch_host::handleCommand(line);
  }
  return 0;
}
