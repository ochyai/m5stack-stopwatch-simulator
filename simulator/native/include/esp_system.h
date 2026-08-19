#pragma once

#include <cstdint>

inline uint32_t esp_random() {
  static uint32_t state = 0x6D2B79F5U;
  state ^= state << 13U;
  state ^= state >> 17U;
  state ^= state << 5U;
  return state;
}

class ESPClass {
 public:
  uint64_t getEfuseMac() const { return 0xA1B2C3D4E5F6ULL; }
};

inline ESPClass ESP;
