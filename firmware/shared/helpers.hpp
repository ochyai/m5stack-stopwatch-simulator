#pragma once

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

namespace c152 {

inline void formatElapsed(uint64_t elapsed_us, char* output,
                          size_t output_size) {
  const uint64_t total_centiseconds = elapsed_us / 10000ULL;
  const uint64_t centiseconds = total_centiseconds % 100ULL;
  const uint64_t total_seconds = total_centiseconds / 100ULL;
  const uint64_t seconds = total_seconds % 60ULL;
  const uint64_t total_minutes = total_seconds / 60ULL;
  const uint64_t minutes = total_minutes % 60ULL;
  const uint64_t hours = (total_minutes / 60ULL) % 100ULL;
  snprintf(output, output_size, "%02llu:%02llu:%02llu.%02llu",
           static_cast<unsigned long long>(hours),
           static_cast<unsigned long long>(minutes),
           static_cast<unsigned long long>(seconds),
           static_cast<unsigned long long>(centiseconds));
}

inline int clampPercent(int value) {
  if (value < 0) return 0;
  if (value > 100) return 100;
  return value;
}

}  // namespace c152
