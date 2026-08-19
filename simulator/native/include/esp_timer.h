#pragma once

#include "sim_runtime.hpp"

#include <cstdint>

inline int64_t esp_timer_get_time() {
  return static_cast<int64_t>(sokkon_sim::micros64());
}
