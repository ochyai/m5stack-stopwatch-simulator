#include <Arduino.h>
#include <M5Unified.h>
#include <WiFi.h>

#include "board.hpp"

namespace {

void scanAndDraw() {
  M5.Display.fillRect(38, 66, 390, 342, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_CYAN, TFT_BLACK);
  M5.Display.drawString("Scanning 2.4 GHz...", M5.Display.width() / 2, 95);

  WiFi.scanDelete();
  const int count = WiFi.scanNetworks(false, true);
  M5.Display.fillRect(38, 66, 390, 342, TFT_BLACK);
  M5.Display.setTextDatum(top_left);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.setCursor(70, 76);
  M5.Display.printf("%d networks found\n\n", count < 0 ? 0 : count);

  const int rows = min(count, 8);
  for (int index = 0; index < rows; ++index) {
    String ssid = WiFi.SSID(index);
    if (ssid.length() == 0) ssid = "<hidden>";
    if (ssid.length() > 20) ssid = ssid.substring(0, 19) + "~";
    const int rssi = WiFi.RSSI(index);
    const bool open = WiFi.encryptionType(index) == WIFI_AUTH_OPEN;
    M5.Display.setTextColor(rssi > -67 ? TFT_GREEN : TFT_LIGHTGREY,
                            TFT_BLACK);
    M5.Display.printf("%2d  %-20s %4d %s\n", index + 1, ssid.c_str(), rssi,
                      open ? " " : "*");
    // Keep nearby SSIDs on the local display only; serial logs are often
    // persisted and should not collect location-identifying network names.
    Serial.printf("wifi,%d,rssi=%d,%s\n", index + 1, rssi,
                  open ? "open" : "secured");
  }
  WiFi.scanDelete();
  c152::drawFooter("A / touch: scan again", TFT_CYAN);
}

}  // namespace

void setup() {
  c152::begin("05 / WI-FI SCAN");
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);
  scanAndDraw();
}

void loop() {
  c152::update();
  if (c152::primaryWasPressed()) {
    // Wi-Fi scanning blocks for seconds, so do not leave a timed vibration
    // running while c152::update() cannot turn it off.
    c152::feedback(4600, 45, 0);
    scanAndDraw();
  }
  delay(10);
}
