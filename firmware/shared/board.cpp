#include "board.hpp"

#include <stdio.h>

namespace {

uint32_t vibration_until_ms = 0;
bool vibration_active = false;
bool previous_touch_down = false;

}  // namespace

namespace c152 {

void begin(const char* title) {
  auto config = M5.config();
  config.serial_baudrate = 115200;
  config.clear_display = true;
  config.internal_imu = true;
  config.internal_rtc = true;
  config.internal_spk = true;
  config.output_power = true;
  M5.begin(config);

  M5.Display.setRotation(0);
  M5.Display.setBrightness(96);
  M5.Display.setTextWrap(false);
  M5.Speaker.setVolume(72);
  previous_touch_down = M5.Touch.getDetail().isPressed();
  drawHeader(title);

  Serial.printf("\nM5Stack StopWatch C152: %s\n", title);
  Serial.printf("display=%dx%d board=%d\n", M5.Display.width(),
                M5.Display.height(), static_cast<int>(M5.getBoard()));
}

void update() {
  M5.update();
  if (vibration_active &&
      static_cast<int32_t>(millis() - vibration_until_ms) >= 0) {
    M5.Power.setVibration(0);
    vibration_active = false;
  }
}

bool touchWasPressed() {
  const bool touch_down = M5.Touch.getDetail().isPressed();
  const bool pressed = touch_down && !previous_touch_down;
  previous_touch_down = touch_down;
  return pressed;
}

bool primaryWasPressed() {
  const bool button_pressed = M5.BtnA.wasPressed();
  const bool touch_pressed = touchWasPressed();
  return button_pressed || touch_pressed;
}

void feedback(uint16_t frequency_hz, uint16_t duration_ms,
              uint8_t vibration) {
  if (frequency_hz != 0 && duration_ms != 0) {
    M5.Speaker.tone(frequency_hz, duration_ms);
  }
  if (vibration != 0 && duration_ms != 0) {
    M5.Power.setVibration(vibration);
    vibration_until_ms = millis() + duration_ms;
    vibration_active = true;
  }
}

void drawHeader(const char* title, uint32_t accent) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.fillCircle(M5.Display.width() / 2, 0,
                        M5.Display.width() / 2, accent);
  M5.Display.fillRect(0, 0, M5.Display.width(), 54, accent);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_BLACK, accent);
  M5.Display.drawString(title, M5.Display.width() / 2, 28);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
}

void drawFooter(const char* text, uint32_t color) {
  const int y = M5.Display.height() - 58;
  M5.Display.fillRect(0, y, M5.Display.width(), 58, TFT_BLACK);
  M5.Display.drawFastHLine(86, y, M5.Display.width() - 172, color);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(color, TFT_BLACK);
  M5.Display.drawString(text, M5.Display.width() / 2, y + 25);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
}

void formatRtcTime(char* output, size_t output_size) {
  if (output == nullptr || output_size == 0) {
    return;
  }
  if (!M5.Rtc.isEnabled()) {
    snprintf(output, output_size, "RTC --:--:--");
    return;
  }
  const auto datetime = M5.Rtc.getDateTime();
  snprintf(output, output_size, "%02d:%02d:%02d", datetime.time.hours,
           datetime.time.minutes, datetime.time.seconds);
}

}  // namespace c152
