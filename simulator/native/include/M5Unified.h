#pragma once

#include "Arduino.h"
#include "sim_runtime.hpp"
#include "sim_text.hpp"

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

// LovyanGFX textdatum_t values. The device derives its anchor arithmetic from
// these bits (1:centre 2:right | 4:middle 8:bottom 16:baseline), so the HAL
// must use the real numbers rather than symbolic placeholders.
constexpr int top_left = 0;
constexpr int top_center = 1;
constexpr int top_right = 2;
constexpr int middle_left = 4;
constexpr int middle_center = 5;
constexpr int middle_right = 6;
constexpr int bottom_left = 8;
constexpr int bottom_center = 9;
constexpr int bottom_right = 10;
constexpr int baseline_left = 16;
constexpr int baseline_center = 17;
constexpr int baseline_right = 18;

struct SimFont {
  const char* name;
};

namespace fonts {
inline constexpr SimFont Font2{"Font2"};
inline constexpr SimFont FreeSansBold24pt7b{"FreeSansBold24pt7b"};
inline constexpr SimFont FreeSansBold18pt7b{"FreeSansBold18pt7b"};
}  // namespace fonts

namespace sim_hal {

inline const sim_font::Metrics& metricsFor(const SimFont* font) {
  return sim_font::byName(font == nullptr ? nullptr : font->name);
}

inline const char* datumName(int datum) {
  switch (datum) {
    case top_left: return "top_left";
    case top_center: return "top_center";
    case top_right: return "top_right";
    case middle_left: return "middle_left";
    case middle_right: return "middle_right";
    case bottom_left: return "bottom_left";
    case bottom_center: return "bottom_center";
    case bottom_right: return "bottom_right";
    case baseline_left: return "baseline_left";
    case baseline_center: return "baseline_center";
    case baseline_right: return "baseline_right";
    default: return "middle_center";
  }
}

}  // namespace sim_hal

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
    return sim_text::textWidth(sim_hal::metricsFor(font_), text, text_size_);
  }
  int32_t fontHeight() const {
    return sim_text::applyScale(sim_hal::metricsFor(font_).height,
                                sim_text::fixedScale(text_size_));
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
    return sim_text::textWidth(sim_hal::metricsFor(font_), text, text_size_);
  }
  int32_t fontHeight() const {
    return sim_text::applyScale(sim_hal::metricsFor(font_).height,
                                sim_text::fixedScale(text_size_));
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
    const sim_font::Metrics& metrics = sim_hal::metricsFor(font_);
    const sim_text::Layout placement =
        sim_text::layout(metrics, text, x, y, datum_, text_size_, text_size_);

    sokkon_sim::DrawCommand command;
    command.op = "drawString";
    command.text = text == nullptr ? "" : text;
    command.x = x;
    command.y = y;
    command.font = metrics.name;
    command.font_size = metrics.height;
    command.text_size = text_size_;
    command.datum = sim_hal::datumName(datum_);
    command.color = color_;
    command.background = background_;
    command.text_left = placement.left;
    command.text_top = placement.top;
    command.text_baseline = placement.baseline;
    command.text_pixel_width = placement.width;
    command.text_box_height = placement.height;
    command.pen_x = placement.pen;
    commands_.push_back(std::move(command));
    return placement.width;
  }

  void pushSprite(int32_t, int32_t) {
    sokkon_sim::runtime().published_commands = commands_;
  }

 private:
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

struct ImuAxis3 {
  float x = 0.0F;
  float y = 0.0F;
  float z = 0.0F;
};

struct ImuData {
  ImuAxis3 accel;
  ImuAxis3 gyro;
};

class ImuStub {
 public:
  bool isEnabled() const { return true; }
  bool update() const { return true; }
  ImuData getImuData() const {
    const auto& state = sokkon_sim::runtime();
    return {{state.imu_accel_x, state.imu_accel_y, state.imu_accel_z},
            {state.imu_gyro_x, state.imu_gyro_y, state.imu_gyro_z}};
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
  ImuStub Imu;

  M5ConfigStub config() const { return {}; }
  void begin(const M5ConfigStub&) {}
  void update() {}
  int getBoard() const { return 152; }
};

inline M5UnifiedStub M5;
