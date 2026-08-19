#pragma once

#include <M5Unified.h>
#include <stdint.h>

namespace c152 {

constexpr int kGroveSda = 10;
constexpr int kGroveScl = 11;

void begin(const char* title);
void update();

// Button A and a new touch both act as the primary action.
bool touchWasPressed();
bool primaryWasPressed();

// Starts a short, non-blocking tone and vibration pulse.
void feedback(uint16_t frequency_hz = 4400, uint16_t duration_ms = 70,
              uint8_t vibration = 100);

void drawHeader(const char* title, uint32_t accent = TFT_CYAN);
void drawFooter(const char* text, uint32_t color = TFT_DARKGREY);
void formatRtcTime(char* output, size_t output_size);

}  // namespace c152
