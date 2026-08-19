#pragma once

#include "Arduino.h"
#include "sim_runtime.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

constexpr uint32_t TFT_BLACK = 0x0000;
constexpr uint32_t TFT_WHITE = 0xFFFF;
constexpr uint32_t TFT_RED = 0xF800;
constexpr uint32_t TFT_GREEN = 0x07E0;
constexpr uint32_t TFT_BLUE = 0x001F;
constexpr uint32_t TFT_YELLOW = 0xFFE0;
constexpr uint32_t TFT_CYAN = 0x07FF;
constexpr uint32_t TFT_MAGENTA = 0xF81F;
constexpr uint32_t TFT_ORANGE = 0xFD20;
constexpr uint32_t TFT_DARKGREY = 0x7BEF;
constexpr uint32_t TFT_LIGHTGREY = 0xD69A;

constexpr int middle_center = 0;
constexpr int top_left = 1;
constexpr int top_center = 2;

struct SimFont {
  const char* name;
  int size_px;
};

namespace fonts {
inline constexpr SimFont Font2{"Font2", 16};
inline constexpr SimFont FreeSansBold24pt7b{"FreeSansBold24pt7b", 48};
inline constexpr SimFont FreeSansBold18pt7b{"FreeSansBold18pt7b", 36};
}  // namespace fonts

class M5DisplayStub {
 public:
  int width() const { return 466; }
  int height() const { return 466; }

  void setRotation(int) {}
  void setTextWrap(bool) {}
  void setTextDatum(int datum) { datum_ = datum; }
  void setTextSize(float size) { text_size_ = size; }
  void setFont(const SimFont* font) { font_ = font; }
  void setTextColor(uint32_t foreground, uint32_t background = TFT_BLACK) {
    color_ = foreground;
    background_ = background;
  }
  void setBrightness(uint8_t brightness) {
    sokkon_sim::runtime().brightness = static_cast<int>(brightness);
  }
  void fillScreen(uint32_t) {}
  void fillCircle(int32_t, int32_t, int32_t, uint32_t) {}
  void fillRect(int32_t, int32_t, int32_t, int32_t, uint32_t) {}
  void drawFastHLine(int32_t, int32_t, int32_t, uint32_t) {}
  int32_t drawString(const char* text, int32_t, int32_t) const {
    return text == nullptr ? 0 : textWidth(text);
  }
  int32_t textWidth(const char* text) const {
    if (text == nullptr) return 0;
    const int size = font_ == nullptr ? 16 : font_->size_px;
    return static_cast<int32_t>(std::lround(std::strlen(text) * size *
                                            text_size_ * 0.56));
  }

 private:
  const SimFont* font_ = &fonts::Font2;
  int datum_ = middle_center;
  float text_size_ = 1.0F;
  uint32_t color_ = TFT_WHITE;
  uint32_t background_ = TFT_BLACK;
};

class M5Canvas {
 public:
  explicit M5Canvas(M5DisplayStub*) {}

  void setColorDepth(int) {}
  bool createSprite(int32_t width, int32_t height) {
    width_ = width;
    height_ = height;
    return width > 0 && height > 0;
  }
  int32_t width() const { return width_; }
  int32_t height() const { return height_; }

  void setTextDatum(int datum) { datum_ = datum; }
  void setTextSize(float size) { text_size_ = size; }
  void setFont(const SimFont* font) {
    font_ = font == nullptr ? &fonts::Font2 : font;
  }
  void setTextColor(uint32_t foreground, uint32_t background = TFT_BLACK) {
    color_ = foreground;
    background_ = background;
  }

  int32_t textWidth(const char* text) const {
    if (text == nullptr) return 0;
    const int size = font_ == nullptr ? 16 : font_->size_px;
    return static_cast<int32_t>(std::lround(std::strlen(text) * size *
                                            text_size_ * 0.56));
  }

  void fillScreen(uint32_t color) {
    commands_.clear();
    sokkon_sim::DrawCommand command;
    command.op = "fillScreen";
    command.color = color;
    commands_.push_back(std::move(command));
  }

  void drawCircle(int32_t x, int32_t y, int32_t radius, uint32_t color) {
    sokkon_sim::DrawCommand command;
    command.op = "drawCircle";
    command.x = x;
    command.y = y;
    command.r = radius;
    command.color = color;
    commands_.push_back(std::move(command));
  }

  void fillCircle(int32_t x, int32_t y, int32_t radius, uint32_t color) {
    sokkon_sim::DrawCommand command;
    command.op = "fillCircle";
    command.x = x;
    command.y = y;
    command.r = radius;
    command.color = color;
    commands_.push_back(std::move(command));
  }

