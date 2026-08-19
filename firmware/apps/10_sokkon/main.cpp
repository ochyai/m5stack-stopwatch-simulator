#include <Arduino.h>
#include <M5Unified.h>
#include <esp_system.h>
#include <esp_timer.h>

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "board.hpp"
#include "helpers.hpp"
#include "stopwatch_core.hpp"

namespace {

constexpr const char* kModes[] = {"NOW", "BUILD", "READ",
                                  "MEET", "PRESENT", "REST"};
constexpr size_t kModeCount = sizeof(kModes) / sizeof(kModes[0]);
constexpr uint32_t kHostTimeoutMs = 5000;
constexpr size_t kSerialLineSize = 256;
constexpr size_t kPendingEventCount = 8;
constexpr uint32_t kResultTimeoutMs = 30000;
constexpr uint32_t kDimAfterMs = 2UL * 60UL * 1000UL;
constexpr uint32_t kSleepAfterMs = 10UL * 60UL * 1000UL;

enum class Intent : uint8_t {
  kCapture,
  kFocusToggle,
  kModeNext,
};

struct PendingEvent {
  uint32_t sequence = 0;
  uint32_t created_at_ms = 0;
  uint32_t event_uptime_ms = 0;
  uint64_t elapsed_ms = 0;
  Intent intent = Intent::kCapture;
  uint8_t mode = 0;
  bool focus_running = false;
  bool accepted = false;
  bool active = false;
};

struct HapticPattern {
  uint8_t pulses_remaining = 0;
  uint8_t intensity = 0;
  uint16_t duration_ms = 0;
  uint16_t gap_ms = 0;
  uint32_t next_pulse_ms = 0;
};

c152::StopwatchCore focus_timer;
M5Canvas canvas(&M5.Display);
bool canvas_ready = false;

char serial_line[kSerialLineSize] = {};
size_t serial_line_length = 0;
bool serial_line_overflow = false;

char host_time[8] = "--:--";
char context_text[40] = "MAC NOT CONNECTED";
char detail_text[64] = "USB-C TO BEGIN";
char rtc_text[24] = "--:--:--";
char toast_text[24] = {};

size_t mode_index = 0;
uint32_t last_host_ms = 0;
uint32_t last_draw_ms = 0;
uint32_t last_sensor_ms = 0;
uint32_t toast_until_ms = 0;
uint32_t mark_count = 0;
uint32_t next_sequence = 1;
uint64_t device_id = 0;
uint64_t boot_session = 0;
uint32_t last_interaction_ms = 0;
int battery_percent = 0;
bool charging = false;
bool host_seen = false;
bool previous_touch_down = false;
bool display_dimmed = false;
bool display_sleeping = false;
PendingEvent pending_events[kPendingEventCount];
HapticPattern haptic_pattern;

uint64_t nowMicros() {
  return static_cast<uint64_t>(esp_timer_get_time());
}

bool hostConnected(uint32_t now_ms) {
  return host_seen && (now_ms - last_host_ms) < kHostTimeoutMs;
}

void wakeDisplay(uint32_t now_ms) {
  last_interaction_ms = now_ms;
  if (display_dimmed || display_sleeping) {
    M5.Display.setBrightness(96);
  }
  display_dimmed = false;
  display_sleeping = false;
}

void copyDisplayField(char* destination, size_t destination_size,
                      const char* source) {
  if (destination == nullptr || destination_size == 0) return;
  if (source == nullptr) {
    destination[0] = '\0';
    return;
  }

  size_t output = 0;
  for (size_t input = 0; source[input] != '\0' &&
                         output + 1 < destination_size;
       ++input) {
    const unsigned char value = static_cast<unsigned char>(source[input]);
    if (value >= 32 && value <= 126 && value != '|') {
      destination[output++] = static_cast<char>(value);
    } else if (value > 126) {
      destination[output++] = '?';
    }
  }
  destination[output] = '\0';
}

size_t splitFields(char* line, char* fields[], size_t field_capacity) {
  if (line == nullptr || fields == nullptr || field_capacity == 0) return 0;
  size_t count = 1;
  fields[0] = line;
  for (char* cursor = line; *cursor != '\0'; ++cursor) {
    if (*cursor == '|') {
      if (count >= field_capacity) return field_capacity + 1;
      *cursor = '\0';
      fields[count++] = cursor + 1;
    }
  }
  return count;
}

int findMode(const char* mode) {
  if (mode == nullptr) return -1;
  for (size_t index = 0; index < kModeCount; ++index) {
    if (strcmp(mode, kModes[index]) == 0) {
      return static_cast<int>(index);
    }
  }
  return -1;
}

uint32_t modeColor() {
  switch (mode_index) {
    case 1:
      return TFT_ORANGE;
    case 2:
      return TFT_GREEN;
    case 3:
      return 0x051F;
    case 4:
      return TFT_MAGENTA;
    case 5:
      return 0x7BEF;
    default:
      return TFT_CYAN;
  }
}

void showToast(const char* text, uint32_t duration_ms = 900) {
  wakeDisplay(millis());
  copyDisplayField(toast_text, sizeof(toast_text), text);
  toast_until_ms = millis() + duration_ms;
}

void startHaptic(uint8_t pulse_count, uint8_t intensity, uint16_t duration_ms,
                 uint16_t gap_ms = 45) {
  haptic_pattern = {};
  if (pulse_count == 0 || intensity == 0 || duration_ms == 0) return;

  c152::feedback(0, duration_ms, intensity);
  haptic_pattern.pulses_remaining = pulse_count - 1;
  haptic_pattern.intensity = intensity;
  haptic_pattern.duration_ms = duration_ms;
  haptic_pattern.gap_ms = gap_ms;
  haptic_pattern.next_pulse_ms = millis() + duration_ms + gap_ms;
}

void updateHaptic(uint32_t now_ms) {
  if (haptic_pattern.pulses_remaining == 0 ||
      static_cast<int32_t>(now_ms - haptic_pattern.next_pulse_ms) < 0) {
    return;
  }

  c152::feedback(0, haptic_pattern.duration_ms, haptic_pattern.intensity);
  --haptic_pattern.pulses_remaining;
  haptic_pattern.next_pulse_ms =
      now_ms + haptic_pattern.duration_ms + haptic_pattern.gap_ms;
}

const char* intentName(Intent intent) {
  switch (intent) {
    case Intent::kFocusToggle:
      return "FOCUS_TOGGLE";
    case Intent::kModeNext:
      return "MODE_NEXT";
    default:
      return "CAPTURE";
  }
}

PendingEvent* findPendingEvent(uint32_t sequence) {
  for (PendingEvent& pending : pending_events) {
    if (pending.active && pending.sequence == sequence) return &pending;
  }
  return nullptr;
}

PendingEvent* reservePendingEvent(uint32_t sequence, Intent intent,
                                  uint32_t now_ms, uint64_t now_us) {
  for (PendingEvent& pending : pending_events) {
    if (!pending.active) {
      pending.sequence = sequence;
      pending.created_at_ms = now_ms;
      pending.event_uptime_ms = now_ms;
      pending.elapsed_ms = focus_timer.elapsedUs(now_us) / 1000ULL;
      pending.intent = intent;
      pending.mode = static_cast<uint8_t>(mode_index);
      pending.focus_running = focus_timer.isRunning();
      pending.accepted = false;
      pending.active = true;
      return &pending;
    }
  }
  return nullptr;
}

void transmitPendingEvent(const PendingEvent& pending) {
  Serial.printf("EVENT|%012llX|%016llX|%lu|%s|%lu|%s|%s|%llu\n",
                static_cast<unsigned long long>(device_id),
                static_cast<unsigned long long>(boot_session),
                static_cast<unsigned long>(pending.sequence),
                intentName(pending.intent),
                static_cast<unsigned long>(pending.event_uptime_ms),
                kModes[pending.mode],
                pending.focus_running ? "RUNNING" : "PAUSED",
                static_cast<unsigned long long>(pending.elapsed_ms));
}

uint32_t sendEvent(Intent intent, uint32_t now_ms, uint64_t now_us) {
  uint32_t sequence = next_sequence++;
  if (sequence == 0) sequence = next_sequence++;
  PendingEvent* pending = reservePendingEvent(sequence, intent, now_ms, now_us);
  if (pending == nullptr) return 0;
  transmitPendingEvent(*pending);
  return sequence;
}

bool parseSequence(const char* text, uint32_t* sequence) {
  if (text == nullptr || sequence == nullptr || text[0] == '\0') return false;
  for (const char* cursor = text; *cursor != '\0'; ++cursor) {
    if (*cursor < '0' || *cursor > '9') return false;
  }
  errno = 0;
  char* end = nullptr;
  const unsigned long long value = strtoull(text, &end, 10);
  if (errno == ERANGE || end == text || *end != '\0' || value > UINT32_MAX) {
    return false;
  }
  *sequence = static_cast<uint32_t>(value);
  return true;
}

bool parseSession(const char* text, uint64_t* session) {
  if (text == nullptr || session == nullptr || strlen(text) != 16) return false;
  for (const char* cursor = text; *cursor != '\0'; ++cursor) {
    const bool digit = *cursor >= '0' && *cursor <= '9';
    const bool upper = *cursor >= 'A' && *cursor <= 'F';
    if (!digit && !upper) return false;
  }
  errno = 0;
  char* end = nullptr;
  const unsigned long long value = strtoull(text, &end, 16);
  if (errno == ERANGE || end == text || *end != '\0') return false;
  *session = static_cast<uint64_t>(value);
  return true;
}

bool handleAck(char* fields[], size_t field_count) {
  if (field_count != 4 || strcmp(fields[3], "ACCEPTED") != 0) return false;
  uint64_t session = 0;
  uint32_t sequence = 0;
  if (!parseSession(fields[1], &session) || session != boot_session ||
      !parseSequence(fields[2], &sequence)) {
    return false;
  }
  PendingEvent* pending = findPendingEvent(sequence);
  if (pending == nullptr) return false;
  pending->accepted = true;
  return true;
}

bool handleResult(char* fields[], size_t field_count) {
  if (field_count < 4 || field_count > 5) return false;
  uint64_t session = 0;
  uint32_t sequence = 0;
  if (!parseSession(fields[1], &session) || session != boot_session ||
      !parseSequence(fields[2], &sequence)) {
    return false;
  }
  PendingEvent* pending = findPendingEvent(sequence);
  if (pending == nullptr) return false;

  const bool succeeded = strcmp(fields[3], "OK") == 0 && field_count == 4;
  const bool failed = strcmp(fields[3], "ERROR") == 0 && field_count == 5 &&
                      fields[4][0] != '\0';
  if (!succeeded && !failed) return false;

  if (succeeded && pending->intent == Intent::kCapture) {
    ++mark_count;
    showToast("MARK SAVED", 1100);
    startHaptic(1, 155, 90);
  } else if (!succeeded) {
    showToast("MAC ERROR", 1400);
    startHaptic(3, 95, 45);
  }
  pending->active = false;
  return true;
}

void servicePendingEvents(uint32_t now_ms) {
  for (PendingEvent& pending : pending_events) {
    if (!pending.active) continue;
    if (now_ms - pending.created_at_ms >= kResultTimeoutMs) {
      showToast(pending.intent == Intent::kCapture ? "SAVE UNKNOWN"
                                                  : "MAC TIMEOUT",
                1600);
      startHaptic(3, 95, 45);
      pending.active = false;
      continue;
    }
  }
}

bool validHostTime(const char* text) {
  if (text == nullptr || strlen(text) != 5 || text[2] != ':') return false;
  if (text[0] < '0' || text[0] > '9' || text[1] < '0' || text[1] > '9' ||
      text[3] < '0' || text[3] > '9' || text[4] < '0' || text[4] > '9') {
    return false;
  }
  const int hour = (text[0] - '0') * 10 + text[1] - '0';
  const int minute = (text[3] - '0') * 10 + text[4] - '0';
  return hour < 24 && minute < 60;
}

void handleSerialLine(char* line) {
  char* fields[5] = {};
  const size_t field_count = splitFields(line, fields, 5);
  if (field_count == 0) return;

  if (strcmp(fields[0], "PING") == 0 && field_count == 1) {
    last_host_ms = millis();
    host_seen = true;
    Serial.printf("SOKKON|PONG|2|%012llX|%016llX\n",
                  static_cast<unsigned long long>(device_id),
                  static_cast<unsigned long long>(boot_session));
    return;
  }

  if (strcmp(fields[0], "ACK") == 0) {
    if (handleAck(fields, field_count)) {
      last_host_ms = millis();
      host_seen = true;
    }
    return;
  }

  if (strcmp(fields[0], "RESULT") == 0) {
    if (handleResult(fields, field_count)) {
      last_host_ms = millis();
      host_seen = true;
    }
    return;
  }

  if (strcmp(fields[0], "STATE") != 0 || field_count != 5 ||
      !validHostTime(fields[1])) {
    return;
  }

  const int requested_mode = findMode(fields[2]);
  if (requested_mode < 0) return;
  copyDisplayField(host_time, sizeof(host_time), fields[1]);
  mode_index = static_cast<size_t>(requested_mode);
  copyDisplayField(context_text, sizeof(context_text), fields[3]);
  copyDisplayField(detail_text, sizeof(detail_text), fields[4]);
  last_host_ms = millis();
  host_seen = true;
}

void readSerial() {
  while (Serial.available() > 0) {
    const char value = static_cast<char>(Serial.read());
    if (value == '\r') continue;
    if (value == '\n') {
      if (!serial_line_overflow && serial_line_length > 0) {
        serial_line[serial_line_length] = '\0';
        handleSerialLine(serial_line);
      }
      serial_line_length = 0;
      serial_line_overflow = false;
      continue;
    }

    if (serial_line_length + 1 < sizeof(serial_line)) {
      serial_line[serial_line_length++] = value;
    } else {
      serial_line_overflow = true;
    }
  }
}

void updateSensors() {
  battery_percent = c152::clampPercent(M5.Power.getBatteryLevel());
  charging = M5.Power.isCharging() == m5::Power_Class::is_charging;
  c152::formatRtcTime(rtc_text, sizeof(rtc_text));
}

bool focusTouchWasPressed() {
  const auto touch = M5.Touch.getDetail();
  const bool touch_down = touch.isPressed();
  const bool new_touch = touch_down && !previous_touch_down;
  previous_touch_down = touch_down;
  if (!new_touch) return false;

  const int32_t delta_x = touch.x - M5.Display.width() / 2;
  const int32_t delta_y = touch.y - M5.Display.height() / 2;
  constexpr int32_t kFocusTouchRadius = 145;
  return delta_x * delta_x + delta_y * delta_y <=
         kFocusTouchRadius * kFocusTouchRadius;
}

void drawFittedString(M5Canvas& gfx, const char* text, int32_t x, int32_t y,
                      int32_t max_width) {
  char source[64];
  copyDisplayField(source, sizeof(source), text);
  const size_t source_length = strlen(source);
  for (size_t keep = source_length;; --keep) {
    char output[64];
    const bool truncated = keep < source_length;
    const size_t suffix_length = truncated ? 3 : 0;
    const size_t copy_length =
        keep + suffix_length < sizeof(output) ? keep : sizeof(output) - 1;
    memcpy(output, source, copy_length);
    size_t output_length = copy_length;
    if (truncated && output_length + 3 < sizeof(output)) {
      output[output_length++] = '.';
      output[output_length++] = '.';
      output[output_length++] = '.';
    }
    output[output_length] = '\0';

    if (gfx.textWidth(output) <= max_width || keep == 0) {
      gfx.drawString(output, x, y);
      return;
    }
  }
}

void updateDisplayPower(uint32_t now_ms) {
  const uint32_t idle_ms = now_ms - last_interaction_ms;
  if (idle_ms >= kSleepAfterMs && !display_sleeping) {
    M5.Display.setBrightness(0);
    display_dimmed = true;
    display_sleeping = true;
  } else if (idle_ms >= kDimAfterMs && !display_dimmed) {
    M5.Display.setBrightness(20);
    display_dimmed = true;
  }
}

void drawUi(uint32_t now_ms, uint64_t now_us) {
  M5Canvas& gfx = canvas;
  const int width = gfx.width();
  const int height = gfx.height();
  const int cx = width / 2;
  const int cy = height / 2;
  const uint32_t accent = modeColor();
  const bool connected = hostConnected(now_ms);
  constexpr int8_t kPixelShift[] = {0, 1, 0, -1};
  const int shift = kPixelShift[(now_ms / 60000UL) % 4];

  gfx.fillScreen(TFT_BLACK);
  gfx.drawCircle(cx, cy, width / 2 - 3, 0x2124);
  gfx.drawCircle(cx, cy, width / 2 - 9, accent);

  const uint64_t elapsed_us = focus_timer.elapsedUs(now_us);
  const uint32_t elapsed_seconds = (elapsed_us / 1000000ULL) % 60ULL;
  const int arc_end = static_cast<int>(elapsed_seconds * 360U / 60U);
  if (focus_timer.isRunning() && arc_end > 3) {
    gfx.drawArc(cx, cy, width / 2 - 15, width / 2 - 24, 0, arc_end,
                accent);
  }

  gfx.setTextDatum(middle_center);
  gfx.setTextSize(1);
  gfx.setFont(&fonts::Font2);

  char status[64];
  snprintf(status, sizeof(status), "%s  BAT %d%%%s", connected ? "USB" : "LOCAL",
           battery_percent, charging ? "+" : "");
  gfx.setTextColor(connected ? TFT_GREEN : TFT_DARKGREY, TFT_BLACK);
  gfx.drawString(status, cx + shift, 52 - shift);

  gfx.setFont(&fonts::FreeSansBold24pt7b);
  gfx.setTextColor(TFT_WHITE, TFT_BLACK);
  gfx.drawString(connected ? host_time : rtc_text, cx + shift, 98 - shift);

  gfx.setFont(&fonts::FreeSansBold18pt7b);
  gfx.setTextColor(accent, TFT_BLACK);
  gfx.drawString(kModes[mode_index], cx + shift, 148 - shift);

  gfx.setFont(&fonts::Font2);
  gfx.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  drawFittedString(gfx, connected ? context_text : "MAC NOT CONNECTED",
                   cx + shift, 188 - shift, 300);
  gfx.setTextColor(TFT_DARKGREY, TFT_BLACK);
  drawFittedString(gfx, connected ? detail_text : "USB-C TO BEGIN", cx + shift,
                   213 - shift, 260);

  gfx.setTextColor(focus_timer.isRunning() ? accent : TFT_LIGHTGREY,
                   TFT_BLACK);
  gfx.drawString(focus_timer.isRunning() ? "FOCUS / RUNNING" : "FOCUS / PAUSED",
                 cx, 258);

  char elapsed_text[24];
  c152::formatElapsed(elapsed_us, elapsed_text, sizeof(elapsed_text));
  gfx.setFont(&fonts::FreeSansBold18pt7b);
  gfx.setTextColor(TFT_WHITE, TFT_BLACK);
  gfx.drawString(elapsed_text, cx, 301);

  gfx.setFont(&fonts::Font2);
  gfx.fillCircle(51, 350, 8, TFT_YELLOW);
  gfx.setTextColor(TFT_YELLOW, TFT_BLACK);
  gfx.drawString("MARK", 89, 350);
  gfx.fillCircle(width - 51, 350, 8, TFT_BLUE);
  gfx.setTextColor(TFT_BLUE, TFT_BLACK);
  gfx.drawString("MODE", width - 91, 350);

  gfx.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  gfx.drawString("TOUCH  FOCUS", cx, 389);
  snprintf(status, sizeof(status), "MARKS %lu", static_cast<unsigned long>(mark_count));
  gfx.setTextColor(TFT_DARKGREY, TFT_BLACK);
  gfx.drawString(status, cx, 416);

  if (toast_text[0] != '\0' && static_cast<int32_t>(toast_until_ms - now_ms) > 0) {
    gfx.fillRoundRect(cx - 92, cy - 24, 184, 48, 16, accent);
    gfx.setTextColor(TFT_BLACK, accent);
    gfx.drawString(toast_text, cx, cy);
  }

  gfx.pushSprite(0, 0);
}

}  // namespace

