#include <Arduino.h>
#include <M5Unified.h>

#include "board.hpp"
#include "helpers.hpp"

namespace {

uint32_t last_draw_ms = 0;
uint8_t brightness_index = 1;
constexpr uint8_t kBrightness[] = {32, 96, 180};

void drawStatus() {
  M5.Display.fillRect(48, 78, 370, 320, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);

  char time_text[24];
  c152::formatRtcTime(time_text, sizeof(time_text));
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.drawString(time_text, M5.Display.width() / 2, 132);
  M5.Display.setTextSize(1);

  const int battery = c152::clampPercent(M5.Power.getBatteryLevel());
  const int voltage_mv = M5.Power.getBatteryVoltage();
  const bool charging =
      M5.Power.isCharging() == m5::Power_Class::is_charging;
  M5.Display.setTextColor(charging ? TFT_GREEN : TFT_WHITE, TFT_BLACK);
  M5.Display.drawString(charging ? "CHARGING" : "ON BATTERY",
                        M5.Display.width() / 2, 210);
  char battery_text[48];
  snprintf(battery_text, sizeof(battery_text), "%d%%   %d mV", battery,
           voltage_mv);
  M5.Display.setTextSize(2);
  M5.Display.drawString(battery_text, M5.Display.width() / 2, 260);
  M5.Display.setTextSize(1);

  const int bar_width = 270;
  const int bar_x = (M5.Display.width() - bar_width) / 2;
  M5.Display.drawRoundRect(bar_x, 310, bar_width, 28, 8, TFT_DARKGREY);
  M5.Display.fillRoundRect(bar_x + 4, 314,
                           (bar_width - 8) * battery / 100, 20, 5,
                           battery > 20 ? TFT_GREEN : TFT_RED);
}

}  // namespace

void setup() {
  c152::begin("03 / RTC + POWER");
  c152::drawFooter("A / touch: brightness", TFT_LIGHTGREY);
  drawStatus();
}

void loop() {
  c152::update();
  if (c152::primaryWasPressed()) {
    brightness_index = (brightness_index + 1) % 3;
    M5.Display.setBrightness(kBrightness[brightness_index]);
    c152::feedback(4200, 45, 55);
  }
  if (millis() - last_draw_ms >= 500) {
    last_draw_ms = millis();
    drawStatus();
  }
  delay(5);
}