  void drawArc(int32_t x, int32_t y, int32_t outer_radius,
               int32_t inner_radius, int32_t start, int32_t end,
               uint32_t color) {
    sokkon_sim::DrawCommand command;
    command.op = "drawArc";
    command.x = x;
    command.y = y;
    command.outer_radius = outer_radius;
    command.inner_radius = inner_radius;
    command.start = start;
    command.end = end;
    command.color = color;
    commands_.push_back(std::move(command));
  }

  void fillRoundRect(int32_t x, int32_t y, int32_t width, int32_t height,
                     int32_t radius, uint32_t color) {
    sokkon_sim::DrawCommand command;
    command.op = "fillRoundRect";
    command.x = x;
    command.y = y;
    command.w = width;
    command.h = height;
    command.r = radius;
    command.color = color;
    commands_.push_back(std::move(command));
  }

  int32_t drawString(const char* text, int32_t x, int32_t y) {
    sokkon_sim::DrawCommand command;
    command.op = "drawString";
    command.text = text == nullptr ? "" : text;
    command.x = x;
    command.y = y;
    command.font = font_ == nullptr ? "Font2" : font_->name;
    command.font_size = font_ == nullptr ? 16 : font_->size_px;
    command.text_size = text_size_;
    command.datum = datumName(datum_);
    command.color = color_;
    command.background = background_;
    commands_.push_back(std::move(command));
    return textWidth(text);
  }

  void pushSprite(int32_t, int32_t) {
    sokkon_sim::runtime().published_commands = commands_;
  }

 private:
  static const char* datumName(int datum) {
    switch (datum) {
      case top_left:
        return "top_left";
      case top_center:
        return "top_center";
      default:
        return "middle_center";
    }
  }

  int32_t width_ = 0;
  int32_t height_ = 0;
  const SimFont* font_ = &fonts::Font2;
  int datum_ = middle_center;
  float text_size_ = 1.0F;
  uint32_t color_ = TFT_WHITE;
  uint32_t background_ = TFT_BLACK;
  std::vector<sokkon_sim::DrawCommand> commands_;
};

struct TouchDetail {
  bool pressed = false;
  int32_t x = 233;
  int32_t y = 233;
  bool isPressed() const { return pressed; }
};

class TouchStub {
 public:
  TouchDetail getDetail() const {
    const auto& state = sokkon_sim::runtime();
    return {state.touch_pressed, state.touch_x, state.touch_y};
  }
};

class ButtonStub {
 public:
  explicit ButtonStub(bool is_a) : is_a_(is_a) {}

  bool wasPressed() {
    auto& state = sokkon_sim::runtime();
    bool& pressed = is_a_ ? state.button_a : state.button_b;
    const bool result = pressed;
    pressed = false;
    return result;
  }

 private:
  bool is_a_;
};

namespace m5 {
enum class Power_Class {
  not_charging = 0,
  is_charging = 1,
};
}  // namespace m5

class PowerStub {
 public:
  int getBatteryLevel() const { return sokkon_sim::runtime().battery_percent; }
  m5::Power_Class isCharging() const {
    return sokkon_sim::runtime().charging ? m5::Power_Class::is_charging
                                          : m5::Power_Class::not_charging;
  }
  void setVibration(uint8_t intensity) {
    auto& state = sokkon_sim::runtime();
    state.vibration = intensity;
    if (intensity != 0) {
      state.last_vibration = intensity;
      ++state.haptic_pulses;
    }
  }
};

class SpeakerStub {
 public:
  void setVolume(uint8_t) {}
  void tone(uint16_t, uint16_t) {}
  void end() {}
};

struct RtcTime {
  int hours = 0;
  int minutes = 0;
  int seconds = 0;
};

struct RtcDateTime {
  RtcTime time;
};

class RtcStub {
 public:
  bool isEnabled() const { return true; }
  RtcDateTime getDateTime() const {
    const uint64_t seconds = sokkon_sim::runtime().now_us / 1000000ULL;
    const uint64_t day_seconds = (12ULL * 3600ULL + 34ULL * 60ULL + seconds) % 86400ULL;
    return {{static_cast<int>(day_seconds / 3600ULL),
             static_cast<int>((day_seconds / 60ULL) % 60ULL),
             static_cast<int>(day_seconds % 60ULL)}};
  }
};

struct M5ConfigStub {
  uint32_t serial_baudrate = 115200;
  bool clear_display = true;
  bool internal_imu = true;
  bool internal_rtc = true;
  bool internal_spk = true;
  bool output_power = true;
};

class M5UnifiedStub {
 public:
  M5DisplayStub Display;
  TouchStub Touch;
  ButtonStub BtnA{true};
  ButtonStub BtnB{false};
  PowerStub Power;
  SpeakerStub Speaker;
  RtcStub Rtc;

  M5ConfigStub config() const { return {}; }
  void begin(const M5ConfigStub&) {}
  void update() {}
  int getBoard() const { return 152; }
};

inline M5UnifiedStub M5;
