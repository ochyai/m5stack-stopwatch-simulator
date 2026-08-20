#pragma once

// Shared host framework for every native firmware simulator.
//
// A runner in this repository is a thin adapter: it owns the semantics of one
// production firmware (its protocol, its inputs, its screen block) and nothing
// else.  Serial plumbing, NDJSON encoding, scenario parsing, wall-clock
// scaling, and the stdin/stdout command loop live here so both runners cannot
// drift apart in the parts a UI depends on.
//
// This header defines (not merely declares) the ``sokkon_sim`` runtime hooks.
// Each simulator binary links exactly one runner translation unit, so a single
// inclusion per program is both required and sufficient.

#include "sim_runtime.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
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

namespace sim_host {

inline constexpr size_t kLogCapacity = 120;

// ---------------------------------------------------------------------------
// JSON encoding
// ---------------------------------------------------------------------------

inline std::string jsonEscape(std::string_view value) {
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

// ---------------------------------------------------------------------------
// Protocol / event log
// ---------------------------------------------------------------------------

struct LogEntry {
  uint64_t at_ms = 0;
  std::string kind;
  std::string message;
};

class LogRing {
 public:
  void add(std::string kind, std::string message) {
    entries_.push_back({static_cast<uint64_t>(sokkon_sim::millis32()),
                        std::move(kind), std::move(message)});
    if (entries_.size() > kLogCapacity) {
      entries_.erase(entries_.begin(),
                     entries_.begin() + static_cast<std::ptrdiff_t>(
                                            entries_.size() - kLogCapacity));
    }
  }

  void appendJson(std::ostringstream& output) const {
    output << "[";
    for (size_t index = 0; index < entries_.size(); ++index) {
      if (index != 0) output << ',';
      const LogEntry& entry = entries_[index];
      output << "{\"time\":" << entry.at_ms
             << ",\"kind\":" << jsonEscape(entry.kind)
             << ",\"message\":" << jsonEscape(entry.message) << '}';
    }
    output << ']';
  }

 private:
  std::vector<LogEntry> entries_;
};

// ---------------------------------------------------------------------------
// Scenario (the UI-visible host situation, identical across firmwares)
// ---------------------------------------------------------------------------

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
  // Accelerometer reading in g along the panel's x and y axes: how the device
  // is being held.
  double tilt_x = 0.12;
  double tilt_y = -0.08;
};

inline bool parseBoolean(const std::string& value, bool* output) {
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

inline uint64_t parseUnsigned(const std::string& value, uint64_t maximum) {
  if (value.empty()) throw std::invalid_argument("empty integer");
  size_t consumed = 0;
  const unsigned long long parsed = std::stoull(value, &consumed, 10);
  if (consumed != value.size() || parsed > maximum) {
    throw std::out_of_range("integer outside range");
  }
  return static_cast<uint64_t>(parsed);
}

inline double parseTilt(const std::string& value) {
  size_t consumed = 0;
  const double parsed = std::stod(value, &consumed);
  if (consumed != value.size() || !std::isfinite(parsed) || parsed < -1.0 ||
      parsed > 1.0) {
    throw std::invalid_argument("tilt outside -1 g to 1 g");
  }
  return parsed;
}

// Gravity has a fixed magnitude, so whatever the x and y axes do not take is
// what the z axis reads. A viewer that sets only a tilt still gets a physically
// possible accelerometer sample.
inline void applyTilt(double tilt_x, double tilt_y) {
  auto& state = sokkon_sim::runtime();
  state.imu_accel_x = static_cast<float>(tilt_x);
  state.imu_accel_y = static_cast<float>(tilt_y);
  const double squared = tilt_x * tilt_x + tilt_y * tilt_y;
  state.imu_accel_z =
      squared >= 1.0 ? 0.0F : static_cast<float>(std::sqrt(1.0 - squared));
}

inline double parseTimeScale(const std::string& value) {
  size_t consumed = 0;
  const double parsed = std::stod(value, &consumed);
  if (consumed != value.size() || !std::isfinite(parsed) || parsed < 0.01 ||
      parsed > 1000.0) {
    throw std::invalid_argument("TIME_SCALE outside range");
  }
  return parsed;
}

// Apply one CONFIGURE field that every firmware understands the same way.
// Returns false for keys the caller must interpret itself (CONNECTED and
// HOST_MODE carry firmware-specific meaning).  Throws std::invalid_argument or
// std::out_of_range for a malformed value.
inline bool applyCommonScenarioField(Scenario& scenario, const std::string& key,
                                     const std::string& value) {
  if (key == "OUTCOME") {
    if (value != "OK" && value != "ERROR" && value != "TIMEOUT") {
      throw std::invalid_argument("unsupported OUTCOME");
    }
    scenario.outcome = value;
    return true;
  }
  if (key == "LATENCY_MS") {
    scenario.latency_ms = parseUnsigned(value, 60000);
    return true;
  }
  if (key == "CONTEXT") {
    scenario.context = value;
    return true;
  }
  if (key == "DETAIL") {
    scenario.detail = value;
    return true;
  }
  if (key == "BATTERY_PERCENT") {
    scenario.battery_percent = static_cast<int>(parseUnsigned(value, 100));
    sokkon_sim::runtime().battery_percent = scenario.battery_percent;
    return true;
  }
  if (key == "CHARGING") {
    if (!parseBoolean(value, &scenario.charging)) {
      throw std::invalid_argument("CHARGING must be boolean");
    }
    sokkon_sim::runtime().charging = scenario.charging;
    return true;
  }
  if (key == "TIME_SCALE") {
    scenario.time_scale = parseTimeScale(value);
    return true;
  }
  if (key == "TILT_X" || key == "TILT_Y") {
    const double tilt = parseTilt(value);
    (key == "TILT_X" ? scenario.tilt_x : scenario.tilt_y) = tilt;
    applyTilt(scenario.tilt_x, scenario.tilt_y);
    return true;
  }
  return false;
}

inline void appendScenarioJson(std::ostringstream& output,
                               const Scenario& scenario) {
  output << "{\"connected\":" << (scenario.connected ? "true" : "false")
         << ",\"outcome\":" << jsonEscape(scenario.outcome)
         << ",\"latency_ms\":" << scenario.latency_ms
         << ",\"context\":" << jsonEscape(scenario.context)
         << ",\"detail\":" << jsonEscape(scenario.detail)
         << ",\"host_mode\":" << jsonEscape(scenario.host_mode)
         << ",\"battery_percent\":" << scenario.battery_percent
         << ",\"charging\":" << (scenario.charging ? "true" : "false")
         << ",\"time_scale\":" << scenario.time_scale
         << ",\"tilt_x\":" << scenario.tilt_x
         << ",\"tilt_y\":" << scenario.tilt_y << '}';
}

// Replace the pipe-delimited protocol's separators so a scenario string can
// never forge an extra field.
inline std::string protocolSafe(std::string value) {
  for (char& character : value) {
    if (character == '|' || character == '\r' || character == '\n' ||
        character == '\t' || character == '\0') {
      character = ' ';
    }
  }
  return value;
}

inline std::vector<std::string> splitPipe(const std::string& line) {
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

// ---------------------------------------------------------------------------
// Frame, haptics, and firmware identity
// ---------------------------------------------------------------------------

inline void appendDrawCommand(std::ostringstream& output,
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
    output << ",\"text\":" << jsonEscape(command.text) << ",\"x\":" << command.x
           << ",\"y\":" << command.y << ",\"font\":" << jsonEscape(command.font)
           << ",\"font_size\":" << command.font_size
           << ",\"text_size\":" << command.text_size
           << ",\"datum\":" << jsonEscape(command.datum)
           << ",\"color\":" << command.color
           << ",\"background\":" << command.background;
    // The device already knows where every glyph lands. Publishing that grid
    // keeps a viewer from re-deriving it from a browser font that is not the
    // panel's font.
    output << ",\"layout\":{\"left\":" << command.text_left
           << ",\"top\":" << command.text_top
           << ",\"baseline\":" << command.text_baseline
           << ",\"width\":" << command.text_pixel_width
           << ",\"height\":" << command.text_box_height << ",\"pen\":[";
    for (size_t index = 0; index < command.pen_x.size(); ++index) {
      if (index != 0) output << ',';
      output << command.pen_x[index];
    }
    output << "]}";
  }
  output << '}';
}

inline void appendFrameJson(std::ostringstream& output,
                            const sokkon_sim::Runtime& state, int width,
                            int height) {
  output << "{\"width\":" << width << ",\"height\":" << height
         << ",\"brightness\":" << state.brightness << ",\"commands\":[";
  for (size_t index = 0; index < state.published_commands.size(); ++index) {
    if (index != 0) output << ',';
    appendDrawCommand(output, state.published_commands[index]);
  }
  output << "]}";
}

// ``active`` and ``label`` describe the same instant: the motor is either
// driven right now or it is idle.  ``pulses`` is the cumulative count.
inline void appendHapticJson(std::ostringstream& output,
                             const sokkon_sim::Runtime& state) {
  const bool active = state.vibration != 0;
  output << "{\"active\":" << (active ? "true" : "false")
         << ",\"intensity\":" << static_cast<int>(state.last_vibration)
         << ",\"pulses\":" << state.haptic_pulses
         << ",\"label\":" << jsonEscape(active ? "VIBRATION" : "IDLE") << '}';
}

// Presentation contract consumed by every simulator UI.  A runner declares one
// of these instead of hand-writing the same JSON object.
struct FirmwareIdentity {
  const char* id = "";
  const char* label = "";
  const char* subtitle = "";
  const char* shell_subtitle = "";
  const char* heading = "";
  const char* primary_label = "";
  const char* secondary_label = "";
  const char* touch_label = "";
  const char* primary_aria = "";
  const char* secondary_aria = "";
  const char* touch_aria = "";
  const char* state_semantics = "";
  bool host_controls = false;
};

inline void appendFirmwareJson(std::ostringstream& output,
                               const FirmwareIdentity& identity) {
  output << "{\"id\":" << jsonEscape(identity.id)
         << ",\"label\":" << jsonEscape(identity.label)
         << ",\"subtitle\":" << jsonEscape(identity.subtitle)
         << ",\"shell_subtitle\":" << jsonEscape(identity.shell_subtitle)
         << ",\"heading\":" << jsonEscape(identity.heading)
         << ",\"primary_label\":" << jsonEscape(identity.primary_label)
         << ",\"secondary_label\":" << jsonEscape(identity.secondary_label)
         << ",\"touch_label\":" << jsonEscape(identity.touch_label)
         << ",\"primary_aria\":" << jsonEscape(identity.primary_aria)
         << ",\"secondary_aria\":" << jsonEscape(identity.secondary_aria)
         << ",\"touch_aria\":" << jsonEscape(identity.touch_aria)
         << ",\"state_semantics\":" << jsonEscape(identity.state_semantics)
         << ",\"host_controls\":" << (identity.host_controls ? "true" : "false")
         << '}';
}

// ---------------------------------------------------------------------------
// Wall clock
// ---------------------------------------------------------------------------

// Converts real elapsed time into scaled virtual microseconds.  The remainder
// is carried, so a slow scale still advances instead of truncating to zero on
// every poll.
class WallClock {
 public:
  void reset() {
    last_ = Clock::now();
    fraction_us_ = 0.0L;
  }

  uint64_t takeScaledUs(double time_scale, uint64_t maximum) {
    const Clock::time_point now = Clock::now();
    const auto elapsed =
        std::chrono::duration_cast<std::chrono::microseconds>(now - last_)
            .count();
    last_ = now;
    if (elapsed <= 0 || time_scale <= 0.0) return 0;
    const long double scaled =
        static_cast<long double>(elapsed) *
            static_cast<long double>(time_scale) +
        fraction_us_;
    if (scaled >= static_cast<long double>(maximum)) {
      fraction_us_ = 0.0L;
      return maximum;
    }
    const uint64_t delta_us = static_cast<uint64_t>(scaled);
    fraction_us_ = scaled - static_cast<long double>(delta_us);
    return delta_us;
  }

 private:
  using Clock = std::chrono::steady_clock;

  Clock::time_point last_ = Clock::now();
  long double fraction_us_ = 0.0L;
};

inline uint64_t remainingVirtualUs() {
  return std::numeric_limits<uint64_t>::max() - sokkon_sim::runtime().now_us;
}

inline uint64_t millisecondsToUs(uint64_t milliseconds) {
  return milliseconds > std::numeric_limits<uint64_t>::max() / 1000ULL
             ? std::numeric_limits<uint64_t>::max()
             : milliseconds * 1000ULL;
}

// ---------------------------------------------------------------------------
// Command loop
// ---------------------------------------------------------------------------

struct Command {
  enum class Kind { Snapshot, Action, Touch, Advance, Configure, Freeze, Unsupported };

  Kind kind = Kind::Unsupported;
  std::string first;
  std::string second;
};

inline Command parseCommand(const std::string& line) {
  Command command;
  if (line == "SNAPSHOT") {
    command.kind = Command::Kind::Snapshot;
  } else if (line.rfind("ACTION\t", 0) == 0) {
    command.kind = Command::Kind::Action;
    command.first = line.substr(7);
  } else if (line.rfind("ADVANCE\t", 0) == 0) {
    command.kind = Command::Kind::Advance;
    command.first = line.substr(8);
  } else if (line.rfind("TOUCH\t", 0) == 0) {
    const size_t separator = line.find('\t', 6);
    if (separator != std::string::npos) {
      command.kind = Command::Kind::Touch;
      command.first = line.substr(6, separator - 6);
      command.second = line.substr(separator + 1);
    }
  } else if (line.rfind("FREEZE\t", 0) == 0) {
    command.kind = Command::Kind::Freeze;
    command.first = line.substr(7);
  } else if (line.rfind("CONFIGURE\t", 0) == 0) {
    const size_t separator = line.find('\t', 10);
    if (separator != std::string::npos) {
      command.kind = Command::Kind::Configure;
      command.first = line.substr(10, separator - 10);
      command.second = line.substr(separator + 1);
    }
  }
  return command;
}

// Base class for a firmware adapter.  ``run`` owns the request/response
// contract the Python bridge relies on: exactly one NDJSON snapshot per
// command line, with a monotonically increasing revision.
class Host {
 public:
  virtual ~Host() = default;

  int run() {
    std::ios::sync_with_stdio(false);
    initialize();
    wall_clock.reset();
    std::string line;
    while (std::getline(std::cin, line)) {
      if (!line.empty() && line.back() == '\r') line.pop_back();
      handleCommand(line);
    }
    return 0;
  }

  // Exposed for in-process tests and for ``run``.
  void handleCommand(const std::string& line) {
    command_error.clear();
    // Frozen time is what makes a scripted session reproducible: virtual time
    // then moves only when a command says so.
    if (frozen) {
      wall_clock.reset();
    } else {
      syncWallClock();
    }
    beforeCommand();
    const Command command = parseCommand(line);
    switch (command.kind) {
      case Command::Kind::Snapshot:
        settle();
        break;
      case Command::Kind::Action:
        performAction(command.first);
        break;
      case Command::Kind::Touch:
        try {
          performTouch(parseCoordinate(command.first),
                       parseCoordinate(command.second));
        } catch (const std::exception& error) {
          command_error = error.what();
        }
        break;
      case Command::Kind::Advance:
        try {
          advance(parseUnsigned(command.first, maximumAdvanceMs()));
        } catch (const std::exception& error) {
          command_error = error.what();
        }
        break;
      case Command::Kind::Configure:
        try {
          configure(command.first, command.second);
        } catch (const std::exception& error) {
          command_error = error.what();
        }
        break;
      case Command::Kind::Freeze:
        if (!parseBoolean(command.first, &frozen)) {
          command_error = "FREEZE must be boolean";
        }
        break;
      case Command::Kind::Unsupported:
        if (line.rfind("CONFIGURE\t", 0) == 0) {
          command_error = "CONFIGURE requires key and value";
        } else if (line.rfind("TOUCH\t", 0) == 0) {
          command_error = "TOUCH requires x and y";
        } else {
          command_error = "unsupported command";
        }
        break;
    }
    ++revision;
    std::cout << snapshotJson() << '\n' << std::flush;
    wall_clock.reset();
  }

 protected:
  // Firmware-specific behaviour.
  virtual void initialize() = 0;
  virtual void performAction(const std::string& action) = 0;
  virtual void advance(uint64_t milliseconds) = 0;
  virtual void configure(const std::string& key, const std::string& value) = 0;
  virtual std::string snapshotJson() = 0;
  virtual uint64_t maximumAdvanceMs() const = 0;

  // Optional hooks.
  virtual void beforeCommand() {}
  virtual void settle() {}
  virtual void syncWallClock() = 0;

  // Run the production loop once, and give it the window it needs to redraw
  // after an input. Both are firmware-specific; touch handling is not.
  virtual void runOneLoop() = 0;
  virtual void settleInput() = 0;

  // Press and release at an exact panel coordinate. The firmware decides what
  // that means: 10_sokkon only treats a press inside its focus ring as a focus
  // toggle, and a simulator that could only reach the centre could never show
  // that.
  virtual void performTouch(int32_t x, int32_t y) {
    auto& state = sokkon_sim::runtime();
    state.touch_x = x;
    state.touch_y = y;
    state.touch_pressed = true;
    runOneLoop();
    state.touch_pressed = false;
    runOneLoop();
    settleInput();
  }

  static int32_t parseCoordinate(const std::string& value) {
    const uint64_t parsed = parseUnsigned(value, 465);
    return static_cast<int32_t>(parsed);
  }

  // Shared state every runner reports.
  Scenario scenario;
  LogRing log;
  WallClock wall_clock;
  std::string command_error;
  uint64_t revision = 0;
  bool frozen = false;

  // Emit the fields whose shape the UI treats as one contract.
  void appendCommonPrefix(std::ostringstream& output,
                          const FirmwareIdentity& identity) const {
    output << "{\"revision\":" << revision;
    if (!command_error.empty()) {
      output << ",\"command_error\":" << jsonEscape(command_error);
    }
    output << ",\"firmware\":";
    appendFirmwareJson(output, identity);
    output << ",\"frame\":";
    appendFrameJson(output, sokkon_sim::runtime(), 466, 466);
  }

  void appendCommonSuffix(std::ostringstream& output) const {
    output << ",\"scenario\":";
    appendScenarioJson(output, scenario);
    output << ",\"time_source\":" << jsonEscape(frozen ? "frozen" : "wall_clock");
    output << ",\"haptic\":";
    appendHapticJson(output, sokkon_sim::runtime());
    output << ",\"log\":";
    log.appendJson(output);
    output << '}';
  }
};

}  // namespace sim_host
