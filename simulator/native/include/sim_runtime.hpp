#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
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
  int brightness = 96;
  int battery_percent = 84;
  bool charging = false;
  bool button_a = false;
  bool button_b = false;
  bool touch_pressed = false;
  int32_t touch_x = 233;
  int32_t touch_y = 233;
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
  runtime().now_us += milliseconds * 1000ULL;
}

}  // namespace sokkon_sim