void setup() {
  c152::begin("10 / SOKKON");
  device_id = ESP.getEfuseMac() & 0xFFFFFFFFFFFFULL;
  do {
    boot_session = (static_cast<uint64_t>(esp_random()) << 32U) | esp_random();
  } while (boot_session == 0);
  M5.Speaker.end();
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
  previous_touch_down = M5.Touch.getDetail().isPressed();
  last_interaction_ms = millis();
  Serial.printf("SOKKON|READY|2|%012llX|%016llX\n",
                static_cast<unsigned long long>(device_id),
                static_cast<unsigned long long>(boot_session));
  drawUi(millis(), nowMicros());
}

void loop() {
  c152::update();
  readSerial();

  const uint32_t now_ms = millis();
  const uint64_t now_us = nowMicros();
  const bool mark_pressed = M5.BtnA.wasPressed();
  const bool mode_pressed = M5.BtnB.wasPressed();
  const bool was_sleeping = display_sleeping;
  bool focus_pressed = focusTouchWasPressed();
  if (focus_pressed && was_sleeping) {
    wakeDisplay(now_ms);
    focus_pressed = false;
  }

  if (mark_pressed) {
    if (hostConnected(now_ms)) {
      if (sendEvent(Intent::kCapture, now_ms, now_us) != 0) {
        showToast("MARK SENT", 650);
        startHaptic(1, 45, 30);
      } else {
        showToast("MAC BUSY", 1200);
        startHaptic(3, 80, 45);
      }
    } else {
      showToast("NOT SAVED", 1200);
      startHaptic(3, 80, 45);
    }
  } else if (mode_pressed) {
    mode_index = (mode_index + 1) % kModeCount;
    const bool queued = !hostConnected(now_ms) ||
                        sendEvent(Intent::kModeNext, now_ms, now_us) != 0;
    if (!queued) {
      showToast("MAC BUSY", 1200);
      startHaptic(3, 80, 45);
    } else {
      showToast(kModes[mode_index], 650);
      startHaptic(1, 85, 35);
    }
  } else if (focus_pressed) {
    focus_timer.toggle(now_us);
    const bool queued = !hostConnected(now_ms) ||
                        sendEvent(Intent::kFocusToggle, now_ms, now_us) != 0;
    if (!queued) {
      showToast("MAC BUSY", 1200);
      startHaptic(3, 80, 45);
    } else {
      showToast(focus_timer.isRunning() ? "FOCUS START" : "FOCUS PAUSE");
      if (focus_timer.isRunning()) {
        startHaptic(2, 75, 30);
      } else {
        startHaptic(1, 85, 75);
      }
    }
  }

  servicePendingEvents(now_ms);
  updateHaptic(now_ms);
  updateDisplayPower(now_ms);

  if (now_ms - last_sensor_ms >= 1000) {
    last_sensor_ms = now_ms;
    updateSensors();
  }
  if (canvas_ready && !display_sleeping && now_ms - last_draw_ms >= 100) {
    last_draw_ms = now_ms;
    drawUi(now_ms, now_us);
  }
  delay(2);
}
