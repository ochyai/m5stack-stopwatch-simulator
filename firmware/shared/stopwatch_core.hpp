#pragma once

#include <stdint.h>

namespace c152 {

// Pure state machine. Timestamps are supplied by the caller, so this can be
// tested on a host and driven by esp_timer_get_time() on the device.
class StopwatchCore {
 public:
  void toggle(uint64_t now_us) {
    if (running_) {
      accumulated_us_ += deltaSinceStart(now_us);
      running_ = false;
    } else {
      started_at_us_ = now_us;
      running_ = true;
    }
  }

  void reset(uint64_t now_us = 0) {
    accumulated_us_ = 0;
    started_at_us_ = now_us;
    running_ = false;
  }

  uint64_t elapsedUs(uint64_t now_us) const {
    return accumulated_us_ + (running_ ? deltaSinceStart(now_us) : 0);
  }

  bool isRunning() const { return running_; }

 private:
  uint64_t deltaSinceStart(uint64_t now_us) const {
    return now_us >= started_at_us_ ? now_us - started_at_us_ : 0;
  }

  uint64_t accumulated_us_ = 0;
  uint64_t started_at_us_ = 0;
  bool running_ = false;
};

}  // namespace c152
