#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>
#include <string>
#include <vector>

namespace sokkon_sim {

struct DrawCommand {
  std::string op;
  std::string text;
  std::string font;
  std::string datum;
  int32_t x = 0;
  int32_t y = 0;
  int32_t r = 0;
  int32_t w = 0;
  int32_t h = 0;
  int32_t outer_radius = 0;
  int32_t inner_radius = 0;
  int32_t start = 0;
  int32_t end = 0;
  uint32_t color = 0;
  uint32_t background = 0;
  int32_t font_size = 16;
  float text_size = 1.0F;
};

struct Runtime {
  uint64_t now_us = 0;
  uint64_t advance_limit_us = std::numeric_limits<uint64_t>::max();
  int brightness = 96;
  int battery_percent = 84;
  bool charging = false;
  bool button_a = false;
  bool button_b = false;
  bool touch_pressed = false;
  int32_t touch_x = 233;
  int32_t touch_y = 233;
  float imu_accel_x = 0.12F;
  float imu_accel_y = -0.08F;
  float imu_accel_z = 0.99F;
  float imu_gyro_x = 0.0F;
  float imu_gyro_y = 0.0F;
  float imu_gyro_z = 0.0F;
  uint8_t vibration = 0;
  uint8_t last_vibration = 0;
  uint32_t haptic_pulses = 0;
  std::deque<char> serial_rx;
  std::string serial_partial;
  std::vector<std::string> device_lines;
  std::vector<DrawCommand> published_commands;
};

Runtime& runtime();
void serialWrite(const char* data, size_t size);

inline uint32_t millis32() {
  return static_cast<uint32_t>(runtime().now_us / 1000ULL);
}

inline uint64_t micros64() { return runtime().now_us; }

inline void advanceMs(uint64_t milliseconds) {
  auto& state = runtime();
  const uint64_t delta =
      milliseconds > std::numeric_limits<uint64_t>::max() / 1000ULL
          ? std::numeric_limits<uint64_t>::max()
          : milliseconds * 1000ULL;
  const uint64_t maximum_delta =
      std::numeric_limits<uint64_t>::max() - state.now_us;
  const uint64_t next = state.now_us + std::min(delta, maximum_delta);
  state.now_us = std::min(next, state.advance_limit_us);
}

}  // namespace sokkon_sim
