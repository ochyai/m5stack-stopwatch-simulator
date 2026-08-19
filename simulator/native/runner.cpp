#include "sim_runtime.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <deque>
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

#ifndef SOKKON_PRODUCTION_MAIN
#define SOKKON_PRODUCTION_MAIN "../../firmware/apps/10_sokkon/main.cpp"
#endif
#include SOKKON_PRODUCTION_MAIN

namespace sokkon_host {

using Clock = std::chrono::steady_clock;

struct Scenario {
  bool connected = true;
  std::string outcome = "OK";
  uint64_t latency_ms = 400;
  std::string context = "CODEX";
  std::string detail = "BUILDING SOKKON";
  std::string host_mode = "NOW";
  int battery_percent = 84;
  bool charging = false;
  double time_scale = 1.0;
};

struct ScheduledLine {
  uint64_t due_us = 0;
  std::string line;
};

struct LogEntry {
  uint64_t at_ms = 0;
  std::string kind;
  std::string message;
};

Scenario scenario;
std::vector<ScheduledLine> scheduled_lines;
std::vector<LogEntry> protocol_log;
size_t processed_device_lines = 0;
uint64_t revision = 0;
std::string command_error;
Clock::time_point last_wall = Clock::now();

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
  protocol_log.push_back(
      {static_cast<uint64_t>(millis()), std::move(kind), std::move(message)});
  if (protocol_log.size() > 120) {
    protocol_log.erase(protocol_log.begin(),
                       protocol_log.begin() +
                           static_cast<std::ptrdiff_t>(protocol_log.size() - 120));
  }
}

std::vector<std::string> splitPipe(const std::string& line) {
  std::vector<std::string> fields;
  size_t start = 0;
  while (true) {
    const size_t separator = line.find('|', start);
    if (separator == std::string::npos) {
      fields.push_back(line.substr(start));
      return fields;
    }
    fields.push_back(line.substr(start, separator - start));
    start = separator + 1;
  }
}

std::string protocolSafe(std::string value) {
  for (char& character : value) {
    if (character == '|' || character == '\r' || character == '\n' ||
        character == '\t' || character == '\0') {
      character = ' ';
    }
  }
  return value;
}

void queueHostInput(const std::string& line) {
  auto& input = sokkon_sim::runtime().serial_rx;
  for (const char character : line) input.push_back(character);
  input.push_back('\n');
  addLog("RX", line);
}

void scheduleHostResponse(const std::string& line, uint64_t delay_ms) {
  scheduled_lines.push_back(
      {sokkon_sim::micros64() + delay_ms * 1000ULL, line});
  std::stable_sort(scheduled_lines.begin(), scheduled_lines.end(),
                   [](const ScheduledLine& left, const ScheduledLine& right) {
                     return left.due_us < right.due_us;
                   });
}

