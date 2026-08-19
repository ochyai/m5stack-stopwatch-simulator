#include <Arduino.h>
#include <M5Unified.h>
#include <esp_timer.h>

#include <math.h>

#include "board.hpp"
#include "helpers.hpp"
#include "stopwatch_core.hpp"

namespace {

c152::StopwatchCore stopwatch;
M5Canvas canvas(&M5.Display);
bool canvas_ready = false;
uint32_t last_draw_ms = 0;
uint32_t last_sensor_ms = 0;
int battery_percent = 0;
bool charging = false;
float tilt_x = 0;
float tilt_y = 0;
char rtc_text[24] = "--:--:--";

uint64_t nowMicros() {
  return static_cast<uint64_t>(esp_timer_get_time());
}

void updateSensors() {
  battery_percent = c152::clampPercent(M5.Power.getBatteryLevel());
  charging = M5.Power.isCharging() == m5::Power_Class::is_charging;
  c152::formatRtcTime(rtc_text, sizeof(rtc_text));
  if (M5.Imu.update()) {
    const auto data = M5.Imu.getImuData();
    tilt_x = data.accel.x;
    tilt_y = data.accel.y;
  }
}

void drawUi(uint64_t elapsed_us) {
  M5Canvas& gfx = canvas;
  const int width = gfx.width();
  const int height = gfx.height();
  const int cx = width / 2;
  const int cy = height / 2;
  const uint32_t accent = stopwatch.isRunning() ? TFT_CYAN : TFT_MAGENTA;

  gfx.fillScreen(TFT_BLACK);
  gfx.drawCircle(cx, cy, width / 2 - 3, 0x2124);
  gfx.drawCircle(cx, cy, width / 2 - 9, 0x18E3);

  const uint32_t centiseconds = (elapsed_us / 10000ULL) % 100ULL;
  const int arc_end = static_cast<int>(centiseconds * 360U / 100U);
  if (arc_end > 2) {
    gfx.drawArc(cx, cy, width / 2 - 15, width / 2 - 25, 0, arc_end,
                accent);
  }

  gfx.setTextDatum(middle_center);
  gfx.setFont(&fonts::Font2);
  gfx.setTextSize(1);
  gfx.setTextColor(accent, TFT_BLACK);
  gfx.drawString(stopwatch.isRunning() ? "RUNNING" : "PAUSED", cx, 74);

  char elapsed_text[24];
  c152::formatElapsed(elapsed_us, elapsed_text, sizeof(elapsed_text));
  gfx.setFont(&fonts::FreeSansBold24pt7b);
  gfx.setTextColor(TFT_WHITE, TFT_BLACK);
  gfx.drawString(elapsed_text, cx, cy - 14);

  gfx.setFont(&fonts::Font2);
  gfx.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  gfx.drawString("A / TOUCH  start / pause", cx, cy + 62);
  gfx.drawString("B          reset", cx, cy + 88);

  char status[96];
  snprintf(status, sizeof(status), "%s  BAT %d%%%s", rtc_text,
           battery_percent, charging ? "+" : "");
  gfx.setTextColor(charging ? TFT_GREEN : TFT_CYAN, TFT_BLACK);
  gfx.drawString(status, cx, height - 95);

  snprintf(status, sizeof(status), "IMU tilt  X%+.2f  Y%+.2f", tilt_x,
           tilt_y);
  gfx.setTextColor(TFT_DARKGREY, TFT_BLACK);
  gfx.drawString(status, cx, height - 65);

  gfx.fillCircle(65, cy, 9, TFT_YELLOW);
  gfx.fillCircle(width - 65, cy, 9, TFT_BLUE);
  gfx.pushSprite(0, 0);
}

}  // namespace

void setup() {
  c152::begin("99 / STOPWATCH");
  canvas.setColorDepth(16);
  canvas_ready = canvas.createSprite(M5.Display.width(), M5.Display.height());
  if (!canvas_ready) {
    Serial.println("canvas allocation failed");
    M5.Display.setTextDatum(middle_center);
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.drawString("Canvas allocation failed",
                          M5.Display.width() / 2, M5.Display.height() / 2);
    return;
  }
  updateSensors();
  drawUi(0);
}

void loop() {
  c152::update();
  const uint64_t now_us = nowMicros();
  const bool reset_pressed = M5.BtnB.wasPressed();
  const bool primary_pressed = c152::primaryWasPressed();

  if (reset_pressed) {
    stopwatch.reset(now_us);
    c152::feedback(2600, 90, 150);
  } else if (primary_pressed) {
    stopwatch.toggle(now_us);
    c152::feedback(stopwatch.isRunning() ? 5600 : 3800, 70,
                   stopwatch.isRunning() ? 110 : 75);
  }

  if (millis() - last_sensor_ms >= 500) {
    last_sensor_ms = millis();
    updateSensors();
  }
  if (canvas_ready && millis() - last_draw_ms >= 33) {
    last_draw_ms = millis();
    drawUi(stopwatch.elapsedUs(now_us));
  }
  delay(2);
}
