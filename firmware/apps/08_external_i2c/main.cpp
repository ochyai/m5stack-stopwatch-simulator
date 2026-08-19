#include <Arduino.h>
#include <M5Unified.h>

#include "board.hpp"

namespace {

bool external_i2c_ready = false;

void scanBus() {
  M5.Display.fillRect(44, 72, 378, 326, TFT_BLACK);
  M5.Display.setTextDatum(top_left);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.setCursor(72, 80);
  M5.Display.printf("PORT.A I2C\nSDA GPIO%d / SCL GPIO%d\n\n",
                    c152::kGroveSda, c152::kGroveScl);

  uint8_t found[32] = {};
  size_t found_count = 0;
  // M5Unified excludes 0x00-0x07 on ESP32-S3 because probing those reserved
  // addresses can halt the controller. 0x78-0x7F are reserved as well.
  for (uint8_t address = 0x08; address < 0x78; ++address) {
    if (M5.Ex_I2C.scanID(address)) {
      if (found_count < sizeof(found)) found[found_count] = address;
      ++found_count;
      Serial.printf("external_i2c,0x%02X\n", address);
    }
  }

  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  if (found_count == 0) {
    M5.Display.println("No devices found.\nConnect an I2C Unit to PORT.A.");
  } else {
    M5.Display.printf("Found %u device(s):\n", static_cast<unsigned>(found_count));
    const size_t shown = min(found_count, sizeof(found));
    for (size_t index = 0; index < shown; ++index) {
      M5.Display.printf("  0x%02X%s", found[index],
                        (index % 5 == 4) ? "\n" : "");
    }
  }
  c152::drawFooter("A / touch: scan again", TFT_CYAN);
}

}  // namespace

void setup() {
  c152::begin("08 / EXTERNAL I2C");
  M5.Power.setExtOutput(true);
  delay(100);
  external_i2c_ready = M5.Ex_I2C.begin();
  if (external_i2c_ready) {
    scanBus();
  } else {
    M5.Display.setTextDatum(middle_center);
    M5.Display.setTextColor(TFT_RED, TFT_BLACK);
    M5.Display.drawString("PORT.A I2C init failed", M5.Display.width() / 2,
                          M5.Display.height() / 2);
    c152::drawFooter("Check board configuration", TFT_RED);
    Serial.println("external_i2c_init=failed");
  }
}

void loop() {
  c152::update();
  if (external_i2c_ready && c152::primaryWasPressed()) {
    scanBus();
    // Signal completion after the synchronous bus scan so the timed
    // vibration is serviced immediately by the normal update loop.
    c152::feedback(4200, 45, 45);
  }
  delay(10);
}