void processDeviceOutput() {
  auto& lines = sokkon_sim::runtime().device_lines;
  while (processed_device_lines < lines.size()) {
    const std::string line = lines[processed_device_lines++];
    addLog("TX", line);
    const std::vector<std::string> fields = splitPipe(line);
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

bool deliverScheduledLines() {
  if (!scenario.connected) {
    scheduled_lines.clear();
    return false;
  }
  bool delivered = false;
  const uint64_t now_us = sokkon_sim::micros64();
  while (!scheduled_lines.empty() && scheduled_lines.front().due_us <= now_us) {
    queueHostInput(scheduled_lines.front().line);
    scheduled_lines.erase(scheduled_lines.begin());
    delivered = true;
  }
  return delivered;
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

void injectHostState() {
  if (!scenario.connected) return;
  queueHostInput("PING");
  queueHostInput("STATE|12:34|" + scenario.host_mode + "|" +
                 protocolSafe(scenario.context) + "|" +
                 protocolSafe(scenario.detail));
  consumeHostInput();
}

void settleAtCurrentTime();

bool queueHeartbeatIfDue() {
  if (!scenario.connected) return false;
  const uint32_t now_ms = millis();
  if (host_seen && now_ms - last_host_ms < 1000U) return false;
  queueHostInput("PING");
  queueHostInput("STATE|12:34|" + scenario.host_mode + "|" +
                 protocolSafe(scenario.context) + "|" +
                 protocolSafe(scenario.detail));
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
  auto& state = sokkon_sim::runtime();
  const uint64_t delta_us =
      milliseconds > std::numeric_limits<uint64_t>::max() / 1000ULL
          ? std::numeric_limits<uint64_t>::max()
          : milliseconds * 1000ULL;
  const uint64_t maximum_delta =
      std::numeric_limits<uint64_t>::max() - state.now_us;
  advanceRuntimeTo(state.now_us + std::min(delta_us, maximum_delta));
}

void maintainHostConnection() {
  if (queueHeartbeatIfDue()) runFirmwareLoop();
  settleAtCurrentTime();
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

void redrawAfterInput() {
  advanceRuntimeByMs(101);
  settleAtCurrentTime();
}

void syncWallClock() {
  const Clock::time_point now = Clock::now();
  const auto elapsed =
      std::chrono::duration_cast<std::chrono::microseconds>(now - last_wall)
          .count();
  last_wall = now;
  if (elapsed <= 0 || scenario.time_scale <= 0.0) return;
  const long double scaled = static_cast<long double>(elapsed) *
                             static_cast<long double>(scenario.time_scale);
  const uint64_t maximum = std::numeric_limits<uint64_t>::max() -
                           sokkon_sim::runtime().now_us;
  const uint64_t delta_us =
      static_cast<uint64_t>(std::min<long double>(scaled, maximum));
  advanceRuntimeTo(sokkon_sim::runtime().now_us + delta_us);
  settleAtCurrentTime();
}

void performAction(const std::string& action) {
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
    state.touch_x = M5.Display.width() / 2;
    state.touch_y = M5.Display.height() / 2;
    state.touch_pressed = true;
    runFirmwareLoop();
    state.touch_pressed = false;
    runFirmwareLoop();
  } else {
    command_error = "unsupported action";
    return;
  }
  processDeviceOutput();
  settleAtCurrentTime();
  redrawAfterInput();
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

bool validMode(const std::string& value) {
  for (const char* mode : kModes) {
    if (value == mode) return true;
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
      if (!parseBoolean(value, &scenario.connected)) {
        throw std::invalid_argument("CONNECTED must be boolean");
      }
      if (!scenario.connected) {
        scheduled_lines.clear();
        state.serial_rx.clear();
      }
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
      if (!validMode(value)) throw std::invalid_argument("unsupported HOST_MODE");
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

  if (scenario.connected) injectHostState();
  if (key == "BATTERY_PERCENT" || key == "CHARGING") {
    advanceRuntimeByMs(1001);
  } else {
    advanceRuntimeByMs(101);
  }
  settleAtCurrentTime();
}

void advanceVirtualTime(uint64_t milliseconds) {
  advanceRuntimeByMs(milliseconds);
  settleAtCurrentTime();
}

std::string intentString(Intent intent) { return intentName(intent); }

void appendDrawCommand(std::ostringstream& output,
                       const sokkon_sim::DrawCommand& command) {
  output << "{\"op\":" << jsonEscape(command.op);
  if (command.op == "fillScreen") {
    output << ",\"color\":" << command.color;
  } else if (command.op == "drawCircle" || command.op == "fillCircle") {
    output << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"r\":" << command.r << ",\"color\":"
           << command.color;
  } else if (command.op == "drawArc") {
    output << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"outer_radius\":" << command.outer_radius
           << ",\"inner_radius\":" << command.inner_radius
           << ",\"start\":" << command.start << ",\"end\":"
           << command.end << ",\"color\":" << command.color;
  } else if (command.op == "fillRoundRect") {
    output << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"w\":" << command.w << ",\"h\":" << command.h
           << ",\"r\":" << command.r << ",\"color\":"
           << command.color;
  } else if (command.op == "drawString") {
    output << ",\"text\":" << jsonEscape(command.text)
           << ",\"x\":" << command.x << ",\"y\":" << command.y
           << ",\"font\":" << jsonEscape(command.font)
           << ",\"font_size\":" << command.font_size
           << ",\"text_size\":" << command.text_size
           << ",\"datum\":" << jsonEscape(command.datum)
           << ",\"color\":" << command.color << ",\"background\":"
           << command.background;
  }
  output << '}';
}

std::string snapshotJson() {
  const uint32_t now_ms = millis();
  const uint64_t elapsed_ms = focus_timer.elapsedUs(nowMicros()) / 1000ULL;
  char elapsed_text[24];
  c152::formatElapsed(elapsed_ms * 1000ULL, elapsed_text,
                      sizeof(elapsed_text));
  const bool connected = hostConnected(now_ms);
  const bool toast_visible =
      toast_text[0] != '\0' && static_cast<int32_t>(toast_until_ms - now_ms) > 0;
  const auto& runtime = sokkon_sim::runtime();

  std::ostringstream output;
  output << "{\"revision\":" << revision;
  if (!command_error.empty()) {
    output << ",\"command_error\":" << jsonEscape(command_error);
  }
  output << ",\"frame\":{\"width\":466,\"height\":466,\"brightness\":"
         << runtime.brightness << ",\"commands\":[";
  for (size_t index = 0; index < runtime.published_commands.size(); ++index) {
    if (index != 0) output << ',';
    appendDrawCommand(output, runtime.published_commands[index]);
  }
  output << "]}";

  output << ",\"screen\":{\"connected\":"
         << (connected ? "true" : "false") << ",\"status\":"
         << jsonEscape(connected ? "USB" : "LOCAL")
         << ",\"battery_percent\":" << battery_percent
         << ",\"charging\":" << (charging ? "true" : "false")
         << ",\"brightness\":" << runtime.brightness
         << ",\"sleeping\":" << (display_sleeping ? "true" : "false")
         << ",\"time\":" << jsonEscape(connected ? host_time : rtc_text)
         << ",\"mode\":" << jsonEscape(kModes[mode_index])
         << ",\"context\":"
         << jsonEscape(connected ? context_text : "MAC NOT CONNECTED")
         << ",\"detail\":"
         << jsonEscape(connected ? detail_text : "USB-C TO BEGIN")
         << ",\"focus_running\":"
         << (focus_timer.isRunning() ? "true" : "false")
         << ",\"elapsed_ms\":" << elapsed_ms
         << ",\"elapsed_text\":" << jsonEscape(elapsed_text)
         << ",\"marks\":" << mark_count << ",\"toast\":"
         << jsonEscape(toast_visible ? toast_text : "") << '}';

  output << ",\"scenario\":{\"connected\":"
         << (scenario.connected ? "true" : "false") << ",\"outcome\":"
         << jsonEscape(scenario.outcome) << ",\"latency_ms\":"
         << scenario.latency_ms << ",\"context\":"
         << jsonEscape(scenario.context) << ",\"detail\":"
         << jsonEscape(scenario.detail) << ",\"host_mode\":"
         << jsonEscape(scenario.host_mode) << ",\"battery_percent\":"
         << scenario.battery_percent << ",\"charging\":"
         << (scenario.charging ? "true" : "false")
         << ",\"time_scale\":" << scenario.time_scale << '}';

  output << ",\"pending\":[";
  bool first_pending = true;
  for (const PendingEvent& pending : pending_events) {
    if (!pending.active) continue;
    if (!first_pending) output << ',';
    first_pending = false;
    output << "{\"sequence\":" << pending.sequence << ",\"intent\":"
           << jsonEscape(intentString(pending.intent)) << ",\"accepted\":"
           << (pending.accepted ? "true" : "false") << '}';
  }
  output << ']';

  output << ",\"haptic\":{\"active\":"
         << (runtime.vibration != 0 ? "true" : "false")
         << ",\"intensity\":" << static_cast<int>(runtime.last_vibration)
         << ",\"pulses\":" << runtime.haptic_pulses
         << ",\"label\":"
         << jsonEscape(runtime.haptic_pulses == 0 ? "IDLE" : "VIBRATION")
         << '}';

  output << ",\"log\":[";
  for (size_t index = 0; index < protocol_log.size(); ++index) {
    if (index != 0) output << ',';
    const LogEntry& entry = protocol_log[index];
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
  injectHostState();
  advanceRuntimeByMs(101);
  settleAtCurrentTime();
  last_wall = Clock::now();
}

void handleCommand(const std::string& line) {
  command_error.clear();
  syncWallClock();
  maintainHostConnection();
  if (line == "SNAPSHOT") {
    settleAtCurrentTime();
  } else if (line.rfind("ACTION\t", 0) == 0) {
    performAction(line.substr(7));
  } else if (line.rfind("ADVANCE\t", 0) == 0) {
    try {
      advanceVirtualTime(parseUnsigned(line.substr(8), 7ULL * 24ULL * 60ULL *
                                                           60ULL * 1000ULL));
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

}  // namespace sokkon_host

int main() {
  std::ios::sync_with_stdio(false);
  sokkon_host::initialize();
  std::string line;
  while (std::getline(std::cin, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    sokkon_host::handleCommand(line);
  }
  return 0;
}
