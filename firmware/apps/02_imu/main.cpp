#include <Arduino.h>
#include <M5Unified.h>

#include "board.hpp"

namespace {

uint32_t last_draw_ms = 0;

void drawImu(float ax, float ay, float az, float gx, float gy, float gz) {
  M5.Display.fillRect(42, 72, 382, 330, TFT_BLACK);
  M5.Display.setTextDatum(top_left);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(80, 92);
  M5.Display.println("ACCELERATION (g)");
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.printf("  X  %+7.3f\n  Y  %+7.3f\n  Z  %+7.3f\n", ax, ay, az);
  M5.Display.setTextColor(TFT_MAGENTA, TFT_BLACK);
  M5.Display.println("\nGYROSCOPE (dps)");
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.printf("  X  %+7.2f\n  Y  %+7.2f\n  Z  %+7.2f", gx, gy, gz);

  const int cx = M5.Display.width() / 2;
  const int cy = 372;
  M5.Display.drawCircle(cx, cy, 26, TFT_DARKGREY);
  const int dot_x = cx + static_cast<int>(constrain(ax, -1.0f, 1.0f) * 22.0f);
  const int dot_y = cy + static_cast<int>(constrain(ay, -1.0f, 1.0f) * 22.0f);
  M5.Display.fillCircle(dot_x, dot_y, 5, TFT_GREEN);
}
}  // namespace

void setup() {
  c152::begin("02 / BMI270 IMU");
  if (!M5.Imu.isEnabled()) {
    M5.Display.setTextDatum(middle_center);
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.drawString("BMI270 not detected", M5.Display.width() / 2,
                          M5.Display.height() / 2);
  }
  c152::drawFooter("Move and rotate the watch", TFT_GREEN);
}

void loop() {
  c152::update();
  if (M5.Imu.update() && millis() - last_draw_ms >= 80) {
    last_draw_ms = millis();
    const auto data = M5.Imu.getImuData();
    drawImu(data.accel.x, data.accel.y, data.accel.z, data.gyro.x,
            data.gyro.y, data.gyro.z);
    Serial.printf("a,%f,%f,%f,g,%f,%f,%f\n", data.accel.x, data.accel.y,
                  data.accel.z, data.gyro.x, data.gyro.y, data.gyro.z);
  }
  delay(5);
}
