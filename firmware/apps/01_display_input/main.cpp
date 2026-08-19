#include <Arduino.h>
#include <M5Unified.h>

#include "board.hpp"

namespace {

void drawControls() {
  const int width = M5.Display.width();
  M5.Display.fillCircle(width / 2, 232, 126, 0x18E3);
  M5.Display.drawCircle(width / 2, 232, 126, TFT_DARKGREY);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_YELLOW, 0x18E3);
  M5.Display.drawString("YELLOW: A", width / 2, 190);
  M5.Display.setTextColor(TFT_BLUE, 0x18E3);
  M5.Display.drawString("BLUE: B", width / 2, 222);
  M5.Display.setTextColor(TFT_CYAN, 0x18E3);
  M5.Display.drawString("TOUCH THE AMOLED", width / 2, 274);
}
}  // namespace

void setup() {
  c152::begin("01 / DISPLAY + INPUT");
  drawControls();
  c152::drawFooter("Touch draws a point", TFT_LIGHTGREY);
}

void loop() {
  c152::update();
  const auto touch = M5.Touch.getDetail();

  if (touch.isPressed()) {
    M5.Display.fillCircle(touch.x, touch.y, 7, TFT_CYAN);
    char status[48];
    snprintf(status, sizeof(status), "touch x=%d y=%d", touch.x, touch.y);
    c152::drawFooter(status, TFT_CYAN);
  }
  if (M5.BtnA.wasPressed()) {
    c152::drawFooter("Button A pressed", TFT_YELLOW);
    c152::feedback(5200, 55, 70);
  }
  if (M5.BtnB.wasPressed()) {
    c152::drawFooter("Button B pressed", TFT_BLUE);
    c152::feedback(3600, 55, 70);
  }
  if (M5.BtnA.wasHold() || M5.BtnB.wasHold()) {
    c152::drawHeader("01 / DISPLAY + INPUT");
    drawControls();
    c152::drawFooter("Canvas cleared", TFT_LIGHTGREY);
  }
  delay(5);
}
