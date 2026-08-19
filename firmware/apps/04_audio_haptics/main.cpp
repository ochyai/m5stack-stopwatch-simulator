#include <Arduino.h>
#include <M5Unified.h>

#include "board.hpp"

namespace {

constexpr uint16_t kToneFrequency = 1760;
constexpr uint8_t kVibrationStrength = 120;
constexpr size_t kSampleCount = 256;
constexpr uint32_t kSampleRate = 16000;

int16_t mic_samples[kSampleCount] = {};
bool mic_mode = false;
uint32_t last_meter_ms = 0;

void drawSpeakerMode() {
  M5.Display.fillRect(54, 88, 358, 290, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_MAGENTA, TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.drawString("SPEAKER + HAPTIC", M5.Display.width() / 2, 150);
  M5.Display.setTextSize(1);
  char details[64];
  snprintf(details, sizeof(details), "%u Hz     strength %u",
           kToneFrequency, kVibrationStrength);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  M5.Display.drawString(details, M5.Display.width() / 2, 224);
  M5.Display.drawCircle(M5.Display.width() / 2, 310, 58, TFT_CYAN);
  c152::drawFooter("A/touch: play   B: microphone", TFT_CYAN);
}

void playPattern() {
  c152::feedback(kToneFrequency, 130, kVibrationStrength);
  Serial.printf("tone=%uHz vibration=%u\n", kToneFrequency,
                kVibrationStrength);
}

void enterMicMode() {
  while (M5.Speaker.isPlaying()) {
    M5.delay(1);
  }
  // StopWatch shares its ES8311 audio path. The official examples require
  // switching the speaker off before the microphone is started.
  M5.Speaker.end();
  M5.Mic.begin();
  mic_mode = true;
  M5.Display.fillRect(54, 88, 358, 290, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_GREEN, TFT_BLACK);
  M5.Display.setTextSize(2);
  M5.Display.drawString("MIC LEVEL", M5.Display.width() / 2, 136);
  M5.Display.setTextSize(1);
  M5.Display.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  M5.Display.drawString("MEMS MIC / 16 kHz", M5.Display.width() / 2, 184);
  c152::drawFooter("Make a sound   B: speaker", TFT_GREEN);
}

void leaveMicMode() {
  while (M5.Mic.isRecording()) {
    M5.delay(1);
  }
  M5.Mic.end();
  M5.Speaker.begin();
  M5.Speaker.setVolume(72);
  mic_mode = false;
  drawSpeakerMode();
}

void updateMicMeter() {
  if (!M5.Mic.isEnabled() || M5.Mic.isRecording() ||
      millis() - last_meter_ms < 40) {
    return;
  }
  last_meter_ms = millis();
  if (!M5.Mic.record(mic_samples, kSampleCount, kSampleRate)) {
    return;
  }
  while (M5.Mic.isRecording()) {
    M5.delay(1);
  }

  int64_t sum = 0;
  for (const int16_t sample : mic_samples) {
    sum += sample;
  }
  const int32_t dc = static_cast<int32_t>(sum / kSampleCount);
  uint32_t peak = 0;
  for (const int16_t sample : mic_samples) {
    const uint32_t magnitude = abs(static_cast<int32_t>(sample) - dc);
    if (magnitude > peak) peak = magnitude;
  }

  const int meter = constrain(static_cast<int>(peak / 96U), 0, 280);
  const int x = (M5.Display.width() - 280) / 2;
  M5.Display.fillRoundRect(x, 238, 280, 38, 10, 0x18E3);
  M5.Display.fillRoundRect(x, 238, meter, 38, 10,
                           meter > 230 ? TFT_RED : TFT_GREEN);
  M5.Display.fillRect(80, 294, 306, 34, TFT_BLACK);
  M5.Display.setTextDatum(middle_center);
  M5.Display.setFont(&fonts::Font2);
  M5.Display.setTextColor(TFT_WHITE, TFT_BLACK);
  char text[40];
  snprintf(text, sizeof(text), "peak %lu", static_cast<unsigned long>(peak));
  M5.Display.drawString(text, M5.Display.width() / 2, 310);
  Serial.printf("mic_peak=%lu\n", static_cast<unsigned long>(peak));
}

}  // namespace

void setup() {
  c152::begin("04 / AUDIO + HAPTICS");
  drawSpeakerMode();
}

void loop() {
  c152::update();
  if (!mic_mode && c152::primaryWasPressed()) {
    playPattern();
  }
  if (M5.BtnB.wasPressed()) {
    if (mic_mode) {
      leaveMicMode();
    } else {
      enterMicMode();
    }
  }
  if (mic_mode) {
    // Consume touch edges while the live meter owns the primary interaction.
    c152::touchWasPressed();
    updateMicMeter();
  }
  delay(5);
}
