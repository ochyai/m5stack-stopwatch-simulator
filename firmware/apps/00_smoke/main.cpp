#include <Arduino.h>
#include <M5Unified.h>

#include "board.hpp"

namespace {

uint32_t last_heartbeat_ms = 0;
bool heartbeat_on = false;

void drawCapabilities() {
  M5.Display.setTextDatum(top_left);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setCursor(72, 96);
  M5.Display.printf("Board enum  %d\n", static_cast<int>(M5.getBoard()));
  M5.Display.printf("AMOLED      %d x %d\n", M5.Display.width(),
                    M5.Display.height());
  M5.Display.printf("Flash       %u MB\n", ESP.getFlashChipSize() / 1048576U);
  M5.Display.printf("PSRAM       %u MB\n", ESP.getPsramSize() / 1048576U);
  M5.Display.printf("Touch       %s\n", M5.Touch.isEnabled() ? "ready" : "not found");
  M5.Display.printf("IMU         %s\n", M5.Imu.isEnabled() ? "ready" : "not found");
  M5.Display.printf("RTC         %s\n", M5.Rtc.isEnabled() ? "ready" : "not found");
}
}  // namespace

void setup() {
  c152::begin("00 / SMOKE TEST");
  drawCapabilities();
  c152::drawFooter("A / touch / B: input test", TFT_GREEN);
}

void loop() {
  c152::update();

  const bool a = M5.BtnA.wasPressed();
  const bool b = M5.BtnB.wasPressed();
  const bool touch = c152::touchWasPressed();
  if (a || b || touch) {
    const char* source = a ? "A" : (b ? "B" : "TOUCH");
    char message[48];
    snprintf(message, sizeof(message), "%s OK  uptime %lus", source,
             static_cast<unsigned long>(millis() / 1000U));
    c152::drawFooter(message, a ? TFT_YELLOW : (b ? TFT_BLUE : TFT_CYAN));
    c152::feedback(a ? 5200 : (b ? 3600 : 4400), 60, 80);
    Serial.printf("input=%s uptime_ms=%lu\n", source,
                  static_cast<unsigned long>(millis()));
  }

  if (millis() - last_heartbeat_ms >= 500) {
    last_heartbeat_ms = millis();
    heartbeat_on = !heartbeat_on;
    M5.Display.fillCircle(M5.Display.width() / 2, 352, 12,
                          heartbeat_on ? TFT_GREEN : TFT_DARKGREEN);
  }
  delay(5);
}
